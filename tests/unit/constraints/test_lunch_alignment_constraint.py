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


def _build_soft_split_context(*, same_course: bool) -> ConstraintContext:
	model = cp_model.CpModel()
	day_map = {slot: model.NewBoolVar(f"soft_{GROUP_ID}_d0_s{slot}") for slot in LUNCH_WINDOW}
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

	lab_l2 = model.NewBoolVar("split_lab_L2")
	lab_l3 = model.NewBoolVar("split_lab_L3")
	assignments = {
		"T1": {"LAB_A": {0: {"L2": {"R1": lab_l2}}}},
		"T2": {"LAB_B": {0: {"L3": {"R1": lab_l3}}}},
	}
	second_course_code = "ME23521" if same_course else "ME23532"
	lab_requirements = {
		"LAB_A": LabCourseRequirement(
			course_instance_id="LAB_A",
			course_code="ME23521",
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
		"LAB_B": LabCourseRequirement(
			course_instance_id="LAB_B",
			course_code=second_course_code,
			teacher_id="T2",
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
		teacher_courses={"T1": ("LAB_A",), "T2": ("LAB_B",)},
		day_patterns={"LAB_A": DAY_PATTERN, "LAB_B": DAY_PATTERN},
		lab_session_names=("L2", "L3"),
		room_ids=("R1",),
		instance_group_lookup={"LAB_A": GROUP_ID, "LAB_B": GROUP_ID},
	)

	raw_time = SimpleNamespace(
		lab_sessions={
			"L2": LabSessionDetail(name="L2", slots=(2, 3), time_range="10:00-11:40"),
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
	return ConstraintContext(
		model=model,
		config=SimpleNamespace(),
		data=data,
		variables=variables,
		logger=logging.getLogger("tests.constraints.lunch_alignment.soft"),
	)


def _soft_split_lab_vars(context: ConstraintContext) -> tuple[cp_model.IntVar, cp_model.IntVar]:
	lab_l2 = context.variables.lab.assignments["T1"]["LAB_A"][0]["L2"]["R1"]
	lab_l3 = context.variables.lab.assignments["T2"]["LAB_B"][0]["L3"]["R1"]
	return lab_l2, lab_l3


def _solve_soft_lunch_with_fixed_split(context: ConstraintContext) -> tuple[int, int]:
	constraint = build_lunch_alignment_constraint(
		metadata=_metadata("soft_split"),
		params={
			"lunch_slot_window": LUNCH_WINDOW,
			"minimum_free_slots": 1,
			"soft_departments": (f"{DEPARTMENT}_S5",),
			"penalty_weight": 10,
		},
	)
	result = constraint.apply(context)
	assert result.status == ConstraintStatus.APPLIED
	assert result.details["soft_penalties"] == 1

	lab_l2, lab_l3 = _soft_split_lab_vars(context)
	context.model.Add(lab_l2 == 1)
	context.model.Add(lab_l3 == 1)
	for slot_var in context.variables.theory.group_timeslots[GROUP_ID][0].values():
		context.model.Add(slot_var == 0)

	penalties = context.extra["objective"]["penalties"]
	assert len(penalties) == 1
	context.model.Minimize(sum(weight * variable for weight, variable, _tag in penalties))

	solver = cp_model.CpSolver()
	status = solver.Solve(context.model)
	assert status == cp_model.OPTIMAL
	return solver.Value(penalties[0][1]), int(solver.ObjectiveValue())


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


def test_soft_lunch_accepts_split_same_course_lab_batches() -> None:
	context = _build_soft_split_context(same_course=True)

	penalty_value, objective_value = _solve_soft_lunch_with_fixed_split(context)

	assert penalty_value == 0
	assert objective_value == 0


def test_soft_lunch_penalizes_non_split_lunch_blocking_labs() -> None:
	context = _build_soft_split_context(same_course=False)

	penalty_value, objective_value = _solve_soft_lunch_with_fixed_split(context)

	assert penalty_value == 1
	assert objective_value == 10
