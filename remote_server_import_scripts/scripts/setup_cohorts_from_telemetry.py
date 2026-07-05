"""
setup_cohorts_from_telemetry.py
================================
Reads the legacy grouping_telemetry.json files (produced by course_group_optimizer.py)
and rebuilds OfferingBuckets + CourseOfferings in the new system to match EXACTLY what
the legacy optimizer decided.

Logic
-----
1. Load both telemetry files → flat list of (dept_legacy_name, semester, groups[])
2. Map legacy dept name → new-system dept_id via a name lookup table
3. For the given scenario, DELETE any existing buckets + offerings created for those dept/sems
   (the ones from the previous wrong run of setup_cohorts_from_import.py)
   AIDS Sem5 is skipped entirely — it was set up correctly by the app before this.
4. For each group in telemetry:
   a. Each group has course_instances = list of TA UUIDs
   b. For each TA UUID: look up (course_id, faculty_id) from scheduled_sessions
      (session_id starts with the TA UUID)
   c. Create OfferingBucket for the group (if not already existing)
   d. Create CourseOffering per (course_id, faculty_id) with correct group_number
5. UPDATE scheduled_sessions.offering_id

Usage
-----
    python backend/scripts/setup_cohorts_from_telemetry.py \\
        --scenario-id b5e52d55-f574-47de-b327-a03e06d70b87
    python backend/scripts/setup_cohorts_from_telemetry.py \\
        --scenario-id b5e52d55-f574-47de-b327-a03e06d70b87 --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from collections import defaultdict
from pathlib import Path

import psycopg2
import psycopg2.extras

# ── Paths ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR  = Path(__file__).parent.resolve()
BACKEND_DIR = SCRIPT_DIR.parent

TELEMETRY_FILES = [
    Path("E:/coding/grind_project/timetable_scheduler/output/2026-06-10_23-23-56/grouping_telemetry.json"),
    Path("E:/coding/grind_project/timetable_scheduler/output/2026-06-10_23-24-56/grouping_telemetry.json"),
]

# ── Legacy name → DB name fragment mapping ────────────────────────────────────
# Maps the short dept names used in legacy telemetry to substrings that appear
# uniquely in the new system's departments.name column.
LEGACY_TO_DB_FRAGMENT: dict[str, str] = {
    "Aeronautical Engineering":                         "Aeronautical",
    "Artificial Intelligence & Data Science":           "Artificial Intelligence and Data Science",
    "Artificial Intelligence & Machine Learning":       "Artificial Intelligence and Machine Learning",
    "Automobile Engineering":                           "Automobile Engineering",
    "Biomedical Engineering":                           "Biomedical Engineering",
    "Biotechnology":                                    "Biotechnology",
    "Chemical Engineering":                             "Chemical Engineering",
    "Civil Engineering":                                "Civil Engineering",
    "Computer Science & Business Systems":              "Computer Science and Business Systems",
    "Computer Science & Design":                        "Computer Science and Design",
    "Computer Science & Engineering":                   "Computer Science and Engineering\"",   # exact end
    "Computer Science & Engineering (Cyber Security)":  "Cyber Security",
    "Electrical & Electronics Engineering":             "Electrical and Electronics",
    "Electronics & Communication Engineering":          "Electronics and Communication",
    "Food Technology":                                  "Food Technology",
    "Information Technology":                           "Information Technology",
    "Mechanical Engineering":                           "Mechanical Engineering",
    "Mechatronics Engineering":                         "Mechatronics",
    "Robotics & Automation":                            "Robotics",
}

# AIDS Sem5 was already set up correctly by the app before this import — skip it.
SKIP = {("Artificial Intelligence & Data Science", 5)}


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
        sys.exit("DATABASE_URL not found")
    return dsn


def load_telemetry(extra_paths: list[Path] | None = None) -> list[dict]:
    """Return flat list of dept entries across telemetry files."""
    sources = extra_paths if extra_paths else TELEMETRY_FILES
    entries: list[dict] = []
    for path in sources:
        if not path.exists():
            print(f"[WARN] Telemetry file not found: {path}")
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for entry in data.get("departments", []):
            entries.append(entry)
    return entries


def build_dept_id_map(cur) -> dict[str, str]:
    """
    Build {legacy_name: dept_id} by matching LEGACY_TO_DB_FRAGMENT against
    the departments table.
    """
    cur.execute("SELECT id::text, name FROM departments ORDER BY name")
    db_depts = cur.fetchall()

    result: dict[str, str] = {}
    for legacy_name, fragment in LEGACY_TO_DB_FRAGMENT.items():
        # Strip the trailing quote hack used for exact CSE match
        frag = fragment.rstrip('"')
        exact_end = fragment.endswith('"')
        matches = []
        for row in db_depts:
            if exact_end:
                if row["name"].endswith(frag):
                    matches.append(row)
            else:
                if frag.lower() in row["name"].lower():
                    matches.append(row)
        if len(matches) == 1:
            result[legacy_name] = matches[0]["id"]
        elif len(matches) == 0:
            print(f"[WARN] No dept match for '{legacy_name}' (fragment='{frag}')")
        else:
            print(f"[WARN] Ambiguous match for '{legacy_name}': {[r['name'] for r in matches]}")
    return result


def get_scenario_info(cur, scenario_id: str) -> tuple[str, str]:
    cur.execute(
        "SELECT academic_term_id, institution_id FROM scenarios WHERE id = %s",
        (scenario_id,)
    )
    row = cur.fetchone()
    if not row:
        sys.exit(f"Scenario {scenario_id!r} not found")
    return str(row["academic_term_id"]), str(row["institution_id"])


def build_ta_session_map(cur, scenario_id: str, term_id: str) -> dict[str, tuple[str, str]]:
    """
    ta_uuid (str) -> (course_id_str, faculty_id_str)

    Reads from teaching_assignments directly so it works for both old-format CSVs
    (where session_id prefix was the TA UUID) and new-format CSVs (where
    course_instance_id is an integer and session_id has an integer prefix).
    """
    cur.execute(
        """SELECT id::text AS ta_id, course_id::text AS course_id, faculty_id::text AS faculty_id
           FROM teaching_assignments WHERE academic_term_id = %s""",
        (term_id,)
    )
    return {row["ta_id"]: (row["course_id"], str(row["faculty_id"] or ""))
            for row in cur.fetchall()}


def delete_existing_cohort_data(cur, scenario_id: str, dept_id: str, sem: int, dry_run: bool) -> int:
    """
    Delete OfferingBuckets (and cascade CourseOfferings) for this dept/sem combo,
    then NULL out the offering_id on affected sessions so they can be re-linked.
    Returns number of buckets deleted.
    """
    # Find buckets for this dept/sem
    cur.execute("""
        SELECT DISTINCT ob.id::text
        FROM offering_buckets ob
        JOIN course_offerings co ON co.bucket_id = ob.id
        WHERE ob.scenario_id = %s
          AND ob.department_id = %s::uuid
          AND co.study_semester = %s
    """, (scenario_id, dept_id, sem))
    bucket_ids = [r["id"] for r in cur.fetchall()]
    if not bucket_ids:
        return 0

    if not dry_run:
        # NULL out offering_id on sessions that point to these buckets
        cur.execute("""
            UPDATE scheduled_sessions
            SET offering_id = NULL
            WHERE scenario_id = %s
              AND offering_id IN (
                  SELECT co.id FROM course_offerings co
                  WHERE co.bucket_id = ANY(%s::uuid[])
              )
        """, (scenario_id, bucket_ids))

        # Delete buckets (cascades to course_offerings via FK)
        cur.execute(
            "DELETE FROM offering_buckets WHERE id = ANY(%s::uuid[])",
            (bucket_ids,)
        )

        # Also delete SchedulingTarget for this dept/sem (we'll recreate it)
        cur.execute("""
            DELETE FROM scheduling_targets
            WHERE scenario_id IS NULL
              AND department_id = %s::uuid
              AND study_semester = %s
              AND target_type = 'COHORT'
        """, (dept_id, sem))

    return len(bucket_ids)


def create_bucket(cur, dept_id: str, group_num: int, dept_name: str, sem: int,
                  scenario_id: str, term_id: str, inst_id: str, dry_run: bool) -> str:
    bucket_id = str(uuid.uuid4())
    name = f"{dept_name} Sem {sem} · Group {group_num}"
    if not dry_run:
        cur.execute("""
            INSERT INTO offering_buckets
                (id, institution_id, academic_term_id, department_id, name,
                 min_selection, max_selection, selection_policy, scenario_id,
                 is_active, created_at, updated_at)
            VALUES (%s::uuid,%s::uuid,%s::uuid,%s::uuid,%s,1,1,'FIXED_BATCH',%s,true,NOW(),NOW())
        """, (bucket_id, inst_id, term_id, dept_id, name, scenario_id))
    return bucket_id


def create_offering(cur, bucket_id: str, course_id: str, faculty_id: str | None,
                    group_num: int, sem: int, dry_run: bool) -> str:
    offering_id = str(uuid.uuid4())
    if not dry_run:
        cur.execute("""
            INSERT INTO course_offerings
                (id, bucket_id, course_id, faculty_id, group_number, study_semester, created_at)
            VALUES (%s::uuid,%s::uuid,%s::uuid,%s::uuid,%s,%s,NOW())
        """, (
            offering_id, bucket_id,
            course_id,
            faculty_id if faculty_id else None,
            group_num, sem,
        ))
    return offering_id


def create_scheduling_target(cur, dept_id: str, sem: int, num_groups: int,
                              term_id: str, inst_id: str, dept_name: str, dry_run: bool) -> None:
    if not dry_run:
        cur.execute("""
            INSERT INTO scheduling_targets
                (id, institution_id, academic_term_id, department_id, name,
                 target_type, study_semester, class_count, size, is_active,
                 created_at, updated_at)
            VALUES (%s::uuid,%s::uuid,%s::uuid,%s::uuid,%s,'COHORT',%s,%s,0,true,NOW(),NOW())
        """, (str(uuid.uuid4()), inst_id, term_id, dept_id,
              f"{dept_name} Sem {sem}", sem, num_groups))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario-id", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--telemetry-file", dest="telemetry_files", action="append",
        metavar="PATH", default=None,
        help="Telemetry JSON path(s). Repeatable. Overrides hardcoded TELEMETRY_FILES.",
    )
    args = ap.parse_args()
    extra_telem = [Path(p) for p in args.telemetry_files] if args.telemetry_files else None

    dsn  = _get_dsn()
    conn = psycopg2.connect(dsn)
    conn.autocommit = False
    cur  = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    try:
        term_id, inst_id = get_scenario_info(cur, args.scenario_id)
        print(f"Scenario: {args.scenario_id[:8]}  term: {term_id[:8]}")

        dept_id_map = build_dept_id_map(cur)
        ta_session_map = build_ta_session_map(cur, args.scenario_id, term_id)
        print(f"Dept map: {len(dept_id_map)} entries")
        print(f"TA->course map: {len(ta_session_map)} teaching assignments loaded\n")

        entries = load_telemetry(extra_telem)
        print(f"Telemetry entries: {len(entries)} dept/sem combos\n")

        total_buckets = total_offerings = total_linked = 0
        total_deleted = 0

        for entry in entries:
            legacy_name = entry["department"]
            sem         = entry["semester"]
            groups      = entry.get("groups", [])

            if (legacy_name, sem) in SKIP:
                print(f"  SKIP  {legacy_name:45s}  s{sem}  (already correct)")
                continue

            dept_id = dept_id_map.get(legacy_name)
            if not dept_id:
                print(f"  MISS  {legacy_name:45s}  s{sem}  (no dept_id mapping)")
                continue

            # Get short dept name for bucket labels
            cur.execute("SELECT name FROM departments WHERE id = %s::uuid", (dept_id,))
            dept_name_row = cur.fetchone()
            dept_name = dept_name_row["name"] if dept_name_row else legacy_name

            # ── Delete existing wrong data ─────────────────────────────────
            deleted = delete_existing_cohort_data(
                cur, args.scenario_id, dept_id, sem, dry_run=args.dry_run
            )
            total_deleted += deleted

            # ── Create SchedulingTarget ───────────────────────────────────
            create_scheduling_target(
                cur, dept_id, sem, len(groups),
                term_id, inst_id, dept_name, dry_run=args.dry_run
            )

            # ── Create Buckets + Offerings ────────────────────────────────
            co_map: dict[tuple[str, str], str] = {}  # (course_id, faculty_id) -> offering_id
            buckets_here = offerings_here = 0
            bucket_ids_here: list[str] = []

            for g_idx, group in enumerate(groups):
                group_num = g_idx + 1
                bucket_id = create_bucket(
                    cur, dept_id, group_num, dept_name, sem,
                    args.scenario_id, term_id, inst_id, dry_run=args.dry_run
                )
                buckets_here += 1
                bucket_ids_here.append(bucket_id)

                for ta_uuid in group.get("course_instances", []):
                    pair = ta_session_map.get(ta_uuid)
                    if not pair:
                        print(f"    [WARN] TA {ta_uuid[:8]} not found in sessions")
                        continue
                    course_id, faculty_id = pair
                    oid = create_offering(
                        cur, bucket_id, course_id,
                        faculty_id if faculty_id else None,
                        group_num, sem, dry_run=args.dry_run
                    )
                    offerings_here += 1
                    co_map[(course_id, faculty_id)] = oid

            # ── Link sessions ─────────────────────────────────────────────
            linked_here = 0
            for (course_id, faculty_id), offering_id in co_map.items():
                if args.dry_run:
                    linked_here += 1
                    continue
                cur.execute("""
                    UPDATE scheduled_sessions
                    SET offering_id = %s::uuid
                    WHERE scenario_id = %s
                      AND course_id   = %s
                      AND faculty_id  = %s
                      AND offering_id IS NULL
                """, (offering_id, args.scenario_id, course_id, faculty_id))
                linked_here += cur.rowcount

            # ── TargetRequirements: link ALL COHORT targets for this dept/sem ──
            # This includes both system-created and admin-created batch SchedulingTargets
            if not args.dry_run and bucket_ids_here:
                cur.execute("""
                    SELECT id::text FROM scheduling_targets
                    WHERE department_id = %s::uuid
                      AND study_semester = %s
                      AND academic_term_id = %s
                      AND target_type = 'COHORT'
                """, (dept_id, sem, term_id))
                target_ids = [r["id"] for r in cur.fetchall()]
                for tid in target_ids:
                    for bid in bucket_ids_here:
                        cur.execute("""
                            INSERT INTO target_requirements (id, target_id, bucket_id, created_at)
                            VALUES (%s::uuid, %s::uuid, %s::uuid, NOW())
                            ON CONFLICT ON CONSTRAINT uq_target_bucket DO NOTHING
                        """, (str(uuid.uuid4()), tid, bid))

            total_buckets   += buckets_here
            total_offerings += offerings_here
            total_linked    += linked_here

            print(
                f"  {'(dry)' if args.dry_run else 'DONE'}"
                f"  {legacy_name:45s}  s{sem}"
                f"  groups={len(groups)}"
                f"  del={deleted}"
                f"  buckets+={buckets_here}"
                f"  offerings+={offerings_here}"
                f"  linked+={linked_here}"
            )

        # ── Final summary ─────────────────────────────────────────────────
        cur.execute("""
            SELECT
              COUNT(*) FILTER (WHERE offering_id IS NOT NULL) AS with_offering,
              COUNT(*) FILTER (WHERE offering_id IS NULL)     AS without_offering
            FROM scheduled_sessions WHERE scenario_id = %s
        """, (args.scenario_id,))
        r = cur.fetchone()

        print(f"\nSummary:")
        print(f"  Buckets deleted (old)   : {total_deleted}")
        print(f"  Buckets created         : {total_buckets}")
        print(f"  CourseOfferings created : {total_offerings}")
        print(f"  Sessions linked         : {total_linked}")
        print(f"  Sessions with offering  : {r['with_offering']} / {r['with_offering'] + r['without_offering']}")
        print(f"  Sessions still NULL     : {r['without_offering']}")

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
