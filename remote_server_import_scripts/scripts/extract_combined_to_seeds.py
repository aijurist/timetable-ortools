"""
extract_combined_to_seeds.py
=============================
Copy the combined scheduler's output (lab CSV, theory CSV, telemetry)
into backend/data/legacy_seeds/ so it can be committed and used by
seed_s57_schedule.py on prod.

Usage:
    python backend/scripts/extract_combined_to_seeds.py
    python backend/scripts/extract_combined_to_seeds.py --output-dir <path>

With no --output-dir, scans the combined scheduler's output root and picks
the most recent FEASIBLE or OPTIMAL run.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

COMBINED_OUTPUT_ROOT = Path(
    "E:/coding/grind_project/timetable_scheduler/output/all_s57_combined"
)

SCRIPT_DIR  = Path(__file__).parent.resolve()
BACKEND_DIR = SCRIPT_DIR.parent
SEEDS_DIR   = BACKEND_DIR / "data" / "legacy_seeds"


def _solver_status(run_dir: Path) -> str:
    metrics = run_dir / "solver_metrics.json"
    if not metrics.exists():
        return "UNKNOWN"
    data = json.loads(metrics.read_text(encoding="utf-8"))
    return str(data.get("status", "UNKNOWN")).upper()


def find_best_run(output_root: Path) -> Path:
    candidates = sorted(
        [d for d in output_root.iterdir() if d.is_dir() and d.name[0].isdigit()],
        reverse=True,
    )
    for d in candidates:
        status = _solver_status(d)
        if status in ("FEASIBLE", "OPTIMAL"):
            return d
    if candidates:
        print(f"[WARN] No FEASIBLE/OPTIMAL run found — using most recent: {candidates[0].name}")
        return candidates[0]
    sys.exit(f"No run directories found in {output_root}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--output-dir",
        default=None,
        help="Explicit run directory to use (default: auto-detect most recent FEASIBLE/OPTIMAL)",
    )
    args = ap.parse_args()

    run_dir = Path(args.output_dir) if args.output_dir else find_best_run(COMBINED_OUTPUT_ROOT)
    print(f"Source run dir : {run_dir}")
    print(f"Status         : {_solver_status(run_dir)}")

    csv_dir  = run_dir / "csv"
    lab_src  = csv_dir / "lab_schedule.csv"
    th_src   = csv_dir / "theory_schedule.csv"
    tel_src  = run_dir / "grouping_telemetry.json"

    for p in (lab_src, th_src, tel_src):
        if not p.exists():
            sys.exit(f"Expected file not found: {p}")

    SEEDS_DIR.mkdir(parents=True, exist_ok=True)

    lab_dst = SEEDS_DIR / "s57_lab_schedule.csv"
    th_dst  = SEEDS_DIR / "s57_theory_schedule.csv"
    tel_dst = SEEDS_DIR / "s57_grouping_telemetry.json"

    shutil.copy2(lab_src,  lab_dst)
    shutil.copy2(th_src,   th_dst)
    shutil.copy2(tel_src,  tel_dst)

    import pandas as pd
    lab_rows  = len(pd.read_csv(lab_dst))
    th_rows   = len(pd.read_csv(th_dst))
    tel_depts = len(json.loads(tel_dst.read_text(encoding="utf-8")).get("departments", []))

    print(f"\nCopied to {SEEDS_DIR}/:")
    print(f"  s57_lab_schedule.csv          : {lab_rows} rows")
    print(f"  s57_theory_schedule.csv       : {th_rows} rows")
    print(f"  s57_grouping_telemetry.json   : {tel_depts} departments")
    print("\nNow commit these files and run seed_s57_schedule.py on prod.")


if __name__ == "__main__":
    main()
