"""Tests for selected theory courses that must be scheduled in consecutive pairs."""

from __future__ import annotations

import logging
from types import SimpleNamespace

from ortools.sat.python import cp_model

from src.constraints.base import ConstraintMetadata
from src.constraints.context import ConstraintContext
from src.constraints.schema import ConstraintStatus
from src.constraints.theory.course_consecutive_pairs import (
	build_theory_course_consecutive_pairs_constraint,
)
from src.data.schemas import ExtendedDataContainer
from src.models.schema import (
	LabVariableBlock,
	TheoryCourseRequirement,
	TheoryVariableBlock,
	VariableCreationResult,
)


def _metadata() -> ConstraintMetadata:
	return ConstraintMetadata(
		id="theory.course_consecutive_pairs",
		name="Theory Course Consecutive Pairs",
		category="theory",
		priority=9,
	)


def _build_context(
	*,
	course_code: str = "GE23627",
	required_slots: int = 4,
	slot_count: int = 5,
	rooms_by_slot: dict[int, tuple[str, ...]] | None = None,
) -> tuple[ConstraintContext, dict[int, cp_model.IntVar], dict[tuple[int, str], cp_model.IntVar]]:
	model = cp_model.CpModel()
	course_id = "C_GE23627"
	teacher_id = "T1"
	day_idx = 0
	slot_vars: dict[int, cp_model.IntVar] = {}
	room_vars: dict[tuple[int, str], cp_model.IntVar] = {}
	assignments = {teacher_id: {course_id: {day_idx: {}}}}
	room_assignments = {teacher_id: {course_id: {day_idx: {}}}}
	all_room_ids: set[str] = set()

	for slot_idx in range(slot_count):
		slot_var = model.NewBoolVar(f"{course_id}_s{slot_idx}")
		slot_vars[slot_idx] = slot_var
		assignments[teacher_id][course_id][day_idx][slot_idx] = slot_var
		room_ids = (rooms_by_slot or {}).get(slot_idx, ("R1", "R2"))
		room_bucket: dict[str, cp_model.IntVar] = {}
		for room_id in room_ids:
			all_room_ids.add(room_id)
			room_var = model.NewBoolVar(f"{course_id}_s{slot_idx}_r{room_id}")
			room_bucket[room_id] = room_var
			room_vars[(slot_idx, room_id)] = room_var
		if room_bucket:
			model.Add(sum(room_bucket.values()) == slot_var)
		else:
			model.Add(slot_var == 0)
		room_assignments[teacher_id][course_id][day_idx][slot_idx] = room_bucket

	theory_requirement = TheoryCourseRequirement(
		course_instance_id=course_id,
		course_code=course_code,
		group_id="G1",
		teacher_id=teacher_id,
		department="Electrical & Electronics Engineering",
		semester=5,
		required_slots=required_slots,
		lecture_hours=required_slots,
		tutorial_hours=0,
		student_count=65,
		preferred_room_type=None,
		required_room_type=None,
	)
	theory_block = TheoryVariableBlock(
		assignments=assignments,
		room_assignments=room_assignments,
		course_requirements={course_id: theory_requirement},
		teacher_courses={teacher_id: (course_id,)},
		course_day_patterns={course_id: ("mon",)},
		theory_slot_labels=tuple(f"S{idx}" for idx in range(slot_count)),
		instance_group_lookup={course_id: "G1"},
		room_ids=tuple(sorted(all_room_ids)),
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
	context = ConstraintContext(
		model=model,
		config=SimpleNamespace(),
		data=ExtendedDataContainer(raw=SimpleNamespace(), preprocessing=SimpleNamespace()),
		variables=VariableCreationResult(lab=lab_block, theory=theory_block, metadata={}),
		logger=logging.getLogger("tests.constraints.theory_course_consecutive_pairs"),
	)
	return context, slot_vars, room_vars


def _apply_constraint(context: ConstraintContext, params: dict[str, object]):
	constraint = build_theory_course_consecutive_pairs_constraint(
		metadata=_metadata(),
		params=params,
	)
	return constraint.apply(context)


def test_course_specific_required_slots_override_applies_to_ge23627() -> None:
	context, slot_vars, _room_vars = _build_context(required_slots=4, slot_count=5)

	result = _apply_constraint(
		context,
		{
			"course_codes": ["GE23627"],
			"required_slots": 2,
			"required_slots_by_course": {"GE23627": 4},
			"pair_length": 2,
		},
	)

	assert result.status == ConstraintStatus.APPLIED
	assert result.details["courses"] == 1

	for idx, var in slot_vars.items():
		context.model.Add(var == (1 if idx in {0, 2, 3, 4} else 0))

	solver = cp_model.CpSolver()
	assert solver.Solve(context.model) == cp_model.INFEASIBLE


def test_course_specific_required_slots_override_accepts_two_valid_pairs() -> None:
	context, slot_vars, room_vars = _build_context(required_slots=4, slot_count=5)

	result = _apply_constraint(
		context,
		{
			"course_codes": ["GE23627"],
			"required_slots": 2,
			"required_slots_by_course": {"GE23627": 4},
			"pair_length": 2,
			"enforce_same_room": True,
		},
	)

	assert result.status == ConstraintStatus.APPLIED

	for idx, var in slot_vars.items():
		context.model.Add(var == (1 if idx in {0, 1, 3, 4} else 0))
	for idx in (0, 1, 3, 4):
		context.model.Add(room_vars[(idx, "R1")] == 1)

	solver = cp_model.CpSolver()
	assert solver.Solve(context.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)


def test_same_room_enforcement_blocks_different_rooms_when_candidate_sets_differ() -> None:
	context, slot_vars, room_vars = _build_context(
		required_slots=2,
		slot_count=2,
		rooms_by_slot={0: ("R1", "R2"), 1: ("R2", "R3")},
	)

	result = _apply_constraint(
		context,
		{
			"course_codes": ["GE23627"],
			"required_slots": 2,
			"pair_length": 2,
			"enforce_same_room": True,
		},
	)

	assert result.status == ConstraintStatus.APPLIED
	context.model.Add(slot_vars[0] == 1)
	context.model.Add(slot_vars[1] == 1)
	context.model.Add(room_vars[(0, "R1")] == 1)
	context.model.Add(room_vars[(1, "R3")] == 1)

	solver = cp_model.CpSolver()
	assert solver.Solve(context.model) == cp_model.INFEASIBLE
