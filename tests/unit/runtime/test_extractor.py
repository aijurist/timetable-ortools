from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

from src.runtime.extractor import ScheduleExtractor
from src.runtime.extractor_schema import LabScheduleEntry
from src.data.schemas import LabSessionDetail
from src.models.schema import LabCourseRequirement
from tests.unit.runtime.runtime_test_helpers import (
	build_constraint_model,
	build_extended_container,
	build_solver_result,
)


def test_schedule_extractor_builds_and_exports(tmp_path: Path) -> None:
	data = build_extended_container()
	constraint_model = build_constraint_model()
	extractor = ScheduleExtractor(data, constraint_model)
	solver_result = build_solver_result(constraint_model.model)
	result = extractor.export(solver_result, output_dir=tmp_path, write_json=True, write_csv=True)

	assert len(result.lab_entries) == 1
	assert result.lab_entries[0].is_lunch_window is True
	assert result.lab_entries[0].five_pm_flag is True
	assert len(result.theory_entries) == 1
	assert result.theory_entries[0].five_pm_flag is False
	assert "C1" in result.instance_index

	schedule_json = tmp_path / "schedule.json"
	assert schedule_json.exists()
	payload = json.loads(schedule_json.read_text(encoding="utf-8"))
	assert payload["lab_entries"], "Lab schedule missing from JSON payload"

	csv_dir = tmp_path / "csv"
	lab_csv = csv_dir / "lab_schedule.csv"
	theory_csv = csv_dir / "theory_schedule.csv"
	assert lab_csv.exists()
	assert theory_csv.exists()


def test_theory_block_metadata_is_applied() -> None:
	data = build_extended_container()
	constraint_model = build_constraint_model()
	extractor = ScheduleExtractor(data, constraint_model)
	solver_result = build_solver_result(constraint_model.model)
	result = extractor.extract(solver_result)
	assert result.theory_entries, "Expected at least one theory entry"
	entry = result.theory_entries[0]
	assert entry.block == "A Block"
	assert entry.room_number == "A202"
	assert entry.room_id == "A202"


def test_lab_batch_annotation_balances_paired_and_single_sessions() -> None:
	extractor = object.__new__(ScheduleExtractor)
	extractor._time = SimpleNamespace(
		lab_sessions={
			"L1": LabSessionDetail("L1", (0, 1), "08:00-09:40"),
			"L2": LabSessionDetail("L2", (2, 3), "10:00-11:40"),
			"L3": LabSessionDetail("L3", (4, 5), "11:50-13:20"),
			"L4": LabSessionDetail("L4", (6, 7), "13:20-15:00"),
		}
	)
	extractor._lab_vars = SimpleNamespace(
		requirements={
			"C1": LabCourseRequirement(
				course_instance_id="C1",
				course_code="CS101",
				teacher_id="t1",
				group_id="G1",
				department="Engineering",
				semester=3,
				practical_hours=4,
				required_sessions=2,
				student_count=70,
				preferred_room_type=None,
				required_room_type=None,
				tags=tuple(),
			)
		}
	)

	entries = (
		_lab_entry("L1", day_index=1),
		_lab_entry("L2", day_index=2),
		_lab_entry("L3", day_index=0),
		_lab_entry("L4", day_index=0),
	)

	annotated = extractor._annotate_lab_batches(entries)
	counts = Counter(entry.batch_label for entry in annotated)

	assert counts == {"Batch 1": 2, "Batch 2": 2}
	assert {
		(entry.session_name, entry.batch_label)
		for entry in annotated
		if entry.day_index == 0
	} == {("L3", "Batch 1"), ("L4", "Batch 1")}


def test_lab_batch_annotation_avoids_same_day_reuse_for_nonconsecutive_sessions() -> None:
	extractor = object.__new__(ScheduleExtractor)
	extractor._time = SimpleNamespace(
		lab_sessions={
			"L1": LabSessionDetail("L1", (0, 1), "08:00-09:40"),
			"L2": LabSessionDetail("L2", (2, 3), "10:00-11:40"),
			"L3": LabSessionDetail("L3", (4, 5), "11:50-13:20"),
			"L4": LabSessionDetail("L4", (6, 7), "13:20-15:00"),
		}
	)
	extractor._lab_vars = SimpleNamespace(
		requirements={
			"C1": LabCourseRequirement(
				course_instance_id="C1",
				course_code="CS101",
				teacher_id="t1",
				group_id="G1",
				department="Engineering",
				semester=3,
				practical_hours=4,
				required_sessions=2,
				student_count=70,
				preferred_room_type=None,
				required_room_type=None,
				tags=tuple(),
			)
		}
	)

	entries = (
		_lab_entry("L1", day_index=0),
		_lab_entry("L1", day_index=1),
		_lab_entry("L3", day_index=0),
		_lab_entry("L3", day_index=1),
	)

	annotated = extractor._annotate_lab_batches(entries)
	labels_by_day = {
		day_index: {entry.batch_label for entry in annotated if entry.day_index == day_index}
		for day_index in (0, 1)
	}

	assert labels_by_day == {0: {"Batch 1", "Batch 2"}, 1: {"Batch 1", "Batch 2"}}


def _lab_entry(session_name: str, *, day_index: int) -> LabScheduleEntry:
	return LabScheduleEntry(
		teacher_id="t1",
		teacher_name="Teacher One",
		course_instance_id="C1",
		course_code="CS101",
		course_name="Intro to CS Lab",
		group_id="G1",
		department="Engineering",
		semester=3,
		day=f"day_{day_index}",
		day_index=day_index,
		session_name=session_name,
		session_slots=tuple(),
		session_time=session_name,
		room_id=f"Lab{session_name}",
		student_count=70,
		tags=tuple(),
		is_lunch_window=False,
		five_pm_policy=None,
		five_pm_flag=False,
		practical_hours=4,
		capacity=35,
	)
