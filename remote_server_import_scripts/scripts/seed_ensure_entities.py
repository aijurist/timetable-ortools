"""
seed_ensure_entities.py
=======================
Pre-seed step: scan both CSV files and ensure every room, faculty member, and
course referenced therein exists in the database. Creates missing entities with
sensible defaults derived from the CSV data.  Also builds PE / OE elective-pool
OfferingBuckets after the main session import.

Run this BEFORE seed_s57_schedule.py (or let seed_s57_schedule.py call it as
its first sub-step).

Usage (from backend/):
    python scripts/seed_ensure_entities.py
    python scripts/seed_ensure_entities.py --dry-run
    python scripts/seed_ensure_entities.py --pe-pools-only   # skip entity creation, only build PE pools
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path

import pandas as pd
import psycopg2
import psycopg2.extras

SCRIPT_DIR  = Path(__file__).parent.resolve()
BACKEND_DIR = SCRIPT_DIR.parent
SEEDS_DIR   = BACKEND_DIR / "data" / "legacy_seeds"

LAB_CSV    = SEEDS_DIR / "lab_schedule.csv"
THEORY_CSV = SEEDS_DIR / "theory_schedule.csv"

# Inactive bcrypt-hashed placeholder for auto-created users (they can reset password later)
BCRYPT_PLACEHOLDER = "$2b$12$PLACEHOLDER_SEEDED_USER_DO_NOT_LOGIN_xxxxxxxxxxxxxxxxxxxxxxxx"

# ── Dept name mapping: legacy CSV name → DB departments.name fragment ──────────
LEGACY_TO_DB_DEPT_NAME: dict[str, str] = {
    "Aeronautical Engineering":                         "Aeronautical Engineering",
    "Artificial Intelligence & Data Science":           "Artificial Intelligence and Data Science",
    "Artificial Intelligence & Machine Learning":       "Artificial Intelligence and Machine Learning",
    "Automobile Engineering":                           "Automobile Engineering",
    "Biomedical Engineering":                           "Biomedical Engineering",
    "Biotechnology":                                    "Biotechnology",
    "Chemical Engineering":                             "Chemical Engineering",
    "Civil Engineering":                                "Civil Engineering",
    "Computer Science & Business Systems":              "Computer Science and Business Systems",
    "Computer Science & Design":                        "Computer Science and Design",
    "Computer Science & Engineering":                   "Computer Science and Engineering",
    "Computer Science & Engineering (Cyber Security)":  "Cyber Security",
    "Electrical & Electronics Engineering":             "Electrical and Electronics",
    "Electronics & Communication Engineering":          "Electronics and Communication",
    "Food Technology":                                  "Food Technology",
    "Information Technology":                           "Information Technology",
    "Mechanical Engineering":                           "Mechanical Engineering",
    "Mechatronics Engineering":                         "Mechatronics",
    "Robotics & Automation":                            "Robotics",
}

# Skip these teacher values entirely
_SKIP_TEACHERS = {"unknown teacher", "new faculty", "", "nan", "unassigned-ms", "new faculty 1", "new faculty 2", "nf1 nan", "nf2 nan"}


def _get_dsn() -> str:
    env_file = BACKEND_DIR / ".env"
    db_url: str | None = None
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("DATABASE_URL="):
                db_url = line.split("=", 1)[1].strip()
                break
    db_url = db_url or os.getenv("DATABASE_URL", "")
    dsn = db_url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")
    if not dsn:
        sys.exit("DATABASE_URL not found in backend/.env or $DATABASE_URL")
    return dsn


def _is_blank(val) -> bool:
    return val is None or (isinstance(val, float) and str(val) == "nan") or str(val).strip() in ("", "nan", "NaN")


# ── Build dept_id_map ─────────────────────────────────────────────────────────

def build_dept_id_map(cur) -> dict[str, str]:
    """legacy CSV dept name → dept UUID str"""
    cur.execute("SELECT id::text, name FROM departments ORDER BY name")
    db_depts = cur.fetchall()
    result: dict[str, str] = {}
    for legacy_name, fragment in LEGACY_TO_DB_DEPT_NAME.items():
        # Special exact-suffix match for CSE (to avoid matching CSE Cyber Security)
        exact = legacy_name == "Computer Science & Engineering"
        matches = []
        for row in db_depts:
            if exact:
                if row["name"].rstrip('"').endswith("Computer Science and Engineering"):
                    matches.append(row)
            else:
                if fragment.lower() in row["name"].lower():
                    matches.append(row)
        if len(matches) == 1:
            result[legacy_name] = matches[0]["id"]
        elif len(matches) == 0:
            print(f"  [WARN] No dept match for '{legacy_name}'")
        else:
            # prefer the shorter name to avoid ambiguity
            best = min(matches, key=lambda r: len(r["name"]))
            result[legacy_name] = best["id"]
    return result


# ── 1. Ensure rooms ───────────────────────────────────────────────────────────

def ensure_rooms(cur, lab_df: pd.DataFrame, theory_df: pd.DataFrame,
                 inst_id: str, dry_run: bool) -> int:
    cur.execute("SELECT code FROM rooms WHERE institution_id = %s", (inst_id,))
    existing = {r["code"].strip() for r in cur.fetchall()}

    # Build capacity map from lab CSV (only source that has capacity)
    cap_map: dict[str, int] = {}
    for _, r in lab_df.iterrows():
        rn = str(r.get("room_number") or "").strip()
        cap_raw = r.get("capacity")
        if rn and not _is_blank(cap_raw):
            cap_map[rn] = max(cap_map.get(rn, 0), int(float(cap_raw)))

    # Build block map from both CSVs
    block_map: dict[str, str] = {}
    for df in [lab_df, theory_df]:
        for _, r in df.iterrows():
            rn = str(r.get("room_number") or "").strip()
            blk = str(r.get("block") or "").strip()
            if rn and blk and blk != "nan":
                block_map[rn] = blk

    # Rooms that appear in lab CSV → LAB type; theory-only rooms → LECTURE type
    lab_rooms = set(lab_df["room_number"].dropna().str.strip())

    all_rooms: set[str] = (
        set(lab_df["room_number"].dropna().str.strip()) |
        set(theory_df["room_number"].dropna().str.strip())
    )

    created = 0
    for room_num in sorted(all_rooms - existing):
        if not room_num or room_num.lower() == "nan":
            continue
        cap      = cap_map.get(room_num, 60)
        building = block_map.get(room_num, "")
        rtype    = "LAB" if room_num in lab_rooms else "LECTURE"
        name     = f"{room_num} ({building})" if building else room_num

        print(f"  + Room  {room_num:20s}  type={rtype:8s}  cap={cap:4d}  building={building}")
        if not dry_run:
            cur.execute(
                """INSERT INTO rooms
                       (id, institution_id, code, name, capacity, room_type,
                        is_active, created_at, updated_at, building)
                   VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, true, NOW(), NOW(), %s)
                   ON CONFLICT DO NOTHING""",
                (str(uuid.uuid4()), inst_id, room_num, name, cap, rtype, building or None),
            )
        created += 1
    return created


# ── 2. Ensure faculty ─────────────────────────────────────────────────────────

def ensure_faculty(cur, lab_df: pd.DataFrame, theory_df: pd.DataFrame,
                   inst_id: str, dept_id_map: dict[str, str],
                   dry_run: bool) -> int:
    cur.execute(
        "SELECT id::text, name, staff_code FROM faculty WHERE institution_id = %s",
        (inst_id,)
    )
    existing_by_code: dict[str, str] = {}
    existing_by_name: dict[str, str] = {}
    for r in cur.fetchall():
        if r["staff_code"]:
            existing_by_code[r["staff_code"].strip().lower()] = str(r["id"])
        existing_by_name[r["name"].strip().lower()] = str(r["id"])

    # Also check users email to avoid duplicate email conflicts
    cur.execute("SELECT email FROM users WHERE institution_id = %s", (inst_id,))
    existing_emails = {r["email"].lower() for r in cur.fetchall()}

    # Collect unique faculty from both CSVs
    faculty_info: dict[str, dict] = {}  # staff_code_lower (or name_lower) → {name, scode, dept}
    for df in [lab_df, theory_df]:
        for _, r in df.iterrows():
            name  = str(r.get("teacher_name") or "").strip()
            scode = str(r.get("staff_code")   or "").strip()
            dept  = str(r.get("department")   or "").strip()
            if not name or name.lower() in _SKIP_TEACHERS:
                continue
            scode_norm = scode.lower() if scode and scode.lower() not in ("nan", "") else ""
            key = scode_norm if scode_norm else name.lower()
            if key not in faculty_info:
                faculty_info[key] = {"name": name, "scode": scode_norm, "dept": dept}

    created = 0
    for key, info in sorted(faculty_info.items()):
        name  = info["name"]
        scode = info["scode"]
        dept  = info["dept"]

        # Already in DB?
        if scode and scode in existing_by_code:
            continue
        if name.lower() in existing_by_name:
            continue

        dept_id = dept_id_map.get(dept)
        # Generate email from staff_code or name
        if scode and scode not in ("nan", ""):
            base_email = f"{scode.strip()}@rec.ac.in"
        else:
            base_email = name.lower().replace(" ", ".").replace("..", ".").replace("'", "") + "@rec.ac.in"
        # Deduplicate email
        email = base_email
        suffix = 2
        while email.lower() in existing_emails:
            email = f"{base_email.rsplit('@', 1)[0]}{suffix}@rec.ac.in"
            suffix += 1

        print(f"  + Faculty  {name:45s}  code={scode:10s}  dept={dept}")
        if not dry_run:
            user_id = str(uuid.uuid4())
            fac_id  = str(uuid.uuid4())
            # User row (seeded, inactive login)
            cur.execute(
                """INSERT INTO users
                       (id, institution_id, email, hashed_password, full_name,
                        role, is_active, is_verified, created_at, updated_at, department_id)
                   VALUES (%s::uuid, %s::uuid, %s, %s, %s,
                           'teacher', true, true, NOW(), NOW(), %s)
                   ON CONFLICT (email) DO NOTHING""",
                (user_id, inst_id, email, BCRYPT_PLACEHOLDER, name, dept_id),
            )
            # Faculty row
            cur.execute(
                """INSERT INTO faculty
                       (id, institution_id, name, user_id, staff_code,
                        employment_type, max_weekly_hours, is_active, created_at, updated_at)
                   VALUES (%s::uuid, %s::uuid, %s, %s::uuid, %s,
                           'FULL_TIME', 20, true, NOW(), NOW())
                   ON CONFLICT DO NOTHING""",
                (fac_id, inst_id, name, user_id, scode if scode else None),
            )
        existing_emails.add(email.lower())
        if scode:
            existing_by_code[scode] = "new"
        existing_by_name[name.lower()] = "new"
        created += 1
    return created


# ── 3. Ensure courses ─────────────────────────────────────────────────────────

def _elective_type(code: str) -> str | None:
    cu = code.upper()
    if "PE" in cu:
        return "PROFESSIONAL"
    if "OE" in cu:
        return "OPEN"
    return None


def ensure_courses(cur, lab_df: pd.DataFrame, theory_df: pd.DataFrame,
                   inst_id: str, dept_id_map: dict[str, str],
                   dry_run: bool) -> int:
    cur.execute("SELECT code FROM courses WHERE institution_id = %s", (inst_id,))
    existing = {r["code"].strip().upper() for r in cur.fetchall()}

    # Collect unique courses from both CSVs
    courses: dict[str, dict] = {}  # code → info
    for df, stype in [(lab_df, "LAB"), (theory_df, "THEORY")]:
        for _, r in df.iterrows():
            code = str(r.get("course_code") or "").strip().upper()
            name = str(r.get("course_name") or "").strip()
            dept = str(r.get("department")  or "").strip()
            sem_raw = r.get("semester")
            if not code or code == "NAN" or code in existing:
                continue
            if code in courses:
                continue
            # Hours: lab uses practical_hours, theory uses lecture+tutorial
            if stype == "LAB":
                hours_raw = r.get("practical_hours")
            else:
                lh = r.get("lecture_hours") or 0
                th = r.get("tutorial_hours") or 0
                hours_raw = (0 if _is_blank(lh) else float(lh)) + (0 if _is_blank(th) else float(th))
            hours = max(int(float(hours_raw)) if not _is_blank(hours_raw) else 3, 1)
            sem   = int(float(sem_raw)) if not _is_blank(sem_raw) else None
            courses[code] = {"name": name, "dept": dept, "sem": sem,
                             "stype": stype, "hours": hours}

    created = 0
    for code, info in sorted(courses.items()):
        if code in existing:
            continue
        dept_id     = dept_id_map.get(info["dept"])
        elec_type   = _elective_type(code)
        stype       = info["stype"]

        print(f"  + Course  {code:20s}  {stype:7s}  elective={elec_type}  dept={info['dept']}")
        if not dry_run:
            cur.execute(
                """INSERT INTO courses
                       (id, institution_id, code, name, weekly_hours, session_type,
                        credits, is_active, created_at, updated_at,
                        department_id, elective_semester, elective_type,
                        room_tags_soft, preferred_room_ids_soft,
                        lab_preferred_room_ids_soft, lab_room_tags_soft)
                   VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s,
                           3, true, NOW(), NOW(),
                           %s, %s, %s,
                           false, false, false, false)
                   ON CONFLICT DO NOTHING""",
                (
                    str(uuid.uuid4()), inst_id, code, info["name"],
                    info["hours"], stype,
                    dept_id, info["sem"], elec_type,
                ),
            )
        existing.add(code)
        created += 1
    return created


# ── 4. Ensure teaching assignments for PE/OE courses ─────────────────────────

def ensure_teaching_assignments(cur, lab_df: pd.DataFrame, theory_df: pd.DataFrame,
                                 inst_id: str, term_id: str,
                                 dept_id_map: dict[str, str], dry_run: bool) -> int:
    """
    Create TeachingAssignment rows for PE/OE courses that don't yet have one.
    This lets setup_cohorts_from_telemetry (and offering_lk) find them.
    """
    cur.execute("SELECT id::text, code FROM courses WHERE institution_id = %s", (inst_id,))
    course_lk = {r["code"].strip().upper(): r["id"] for r in cur.fetchall()}

    cur.execute(
        "SELECT id::text, name, staff_code FROM faculty WHERE institution_id = %s",
        (inst_id,)
    )
    faculty_by_code: dict[str, str] = {}
    faculty_by_name: dict[str, str] = {}
    for r in cur.fetchall():
        if r["staff_code"]:
            faculty_by_code[r["staff_code"].strip().lower()] = r["id"]
        faculty_by_name[r["name"].strip().lower()] = r["id"]

    # Existing TAs to avoid duplicates
    cur.execute(
        "SELECT course_id::text, faculty_id::text FROM teaching_assignments WHERE academic_term_id = %s",
        (term_id,)
    )
    existing_ta = {(r["course_id"], r["faculty_id"]) for r in cur.fetchall()}

    created = 0
    seen: set[tuple] = set()
    for df in [lab_df, theory_df]:
        for _, r in df.iterrows():
            code  = str(r.get("course_code") or "").strip().upper()
            dept  = str(r.get("department")  or "").strip()
            name  = str(r.get("teacher_name") or "").strip()
            scode = str(r.get("staff_code")   or "").strip().lower()

            if not code or not _elective_type(code):
                continue  # only PE/OE

            course_id = course_lk.get(code)
            if not course_id:
                continue

            fac_id = (
                faculty_by_code.get(scode) or
                faculty_by_name.get(name.lower())
            )
            if not fac_id:
                continue

            dept_id = dept_id_map.get(dept)
            key = (course_id, fac_id)
            if key in existing_ta or key in seen:
                continue
            seen.add(key)

            sem_raw = r.get("semester")
            sem = int(float(sem_raw)) if not _is_blank(sem_raw) else 1

            print(f"  + TA  {code:20s}  faculty={name}")
            if not dry_run:
                cur.execute(
                    """INSERT INTO teaching_assignments
                           (id, institution_id, academic_term_id, department_id,
                            course_id, faculty_id, section_count,
                            is_active, created_at, updated_at,
                            study_semester)
                       VALUES (%s::uuid, %s::uuid, %s::uuid, %s::uuid,
                               %s::uuid, %s::uuid, 1,
                               true, NOW(), NOW(), %s)
                       ON CONFLICT ON CONSTRAINT uq_teaching_assignment DO NOTHING""",
                    (
                        str(uuid.uuid4()), inst_id, term_id, dept_id,
                        course_id, fac_id, sem,
                    ),
                )
            created += 1
    return created


# ── 5. Build PE / OE elective pool OfferingBuckets ───────────────────────────

def build_pe_pools(cur, lab_df: pd.DataFrame, theory_df: pd.DataFrame,
                   inst_id: str, term_id: str, scenario_id: str,
                   dept_id_map: dict[str, str], dry_run: bool) -> int:
    """
    For each dept/sem with PE or OE courses: create one CHOOSE_COURSE
    OfferingBucket ("PE Pool" / "OE Pool") and one CourseOffering per PE/OE
    option.  Link all existing scheduled_sessions for that course/faculty pair
    to the new offering.  Also add TargetRequirements from the dept/sem
    SchedulingTarget → the pool bucket so batch-assigned students can see them.
    """
    cur.execute("SELECT id::text, code FROM courses WHERE institution_id = %s", (inst_id,))
    course_lk = {r["code"].strip().upper(): r["id"] for r in cur.fetchall()}

    cur.execute(
        "SELECT id::text, name, staff_code FROM faculty WHERE institution_id = %s",
        (inst_id,)
    )
    faculty_by_code: dict[str, str] = {}
    faculty_by_name: dict[str, str] = {}
    for r in cur.fetchall():
        if r["staff_code"]:
            faculty_by_code[r["staff_code"].strip().lower()] = r["id"]
        faculty_by_name[r["name"].strip().lower()] = r["id"]

    # Collect PE/OE courses grouped by (dept, sem, pool_type)
    # pool_key → list of (course_id, faculty_id, course_code, course_name)
    from collections import defaultdict
    pools: dict[tuple, list] = defaultdict(list)  # (dept, sem, pool_label) → [(course_id, faculty_id, code, name)]
    seen_pool_entries: set = set()

    all_df = pd.concat([theory_df, lab_df], ignore_index=True)
    for _, r in all_df.iterrows():
        code = str(r.get("course_code") or "").strip().upper()
        et   = _elective_type(code)
        if not et:
            continue
        dept = str(r.get("department") or "").strip()
        sem_raw = r.get("semester")
        sem = int(float(sem_raw)) if not _is_blank(sem_raw) else 1
        cname = str(r.get("course_name") or "").strip()

        course_id = course_lk.get(code)
        if not course_id:
            continue

        teacher = str(r.get("teacher_name") or "").strip()
        scode   = str(r.get("staff_code")   or "").strip().lower()
        fac_id  = faculty_by_code.get(scode) or faculty_by_name.get(teacher.lower())

        pool_label = "PE Pool" if et == "PROFESSIONAL" else "OE Pool"
        pool_key   = (dept, sem, pool_label)
        entry_key  = (pool_key, course_id, fac_id or "")
        if entry_key not in seen_pool_entries:
            seen_pool_entries.add(entry_key)
            pools[pool_key].append((course_id, fac_id, code, cname))

    # Existing pool buckets to detect re-runs
    cur.execute(
        """SELECT ob.name FROM offering_buckets ob
           WHERE ob.institution_id = %s
             AND ob.academic_term_id = %s
             AND ob.scenario_id = %s
             AND ob.name LIKE '%% Pool'""",
        (inst_id, term_id, scenario_id),
    )
    existing_pool_names = {r["name"] for r in cur.fetchall()}

    # Scheduling targets (COHORT) for dept/sem — for TargetRequirements
    cur.execute(
        """SELECT id::text, department_id::text, study_semester
           FROM scheduling_targets
           WHERE institution_id = %s
             AND academic_term_id = %s
             AND target_type = 'COHORT'""",
        (inst_id, term_id),
    )
    sched_targets: dict[tuple, list[str]] = defaultdict(list)  # (dept_id, sem) → [target_id]
    for r in cur.fetchall():
        sched_targets[(r["department_id"], r["study_semester"])].append(r["id"])

    total_buckets = 0
    for pool_key, entries in sorted(pools.items()):
        dept, sem, pool_label = pool_key
        dept_id = dept_id_map.get(dept)
        if not dept_id:
            print(f"  [WARN] No dept_id for {dept}")
            continue

        pool_name = f"{dept} Sem {sem} {pool_label}"
        if pool_name in existing_pool_names:
            print(f"  SKIP  {pool_name} (already exists)")
            continue

        print(f"  + Pool  {pool_name}  ({len(entries)} options)")
        bucket_id = str(uuid.uuid4())
        if not dry_run:
            cur.execute(
                """INSERT INTO offering_buckets
                       (id, institution_id, academic_term_id, department_id,
                        name, min_selection, max_selection, selection_policy,
                        scenario_id, is_active, created_at, updated_at)
                   VALUES (%s::uuid, %s::uuid, %s::uuid, %s::uuid,
                           %s, 1, 1, 'CHOOSE_COURSE',
                           %s, true, NOW(), NOW())""",
                (bucket_id, inst_id, term_id, dept_id, pool_name, scenario_id),
            )

        # CourseOfferings
        for g_idx, (course_id, fac_id, code, cname) in enumerate(entries, 1):
            offering_id = str(uuid.uuid4())
            print(f"      Offering {g_idx}: {code} — {cname}")
            if not dry_run:
                cur.execute(
                    """INSERT INTO course_offerings
                           (id, bucket_id, course_id, faculty_id,
                            group_number, study_semester, created_at)
                       VALUES (%s::uuid, %s::uuid, %s::uuid, %s::uuid, %s, %s, NOW())""",
                    (offering_id, bucket_id, course_id, fac_id or None, g_idx, sem),
                )
                # Link sessions
                cur.execute(
                    """UPDATE scheduled_sessions
                       SET offering_id = %s::uuid
                       WHERE scenario_id = %s
                         AND course_id   = %s
                         AND (faculty_id = %s OR %s IS NULL)
                         AND offering_id IS NULL""",
                    (offering_id, scenario_id, course_id, fac_id, fac_id),
                )
                linked = cur.rowcount
                if linked:
                    print(f"        → linked {linked} sessions")

        # TargetRequirements: link this pool bucket to dept/sem SchedulingTargets
        target_ids = sched_targets.get((dept_id, sem), [])
        for tid in target_ids:
            print(f"      TargetRequirement → {tid[:8]}...")
            if not dry_run:
                cur.execute(
                    """INSERT INTO target_requirements
                           (id, target_id, bucket_id, created_at)
                       VALUES (%s::uuid, %s::uuid, %s::uuid, NOW())
                       ON CONFLICT DO NOTHING""",
                    (str(uuid.uuid4()), tid, bucket_id),
                )

        total_buckets += 1
    return total_buckets


# ── Main ─────────────────────────────────────────────────────────────────────

DEFAULT_SCENARIO_ID = "b5e52d55-f574-47de-b327-a03e06d70b87"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="Print what would be created; no DB writes")
    ap.add_argument("--pe-pools-only", action="store_true",
                    help="Skip room/faculty/course creation; only build PE/OE pools")
    ap.add_argument("--scenario-id", default=DEFAULT_SCENARIO_ID)
    args = ap.parse_args()

    for p in (LAB_CSV, THEORY_CSV):
        if not p.exists():
            sys.exit(f"Seed file not found: {p}")

    lab_df    = pd.read_csv(LAB_CSV)
    theory_df = pd.read_csv(THEORY_CSV)
    print(f"Loaded: {len(lab_df)} lab rows, {len(theory_df)} theory rows")

    dsn  = _get_dsn()
    conn = psycopg2.connect(dsn)
    conn.autocommit = False
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        # Institution + term
        cur.execute("SELECT id::text FROM institutions LIMIT 1")
        inst_id = cur.fetchone()["id"]

        cur.execute(
            "SELECT academic_term_id::text FROM scenarios WHERE id = %s",
            (args.scenario_id,)
        )
        row = cur.fetchone()
        if not row:
            sys.exit(f"Scenario {args.scenario_id} not found")
        term_id = row["academic_term_id"]
        print(f"Institution: {inst_id[:8]}...  Term: {term_id[:8]}...")

        dept_id_map = build_dept_id_map(cur)
        print(f"Dept map: {len(dept_id_map)} entries")

        if not args.pe_pools_only:
            print("\n─── 1. Rooms ───────────────────────────────────────────────")
            n = ensure_rooms(cur, lab_df, theory_df, inst_id, args.dry_run)
            print(f"  Created: {n}")

            print("\n─── 2. Faculty ─────────────────────────────────────────────")
            n = ensure_faculty(cur, lab_df, theory_df, inst_id, dept_id_map, args.dry_run)
            print(f"  Created: {n}")

            print("\n─── 3. Courses ─────────────────────────────────────────────")
            n = ensure_courses(cur, lab_df, theory_df, inst_id, dept_id_map, args.dry_run)
            print(f"  Created: {n}")

            print("\n─── 4. Teaching Assignments (PE/OE) ────────────────────────")
            n = ensure_teaching_assignments(cur, lab_df, theory_df, inst_id, term_id, dept_id_map, args.dry_run)
            print(f"  Created: {n}")

        print("\n─── 5. PE / OE Pools ───────────────────────────────────────")
        n = build_pe_pools(cur, lab_df, theory_df, inst_id, term_id,
                           args.scenario_id, dept_id_map, args.dry_run)
        print(f"  Pools created: {n}")

        if args.dry_run:
            conn.rollback()
            print("\nDry run — nothing written.")
        else:
            conn.commit()
            print("\nCommitted.")

    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
