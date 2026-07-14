"""Run the current second-year timetable model one cohort at a time.

The diagnostic deliberately keeps the production room file, fixed-schedule locks,
and constraint configuration unchanged.  Only the course CSV is narrowed to one
``student_dept`` value for each run.  This distinguishes failures in the
DBMS/OOPS preallocator from infeasibility in the main CP-SAT model and records a
sufficient constraint core for the latter when OR-Tools can provide one.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
	sys.path.insert(0, str(PROJECT_ROOT))


def _slug(value: str) -> str:
	return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _write_results(output_dir: Path, results: list[dict[str, Any]]) -> None:
	output_dir.mkdir(parents=True, exist_ok=True)
	(output_dir / "department_results.json").write_text(
		json.dumps(results, indent=2, sort_keys=True, default=str),
		encoding="utf-8",
	)
	columns = [
		"department",
		"rows",
		"combined_course_rows",
		"preallocation_status",
		"preallocation_allocations",
		"preallocation_pairs",
		"main_status",
		"solution_count",
		"build_sec",
		"solve_sec",
		"elapsed_sec",
		"unsat_core",
		"error",
	]
	with (output_dir / "department_results.csv").open("w", newline="", encoding="utf-8-sig") as handle:
		writer = csv.DictWriter(handle, fieldnames=columns)
		writer.writeheader()
		for result in results:
			row = {key: result.get(key, "") for key in columns}
			if isinstance(row["unsat_core"], list):
				row["unsat_core"] = " | ".join(row["unsat_core"])
			writer.writerow(row)


def _run_department(
	department: str,
	department_df: pd.DataFrame,
	*,
	config_path: Path,
	output_dir: Path,
	main_time_limit: int,
	preallocation_time_limit: int,
) -> dict[str, Any]:
	from src.pipeline.orchestrator import PipelineOrchestrator

	slug = _slug(department)
	input_dir = output_dir / "inputs"
	input_dir.mkdir(parents=True, exist_ok=True)
	course_csv = input_dir / f"{slug}.csv"
	department_df.to_csv(course_csv, index=False)
	run_root = output_dir / "runs" / slug

	overrides = {
		"paths": {
			"courses_csv": str(course_csv),
			"output_root": str(run_root),
		},
		"model": {
			"combined_lab_courses": {
				"preallocation_time_limit_sec": int(preallocation_time_limit),
				"preallocation_stop_after_first_solution": False,
			}
		},
		"runtime": {
			"time_limit_sec": int(main_time_limit),
			"thread_count": 8,
			"stop_after_first_solution": True,
			"enable_lns": False,
			"enable_trace": False,
			"warm_start": {"enabled": False},
		},
		"logging": {"level": "WARNING"},
	}
	started = time.perf_counter()
	result: dict[str, Any] = {
		"department": department,
		"rows": int(len(department_df)),
		"combined_course_rows": int(
			department_df["course_code"]
			.astype(str)
			.str.strip()
			.str.upper()
			.isin({"CS23332", "CS23333"})
			.sum()
		),
		"preallocation_status": "NOT_RUN",
		"preallocation_allocations": 0,
		"preallocation_pairs": 0,
		"main_status": "NOT_RUN",
		"solution_count": 0,
		"build_sec": None,
		"solve_sec": None,
		"elapsed_sec": None,
		"unsat_core": [],
		"preallocation_stats": {},
		"error": "",
	}
	try:
		orchestrator = PipelineOrchestrator(config_path=config_path, base_dir=PROJECT_ROOT)
		orchestrator.load_config(overrides=overrides, strict=True)
		orchestrator.load_data()
		preprocess_started = time.perf_counter()
		extended = orchestrator.load_preprocessed_data()
		preallocation_stats = dict(
			extended.preprocessing.stats.get("combined_lab_preallocation", {}) or {}
		)
		result["preallocation_stats"] = preallocation_stats
		result["preallocation_status"] = str(preallocation_stats.get("status", "OK"))
		result["preallocation_allocations"] = len(extended.preprocessing.combined_lab_allocations)
		result["preallocation_pairs"] = int(preallocation_stats.get("paired_units", 0) or 0)
		result["preprocess_sec"] = round(time.perf_counter() - preprocess_started, 3)

		build_started = time.perf_counter()
		model = orchestrator.build_model()
		result["build_sec"] = round(time.perf_counter() - build_started, 3)
		result["variables"] = len(model.model.Proto().variables)
		result["constraints"] = len(model.model.Proto().constraints)

		solve_started = time.perf_counter()
		solver_result = orchestrator.solve()
		result["solve_sec"] = round(time.perf_counter() - solve_started, 3)
		result["main_status"] = solver_result.status
		result["solution_count"] = int(solver_result.solution_count)
		result["unsat_core"] = list(solver_result.unsat_core or [])
		result["solver_statistics"] = dict(solver_result.solver_statistics or {})
	except Exception as exc:  # noqa: BLE001 - every department must still be attempted.
		if result["preallocation_status"] == "NOT_RUN":
			result["preallocation_status"] = "ERROR"
		result["main_status"] = "PREPROCESS_ERROR"
		result["error"] = f"{type(exc).__name__}: {exc}"
	result["elapsed_sec"] = round(time.perf_counter() - started, 3)
	return result


def main() -> int:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument(
		"--courses",
		type=Path,
		default=PROJECT_ROOT / "data/2_combined/All_Departments_Combined_course_data.csv",
	)
	parser.add_argument(
		"--config",
		type=Path,
		default=PROJECT_ROOT / "config/scheduler.yaml",
	)
	parser.add_argument(
		"--output",
		type=Path,
		default=PROJECT_ROOT / "output/diagnostics/second_year_departments",
	)
	parser.add_argument("--main-time-limit", type=int, default=60)
	parser.add_argument("--preallocation-time-limit", type=int, default=60)
	parser.add_argument(
		"--department",
		action="append",
		default=[],
		help="Exact student_dept label to run; repeat to select more than one.",
	)
	args = parser.parse_args()

	logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
	courses_path = args.courses.resolve()
	config_path = args.config.resolve()
	output_dir = args.output.resolve()
	df = pd.read_csv(courses_path)
	if "student_dept" not in df.columns:
		raise ValueError(f"{courses_path} has no student_dept column")

	departments = sorted(str(value) for value in df["student_dept"].dropna().unique())
	if args.department:
		requested = set(args.department)
		missing = sorted(requested.difference(departments))
		if missing:
			raise ValueError(f"Unknown department labels: {missing}")
		departments = [department for department in departments if department in requested]

	previous_unsat_core = os.environ.get("SCHEDULER_UNSAT_CORE")
	os.environ["SCHEDULER_UNSAT_CORE"] = "1"
	results: list[dict[str, Any]] = []
	try:
		for index, department in enumerate(departments, start=1):
			department_df = df[df["student_dept"].astype(str) == department].copy()
			print(f"[{index:02d}/{len(departments):02d}] {department}", flush=True)
			result = _run_department(
				department,
				department_df,
				config_path=config_path,
				output_dir=output_dir,
				main_time_limit=args.main_time_limit,
				preallocation_time_limit=args.preallocation_time_limit,
			)
			results.append(result)
			_write_results(output_dir, results)
			print(
				f"    prealloc={result['preallocation_status']} "
				f"main={result['main_status']} elapsed={result['elapsed_sec']}s"
				+ (f" error={result['error']}" if result["error"] else ""),
				flush=True,
			)
	finally:
		if previous_unsat_core is None:
			os.environ.pop("SCHEDULER_UNSAT_CORE", None)
		else:
			os.environ["SCHEDULER_UNSAT_CORE"] = previous_unsat_core

	feasible = sum(result["main_status"] in {"FEASIBLE", "OPTIMAL"} for result in results)
	infeasible = sum(result["main_status"] == "INFEASIBLE" for result in results)
	errors = len(results) - feasible - infeasible
	print(
		f"Completed {len(results)} cohorts: feasible={feasible}, "
		f"infeasible={infeasible}, other/errors={errors}",
		flush=True,
	)
	print(output_dir / "department_results.csv", flush=True)
	return 0 if errors == 0 else 2


if __name__ == "__main__":
	raise SystemExit(main())
