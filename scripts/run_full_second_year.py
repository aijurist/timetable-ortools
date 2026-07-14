"""Run, certify, and validate the complete 19-department second-year timetable.

This is the production entrypoint intended for the solver machine. It
uses the two fixed schedule locks in ``prod/`` and writes an isolated complete
run below ``output/timetables/second_year_full/`` by default.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path


EXPECTED_DEPARTMENT_COUNT = 19
LOCK_HASHES = {
    "prod/theory_schedule_lock.csv": "42303b4d6991cbfe95b7c0e03513746193598a8c061580c9a15afe43f332eb66",
    "prod/lab_schedule_lock.csv": "f0eae7eb337736393e57eb85461956c0b0da8a1e797794458f6241580eb7f9fd",
}
STATUSES = ("OPTIMAL", "FEASIBLE", "INFEASIBLE", "UNKNOWN", "MODEL_INVALID")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_locks(root: Path) -> dict[str, str]:
    actual: dict[str, str] = {}
    for relative, expected in LOCK_HASHES.items():
        path = root / relative
        if not path.is_file():
            raise FileNotFoundError(f"Required production lock is missing: {path}")
        digest = _sha256(path)
        actual[relative] = digest
        if digest != expected:
            raise RuntimeError(
                f"Production lock does not match copy/kutty_concepts: {relative}\n"
                f"expected {expected}\nactual   {digest}"
            )
    return actual


def _stream(command: list[str], *, cwd: Path, env: dict[str, str]) -> tuple[int, str]:
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


def _phase_statuses(output: str) -> tuple[list[str], list[str]]:
    before, marker, after = output.partition("PHASE 2:")
    if not marker:
        return [], []
    pattern = rf"->\s+({'|'.join(STATUSES)})"
    phase1 = re.findall(pattern, before)
    phase2 = re.findall(pattern, after)
    return phase1[-EXPECTED_DEPARTMENT_COUNT:], phase2[:EXPECTED_DEPARTMENT_COUNT]


def run(args: argparse.Namespace) -> int:
    root = Path(__file__).resolve().parents[1]
    lock_hashes = _verify_locks(root)
    output_dir = root / "output" / "timetables" / args.run_tag
    output_dir.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    env.pop("DEPT_FILTER", None)
    env.update(
        {
            "PYTHONPATH": ".",
            "RUN_TAG": args.run_tag,
            "PHASE1_TIME": str(args.phase1_time),
            "PHASE2_TIME": str(args.phase2_time),
            "DETERMINISTIC_TIE_BREAKER": "1",
            "DIRECT_SINGLE_WORKER": "0",
            "SOLVER_WORKERS": str(args.workers),
            "OPTIMIZE_PHASE1": "1",
            "PHASE1_OBJECTIVE_SCOPE": "lab_cells",
            "PACK_COMBINED_CELLS": "1",
            "PHASE1_ABSOLUTE_GAP": "0",
            "DEBUG_DEPT": "1",
            "FIXED_THEORY_CSV": "prod/theory_schedule_lock.csv",
            "FIXED_LAB_CSV": "prod/lab_schedule_lock.csv",
        }
    )

    print("Verified production schedule locks from copy/kutty_concepts.", flush=True)
    exit_code, output = _stream(
        [sys.executable, "-u", "scripts/seeded_bundle.py"],
        cwd=root,
        env=env,
    )
    (output_dir / "solver.log").write_text(output, encoding="utf-8")

    phase1, phase2 = _phase_statuses(output)
    schedule_path = output_dir / "schedule.json"
    theory_path = output_dir / "theory_schedule_second_year.csv"
    lab_path = output_dir / "lab_schedule_second_year.csv"
    departments: list[str] = []
    if schedule_path.is_file():
        payload = json.loads(schedule_path.read_text(encoding="utf-8"))
        entries = payload.get("theory_entries", []) + payload.get("lab_entries", [])
        departments = sorted({str(row.get("department")) for row in entries if row.get("department")})

    validation_path = output_dir / "validation.json"
    validation_exit = 1
    validation: dict[str, object] = {}
    if theory_path.is_file() and lab_path.is_file():
        validation_run = subprocess.run(
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
            encoding="utf-8",
            errors="replace",
        )
        validation_exit = validation_run.returncode
        if validation_path.is_file():
            validation = json.loads(validation_path.read_text(encoding="utf-8"))

    certified = (
        exit_code == 0
        and len(phase1) == EXPECTED_DEPARTMENT_COUNT
        and len(phase2) == EXPECTED_DEPARTMENT_COUNT
        and all(status == "OPTIMAL" for status in phase1 + phase2)
        and len(departments) == EXPECTED_DEPARTMENT_COUNT
        and validation_exit == 0
        and validation.get("status") == "PASS"
    )
    report = {
        "status": "PASS" if certified else "FAIL",
        "lock_hashes": lock_hashes,
        "solver_exit_code": exit_code,
        "phase1_statuses": phase1,
        "phase2_statuses": phase2,
        "departments": departments,
        "department_count": len(departments),
        "validation_status": validation.get("status", "NOT_RUN"),
        "violation_counts": validation.get("violation_counts", {}),
        "output_dir": str(output_dir),
    }
    report_path = output_dir / "full_run_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    print(f"Full-run report: {report_path}", flush=True)
    return 0 if certified else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase1-time", type=int, default=900, help="Per-department Phase 1 proof budget in seconds")
    parser.add_argument("--phase2-time", type=int, default=900, help="Per-department Phase 2 proof budget in seconds")
    parser.add_argument("--workers", type=int, default=min(16, max(1, os.cpu_count() or 8)))
    parser.add_argument("--run-tag", default="second_year_full")
    return parser


if __name__ == "__main__":
    raise SystemExit(run(_parser().parse_args()))
