"""Tests for teacher lab telemetry builder."""

from __future__ import annotations

from datetime import datetime

from src.constraints.schema import ConstraintApplicationResult
from src.runtime.extractor_schema import LabScheduleEntry, ScheduleExtractionResult
from src.telemetry.teacher_labs import TeacherLabTelemetryBuilder, TeacherPolicy


def test_builder_flags_daily_cap_and_consecutive_violations() -> None:
	entries = (
		_make_entry("L1", 0),
		_make_entry("L2", 1),
		_make_entry("L3", 2),
		_make_entry("L5", 4),
		_make_entry("L6", 5),
	)
	schedule = ScheduleExtractionResult(
		lab_entries=entries,
		theory_entries=tuple(),
		combined_entries=tuple(),
		instance_index={},
	)

	daily_presence = ConstraintApplicationResult(
		name="Teacher Daily Lab Presence",
		domain="lab",
		priority=5,
		enabled=True,
		status="applied",
		details={
			"max_daily_sessions": 2,
			"early_sessions": ("L1",),
			"buffer_sessions": ("L5",),
			"late_sessions": ("L6",),
		},
	)
	max_consecutive = ConstraintApplicationResult(
		name="Teacher Max Consecutive Lab Sessions",
		domain="lab",
		priority=5,
		enabled=True,
		status="applied",
		details={
			"max_consecutive_sessions": 2,
			"soft_teachers": ("T1",),
		},
	)

	builder = TeacherLabTelemetryBuilder(
		constraint_results=(daily_presence, max_consecutive),
		timestamp=datetime(2025, 6, 15),
	)
	payload = builder.build(schedule)

	summary = payload["summary"]
	assert summary["days_over_daily_cap"] == 1
	assert summary["teachers_over_daily_cap"] == 1
	assert summary["long_consecutive_windows"] == 1
	assert summary["teachers_long_consecutive"] == 1
	assert summary["early_late_conflicts"] == 1
	assert summary["triple_blocks"] == 1

	teachers = payload["teachers"]
	assert len(teachers) == 1
	teacher_entry = teachers[0]
	assert teacher_entry["flags"]["over_daily_cap"] is True
	assert teacher_entry["flags"]["long_consecutive_run"] is True
	assert any(day["flags"]["triple_block"] for day in teacher_entry["day_usage"])

	timestamp = payload["generated_at"]
	assert timestamp.startswith("2025-06-15")


def test_builder_uses_fallback_policy_without_constraints() -> None:
	schedule = ScheduleExtractionResult(
		lab_entries=(
			_make_entry("L2", 1),
		),
		theory_entries=tuple(),
		combined_entries=tuple(),
		instance_index={},
	)

	builder = TeacherLabTelemetryBuilder(constraint_results=tuple())
	payload = builder.build(schedule)

	policies = payload["policies"]
	default_policy = TeacherPolicy()
	assert policies["max_daily_sessions"] == default_policy.max_daily_sessions
	assert policies["max_consecutive_sessions"] == default_policy.max_consecutive_sessions
	assert payload["summary"]["teachers_in_schedule"] == 1
	assert payload["summary"]["days_over_daily_cap"] == 0


def _make_entry(session_name: str, slot_index: int) -> LabScheduleEntry:
	return LabScheduleEntry(
		teacher_id="T1",
		teacher_name="Alice",
		course_instance_id=f"CI-{session_name}",
		course_code="CS101",
		course_name="Computing Lab",
		group_id="G1",
		department="CSE",
		semester=5,
		day="monday",
		day_index=0,
		session_name=session_name,
		session_slots=(slot_index,),
		session_time=f"{9 + slot_index}:00",
		room_id="R1",
		student_count=32,
		tags=tuple(),
		is_lunch_window=False,
		five_pm_policy=None,
		five_pm_flag=False,
	)
