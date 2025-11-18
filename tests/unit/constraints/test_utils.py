"""Unit tests for constraint helper utilities."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
from ortools.sat.python import cp_model

from src.constraints.context import ConstraintContext
from src.constraints.utils import (
	ensure_extra_bucket,
	get_lab_session_detail,
	get_room_attributes,
	iter_group_timeslot_variables,
	iter_lab_session_variables,
	resolve_day_pattern,
)
from src.data.schemas import ExtendedDataContainer, LabSessionDetail
from src.models.variables import (
	GroupTimeslotRequirement,
	LabCourseRequirement,
	LabVariableBlock,
	TheoryVariableBlock,
	VariableCreationResult,
)


@pytest.fixture()
def sample_context() -> ConstraintContext:
	model = cp_model.CpModel()
	lab_var = model.NewBoolVar("lab_t1_c1_d0_L1_R1")
	lab_requirement = LabCourseRequirement(
		course_instance_id="C1",
		course_code="CS101",
		teacher_id="T1",
		group_id="G1",
		department="Computer Science",
		semester=5,
		practical_hours=2,
		required_sessions=1,
		student_count=32,
		preferred_room_type=None,
		required_room_type=None,
		tags=("lab",),
	)
	lab_block = LabVariableBlock(
		assignments={
			"T1": {
				"C1": {
					0: {
						"L1": {
							"R1": lab_var,
						}
					}
				}
			}
		},
		requirements={"C1": lab_requirement},
		teacher_courses={"T1": ("C1",)},
		day_patterns={"C1": ("monday",)},
		lab_session_names=("L1",),
		room_ids=("R1",),
		instance_group_lookup={"C1": "G1"},
	)
	theory_var = model.NewBoolVar("grp_G1_d0_t0")
	group_requirement = GroupTimeslotRequirement(
		group_id="G1",
		department="Computer Science",
		semester=5,
		required_theory_slots=2,
		day_pattern=("monday",),
		lunch_slot_window=(3, 4),
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
	variables = VariableCreationResult(lab=lab_block, theory=theory_block, metadata={})
	time_ns = SimpleNamespace(
		lab_sessions={
			"L1": LabSessionDetail(name="L1", slots=(0, 1), time_range="8:00-9:40"),
		},
		working_days=("monday", "tuesday"),
	)
	departments_ns = SimpleNamespace(day_patterns={"__default__": ("monday", "tuesday")})
	raw = SimpleNamespace(time=time_ns, departments=departments_ns, room_registry={"R1": {"capacity": 60}})
	data = ExtendedDataContainer(raw=raw, preprocessing=SimpleNamespace())
	config = SimpleNamespace()
	logger = logging.getLogger("tests.constraints.utils")
	return ConstraintContext(
		model=model,
		config=config,
		data=data,
		variables=variables,
		logger=logger,
	)


def test_iter_lab_session_variables_filters(sample_context: ConstraintContext) -> None:
	assignments = list(iter_lab_session_variables(sample_context))
	assert assignments
	assert assignments[0][:4] == ("T1", "C1", 0, "L1")
	assert list(iter_lab_session_variables(sample_context, course_instance_id="nope")) == []


def test_iter_group_timeslot_variables(sample_context: ConstraintContext) -> None:
	slots = list(iter_group_timeslot_variables(sample_context, group_id="G1"))
	assert slots == [("G1", 0, 0, slots[0][3])]


def test_get_room_attributes(sample_context: ConstraintContext) -> None:
	attrs = get_room_attributes(sample_context, "R1")
	assert attrs and attrs["capacity"] == 60
	assert get_room_attributes(sample_context, "R2") is None


def test_get_lab_session_detail(sample_context: ConstraintContext) -> None:
	detail = get_lab_session_detail(sample_context, "L1")
	assert detail.time_range == "8:00-9:40"


def test_resolve_day_pattern(sample_context: ConstraintContext) -> None:
	pattern = resolve_day_pattern(sample_context, "Unknown Dept")
	assert pattern == ("monday", "tuesday")


def test_ensure_extra_bucket(sample_context: ConstraintContext) -> None:
	first = ensure_extra_bucket(sample_context, "cache")
	second = ensure_extra_bucket(sample_context, "cache")
	assert first is second