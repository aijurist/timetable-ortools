"""
fix_unlinked_sessions.py
========================
Finds scheduled_sessions with offering_id=NULL, looks up the original CSV rows
(using the integer prefix in session_id as course_instance_id), creates missing
teaching_assignments + group OfferingBuckets + CourseOfferings, links the sessions,
and wires TargetRequirements so COHORT students see them.

Usage (from backend/):
    python -X utf8 scripts/fix_unlinked_sessions.py
    python -X utf8 scripts/fix_unlinked_sessions.py --dry-run
"""
from __future__ import annotations

import argparse
import os
import uuid
from collections import defaultdict
from pathlib import Path

import psycopg2
import psycopg2.extras
import pandas as pd

SCRIPT_DIR  = Path(__file__).parent
BACKEND_DIR = SCRIPT_DIR.parent

LAB_CSV    = BACKEND_DIR / "data" / "legacy_seeds" / "lab_schedule.csv"
THEORY_CSV = BACKEND_DIR / "data" / "legacy_seeds" / "theory_schedule.csv"

SCENARIO = "b5e52d55-f574-47de-b327-a03e06d70b87"
TERM_ID  = "fd9f461a-1d43-4dd1-bc61-bfefa93ee363"
INST_ID  = "1eebed4f-b801-43ae-b089-e5da3ffe86e0"

# Legacy dept name → DB name fragment  (same as setup_cohorts_from_telemetry.py)
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
    "Computer Science & Engineering":                   'Computer Science and Engineering"',  # exact end
    "Computer Science & Engineering (Cyber Security)":  "Cyber Security",
    "Electrical & Electronics Engineering":             "Electrical and Electronics",
    "Electronics & Communication Engineering":          "Electronics and Communication",
    "Food Technology":                                  "Food Technology",
    "Information Technology":                           "Information Technology",
    "Mechanical Engineering":                           "Mechanical Engineering",
    "Mechatronics Engineering":                         "Mechatronics",
    "Robotics & Automation":                            "Robotics",
}


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
        raise SystemExit("DATABASE_URL not found")
    return dsn


def build_dept_id_map(cur) -> dict[str, str]:
    cur.execute("SELECT id::text, name FROM departments ORDER BY name")
    db_depts = cur.fetchall()
    result: dict[str, str] = {}
    for legacy_name, fragment in LEGACY_TO_DB_FRAGMENT.items():
        frag = fragment.rstrip('"')
        exact_end = fragment.endswith('"')
        matches = [
            r for r in db_depts
            if (r["name"].endswith(frag) if exact_end else frag.lower() in r["name"].lower())
        ]
        if len(matches) == 1:
            result[legacy_name] = matches[0]["id"]
        elif len(matches) == 0:
            print(f"  [WARN] No dept match for '{legacy_name}'")
    return result


def build_csv_index(lab_df: pd.DataFrame, theory_df: pd.DataFrame) -> dict[str, dict]:
    """Build {str(course_instance_id): {dept, semester, course_code}} from both CSVs."""
    index: dict[str, dict] = {}
    for df in [lab_df, theory_df]:
        for _, r in df.iterrows():
            ta_id = str(int(r["course_instance_id"])) if not pd.isna(r.get("course_instance_id")) else None
            if not ta_id:
                continue
            dept = str(r.get("department") or "").strip()
            sem = r.get("semester")
            code = str(r.get("course_code") or "").strip()
            if ta_id not in index and dept and sem and code:
                index[ta_id] = {"dept": dept, "semester": int(sem), "course_code": code}
    return index


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print("Loading CSVs …")
    lab_df    = pd.read_csv(LAB_CSV)
    theory_df = pd.read_csv(THEORY_CSV)
    csv_index = build_csv_index(lab_df, theory_df)
    print(f"  CSV index: {len(csv_index)} unique course_instance_ids\n")

    dsn  = _get_dsn()
    conn = psycopg2.connect(dsn)
    conn.autocommit = False
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        dept_id_map = build_dept_id_map(cur)
        print(f"Dept map: {len(dept_id_map)} entries\n")

        # ── Step 1: gather all unlinked (course_id, faculty_id) from sessions ──
        cur.execute("""
            SELECT DISTINCT ss.course_id, ss.faculty_id, c.code as course_code
            FROM scheduled_sessions ss
            LEFT JOIN courses c ON c.id::text = ss.course_id
            WHERE ss.scenario_id = %s AND ss.offering_id IS NULL
        """, (SCENARIO,))
        unlinked_pairs = cur.fetchall()
        print(f"Unlinked (course_id, faculty_id) pairs: {len(unlinked_pairs)}")

        # For each pair, figure out dept/sem by looking at session_id prefixes → CSV
        # session_id format: "{ta_id}_{slot_code}[_B{N}]"
        pair_to_meta: dict[tuple[str, str], dict] = {}  # (course_id, fac_id) -> {dept_id, sem, course_code}

        for pair in unlinked_pairs:
            course_id = pair["course_id"]
            fac_id    = pair["faculty_id"]
            code      = pair["course_code"]

            # Find a session with this course+faculty to extract ta_id from session_id
            cur.execute("""
                SELECT session_id FROM scheduled_sessions
                WHERE scenario_id = %s AND course_id = %s AND faculty_id = %s
                LIMIT 1
            """, (SCENARIO, course_id, fac_id))
            row = cur.fetchone()
            if not row:
                continue

            ta_id_str = row["session_id"].split("_")[0]
            csv_row = csv_index.get(ta_id_str)
            if not csv_row:
                print(f"  [SKIP] ta_id={ta_id_str} not in CSV index (course={code})")
                continue

            dept_id = dept_id_map.get(csv_row["dept"])
            if not dept_id:
                print(f"  [SKIP] dept '{csv_row['dept']}' not found in DB")
                continue

            pair_to_meta[(course_id, fac_id)] = {
                "dept_id": dept_id,
                "dept_name": csv_row["dept"],
                "sem": csv_row["semester"],
                "course_code": code,
            }

        print(f"Resolved metadata for {len(pair_to_meta)} pairs\n")

        # ── Step 2: group pairs by (dept_id, sem) ─────────────────────────────
        # Each dept/sem gets ONE supplementary "ungrouped" bucket with offerings per pair
        by_dept_sem: dict[tuple[str, int], list[tuple[str, str]]] = defaultdict(list)
        for (course_id, fac_id), meta in pair_to_meta.items():
            by_dept_sem[(meta["dept_id"], meta["sem"])].append((course_id, fac_id))

        total_buckets_created = 0
        total_offerings_created = 0
        total_tas_created = 0
        total_sessions_linked = 0
        total_trs_created = 0

        for (dept_id, sem), pairs in sorted(by_dept_sem.items()):
            # Get dept_name
            cur.execute("SELECT name FROM departments WHERE id = %s::uuid", (dept_id,))
            dept_name_row = cur.fetchone()
            dept_name = dept_name_row["name"] if dept_name_row else dept_id[:8]

            print(f"\n  {dept_name} Sem {sem}  ({len(pairs)} missing course+faculty pairs)")

            # Check if a "Supplementary" bucket already exists for this dept/sem
            cur.execute("""
                SELECT id::text FROM offering_buckets
                WHERE scenario_id = %s AND department_id = %s::uuid
                  AND name = %s
            """, (SCENARIO, dept_id, f"{dept_name} Sem {sem} · Supplementary"))
            existing = cur.fetchone()

            if existing:
                bucket_id = existing["id"]
                print(f"    Using existing Supplementary bucket {bucket_id[:8]}")
            else:
                bucket_id = str(uuid.uuid4())
                print(f"    Creating Supplementary bucket {bucket_id[:8]}")
                if not args.dry_run:
                    cur.execute("""
                        INSERT INTO offering_buckets
                            (id, institution_id, academic_term_id, department_id, name,
                             min_selection, max_selection, selection_policy, scenario_id,
                             is_active, created_at, updated_at)
                        VALUES (%s::uuid,%s::uuid,%s::uuid,%s::uuid,%s,1,100,'FIXED_BATCH',%s,true,NOW(),NOW())
                    """, (bucket_id, INST_ID, TERM_ID, dept_id, f"{dept_name} Sem {sem} · Supplementary", SCENARIO))
                total_buckets_created += 1

            # ── TargetRequirements: link to all COHORT targets for this dept/sem ──
            if not args.dry_run:
                cur.execute("""
                    SELECT id::text FROM scheduling_targets
                    WHERE department_id = %s::uuid
                      AND study_semester = %s
                      AND academic_term_id = %s::uuid
                      AND target_type = 'COHORT'
                """, (dept_id, sem, TERM_ID))
                target_ids = [r["id"] for r in cur.fetchall()]
                for tid in target_ids:
                    cur.execute("""
                        INSERT INTO target_requirements (id, target_id, bucket_id, created_at)
                        VALUES (%s::uuid, %s::uuid, %s::uuid, NOW())
                        ON CONFLICT ON CONSTRAINT uq_target_bucket DO NOTHING
                    """, (str(uuid.uuid4()), tid, bucket_id))
                    total_trs_created += 1

            # ── Per pair: create TA if missing, create offering, link sessions ──
            for course_id, fac_id in pairs:
                meta = pair_to_meta[(course_id, fac_id)]

                # Check if offering already exists for this pair in this bucket
                cur.execute("""
                    SELECT id::text FROM course_offerings
                    WHERE bucket_id = %s::uuid AND course_id = %s::uuid AND faculty_id = %s::uuid
                """, (bucket_id, course_id, fac_id))
                existing_off = cur.fetchone()

                if existing_off:
                    offering_id = existing_off["id"]
                else:
                    # Ensure TA exists
                    cur.execute("""
                        SELECT id::text FROM teaching_assignments
                        WHERE academic_term_id = %s::uuid AND department_id = %s::uuid
                          AND course_id = %s::uuid AND faculty_id = %s::uuid
                    """, (TERM_ID, dept_id, course_id, fac_id))
                    ta_row = cur.fetchone()

                    if not ta_row:
                        ta_id = str(uuid.uuid4())
                        print(f"      + TA for {meta['course_code']} fac={fac_id[:8]}")
                        if not args.dry_run:
                            cur.execute("""
                                INSERT INTO teaching_assignments
                                    (id, institution_id, academic_term_id, department_id,
                                     course_id, faculty_id, section_count, is_active,
                                     created_at, updated_at, study_semester)
                                VALUES (%s::uuid,%s::uuid,%s::uuid,%s::uuid,
                                        %s::uuid,%s::uuid,1,true,NOW(),NOW(),%s)
                                ON CONFLICT ON CONSTRAINT uq_teaching_assignment DO NOTHING
                            """, (ta_id, INST_ID, TERM_ID, dept_id, course_id, fac_id, sem))
                        total_tas_created += 1

                    # Create CourseOffering
                    offering_id = str(uuid.uuid4())
                    if not args.dry_run:
                        cur.execute("""
                            INSERT INTO course_offerings
                                (id, bucket_id, course_id, faculty_id, group_number, study_semester, created_at)
                            VALUES (%s::uuid,%s::uuid,%s::uuid,%s::uuid,0,%s,NOW())
                        """, (offering_id, bucket_id, course_id, fac_id, sem))
                    total_offerings_created += 1

                # Link sessions
                if not args.dry_run:
                    cur.execute("""
                        UPDATE scheduled_sessions
                        SET offering_id = %s::uuid
                        WHERE scenario_id = %s AND course_id = %s AND faculty_id = %s
                          AND offering_id IS NULL
                    """, (offering_id, SCENARIO, course_id, fac_id))
                    linked = cur.rowcount
                else:
                    cur.execute("""
                        SELECT COUNT(*) FROM scheduled_sessions
                        WHERE scenario_id = %s AND course_id = %s AND faculty_id = %s
                          AND offering_id IS NULL
                    """, (SCENARIO, course_id, fac_id))
                    linked = cur.fetchone()["count"]
                total_sessions_linked += linked
                print(f"      {meta['course_code']}  fac={fac_id[:8]}  → linked {linked} sessions")

        print(f"\n{'='*60}")
        print(f"Buckets created   : {total_buckets_created}")
        print(f"TAs created       : {total_tas_created}")
        print(f"Offerings created : {total_offerings_created}")
        print(f"Sessions linked   : {total_sessions_linked}")
        print(f"TRs added         : {total_trs_created}")

        # Final count
        cur.execute("""
            SELECT COUNT(*) as total, COUNT(offering_id) as linked, COUNT(*)-COUNT(offering_id) as unlinked
            FROM scheduled_sessions WHERE scenario_id = %s
        """, (SCENARIO,))
        r = cur.fetchone()
        print(f"\nFinal: {r['linked']}/{r['total']} sessions linked, {r['unlinked']} still NULL")

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
