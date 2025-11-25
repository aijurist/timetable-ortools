"""Unit tests for the cross-system lunch alignment constraint."""

from __future__ import annotations

import logging
from types import SimpleNamespace

from ortools.sat.python import cp_model

from src.constraints.base import ConstraintMetadata
from src.constraints.context import ConstraintContext
from src.constraints.cross_system.lunch_alignment import build_lunch_alignment_constraint
from src.constraints.schema import ConstraintStatus
from src.data.schemas import ExtendedDataContainer, LabSessionDetail
from src.models.schema import (
	GroupTimeslotRequirement,
	LabCourseRequirement,
	LabVariableBlock,
	TheoryVariableBlock,
	VariableCreationResult,
)


GROUP_ID = "G-flex"
DEPARTMENT = "Computer Science"
DAY_PATTERN = ("monday",)
LUNCH_WINDOW = (2, 3, 4, 5)


def _metadata(identifier: str) -> ConstraintMetadata:
	return ConstraintMetadata(
		id=f"cross_system.{identifier}",
		name=f"Lunch Alignment {identifier}",
		category="cross_system",
		priority=5,
		description="unit-test metadata",
	)


def _build_context() -> ConstraintContext:
	model = cp_model.CpModel()
	day_map = {slot: model.NewBoolVar(f"{GROUP_ID}_d0_s{slot}") for slot in LUNCH_WINDOW}
	theory_block = TheoryVariableBlock(
		group_timeslots={GROUP_ID: {0: day_map}},
		requirements={
			GROUP_ID: GroupTimeslotRequirement(
				group_id=GROUP_ID,
				department=DEPARTMENT,
				semester=5,
				required_theory_slots=6,
				day_pattern=DAY_PATTERN,
				lunch_slot_window=LUNCH_WINDOW,
				five_pm_policy=None,
				tags=tuple(),
				base_requirement=None,
			)
		},
		day_patterns={GROUP_ID: DAY_PATTERN},
		theory_slot_labels=tuple(f"Slot-{idx}" for idx in range(10)),
	)

	lab_l2 = model.NewBoolVar("lab_L2")
	lab_l3 = model.NewBoolVar("lab_L3")
	assignments = {
		"T1": {
			"LAB_L2": {0: {"L2": {"R1": lab_l2}}},
			"LAB_L3": {0: {"L3": {"R1": lab_l3}}},
		}
	}
	lab_requirements = {
		"LAB_L2": LabCourseRequirement(
			course_instance_id="LAB_L2",
			course_code="LAB200",
			teacher_id="T1",
			group_id=GROUP_ID,
			department=DEPARTMENT,
			semester=5,
			practical_hours=2,
			required_sessions=1,
			student_count=32,
			preferred_room_type=None,
			required_room_type=None,
			tags=("lab",),
		),
		"LAB_L3": LabCourseRequirement(
			course_instance_id="LAB_L3",
			course_code="LAB201",
			teacher_id="T1",
			group_id=GROUP_ID,
			department=DEPARTMENT,
			semester=5,
			practical_hours=2,
			required_sessions=1,
			student_count=32,
			preferred_room_type=None,
			required_room_type=None,
			tags=("lab",),
		),
	}
	lab_block = LabVariableBlock(
		assignments=assignments,
		requirements=lab_requirements,
		teacher_courses={"T1": ("LAB_L2", "LAB_L3")},
		day_patterns={"LAB_L2": DAY_PATTERN, "LAB_L3": DAY_PATTERN},
		lab_session_names=("L2", "L3"),
		room_ids=("R1",),
		instance_group_lookup={"LAB_L2": GROUP_ID, "LAB_L3": GROUP_ID},
	)

	raw_time = SimpleNamespace(
		lab_sessions={
			"L2": LabSessionDetail(name="L2", slots=(2, 3), time_range="09:50-11:30"),
			"L3": LabSessionDetail(name="L3", slots=(4, 5), time_range="11:40-13:20"),
		},
		working_days=("monday",),
		lab_session_to_theory={"L2": (2, 3), "L3": (4, 5)},
	)
	raw = SimpleNamespace(
		time=raw_time,
		departments=SimpleNamespace(flexible_lunch_departments=tuple()),
	)
	data = ExtendedDataContainer(raw=raw, preprocessing=SimpleNamespace())
	variables = VariableCreationResult(lab=lab_block, theory=theory_block, metadata={})
	logger = logging.getLogger("tests.constraints.lunch_alignment")
	return ConstraintContext(
		model=model,
		config=SimpleNamespace(),
		data=data,
		variables=variables,
		logger=logger,
	)


def _lab_vars(context: ConstraintContext) -> tuple[cp_model.IntVar, cp_model.IntVar]:
	lab_block = context.variables.lab.assignments["T1"]
	lab_l2 = lab_block["LAB_L2"][0]["L2"]["R1"]
	lab_l3 = lab_block["LAB_L3"][0]["L3"]["R1"]
	return lab_l2, lab_l3


def test_solver_can_keep_one_candidate_session_active() -> None:
	context = _build_context()
	constraint = build_lunch_alignment_constraint(metadata=_metadata("slot_choice"))
	result = constraint.apply(context)
	assert result.status == ConstraintStatus.APPLIED

	lab_l2, lab_l3 = _lab_vars(context)
	context.model.Add(lab_l2 == 1)
	context.model.Add(lab_l3 == 0)

	solver = cp_model.CpSolver()
	status = solver.Solve(context.model)
	assert status == cp_model.OPTIMAL
	assert solver.BooleanValue(lab_l2) == 1
	assert solver.BooleanValue(lab_l3) == 0


def test_solver_must_block_at_least_one_lab_session() -> None:
	context = _build_context()
	constraint = build_lunch_alignment_constraint(metadata=_metadata("slot_choice"))
	constraint.apply(context)

	lab_l2, lab_l3 = _lab_vars(context)
	context.model.Add(lab_l2 == 1)
	context.model.Add(lab_l3 == 1)

	solver = cp_model.CpSolver()
	status = solver.Solve(context.model)
	assert status == cp_model.INFEASIBLE