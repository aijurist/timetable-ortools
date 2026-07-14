"""Solve and validate every Semester-3 department independently.

Each department receives the same CP-SAT budgets and sees only the production
schedule locks, eliminating department-order effects. Outputs are written below
output/timetables/dept_by_dept_hard_deterministic/<department-slug>/ by default.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


DEPARTMENTS = (
    "Aeronautical Engineering",
    "Artificial Intelligence and Data Science",
    "Artificial Intelligence and Machine Learning",
    "Automobile Engineering",
    "Biomedical Engineering",
    "Biotechnology",
    "Chemical Engineering",
    "Civil Engineering",
    "Computer Science and Business Systems",
    "Computer Science and Design",
    "Computer Science and Engineering Cyber Security",
    "Computer Science and Engineering",
    "Electrical and Electronics Engineering",
    "Electronics and Communication Engineering",
    "Food Technology",
    "Information Technology",
    "Mechanical Engineering",
    "Mechatronics Engineering",
    "Robotics and Automation",
)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _stream(command: list[str], *, env: dict[str, str], cwd: Path) -> tuple[int, str]:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    lines: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        print(line, end="", flush=True)
        lines.append(line)
    return process.wait(), "".join(lines)


def _status_matches(output: str) -> list[str]:
    return re.findall(r"->\s+(OPTIMAL|FEASIBLE|INFEASIBLE|UNKNOWN|MODEL_INVALID)", output)


def _mode(output: str, name: str, default: str = "") -> str:
    matches = re.findall(rf"{re.escape(name)}=([a-zA-Z0-9_-]+)", output)
    return matches[-1] if matches else default


def run(args: argparse.Namespace) -> int:
    root = Path(__file__).resolve().parents[1]
    departments = tuple(args.department) if args.department else DEPARTMENTS
    report_root = root / "output" / "timetables" / args.run_tag
    report_root.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, object]] = []

    for index, department in enumerate(departments, start=1):
        slug = _slug(department)
        output_dir = report_root / slug
        output_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n=== [{index}/{len(departments)}] {department} ===", flush=True)
        env = dict(os.environ)
        env.update(
            {
                "PYTHONPATH": ".",
                "DEPT_FILTER": department,
                "RUN_TAG": f"{args.run_tag}/{slug}",
                "PHASE1_TIME": str(args.phase1_time),
                "PHASE2_TIME": str(args.phase2_time),
                "DETERMINISTIC_SOLVE": "1",
                "DETERMINISTIC_TIE_BREAKER": "1",
                "SOLVER_WORKERS": "1",
                "OPTIMIZE_PHASE1": "1",
                "DEBUG_DEPT": "1",
                "FIXED_THEORY_CSV": "prod/theory_schedule_lock.csv",
                "FIXED_LAB_CSV": "prod/lab_schedule_lock.csv",
            }
        )
        started = time.monotonic()
        exit_code, output = _stream(
            [sys.executable, "-u", "scripts/seeded_bundle.py"],
            env=env,
            cwd=root,
        )
        (output_dir / "solver.log").write_text(output, encoding="utf-8")
        statuses = _status_matches(output)
        phase1_status = statuses[0] if statuses else "MISSING"
        phase2_status = statuses[-1] if len(statuses) > 1 else "MISSING"
        theory_path = output_dir / "theory_schedule_second_year.csv"
        lab_path = output_dir / "lab_schedule_second_year.csv"
        schedule_path = output_dir / "schedule.json"
        theory_rows = 0
        lab_rows = 0
        if schedule_path.is_file():
            payload = json.loads(schedule_path.read_text(encoding="utf-8"))
            theory_rows = len(payload.get("theory_entries", ()))
            lab_rows = len(payload.get("lab_entries", ()))

        validation_status = "NOT_RUN"
        validation_payload: dict[str, object] = {}
        if theory_rows and theory_path.is_file() and lab_path.is_file():
            validation_path = output_dir / "validation.json"
            validation = subprocess.run(
                [
                    sys.executable,
                    "scripts/validate_second_year_schedule.py",
                    "--theory",
                    str(theory_path),
                    "--lab",
                    str(lab_path),
                    "--json-output",
                    str(validation_path),
                ],
                cwd=root,
                text=True,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
            )
            if validation.stdout:
                print(validation.stdout, end="", flush=True)
            if validation.stderr:
                print(validation.stderr, end="", flush=True)
            if validation_path.is_file():
                validation_payload = json.loads(validation_path.read_text(encoding="utf-8"))
                validation_status = str(validation_payload.get("status", "UNKNOWN"))
            elif validation.returncode:
                validation_status = "ERROR"

        elapsed = round(time.monotonic() - started, 2)
        result = {
            "department": department,
            "phase1_status": phase1_status,
            "phase2_status": phase2_status,
            "certified_optimal": phase1_status == "OPTIMAL" and phase2_status == "OPTIMAL",
            "late_mode": _mode(output, "late"),
            "lunch_mode": _mode(output, "lunch", "hard"),
            "interleave": _mode(output, "il"),
            "theory_rows": theory_rows,
            "lab_rows": lab_rows,
            "physical_kutty_sessions": validation_payload.get("physical_kutty_sessions", 0),
            "validation_status": validation_status,
            "violation_counts": validation_payload.get("violation_counts", {}),
            "process_exit_code": exit_code,
            "elapsed_seconds": elapsed,
            "output_dir": str(output_dir),
        }
        results.append(result)
        print(
            f"RESULT {department}: P1={phase1_status} P2={phase2_status} "
            f"validation={validation_status} lunch={result['lunch_mode']} "
            f"elapsed={elapsed:.2f}s",
            flush=True,
        )

    json_path = report_root / "report.json"
    csv_path = report_root / "report.csv"
    json_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = (
            "department",
            "phase1_status",
            "phase2_status",
            "certified_optimal",
            "late_mode",
            "lunch_mode",
            "interleave",
            "theory_rows",
            "lab_rows",
            "physical_kutty_sessions",
            "validation_status",
            "process_exit_code",
            "elapsed_seconds",
            "output_dir",
        )
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            writer.writerow({key: result.get(key) for key in fieldnames})
    print(f"\nReport: {json_path}\nCSV: {csv_path}", flush=True)
    return 0 if all(
        result["certified_optimal"] and result["validation_status"] == "PASS"
        for result in results
    ) else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--department", action="append", choices=DEPARTMENTS)
    parser.add_argument("--phase1-time", type=int, default=180)
    parser.add_argument("--phase2-time", type=int, default=300)
    parser.add_argument("--run-tag", default="dept_by_dept_hard_deterministic")
    return parser


if __name__ == "__main__":
    raise SystemExit(run(_parser().parse_args()))
