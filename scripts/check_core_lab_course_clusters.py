"""Check timetable feasibility for departments sharing mapped core labs.

This uses data/core_lab_mapping.csv as the source of truth for core-lab
sharing. For every core lab that appears against more than one current
third-year course/department, it builds a combined course CSV containing all
courses from the affected departments, then solves that combined model.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
	sys.path.insert(0, str(PROJECT_ROOT))


LAB_COLUMNS = ("lab_1", "lab_2", "lab_3", "lab_4", "lab_5")


def _clean(value: Any) -> str:
	return str(value or "").strip()


def _normalise_lab_name(value: str) -> str:
	return re.sub(r"\s+", " ", value.strip()).casefold()


def _slug(value: str) -> str:
	slug = re.sub(r"[^A-Za-z0-9]+", "_", value.strip()).strip("_")
	return slug or "cluster"


def _read_csv(path: Path) -> list[dict[str, str]]:
	with path.open(newline="", encoding="utf-8-sig") as handle:
		return list(csv.DictReader(handle))


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	with path.open("w", newline="", encoding="utf-8") as handle:
		writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
		writer.writeheader()
		writer.writerows(rows)


def _practical_hours(row: dict[str, str]) -> float:
	try:
		return float(_clean(row.get("practical_hours")) or 0)
	except ValueError:
		return 0.0


def _course_map(mapping_rows: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
	by_course: dict[str, dict[str, Any]] = {}
	for row in mapping_rows:
		course_code = _clean(row.get("course_code"))
		if not course_code:
			continue
		labs: list[dict[str, str]] = []
		seen: set[str] = set()
		for column in LAB_COLUMNS:
			lab = _clean(row.get(column))
			if not lab:
				continue
			key = _normalise_lab_name(lab)
			if key in seen:
				continue
			seen.add(key)
			labs.append({"name": lab, "key": key})
		if labs:
			by_course[course_code] = {
				"department": _clean(row.get("department")),
				"course_name": _clean(row.get("course_name")),
				"labs": labs,
			}
	return by_course


def _classify(status: str, solution_count: int | None) -> str:
	if status in {"FEASIBLE", "OPTIMAL"} or (solution_count is not None and solution_count > 0):
		return "feasible"
	if status == "INFEASIBLE":
		return "infeasible"
	if status in {"UNKNOWN", "PROCESS_TIMEOUT"}:
		return "too_long"
	return "error"


def _build_clusters(
	course_rows: list[dict[str, str]],
	mapping_by_course: dict[str, dict[str, Any]],
	output_dir: Path,
) -> list[dict[str, Any]]:
	fieldnames = list(course_rows[0].keys()) if course_rows else []
	current_by_course: dict[str, list[dict[str, str]]] = defaultdict(list)
	all_rows_by_dept: dict[str, list[dict[str, str]]] = defaultdict(list)
	for row in course_rows:
		dept = _clean(row.get("student_dept"))
		if dept:
			all_rows_by_dept[dept].append(row)
		if _practical_hours(row) > 0:
			course_code = _clean(row.get("course_code"))
			if course_code in mapping_by_course:
				current_by_course[course_code].append(row)

	lab_to_courses: dict[str, dict[str, Any]] = {}
	for course_code, rows in current_by_course.items():
		mapping = mapping_by_course[course_code]
		depts = sorted({_clean(row.get("student_dept")) for row in rows if _clean(row.get("student_dept"))})
		for lab in mapping["labs"]:
			entry = lab_to_courses.setdefault(
				lab["key"],
				{
					"lab_name": lab["name"],
					"courses": set(),
					"departments": set(),
					"course_departments": defaultdict(set),
					"course_names": {},
					"mapped_departments": set(),
					"mapped_lab_count": 0,
				},
			)
			entry["courses"].add(course_code)
			entry["departments"].update(depts)
			entry["mapped_departments"].add(_clean(mapping.get("department")))
			entry["course_names"][course_code] = _clean(mapping.get("course_name"))
			for dept in depts:
				entry["course_departments"][course_code].add(dept)

	clusters: list[dict[str, Any]] = []
	used_slugs: set[str] = set()
	for entry in lab_to_courses.values():
		departments = sorted(dept for dept in entry["departments"] if dept)
		courses = sorted(entry["courses"])
		if len(courses) < 2 and len(departments) < 2:
			continue
		combo_rows: list[dict[str, str]] = []
		for dept in departments:
			combo_rows.extend(all_rows_by_dept.get(dept, []))
		if len(departments) < 2:
			continue
		slug_base = _slug(entry["lab_name"])
		slug = slug_base
		counter = 2
		while slug in used_slugs:
			slug = f"{slug_base}_{counter}"
			counter += 1
		used_slugs.add(slug)
		combo_csv = output_dir / f"{slug}_combo.csv"
		_write_csv(combo_csv, fieldnames, combo_rows)
		course_departments = {
			course: sorted(depts)
			for course, depts in sorted(entry["course_departments"].items())
		}
		clusters.append(
			{
				"lab_name": entry["lab_name"],
				"slug": slug,
				"combo_csv": str(combo_csv),
				"department_count": len(departments),
				"departments": departments,
				"combo_rows": len(combo_rows),
				"shared_courses": courses,
				"shared_course_count": len(courses),
				"course_departments": course_departments,
				"mapped_departments": sorted(dept for dept in entry["mapped_departments"] if dept),
				"course_names": {course: entry["course_names"].get(course, "") for course in courses},
			}
		)
	return sorted(
		clusters,
		key=lambda item: (-int(item["department_count"]), -int(item["combo_rows"]), item["lab_name"]),
	)


def _run_cluster(cluster: dict[str, Any], config_path: Path, time_limit: int, output_dir: Path) -> dict[str, Any]:
	from src.pipeline.orchestrator import PipelineOrchestrator

	course_csv = Path(cluster["combo_csv"]).resolve()
	run_output_root = output_dir / "runs" / cluster["slug"]
	overrides = {
		"paths": {
			"courses_csv": str(course_csv),
			"output_root": str(run_output_root),
		},
		"runtime": {
			"time_limit_sec": int(time_limit),
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
	start = time.perf_counter()
	try:
		orchestrator = PipelineOrchestrator(config_path=config_path, base_dir=PROJECT_ROOT)
		orchestrator.load_config(overrides=overrides, strict=True)
		orchestrator.load_data()
		orchestrator.load_preprocessed_data()
		orchestrator.build_model()
		build_elapsed = round(time.perf_counter() - start, 3)
		model = orchestrator._constraint_model.model  # noqa: SLF001 - diagnostic runner.
		variable_count = len(model.Proto().variables)
		constraint_count = len(model.Proto().constraints)
		result = orchestrator.solve()
		stats = result.solver_statistics or {}
		solution_count = result.solution_count
		status = result.status
		return {
			"lab_name": cluster["lab_name"],
			"slug": cluster["slug"],
			"classification": _classify(status, solution_count),
			"status": status,
			"solution_count": solution_count,
			"solver_wall_time": result.wall_time,
			"elapsed_sec": round(time.perf_counter() - start, 3),
			"build_sec": build_elapsed,
			"variables": variable_count,
			"constraints": constraint_count,
			"objective_value": result.objective_value,
			"branches": stats.get("branches"),
			"conflicts": stats.get("conflicts"),
			"error": "",
		}
	except Exception as exc:  # noqa: BLE001 - continue other clusters.
		return {
			"lab_name": cluster["lab_name"],
			"slug": cluster["slug"],
			"classification": "error",
			"status": "ERROR",
			"solution_count": None,
			"solver_wall_time": None,
			"elapsed_sec": round(time.perf_counter() - start, 3),
			"build_sec": None,
			"variables": None,
			"constraints": None,
			"objective_value": None,
			"branches": None,
			"conflicts": None,
			"error": repr(exc),
		}


def _write_manifest(clusters: list[dict[str, Any]], path: Path) -> None:
	path.write_text(json.dumps(clusters, indent=2, sort_keys=True), encoding="utf-8")


def _write_cluster_summary(clusters: list[dict[str, Any]], path: Path) -> None:
	fields = [
		"lab_name",
		"slug",
		"department_count",
		"departments",
		"combo_rows",
		"shared_course_count",
		"shared_courses",
		"combo_csv",
	]
	rows = []
	for cluster in clusters:
		rows.append(
			{
				"lab_name": cluster["lab_name"],
				"slug": cluster["slug"],
				"department_count": cluster["department_count"],
				"departments": "; ".join(cluster["departments"]),
				"combo_rows": cluster["combo_rows"],
				"shared_course_count": cluster["shared_course_count"],
				"shared_courses": ", ".join(cluster["shared_courses"]),
				"combo_csv": cluster["combo_csv"],
			}
		)
	_write_csv(path, fields, rows)


def _write_results(clusters: list[dict[str, Any]], results: list[dict[str, Any]], path: Path) -> None:
	by_slug = {result["slug"]: result for result in results}
	fields = [
		"lab_name",
		"slug",
		"department_count",
		"departments",
		"combo_rows",
		"shared_courses",
		"classification",
		"status",
		"solution_count",
		"solver_wall_time",
		"elapsed_sec",
		"build_sec",
		"variables",
		"constraints",
		"objective_value",
		"branches",
		"conflicts",
		"error",
	]
	rows = []
	for cluster in clusters:
		result = by_slug.get(cluster["slug"], {})
		rows.append(
			{
				"lab_name": cluster["lab_name"],
				"slug": cluster["slug"],
				"department_count": cluster["department_count"],
				"departments": "; ".join(cluster["departments"]),
				"combo_rows": cluster["combo_rows"],
				"shared_courses": ", ".join(cluster["shared_courses"]),
				"classification": result.get("classification", "not_run"),
				"status": result.get("status", ""),
				"solution_count": result.get("solution_count"),
				"solver_wall_time": result.get("solver_wall_time"),
				"elapsed_sec": result.get("elapsed_sec"),
				"build_sec": result.get("build_sec"),
				"variables": result.get("variables"),
				"constraints": result.get("constraints"),
				"objective_value": result.get("objective_value"),
				"branches": result.get("branches"),
				"conflicts": result.get("conflicts"),
				"error": result.get("error", ""),
			}
		)
	_write_csv(path, fields, rows)


def main() -> None:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--courses", default="data/dept_wise_course/3rd_year.csv")
	parser.add_argument("--core-mapping", default="data/core_lab_mapping.csv")
	parser.add_argument("--config", default="config/scheduler.yaml")
	parser.add_argument("--output-dir", default="output/core_lab_course_clusters")
	parser.add_argument("--time-limit", type=int, default=300)
	parser.add_argument("--no-run", action="store_true", help="Only build cluster CSVs and manifests.")
	args = parser.parse_args()

	logging.basicConfig(level=logging.WARNING)
	courses_path = (PROJECT_ROOT / args.courses).resolve()
	mapping_path = (PROJECT_ROOT / args.core_mapping).resolve()
	config_path = (PROJECT_ROOT / args.config).resolve()
	output_dir = (PROJECT_ROOT / args.output_dir).resolve()
	output_dir.mkdir(parents=True, exist_ok=True)

	course_rows = _read_csv(courses_path)
	mapping_rows = _read_csv(mapping_path)
	mapping_by_course = _course_map(mapping_rows)
	clusters = _build_clusters(course_rows, mapping_by_course, output_dir)

	_write_manifest(clusters, output_dir / "manifest.json")
	_write_cluster_summary(clusters, output_dir / "shared_core_lab_clusters.csv")
	print(f"Built {len(clusters)} shared mapped core-lab clusters in {output_dir}", flush=True)

	results: list[dict[str, Any]] = []
	if not args.no_run:
		for index, cluster in enumerate(clusters, start=1):
			print(
				f"[{index}/{len(clusters)}] {cluster['lab_name']} "
				f"({cluster['department_count']} depts, {cluster['combo_rows']} rows)",
				flush=True,
			)
			result = _run_cluster(cluster, config_path, args.time_limit, output_dir)
			results.append(result)
			_write_results(clusters, results, output_dir / "shared_core_lab_cluster_results.csv")
			(output_dir / "shared_core_lab_cluster_results.json").write_text(
				json.dumps(results, indent=2, sort_keys=True),
				encoding="utf-8",
			)
			print(
				f"  -> {result['classification']} "
				f"({result['status']}, {result['elapsed_sec']}s)",
				flush=True,
			)

	if args.no_run:
		_write_results(clusters, results, output_dir / "shared_core_lab_cluster_results.csv")
		(output_dir / "shared_core_lab_cluster_results.json").write_text("[]\n", encoding="utf-8")

	print(f"Wrote {output_dir / 'shared_core_lab_clusters.csv'}")
	print(f"Wrote {output_dir / 'shared_core_lab_cluster_results.csv'}")


if __name__ == "__main__":
	main()
