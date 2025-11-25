"""Tests for overlap telemetry builder."""

from __future__ import annotations

from datetime import datetime

from src.constraints.schema import ConstraintApplicationResult
from src.data.schemas import LabSessionDetail, TimeSystemArtifacts
from src.runtime.extractor_schema import (
	LabScheduleEntry,
	ScheduleExtractionResult,
	TheoryScheduleEntry,
)
from src.telemetry.overlaps import OverlapTelemetryBuilder


def test_overlap_builder_detects_conflicts() -> None:
	time_system = _time_system()
	group_constraint = ConstraintApplicationResult(
		name="Department Group Non-Overlap",
		domain="cross_system",
		priority=9,
		enabled=True,
		status="applied",
		details={},
	)
	teacher_constraint = ConstraintApplicationResult(
		name="Teacher Overlap Guard",
		domain="cross_system",
		priority=10,
		enabled=True,
		status="applied",
		details={},
	)

	lab_g1 = _lab_entry("G1", teacher_id="T-Overlap")
	lab_g2 = _lab_entry("G2", teacher_id="T2")
	theory_g1 = _theory_entry("G1", teacher_id="T-Overlap")
	theory_g2 = _theory_entry("G2", teacher_id="T-Overlap")

	schedule = ScheduleExtractionResult(
		lab_entries=(lab_g1, lab_g2),
		theory_entries=(theory_g1, theory_g2),
		combined_entries=tuple(),
		instance_index={},
	)

	builder = OverlapTelemetryBuilder(
		constraint_results=(group_constraint, teacher_constraint),
		time_system=time_system,
		timestamp=datetime(2025, 7, 1),
	)
	payload = builder.build(schedule)

	assert payload["group_summary"]["conflict_windows"] >= 1
	group_conflict = payload["group_conflicts"][0]
	assert sorted(group_conflict["groups"]) == ["G1", "G2"]

	teacher_conflicts = payload["teacher_conflicts"]
	assert teacher_conflicts
	assert teacher_conflicts[0]["teacher_id"] == "T-Overlap"

	constraints = payload["constraints"]
	assert set(constraints.keys()) == {"group_non_overlap", "teacher_overlap"}


def test_overlap_builder_handles_empty_schedule() -> None:
	builder = OverlapTelemetryBuilder(
		constraint_results=tuple(),
		time_system=_time_system(),
	)
	payload = builder.build(
		ScheduleExtractionResult(
			lab_entries=tuple(),
			theory_entries=tuple(),
			combined_entries=tuple(),
			instance_index={},
		)
	)
	assert list(payload["group_conflicts"]) == []
	assert list(payload["teacher_conflicts"]) == []


def _time_system() -> TimeSystemArtifacts:
	return TimeSystemArtifacts(
		theory_slots=("8:00 - 8:50", "9:00 - 9:50"),
		lab_slots=("8:00 - 8:50", "9:00 - 9:40"),
		lab_sessions={"L1": LabSessionDetail(name="L1", slots=(0,), time_range="8:00 - 9:00")},
		working_days=("monday",),
		lab_slot_to_theory={0: (0,)},
		theory_slot_to_lab={0: (0,)},
		lab_session_to_theory={"L1": (0,)},
	)


def _lab_entry(group_id: str, *, teacher_id: str) -> LabScheduleEntry:
	return LabScheduleEntry(
		teacher_id=teacher_id,
		teacher_name=f"Teacher {teacher_id}",
		course_instance_id=f"CI-{group_id}-L",
		course_code="LAB101",
		course_name="Lab",
		group_id=group_id,
		department="CSE",
		semester=5,
		day="monday",
		day_index=0,
		session_name="L1",
		session_slots=(0,),
		session_time="8:00 - 9:00",
		room_id="Lab1",
		student_count=30,
		tags=tuple(),
		is_lunch_window=False,
		five_pm_policy=None,
		five_pm_flag=False,
	)


def _theory_entry(group_id: str, *, teacher_id: str) -> TheoryScheduleEntry:
	return TheoryScheduleEntry(
		group_id=group_id,
		department="CSE",
		semester=5,
		day="monday",
		day_index=0,
		slot_index=0,
		slot_label="8:00 - 8:50",
		teacher_ids=(teacher_id,),
		teacher_names=(f"Teacher {teacher_id}",),
		course_codes=("TH101",),
		is_lunch_window=False,
		five_pm_policy=None,
		five_pm_flag=False,
		tags=tuple(),
	)
