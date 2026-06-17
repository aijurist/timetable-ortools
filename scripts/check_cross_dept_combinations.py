"""Build and solve cross-department timetable combinations.

The detector finds department sets that interact through current third-year
data: shared assigned rooms, shared staff, shared course codes, cross-teaching
department ownership, and mapped core-lab names. For each unique department set,
it writes a full-department combined CSV and optionally runs the scheduler.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
import time
from collections import defaultdict, deque
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
	sys.path.insert(0, str(PROJECT_ROOT))


LAB_COLUMNS = ("lab_1", "lab_2", "lab_3", "lab_4", "lab_5")


def _clean(value: Any) -> str:
	return str(value or "").strip()


def _norm(value: str) -> str:
	return re.sub(r"\s+", " ", value.strip()).casefold()


def _slug(value: str) -> str:
	slug = re.sub(r"[^A-Za-z0-9]+", "_", value.strip()).strip("_")
	return slug[:120] or "combo"


def _read_csv(path: Path) -> list[dict[str, str]]:
	with path.open(newline="", encoding="utf-8-sig") as handle:
		return list(csv.DictReader(handle))


def _write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	with path.open("w", newline="", encoding="utf-8") as handle:
		writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
		writer.writeheader()
		writer.writerows(rows)


def _numeric(value: Any) -> float:
	try:
		return float(_clean(value) or 0)
	except ValueError:
		return 0.0


def _teacher_key(row: dict[str, str]) -> str:
	for column in ("staff_code", "teacher_id", "teacher_email"):
		value = _clean(row.get(column))
		if value:
			return value
	return ""


def _teacher_label(row: dict[str, str]) -> str:
	first = _clean(row.get("first_name"))
	last = _clean(row.get("last_name"))
	code = _clean(row.get("staff_code")) or _clean(row.get("teacher_id"))
	name = " ".join(part for part in (first, last) if part)
	return f"{name} ({code})".strip() if name else code


def _course_code(row: dict[str, str]) -> str:
	return _clean(row.get("course_code"))


def _dept(row: dict[str, str]) -> str:
	return _clean(row.get("student_dept"))


def _row_summary(rows: list[dict[str, str]]) -> dict[str, Any]:
	return {
		"row_count": len(rows),
		"courses": sorted({_course_code(row) for row in rows if _course_code(row)}),
		"departments": sorted({_dept(row) for row in rows if _dept(row)}),
	}


def _add_resource(
	resources: list[dict[str, Any]],
	kind: str,
	key: str,
	label: str,
	rows: list[dict[str, str]],
	extra: dict[str, Any] | None = None,
) -> None:
	departments = sorted({_dept(row) for row in rows if _dept(row)})
	if len(departments) < 2:
		return
	payload = {
		"kind": kind,
		"key": key,
		"label": label,
		"departments": departments,
		"department_count": len(departments),
		**_row_summary(rows),
	}
	if extra:
		payload.update(extra)
	resources.append(payload)


def _build_mapped_core_lab_resources(
	course_rows: list[dict[str, str]],
	core_mapping_rows: list[dict[str, str]],
) -> list[dict[str, Any]]:
	mapping_by_course: dict[str, dict[str, Any]] = {}
	for row in core_mapping_rows:
		code = _clean(row.get("course_code"))
		if not code:
			continue
		labs = []
		seen = set()
		for column in LAB_COLUMNS:
			lab = _clean(row.get(column))
			if not lab:
				continue
			key = _norm(lab)
			if key in seen:
				continue
			seen.add(key)
			labs.append({"key": key, "label": lab})
		if labs:
			mapping_by_course[code] = {
				"labs": labs,
				"mapped_department": _clean(row.get("department") or row.get("Student Department")),
				"course_name": _clean(row.get("course_name")),
			}

	lab_rows: dict[str, list[dict[str, str]]] = defaultdict(list)
	lab_labels: dict[str, str] = {}
	for row in course_rows:
		if _numeric(row.get("practical_hours")) <= 0:
			continue
		mapping = mapping_by_course.get(_course_code(row))
		if not mapping:
			continue
		for lab in mapping["labs"]:
			lab_rows[lab["key"]].append(row)
			lab_labels[lab["key"]] = lab["label"]

	resources: list[dict[str, Any]] = []
	for key, rows in lab_rows.items():
		_add_resource(
			resources,
			"mapped_core_lab",
			key,
			lab_labels.get(key, key),
			rows,
		)
	return resources


def _build_resources(
	course_rows: list[dict[str, str]],
	core_mapping_rows: list[dict[str, str]],
) -> list[dict[str, Any]]:
	resources: list[dict[str, Any]] = []

	rows_by_room: dict[str, list[dict[str, str]]] = defaultdict(list)
	rows_by_lab_room: dict[str, list[dict[str, str]]] = defaultdict(list)
	rows_by_teacher: dict[str, list[dict[str, str]]] = defaultdict(list)
	rows_by_course: dict[str, list[dict[str, str]]] = defaultdict(list)
	rows_by_teaching_dept: dict[str, list[dict[str, str]]] = defaultdict(list)
	current_departments = {_dept(row) for row in course_rows if _dept(row)}

	for row in course_rows:
		room = _clean(row.get("room_number"))
		if room:
			rows_by_room[room].append(row)
			if _numeric(row.get("practical_hours")) > 0:
				rows_by_lab_room[room].append(row)

		teacher_key = _teacher_key(row)
		if teacher_key:
			rows_by_teacher[teacher_key].append(row)

		code = _course_code(row)
		if code:
			rows_by_course[code].append(row)

		student_dept = _dept(row)
		for column in ("teaching_dept", "owner_dept"):
			other_dept = _clean(row.get(column))
			if other_dept and other_dept != student_dept and other_dept in current_departments:
				rows_by_teaching_dept[f"{column}:{other_dept}"].append(row)

	for room, rows in rows_by_room.items():
		_add_resource(resources, "exact_room", room, room, rows)
	for room, rows in rows_by_lab_room.items():
		_add_resource(resources, "exact_lab_room", room, room, rows)
	for teacher_key, rows in rows_by_teacher.items():
		label = _teacher_label(rows[0]) or teacher_key
		_add_resource(resources, "shared_teacher", teacher_key, label, rows)
	for code, rows in rows_by_course.items():
		_add_resource(resources, "shared_course_code", code, code, rows)
	for key, rows in rows_by_teaching_dept.items():
		other_dept = key.split(":", 1)[1]
		student_depts = {_dept(row) for row in rows if _dept(row)}
		pseudo_rows = list(rows)
		for dept in sorted(student_depts):
			if dept == other_dept:
				continue
		departments = sorted((student_depts | {other_dept}) - {""})
		if len(departments) < 2:
			continue
		resources.append(
			{
				"kind": "cross_teaching_dept",
				"key": key,
				"label": key,
				"departments": departments,
				"department_count": len(departments),
				**_row_summary(pseudo_rows),
			}
		)

	resources.extend(_build_mapped_core_lab_resources(course_rows, core_mapping_rows))
	return sorted(
		resources,
		key=lambda item: (
			item["kind"],
			-int(item["department_count"]),
			-int(item["row_count"]),
			item["label"],
		),
	)


def _component_sets(resources: list[dict[str, Any]], kinds: set[str] | None = None) -> list[dict[str, Any]]:
	adjacency: dict[str, set[str]] = defaultdict(set)
	edge_reasons: dict[tuple[str, str], list[str]] = defaultdict(list)
	for resource in resources:
		if kinds is not None and resource["kind"] not in kinds:
			continue
		departments = list(resource["departments"])
		for left, right in combinations(departments, 2):
			adjacency[left].add(right)
			adjacency[right].add(left)
			edge = tuple(sorted((left, right)))
			edge_reasons[edge].append(f"{resource['kind']}:{resource['label']}")

	seen: set[str] = set()
	components: list[dict[str, Any]] = []
	for start in sorted(adjacency):
		if start in seen:
			continue
		queue = deque([start])
		seen.add(start)
		component = []
		while queue:
			dept = queue.popleft()
			component.append(dept)
			for nxt in sorted(adjacency[dept]):
				if nxt not in seen:
					seen.add(nxt)
					queue.append(nxt)
		if len(component) < 2:
			continue
		reasons = []
		for left, right in combinations(sorted(component), 2):
			reasons.extend(edge_reasons.get(tuple(sorted((left, right))), []))
		components.append(
			{
				"kind": "connected_component",
				"label": "all_reasons" if kinds is None else "+".join(sorted(kinds)),
				"departments": sorted(component),
				"department_count": len(component),
				"reasons": sorted(set(reasons)),
			}
		)
	return sorted(components, key=lambda item: (-int(item["department_count"]), item["label"]))


def _build_combos(
	course_rows: list[dict[str, str]],
	resources: list[dict[str, Any]],
	output_dir: Path,
	include_components: bool,
) -> list[dict[str, Any]]:
	fieldnames = list(course_rows[0].keys()) if course_rows else []
	rows_by_dept: dict[str, list[dict[str, str]]] = defaultdict(list)
	for row in course_rows:
		dept = _dept(row)
		if dept:
			rows_by_dept[dept].append(row)

	combos_by_set: dict[frozenset[str], dict[str, Any]] = {}

	def add_combo(source: str, label: str, departments: list[str], reason: dict[str, Any]) -> None:
		dept_set = frozenset(departments)
		if len(dept_set) < 2:
			return
		combo = combos_by_set.setdefault(
			dept_set,
			{
				"source": source,
				"labels": [],
				"departments": sorted(dept_set),
				"department_count": len(dept_set),
				"reasons": [],
			},
		)
		combo["labels"].append(label)
		combo["reasons"].append(reason)

	for resource in resources:
		add_combo("resource", resource["label"], resource["departments"], resource)

	if include_components:
		component_groups = [
			(None, "all_reasons_component"),
			({"exact_room", "exact_lab_room", "mapped_core_lab"}, "room_component"),
			({"shared_teacher"}, "teacher_component"),
			({"shared_course_code", "cross_teaching_dept"}, "course_dept_component"),
		]
		for kinds, label in component_groups:
			for component in _component_sets(resources, kinds):
				add_combo("component", label, component["departments"], component)

	used_slugs: set[str] = set()
	combos = []
	for index, combo in enumerate(
		sorted(
			combos_by_set.values(),
			key=lambda item: (-int(item["department_count"]), item["departments"]),
		),
		start=1,
	):
		departments = combo["departments"]
		rows = []
		for dept in departments:
			rows.extend(rows_by_dept[dept])
		label = combo["labels"][0] if combo["labels"] else "_".join(departments)
		base = f"{index:02d}_{combo['department_count']}depts_{_slug(label)}"
		slug = base
		counter = 2
		while slug in used_slugs:
			slug = f"{base}_{counter}"
			counter += 1
		used_slugs.add(slug)
		combo_csv = output_dir / f"{slug}_combo.csv"
		_write_csv(combo_csv, fieldnames, rows)
		combos.append(
			{
				**combo,
				"slug": slug,
				"combo_csv": str(combo_csv),
				"combo_rows": len(rows),
				"reason_count": len(combo["reasons"]),
				"labels": sorted(set(combo["labels"])),
			}
		)
	return combos


def _classify(status: str, solution_count: int | None) -> str:
	if status in {"FEASIBLE", "OPTIMAL"} or (solution_count is not None and solution_count > 0):
		return "feasible"
	if status == "INFEASIBLE":
		return "infeasible"
	if status in {"UNKNOWN", "PROCESS_TIMEOUT"}:
		return "too_long"
	return "error"


def _run_combo(combo: dict[str, Any], config_path: Path, time_limit: int, output_dir: Path) -> dict[str, Any]:
	from src.pipeline.orchestrator import PipelineOrchestrator

	course_csv = Path(combo["combo_csv"]).resolve()
	run_output_root = output_dir / "runs" / combo["slug"]
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
		raw = orchestrator.load_data()
		ext = orchestrator.load_preprocessed_data()
		group_count = sum(len(groups) for groups in ext.preprocessing.groups.values())
		model = orchestrator.build_model()
		build_elapsed = round(time.perf_counter() - start, 3)
		proto = model.model.Proto()
		result = orchestrator.solve()
		stats = result.solver_statistics or {}
		status = result.status
		solution_count = result.solution_count
		return {
			"slug": combo["slug"],
			"classification": _classify(status, solution_count),
			"status": status,
			"solution_count": solution_count,
			"solver_wall_time": result.wall_time,
			"elapsed_sec": round(time.perf_counter() - start, 3),
			"build_sec": build_elapsed,
			"rows_loaded": len(raw.courses_df),
			"departments_loaded": int(raw.courses_df.student_dept.nunique()),
			"groups": group_count,
			"variables": len(proto.variables),
			"constraints": len(proto.constraints),
			"objective_value": result.objective_value,
			"best_bound": result.best_bound,
			"branches": stats.get("branches"),
			"conflicts": stats.get("conflicts"),
			"log_path": str(result.log_path) if result.log_path else "",
			"error": "",
		}
	except Exception as exc:  # noqa: BLE001 - diagnostic batch should continue.
		return {
			"slug": combo["slug"],
			"classification": "error",
			"status": "ERROR",
			"solution_count": None,
			"solver_wall_time": None,
			"elapsed_sec": round(time.perf_counter() - start, 3),
			"build_sec": None,
			"rows_loaded": None,
			"departments_loaded": None,
			"groups": None,
			"variables": None,
			"constraints": None,
			"objective_value": None,
			"best_bound": None,
			"branches": None,
			"conflicts": None,
			"log_path": "",
			"error": repr(exc),
		}


def _write_manifest(output_dir: Path, resources: list[dict[str, Any]], combos: list[dict[str, Any]]) -> None:
	(output_dir / "resources.json").write_text(
		json.dumps(resources, indent=2, sort_keys=True),
		encoding="utf-8",
	)
	(output_dir / "combos_manifest.json").write_text(
		json.dumps(combos, indent=2, sort_keys=True),
		encoding="utf-8",
	)
	resource_fields = [
		"kind",
		"label",
		"department_count",
		"departments",
		"row_count",
		"courses",
	]
	_write_csv(
		output_dir / "cross_dept_resources.csv",
		resource_fields,
		(
			{
				"kind": item["kind"],
				"label": item["label"],
				"department_count": item["department_count"],
				"departments": "; ".join(item["departments"]),
				"row_count": item.get("row_count", ""),
				"courses": ", ".join(item.get("courses", [])),
			}
			for item in resources
		),
	)
	combo_fields = [
		"slug",
		"source",
		"department_count",
		"departments",
		"combo_rows",
		"reason_count",
		"labels",
		"combo_csv",
	]
	_write_csv(
		output_dir / "cross_dept_combos.csv",
		combo_fields,
		(
			{
				"slug": item["slug"],
				"source": item["source"],
				"department_count": item["department_count"],
				"departments": "; ".join(item["departments"]),
				"combo_rows": item["combo_rows"],
				"reason_count": item["reason_count"],
				"labels": "; ".join(item["labels"]),
				"combo_csv": item["combo_csv"],
			}
			for item in combos
		),
	)


def _write_results(output_dir: Path, combos: list[dict[str, Any]], results: list[dict[str, Any]]) -> None:
	by_slug = {result["slug"]: result for result in results}
	fields = [
		"slug",
		"source",
		"department_count",
		"departments",
		"combo_rows",
		"reason_count",
		"labels",
		"classification",
		"status",
		"solution_count",
		"solver_wall_time",
		"elapsed_sec",
		"build_sec",
		"groups",
		"variables",
		"constraints",
		"objective_value",
		"best_bound",
		"branches",
		"conflicts",
		"log_path",
		"error",
	]
	rows = []
	for combo in combos:
		result = by_slug.get(combo["slug"], {})
		rows.append(
			{
				"slug": combo["slug"],
				"source": combo["source"],
				"department_count": combo["department_count"],
				"departments": "; ".join(combo["departments"]),
				"combo_rows": combo["combo_rows"],
				"reason_count": combo["reason_count"],
				"labels": "; ".join(combo["labels"]),
				"classification": result.get("classification", "not_run"),
				"status": result.get("status", ""),
				"solution_count": result.get("solution_count"),
				"solver_wall_time": result.get("solver_wall_time"),
				"elapsed_sec": result.get("elapsed_sec"),
				"build_sec": result.get("build_sec"),
				"groups": result.get("groups"),
				"variables": result.get("variables"),
				"constraints": result.get("constraints"),
				"objective_value": result.get("objective_value"),
				"best_bound": result.get("best_bound"),
				"branches": result.get("branches"),
				"conflicts": result.get("conflicts"),
				"log_path": result.get("log_path", ""),
				"error": result.get("error", ""),
			}
		)
	_write_csv(output_dir / "cross_dept_combo_results.csv", fields, rows)
	(output_dir / "cross_dept_combo_results.json").write_text(
		json.dumps(results, indent=2, sort_keys=True),
		encoding="utf-8",
	)


def main() -> None:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--courses", default="data/dept_wise_course/3rd_year.csv")
	parser.add_argument("--core-mapping", default="data/core_lab_mapping.csv")
	parser.add_argument("--config", default="config/scheduler.yaml")
	parser.add_argument("--output-dir", default="output/cross_dept_combinations")
	parser.add_argument("--time-limit", type=int, default=300)
	parser.add_argument("--max-depts", type=int, default=19)
	parser.add_argument("--min-depts", type=int, default=2)
	parser.add_argument("--largest-first", action="store_true")
	parser.add_argument("--no-components", action="store_true")
	parser.add_argument("--no-run", action="store_true")
	args = parser.parse_args()

	logging.basicConfig(level=logging.WARNING)
	courses_path = (PROJECT_ROOT / args.courses).resolve()
	core_mapping_path = (PROJECT_ROOT / args.core_mapping).resolve()
	config_path = (PROJECT_ROOT / args.config).resolve()
	output_dir = (PROJECT_ROOT / args.output_dir).resolve()
	output_dir.mkdir(parents=True, exist_ok=True)

	course_rows = _read_csv(courses_path)
	core_mapping_rows = _read_csv(core_mapping_path) if core_mapping_path.exists() else []
	resources = _build_resources(course_rows, core_mapping_rows)
	combos = _build_combos(
		course_rows,
		resources,
		output_dir,
		include_components=not args.no_components,
	)
	combos = [
		combo
		for combo in combos
		if int(args.min_depts) <= int(combo["department_count"]) <= int(args.max_depts)
	]
	combos = sorted(
		combos,
		key=lambda item: (
			int(item["department_count"]) * (-1 if args.largest_first else 1),
			int(item["combo_rows"]) * (-1 if args.largest_first else 1),
			item["slug"],
		),
	)
	_write_manifest(output_dir, resources, combos)
	_write_results(output_dir, combos, [])
	print(
		f"Detected {len(resources)} cross-dept resources and {len(combos)} unique combos.",
		flush=True,
	)
	print(f"Wrote {output_dir / 'cross_dept_combos.csv'}", flush=True)

	if args.no_run:
		return

	results: list[dict[str, Any]] = []
	for index, combo in enumerate(combos, start=1):
		print(
			f"[{index}/{len(combos)}] {combo['slug']} "
			f"({combo['department_count']} depts, {combo['combo_rows']} rows)",
			flush=True,
		)
		result = _run_combo(combo, config_path, int(args.time_limit), output_dir)
		results.append(result)
		_write_results(output_dir, combos, results)
		print(
			f"  -> {result['classification']} "
			f"({result['status']}, {result['elapsed_sec']}s)",
			flush=True,
		)

	print(f"Wrote {output_dir / 'cross_dept_combo_results.csv'}", flush=True)


if __name__ == "__main__":
	main()
