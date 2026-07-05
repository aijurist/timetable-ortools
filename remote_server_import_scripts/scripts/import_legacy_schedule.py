"""
import_legacy_schedule.py
=========================
Import the legacy CP-SAT scheduler's CSV output into the app's scheduled_sessions table.

Usage (from backend/):
    # Auto-detect CSVs under <output_dir>/csv/
    python scripts/import_legacy_schedule.py --scenario-id <uuid> --output-dir <path>

    # Explicit CSVs + merge a second run (e.g. ECE sem5 from a separate solve):
    python scripts/import_legacy_schedule.py \\
        --scenario-id <uuid> \\
        --lab-csv    E:/coding/grind_project/timetable_scheduler/output/2026-06-10_23-23-56/csv/lab_schedule.csv \\
        --theory-csv E:/coding/grind_project/timetable_scheduler/output/2026-06-10_23-23-56/csv/theory_schedule.csv \\
        --extra-lab-csv    E:/coding/grind_project/timetable_scheduler/output/2026-06-10_23-24-56/csv/lab_schedule.csv \\
        --extra-theory-csv E:/coding/grind_project/timetable_scheduler/output/2026-06-10_23-24-56/csv/theory_schedule.csv

    # Dry run — print what would be inserted, no DB writes:
    python scripts/import_legacy_schedule.py --scenario-id <uuid> ... --dry-run

Slot code convention
--------------------
  Theory : "{DAY_ABBR}_T{SLOT_INDEX}"  e.g. "MON_T2"  (Monday slot index 2, 10:00-10:50)
  Lab    : "{DAY_ABBR}_L{SESSION_NUM}" e.g. "WED_L3"  (Wednesday lab session L3, 11:50-13:20)

  These codes are written/merged into the scenario's TimeGrid so the UI can resolve
  slot codes to actual times.

Column mapping from legacy scheduler CSVs
------------------------------------------
  course_instance_id  -> ScheduledSession.course_id  (= TeachingAssignment.id UUID as string)
  room_number         -> Room.room_number lookup -> Room.id UUID stored as string
  teacher_name / staff_code -> Faculty lookup -> Faculty.id UUID stored as string
  offering_id         -> CourseOffering matched via (course_id, faculty_id) — best effort, NULL if unmatched
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from pathlib import Path

import psycopg2
import psycopg2.extras
import pandas as pd

SCRIPT_DIR  = Path(__file__).parent.resolve()
BACKEND_DIR = SCRIPT_DIR.parent

# ── Slot time definitions (matches legacy scheduler config/scheduler.yaml) ────
THEORY_TIMES: list[tuple[str, str]] = [
    ("08:00", "08:50"),
    ("09:00", "09:50"),
    ("10:00", "10:50"),
    ("11:00", "11:50"),
    ("12:00", "12:50"),
    ("13:20", "14:10"),
    ("14:10", "15:00"),
    ("15:00", "15:50"),
    ("16:00", "16:50"),
    ("17:00", "17:50"),
    ("18:00", "18:50"),
]
LAB_TIMES: dict[str, tuple[str, str]] = {
    "L1": ("08:00", "09:40"),
    "L2": ("10:00", "11:40"),
    "L3": ("11:50", "13:20"),
    "L4": ("13:20", "15:00"),
    "L5": ("15:00", "16:40"),
    "L6": ("17:00", "18:40"),
}
CANONICAL_DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT"]
_DAY_ABBR: dict[str, str] = {
    "monday": "MON", "tuesday": "TUE",
    "wednesday": "WED", "wed": "WED",
    "thursday": "THU", "thur": "THU",
    "friday": "FRI", "fri": "FRI",
    "saturday": "SAT",
}


def _day_abbr(day: str) -> str:
    return _DAY_ABBR.get(str(day).lower().strip(), str(day).upper()[:3])


def build_slot_code(day: str, slot_type: str, slot_ref: str | int) -> str:
    abbr = _day_abbr(day)
    if slot_type == "T":
        return f"{abbr}_T{slot_ref}"
    num = str(slot_ref).upper().lstrip("L")
    return f"{abbr}_L{num}"


def build_time_grid_slots() -> dict:
    """Full slots dict for a TimeGrid: all 6 days × 11 theory + 6 lab sessions."""
    slots: dict = {}
    for abbr in CANONICAL_DAYS:
        for idx, (start, end) in enumerate(THEORY_TIMES):
            period = "lunch" if idx == 4 else ("morning" if idx < 4 else "afternoon")
            slots[f"{abbr}_T{idx}"] = {
                "day": abbr, "start": start, "end": end,
                "period": period, "type": "theory", "slot_index": idx,
            }
        for name, (start, end) in LAB_TIMES.items():
            num = name[1:]
            period = "afternoon" if int(num) >= 4 else "morning"
            slots[f"{abbr}_L{num}"] = {
                "day": abbr, "start": start, "end": end,
                "period": period, "type": "lab", "session_name": name,
            }
    return slots


# ── DB helpers ─────────────────────────────────────────────────────────────────

def _get_dsn() -> str:
    db_url: str | None = None
    env_file = BACKEND_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("DATABASE_URL="):
                db_url = line.split("=", 1)[1].strip()
                break
    db_url = db_url or os.getenv("DATABASE_URL", "")
    dsn = (
        db_url
        .replace("postgresql+asyncpg://", "postgresql://")
        .replace("postgresql+psycopg2://", "postgresql://")
    )
    if not dsn:
        sys.exit("DATABASE_URL not found in backend/.env or $DATABASE_URL")
    return dsn


def build_room_lookup(cur) -> dict[str, str]:
    # legacy CSV column "room_number" == rooms.code in the app DB
    cur.execute("SELECT id, code FROM rooms WHERE code IS NOT NULL")
    return {row["code"].strip(): str(row["id"]) for row in cur.fetchall()}


def build_ta_course_lookup(cur, term_id: str) -> dict[str, str]:
    """ta_uuid (str) -> course_uuid (str).
    The solver writes Course.id into ScheduledSession.course_id — not TA.id.
    Without this, get_by_scenario's Course JOIN never matches and course_code/
    course_name/department_name all come back NULL.
    """
    cur.execute(
        "SELECT id::text AS ta_id, course_id::text AS course_id FROM teaching_assignments WHERE academic_term_id = %s",
        (term_id,)
    )
    return {row["ta_id"]: row["course_id"] for row in cur.fetchall()}


def build_faculty_lookup(cur) -> dict[str, str]:
    # faculty.name = full display name; faculty.staff_code = short code
    cur.execute("SELECT id, name, staff_code FROM faculty")
    lookup: dict[str, str] = {}
    for row in cur.fetchall():
        if row["name"]:
            lookup[row["name"].strip().lower()] = str(row["id"])
        if row["staff_code"]:
            lookup[row["staff_code"].strip().lower()] = str(row["id"])
    return lookup


_UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE,
)

def _is_uuid(s: str) -> bool:
    return bool(_UUID_RE.match(s))


def build_course_lookup(cur) -> dict[str, str]:
    """course_code (upper) → course_uuid — for new-format CSVs where course_instance_id is an integer."""
    cur.execute("SELECT id, code FROM courses WHERE code IS NOT NULL")
    return {row["code"].strip().upper(): str(row["id"]) for row in cur.fetchall()}


def build_offering_lookup(cur, term_id: str) -> dict[tuple[str, str], str]:
    """(ta_course_id_str, faculty_uuid_str) -> CourseOffering UUID (str), best-effort."""
    cur.execute(
        """SELECT co.id       AS co_id,
                  co.course_id  AS course_id,
                  co.faculty_id AS faculty_id
           FROM course_offerings co
           JOIN offering_buckets ob ON ob.id = co.bucket_id
           WHERE ob.academic_term_id = %s""",
        (term_id,)
    )
    lookup: dict[tuple[str, str], str] = {}
    for row in cur.fetchall():
        key = (str(row["course_id"]), str(row["faculty_id"] or ""))
        if key not in lookup:
            lookup[key] = str(row["co_id"])
    return lookup


def get_scenario_info(cur, scenario_id: str) -> tuple[str, str | None]:
    cur.execute(
        "SELECT academic_term_id, selected_time_grid_id FROM scenarios WHERE id = %s",
        (scenario_id,)
    )
    row = cur.fetchone()
    if not row:
        raise ValueError(f"Scenario {scenario_id!r} not found in DB")
    return str(row["academic_term_id"]), (str(row["selected_time_grid_id"]) if row["selected_time_grid_id"] else None)


def ensure_time_grid(cur, scenario_id: str, term_id: str, existing_tg_id: str | None, dry_run: bool) -> str:
    """
    If the scenario already has a TimeGrid, merge new slot codes into it.
    Otherwise create a new TimeGrid and attach it to the scenario.
    """
    new_slots = build_time_grid_slots()

    if existing_tg_id:
        cur.execute("SELECT slots FROM time_grids WHERE id = %s", (existing_tg_id,))
        row = cur.fetchone()
        existing = row["slots"] if row else {}
        merged   = {**new_slots, **existing}   # existing slots win on key collision
        added    = set(merged) - set(existing)
        print(f"  TimeGrid {existing_tg_id[:8]}... exists — {len(added)} new slot codes added")
        if not dry_run and added:
            cur.execute(
                "UPDATE time_grids SET slots = %s, updated_at = NOW() WHERE id = %s",
                (json.dumps(merged), existing_tg_id)
            )
        return existing_tg_id

    new_id = str(uuid.uuid4())
    print(f"  Creating TimeGrid {new_id[:8]}... ({len(new_slots)} slots)")
    if not dry_run:
        cur.execute(
            """INSERT INTO time_grids (id, academic_term_id, name, slots, is_active, created_at, updated_at)
               VALUES (%s, %s, %s, %s, true, NOW(), NOW())""",
            (new_id, term_id, "Legacy Scheduler Import", json.dumps(new_slots))
        )
        cur.execute(
            "UPDATE scenarios SET selected_time_grid_id = %s WHERE id = %s",
            (new_id, scenario_id)
        )
    return new_id


# ── Row processing ─────────────────────────────────────────────────────────────

def _resolve_faculty(teacher: str, staff_code: str, faculty_lk: dict) -> str | None:
    return (
        faculty_lk.get(teacher.strip().lower()) or
        faculty_lk.get(staff_code.strip().lower()) or
        None
    )


def _is_blank(val) -> bool:
    return val is None or (isinstance(val, float) and str(val) == "nan") or str(val).strip() in ("", "nan", "NaN")


def process_lab_df(
    df: pd.DataFrame,
    room_lk: dict,
    faculty_lk: dict,
    offering_lk: dict,
    ta_course_lk: dict,
    scenario_id: str,
    miss_rooms: set,
    miss_faculty: set,
    course_lk: dict | None = None,
) -> list[dict]:
    rows: list[dict] = []
    for _, r in df.iterrows():
        room_num = str(r.get("room_number") or "").strip()
        room_id  = room_lk.get(room_num)
        if not room_id:
            miss_rooms.add(room_num or "(empty)")
            continue

        teacher  = str(r.get("teacher_name") or "").strip()
        scode    = str(r.get("staff_code")   or "").strip()
        fac_id   = _resolve_faculty(teacher, scode, faculty_lk)
        if not fac_id:
            miss_faculty.add(teacher or scode or "(empty)")
            continue

        day     = str(r.get("day") or "").lower().strip()
        session = str(r.get("session_name") or "").strip()
        slot    = build_slot_code(day, "L", session)
        ta_id   = str(r.get("course_instance_id") or "")

        if _is_uuid(ta_id):
            # Old format: course_instance_id is a TA UUID
            course_id = ta_course_lk.get(ta_id, ta_id)
        else:
            # New format: course_instance_id is an integer — look up via course_code
            code = str(r.get("course_code") or "").strip().upper()
            course_id = (course_lk or {}).get(code, "")
            if not course_id:
                miss_rooms.add(f"course_code={code}")
                continue

        batch_num = r.get("batch_number")
        batch_sfx = f"_B{int(batch_num)}" if not _is_blank(batch_num) else ""
        session_id = f"{ta_id}_{slot}{batch_sfx}"

        rows.append({
            "id":        str(uuid.uuid4()),
            "scenario_id": scenario_id,
            "session_id":  session_id,
            "course_id":   course_id,
            "_ta_id":      ta_id,
            "faculty_id":  fac_id,
            "room_id":     room_id,
            "slot_code":   slot,
            "is_pinned":   False,
            "offering_id": None,
        })
    return rows


def process_theory_df(
    df: pd.DataFrame,
    room_lk: dict,
    faculty_lk: dict,
    offering_lk: dict,
    ta_course_lk: dict,
    scenario_id: str,
    miss_rooms: set,
    miss_faculty: set,
    course_lk: dict | None = None,
) -> list[dict]:
    rows: list[dict] = []
    for _, r in df.iterrows():
        room_num = str(r.get("room_number") or "").strip()
        room_id  = room_lk.get(room_num)
        if not room_id:
            miss_rooms.add(room_num or "(empty)")
            continue

        teacher = str(r.get("teacher_name") or "").strip()
        scode   = str(r.get("staff_code")   or "").strip()
        fac_id  = _resolve_faculty(teacher, scode, faculty_lk)
        if not fac_id:
            miss_faculty.add(teacher or scode or "(empty)")
            continue

        day     = str(r.get("day") or "").lower().strip()
        slot_raw = r.get("slot_index")
        if _is_blank(slot_raw):
            continue
        slot   = build_slot_code(day, "T", int(slot_raw))
        ta_id  = str(r.get("course_instance_id") or "")

        if _is_uuid(ta_id):
            course_id = ta_course_lk.get(ta_id, ta_id)
        else:
            code = str(r.get("course_code") or "").strip().upper()
            course_id = (course_lk or {}).get(code, "")
            if not course_id:
                miss_rooms.add(f"course_code={code}")
                continue

        session_num = r.get("session_number")
        seq = int(session_num) if not _is_blank(session_num) else 1
        session_id = f"{ta_id}_{slot}_S{seq}"

        rows.append({
            "id":        str(uuid.uuid4()),
            "scenario_id": scenario_id,
            "session_id":  session_id,
            "course_id":   course_id,
            "_ta_id":      ta_id,
            "faculty_id":  fac_id,
            "room_id":     room_id,
            "slot_code":   slot,
            "is_pinned":   False,
            "offering_id": None,
        })
    return rows


def bulk_fill_offering_ids(
    cur,
    rows: list[dict],
    term_id: str,
    offering_lk: dict | None = None,
) -> int:
    """
    Fill offering_id on each row.

    UUID ta_id path  (old CSV format): SQL lookup via teaching_assignments.id
    Integer ta_id path (new CSV format): direct lookup via offering_lk[(course_id, faculty_id)]
    """
    uuid_rows    = [r for r in rows if r.get("_ta_id") and _is_uuid(r["_ta_id"])]
    nonuuid_rows = [r for r in rows if r.get("_ta_id") and not _is_uuid(r["_ta_id"])]

    filled = 0

    # ── UUID path ──────────────────────────────────────────────────────────────
    if uuid_rows:
        ta_ids = list({r["_ta_id"] for r in uuid_rows})
        cur.execute(
            """SELECT ta.id::text AS ta_id,
                      co.id::text AS offering_id
               FROM teaching_assignments ta
               LEFT JOIN course_offerings co
                 ON co.course_id  = ta.course_id
                AND co.faculty_id = ta.faculty_id
               WHERE ta.id = ANY(%s::uuid[])
                 AND ta.academic_term_id = %s""",
            (ta_ids, term_id),
        )
        ta_to_offering: dict[str, str] = {}
        for row in cur.fetchall():
            if row["offering_id"] and row["ta_id"] not in ta_to_offering:
                ta_to_offering[row["ta_id"]] = row["offering_id"]

        for r in uuid_rows:
            oid = ta_to_offering.get(r["_ta_id"])
            if oid:
                r["offering_id"] = oid
                filled += 1

    # ── Non-UUID path (integer course_instance_id) ────────────────────────────
    if nonuuid_rows and offering_lk:
        for r in nonuuid_rows:
            key = (r["course_id"], r["faculty_id"] or "")
            oid = offering_lk.get(key)
            if oid:
                r["offering_id"] = oid
                filled += 1

    return filled


def insert_sessions(cur, rows: list[dict], scenario_id: str, dry_run: bool) -> None:
    if not rows:
        print("  No rows to insert.")
        return

    if dry_run:
        print(f"  [DRY RUN] Would clear + insert {len(rows)} sessions. Sample:")
        for r in rows[:5]:
            print(f"    {r['slot_code']:<10}  course={r['course_id'][:8]}...  room={r['room_id'][:8]}...  fac={r['faculty_id'][:8]}...")
        return

    cur.execute("DELETE FROM scheduled_sessions WHERE scenario_id = %s", (scenario_id,))

    psycopg2.extras.execute_values(
        cur,
        """INSERT INTO scheduled_sessions
               (id, scenario_id, session_id, course_id, faculty_id, room_id,
                slot_code, is_pinned, offering_id, created_at)
           VALUES %s""",
        [
            (
                r["id"], r["scenario_id"], r["session_id"],
                r["course_id"], r["faculty_id"], r["room_id"],
                r["slot_code"], r["is_pinned"], r["offering_id"],
            )
            for r in rows
        ],
        template="(%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())",
    )
    print(f"  Inserted {len(rows)} scheduled_sessions")


# ── Entry point ────────────────────────────────────────────────────────────────

def _load_csv_pair(lab_path: Path, theory_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    lab_df    = pd.read_csv(lab_path)    if lab_path.exists()    else pd.DataFrame()
    theory_df = pd.read_csv(theory_path) if theory_path.exists() else pd.DataFrame()
    return lab_df, theory_df


def main() -> None:
    ap = argparse.ArgumentParser(description="Import legacy scheduler CSVs into app DB")
    ap.add_argument("--scenario-id",  required=True,
                    help="UUID of the app Scenario to write sessions into")
    ap.add_argument("--output-dir",   default=None,
                    help="Scheduler output dir; auto-finds csv/lab_schedule.csv + csv/theory_schedule.csv")
    ap.add_argument("--lab-csv",      default=None, help="Primary lab_schedule.csv")
    ap.add_argument("--theory-csv",   default=None, help="Primary theory_schedule.csv")
    ap.add_argument("--extra-lab-csv",    default=None,
                    help="Extra lab_schedule.csv to merge in (e.g. ECE sem5 separate run)")
    ap.add_argument("--extra-theory-csv", default=None, help="Extra theory_schedule.csv to merge in")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print plan without writing to DB")
    args = ap.parse_args()

    # ── Resolve CSV paths ──────────────────────────────────────────────────────
    if args.output_dir:
        base = Path(args.output_dir)
        lab_path    = base / "csv" / "lab_schedule.csv"
        theory_path = base / "csv" / "theory_schedule.csv"
    elif args.lab_csv and args.theory_csv:
        lab_path    = Path(args.lab_csv)
        theory_path = Path(args.theory_csv)
    else:
        ap.error("Provide --output-dir OR both --lab-csv and --theory-csv")
        return  # unreachable but satisfies type checkers

    lab_df, theory_df = _load_csv_pair(lab_path, theory_path)

    if args.extra_lab_csv:
        p = Path(args.extra_lab_csv)
        if p.exists():
            lab_df = pd.concat([lab_df, pd.read_csv(p)], ignore_index=True)
    if args.extra_theory_csv:
        p = Path(args.extra_theory_csv)
        if p.exists():
            theory_df = pd.concat([theory_df, pd.read_csv(p)], ignore_index=True)

    print(f"Input: {len(lab_df)} lab rows, {len(theory_df)} theory rows")

    # ── DB ─────────────────────────────────────────────────────────────────────
    dsn  = _get_dsn()
    conn = psycopg2.connect(dsn)
    conn.autocommit = False
    cur  = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    try:
        print("\n[1/6] Scenario info ...")
        term_id, existing_tg_id = get_scenario_info(cur, args.scenario_id)
        print(f"      term={term_id[:8]}...  time_grid={'set' if existing_tg_id else 'none'}")

        print("\n[2/6] TimeGrid ...")
        tg_id = ensure_time_grid(cur, args.scenario_id, term_id, existing_tg_id, dry_run=args.dry_run)

        print("\n[3/6] Room lookup ...")
        room_lk = build_room_lookup(cur)
        print(f"      {len(room_lk)} rooms")

        print("\n[4/6] Faculty lookup ...")
        faculty_lk = build_faculty_lookup(cur)
        print(f"      {len(faculty_lk)} keys (name + staff_code)")

        print("\n[5/6] Lookups (offering + TA->Course + Course code) ...")
        offering_lk  = build_offering_lookup(cur, term_id)
        ta_course_lk = build_ta_course_lookup(cur, term_id)
        course_lk    = build_course_lookup(cur)
        print(f"      {len(offering_lk)} offering pairs, {len(ta_course_lk)} TA→Course mappings, {len(course_lk)} courses")

        print("\n[6/6] Processing rows ...")
        miss_rooms:   set = set()
        miss_faculty: set = set()

        lab_rows    = process_lab_df(lab_df, room_lk, faculty_lk, offering_lk, ta_course_lk,
                                     args.scenario_id, miss_rooms, miss_faculty, course_lk=course_lk)
        theory_rows = process_theory_df(theory_df, room_lk, faculty_lk, offering_lk, ta_course_lk,
                                        args.scenario_id, miss_rooms, miss_faculty, course_lk=course_lk)
        all_rows = lab_rows + theory_rows
        print(f"      lab={len(lab_rows)}, theory={len(theory_rows)}, total={len(all_rows)}")

        print("\n      Filling offering_ids via TA/course lookup ...")
        filled = bulk_fill_offering_ids(cur, all_rows, term_id, offering_lk=offering_lk)
        print(f"      {filled}/{len(all_rows)} rows got offering_id")

        if miss_rooms:
            top = sorted(miss_rooms)[:15]
            print(f"\n  [WARN] {len(miss_rooms)} room(s) unmatched: {top}")
        if miss_faculty:
            top = sorted(miss_faculty)[:15]
            print(f"  [WARN] {len(miss_faculty)} faculty unmatched: {top}")

        dropped = (len(lab_df) + len(theory_df)) - len(all_rows)
        if dropped:
            print(f"  [WARN] {dropped} rows dropped (unmatched room or faculty)")

        print()
        insert_sessions(cur, all_rows, args.scenario_id, dry_run=args.dry_run)

        if not args.dry_run:
            conn.commit()
            print(f"\nDone — {len(all_rows)} sessions committed to scenario {args.scenario_id}.")
        else:
            conn.rollback()
            print("\nDry run complete — no changes written.")

    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
