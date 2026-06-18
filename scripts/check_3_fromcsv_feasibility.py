"""Run per-department feasibility checks for a folder of course CSV files."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
	sys.path.insert(0, str(PROJECT_ROOT))


def _department_name(course_csv: Path) -> str:
	with course_csv.open(newline="", encoding="utf-8-sig") as handle:
		reader = csv.DictReader(handle)
		for row in reader:
			return (
				row.get("student_dept")
				or row.get("department")
				or course_csv.stem.replace("_course_data", "")
			).strip()
	return course_csv.stem.replace("_course_data", "")


def _row_count(course_csv: Path) -> int:
	with course_csv.open(newline="", encoding="utf-8-sig") as handle:
		reader = csv.DictReader(handle)
		return sum(1 for _ in reader)


def _classify(status: str, solution_count: int | None) -> str:
	if status in {"FEASIBLE", "OPTIMAL"} or (solution_count is not None and solution_count > 0):
		return "feasible"
	if status == "INFEASIBLE":
		return "infeasible"
	if status in {"UNKNOWN", "PROCESS_TIMEOUT"}:
		return "too_long"
	return "error"


def _write_reports(rows: List[Dict[str, Any]], csv_path: Path, jsonl_path: Path) -> None:
	csv_path.parent.mkdir(parents=True, exist_ok=True)
	fields = [
		"department",
		"course_csv",
		"rows",
		"classification",
		"status",
		"solution_count",
		"wall_time_sec",
		"elapsed_sec",
		"return_code",
		"error",
	]
	with csv_path.open("w", newline="", encoding="utf-8") as handle:
		writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
		writer.writeheader()
		writer.writerows(rows)
	with jsonl_path.open("w", encoding="utf-8") as handle:
		for row in rows:
			handle.write(json.dumps(row, sort_keys=True) + "\n")


def _parse_worker_stdout(stdout: str) -> Dict[str, Any] | None:
	for line in reversed(stdout.splitlines()):
		line = line.strip()
		if not line.startswith("{"):
			continue
		try:
			return json.loads(line)
		except json.JSONDecodeError:
			continue
	return None


def _run_worker(args: argparse.Namespace) -> None:
	from src.pipeline.orchestrator import PipelineOrchestrator

	logging.basicConfig(level=logging.WARNING)
	course_csv = Path(args.worker).resolve()
	config_path = Path(args.config).resolve()
	worker_output_root = Path(args.worker_output_root)
	if not worker_output_root.is_absolute():
		worker_output_root = PROJECT_ROOT / worker_output_root
	output_root = worker_output_root / course_csv.stem

	overrides = {
		"paths": {
			"courses_csv": str(course_csv),
			"output_root": str(output_root),
		},
		"runtime": {
			"time_limit_sec": int(args.time_limit),
			"stop_after_first_solution": True,
			"enable_lns": False,
			"enable_trace": False,
			"warm_start": {
				"enabled": False,
			},
		},
		"logging": {
			"level": "WARNING",
		},
	}
	for arg_name, path_key in (
		("rooms_csv", "rooms_csv"),
		("core_lab_mapping_csv", "core_lab_mapping_csv"),
		("computer_lab_mapping_csv", "computer_lab_mapping_csv"),
	):
		value = getattr(args, arg_name)
		if value:
			path = Path(value)
			if not path.is_absolute():
				path = PROJECT_ROOT / path
			overrides["paths"][path_key] = str(path)

	start = time.perf_counter()
	try:
		orchestrator = PipelineOrchestrator(config_path=config_path, base_dir=PROJECT_ROOT)
		orchestrator.load_config(overrides=overrides, strict=True)
		orchestrator.load_data()
		orchestrator.load_preprocessed_data()
		orchestrator.build_model()
		result = orchestrator.solve()
		payload: Dict[str, Any] = {
			"ok": True,
			"status": result.status,
			"status_code": result.status_code,
			"solution_count": result.solution_count,
			"wall_time_sec": result.wall_time,
			"best_bound": result.best_bound,
			"objective_value": result.objective_value,
			"elapsed_sec": round(time.perf_counter() - start, 3),
		}
	except Exception as exc:  # noqa: BLE001 - report and continue in batch mode.
		payload = {
			"ok": False,
			"status": "ERROR",
			"error": repr(exc),
			"elapsed_sec": round(time.perf_counter() - start, 3),
		}
	print(json.dumps(payload, sort_keys=True))


def _iter_course_csvs(source_dir: Path) -> Iterable[Path]:
	return sorted(source_dir.glob("*_course_data.csv"), key=lambda path: path.name.lower())


def main() -> None:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument(
		"--source-dir",
		default="data/dept_wise_course/3_fromcsv",
		help="Folder containing per-department *_course_data.csv files.",
	)
	parser.add_argument("--config", default="config/scheduler.yaml")
	parser.add_argument("--time-limit", type=int, default=60, help="CP-SAT time limit per department.")
	parser.add_argument(
		"--process-timeout",
		type=int,
		default=150,
		help="Outer wall timeout per department, including model build.",
	)
	parser.add_argument(
		"--report-csv",
		default="output/3_fromcsv_runs/summary.csv",
		help="CSV summary path.",
	)
	parser.add_argument(
		"--report-jsonl",
		default="output/3_fromcsv_runs/results.jsonl",
		help="JSONL detail path.",
	)
	parser.add_argument(
		"--worker-output-root",
		default="output/3_fromcsv_runs",
		help="Folder where each worker writes solver logs/artifacts.",
	)
	parser.add_argument("--rooms-csv", help="Override scheduler paths.rooms_csv for each worker.")
	parser.add_argument("--core-lab-mapping-csv", help="Override scheduler paths.core_lab_mapping_csv for each worker.")
	parser.add_argument("--computer-lab-mapping-csv", help="Override scheduler paths.computer_lab_mapping_csv for each worker.")
	parser.add_argument("--worker", help=argparse.SUPPRESS)
	args = parser.parse_args()

	if args.worker:
		_run_worker(args)
		return

	source_dir = (PROJECT_ROOT / args.source_dir).resolve()
	config_path = (PROJECT_ROOT / args.config).resolve()
	report_csv = (PROJECT_ROOT / args.report_csv).resolve()
	report_jsonl = (PROJECT_ROOT / args.report_jsonl).resolve()
	course_files = list(_iter_course_csvs(source_dir))
	if not course_files:
		raise SystemExit(f"No *_course_data.csv files found in {source_dir}")

	rows: List[Dict[str, Any]] = []
	for index, course_csv in enumerate(course_files, start=1):
		department = _department_name(course_csv)
		count = _row_count(course_csv)
		print(f"[{index}/{len(course_files)}] {department} ({count} rows)", flush=True)
		start = time.perf_counter()
		cmd = [
			sys.executable,
			str(Path(__file__).resolve()),
			"--worker",
			str(course_csv),
			"--config",
			str(config_path),
			"--time-limit",
			str(args.time_limit),
			"--worker-output-root",
			str(args.worker_output_root),
		]
		for option, value in (
			("--rooms-csv", args.rooms_csv),
			("--core-lab-mapping-csv", args.core_lab_mapping_csv),
			("--computer-lab-mapping-csv", args.computer_lab_mapping_csv),
		):
			if value:
				cmd.extend([option, str(value)])
		try:
			completed = subprocess.run(
				cmd,
				cwd=PROJECT_ROOT,
				capture_output=True,
				text=True,
				timeout=args.process_timeout,
				check=False,
			)
			worker_payload = _parse_worker_stdout(completed.stdout) or {}
			status = str(worker_payload.get("status") or "ERROR")
			solution_count = worker_payload.get("solution_count")
			row = {
				"department": department,
				"course_csv": str(course_csv.relative_to(PROJECT_ROOT)),
				"rows": count,
				"classification": _classify(status, solution_count),
				"status": status,
				"solution_count": solution_count,
				"wall_time_sec": worker_payload.get("wall_time_sec"),
				"elapsed_sec": worker_payload.get("elapsed_sec", round(time.perf_counter() - start, 3)),
				"return_code": completed.returncode,
				"error": worker_payload.get("error") or (completed.stderr.strip() if completed.returncode else ""),
			}
		except subprocess.TimeoutExpired as exc:
			row = {
				"department": department,
				"course_csv": str(course_csv.relative_to(PROJECT_ROOT)),
				"rows": count,
				"classification": "too_long",
				"status": "PROCESS_TIMEOUT",
				"solution_count": None,
				"wall_time_sec": None,
				"elapsed_sec": round(time.perf_counter() - start, 3),
				"return_code": None,
				"error": f"Process exceeded {args.process_timeout}s wall timeout",
			}
			if exc.stdout:
				row["stdout_tail"] = exc.stdout[-1000:]
			if exc.stderr:
				row["stderr_tail"] = exc.stderr[-1000:]

		rows.append(row)
		_write_reports(rows, report_csv, report_jsonl)
		print(f"  -> {row['classification']} ({row['status']}, {row['elapsed_sec']}s)", flush=True)

	print(f"\nWrote {report_csv}")
	print(f"Wrote {report_jsonl}")


if __name__ == "__main__":
	main()
