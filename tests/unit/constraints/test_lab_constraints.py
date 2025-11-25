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
from src.constraints.lab.core_lab import build_core_lab_mapping_constraint
from src.constraints.lab.requirements import build_lab_session_coverage_constraint
from src.constraints.lab.room_single_assignment import build_lab_room_single_assignment_constraint
from src.constraints.lab.slot_caps import (
	build_computing_group_slot_cap_constraint,
	build_core_lab_group_slot_cap_constraint,
	build_semester_lab_slot_cap_constraint,
)
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
