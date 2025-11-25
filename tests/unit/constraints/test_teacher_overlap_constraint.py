"""Unit tests for the teacher overlap constraint."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Dict, Mapping, Tuple

from ortools.sat.python import cp_model

from src.constraints.base import ConstraintMetadata
from src.constraints.context import ConstraintContext
from src.constraints.cross_system.teacher_overlap import build_teacher_overlap_constraint
from src.constraints.schema import ConstraintStatus
from src.data.schemas import (
	CourseGroup,
	DepartmentSemesterKey,
	ExtendedDataContainer,
	GroupSummary,
)
from src.models.schema import (
	GroupTimeslotRequirement,
	LabCourseRequirement,
	LabVariableBlock,
	TheoryVariableBlock,
	VariableCreationResult,
)

DAY_PATTERN = ("monday",)
DEPARTMENT = "Computer Science & Engineering"
SEMESTER = 5
THEORY_SLOTS = ("Slot-0",)
DEPT_KEY = DepartmentSemesterKey(department=DEPARTMENT, semester=SEMESTER)
SUMMARY = GroupSummary(
	num_instances=1,
	num_courses=1,
	num_teachers=1,
	lab_instances=1,
	theory_instances=1,
	total_student_count=60,
	lab_hours=2,
	theory_hours=2,
)


def _metadata(label: str) -> ConstraintMetadata:
	return ConstraintMetadata(
		id=f"cross.teacher_overlap.{label}",
		name=f"Teacher Overlap {label}",
		category="cross_system",
		priority=9,
	)


def _build_context(
	*,
	theory_groups: Mapping[str, str] | None = None,
	lab_courses: Mapping[str, Mapping[str, object]] | None = None,
	lab_session_map: Mapping[str, Tuple[int, ...]] | None = None,
) -> Tuple[ConstraintContext, Dict[str, cp_model.IntVar], Dict[str, cp_model.IntVar]]:
	model = cp_model.CpModel()
	theory_groups = theory_groups or {}
	lab_courses = lab_courses or {}
	lab_session_map = lab_session_map or {"L1": (0,)}

	group_timeslots = {}
	theory_requirements = {}
	theory_patterns = {}
	theory_vars: Dict[str, cp_model.IntVar] = {}

	for group_id in theory_groups:
		var = model.NewBoolVar(f"{group_id}_d0_s0")
		theory_vars[group_id] = var
		group_timeslots[group_id] = {0: {0: var}}
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
		theory_slot_labels=THEORY_SLOTS,
	)

	assignments: Dict[str, Dict[str, Dict[int, Dict[str, Dict[str, cp_model.IntVar]]]]] = {}
	teacher_courses: Dict[str, Tuple[str, ...]] = {}
	lab_requirements: Dict[str, LabCourseRequirement] = {}
	day_patterns = {}
	instance_lookup = {}
	lab_vars: Dict[str, cp_model.IntVar] = {}

	lab_session_names = set()
	room_ids = set()

	teacher_course_buffer: Dict[str, list[str]] = {}
	for course_id, meta in lab_courses.items():
		teacher_id = str(meta["teacher_id"])
		group_id = str(meta["group_id"])
		course_code = str(meta.get("course_code", course_id))
		practical_hours = int(meta.get("practical_hours", 2))
		session_name = str(meta.get("session_name", "L1"))
		room_id = str(meta.get("room_id", "R1"))

		lab_session_names.add(session_name)
		room_ids.add(room_id)

		var = model.NewBoolVar(f"{course_id}_d0_{session_name}_{room_id}")
		lab_vars[course_id] = var

		course_assignments = assignments.setdefault(teacher_id, {})
		day_map = course_assignments.setdefault(course_id, {})
		day_map.setdefault(0, {}).setdefault(session_name, {})[room_id] = var

		teacher_course_buffer.setdefault(teacher_id, []).append(course_id)
		requirement = LabCourseRequirement(
			course_instance_id=course_id,
			course_code=course_code,
			teacher_id=teacher_id,
			group_id=group_id,
			department=DEPARTMENT,
			semester=SEMESTER,
			practical_hours=practical_hours,
			required_sessions=1,
			student_count=32,
			preferred_room_type=None,
			required_room_type=None,
			tags=tuple(),
		)
		lab_requirements[course_id] = requirement
		day_patterns[course_id] = DAY_PATTERN
		instance_lookup[course_id] = group_id

	teacher_courses = {teacher: tuple(sorted(courses)) for teacher, courses in teacher_course_buffer.items()}

	lab_block = LabVariableBlock(
		assignments=assignments,
		requirements=lab_requirements,
		teacher_courses=teacher_courses,
		day_patterns=day_patterns,
		lab_session_names=tuple(sorted(lab_session_names)) if lab_session_names else tuple(),
		room_ids=tuple(sorted(room_ids)) if room_ids else tuple(),
		instance_group_lookup=instance_lookup,
	)

	course_groups = []
	added_groups = set()
	for group_id, teacher_id in theory_groups.items():
		if group_id in added_groups:
			continue
		course_groups.append(
			CourseGroup(
				key=DEPT_KEY,
				group_id=group_id,
				ordinal=len(course_groups) + 1,
				is_professional_elective=False,
				course_instance_ids=(f"{group_id}_C",),
				teacher_ids=(teacher_id,),
				course_codes=("GEN101",),
				summary=SUMMARY,
				tags=tuple(),
			)
		)
		added_groups.add(group_id)

	preprocessing = SimpleNamespace(groups={DEPT_KEY: tuple(course_groups)} if course_groups else {}, scheduling_packages={})
	raw_time = SimpleNamespace(working_days=DAY_PATTERN, lab_session_to_theory=lab_session_map)
	data = ExtendedDataContainer(raw=SimpleNamespace(time=raw_time), preprocessing=preprocessing)

	variables = VariableCreationResult(lab=lab_block, theory=theory_block, metadata={})
	context = ConstraintContext(
		model=model,
		config=SimpleNamespace(),
		data=data,
		variables=variables,
		logger=logging.getLogger("tests.constraints.teacher_overlap"),
	)

	return context, theory_vars, lab_vars


def test_prevents_theory_conflicts_for_same_teacher() -> None:
	context, theory_vars, _ = _build_context(theory_groups={"G1": "T1", "G2": "T1"})
	constraint = build_teacher_overlap_constraint(metadata=_metadata("theory"))
	result = constraint.apply(context)
	assert result.status == ConstraintStatus.APPLIED

	context.model.Add(theory_vars["G1"] == 1)
	context.model.Add(theory_vars["G2"] == 1)

	solver = cp_model.CpSolver()
	status = solver.Solve(context.model)
	assert status == cp_model.INFEASIBLE


def test_prevents_lab_theory_overlap_for_teacher() -> None:
	lab_courses = {
		"LAB1": {
			"teacher_id": "T1",
			"group_id": "G1",
			"course_code": "LAB101",
			"practical_hours": 2,
			"session_name": "L1",
			"room_id": "R1",
		},
	}
	context, theory_vars, lab_vars = _build_context(
		theory_groups={"G1": "T1"},
		lab_courses=lab_courses,
		lab_session_map={"L1": (0,)},
	)
	constraint = build_teacher_overlap_constraint(metadata=_metadata("lab_vs_theory"))
	constraint.apply(context)

	context.model.Add(theory_vars["G1"] == 1)
	context.model.Add(lab_vars["LAB1"] == 1)

	solver = cp_model.CpSolver()
	status = solver.Solve(context.model)
	assert status == cp_model.INFEASIBLE


def test_allows_co_scheduled_duplicate_lab_course() -> None:
	lab_courses = {
		"LAB_A": {
			"teacher_id": "T1",
			"group_id": "G1",
			"course_code": "LAB140",
			"practical_hours": 4,
			"session_name": "L1",
			"room_id": "R1",
		},
		"LAB_B": {
			"teacher_id": "T1",
			"group_id": "G1",
			"course_code": "LAB140",
			"practical_hours": 4,
			"session_name": "L1",
			"room_id": "R2",
		},
	}
	context, _, lab_vars = _build_context(lab_courses=lab_courses, lab_session_map={"L1": (0,)})
	constraint = build_teacher_overlap_constraint(metadata=_metadata("co_schedule"))
	result = constraint.apply(context)
	assert result.status == ConstraintStatus.SKIPPED

	context.model.Add(lab_vars["LAB_A"] == 1)
	context.model.Add(lab_vars["LAB_B"] == 1)

	solver = cp_model.CpSolver()
	status = solver.Solve(context.model)
	assert status in {cp_model.FEASIBLE, cp_model.OPTIMAL}
