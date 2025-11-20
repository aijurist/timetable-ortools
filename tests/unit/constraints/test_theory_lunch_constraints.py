"""Unit tests for theory lunch constraints."""

from __future__ import annotations

import logging
from types import SimpleNamespace

from ortools.sat.python import cp_model

from src.constraints.base import ConstraintMetadata
from src.constraints.context import ConstraintContext
from src.constraints.schema import ConstraintStatus
from src.constraints.theory.lunch import (
	build_flexible_lunch_constraint,
	build_theory_lunch_break_constraint,
)
from src.data.schemas import ExtendedDataContainer
from src.models.schema import (
	GroupTimeslotRequirement,
	LabCourseRequirement,
	LabVariableBlock,
	TheoryVariableBlock,
	VariableCreationResult,
)


GROUP_ID = "G1"
DEPARTMENT = "Computer Science"
DAY_PATTERN = ("monday",)
THEORY_SLOT_LABELS = tuple(f"Slot-{idx}" for idx in range(8))


def _metadata(identifier: str) -> ConstraintMetadata:
	return ConstraintMetadata(
		id=f"theory.{identifier}",
		name=identifier.replace("_", " ").title(),
		category="theory",
		priority=8,
		description=f"Unit-test metadata for {identifier}",
	)


def _build_context(
	*,
	lunch_window: tuple[int, ...] = (3, 4, 5),
	flexible_departments: tuple[str, ...] = (),
	include_lab_sessions: bool = True,
) -> ConstraintContext:
	model = cp_model.CpModel()
	day_map = {slot_idx: model.NewBoolVar(f"{GROUP_ID}_d0_s{slot_idx}") for slot_idx in range(len(THEORY_SLOT_LABELS))}
	theory_block = TheoryVariableBlock(
		group_timeslots={GROUP_ID: {0: day_map}},
		requirements={
			GROUP_ID: GroupTimeslotRequirement(
				group_id=GROUP_ID,
				department=DEPARTMENT,
				semester=3,
				required_theory_slots=6,
				day_pattern=DAY_PATTERN,
				lunch_slot_window=lunch_window,
				five_pm_policy=None,
				tags=tuple(),
				base_requirement=None,
			)
		},
		day_patterns={GROUP_ID: DAY_PATTERN},
		theory_slot_labels=THEORY_SLOT_LABELS,
	)

	if include_lab_sessions:
		lab_var = model.NewBoolVar("lab_g1_L3")
		assignments = {
			"T1": {
				"LAB1": {
					0: {
						"L3": {"R1": lab_var},
					}
				}
			}
		}
		lab_requirement = LabCourseRequirement(
			course_instance_id="LAB1",
			course_code="LAB101",
			teacher_id="T1",
			group_id=GROUP_ID,
			department=DEPARTMENT,
			semester=3,
			practical_hours=2,
			required_sessions=1,
			student_count=32,
			preferred_room_type=None,
			required_room_type=None,
			tags=("lab",),
		)
		lab_block = LabVariableBlock(
			assignments=assignments,
			requirements={"LAB1": lab_requirement},
			teacher_courses={"T1": ("LAB1",)},
			day_patterns={"LAB1": DAY_PATTERN},
			lab_session_names=("L3",),
			room_ids=("R1",),
			instance_group_lookup={"LAB1": GROUP_ID},
		)
	else:
		lab_block = LabVariableBlock(
			assignments={},
			requirements={},
			teacher_courses={},
			day_patterns={},
			lab_session_names=tuple(),
			room_ids=tuple(),
			instance_group_lookup={},
		)

	raw_departments = SimpleNamespace(flexible_lunch_departments=tuple(flexible_departments))
	raw = SimpleNamespace(departments=raw_departments)
	data = ExtendedDataContainer(raw=raw, preprocessing=SimpleNamespace())
	variables = VariableCreationResult(lab=lab_block, theory=theory_block, metadata={})
	logger = logging.getLogger("tests.constraints.theory")
	return ConstraintContext(
		model=model,
		config=SimpleNamespace(),
		data=data,
		variables=variables,
		logger=logger,
	)


def test_lunch_window_enforces_non_flexible_group() -> None:
	context = _build_context()
	constraint = build_theory_lunch_break_constraint(metadata=_metadata("lunch_window"))
	result = constraint.apply(context)
	assert result.status == ConstraintStatus.APPLIED
	assert result.details["groups"] == 1
	assert result.details["flexible_skipped"] == 0


def test_lunch_window_skips_flexible_departments() -> None:
	context = _build_context(flexible_departments=(DEPARTMENT,))
	constraint = build_theory_lunch_break_constraint(metadata=_metadata("lunch_window"))
	result = constraint.apply(context)
	assert result.status == ConstraintStatus.SKIPPED
	assert result.details["flexible_skipped"] == 1


def test_flexible_lunch_uses_natural_pattern() -> None:
	context = _build_context(flexible_departments=(DEPARTMENT,))
	constraint = build_flexible_lunch_constraint(metadata=_metadata("flexible_lunch"))
	result = constraint.apply(context)
	assert result.status == ConstraintStatus.APPLIED
	assert result.details["clauses"] == 1


def test_flexible_lunch_falls_back_to_traditional_window() -> None:
	context = _build_context(flexible_departments=(DEPARTMENT,), include_lab_sessions=False)
	constraint = build_flexible_lunch_constraint(metadata=_metadata("flexible_lunch"))
	result = constraint.apply(context)
	assert result.status == ConstraintStatus.APPLIED
	assert result.details["clauses"] == 1
