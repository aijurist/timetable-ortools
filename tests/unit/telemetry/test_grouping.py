"""Tests for grouping telemetry builder."""

from __future__ import annotations

from datetime import datetime

from src.constraints.schema import ConstraintApplicationResult
from src.runtime.extractor_schema import (
	InstanceAssignment,
	LabScheduleEntry,
	ScheduleExtractionResult,
	TheoryScheduleEntry,
)
from src.telemetry.grouping import GroupTelemetryBuilder


def test_grouping_builder_aggregates_department_groups() -> None:
	constraint = ConstraintApplicationResult(
		name="Department Group Non-Overlap",
		domain="cross_system",
		priority=9,
		enabled=True,
		status="applied",
		details={"guard_clauses": 4},
	)

	g1_lab = _lab_entry("CI-L1", "G1", session_name="L1")
	g2_lab = _lab_entry("CI-L2", "G2", session_name="L2")
	g1_theory = _theory_entry("G1", slot_index=0)
	g2_theory = _theory_entry("G2", slot_index=1)

	assignments = {
		"CI-L1": InstanceAssignment(
			course_instance_id="CI-L1",
			group_id="G1",
			department="CSE",
			semester=5,
			lab_entries=(g1_lab,),
			theory_entries=(g1_theory,),
		),
		"CI-L2": InstanceAssignment(
			course_instance_id="CI-L2",
			group_id="G2",
			department="CSE",
			semester=5,
			lab_entries=(g2_lab,),
			theory_entries=(g2_theory,),
		),
	}

	schedule = ScheduleExtractionResult(
		lab_entries=(g1_lab, g2_lab),
		theory_entries=(g1_theory, g2_theory),
		combined_entries=tuple(),
		instance_index=assignments,
	)

	builder = GroupTelemetryBuilder(constraint_results=(constraint,), timestamp=datetime(2025, 7, 1))
	payload = builder.build(schedule)

	summary = payload["summary"]
	assert summary["total_groups"] == 2
	assert summary["departments"] == 1
	assert summary["groups_without_lab_sessions"] == 0
	assert summary["groups_without_theory_slots"] == 0

	departments = payload["departments"]
	assert len(departments) == 1
	dept_entry = departments[0]
	assert dept_entry["department"] == "CSE"
	assert dept_entry["group_count"] == 2
	assert len(dept_entry["groups"]) == 2
	group_ids = {group["group_id"] for group in dept_entry["groups"]}
	assert group_ids == {"G1", "G2"}

	constraints = payload["constraints"]
	assert "group_non_overlap" in constraints
	assert constraints["group_non_overlap"]["details"]["guard_clauses"] == 4


def test_grouping_builder_counts_missing_sessions() -> None:
	constraint = ConstraintApplicationResult(
		name="Department Group Non-Overlap",
		domain="cross_system",
		priority=9,
		enabled=True,
		status="applied",
		details={},
	)

	assignment = InstanceAssignment(
		course_instance_id="CI-ONLY-THEORY",
		group_id="G3",
		department="CSE",
		semester=5,
		lab_entries=tuple(),
		theory_entries=(_theory_entry("G3", slot_index=2),),
	)

	schedule = ScheduleExtractionResult(
		lab_entries=tuple(),
		theory_entries=assignment.theory_entries,
		combined_entries=tuple(),
		instance_index={assignment.course_instance_id: assignment},
	)

	payload = GroupTelemetryBuilder(constraint_results=(constraint,)).build(schedule)
	summary = payload["summary"]
	assert summary["total_groups"] == 1
	assert summary["groups_without_lab_sessions"] == 1
	assert summary["groups_without_theory_slots"] == 0


def _lab_entry(course_instance_id: str, group_id: str, *, session_name: str) -> LabScheduleEntry:
	return LabScheduleEntry(
		teacher_id="T1",
		teacher_name="Teacher One",
		course_instance_id=course_instance_id,
		course_code="LAB101",
		course_name="Foundations Lab",
		group_id=group_id,
		department="CSE",
		semester=5,
		day="monday",
		day_index=0,
		session_name=session_name,
		session_slots=(0,),
		session_time="8:00 - 9:00",
		room_id="Lab1",
		student_count=30,
		tags=tuple(),
		is_lunch_window=False,
		five_pm_policy=None,
		five_pm_flag=False,
	)


def _theory_entry(group_id: str, *, slot_index: int) -> TheoryScheduleEntry:
	return TheoryScheduleEntry(
		group_id=group_id,
		department="CSE",
		semester=5,
		day="monday",
		day_index=0,
		slot_index=slot_index,
		slot_label=f"Slot-{slot_index}",
		teacher_ids=("T2",),
		teacher_names=("Teacher Two",),
		course_codes=("TH101",),
		is_lunch_window=False,
		five_pm_policy=None,
		five_pm_flag=False,
		tags=tuple(),
	)
