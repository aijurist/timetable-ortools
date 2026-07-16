"""Regression tests for pair-aware teacher workload accounting."""

from __future__ import annotations

import logging
from types import SimpleNamespace

from ortools.sat.python import cp_model

from src.constraints.base import ConstraintMetadata
from src.constraints.context import ConstraintContext
from src.constraints.cross_system.teacher_daily_workload import (
	build_teacher_daily_workload_constraint,
)


def _metadata() -> ConstraintMetadata:
	return ConstraintMetadata(
		id="cross_system.teacher_daily_workload",
		name="Teacher Daily Workload",
		category="cross_system",
		priority=9,
	)


def _build_context(*, shared_slots: int, ordinary_slots: int) -> tuple[
	ConstraintContext,
	cp_model.IntVar,
	list[cp_model.IntVar],
]:
	model = cp_model.CpModel()
	pair_literal = model.NewBoolVar("bundle_pair_short_long")
	short_vars = [model.NewBoolVar(f"short_s{slot}") for slot in range(shared_slots)]
	long_vars = [model.NewBoolVar(f"long_s{slot}") for slot in range(shared_slots)]
	ordinary_vars = [
		model.NewBoolVar(f"ordinary_s{shared_slots + slot}")
		for slot in range(ordinary_slots)
	]

	assignments = {
		"T1": {
			"SHORT": {0: {slot: var for slot, var in enumerate(short_vars)}},
			"ORDINARY": {
				0: {
					shared_slots + slot: var
					for slot, var in enumerate(ordinary_vars)
				}
			},
		},
		"T2": {
			"LONG": {0: {slot: var for slot, var in enumerate(long_vars)}},
		},
	}
	requirements = {
		"SHORT": SimpleNamespace(course_code="CS23331"),
		"LONG": SimpleNamespace(course_code="CS23332"),
		"ORDINARY": SimpleNamespace(course_code="MA23311"),
	}
	patterns = {course_id: ("monday",) for course_id in requirements}

	variables = SimpleNamespace(
		theory=SimpleNamespace(
			assignments=assignments,
			course_day_patterns=patterns,
			course_requirements=requirements,
		),
		lab=SimpleNamespace(
			assignments={},
			day_patterns={},
			requirements={},
		),
	)
	data = SimpleNamespace(
		raw=SimpleNamespace(
			time=SimpleNamespace(working_days=("monday",), lab_session_to_theory={}),
			blocking_mask=None,
		),
		preprocessing=None,
	)
	config = SimpleNamespace(model=SimpleNamespace(combined_lab_courses={}))
	context = ConstraintContext(
		model=model,
		config=config,
		data=data,
		variables=variables,
		logger=logging.getLogger("tests.constraints.teacher_daily_workload"),
		extra={
			"bundles": {
				("Computer Science & Engineering", 3, 1): {
					"pairs": [(pair_literal, "SHORT", "LONG")],
				}
			}
		},
	)
	return context, pair_literal, [*short_vars, *long_vars, *ordinary_vars]


def _solve_forced(context: ConstraintContext, variables: list[cp_model.IntVar]) -> int:
	for variable in variables:
		context.model.Add(variable == 1)
	return cp_model.CpSolver().Solve(context.model)


def test_seven_kutty_halves_count_as_three_and_a_half_hours() -> None:
	context, pair_literal, variables = _build_context(shared_slots=7, ordinary_slots=0)
	constraint = build_teacher_daily_workload_constraint(
		metadata=_metadata(), params={"max_daily_hours": 4, "mode": "hard"}
	)
	constraint.apply(context)
	context.model.Add(pair_literal == 1)

	assert _solve_forced(context, variables) in (cp_model.FEASIBLE, cp_model.OPTIMAL)


def test_kutty_halves_plus_full_theory_use_exact_half_hour_load() -> None:
	# 7 Kutty halves (3.5h) + one ordinary theory cell (1h) exceeds a 4h cap.
	context, pair_literal, variables = _build_context(shared_slots=7, ordinary_slots=1)
	constraint = build_teacher_daily_workload_constraint(
		metadata=_metadata(), params={"max_daily_hours": 4, "mode": "hard"}
	)
	constraint.apply(context)
	context.model.Add(pair_literal == 1)

	assert _solve_forced(context, variables) == cp_model.INFEASIBLE


def test_unpaired_theory_cell_still_counts_as_one_hour() -> None:
	context, pair_literal, variables = _build_context(shared_slots=0, ordinary_slots=5)
	constraint = build_teacher_daily_workload_constraint(
		metadata=_metadata(), params={"max_daily_hours": 4, "mode": "hard"}
	)
	constraint.apply(context)
	context.model.Add(pair_literal == 0)

	assert _solve_forced(context, variables) == cp_model.INFEASIBLE
