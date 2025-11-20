"""Unit tests for the unified five-pm policy constraint."""

from __future__ import annotations

import logging
from types import SimpleNamespace

from ortools.sat.python import cp_model

from src.constraints.base import ConstraintMetadata
from src.constraints.context import ConstraintContext
from src.constraints.cross_system.five_pm_policy import build_five_pm_policy_constraint
from src.constraints.schema import ConstraintStatus
from src.data.schemas import ExtendedDataContainer
from src.models.schema import (
	GroupTimeslotRequirement,
	LabCourseRequirement,
	LabVariableBlock,
	TheoryVariableBlock,
	VariableCreationResult,
)

DEPARTMENT = "Computer Science"
GROUP_ID = "G1"
COURSE_ID = "LAB1"
DAY_PATTERN = ("monday",)


def _metadata(identifier: str, *, weight: float = 0.5) -> ConstraintMetadata:
	return ConstraintMetadata(
		id=f"cross_system.{identifier}",
		name=identifier,
		category="cross_system",
		priority=7,
		description="unit-test metadata",
		weight=weight,
	)


def _build_context(*, include_lab: bool = True) -> ConstraintContext:
	model = cp_model.CpModel()
	day_slots = {9: model.NewBoolVar("theory_slot_9"), 8: model.NewBoolVar("theory_slot_8")}
	theory_block = TheoryVariableBlock(
		group_timeslots={GROUP_ID: {0: day_slots}},
		requirements={
			GROUP_ID: GroupTimeslotRequirement(
				group_id=GROUP_ID,
				department=DEPARTMENT,
				semester=3,
				required_theory_slots=6,
				day_pattern=DAY_PATTERN,
				lunch_slot_window=tuple(),
				five_pm_policy=None,
				tags=tuple(),
				base_requirement=None,
			)
		},
		day_patterns={GROUP_ID: DAY_PATTERN},
		theory_slot_labels=tuple(f"Slot-{idx}" for idx in range(12)),
	)

	if include_lab:
		lab_var = model.NewBoolVar("lab_L6")
		assignments = {
			"T1": {
				COURSE_ID: {
					0: {
						"L6": {"R1": lab_var},
					}
				}
			}
		}
		lab_requirement = LabCourseRequirement(
			course_instance_id=COURSE_ID,
			course_code="LAB101",
			teacher_id="T1",
			group_id=GROUP_ID,
			department=DEPARTMENT,
			semester=3,
			practical_hours=2,
			required_sessions=1,
			student_count=30,
			preferred_room_type=None,
			required_room_type=None,
			tags=tuple(),
		)
		lab_block = LabVariableBlock(
			assignments=assignments,
			requirements={COURSE_ID: lab_requirement},
			teacher_courses={"T1": (COURSE_ID,)},
			day_patterns={COURSE_ID: DAY_PATTERN},
			lab_session_names=("L6",),
			room_ids=("R1",),
			instance_group_lookup={COURSE_ID: GROUP_ID},
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

	raw = SimpleNamespace(
		departments=SimpleNamespace(five_pm_constraints=None),
	)
	data = ExtendedDataContainer(raw=raw, preprocessing=SimpleNamespace())
	variables = VariableCreationResult(lab=lab_block, theory=theory_block, metadata={})
	logger = logging.getLogger("tests.constraints.five_pm")
	return ConstraintContext(
		model=model,
		config=SimpleNamespace(),
		data=data,
		variables=variables,
		logger=logger,
	)


def test_hard_policy_blocks_theory_and_lab_slots() -> None:
	context = _build_context()
	constraint = build_five_pm_policy_constraint(
		metadata=_metadata("five_pm_hard"),
		params={
			"hard_departments": (f"{DEPARTMENT}_S3",),
			"blocked_theory_slots": (9,),
			"blocked_lab_sessions": ("L6",),
		},
	)
	result = constraint.apply(context)
	assert result.status == ConstraintStatus.APPLIED
	assert result.details["hard_theory_clauses"] >= 1
	assert result.details["hard_lab_clauses"] >= 1

	# Forcing the forbidden variables to 1 should render the model infeasible
	theory_var = context.variables.theory.group_timeslots[GROUP_ID][0][9]
	lab_var = context.variables.lab.assignments["T1"][COURSE_ID][0]["L6"]["R1"]
	context.model.Add(theory_var == 1)
	context.model.Add(lab_var == 1)
	solver = cp_model.CpSolver()
	status = solver.Solve(context.model)
	assert status == cp_model.INFEASIBLE


def test_soft_policy_registers_penalties() -> None:
	context = _build_context()
	constraint = build_five_pm_policy_constraint(
		metadata=_metadata("five_pm_soft"),
		params={
			"soft_departments": (f"{DEPARTMENT}_S3",),
			"discouraged_theory_slots": (9,),
			"discouraged_lab_sessions": ("L6",),
			"soft_penalty_weight": 3,
		},
	)
	result = constraint.apply(context)
	assert result.status == ConstraintStatus.APPLIED
	assert result.details["penalty_terms"] == 2
	objective_bucket = context.extra.get("objective", {})
	penalties = objective_bucket.get("penalties", [])
	assert len(penalties) == 2
	assert {entry[0] for entry in penalties} == {3}


def test_policy_falls_back_to_department_payload() -> None:
	context = _build_context()
	context.data.raw.departments.five_pm_constraints = {
		"hard": {
			"departments": (f"{DEPARTMENT}_S3",),
			"blocked_theory_slots": (9,),
			"blocked_lab_sessions": ("L6",),
		}
	}
	constraint = build_five_pm_policy_constraint(metadata=_metadata("five_pm_data"), params=None)
	result = constraint.apply(context)
	assert result.status == ConstraintStatus.APPLIED
	assert result.details["hard_theory_clauses"] >= 1