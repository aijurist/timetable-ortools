"""
export_for_legacy_scheduler.py
==============================
Export data from the new app DB into CSV files the old scheduler expects.

Exports:
  courses.csv          — one row per course_offering (teacher × course × semester)
  rooms.csv            — all rooms for the institution
  core_lab_mapping.csv — ONLY courses with override_lab_room_ids set (lab-pinned)

Usage (from backend/):
    python scripts/export_for_legacy_scheduler.py --term-id <uuid>
    python scripts/export_for_legacy_scheduler.py           # auto-detects latest term

The --out-dir defaults to E:/coding/grind_project/timetable_scheduler/data/exported/
A scheduler_exported.yaml is also written, copying the base config with updated paths.
Then run the old scheduler with:
    cd E:/coding/grind_project/timetable_scheduler
    python -m src.pipeline.cli --config data/exported/scheduler_exported.yaml
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras
import pandas as pd
import yaml

# --─ Paths ------------------------------------------------------------------

SCRIPT_DIR  = Path(__file__).parent.resolve()
BACKEND_DIR = SCRIPT_DIR.parent
LEGACY_ROOT = Path("E:/coding/grind_project/timetable_scheduler")
BASE_CONFIG = LEGACY_ROOT / "config" / "scheduler.yaml"
DEFAULT_OUT = LEGACY_ROOT / "data" / "exported"
# Use the existing room CSV from the old scheduler — it already has the correct
# Core-Lab / Laboratory distinction that the constraint logic relies on.
LEGACY_ROOMS_CSV = LEGACY_ROOT / "data" / "block_wise" / "new.csv"


# --─ DB connection ----------------------------------------------------------─

def _get_dsn() -> str:
    db_url = None
    env_file = BACKEND_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("DATABASE_URL="):
                db_url = line.split("=", 1)[1].strip()
                break
    db_url = db_url or os.getenv("DATABASE_URL", "")
    # asyncpg -> psycopg2
    dsn = (
        db_url
        .replace("postgresql+asyncpg://", "postgresql://")
        .replace("postgresql+psycopg2://", "postgresql://")
    )
    if not dsn:
        sys.exit("DATABASE_URL not found in .env or environment")
    return dsn


def _connect(dsn: str):
    return psycopg2.connect(dsn, cursor_factory=psycopg2.extras.RealDictCursor)


# --─ Metadata helpers --------------------------------------------------------

def _resolve_term(conn, term_id_str: str | None) -> tuple[str, str]:
    """Return (term_id, institution_id) as strings."""
    cur = conn.cursor()
    if term_id_str:
        cur.execute(
            "SELECT id, institution_id, name FROM academic_terms WHERE id = %s",
            (term_id_str,),
        )
    else:
        cur.execute(
            """SELECT id, institution_id, name
               FROM academic_terms
               ORDER BY start_date DESC NULLS LAST, created_at DESC
               LIMIT 1"""
        )
    row = cur.fetchone()
    if not row:
        sys.exit(f"Term not found: {term_id_str or '(auto)'}")
    print(f"Term: {row['name']}  ({row['id']})")
    return str(row["id"]), str(row["institution_id"])


# --─ Rooms ------------------------------------------------------------------─

def export_rooms(conn, institution_id: str, out_dir: Path) -> Path:
    """Use the existing old-scheduler room CSV directly.

    The old scheduler's data/block_wise/new.csv already has the correct
    room_type distinction (Core-Lab vs Laboratory) that the constraint
    logic depends on.  Exporting from our DB would lose that nuance.
    """
    import shutil
    out = out_dir / "rooms.csv"
    shutil.copy2(LEGACY_ROOMS_CSV, out)
    df = pd.read_csv(out)
    labs = df[df["is_lab"] == 1]
    core = (labs["room_type"] == "Core-Lab").sum()
    lab_gen = (labs["room_type"].str.contains("laboratory", case=False, na=False) &
               (labs["room_type"] != "Core-Lab")).sum()
    print(f"  rooms.csv            -> {len(df)} rooms  (core_lab={core}, computer_lab={lab_gen})")
    return out


# --─ Courses ----------------------------------------------------------------─

def export_courses(conn, term_id: str, out_dir: Path) -> Path:
    """
    One row per TeachingAssignment.
    TAs are the real source of course data (1078 rows vs 12 solver offerings).
    Semester is resolved from target_course_demand -> scheduling_targets where available,
    otherwise derived heuristically from the course code pattern (XX23Y...).
    """
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            ta.id                                    AS id,
            c.code                                   AS course_code,
            c.name                                   AS course_name,
            c.session_type                           AS session_type,
            c.weekly_hours,
            c.structure,
            COALESCE(f.name, 'TBD')                  AS teacher,
            COALESCE(f.staff_code, '')               AS staff_code,
            d_teach.name                             AS teaching_dept,
            -- Student dept: if TA has explicit dept, use it; else fall back to teaching dept
            COALESCE(d_stud.name, d_teach.name)      AS student_dept,
            ta.override_lab_room_ids,
            ta.override_room_ids,
            ta.study_semester                        AS semester,
            ta.study_year                            AS academic_year
        FROM teaching_assignments ta
        JOIN  courses     c      ON c.id  = ta.course_id
        LEFT JOIN faculty f      ON f.id  = ta.faculty_id
        LEFT JOIN departments d_teach ON d_teach.id = ta.department_id
        -- student_dept comes from the first scheduling_target linked via target_course_demand
        LEFT JOIN LATERAL (
            SELECT st.department_id
            FROM target_course_demand cd
            JOIN scheduling_targets st ON st.id = cd.target_id
            WHERE cd.course_id = ta.course_id
              AND cd.academic_term_id = ta.academic_term_id
            ORDER BY st.study_semester
            LIMIT 1
        ) st_sub ON true
        LEFT JOIN departments d_stud ON d_stud.id = st_sub.department_id
        WHERE ta.academic_term_id = %s
        ORDER BY COALESCE(d_stud.name, d_teach.name) NULLS LAST, c.code
        """,
        (term_id,),
    )
    rows = [dict(r) for r in cur.fetchall()]

    # Build student-count lookup: (dept_name, semester) -> total size
    size_map = _load_size_map(conn, term_id)

    records = []
    for d in rows:
        lec, prac, tut = _hours(d)
        stype = (d.get("session_type") or "THEORY").upper()
        has_lab_pin = bool(d.get("override_lab_room_ids"))

        if stype == "LAB":
            lab_status = "Lab-Required-With-Assignment" if has_lab_pin else "Lab-Required-No-Assignment"
        else:
            lab_status = "No-Lab-Required"

        sem = int(d.get("semester") or 0) or 1
        acyr = int(d.get("academic_year") or 0) or ((sem + 1) // 2)
        raw_dept  = d.get("student_dept") or ""
        short_dept = _short_dept(raw_dept)
        student_count = size_map.get((raw_dept, sem), size_map.get((short_dept, sem), 70))
        if student_count == 0:
            student_count = 70

        records.append({
            "id":                   str(d["id"]),
            "student_count":        student_count,
            "academic_year":        acyr,
            "semester":             sem,
            "teacher":              d["teacher"],
            "staff_code":           d.get("staff_code") or "",
            "course_code":          d["course_code"],
            "course_name":          d["course_name"],
            "course_type":          _map_course_type(stype),
            "lecture_hours":        lec,
            "practical_hours":      prac,
            "tutorial_hours":       tut,
            # Use short dept name so YAML config keys (day pattern, shift, block priority) match
            "department":           short_dept,
            "student_dept":         short_dept,
            "teaching_dept":        _short_dept(d.get("teaching_dept") or ""),
            "required_room_type":   "lab" if stype == "LAB" else "standard",
            "lab_assignment_status": lab_status,
        })

    df = pd.DataFrame(records) if records else pd.DataFrame()
    out = out_dir / "courses.csv"
    df.to_csv(out, index=False)
    print(f"  courses.csv          -> {len(df)} offerings")
    return out


def _derive_semester(course_code: str) -> int:
    """VIT code pattern XX23YNN — 5th char (index 4) is the semester number."""
    if len(course_code) >= 5 and course_code[4].isdigit():
        sem = int(course_code[4])
        return sem if sem > 0 else 1
    return 1


def _hours(row: dict) -> tuple[int, int, int]:
    """Derive lecture/practical/tutorial hours from structure or session_type fallback."""
    struct = row.get("structure") or {}
    if isinstance(struct, str):
        try:
            struct = json.loads(struct)
        except Exception:
            struct = {}
    lec  = int(struct.get("L", 0) or 0)
    prac = int(struct.get("P", 0) or 0)
    tut  = int(struct.get("T", 0) or 0)
    if lec == 0 and prac == 0 and tut == 0:
        wh    = int(row.get("weekly_hours") or 3)
        stype = (row.get("session_type") or "THEORY").upper()
        if stype == "LAB":
            prac = wh
        elif stype == "TUTORIAL":
            tut = wh
        else:
            lec = wh
    return lec, prac, tut


def _map_course_type(session_type: str) -> str:
    return {"LAB": "P", "TUTORIAL": "T", "THEORY": "T"}.get(session_type, "T")


# Maps full DB department names to the short names the old scheduler uses in its YAML config.
_DEPT_SHORT = {
    "Department of Artificial Intelligence and Data Science":           "Artificial Intelligence & Data Science",
    "Department of Artificial Intelligence and Machine Learning":       "Artificial Intelligence & Machine Learning",
    "Department of Computer Science and Engineering":                   "Computer Science & Engineering",
    "Department of Information Technology":                             "Information Technology",
    "Department of Electronics and Communication Engineering":          "Electronics & Communication Engineering",
    "Department of Electrical and Electronics Engineering":             "Electrical & Electronics Engineering",
    "Department of Mechanical Engineering":                             "Mechanical Engineering",
    "Department of Civil Engineering":                                  "Civil Engineering",
    "Department of Biotechnology":                                      "Biotechnology",
    "Department of Biomedical Engineering":                             "Biomedical Engineering",
    "Department of Chemical Engineering":                               "Chemical Engineering",
    "Department of Food Technology":                                    "Food Technology",
    "Department of Aeronautical Engineering":                           "Aeronautical Engineering",
    "Department of Automobile Engineering":                             "Automobile Engineering",
    "Department of Robotics and Automation":                            "Robotics & Automation",
    "Department of Mechatronics Engineering":                           "Mechatronics Engineering",
    "Department of Computer Science and Business Systems":              "Computer Science & Business Systems",
    "Department of Computer Science and Design":                        "Computer Science & Design",
    "Department of Computer Science and Engineering (Cyber Security)":  "Computer Science & Engineering (Cyber Security)",
}

def _short_dept(name: str) -> str:
    """Convert full DB department name to old-scheduler short form."""
    return _DEPT_SHORT.get(name, name)


def _load_size_map(conn, term_id: str) -> dict[tuple[str, int], int]:
    """(dept_name, semester) -> per-section student count for this term.

    Uses class_count to derive per-section size: ceil(total / class_count).
    Falls back to 70 when not available.
    """
    import math
    cur = conn.cursor()
    cur.execute(
        """
        SELECT d.name AS dept_name, st.study_semester,
               SUM(st.size)        AS total,
               SUM(st.class_count) AS classes
        FROM scheduling_targets st
        JOIN departments d ON d.id = st.department_id
        WHERE st.academic_term_id = %s
          AND st.study_semester IS NOT NULL
        GROUP BY d.name, st.study_semester
        """,
        (term_id,),
    )
    result = {}
    for r in cur.fetchall():
        total   = int(r["total"] or 0)
        classes = int(r["classes"] or 0)
        if classes > 0:
            per_section = math.ceil(total / classes)
        else:
            per_section = total or 70
        result[(r["dept_name"], int(r["study_semester"]))] = per_section
    return result


# --─ Core lab mapping --------------------------------------------------------

def export_core_lab_mapping(conn, term_id: str, out_dir: Path) -> Path:
    """
    Build core_lab_mapping.csv merging both pin sources (priority: TA override > course default).

    Source 1 — TA-level:  teaching_assignments.override_lab_room_ids
      An explicit room assignment set by the coordinator for a specific faculty×course.

    Source 2 — Course-level: courses.lab_preferred_room_ids
      The default lab room(s) for a course when no TA-level override exists.
      Included for every TA whose course has this set (linked via the TA's department
      so the (course_code, department) key is correct for the old scheduler).

    Output columns (matches CoreMappingSimplified_StudentDept.csv):
      course_code | department | total_labs | lab_1..lab_5 | course_name
    """
    def _parse_ids(val) -> list[str]:
        if val is None:
            return []
        if isinstance(val, list):
            return [str(v) for v in val if v]
        try:
            return [str(v) for v in json.loads(val) if v]
        except Exception:
            return []

    cur = conn.cursor()

    # --- Source 1: TA-level overrides ---
    cur.execute(
        """
        SELECT
            c.code  AS course_code,
            c.name  AS course_name,
            d.name  AS department,
            ta.override_lab_room_ids   AS lab_room_ids,
            'ta'                       AS source
        FROM teaching_assignments ta
        JOIN  courses     c ON c.id  = ta.course_id
        LEFT JOIN departments d ON d.id = ta.department_id
        WHERE ta.academic_term_id = %s
        ORDER BY c.code, d.name
        """,
        (term_id,),
    )
    ta_rows = [dict(r) for r in cur.fetchall()]

    # --- Source 2: Course-level pins (for courses whose TAs have no override) ---
    # Join TAs to courses so we get (course_code, department) keyed correctly.
    # No DISTINCT — json columns don't support equality; deduplicate in Python below.
    cur.execute(
        """
        SELECT
            c.code                     AS course_code,
            c.name                     AS course_name,
            d.name                     AS department,
            c.lab_preferred_room_ids   AS lab_room_ids,
            'course'                   AS source
        FROM teaching_assignments ta
        JOIN  courses     c ON c.id  = ta.course_id
        LEFT JOIN departments d ON d.id = ta.department_id
        WHERE ta.academic_term_id = %s
          AND c.lab_preferred_room_ids IS NOT NULL
        ORDER BY c.code, d.name
        """,
        (term_id,),
    )
    # Deduplicate in Python (json columns can't use DISTINCT in SQL)
    _seen_course: set[tuple[str, str]] = set()
    course_rows = []
    for r in cur.fetchall():
        k = (r["course_code"], r["department"] or "")
        if k not in _seen_course:
            _seen_course.add(k)
            course_rows.append(dict(r))

    # Merge: TA override wins; course-level fills gaps.
    # Key = (course_code, department)
    merged: dict[tuple[str, str], dict] = {}

    # First pass: course-level (lower priority)
    for r in course_rows:
        ids = _parse_ids(r["lab_room_ids"])
        if not ids:
            continue
        key = (r["course_code"], r["department"] or "")
        merged[key] = {**r, "lab_room_ids": ids}

    # Second pass: TA-level overrides (higher priority — overwrites course-level)
    for r in ta_rows:
        ids = _parse_ids(r["lab_room_ids"])
        if not ids:
            continue
        key = (r["course_code"], r["department"] or "")
        merged[key] = {**r, "lab_room_ids": ids}  # TA wins

    if not merged:
        print("  core_lab_mapping.csv -> 0 rows (no lab pins found)")
        cols = ["course_code", "department", "total_labs",
                "lab_1", "lab_2", "lab_3", "lab_4", "lab_5", "course_name"]
        pd.DataFrame(columns=cols).to_csv(out_dir / "core_lab_mapping.csv", index=False)
        return out_dir / "core_lab_mapping.csv"

    # Bulk-resolve all room UUIDs -> code + tag info
    all_ids = {rid for row in merged.values() for rid in row["lab_room_ids"]}
    room_code: dict[str, str] = {}
    room_is_core: dict[str, bool] = {}
    if all_ids:
        ph = ",".join(["%s"] * len(all_ids))
        cur.execute(
            f"SELECT id::text, code, tags FROM rooms WHERE id::text IN ({ph})",
            list(all_ids),
        )
        for r in cur.fetchall():
            room_code[r["id"]] = r["code"]
            tags = r["tags"] or []
            room_is_core[r["id"]] = "CORE_LAB" in tags

    # Dynamic column count: the old scheduler reads ALL lab_* columns, so export
    # as many as the largest room list (min 5 for backwards compat).
    max_rooms = max((len(r["lab_room_ids"]) for r in merged.values()), default=5)
    max_cols  = max(max_rooms, 5)

    records = []
    ta_count = 0
    course_count = 0
    skipped_comp = 0
    for (course_code, dept), row in sorted(merged.items()):
        ids = row["lab_room_ids"]
        # Keep only CORE_LAB rooms — COMPUTER_LAB rooms must not be in the
        # core_lab_mapping because the CoreLabMappingConstraint would force
        # those sessions away from all other rooms, making it infeasible when
        # lab slots are tight.  Computer-lab courses use the open pool instead.
        core_ids = [rid for rid in ids if room_is_core.get(rid, False)]
        if not core_ids:
            skipped_comp += 1
            continue  # all rooms are COMPUTER_LAB — skip entry, use open pool
        names = [room_code.get(rid, rid) for rid in core_ids]
        ids   = core_ids  # repoint for total_labs count
        # Pad with None to max_cols so every row has the same width
        names += [None] * (max_cols - len(names))
        rec: dict = {
            "course_code": course_code,
            "department":  dept,
            "total_labs":  len(ids),
        }
        for i, name in enumerate(names, start=1):
            rec[f"lab_{i}"] = name
        rec["course_name"] = row["course_name"]
        records.append(rec)
        if row["source"] == "ta":
            ta_count += 1
        else:
            course_count += 1

    df = pd.DataFrame(records)
    out = out_dir / "core_lab_mapping.csv"
    df.to_csv(out, index=False)
    print(f"  core_lab_mapping.csv -> {len(df)} core-lab-pinned courses "
          f"(ta_override={ta_count}, course_default={course_count}, "
          f"skipped_computer_lab_only={skipped_comp})")
    return out


# --─ YAML generation --------------------------------------------------------─

def write_yaml(out_dir: Path, courses: Path, rooms: Path, lab_map: Path) -> None:
    if not BASE_CONFIG.exists():
        print(f"  (base config not found at {BASE_CONFIG}; skipping yaml)")
        return

    with open(BASE_CONFIG) as f:
        cfg = yaml.safe_load(f)

    cfg["paths"]["courses_csv"]          = courses.as_posix()
    cfg["paths"]["rooms_csv"]            = rooms.as_posix()
    cfg["paths"]["core_lab_mapping_csv"] = lab_map.as_posix()

    # Disable fixed_schedule_lock — it references the previous semester's room
    # occupancy and blocks rooms/slots that were used in 2025-12. For a fresh
    # semester export we have no prior schedule to lock against.
    for domain in ("cross_system", "lab", "theory"):
        section = cfg.get("constraints", {}).get(domain, {})
        if "fixed_schedule_lock" in section:
            section["fixed_schedule_lock"]["enabled"] = False

    out = out_dir / "scheduler_exported.yaml"
    with open(out, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    print(f"  scheduler_exported.yaml written -> {out}")


# --─ Entry point ------------------------------------------------------------─

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--term-id", default=None, help="Academic term UUID (auto-detects latest)")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    conn = _connect(_get_dsn())
    try:
        term_id, inst_id = _resolve_term(conn, args.term_id)
        print(f"Institution: {inst_id}\nOutput: {out_dir}\n")

        rooms_csv  = export_rooms(conn, inst_id, out_dir)
        course_csv = export_courses(conn, term_id, out_dir)
        lab_csv    = export_core_lab_mapping(conn, term_id, out_dir)

        write_yaml(out_dir, course_csv, rooms_csv, lab_csv)

        print("\n-- Done --")
        print(f"cd E:/coding/grind_project/timetable_scheduler")
        print(f"python -m src.pipeline.cli --config {(out_dir / 'scheduler_exported.yaml').as_posix()}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
