"""Unit tests for the cross-system group non-overlap constraint."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Iterable, Tuple

from ortools.sat.python import cp_model

from src.constraints.base import ConstraintMetadata
from src.constraints.context import ConstraintContext
from src.constraints.cross_system.group_non_overlap import build_group_non_overlap_constraint
from src.constraints.schema import ConstraintStatus
from src.data.schemas import ExtendedDataContainer, LabSessionDetail
from src.models.schema import (
	GroupTimeslotRequirement,
	LabCourseRequirement,
	LabVariableBlock,
	TheoryVariableBlock,
	VariableCreationResult,
)


DEPARTMENT = "Computer Science & Engineering"
DAY_PATTERN = ("monday",)
SEMESTER = 5
THEORY_SLOT_LABELS = ("Slot-0",)
LAB_SESSION_NAME = "L2"


def _metadata(label: str) -> ConstraintMetadata:
	return ConstraintMetadata(
		id=f"cross.group_non_overlap.{label}",
		name=f"Group Non-Overlap {label}",
		category="cross_system",
		priority=9,
	)


def _build_context(
	group_ids: Iterable[str] = ("CSE_S5_G1", "CSE_S5_G2"),
) -> Tuple[ConstraintContext, dict[str, cp_model.IntVar], dict[str, cp_model.IntVar]]:
	model = cp_model.CpModel()

	group_timeslots = {}
	theory_requirements = {}
	theory_patterns = {}
	theory_vars: dict[str, cp_model.IntVar] = {}

	for group_id in group_ids:
		slot_var = model.NewBoolVar(f"{group_id}_d0_s0")
		theory_vars[group_id] = slot_var
		group_timeslots[group_id] = {0: {0: slot_var}}
		theory_requirements[group_id] = GroupTimeslotRequirement(
			group_id=group_id,
			department=DEPARTMENT,
			semester=SEMESTER,
			required_theory_slots=4,
			day_pattern=DAY_PATTERN,
			lunch_slot_window=tuple(),
			five_pm_policy=None,
			tags=tuple(),
			base_requirement=None,
		)
		theory_patterns[group_id] = DAY_PATTERN

	theory_block = TheoryVariableBlock(
		group_timeslots=group_timeslots,
		requirements=theory_requirements,
		day_patterns=theory_patterns,
		theory_slot_labels=THEORY_SLOT_LABELS,
	)

	assignments = {}
	lab_requirements = {}
	teacher_courses = {}
	day_patterns = {}
	instance_lookup = {}
	lab_vars: dict[str, cp_model.IntVar] = {}

	for index, group_id in enumerate(group_ids, start=1):
		teacher_id = f"T{index}"
		course_id = f"{group_id}_LAB"
		lab_var = model.NewBoolVar(f"{course_id}_d0_{LAB_SESSION_NAME}_R1")
		assignments.setdefault(teacher_id, {})[course_id] = {
			0: {LAB_SESSION_NAME: {"R1": lab_var}}
		}
		lab_requirements[course_id] = LabCourseRequirement(
			course_instance_id=course_id,
			course_code=f"LAB{index}",
			teacher_id=teacher_id,
			group_id=group_id,
			department=DEPARTMENT,
			semester=SEMESTER,
			practical_hours=2,
			required_sessions=1,
			student_count=32,
			preferred_room_type=None,
			required_room_type=None,
			tags=("lab",),
		)
		teacher_courses[teacher_id] = (course_id,)
		day_patterns[course_id] = DAY_PATTERN
		instance_lookup[course_id] = group_id
		lab_vars[group_id] = lab_var

	lab_block = LabVariableBlock(
		assignments=assignments,
		requirements=lab_requirements,
		teacher_courses=teacher_courses,
		day_patterns=day_patterns,
		lab_session_names=(LAB_SESSION_NAME,),
		room_ids=("R1",),
		instance_group_lookup=instance_lookup,
	)

	raw_time = SimpleNamespace(
		theory_slot_to_lab={},
		lab_session_to_theory={LAB_SESSION_NAME: (0,)},
		lab_sessions={LAB_SESSION_NAME: LabSessionDetail(name=LAB_SESSION_NAME, slots=(0,), time_range="8-9")},
		working_days=DAY_PATTERN,
	)
	raw_departments = SimpleNamespace(day_patterns={"__default__": DAY_PATTERN})
	raw = SimpleNamespace(time=raw_time, departments=raw_departments)
	data = ExtendedDataContainer(raw=raw, preprocessing=SimpleNamespace())
	variables = VariableCreationResult(lab=lab_block, theory=theory_block, metadata={})
	logger = logging.getLogger("tests.constraints.group_non_overlap")

	return (
		ConstraintContext(
			model=model,
			config=SimpleNamespace(),
			data=data,
			variables=variables,
			logger=logger,
		),
		theory_vars,
		lab_vars,
	)


def test_prevents_theory_conflict_between_groups() -> None:
	context, theory_vars, _ = _build_context()
	constraint = build_group_non_overlap_constraint(metadata=_metadata("theory"))
	result = constraint.apply(context)
	assert result.status == ConstraintStatus.APPLIED

	context.model.Add(theory_vars["CSE_S5_G1"] == 1)
	context.model.Add(theory_vars["CSE_S5_G2"] == 1)

	solver = cp_model.CpSolver()
	status = solver.Solve(context.model)
	assert status == cp_model.INFEASIBLE


def test_prevents_lab_and_theory_overlap_between_groups() -> None:
	context, theory_vars, lab_vars = _build_context()
	constraint = build_group_non_overlap_constraint(metadata=_metadata("lab_vs_theory"))
	constraint.apply(context)

	context.model.Add(lab_vars["CSE_S5_G1"] == 1)
	context.model.Add(theory_vars["CSE_S5_G2"] == 1)

	solver = cp_model.CpSolver()
	status = solver.Solve(context.model)
	assert status == cp_model.INFEASIBLE


def test_skips_when_only_one_group_present() -> None:
	context, _, _ = _build_context(group_ids=("CSE_S5_G1",))
	constraint = build_group_non_overlap_constraint(metadata=_metadata("single"))
	result = constraint.apply(context)
	assert result.status == ConstraintStatus.SKIPPED
