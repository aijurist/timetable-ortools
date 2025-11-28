"""Tests for the theory classroom assignment constraint."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Dict, Iterable, Tuple

import pandas as pd
from ortools.sat.python import cp_model

from src.constraints.base import ConstraintMetadata
from src.constraints.context import ConstraintContext
from src.constraints.schema import ConstraintStatus
from src.constraints.theory.room_assignment import build_theory_room_assignment_constraint
from src.data.schemas import ExtendedDataContainer, RoomCollections
from src.models.schema import (
	LabVariableBlock,
	TheoryCourseRequirement,
	TheoryVariableBlock,
	VariableCreationResult,
)


def _build_context(
	room_specs: Iterable[Dict[str, object]],
	course_specs: Iterable[Dict[str, object]],
) -> Tuple[ConstraintContext, Dict[str, cp_model.IntVar]]:
	model = cp_model.CpModel()
	assignments: Dict[str, Dict[str, Dict[int, Dict[int, cp_model.IntVar]]]] = {}
	room_assignments: Dict[str, Dict[str, Dict[int, Dict[int, Dict[str, cp_model.IntVar]]]]] = {}
	course_requirements: Dict[str, TheoryCourseRequirement] = {}
	teacher_courses: Dict[str, Tuple[str, ...]] = {}
	course_day_patterns: Dict[str, Tuple[str, ...]] = {}
	course_vars: Dict[str, cp_model.IntVar] = {}

	room_list = list(room_specs)
	room_ids = tuple(str(room["id"]) for room in room_list)
	for spec in course_specs:
		course_id = spec["course_id"]
		teacher_id = spec.get("teacher_id", "T1")
		day_idx = spec.get("day", 0)
		slot_idx = spec.get("slot", 0)
		var = model.NewBoolVar(f"{course_id}_d{day_idx}_s{slot_idx}")
		assignments.setdefault(teacher_id, {}).setdefault(course_id, {}).setdefault(day_idx, {})[slot_idx] = var
		room_bucket = {}
		for room_id in room_ids:
			room_var = model.NewBoolVar(f"{course_id}_d{day_idx}_s{slot_idx}_r{room_id}")
			room_bucket[room_id] = room_var
		if room_bucket:
			model.Add(sum(room_bucket.values()) == var)
		room_assignments.setdefault(teacher_id, {}).setdefault(course_id, {}).setdefault(day_idx, {})[slot_idx] = room_bucket
		teacher_courses.setdefault(teacher_id, []).append(course_id)
		course_vars[course_id] = var
		course_day_patterns[course_id] = ("mon",)
		course_requirements[course_id] = TheoryCourseRequirement(
			course_instance_id=course_id,
			course_code=spec.get("course_code", course_id),
			group_id=spec.get("group_id", f"G_{course_id}"),
			teacher_id=teacher_id,
			department=spec.get("department", "Dept"),
			semester=spec.get("semester", 5),
			required_slots=1,
			lecture_hours=1,
			tutorial_hours=0,
			student_count=spec.get("student_count", 60),
			preferred_room_type=None,
			required_room_type=None,
			tags=tuple(),
		)

	teacher_courses = {teacher: tuple(courses) for teacher, courses in teacher_courses.items()}

	theory_block = TheoryVariableBlock(
		assignments=assignments,
		room_assignments=room_assignments,
		course_requirements=course_requirements,
		teacher_courses=teacher_courses,
		course_day_patterns=course_day_patterns,
		group_timeslots={},
		requirements={},
		day_patterns={},
		theory_slot_labels=("Slot-1", "Slot-2"),
		group_course_index={},
		instance_group_lookup={},
		room_ids=room_ids,
	)

	lab_block = LabVariableBlock(
		assignments={},
		requirements={},
		teacher_courses={},
		day_patterns={},
		lab_session_names=tuple(),
		room_ids=tuple(),
		instance_group_lookup={},
	)

	room_df = pd.DataFrame(room_list)
	rooms = RoomCollections(
		lab_rooms=pd.DataFrame(),
		theory_rooms=room_df,
		lab_room_ids=tuple(),
		theory_room_ids=room_ids,
		laboratory_room_ids=tuple(),
	)

	raw = SimpleNamespace(
		time=SimpleNamespace(theory_slots=("Slot-1", "Slot-2")),
		departments=SimpleNamespace(day_patterns={"__default__": ("mon", "tue")}),
		rooms=rooms,
		room_registry={str(room["id"]): room for room in room_list},
		rooms_df=room_df,
	)
	data = ExtendedDataContainer(raw=raw, preprocessing=SimpleNamespace())

	variables = VariableCreationResult(lab=lab_block, theory=theory_block, metadata={})
	context = ConstraintContext(
		model=model,
		config=SimpleNamespace(),
		data=data,
		variables=variables,
		logger=SimpleNamespace(getChild=lambda _name: SimpleNamespace()),
	)
	return context, course_vars


def _apply_constraint(context: ConstraintContext):
	metadata = ConstraintMetadata(
		id="theory.room_assignment",
		name="Theory Classroom Assignment",
		category="theory",
		priority=8,
	)
	constraint = build_theory_room_assignment_constraint(metadata=metadata, params={})
	return constraint.apply(context)


def test_big_courses_require_140_rooms():
	rooms = [
		{"id": "A1", "block": "A Block", "room_max_cap": 160},
		{"id": "A2", "block": "A Block", "room_max_cap": 80},
	]
	courses = [
		{"course_id": "C_BIG_1", "semester": 5, "student_count": 150},
		{"course_id": "C_BIG_2", "semester": 5, "student_count": 150},
	]
	context, vars_map = _build_context(rooms, courses)
	result = _apply_constraint(context)
	assert result.status == ConstraintStatus.APPLIED

	context.model.Add(vars_map["C_BIG_1"] == 1)
	context.model.Add(vars_map["C_BIG_2"] == 1)
	status = cp_model.CpSolver().Solve(context.model)
	assert status == cp_model.INFEASIBLE


def test_small_courses_cannot_use_140_only_block():
	rooms = [
		{"id": "A1", "block": "A Block", "room_max_cap": 150},
	]
	courses = [
		{"course_id": "C_SMALL", "semester": 5, "student_count": 60},
	]
	context, vars_map = _build_context(rooms, courses)
	result = _apply_constraint(context)
	assert result.status == ConstraintStatus.APPLIED

	context.model.Add(vars_map["C_SMALL"] == 1)
	solver = cp_model.CpSolver()
	status = solver.Solve(context.model)
	assert status == cp_model.INFEASIBLE


def test_second_year_overflow_uses_c_block():
	rooms = [
		{"id": "B1", "block": "B Block", "room_max_cap": 70},
		{"id": "C1", "block": "C Block", "room_max_cap": 70},
	]
	courses = [
		{"course_id": "C_S2_A", "semester": 3, "student_count": 60},
		{"course_id": "C_S2_B", "semester": 3, "student_count": 60},
	]
	context, vars_map = _build_context(rooms, courses)
	result = _apply_constraint(context)
	assert result.status == ConstraintStatus.APPLIED

	context.model.Add(vars_map["C_S2_A"] == 1)
	context.model.Add(vars_map["C_S2_B"] == 1)
	solver = cp_model.CpSolver()
	status = solver.Solve(context.model)
	assert status == cp_model.OPTIMAL


def test_year_block_preferences_penalise_alt_blocks():
	rooms = [
		{"id": "B1", "block": "B Block", "room_max_cap": 70},
		{"id": "C1", "block": "C Block", "room_max_cap": 70},
	]
	courses = [
		{"course_id": "C_S3", "semester": 3, "student_count": 60},
	]
	context, _ = _build_context(rooms, courses)
	result = _apply_constraint(context)
	assert result.status == ConstraintStatus.APPLIED
	assert result.details["overflow_penalties"] > 0
