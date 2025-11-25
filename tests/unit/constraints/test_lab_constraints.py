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


@pytest.fixture()
def lab_constraint_context() -> ConstraintContext:
	return _build_constraint_context()


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
