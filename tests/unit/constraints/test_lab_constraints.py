"""Unit tests for lab constraint implementations."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Optional

import pandas as pd
import pytest
from ortools.sat.python import cp_model

from src.constraints.base import ConstraintMetadata
from src.constraints.context import ConstraintContext
from src.constraints.lab.computer_lab_mapping import (
	ComputerLabMappingStats,
	build_computer_lab_mapping_constraint,
)
from src.constraints.lab.core_lab import build_core_lab_mapping_constraint
from src.constraints.lab.requirements import build_lab_session_coverage_constraint
from src.constraints.lab.room_single_assignment import build_lab_room_single_assignment_constraint
from src.constraints.lab.slot_caps import (
	build_computing_group_slot_cap_constraint,
	build_core_lab_group_slot_cap_constraint,
	build_semester_lab_slot_cap_constraint,
)
from src.constraints.lab.teacher_daily_presence_lab import build_teacher_daily_presence_lab_constraint
from src.constraints.lab.teacher_max_consecutive import build_teacher_max_consecutive_lab_constraint
from src.constraints.schema import ConstraintStatus
from src.data.schemas import ExtendedDataContainer, LabSessionDetail, RoomCollections
from src.models.variables import (
	GroupTimeslotRequirement,
	LabCourseRequirement,
	LabVariableBlock,
	TheoryVariableBlock,
	VariableCreationResult,
)


def _build_constraint_context(
	*,
	drop_assignments_for: Optional[str] = None,
	include_mapping: bool = True,
	laboratory_room_ids: Optional[tuple[str, ...]] = None,
) -> ConstraintContext:
	model = cp_model.CpModel()
	core_allowed = model.NewBoolVar("core_allowed")
	core_forbidden = model.NewBoolVar("core_forbidden")
	general_var = model.NewBoolVar("general")

	lab_requirements = {
		"C_CORE": LabCourseRequirement(
			course_instance_id="C_CORE",
			course_code="CORE101",
			teacher_id="T1",
			group_id="G1",
			department="Computer Science",
			semester=5,
			practical_hours=2,
			required_sessions=1,
			student_count=32,
			preferred_room_type=None,
			required_room_type=None,
			tags=("core",),
		),
		"C_GEN": LabCourseRequirement(
			course_instance_id="C_GEN",
			course_code="GEN101",
			teacher_id="T1",
			group_id="G2",
			department="Information Technology",
			semester=3,
			practical_hours=2,
			required_sessions=1,
			student_count=28,
			preferred_room_type=None,
			required_room_type=None,
			tags=("lab",),
		),
	}

	assignments = {
		"T1": {
			"C_CORE": {
				0: {
					"L1": {
						"R1": core_allowed,
						"R2": core_forbidden,
					},
				}
			},
			"C_GEN": {
				0: {
					"L1": {
						"R1": general_var,
					},
				}
			},
		},
	}

	if drop_assignments_for:
		assignments["T1"].pop(drop_assignments_for, None)

	lab_block = LabVariableBlock(
		assignments=assignments,
		requirements=lab_requirements,
		teacher_courses={"T1": tuple(lab_requirements.keys())},
		day_patterns={key: ("monday",) for key in lab_requirements},
		lab_session_names=("L1",),
		room_ids=("R1", "R2", "R3"),
		instance_group_lookup={"C_CORE": "G1", "C_GEN": "G2"},
	)

	theory_var = model.NewBoolVar("theory")
	group_requirement = GroupTimeslotRequirement(
		group_id="G1",
		department="Computer Science",
		semester=5,
		required_theory_slots=2,
		day_pattern=("monday",),
		lunch_slot_window=(),
		five_pm_policy=None,
		tags=("theory",),
		base_requirement=None,
	)
	theory_block = TheoryVariableBlock(
		group_timeslots={"G1": {0: {0: theory_var}}},
		requirements={"G1": group_requirement},
		day_patterns={"G1": ("monday",)},
		theory_slot_labels=("Slot-1",),
	)

	time_ns = SimpleNamespace(
		lab_sessions={
			"L1": LabSessionDetail(name="L1", slots=(0, 1), time_range="8:00-9:40"),
		},
		working_days=("monday", "tuesday"),
	)
	departments_ns = SimpleNamespace(day_patterns={"__default__": ("monday", "tuesday")})
	rooms_df = pd.DataFrame(
		[
			{"id": "R1", "room_number": "L11", "room_name": "Core Lab", "description": "", "block": "A"},
			{"id": "R2", "room_number": "L12", "room_name": "General Lab", "description": "", "block": "B"},
		]
	)
	rooms = RoomCollections(
		lab_rooms=pd.DataFrame(),
		theory_rooms=pd.DataFrame(),
		lab_room_ids=("R1", "R2", "R3"),
		theory_room_ids=tuple(),
		laboratory_room_ids=laboratory_room_ids or ("R1", "R2"),
	)
	core_mapping_df = (
		pd.DataFrame(
			[
				{"course_code": "CORE101", "lab_1_room": "L11", "lab_1_block": "A"},
			]
			)
			if include_mapping
			else None
	)

	raw = SimpleNamespace(
		time=time_ns,
		departments=departments_ns,
		room_registry={"R1": {"capacity": 60}, "R2": {"capacity": 45}},
		rooms=rooms,
		rooms_df=rooms_df,
		core_lab_mapping_df=core_mapping_df,
	)
	data = ExtendedDataContainer(raw=raw, preprocessing=SimpleNamespace())

	variables = VariableCreationResult(lab=lab_block, theory=theory_block, metadata={})
	logger = logging.getLogger("tests.constraints.lab")
	return ConstraintContext(
		model=model,
		config=SimpleNamespace(),
		data=data,
		variables=variables,
		logger=logger,
	)


def _build_slot_cap_context() -> ConstraintContext:
	model = cp_model.CpModel()

	def _add_course(
		assignments: dict[str, dict],
		teacher_id: str,
		course_id: str,
		combos: tuple[tuple[int, str], ...],
	) -> None:
		teacher_entry = assignments.setdefault(teacher_id, {})
		course_entry = teacher_entry.setdefault(course_id, {})
		for day_idx, session_name in combos:
			day_entry = course_entry.setdefault(day_idx, {})
			session_entry = day_entry.setdefault(session_name, {})
			session_entry["R1"] = model.NewBoolVar(f"{course_id}_{day_idx}_{session_name}")

	lab_requirements = {
		"CORE_A": LabCourseRequirement(
			course_instance_id="CORE_A",
			course_code="CORE101",
			teacher_id="T1",
			group_id="G_CORE",
			department="Computer Science & Engineering",
			semester=5,
			practical_hours=2,
			required_sessions=1,
			student_count=30,
			preferred_room_type=None,
			required_room_type=None,
			tags=("core",),
		),
		"CORE_B": LabCourseRequirement(
			course_instance_id="CORE_B",
			course_code="CORE102",
			teacher_id="T1",
			group_id="G_CORE",
			department="Computer Science & Engineering",
			semester=5,
			practical_hours=2,
			required_sessions=1,
			student_count=30,
			preferred_room_type=None,
			required_room_type=None,
			tags=("core",),
		),
		"NON_A": LabCourseRequirement(
			course_instance_id="NON_A",
			course_code="ELE201",
			teacher_id="T2",
			group_id="G_OTHER",
			department="Computer Science & Engineering",
			semester=5,
			practical_hours=2,
			required_sessions=1,
			student_count=28,
			preferred_room_type=None,
			required_room_type=None,
			tags=("lab",),
		),
	}

	assignments: dict[str, dict] = {}
	_add_course(assignments, "T1", "CORE_A", ((0, "L1"), (1, "L1"), (2, "L2")))
	_add_course(assignments, "T1", "CORE_B", ((0, "L2"), (1, "L2")))
	_add_course(assignments, "T2", "NON_A", ((0, "L1"), (1, "L2")))

	lab_block = LabVariableBlock(
		assignments=assignments,
		requirements=lab_requirements,
		teacher_courses={"T1": ("CORE_A", "CORE_B"), "T2": ("NON_A",)},
		day_patterns={key: ("monday", "tuesday", "wed") for key in lab_requirements},
		lab_session_names=("L1", "L2"),
		room_ids=("R1",),
		instance_group_lookup={"CORE_A": "G_CORE", "CORE_B": "G_CORE", "NON_A": "G_OTHER"},
	)

	theory_var = model.NewBoolVar("theory_slot")
	theory_requirement = GroupTimeslotRequirement(
		group_id="G_CORE",
		department="Computer Science & Engineering",
		semester=5,
		required_theory_slots=2,
		day_pattern=("monday",),
		lunch_slot_window=(),
		five_pm_policy=None,
	)
	theory_block = TheoryVariableBlock(
		group_timeslots={"G_CORE": {0: {0: theory_var}}},
		requirements={"G_CORE": theory_requirement},
		day_patterns={"G_CORE": ("monday",)},
		theory_slot_labels=("Slot-1",),
	)

	time_ns = SimpleNamespace(
		lab_sessions={
			"L1": LabSessionDetail(name="L1", slots=(0, 1), time_range="8:00-9:40"),
			"L2": LabSessionDetail(name="L2", slots=(2, 3), time_range="9:50-11:30"),
		},
		working_days=("monday", "tuesday", "wed"),
	)
	departments_ns = SimpleNamespace(day_patterns={"__default__": ("monday", "tuesday", "wed")})
	rooms_df = pd.DataFrame(
		[
			{"id": "R1", "room_number": "Lab1", "room_name": "Primary Lab", "description": "", "block": "A"},
		]
	)
	rooms = RoomCollections(
		lab_rooms=pd.DataFrame(),
		theory_rooms=pd.DataFrame(),
		lab_room_ids=("R1",),
		theory_room_ids=tuple(),
		laboratory_room_ids=("R1",),
	)
	core_mapping_df = pd.DataFrame(
		[
			{"course_code": "CORE101", "lab_1_room": "Lab1"},
			{"course_code": "CORE102", "lab_1_room": "Lab1"},
		]
	)
	preprocessing_groups = {
		"CSE_S5": (
			SimpleNamespace(
				group_id="G_CORE",
				key=SimpleNamespace(department="Computer Science & Engineering", semester=5),
			),
			SimpleNamespace(
				group_id="G_OTHER",
				key=SimpleNamespace(department="Computer Science & Engineering", semester=5),
			),
		),
	}

	raw = SimpleNamespace(
		time=time_ns,
		departments=departments_ns,
		room_registry={"R1": {"capacity": 60}},
		rooms=rooms,
		rooms_df=rooms_df,
		core_lab_mapping_df=core_mapping_df,
	)
	data = ExtendedDataContainer(raw=raw, preprocessing=SimpleNamespace(groups=preprocessing_groups))

	variables = VariableCreationResult(lab=lab_block, theory=theory_block, metadata={})
	logger = logging.getLogger("tests.constraints.lab.slot_caps")
	return ConstraintContext(
		model=model,
		config=SimpleNamespace(),
		data=data,
		variables=variables,
		logger=logger,
	)


def _build_teacher_consecutive_context(
	*,
	course_definitions: Optional[tuple[tuple[str, str, tuple[tuple[int, str], ...]], ...]] = None,
	session_labels: tuple[str, ...] = ("L1", "L2", "L3"),
) -> ConstraintContext:
	model = cp_model.CpModel()
	course_definitions = course_definitions or (
		(
			"COURSE_A",
			"Computer Science & Engineering",
			((0, "L1"), (0, "L2"), (0, "L3")),
		),
	)

	assignments: dict[str, dict[str, dict[int, dict[str, dict[str, cp_model.IntVar]]]]] = {"T_CON": {}}
	lab_requirements: dict[str, LabCourseRequirement] = {}
	instance_group_lookup: dict[str, str] = {}

	for index, (course_id, department, combos) in enumerate(course_definitions):
		lab_requirements[course_id] = LabCourseRequirement(
			course_instance_id=course_id,
			course_code=f"LC{index}",
			teacher_id="T_CON",
			group_id=f"G_CON_{index}",
			department=department,
			semester=5,
			practical_hours=2,
			required_sessions=1,
			student_count=30,
			preferred_room_type=None,
			required_room_type=None,
		)
		instance_group_lookup[course_id] = f"G_CON_{index}"
		course_entry = assignments["T_CON"].setdefault(course_id, {})
		for day_index, session_name in combos:
			day_entry = course_entry.setdefault(day_index, {})
			session_entry = day_entry.setdefault(session_name, {})
			session_entry["R_CON"] = model.NewBoolVar(f"{course_id}_d{day_index}_{session_name}")

	lab_block = LabVariableBlock(
		assignments=assignments,
		requirements=lab_requirements,
		teacher_courses={"T_CON": tuple(lab_requirements.keys())},
		day_patterns={course_id: ("monday",) for course_id in lab_requirements},
		lab_session_names=session_labels,
		room_ids=("R_CON",),
		instance_group_lookup=instance_group_lookup,
	)

	theory_var = model.NewBoolVar("theory_placeholder")
	theory_requirement = GroupTimeslotRequirement(
		group_id="G_CON",
		department="Computer Science & Engineering",
		semester=5,
		required_theory_slots=1,
		day_pattern=("monday",),
		lunch_slot_window=(),
		five_pm_policy=None,
	)
	theory_block = TheoryVariableBlock(
		group_timeslots={"G_CON": {0: {0: theory_var}}},
		requirements={"G_CON": theory_requirement},
		day_patterns={"G_CON": ("monday",)},
		theory_slot_labels=("Slot-1",),
	)

	time_ns = SimpleNamespace(
		lab_sessions={
			session: LabSessionDetail(name=session, slots=(i, i + 1), time_range=f"{8 + i}:00-{9 + i}:40")
			for i, session in enumerate(session_labels)
		},
		working_days=("monday",),
	)
	departments_ns = SimpleNamespace(day_patterns={"__default__": ("monday",)})
	rooms = RoomCollections(
		lab_rooms=pd.DataFrame(),
		theory_rooms=pd.DataFrame(),
		lab_room_ids=("R_CON",),
		theory_room_ids=tuple(),
		laboratory_room_ids=("R_CON",),
	)
	raw = SimpleNamespace(
		time=time_ns,
		departments=departments_ns,
		room_registry={"R_CON": {"capacity": 36}},
		rooms=rooms,
		rooms_df=pd.DataFrame(),
		core_lab_mapping_df=None,
	)
	data = ExtendedDataContainer(raw=raw, preprocessing=SimpleNamespace())
	variables = VariableCreationResult(lab=lab_block, theory=theory_block, metadata={})
	logger = logging.getLogger("tests.constraints.lab.teacher_consecutive")
	return ConstraintContext(
		model=model,
		config=SimpleNamespace(),
		data=data,
		variables=variables,
		logger=logger,
	)


@pytest.fixture()
def lab_constraint_context() -> ConstraintContext:
	return _build_constraint_context()


@pytest.fixture()
def slot_cap_constraint_context() -> ConstraintContext:
	return _build_slot_cap_context()


def _metadata(identifier: str, priority: int = 10) -> ConstraintMetadata:
	return ConstraintMetadata(
		id=f"lab.{identifier}",
		name=identifier.replace("_", " ").title(),
		category="lab",
		priority=priority,
		description=f"Test metadata for {identifier}",
	)


def test_lab_session_coverage_enforces_totals(lab_constraint_context: ConstraintContext) -> None:
	constraint = build_lab_session_coverage_constraint(metadata=_metadata("session_coverage"))
	result = constraint.apply(lab_constraint_context)
	assert result.status == ConstraintStatus.APPLIED
	assert result.details["courses"] == 2


def test_lab_session_coverage_reports_missing_assignments() -> None:
	context = _build_constraint_context(drop_assignments_for="C_CORE")
	constraint = build_lab_session_coverage_constraint(metadata=_metadata("session_coverage"))
	result = constraint.apply(context)
	assert "C_CORE" in result.details["missing_courses"]


def test_core_lab_mapping_enforces_room_whitelist(lab_constraint_context: ConstraintContext) -> None:
	constraint = build_core_lab_mapping_constraint(metadata=_metadata("core_lab_mapping", priority=8))
	result = constraint.apply(lab_constraint_context)
	assert result.status == ConstraintStatus.APPLIED
	assert result.details["forbidden_assignments"] == 1
	assert result.details["mapped_courses"] == 1


def test_core_lab_mapping_skips_when_mapping_missing() -> None:
	context = _build_constraint_context(include_mapping=False)
	constraint = build_core_lab_mapping_constraint(metadata=_metadata("core_lab_mapping", priority=8))
	result = constraint.apply(context)
	assert result.status == ConstraintStatus.SKIPPED


def test_core_lab_mapping_falls_back_to_variable_rooms() -> None:
	context = _build_constraint_context(laboratory_room_ids=tuple())
	constraint = build_core_lab_mapping_constraint(metadata=_metadata("core_lab_mapping", priority=8))
	result = constraint.apply(context)
	assert result.details["general_courses"] == 1
	assert result.details["skipped_courses"] == ()


def test_computer_lab_mapping_resolves_alias_and_block_only_rows() -> None:
	constraint = build_computer_lab_mapping_constraint(metadata=_metadata("computer_lab_mapping", priority=8))
	rooms_df = pd.DataFrame(
		[
			{
				"id": "R_K",
				"room_number": "KFL01",
				"room_name": "K Lab",
				"description": "Computer Lab",
				"block": "K Block",
				"room_type": "Computer-Lab",
			},
			{
				"id": "R_J",
				"room_number": "JL1",
				"room_name": "J Lab",
				"description": "Computer Lab",
				"block": "J Block",
				"room_type": "Computer-Lab",
			},
			{
				"id": "R_A",
				"room_number": "A101",
				"room_name": "A Classroom",
				"description": "Classroom",
				"block": "A Block",
				"room_type": "Class-Room",
			},
		]
	)
	mapping_df = pd.DataFrame(
		[
			{
				"department": "aids",
				"course_code": "AD23531",
				"preferred_lab_room": "",
				"preferred_lab_block": "J Block;K Block",
			}
		]
	)
	stats = ComputerLabMappingStats()
	room_lookup = build_core_lab_mapping_constraint(
		metadata=_metadata("core_lab_mapping", priority=8)
	)._build_room_lookup(rooms_df)
	block_lookup = constraint._build_computer_lab_block_lookup(rooms_df)

	room_map = constraint._build_room_map(
		mapping_df,
		room_lookup,
		block_lookup,
		logging.getLogger("tests.constraints.lab.computer_lab_mapping"),
		stats,
	)

	preference = room_map[("artificial intelligence and data science", "AD23531")]
	assert preference.room_ids == {"R_J", "R_K"}
	assert "R_A" not in preference.room_ids
	assert preference.mode == "soft"
	assert preference.penalty_weight == 500
	assert stats.mapping_rows == 1
	assert stats.soft_mapping_rows == 1


def _build_computer_lab_mapping_context(mapping_df: pd.DataFrame) -> tuple[ConstraintContext, cp_model.IntVar, cp_model.IntVar]:
	model = cp_model.CpModel()
	preferred_room = model.NewBoolVar("preferred_room")
	other_room = model.NewBoolVar("other_room")

	requirement = LabCourseRequirement(
		course_instance_id="C_GEN",
		course_code="GEN101",
		teacher_id="T1",
		group_id="G1",
		department="Information Technology",
		semester=5,
		practical_hours=2,
		required_sessions=1,
		student_count=30,
		preferred_room_type=None,
		required_room_type=None,
		tags=("lab",),
	)
	lab_block = LabVariableBlock(
		assignments={
			"T1": {
				"C_GEN": {
					0: {
						"L1": {
							"R_PREF": preferred_room,
							"R_OTHER": other_room,
						}
					}
				}
			}
		},
		requirements={"C_GEN": requirement},
		teacher_courses={"T1": ("C_GEN",)},
		day_patterns={"C_GEN": ("monday",)},
		lab_session_names=("L1",),
		room_ids=("R_PREF", "R_OTHER"),
		instance_group_lookup={"C_GEN": "G1"},
	)
	rooms_df = pd.DataFrame(
		[
			{
				"id": "R_PREF",
				"room_number": "L11",
				"room_name": "Preferred Lab",
				"description": "Computer Lab",
				"block": "A Block",
				"room_type": "Computer-Lab",
			},
			{
				"id": "R_OTHER",
				"room_number": "L12",
				"room_name": "Other Lab",
				"description": "Computer Lab",
				"block": "B Block",
				"room_type": "Computer-Lab",
			},
		]
	)
	raw = SimpleNamespace(
		computer_lab_mapping_df=mapping_df,
		rooms_df=rooms_df,
	)
	data = ExtendedDataContainer(raw=raw, preprocessing=SimpleNamespace())
	variables = VariableCreationResult(lab=lab_block, theory=TheoryVariableBlock(), metadata={})
	return (
		ConstraintContext(
			model=model,
			config=SimpleNamespace(),
			data=data,
			variables=variables,
			logger=logging.getLogger("tests.constraints.lab.computer_lab_mapping"),
		),
		preferred_room,
		other_room,
	)


def test_computer_lab_mapping_specific_room_rows_are_hard() -> None:
	context, _preferred_room, other_room = _build_computer_lab_mapping_context(
		pd.DataFrame(
			[
				{
					"department": "it",
					"course_code": "GEN101",
					"preferred_lab_room": "L11",
					"preferred_lab_block": "A Block",
				}
			]
		)
	)
	constraint = build_computer_lab_mapping_constraint(metadata=_metadata("computer_lab_mapping", priority=8))

	result = constraint.apply(context)

	assert result.status == ConstraintStatus.APPLIED
	assert result.details["hard_blocks"] == 1
	assert result.details["soft_penalties"] == 0
	assert result.details["hard_mapping_rows"] == 1
	context.model.Add(other_room == 1)
	solver = cp_model.CpSolver()
	assert solver.Solve(context.model) == cp_model.INFEASIBLE


def test_computer_lab_mapping_block_only_rows_are_soft_with_500_weight() -> None:
	context, _preferred_room, other_room = _build_computer_lab_mapping_context(
		pd.DataFrame(
			[
				{
					"department": "it",
					"course_code": "GEN101",
					"preferred_lab_room": "",
					"preferred_lab_block": "A Block",
				}
			]
		)
	)
	constraint = build_computer_lab_mapping_constraint(metadata=_metadata("computer_lab_mapping", priority=8))

	result = constraint.apply(context)

	assert result.status == ConstraintStatus.APPLIED
	assert result.details["hard_blocks"] == 0
	assert result.details["soft_penalties"] == 1
	assert result.details["soft_mapping_rows"] == 1
	penalties = context.extra["objective"]["penalties"]
	assert penalties == [(500, other_room, "computer_lab_mapping:information technology:GEN101")]


def test_room_single_assignment_detects_conflicts(lab_constraint_context: ConstraintContext) -> None:
	constraint = build_lab_room_single_assignment_constraint(metadata=_metadata("room_single_assignment", priority=9))
	result = constraint.apply(lab_constraint_context)
	assert result.status == ConstraintStatus.APPLIED
	assert result.details["room_conflicts"] >= 1
	assert result.details["course_conflicts"] >= 1


def test_room_single_assignment_skips_when_no_conflicts() -> None:
	context = _build_constraint_context(drop_assignments_for="C_CORE")
	constraint = build_lab_room_single_assignment_constraint(metadata=_metadata("room_single_assignment", priority=9))
	result = constraint.apply(context)
	assert result.status == ConstraintStatus.SKIPPED


def test_core_group_slot_cap_penalizes_excess(slot_cap_constraint_context: ConstraintContext) -> None:
	constraint = build_core_lab_group_slot_cap_constraint(
		metadata=_metadata("core_group_slot_cap", priority=7),
		params={"slot_limit": 2, "penalty_weight": 5},
	)
	result = constraint.apply(slot_cap_constraint_context)
	assert result.status == ConstraintStatus.APPLIED
	assert result.details["targeted_groups"] == 1
	assert result.details["penalty_variables"] == 1


def test_computing_group_slot_cap_targets_computing_departments(
	slot_cap_constraint_context: ConstraintContext,
) -> None:
	constraint = build_computing_group_slot_cap_constraint(
		metadata=_metadata("computing_group_slot_cap", priority=8),
		params={"slot_limit": 3},
	)
	result = constraint.apply(slot_cap_constraint_context)
	assert result.status == ConstraintStatus.APPLIED
	assert result.details["constrained_groups"] >= 1
	assert "G_CORE" in result.details["groups"]


def test_semester_slot_cap_ignores_core_courses(slot_cap_constraint_context: ConstraintContext) -> None:
	constraint = build_semester_lab_slot_cap_constraint(
		metadata=_metadata("semester_slot_cap", priority=8),
		params={"slot_limit": 1},
	)
	result = constraint.apply(slot_cap_constraint_context)
	assert result.status == ConstraintStatus.APPLIED
	assert result.details["constrained_semesters"] == 1
	assert result.details["semesters"] == ("Computer Science & Engineering S5",)


def test_teacher_max_consecutive_blocks_hard_departments() -> None:
	context = _build_teacher_consecutive_context()
	constraint = build_teacher_max_consecutive_lab_constraint(
		metadata=_metadata("teacher_max_consecutive", priority=8)
	)
	result = constraint.apply(context)
	assert result.status == ConstraintStatus.APPLIED
	assert result.details["hard_constraints"] >= 1
	assert result.details["soft_penalties"] == 0
	assert result.details["course_clauses"] >= 1


def test_teacher_max_consecutive_penalises_soft_departments() -> None:
	courses = (("COURSE_SOFT", "Biotechnology", ((0, "L1"), (0, "L2"), (0, "L3"))),)
	context = _build_teacher_consecutive_context(course_definitions=courses)
	constraint = build_teacher_max_consecutive_lab_constraint(
		metadata=_metadata("teacher_max_consecutive_soft", priority=8),
		params={"soft_departments": ("Biotechnology",), "soft_penalty_weight": 3},
	)
	result = constraint.apply(context)
	assert result.status == ConstraintStatus.APPLIED
	assert result.details["soft_penalties"] >= 1
	assert result.details["penalty_variables"] >= 1
	assert "T_CON" in result.details["soft_teachers"]


def test_teacher_max_consecutive_checks_cross_course_sequences() -> None:
	courses = (
		("COURSE_L1", "Computer Science & Engineering", ((0, "L1"),)),
		("COURSE_L23", "Computer Science & Engineering", ((0, "L2"), (0, "L3"))),
	)
	context = _build_teacher_consecutive_context(course_definitions=courses)
	constraint = build_teacher_max_consecutive_lab_constraint(
		metadata=_metadata("teacher_max_consecutive_cross", priority=8)
	)
	result = constraint.apply(context)
	assert result.status == ConstraintStatus.APPLIED
	assert result.details["cross_course_clauses"] >= 1


def test_teacher_daily_presence_blocks_early_late_combo() -> None:
	courses = (
		("COURSE_EARLY", "Computer Science & Engineering", ((0, "L1"),)),
		("COURSE_LATE", "Computer Science & Engineering", ((0, "L6"),)),
	)
	context = _build_teacher_consecutive_context(
		course_definitions=courses,
		session_labels=("L1", "L2", "L3", "L4", "L5", "L6"),
	)
	constraint = build_teacher_daily_presence_lab_constraint(
		metadata=_metadata("teacher_daily_presence", priority=8)
	)
	result = constraint.apply(context)
	assert result.status == ConstraintStatus.APPLIED
	assert result.details["early_late_blocks"] >= 1


def test_teacher_daily_presence_limits_total_sessions() -> None:
	courses = (
		("COURSE_A", "Computer Science & Engineering", ((0, "L1"),)),
		("COURSE_B", "Computer Science & Engineering", ((0, "L2"),)),
		("COURSE_C", "Computer Science & Engineering", ((0, "L3"),)),
	)
	context = _build_teacher_consecutive_context(
		course_definitions=courses,
		session_labels=("L1", "L2", "L3"),
	)
	constraint = build_teacher_daily_presence_lab_constraint(
		metadata=_metadata("teacher_daily_presence_daily_cap", priority=8)
	)
	result = constraint.apply(context)
	assert result.status == ConstraintStatus.APPLIED
	assert result.details["daily_cap_days"] >= 1


def test_teacher_daily_presence_blocks_l1_l5_l6_triple() -> None:
	courses = (
		("COURSE_EARLY", "Computer Science & Engineering", ((0, "L1"),)),
		("COURSE_BUFFER", "Computer Science & Engineering", ((0, "L5"),)),
		("COURSE_LATE", "Computer Science & Engineering", ((0, "L6"),)),
	)
	context = _build_teacher_consecutive_context(
		course_definitions=courses,
		session_labels=("L1", "L2", "L3", "L4", "L5", "L6"),
	)
	constraint = build_teacher_daily_presence_lab_constraint(
		metadata=_metadata("teacher_daily_presence_triple", priority=8)
	)
	result = constraint.apply(context)
	assert result.status == ConstraintStatus.APPLIED
	assert result.details["triple_window_blocks"] >= 1
