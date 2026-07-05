"""
run_s57_full_pipeline.py
========================
End-to-end pipeline for Sem5 + Sem7 legacy schedule import:

  Step 1  Run all S5/S7 dept yamls via legacy CP-SAT solver
  Step 2  Collect successful output directories
  Step 3  Import combined CSVs → scheduled_sessions  (via import_legacy_schedule.py)
  Step 4  Create cohorts from merged telemetry       (via setup_cohorts_from_telemetry.py)
  Step 5  Insert SolverJob record + publish to Scenario

Usage (from backend/):
    python scripts/run_s57_full_pipeline.py --scenario-id <uuid>
    python scripts/run_s57_full_pipeline.py --scenario-id <uuid> --dry-run
    python scripts/run_s57_full_pipeline.py --scenario-id <uuid> --skip-solver \\
        --output-dir <dir1> --output-dir <dir2> ...

Notes:
- AIDS Sem5 is always skipped for cohort creation (already set up in app).
- ECE S5, EEE S5, CSE S5 are soft-constrained → may use T9/T10 if needed.
- Script is idempotent: re-running clears and reimports sessions/cohorts.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR  = Path(__file__).parent.resolve()
BACKEND_DIR = SCRIPT_DIR.parent
SOLVER_DIR  = Path(r"E:\coding\grind_project\timetable_scheduler")
SOLVER_PY   = SOLVER_DIR / "env" / "Scripts" / "python.exe"
EXPORT_DIR  = SOLVER_DIR / "data" / "exported"
OUTPUT_DIR  = SOLVER_DIR / "output"

# ── Dept / semester combos (all S5 + S7) ──────────────────────────────────────
COMBOS: list[tuple[str, int, str]] = [
    ("aeronautical_engineering",              7, "Aeronautical Engineering"),
    ("aeronautical_engineering",              5, "Aeronautical Engineering"),
    ("artificial_intelligence_data_science",  7, "Artificial Intelligence & Data Science"),
    ("artificial_intelligence_data_science",  5, "Artificial Intelligence & Data Science"),
    ("artificial_intelligence_machine_learning", 7, "Artificial Intelligence & Machine Learning"),
    ("artificial_intelligence_machine_learning", 5, "Artificial Intelligence & Machine Learning"),
    ("automobile_engineering",                7, "Automobile Engineering"),
    ("automobile_engineering",                5, "Automobile Engineering"),
    ("biomedical_engineering",                7, "Biomedical Engineering"),
    ("biomedical_engineering",                5, "Biomedical Engineering"),
    ("biotechnology",                         7, "Biotechnology"),
    ("biotechnology",                         5, "Biotechnology"),
    ("chemical_engineering",                  7, "Chemical Engineering"),
    ("chemical_engineering",                  5, "Chemical Engineering"),
    ("civil_engineering",                     7, "Civil Engineering"),
    ("civil_engineering",                     5, "Civil Engineering"),
    ("computer_science_business_systems",     7, "Computer Science & Business Systems"),
    ("computer_science_business_systems",     5, "Computer Science & Business Systems"),
    ("computer_science_design",               7, "Computer Science & Design"),
    ("computer_science_design",               5, "Computer Science & Design"),
    ("computer_science_engineering",          7, "Computer Science & Engineering"),
    ("computer_science_engineering",          5, "Computer Science & Engineering"),
    ("computer_science_engineering_cyber_security", 7, "Computer Science & Engineering (Cyber Security)"),
    ("computer_science_engineering_cyber_security", 5, "Computer Science & Engineering (Cyber Security)"),
    ("electrical_electronics_engineering",    7, "Electrical & Electronics Engineering"),
    ("electrical_electronics_engineering",    5, "Electrical & Electronics Engineering"),
    ("electronics_communication_engineering", 7, "Electronics & Communication Engineering"),
    ("electronics_communication_engineering", 5, "Electronics & Communication Engineering"),
    ("food_technology",                       7, "Food Technology"),
    ("food_technology",                       5, "Food Technology"),
    ("information_technology",                7, "Information Technology"),
    ("information_technology",                5, "Information Technology"),
    ("mechanical_engineering",                7, "Mechanical Engineering"),
    ("mechanical_engineering",                5, "Mechanical Engineering"),
    ("mechatronics_engineering",              7, "Mechatronics Engineering"),
    ("mechatronics_engineering",              5, "Mechatronics Engineering"),
    ("robotics_automation",                   7, "Robotics & Automation"),
    ("robotics_automation",                   5, "Robotics & Automation"),
]

# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_dsn() -> str:
    import os
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


def _solver_status(out_dir: Path) -> str:
    """Read status from solver_metrics.json. Returns 'FEASIBLE', 'OPTIMAL', 'INFEASIBLE', or 'UNKNOWN'."""
    metrics_file = out_dir / "solver_metrics.json"
    if not metrics_file.exists():
        return "UNKNOWN"
    try:
        data = json.loads(metrics_file.read_text(encoding="utf-8"))
        return data.get("solver", {}).get("status", "UNKNOWN").upper()
    except Exception:
        return "UNKNOWN"


def _parse_output_dir(stdout: str) -> Path | None:
    """Parse 'Output generated in: <path>' from solver stdout."""
    for line in stdout.splitlines():
        m = re.search(r"Output generated in:\s+(.+)", line)
        if m:
            p = Path(m.group(1).strip())
            if p.exists():
                return p
    return None


def collect_best_output_dirs() -> list[tuple[str, int, str, Path]]:
    """
    Scan OUTPUT_DIR for the most recent FEASIBLE/OPTIMAL run per (dept, sem).
    Returns successes list in COMBO order.
    """
    dirs = sorted(
        [d for d in OUTPUT_DIR.iterdir() if d.is_dir()],
        key=lambda d: d.name,
    )
    # Build map: (dept_name, sem) → most recent FEASIBLE dir
    best: dict[tuple[str, int], Path] = {}
    for d in dirs:
        telem_f   = d / "grouping_telemetry.json"
        metrics_f = d / "solver_metrics.json"
        if not (telem_f.exists() and metrics_f.exists()):
            continue
        status = _solver_status(d)
        if status not in ("FEASIBLE", "OPTIMAL"):
            continue
        try:
            td    = json.loads(telem_f.read_text(encoding="utf-8"))
            depts = td.get("departments", [])
        except Exception:
            continue
        if not depts:
            continue
        key = (depts[0]["department"], int(depts[0]["semester"]))
        best[key] = d  # newer dirs overwrite older ones (sorted ascending)

    # Build ordered successes aligned to COMBOS
    successes: list[tuple[str, int, str, Path]] = []
    missing:   list[tuple[str, int, str]]       = []
    for slug, sem, label in COMBOS:
        # Try exact label match; fall back to partial match
        key = (label, sem)
        d = best.get(key)
        if d is None:
            # Try case-insensitive partial match on dept name
            for (dept_name, dsem), ddir in best.items():
                if dsem == sem and label.lower() in dept_name.lower():
                    d = ddir
                    break
        if d:
            successes.append((slug, sem, label, d))
        else:
            missing.append((slug, sem, label))

    if missing:
        print(f"[WARN] {len(missing)} dept/sem combos have no feasible output dir:")
        for slug, sem, label in missing:
            print(f"  Sem{sem}  {label}")

    print(f"Auto-selected {len(successes)}/{len(COMBOS)} output dirs.\n")
    return successes


# ── Step 1: Run solver for all combos ─────────────────────────────────────────

def run_solver(dry_run: bool) -> list[tuple[str, int, str, Path]]:
    """
    Returns list of (slug, sem, label, output_dir) for each FEASIBLE/OPTIMAL run.
    """
    successes: list[tuple[str, int, str, Path]] = []
    failures:  list[tuple[str, int, str, str]]   = []

    for slug, sem, label in COMBOS:
        yaml_p = EXPORT_DIR / f"scheduler_{slug}_s{sem}.yaml"
        if not yaml_p.exists():
            print(f"  [SKIP]  Sem{sem}  {label}  — yaml not found")
            failures.append((slug, sem, label, "NO_YAML"))
            continue

        tag = f"Sem{sem}  {label}"
        print(f"\n  Running {tag} ...", flush=True)

        if dry_run:
            print(f"    [DRY RUN] would run: python -m src.pipeline.cli --config {yaml_p.name}")
            continue

        t0 = time.time()
        try:
            proc = subprocess.run(
                [str(SOLVER_PY), "-X", "utf8", "-m", "src.pipeline.cli",
                 "--config", str(yaml_p)],
                cwd=str(SOLVER_DIR),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=600,
            )
            combined = proc.stdout + proc.stderr
        except subprocess.TimeoutExpired:
            print(f"    TIMEOUT after 600s")
            failures.append((slug, sem, label, "TIMEOUT"))
            continue

        elapsed = time.time() - t0
        out_dir = _parse_output_dir(combined)

        if out_dir is None:
            print(f"    FAILED — no output dir in stdout  ({elapsed:.0f}s)")
            failures.append((slug, sem, label, "NO_OUTPUT"))
            continue

        status = _solver_status(out_dir)
        ok = status in ("FEASIBLE", "OPTIMAL")
        mark = "OK" if ok else "FAIL"
        print(f"    [{mark}]  {status}  → {out_dir.name}  ({elapsed:.0f}s)")

        if ok:
            successes.append((slug, sem, label, out_dir))
        else:
            failures.append((slug, sem, label, status))

    print(f"\n{'='*60}")
    print(f"Solver pass: {len(successes)} OK, {len(failures)} failed")
    if failures:
        print("Failed:")
        for slug, sem, label, st in failures:
            print(f"  Sem{sem}  {label}  → {st}")
    return successes


# ── Step 2–3: Import CSVs ──────────────────────────────────────────────────────

def run_import(
    successes: list[tuple[str, int, str, Path]],
    scenario_id: str,
    dry_run: bool,
) -> None:
    import tempfile
    try:
        import pandas as pd
    except ImportError:
        sys.exit("pandas not installed — run: pip install pandas")

    if not successes:
        print("No successful runs to import. Aborting.")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"Step 3: Merging + importing CSVs from {len(successes)} output dirs ...")

    # Merge all lab + theory CSVs across all successful runs
    lab_frames, theory_frames = [], []
    for _, _, _, d in successes:
        lab_f    = d / "csv" / "lab_schedule.csv"
        theory_f = d / "csv" / "theory_schedule.csv"
        if lab_f.exists():
            lab_frames.append(pd.read_csv(lab_f))
        if theory_f.exists():
            theory_frames.append(pd.read_csv(theory_f))

    merged_lab    = pd.concat(lab_frames,    ignore_index=True) if lab_frames    else pd.DataFrame()
    merged_theory = pd.concat(theory_frames, ignore_index=True) if theory_frames else pd.DataFrame()
    print(f"  Combined: {len(merged_lab)} lab rows, {len(merged_theory)} theory rows")

    # Write merged CSVs to temp files so import_legacy_schedule.py can read them
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_lab    = Path(tmpdir) / "lab_schedule.csv"
        tmp_theory = Path(tmpdir) / "theory_schedule.csv"
        merged_lab.to_csv(tmp_lab,    index=False)
        merged_theory.to_csv(tmp_theory, index=False)

        cmd = [
            sys.executable, "-X", "utf8", str(SCRIPT_DIR / "import_legacy_schedule.py"),
            "--scenario-id", scenario_id,
            "--lab-csv",    str(tmp_lab),
            "--theory-csv", str(tmp_theory),
        ]
        if dry_run:
            cmd.append("--dry-run")

        if dry_run:
            print("  [DRY RUN]")
        result = subprocess.run(cmd, cwd=str(BACKEND_DIR))
        if result.returncode != 0:
            sys.exit(f"import_legacy_schedule.py failed (rc={result.returncode})")


# ── Step 4: Create cohorts ─────────────────────────────────────────────────────

def run_cohorts(
    successes: list[tuple[str, int, str, Path]],
    scenario_id: str,
    dry_run: bool,
) -> None:
    telem_paths = [d / "grouping_telemetry.json" for _, _, _, d in successes]
    telem_paths = [p for p in telem_paths if p.exists()]

    if not telem_paths:
        print("\n[WARN] No telemetry files found — skipping cohort creation.")
        return

    cmd = [
        sys.executable, "-X", "utf8", str(SCRIPT_DIR / "setup_cohorts_from_telemetry.py"),
        "--scenario-id", scenario_id,
    ]
    for p in telem_paths:
        cmd += ["--telemetry-file", str(p)]
    if dry_run:
        cmd.append("--dry-run")

    print(f"\n{'='*60}")
    print(f"Step 4: Creating cohorts from {len(telem_paths)} telemetry files ...")
    if dry_run:
        print("  [DRY RUN]")

    result = subprocess.run(cmd, cwd=str(BACKEND_DIR))
    if result.returncode != 0:
        sys.exit(f"setup_cohorts_from_telemetry.py failed (rc={result.returncode})")


# ── Step 5: SolverJob + Scenario publish ──────────────────────────────────────

def publish_solver_run(
    successes: list[tuple[str, int, str, Path]],
    scenario_id: str,
    dry_run: bool,
) -> None:
    import psycopg2
    import psycopg2.extras

    print(f"\n{'='*60}")
    print("Step 5: Publishing SolverJob to scenario ...")

    # Build score summary from individual solver_metrics
    total_sessions = 0
    total_wall = 0.0
    dept_statuses: dict[str, str] = {}
    for slug, sem, label, out_dir in successes:
        metrics_f = out_dir / "solver_metrics.json"
        if metrics_f.exists():
            m = json.loads(metrics_f.read_text(encoding="utf-8"))
            s = m.get("solver", {})
            total_wall += s.get("wall_time", 0)
        dept_statuses[f"{label}_S{sem}"] = _solver_status(out_dir)

    # Count sessions from each dept's CSV output
    for _, _, _, out_dir in successes:
        for csv_f in [(out_dir / "csv" / "lab_schedule.csv"),
                      (out_dir / "csv" / "theory_schedule.csv")]:
            if csv_f.exists():
                try:
                    total_sessions += sum(1 for _ in csv_f.read_text(encoding="utf-8").splitlines()) - 1
                except Exception:
                    pass

    score_summary = {
        "note":          "legacy import — S5/S7 all departments",
        "sessions":      total_sessions,
        "wall_seconds":  round(total_wall, 1),
        "dept_statuses": dept_statuses,
        "dept_count":    len(successes),
    }
    config_snapshot = {
        "source":    "legacy_scheduler",
        "mode":      "TRADITIONAL",
        "semesters": [5, 7],
        "combos":    len(COMBOS),
    }
    constraints_snapshot: dict = {}

    job_id = str(uuid.uuid4())

    print(f"  Job ID: {job_id}")
    print(f"  Sessions: {total_sessions}")
    print(f"  Wall time: {total_wall:.0f}s across {len(successes)} depts")
    if dry_run:
        print("  [DRY RUN] — no DB writes")
        return

    dsn  = _get_dsn()
    conn = psycopg2.connect(dsn)
    conn.autocommit = False
    cur  = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    try:
        # Insert SolverJob
        cur.execute("""
            INSERT INTO solver_jobs
                (id, scenario_id, constraints_snapshot, config_snapshot,
                 result_schedule, status, score_summary, started_at, completed_at)
            VALUES (%s::uuid, %s::uuid, %s, %s, %s, 'FEASIBLE', %s, NOW(), NOW())
        """, (
            job_id, scenario_id,
            json.dumps(constraints_snapshot),
            json.dumps(config_snapshot),
            json.dumps([]),           # no in-memory schedule blob needed
            json.dumps(score_summary),
        ))

        # Update scenario: publish the job, mark COMPLETED
        cur.execute("""
            UPDATE scenarios
            SET status          = 'COMPLETED',
                current_job_id  = %s::uuid,
                published_job_id = %s::uuid,
                published_at    = NOW(),
                is_dirty        = false,
                updated_at      = NOW()
            WHERE id = %s
        """, (job_id, job_id, scenario_id))

        conn.commit()
        print(f"  Committed — scenario {scenario_id[:8]}... now COMPLETED, job {job_id[:8]}... published.")

    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="S5/S7 full pipeline: solve → import → cohorts → publish"
    )
    ap.add_argument("--scenario-id", required=True,
                    help="UUID of the app Scenario to target")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print plan without writing to DB or running solver")
    ap.add_argument("--skip-solver", action="store_true",
                    help="Skip the solve step and use --output-dir to supply existing output dirs")
    ap.add_argument("--auto-dirs", action="store_true",
                    help="Auto-select best existing FEASIBLE output dir per dept (implies --skip-solver)")
    ap.add_argument("--output-dir", dest="output_dirs", action="append", metavar="PATH",
                    default=None,
                    help="Existing solver output dir(s). Repeatable. Used with --skip-solver.")
    args = ap.parse_args()

    print(f"{'='*60}")
    print("S5/S7 Full Pipeline")
    print(f"Scenario : {args.scenario_id}")
    print(f"Dry run  : {args.dry_run}")
    print(f"{'='*60}\n")

    if args.auto_dirs:
        # Auto-select best FEASIBLE output dir per dept from OUTPUT_DIR
        successes: list[tuple[str, int, str, Path]] = collect_best_output_dirs()
    elif args.skip_solver:
        if not args.output_dirs:
            ap.error("--skip-solver requires at least one --output-dir")
        # Build successes list from provided dirs
        provided: list[Path] = [Path(d) for d in args.output_dirs]
        successes = []
        for i, d in enumerate(provided):
            status = _solver_status(d)
            if status not in ("FEASIBLE", "OPTIMAL"):
                print(f"[WARN] Skipping {d.name} — status={status}")
                continue
            telem_f = d / "grouping_telemetry.json"
            if telem_f.exists():
                td = json.loads(telem_f.read_text(encoding="utf-8"))
                depts = td.get("departments", [])
                label = depts[0]["department"] if depts else f"dir_{i}"
                sem   = int(depts[0].get("semester", 0))
            else:
                label, sem = f"dir_{i}", 0
            slug = label.lower().replace(" ", "_").replace("&", "").replace("(", "").replace(")", "")
            successes.append((slug, sem, label, d))
        print(f"Using {len(successes)} provided output dirs.\n")
    else:
        # Step 1: Run solver
        print("Step 1: Running legacy solver for all S5/S7 departments ...\n")
        successes = run_solver(args.dry_run)

    if not successes and not args.dry_run:
        sys.exit("No feasible solutions — aborting pipeline.")

    # Step 2 is just collecting the dirs — already done above.

    # Step 3: Import CSVs
    run_import(successes, args.scenario_id, args.dry_run)

    # Step 4: Create cohorts
    run_cohorts(successes, args.scenario_id, args.dry_run)

    # Step 5: Publish
    publish_solver_run(successes, args.scenario_id, args.dry_run)

    print(f"\n{'='*60}")
    print("Pipeline complete.")
    if args.dry_run:
        print("(Dry run — no changes written.)")


if __name__ == "__main__":
    main()
