"""Unit tests for the cross-system group non-overlap constraint."""

from __future__ import annotations

from dataclasses import replace
import logging
from types import SimpleNamespace
from typing import Iterable, Tuple

from ortools.sat.python import cp_model

from src.constraints.base import ConstraintMetadata
from src.constraints.context import ConstraintContext
from src.constraints.cross_system.group_non_overlap import build_group_non_overlap_constraint
from src.constraints.cross_system.teacher_overlap import build_teacher_overlap_constraint
from src.constraints.schema import ConstraintStatus
from src.data.schemas import DepartmentSemesterKey, ExtendedDataContainer, KuttyBundle, LabSessionDetail
from src.models.schema import (
	GroupTimeslotRequirement,
	LabCourseRequirement,
	LabVariableBlock,
	TheoryCourseRequirement,
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


def _add_kutty_pair(
	context: ConstraintContext,
	theory_vars: dict[str, cp_model.IntVar],
) -> tuple[ConstraintContext, cp_model.IntVar]:
	first_group = "CSE_S5_G1"
	second_group = "CSE_S5_G2"
	first_instance = "THEORY_G1"
	second_instance = "THEORY_G2"
	bundle_id = "CSE_S5_KUTTY_G1_G2_B01"
	bundle_var = context.model.NewBoolVar("kutty_bundle_g1_g2_d0_s0")

	def requirement(instance_id: str, group_id: str, teacher_id: str) -> TheoryCourseRequirement:
		return TheoryCourseRequirement(
			course_instance_id=instance_id,
			course_code=instance_id,
			group_id=group_id,
			teacher_id=teacher_id,
			department=DEPARTMENT,
			semester=SEMESTER,
			required_slots=1,
			lecture_hours=1,
			tutorial_hours=0,
			student_count=32,
			preferred_room_type=None,
			required_room_type=None,
			bundle_id=bundle_id,
		)

	assignments = {
		"BT1": {first_instance: {0: {0: bundle_var}}},
		"T2": {second_instance: {0: {0: bundle_var}}},
	}
	course_requirements = {
		first_instance: requirement(first_instance, first_group, "BT1"),
		second_instance: requirement(second_instance, second_group, "T2"),
	}
	for group_id, theory_var in theory_vars.items():
		if group_id in (first_group, second_group):
			continue
		instance_id = f"THEORY_{group_id}"
		teacher_id = f"BT_{group_id}"
		assignments[teacher_id] = {instance_id: {0: {0: theory_var}}}
		course_requirements[instance_id] = requirement(instance_id, group_id, teacher_id)

	bundle = KuttyBundle(
		key=DepartmentSemesterKey(DEPARTMENT, SEMESTER),
		bundle_id=bundle_id,
		bundle_group_id="CSE_S5_KUTTY_G1_G2",
		first_instance_id=first_instance,
		first_group_id=first_group,
		second_instance_id=second_instance,
		second_group_id=second_group,
		delivery_mode="kutty_25x2",
		required_blocks=1,
		theory_hours=1,
		second_theory_hours=1,
		first_remainder_blocks=0,
		second_remainder_blocks=0,
		pairing_score=0,
		feasible_slot_count=1,
	)
	theory_block = replace(
		context.variables.theory,
		assignments=assignments,
		course_requirements=course_requirements,
		course_day_patterns={instance_id: DAY_PATTERN for instance_id in course_requirements},
		bundle_specs={bundle_id: bundle},
		bundle_assignments={bundle_id: {0: {0: bundle_var}}},
		instance_bundle_lookup={first_instance: bundle_id, second_instance: bundle_id},
	)
	variables = replace(context.variables, theory=theory_block)
	return replace(context, variables=variables), bundle_var


def test_kutty_linked_groups_may_overlap_and_leave_staff_guard_to_teacher_constraint() -> None:
	context, theory_vars, lab_vars = _build_context()
	context, bundle_var = _add_kutty_pair(context, theory_vars)
	constraint = build_group_non_overlap_constraint(metadata=_metadata("kutty_pair"))

	result = constraint.apply(context)

	assert result.status == ConstraintStatus.SKIPPED
	assert result.details["allowed_bundle_group_pairs"] == 1
	assert result.details["paired_group_policy"] == "allow_cohort_overlap_teacher_guarded"
	context.model.Add(lab_vars["CSE_S5_G2"] == 1)
	context.model.Add(bundle_var == 1)
	assert cp_model.CpSolver().Solve(context.model) in (cp_model.FEASIBLE, cp_model.OPTIMAL)


def test_kutty_cohort_allows_other_groups_to_overlap() -> None:
	groups = ("CSE_S5_G1", "CSE_S5_G2", "CSE_S5_G3")
	context, theory_vars, lab_vars = _build_context(group_ids=groups)
	context, _bundle_var = _add_kutty_pair(context, theory_vars)
	constraint = build_group_non_overlap_constraint(metadata=_metadata("kutty_unrelated"))

	result = constraint.apply(context)

	assert result.status == ConstraintStatus.SKIPPED
	assert result.details["allowed_bundle_group_pairs"] == 3
	assert result.details["teacher_guarded_cohorts"] == 1
	context.model.Add(lab_vars["CSE_S5_G1"] == 1)
	context.model.Add(theory_vars["CSE_S5_G3"] == 1)
	assert cp_model.CpSolver().Solve(context.model) in (cp_model.FEASIBLE, cp_model.OPTIMAL)


def test_teacher_guard_still_blocks_same_staff_inside_allowed_kutty_pair() -> None:
	context, theory_vars, lab_vars = _build_context()
	context, bundle_var = _add_kutty_pair(context, theory_vars)
	build_group_non_overlap_constraint(metadata=_metadata("kutty_teacher_group")).apply(context)
	build_teacher_overlap_constraint(metadata=_metadata("kutty_teacher")).apply(context)

	context.model.Add(lab_vars["CSE_S5_G2"] == 1)
	context.model.Add(bundle_var == 1)

	assert cp_model.CpSolver().Solve(context.model) == cp_model.INFEASIBLE
