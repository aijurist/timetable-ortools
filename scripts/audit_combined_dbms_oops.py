"""Audit stable DBMS/OOPS pairs in an exported lab schedule."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path


COURSE_CODES = {"CS23332", "CS23333"}
ALLOWED_ROOMS = {"ANEW101", "ANEW102", "ANEW103", "ANEW104", "A104/105", "KSL02"}


def main() -> None:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("lab_schedule_csv", type=Path)
	parser.add_argument("--json-out", type=Path)
	args = parser.parse_args()

	with args.lab_schedule_csv.open(newline="", encoding="utf-8-sig") as handle:
		rows = [row for row in csv.DictReader(handle) if row.get("course_code") in COURSE_CODES]

	errors: list[str] = []
	by_allocation: dict[str, list[dict[str, str]]] = defaultdict(list)
	for row in rows:
		allocation_id = (row.get("co_schedule_id") or "").strip()
		if not allocation_id:
			errors.append(f"{row.get('course_instance_id')}: missing co_schedule_id")
			continue
		by_allocation[allocation_id].append(row)
		if row.get("session_name") == "L3":
			errors.append(f"{allocation_id}: uses excluded L3")
		if row.get("room_number") not in ALLOWED_ROOMS:
			errors.append(f"{allocation_id}: uses disallowed room {row.get('room_number')}")

	paired_allocations = 0
	singletons = 0
	allocation_summary = []
	for allocation_id, allocation_rows in sorted(by_allocation.items()):
		by_instance: dict[str, list[dict[str, str]]] = defaultdict(list)
		for row in allocation_rows:
			by_instance[row["course_instance_id"]].append(row)
		instance_ids = sorted(by_instance)
		if len(instance_ids) == 2:
			paired_allocations += 1
		elif len(instance_ids) == 1:
			singletons += 1
		else:
			errors.append(f"{allocation_id}: expected one or two instances, found {len(instance_ids)}")

		cell_sets = {}
		teacher_ids = {}
		day_patterns = {row.get("day_pattern", "").strip() for row in allocation_rows}
		if len(day_patterns) != 1 or next(iter(day_patterns), "") not in {
			"Monday-Fri",
			"Tuesday-Saturday",
		}:
			errors.append(f"{allocation_id}: incompatible day patterns {sorted(day_patterns)}")
		for instance_id, instance_rows in by_instance.items():
			if len(instance_rows) != 4:
				errors.append(f"{allocation_id}/{instance_id}: expected 4 blocks, found {len(instance_rows)}")
			cell_sets[instance_id] = {
				(row["day"], row["session_name"], row["room_id"])
				for row in instance_rows
			}
			teachers = {row["teacher_id"] for row in instance_rows}
			if len(teachers) != 1:
				errors.append(f"{allocation_id}/{instance_id}: teacher changed across blocks: {sorted(teachers)}")
			teacher_ids[instance_id] = sorted(teachers)
		if len({frozenset(cells) for cells in cell_sets.values()}) > 1:
			errors.append(f"{allocation_id}: partner instances do not share the same four cells")

		allocation_summary.append(
			{
				"allocation_id": allocation_id,
				"course_code": allocation_rows[0]["course_code"],
				"instance_ids": instance_ids,
				"teacher_ids": teacher_ids,
				"cells": sorted(next(iter(cell_sets.values()), set())),
			}
		)

	unique_slots_by_course: dict[str, set[tuple[str, str]]] = defaultdict(set)
	unique_slots_by_department: dict[str, set[tuple[str, str]]] = defaultdict(set)
	for row in rows:
		cell = (row["day"], row["session_name"])
		unique_slots_by_course[row["course_code"]].add(cell)
		unique_slots_by_department[row["department"]].add(cell)

	report = {
		"ok": not errors,
		"errors": errors,
		"rows": len(rows),
		"allocations": len(by_allocation),
		"paired_allocations": paired_allocations,
		"singletons": singletons,
		"unique_slots_by_course": {
			key: len(value) for key, value in sorted(unique_slots_by_course.items())
		},
		"unique_slots_by_department": {
			key: len(value) for key, value in sorted(unique_slots_by_department.items())
		},
		"allocation_summary": allocation_summary,
	}
	if args.json_out:
		args.json_out.parent.mkdir(parents=True, exist_ok=True)
		args.json_out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
	print(json.dumps({key: value for key, value in report.items() if key != "allocation_summary"}, indent=2))
	if errors:
		raise SystemExit(1)


if __name__ == "__main__":
	main()
