"""
setup_cohorts_from_import.py
============================
Creates SchedulingTargets, OfferingBuckets, and CourseOfferings for all
dept/sem combinations that have imported sessions but no cohort setup,
then links scheduled_sessions.offering_id.

This mirrors what the app's cohort allocation flow does at solve time,
but driven entirely from the already-imported scheduled_sessions.

Usage (from the repo root):
    python backend/scripts/setup_cohorts_from_import.py --scenario-id <uuid>
    python backend/scripts/setup_cohorts_from_import.py --scenario-id <uuid> --dry-run

Logic
-----
For each (dept_id, study_semester) found in sessions that still have offering_id=NULL:
  1. Collect all distinct (course_id, faculty_id) pairs that appear in sessions.
  2. Group by course_id → sorted list of faculty_ids.
     The max group-count across courses = num_groups for this cohort.
  3. Assign group_number by position in sorted faculty list per course.
     Courses with only 1 teacher go into group 1 (shared across all groups).
  4. Create SchedulingTarget (COHORT) if one doesn't already exist.
  5. Create OfferingBuckets: one per group_number.
  6. Create CourseOfferings: one per (course, faculty, group_number).
  7. UPDATE scheduled_sessions SET offering_id = <co.id>
     WHERE scenario_id = %s AND course_id = co.course_id AND faculty_id = co.faculty_id.
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

SCRIPT_DIR  = Path(__file__).parent.resolve()
BACKEND_DIR = SCRIPT_DIR.parent


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


def get_scenario_info(cur, scenario_id: str) -> tuple[str, str]:
    cur.execute(
        "SELECT academic_term_id, institution_id FROM scenarios WHERE id = %s",
        (scenario_id,)
    )
    row = cur.fetchone()
    if not row:
        sys.exit(f"Scenario {scenario_id!r} not found")
    return str(row["academic_term_id"]), str(row["institution_id"])


def load_dept_names(cur) -> dict[str, str]:
    """dept_id (str) -> dept short_name or name"""
    cur.execute("SELECT id::text, name, code FROM departments")
    out: dict[str, str] = {}
    for r in cur.fetchall():
        out[r["id"]] = r["name"]
    return out


def get_unlinked_pairs(cur, scenario_id: str, term_id: str) -> list[dict]:
    """
    Return distinct (course_id, faculty_id, dept_id, study_semester) from
    sessions that still have offering_id = NULL.
    """
    cur.execute(
        """
        SELECT DISTINCT
            ss.course_id,
            ss.faculty_id,
            ta.department_id::text  AS dept_id,
            ta.study_semester       AS study_semester
        FROM scheduled_sessions ss
        JOIN teaching_assignments ta
          ON ta.course_id::text    = ss.course_id
         AND ta.faculty_id::text   = ss.faculty_id
         AND ta.academic_term_id   = %s
        WHERE ss.scenario_id = %s
          AND ss.offering_id IS NULL
        ORDER BY 3, 4, 1, 2
        """,
        (term_id, scenario_id),
    )
    return [dict(r) for r in cur.fetchall()]


def get_existing_target(cur, dept_id: str, sem: int, term_id: str) -> str | None:
    """Return id of existing COHORT target for this dept/sem, or None."""
    cur.execute(
        """SELECT id FROM scheduling_targets
           WHERE academic_term_id = %s
             AND department_id = %s
             AND study_semester = %s
             AND target_type = 'COHORT'
           LIMIT 1""",
        (term_id, dept_id, sem),
    )
    row = cur.fetchone()
    return str(row["id"]) if row else None


def get_existing_buckets(cur, scenario_id: str, dept_id: str, sem: int) -> dict[int, str]:
    """Return {group_number: bucket_id} for already-existing buckets."""
    cur.execute(
        """SELECT ob.id::text, co.group_number
           FROM offering_buckets ob
           JOIN course_offerings co ON co.bucket_id = ob.id
           WHERE ob.scenario_id = %s AND ob.department_id = %s
             AND co.study_semester = %s
           GROUP BY ob.id, co.group_number""",
        (scenario_id, dept_id, sem),
    )
    return {r["group_number"]: r["id"] for r in cur.fetchall() if r["group_number"]}


def create_scheduling_target(cur, dept_id: str, sem: int, num_groups: int,
                              term_id: str, inst_id: str, dept_name: str,
                              dry_run: bool) -> str:
    target_id = str(uuid.uuid4())
    name = f"{dept_name} Sem {sem}"
    if not dry_run:
        cur.execute(
            """INSERT INTO scheduling_targets
                   (id, institution_id, academic_term_id, department_id, name,
                    target_type, study_semester, class_count, size, is_active,
                    created_at, updated_at)
               VALUES (%s,%s,%s,%s,%s,'COHORT',%s,%s,0,true,NOW(),NOW())
            """,
            (target_id, inst_id, term_id, dept_id, name, sem, num_groups)
        )
    return target_id


def create_bucket(cur, dept_id: str, group_num: int, dept_name: str, sem: int,
                  scenario_id: str, term_id: str, inst_id: str,
                  dry_run: bool) -> str:
    bucket_id = str(uuid.uuid4())
    name = f"{dept_name} Sem {sem} · Group {group_num}"
    if not dry_run:
        cur.execute(
            """INSERT INTO offering_buckets
                   (id, institution_id, academic_term_id, department_id, name,
                    min_selection, max_selection, selection_policy, scenario_id,
                    is_active, created_at, updated_at)
               VALUES (%s,%s,%s,%s,%s,1,1,'FIXED_BATCH',%s,true,NOW(),NOW())""",
            (bucket_id, inst_id, term_id, dept_id, name, scenario_id)
        )
    return bucket_id


def create_offering(cur, bucket_id: str, course_id: str, faculty_id: str | None,
                    group_num: int, sem: int, dry_run: bool) -> str:
    offering_id = str(uuid.uuid4())
    if not dry_run:
        cur.execute(
            """INSERT INTO course_offerings
                   (id, bucket_id, course_id, faculty_id, group_number,
                    study_semester, created_at)
               VALUES (%s::uuid,%s::uuid,%s::uuid,%s::uuid,%s,%s,NOW())""",
            (
                offering_id, bucket_id,
                course_id,
                faculty_id if faculty_id else None,
                group_num, sem,
            )
        )
    return offering_id


def link_sessions(cur, scenario_id: str, co_map: dict[tuple[str, str], str],
                  dry_run: bool) -> int:
    """
    co_map: (course_id_str, faculty_id_str) -> offering_id_str
    Returns count of rows updated.
    """
    if not co_map:
        return 0
    updated = 0
    for (course_id, faculty_id), offering_id in co_map.items():
        if dry_run:
            updated += 1
            continue
        cur.execute(
            """UPDATE scheduled_sessions
               SET offering_id = %s::uuid
               WHERE scenario_id = %s
                 AND course_id   = %s
                 AND faculty_id  = %s
                 AND offering_id IS NULL""",
            (offering_id, scenario_id, course_id, faculty_id)
        )
        updated += cur.rowcount
    return updated


def process_cohort(
    cur,
    dept_id: str,
    sem: int,
    pairs: list[dict],
    scenario_id: str,
    term_id: str,
    inst_id: str,
    dept_names: dict,
    dry_run: bool,
) -> tuple[int, int, int, dict[tuple[str, str], str]]:
    """
    Process one (dept, sem) cohort.
    Returns (targets_created, buckets_created, offerings_created, co_map).
    """
    dept_name = dept_names.get(dept_id, dept_id[:8])

    # Group (course_id, faculty_id) pairs by course_id
    by_course: dict[str, list[str]] = defaultdict(list)
    for p in pairs:
        if p["faculty_id"]:
            by_course[p["course_id"]].append(p["faculty_id"])
        else:
            by_course[p["course_id"]].append("")

    # Sort faculty lists for deterministic group assignment
    for cid in by_course:
        by_course[cid] = sorted(set(by_course[cid]))

    # num_groups = most common faculty count per course (use max to keep all)
    counts = [len(v) for v in by_course.values()]
    num_groups = max(counts) if counts else 1

    targets_created = buckets_created = offerings_created = 0
    co_map: dict[tuple[str, str], str] = {}

    # ── SchedulingTarget ───────────────────────────────────────────────────────
    existing_target_id = get_existing_target(cur, dept_id, sem, term_id)
    if existing_target_id:
        target_id = existing_target_id
    else:
        target_id = create_scheduling_target(
            cur, dept_id, sem, num_groups, term_id, inst_id, dept_name, dry_run
        )
        targets_created = 1

    # ── OfferingBuckets ────────────────────────────────────────────────────────
    existing_buckets = get_existing_buckets(cur, scenario_id, dept_id, sem)
    bucket_ids: dict[int, str] = dict(existing_buckets)

    for g in range(1, num_groups + 1):
        if g in bucket_ids:
            continue
        bid = create_bucket(
            cur, dept_id, g, dept_name, sem, scenario_id, term_id, inst_id, dry_run
        )
        bucket_ids[g] = bid
        buckets_created += 1

    # ── CourseOfferings ────────────────────────────────────────────────────────
    for course_id, fac_list in by_course.items():
        for idx, fac_id in enumerate(fac_list):
            group_num = idx + 1
            bucket_id = bucket_ids.get(group_num, bucket_ids.get(1, ""))
            if not bucket_id:
                continue
            oid = create_offering(
                cur, bucket_id, course_id,
                fac_id if fac_id else None,
                group_num, sem, dry_run
            )
            offerings_created += 1
            co_map[(course_id, fac_id)] = oid

    print(
        f"  {dept_name[:40]:40s}  s{sem}"
        f"  groups={num_groups}"
        f"  targets+={targets_created}"
        f"  buckets+={buckets_created}"
        f"  offerings+={offerings_created}"
    )
    return targets_created, buckets_created, offerings_created, co_map


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Create cohort structure and link offering_ids for imported sessions"
    )
    ap.add_argument("--scenario-id", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    dsn  = _get_dsn()
    conn = psycopg2.connect(dsn)
    conn.autocommit = False
    cur  = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    try:
        term_id, inst_id = get_scenario_info(cur, args.scenario_id)
        print(f"Scenario: {args.scenario_id[:8]}...  term: {term_id[:8]}...")

        dept_names = load_dept_names(cur)

        print("\nFetching unlinked (course, faculty) pairs ...")
        pairs = get_unlinked_pairs(cur, args.scenario_id, term_id)
        print(f"  {len(pairs)} distinct pairs without offering_id")

        if not pairs:
            print("All sessions already have offering_id. Nothing to do.")
            return

        # Group pairs by (dept_id, study_semester)
        by_dept_sem: dict[tuple[str, int], list[dict]] = defaultdict(list)
        skipped_no_dept = 0
        for p in pairs:
            if not p["dept_id"] or not p["study_semester"]:
                skipped_no_dept += 1
                continue
            by_dept_sem[(p["dept_id"], int(p["study_semester"]))].append(p)

        if skipped_no_dept:
            print(f"  [WARN] {skipped_no_dept} pairs skipped — no dept or semester on TA")

        print(f"\nProcessing {len(by_dept_sem)} dept/sem cohorts ...\n")

        total_targets = total_buckets = total_offerings = total_linked = 0
        all_co_maps: dict[tuple[str, str], str] = {}

        for (dept_id, sem), dept_pairs in sorted(by_dept_sem.items(),
                                                  key=lambda x: (dept_names.get(x[0][0], ""), x[0][1])):
            t, b, o, co_map = process_cohort(
                cur, dept_id, sem, dept_pairs,
                args.scenario_id, term_id, inst_id, dept_names,
                dry_run=args.dry_run,
            )
            total_targets   += t
            total_buckets   += b
            total_offerings += o
            all_co_maps.update(co_map)

        print(f"\nLinking offering_ids on scheduled_sessions ...")
        total_linked = link_sessions(cur, args.scenario_id, all_co_maps, dry_run=args.dry_run)

        print(f"\nSummary:")
        print(f"  SchedulingTargets created : {total_targets}")
        print(f"  OfferingBuckets created   : {total_buckets}")
        print(f"  CourseOfferings created   : {total_offerings}")
        print(f"  Sessions linked           : {total_linked}")

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
