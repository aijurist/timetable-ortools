"""Tests for ordinary and POP-exempt theory daily limits."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pandas as pd
from ortools.sat.python import cp_model

from src.constraints.base import ConstraintMetadata
from src.constraints.context import ConstraintContext
from src.constraints.theory.course_daily_limit import (
	build_theory_course_daily_limit_constraint,
)
from src.data.schemas import ExtendedDataContainer
from src.models.schema import (
	LabVariableBlock,
	TheoryCourseRequirement,
	TheoryVariableBlock,
	VariableCreationResult,
)


def _requirement(
	course_id: str,
	teacher_id: str,
	course_code: str,
	*,
	bundle_id: str | None = None,
) -> TheoryCourseRequirement:
	return TheoryCourseRequirement(
		course_instance_id=course_id,
		course_code=course_code,
		group_id=f"G_{course_id}",
		teacher_id=teacher_id,
		department="Artificial Intelligence & Machine Learning",
		semester=3,
		required_slots=6,
		lecture_hours=3,
		tutorial_hours=0,
		student_count=64,
		preferred_room_type=None,
		required_room_type=None,
		bundle_id=bundle_id,
	)


def _build_context(*, include_pop_partner: bool = False) -> ConstraintContext:
	model = cp_model.CpModel()
	slots = {index: model.NewBoolVar(f"slot_{index}") for index in range(3)}
	model.Add(sum(slots.values()) == 3)

	if include_pop_partner:
		requirements = {
			"AI_POP": _requirement("AI_POP", "74", "AI23231", bundle_id="BUNDLE_1"),
			"AI_PARTNER": _requirement("AI_PARTNER", "70", "MA23311", bundle_id="BUNDLE_1"),
		}
		assignments = {
			"74": {"AI_POP": {0: slots}},
			"70": {"AI_PARTNER": {0: slots}},
		}
		preferences = pd.DataFrame(
			[
				{
					"teacher_id": "74",
					"preferred_day_1": "Fri",
					"preferred_day_2": "Sat",
				}
			]
		)
	else:
		requirements = {"ORDINARY": _requirement("ORDINARY", "70", "MA23311")}
		assignments = {"70": {"ORDINARY": {0: slots}}}
		preferences = pd.DataFrame()

	theory = TheoryVariableBlock(
		assignments=assignments,
		course_requirements=requirements,
		theory_slot_labels=("S1", "S2", "S3"),
	)
	lab = LabVariableBlock(
		assignments={},
		requirements={},
		teacher_courses={},
		day_patterns={},
		lab_session_names=tuple(),
		room_ids=tuple(),
		instance_group_lookup={},
	)
	return ConstraintContext(
		model=model,
		config=SimpleNamespace(),
		data=ExtendedDataContainer(
			raw=SimpleNamespace(teacher_preferences_df=preferences),
			preprocessing=SimpleNamespace(),
		),
		variables=VariableCreationResult(lab=lab, theory=theory, metadata={}),
		logger=logging.getLogger("tests.constraints.theory_course_daily_limit"),
	)


def _apply(context: ConstraintContext):
	metadata = ConstraintMetadata(
		id="theory.course_daily_limit",
		name="Theory Course Daily Limit",
		category="theory",
		priority=9,
	)
	return build_theory_course_daily_limit_constraint(
		metadata,
		params={"max_daily_slots": 2, "exempt_pop_bundles": True},
	).apply(context)


def test_ordinary_course_remains_capped_at_two_slots_per_day() -> None:
	context = _build_context()
	_apply(context)

	assert cp_model.CpSolver().Solve(context.model) == cp_model.INFEASIBLE


def test_pop_course_and_its_kutty_partner_are_both_exempt() -> None:
	context = _build_context(include_pop_partner=True)
	result = _apply(context)

	status = cp_model.CpSolver().Solve(context.model)

	assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
	assert result.details["constraints"] == 0
	assert result.details["pop_exempt_courses"] == 2
	assert result.details["pop_exempt_bundles"] == ("BUNDLE_1",)
