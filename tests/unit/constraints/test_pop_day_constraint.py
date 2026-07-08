"""Unit tests for POP day/time availability constraints."""

from __future__ import annotations

import logging
from types import SimpleNamespace

from ortools.sat.python import cp_model

from src.constraints.base import ConstraintMetadata
from src.constraints.context import ConstraintContext
from src.constraints.cross_system.pop_day import build_pop_day_constraint
from src.constraints.schema import ConstraintStatus
from src.data.schemas import ExtendedDataContainer
from src.models.schema import (
	LabCourseRequirement,
	LabVariableBlock,
	TheoryCourseRequirement,
	TheoryVariableBlock,
	VariableCreationResult,
)


def _metadata() -> ConstraintMetadata:
	return ConstraintMetadata(
		id="cross_system.pop_day",
		name="pop_day",
		category="cross_system",
		priority=9,
		description="unit-test metadata",
		weight=1.0,
	)


def _build_context(*, include_theory: bool = True) -> tuple[ConstraintContext, cp_model.IntVar, cp_model.IntVar]:
	model = cp_model.CpModel()
	tuesday_lab = model.NewBoolVar("tuesday_lab")
	saturday_lab = model.NewBoolVar("saturday_lab")
	day_pattern = ("tuesday", "saturday")
	lab_block = LabVariableBlock(
		assignments={
			"T1": {
				"C1": {
					0: {"L1": {"R1": tuesday_lab}},
					1: {"L1": {"R1": saturday_lab}},
				}
			}
		},
		requirements={
			"C1": LabCourseRequirement(
				course_instance_id="C1",
				course_code="POP101",
				teacher_id="T1",
				group_id="G1",
				department="Biomedical Engineering",
				semester=5,
				practical_hours=2,
				required_sessions=1,
				student_count=30,
				preferred_room_type=None,
				required_room_type=None,
				tags=tuple(),
			)
		},
		teacher_courses={"T1": ("C1",)},
		day_patterns={"C1": day_pattern},
		lab_session_names=("L1",),
		room_ids=("R1",),
		instance_group_lookup={"C1": "G1"},
	)

	if include_theory:
		saturday_theory = model.NewBoolVar("saturday_theory")
		theory_block = TheoryVariableBlock(
			assignments={"T1": {"C1": {1: {0: saturday_theory}}}},
			course_requirements={
				"C1": TheoryCourseRequirement(
					course_instance_id="C1",
					course_code="POP101",
					group_id="G1",
					teacher_id="T1",
					department="Biomedical Engineering",
					semester=5,
					required_slots=1,
					lecture_hours=1,
					tutorial_hours=0,
					student_count=30,
					preferred_room_type=None,
					required_room_type=None,
					tags=tuple(),
				)
			},
			teacher_courses={"T1": ("C1",)},
			course_day_patterns={"C1": day_pattern},
			theory_slot_labels=("08:00-09:00",),
		)
	else:
		saturday_theory = model.NewBoolVar("unused_theory")
		theory_block = TheoryVariableBlock(theory_slot_labels=("08:00-09:00",))

	raw = SimpleNamespace(
		time=SimpleNamespace(
			working_days=day_pattern,
			lab_sessions={"L1": SimpleNamespace(time_range="08:00-10:00")},
		)
	)
	data = ExtendedDataContainer(raw=raw, preprocessing=SimpleNamespace())
	variables = VariableCreationResult(lab=lab_block, theory=theory_block, metadata={})
	context = ConstraintContext(
		model=model,
		config=SimpleNamespace(),
		data=data,
		variables=variables,
		logger=logging.getLogger("tests.constraints.pop_day"),
	)
	return context, saturday_lab, saturday_theory


def test_hard_lab_limit_blocks_labs_outside_pop_window(tmp_path) -> None:
	pop_csv = tmp_path / "pop.csv"
	pop_csv.write_text(
		"Teacher ID,Preferred Day 1,day_time_windows,hard_lab_limit\n"
		'T1,Tue,"Tue 08:00-17:00",true\n',
		encoding="utf-8",
	)
	context, saturday_lab, saturday_theory = _build_context()
	constraint = build_pop_day_constraint(
		metadata=_metadata(),
		params={"pop_csv_path": str(pop_csv)},
	)

	result = constraint.apply(context)

	assert result.status == ConstraintStatus.APPLIED
	assert result.details["hard_theory_constraints"] == 1
	assert result.details["hard_lab_constraints"] == 1
	assert result.details["lab_penalty_terms"] == 0

	context.model.Add(saturday_lab == 1)
	context.model.Add(saturday_theory == 1)
	solver = cp_model.CpSolver()
	assert solver.Solve(context.model) == cp_model.INFEASIBLE


def test_lab_specific_windows_do_not_open_theory_days(tmp_path) -> None:
	pop_csv = tmp_path / "pop.csv"
	pop_csv.write_text(
		"Teacher ID,Preferred Day 1,day_time_windows,lab_day_time_windows,hard_lab_limit\n"
		'T1,Tue,"Tue 08:00-17:00","Sat 08:00-10:00",true\n',
		encoding="utf-8",
	)
	context, saturday_lab, saturday_theory = _build_context()
	constraint = build_pop_day_constraint(
		metadata=_metadata(),
		params={"pop_csv_path": str(pop_csv)},
	)

	result = constraint.apply(context)

	assert result.status == ConstraintStatus.APPLIED
	assert result.details["hard_theory_constraints"] == 1
	assert result.details["hard_lab_constraints"] == 1
	context.model.Add(saturday_lab == 1)
	solver = cp_model.CpSolver()
	assert solver.Solve(context.model) in {cp_model.OPTIMAL, cp_model.FEASIBLE}
	context.model.Add(saturday_theory == 1)
	assert solver.Solve(context.model) == cp_model.INFEASIBLE


def test_pop_lab_rows_remain_soft_without_hard_lab_limit(tmp_path) -> None:
	pop_csv = tmp_path / "pop.csv"
	pop_csv.write_text(
		"Teacher ID,Preferred Day 1,day_time_windows,hard_lab_limit\n"
		'T1,Tue,"Tue 08:00-17:00",\n',
		encoding="utf-8",
	)
	context, saturday_lab, _saturday_theory = _build_context(include_theory=False)
	constraint = build_pop_day_constraint(
		metadata=_metadata(),
		params={"pop_csv_path": str(pop_csv)},
	)

	result = constraint.apply(context)

	assert result.status == ConstraintStatus.APPLIED
	assert result.details["hard_lab_constraints"] == 0
	assert result.details["lab_penalty_terms"] == 1
	context.model.Add(saturday_lab == 1)
	solver = cp_model.CpSolver()
	assert solver.Solve(context.model) in {cp_model.OPTIMAL, cp_model.FEASIBLE}
