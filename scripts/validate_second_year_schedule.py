"""Validate section-wise Semester-3 schedule CSVs against production invariants.

The 50-minute theory row is a container.  A reciprocal
``course_instance_id``/``partner_instance_id`` relationship means the two rows
are the 25+25 halves of one Kutty physical room event.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import yaml


# Lunch accounting intentionally treats the 11:00-11:40 portion before L3 as
# the section's break, while resource conflicts use the exact clock intervals.
LAB_TO_THEORY = {"L1": (0, 1), "L2": (2, 3), "L3": (4, 5), "L4": (5, 6), "L5": (7, 8)}
EXTERNAL_COMBINED_CODES = {"CS23332", "CS23333", "CB23333"}
LUNCH_SLOTS = {3, 4, 5}


@dataclass(frozen=True)
class Event:
	day: str
	start: int
	end: int
	resource: str
	instance_id: str
	course_code: str
	domain: str
	physical_id: str


def _read_csv(path: Path) -> list[dict[str, str]]:
	with path.open("r", newline="", encoding="utf-8-sig") as handle:
		return list(csv.DictReader(handle))


def _norm(value: object) -> str:
	return str(value or "").strip()


def _truthy(value: object) -> bool:
	return _norm(value).lower() in {"1", "true", "yes"}


def _day(value: object) -> str:
	token = _norm(value).lower()
	return {"wednesday": "wed", "thursday": "thur", "friday": "fri"}.get(token, token)


def _clock(value: str) -> int:
	match = re.fullmatch(r"(\d{1,2}):(\d{2})", value.strip())
	if not match:
		raise ValueError(f"Unsupported clock value: {value!r}")
	hour, minute = int(match.group(1)), int(match.group(2))
	if 1 <= hour <= 5:
		hour += 12
	return hour * 60 + minute


def _interval(value: object) -> tuple[int, int]:
	start, end = re.split(r"\s*-\s*", _norm(value), maxsplit=1)
	return _clock(start), _clock(end)


def _overlap(first: Event, second: Event) -> bool:
	return first.day == second.day and first.start < second.end and second.start < first.end


def _section_id(instance_id: object) -> str:
	match = re.search(r"__s(\d+)$", _norm(instance_id), flags=re.IGNORECASE)
	return f"s{match.group(1)}" if match else "s0"


def _pair_key(row: Mapping[str, object]) -> tuple[str, str]:
	return tuple(sorted((_norm(row.get("course_instance_id")), _norm(row.get("partner_instance_id")))))


def _theory_physical_id(row: Mapping[str, object]) -> str:
	if _truthy(row.get("is_co_scheduled")) and _norm(row.get("partner_instance_id")):
		return "kutty:" + "+".join(_pair_key(row))
	return "theory:" + _norm(row.get("course_instance_id"))


def _event(
	row: Mapping[str, object],
	*,
	domain: str,
	resource_field: str,
	physical_id: str,
) -> Event:
	start, end = _interval(row.get("time_slot") if "theory" in domain else row.get("time_range"))
	return Event(
		day=_day(row.get("day")),
		start=start,
		end=end,
		resource=_norm(row.get(resource_field)),
		instance_id=_norm(row.get("course_instance_id")),
		course_code=_norm(row.get("course_code") or row.get("course_code_display")).upper(),
		domain=domain,
		physical_id=physical_id,
	)


def _dedupe_events(events: Iterable[Event]) -> list[Event]:
	return list({(event.day, event.start, event.end, event.resource, event.physical_id): event for event in events}.values())


def _find_overlaps(first: Sequence[Event], second: Sequence[Event], *, same_collection: bool = False) -> list[dict[str, str]]:
	by_key: dict[tuple[str, str], list[Event]] = defaultdict(list)
	for event in second:
		if event.resource:
			by_key[(event.day, event.resource)].append(event)
	violations: dict[tuple[object, ...], dict[str, str]] = {}
	for left_index, left in enumerate(first):
		if not left.resource:
			continue
		for right in by_key.get((left.day, left.resource), ()):
			if same_collection and left is right:
				continue
			if same_collection and (left.physical_id, left.domain) >= (right.physical_id, right.domain):
				continue
			if left.physical_id == right.physical_id and left.domain == right.domain:
				continue
			if not _overlap(left, right):
				continue
			key = (
				left.day,
				left.resource,
				left.domain,
				left.physical_id,
				right.domain,
				right.physical_id,
			)
			violations[key] = {
				"day": left.day,
				"resource": left.resource,
				"new": f"{left.course_code}:{left.instance_id} ({left.domain})",
				"other": f"{right.course_code}:{right.instance_id} ({right.domain})",
			}
	return list(violations.values())


def _pairing_violations(theory: Sequence[Mapping[str, str]]) -> tuple[list[str], int, int]:
	violations: list[str] = []
	partner_sets: dict[str, set[str]] = defaultdict(set)
	paired_rows = [row for row in theory if _truthy(row.get("is_co_scheduled"))]
	cell_index: dict[tuple[str, str, str, str, str], list[Mapping[str, str]]] = defaultdict(list)
	for row in theory:
		cell_index[
			(
				_day(row.get("day")),
				_norm(row.get("slot_index")),
				_norm(row.get("room_number")),
				_norm(row.get("department")),
				_section_id(row.get("course_instance_id")),
			)
		].append(row)
	for row in paired_rows:
		instance = _norm(row.get("course_instance_id"))
		partner = _norm(row.get("partner_instance_id"))
		if not partner:
			violations.append(f"{instance}: paired row has no partner_instance_id")
			continue
		partner_sets[instance].add(partner)
		key = (
			_day(row.get("day")),
			_norm(row.get("slot_index")),
			_norm(row.get("room_number")),
			_norm(row.get("department")),
			_section_id(instance),
		)
		counterparts = [
			other
			for other in cell_index.get(key, ())
			if _norm(other.get("course_instance_id")) == partner
			and _norm(other.get("partner_instance_id")) == instance
			and _truthy(other.get("is_co_scheduled"))
		]
		if len(counterparts) != 1:
			violations.append(f"{instance}<->{partner} at {key[0]} slot {key[1]} has {len(counterparts)} reciprocal rows")
		elif _norm(counterparts[0].get("teacher_id")) == _norm(row.get("teacher_id")):
			violations.append(f"{instance}<->{partner}: both 25-minute halves use teacher {_norm(row.get('teacher_id'))}")
	for instance, partners in partner_sets.items():
		if len(partners) > 1:
			violations.append(f"{instance}: partner changes across sessions: {sorted(partners)}")
	physical_pairs = {
		(
			_day(row.get("day")),
			_norm(row.get("slot_index")),
			_norm(row.get("room_number")),
			_pair_key(row),
		)
		for row in paired_rows
	}
	return violations, len(partner_sets), len(physical_pairs)


def _coverage_violations(theory: Sequence[Mapping[str, str]]) -> list[str]:
	by_instance: dict[str, list[Mapping[str, str]]] = defaultdict(list)
	for row in theory:
		by_instance[_norm(row.get("course_instance_id"))].append(row)
	violations: list[str] = []
	for instance, rows in by_instance.items():
		lecture = int(float(_norm(rows[0].get("lecture_hours")) or 0))
		tutorial = int(float(_norm(rows[0].get("tutorial_hours")) or 0))
		required_half_units = 2 * (lecture + tutorial)
		delivered_half_units = sum(1 if _truthy(row.get("is_co_scheduled")) else 2 for row in rows)
		if required_half_units != delivered_half_units:
			violations.append(
				f"{instance} ({_norm(rows[0].get('course_code'))}): required {required_half_units} half-units, got {delivered_half_units}"
			)
	return violations


def _lunch_violations(theory: Sequence[Mapping[str, str]], lab: Sequence[Mapping[str, str]]) -> list[str]:
	occupied: dict[tuple[str, str, str], set[int]] = defaultdict(set)
	for row in theory:
		key = (_norm(row.get("department")), _section_id(row.get("course_instance_id")), _day(row.get("day")))
		occupied[key].add(int(_norm(row.get("slot_index"))))
	for row in lab:
		key = (_norm(row.get("department")), _section_id(row.get("course_instance_id")), _day(row.get("day")))
		occupied[key].update(LAB_TO_THEORY.get(_norm(row.get("session_name")).upper(), ()))
	return [f"{dept}/{section}/{day}: no free lunch slot in {sorted(LUNCH_SLOTS)}" for (dept, section, day), slots in occupied.items() if LUNCH_SLOTS <= slots]


def _consecutive_violations(lab: Sequence[Mapping[str, str]], config_path: Path) -> tuple[list[str], tuple[str, ...]]:
	config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
	params = config["constraints"]["lab"]["consecutive_batches"]["params"]
	codes = tuple(str(code).strip().upper() for code in params.get("course_codes", ()))
	pairs = tuple(tuple(str(item).strip().upper() for item in pair) for pair in params.get("preferred_pairs", ()))
	min_hours = int(params.get("min_practical_hours", 4))
	min_students = int(params.get("min_student_count", 36))
	by_instance_day: dict[tuple[str, str], set[str]] = defaultdict(set)
	rows_by_instance: dict[str, list[Mapping[str, str]]] = defaultdict(list)
	for row in lab:
		if _norm(row.get("course_code")).upper() not in codes:
			continue
		instance = _norm(row.get("course_instance_id"))
		rows_by_instance[instance].append(row)
		by_instance_day[(instance, _day(row.get("day")))].add(_norm(row.get("session_name")).upper())
	violations: list[str] = []
	paired_sessions = {session for pair in pairs for session in pair}
	for instance, rows in rows_by_instance.items():
		practical = int(float(_norm(rows[0].get("practical_hours")) or 0))
		students = int(float(_norm(rows[0].get("student_count")) or 0))
		if practical < min_hours and students < min_students:
			continue
		for (candidate, day), sessions in by_instance_day.items():
			if candidate != instance:
				continue
			for first, second in pairs:
				if (first in sessions) != (second in sessions):
					violations.append(f"{instance}/{day}: {first},{second} are not consecutive together ({sorted(sessions)})")
			unexpected = sessions - paired_sessions
			if unexpected:
				violations.append(f"{instance}/{day}: targeted consecutive course uses unpaired sessions {sorted(unexpected)}")
	return violations, codes


def _batch_overlap_violations(lab: Sequence[Mapping[str, str]]) -> list[str]:
	cells: dict[tuple[str, str, str, str], list[Mapping[str, str]]] = defaultdict(list)
	for row in lab:
		section = _norm(row.get("section_id")) or _section_id(row.get("course_instance_id"))
		cells[
			(
				_norm(row.get("department")),
				section,
				_day(row.get("day")),
				_norm(row.get("session_name")).upper(),
			)
		].append(row)
	violations: list[str] = []
	for cell, rows in cells.items():
		instances = {_norm(row.get("course_instance_id")) for row in rows}
		if len(instances) <= 1:
			continue
		batch_owners: dict[str, str] = {}
		for row in rows:
			instance = _norm(row.get("course_instance_id"))
			batch = _norm(row.get("batch_number"))
			if batch not in {"1", "2"}:
				violations.append(
					f"{'/'.join(cell)}: whole-section lab {instance} overlaps another course"
				)
				continue
			owner = batch_owners.get(batch)
			if owner and owner != instance:
				violations.append(
					f"{'/'.join(cell)}: Batch {batch} is double-booked by {owner} and {instance}"
				)
			else:
				batch_owners[batch] = instance
	return violations


def _combined_lab_window_violations(lab: Sequence[Mapping[str, str]]) -> list[str]:
	violations: list[str] = []
	for row in lab:
		course_code = _norm(row.get("course_code") or row.get("course_code_display")).upper()
		session_name = _norm(row.get("session_name")).upper()
		if course_code in EXTERNAL_COMBINED_CODES and session_name == "L3":
			violations.append(
				f"{course_code}:{_norm(row.get('course_instance_id'))} "
				f"uses blocked L3 on {_day(row.get('day'))}"
			)
	return violations


def validate(args: argparse.Namespace) -> dict[str, object]:
	theory = _read_csv(args.theory)
	lab = _read_csv(args.lab)
	fixed_theory = _read_csv(args.fixed_theory)
	fixed_lab = _read_csv(args.fixed_lab)

	pairing, stable_pair_count, physical_pair_sessions = _pairing_violations(theory)
	coverage = _coverage_violations(theory)
	lunch = _lunch_violations(theory, lab)
	consecutive, consecutive_codes = _consecutive_violations(lab, args.config)
	batch_overlap = _batch_overlap_violations(lab)
	combined_lab_window = _combined_lab_window_violations(lab)

	new_teacher_events = [
		_event(row, domain="theory", resource_field="teacher_id", physical_id="theory:" + _norm(row.get("course_instance_id")))
		for row in theory
	]
	new_teacher_events.extend(
		_event(row, domain="lab", resource_field="teacher_id", physical_id="lab:" + _norm(row.get("course_instance_id")) + ":" + _day(row.get("day")) + ":" + _norm(row.get("session_name")))
		for row in lab
		if _norm(row.get("course_code")).upper() not in EXTERNAL_COMBINED_CODES
	)
	fixed_teacher_events = [
		_event(row, domain="fixed_theory", resource_field="teacher_id", physical_id="fixed_theory:" + _norm(row.get("course_instance_id")))
		for row in fixed_theory
	]
	fixed_teacher_events.extend(
		_event(row, domain="fixed_lab", resource_field="teacher_id", physical_id="fixed_lab:" + _norm(row.get("course_instance_id")) + ":" + _day(row.get("day")) + ":" + _norm(row.get("session_name")))
		for row in fixed_lab
	)

	new_theory_room_events = _dedupe_events(
		_event(row, domain="theory", resource_field="room_number", physical_id=_theory_physical_id(row)) for row in theory
	)
	new_lab_room_events = _dedupe_events(
		_event(row, domain="lab", resource_field="room_number", physical_id="lab:" + _norm(row.get("course_instance_id")) + ":" + _day(row.get("day")) + ":" + _norm(row.get("session_name"))) for row in lab
	)
	fixed_room_events = _dedupe_events(
		[
			*(_event(row, domain="fixed_theory", resource_field="room_number", physical_id="fixed_theory:" + _norm(row.get("course_instance_id"))) for row in fixed_theory),
			*(_event(row, domain="fixed_lab", resource_field="room_number", physical_id="fixed_lab:" + _norm(row.get("course_instance_id")) + ":" + _day(row.get("day")) + ":" + _norm(row.get("session_name"))) for row in fixed_lab),
		]
	)

	fixed_teacher_conflicts = _find_overlaps(new_teacher_events, fixed_teacher_events)
	fixed_room_conflicts = _find_overlaps([*new_theory_room_events, *new_lab_room_events], fixed_room_events)
	internal_teacher_conflicts = _find_overlaps(new_teacher_events, new_teacher_events, same_collection=True)
	internal_theory_room_conflicts = _find_overlaps(new_theory_room_events, new_theory_room_events, same_collection=True)
	internal_cross_domain_room_conflicts = _find_overlaps(new_theory_room_events, new_lab_room_events)

	violations = {
		"pairing": pairing,
		"coverage": coverage,
		"hard_lunch": lunch,
		"consecutive_batches": consecutive,
		"batch_overlap": batch_overlap,
		"combined_lab_blocked_session": combined_lab_window,
		"fixed_teacher": fixed_teacher_conflicts,
		"fixed_room": fixed_room_conflicts,
		"internal_teacher": internal_teacher_conflicts,
		"internal_theory_room": internal_theory_room_conflicts,
		"internal_theory_lab_room": internal_cross_domain_room_conflicts,
	}
	return {
		"status": "PASS" if not any(violations.values()) else "FAIL",
		"theory_rows": len(theory),
		"lab_rows": len(lab),
		"stable_instance_pairs": stable_pair_count // 2,
		"physical_kutty_sessions": physical_pair_sessions,
		"consecutive_course_codes": consecutive_codes,
		"violation_counts": {name: len(items) for name, items in violations.items()},
		"violations": violations,
	}


def _parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--theory", type=Path, required=True)
	parser.add_argument("--lab", type=Path, required=True)
	parser.add_argument("--fixed-theory", type=Path, default=Path("prod/theory_schedule_lock.csv"))
	parser.add_argument("--fixed-lab", type=Path, default=Path("prod/lab_schedule_lock.csv"))
	parser.add_argument("--config", type=Path, default=Path("config/scheduler.yaml"))
	parser.add_argument("--json-output", type=Path)
	return parser


def main() -> int:
	args = _parser().parse_args()
	result = validate(args)
	if args.json_output:
		args.json_output.parent.mkdir(parents=True, exist_ok=True)
		args.json_output.write_text(json.dumps(result, indent=2), encoding="utf-8")
	print(json.dumps({key: value for key, value in result.items() if key != "violations"}, indent=2))
	if result["status"] != "PASS":
		for category, items in result["violations"].items():
			if items:
				print(f"\n{category}: {len(items)}")
				for item in items[:10]:
					print(f"  - {item}")
	return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
	raise SystemExit(main())
