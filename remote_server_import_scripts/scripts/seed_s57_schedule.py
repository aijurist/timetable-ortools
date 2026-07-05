"""
seed_s57_schedule.py
====================
Prod seed: read committed CSV/JSON from data/legacy_seeds/ and populate
scheduled_sessions, cohorts (offering_buckets + course_offerings), and
publish a SolverJob for the given scenario.

No solver dependency — reads the committed seed files directly.

Usage (from backend/):
    python scripts/seed_s57_schedule.py
    python scripts/seed_s57_schedule.py --scenario-id <uuid>
    python scripts/seed_s57_schedule.py --dry-run

Idempotent: safe to re-run. Each run clears and re-inserts sessions + cohorts,
then creates a new SolverJob row and marks the scenario as COMPLETED/published.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

# Ensure our prints appear before subprocess output
sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]

import psycopg2
import psycopg2.extras

SCRIPT_DIR  = Path(__file__).parent.resolve()
BACKEND_DIR = SCRIPT_DIR.parent
SEEDS_DIR   = BACKEND_DIR / "data" / "legacy_seeds"

LAB_CSV    = SEEDS_DIR / "lab_schedule.csv"
THEORY_CSV = SEEDS_DIR / "theory_schedule.csv"
TELEMETRY  = SEEDS_DIR / "s57_grouping_telemetry.json"

DEFAULT_SCENARIO_ID = "b5e52d55-f574-47de-b327-a03e06d70b87"


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


def run_step(label: str, cmd: list[str]) -> None:
    print(f"\n{'='*60}")
    print(f"STEP : {label}")
    print(f"CMD  : {' '.join(cmd)}")
    print("="*60)
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        sys.exit(f"Step '{label}' failed (exit {result.returncode})")


def publish_solver_job(scenario_id: str, dry_run: bool) -> None:
    print(f"\n{'='*60}")
    print("STEP : Publish SolverJob")
    print("="*60)

    if dry_run:
        print("[DRY RUN] Would insert SolverJob and mark scenario COMPLETED")
        return

    dsn = _get_dsn()
    conn = psycopg2.connect(dsn)
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute(
        "SELECT COUNT(*) AS n FROM scheduled_sessions WHERE scenario_id = %s",
        (scenario_id,),
    )
    session_count: int = cur.fetchone()["n"]

    cur.execute(
        "SELECT COUNT(*) AS n FROM offering_buckets WHERE scenario_id = %s",
        (scenario_id,),
    )
    bucket_count: int = cur.fetchone()["n"]

    job_id = str(uuid.uuid4())
    score_summary = {
        "sessions": session_count,
        "buckets": bucket_count,
        "source": "legacy_seed",
        "seed_files": {
            "lab_csv": LAB_CSV.name,
            "theory_csv": THEORY_CSV.name,
            "telemetry": TELEMETRY.name,
        },
    }
    config_snapshot = {
        "scheduler": "legacy_seed",
        "seed_version": "s57_combined",
    }

    cur.execute(
        """
        INSERT INTO solver_jobs
            (id, scenario_id, constraints_snapshot, config_snapshot,
             result_schedule, status, score_summary, started_at, completed_at)
        VALUES (%s::uuid, %s::uuid, %s, %s, %s, 'FEASIBLE', %s, NOW(), NOW())
        """,
        (
            job_id, scenario_id,
            json.dumps({}),
            json.dumps(config_snapshot),
            json.dumps([]),
            json.dumps(score_summary),
        ),
    )

    cur.execute(
        """
        UPDATE scenarios
        SET status           = 'COMPLETED',
            current_job_id   = %s::uuid,
            published_job_id = %s::uuid,
            published_at     = NOW(),
            is_dirty         = false,
            updated_at       = NOW()
        WHERE id = %s
        """,
        (job_id, job_id, scenario_id),
    )

    conn.commit()
    cur.close()
    conn.close()

    print(f"  SolverJob : {job_id}")
    print(f"  Scenario  : {scenario_id} -> COMPLETED, published_job_id = {job_id}")
    print(f"  sessions  : {session_count}")
    print(f"  buckets   : {bucket_count}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--scenario-id",
        default=DEFAULT_SCENARIO_ID,
        help=f"Scenario UUID to seed (default: {DEFAULT_SCENARIO_ID})",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would happen; no DB writes",
    )
    args = ap.parse_args()

    scenario_id = args.scenario_id
    dry_run     = args.dry_run

    for p in (LAB_CSV, THEORY_CSV, TELEMETRY):
        if not p.exists():
            sys.exit(f"Seed file not found: {p}")

    import pandas as pd
    lab_rows    = len(pd.read_csv(LAB_CSV))
    theory_rows = len(pd.read_csv(THEORY_CSV))
    telem_depts = len(json.loads(TELEMETRY.read_text(encoding="utf-8")).get("departments", []))
    print(f"Seed files ready:")
    print(f"  {LAB_CSV.name}    : {lab_rows} rows")
    print(f"  {THEORY_CSV.name} : {theory_rows} rows")
    print(f"  {TELEMETRY.name}  : {telem_depts} departments")

    py = [sys.executable, "-X", "utf8"]

    # ── Step 0: ensure all rooms, faculty, courses exist ──────────────────────
    ensure_cmd = [
        *py,
        str(SCRIPT_DIR / "seed_ensure_entities.py"),
        "--scenario-id", scenario_id,
    ]
    if dry_run:
        ensure_cmd.append("--dry-run")
    run_step("Ensure entities (rooms / faculty / courses / PE pools — dry)", ensure_cmd)

    # ── Step 1: import scheduled_sessions ─────────────────────────────────────
    import_cmd = [
        *py,
        str(SCRIPT_DIR / "import_legacy_schedule.py"),
        "--scenario-id", scenario_id,
        "--lab-csv",    str(LAB_CSV),
        "--theory-csv", str(THEORY_CSV),
    ]
    if dry_run:
        import_cmd.append("--dry-run")
    run_step("Import sessions (scheduled_sessions)", import_cmd)

    # ── Step 2: create OfferingBuckets + CourseOfferings (regular cohorts) ────
    cohort_cmd = [
        *py,
        str(SCRIPT_DIR / "setup_cohorts_from_telemetry.py"),
        "--scenario-id",    scenario_id,
        "--telemetry-file", str(TELEMETRY),
    ]
    if dry_run:
        cohort_cmd.append("--dry-run")
    run_step("Setup cohorts (offering_buckets + course_offerings)", cohort_cmd)

    # ── Step 2b: build PE / OE elective pools ─────────────────────────────────
    pe_cmd = [
        *py,
        str(SCRIPT_DIR / "seed_ensure_entities.py"),
        "--scenario-id", scenario_id,
        "--pe-pools-only",
    ]
    if dry_run:
        pe_cmd.append("--dry-run")
    run_step("PE / OE elective pools", pe_cmd)

    # ── Step 3: publish SolverJob + mark scenario COMPLETED ───────────────────
    publish_solver_job(scenario_id, dry_run)

    print("\nSeed complete.")
    if dry_run:
        print("(dry run — no changes written)")


if __name__ == "__main__":
    main()
