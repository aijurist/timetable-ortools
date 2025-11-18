"""Tests for the CP-SAT solver orchestration utilities."""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Tuple

import pytest
from ortools.sat import sat_parameters_pb2
from ortools.sat.python import cp_model

from src.config.defaults import default_scheduler_config
from src.models.model_builder import ConstraintModel
from src.models.variables import (
	LabVariableBlock,
	TheoryVariableBlock,
	VariableCreationResult,
)
from src.runtime.solver import SolverRunner


def _empty_variables() -> VariableCreationResult:
	lab_block = LabVariableBlock(
		assignments={},
		requirements={},
		teacher_courses={},
		day_patterns={},
		lab_session_names=tuple(),
		room_ids=tuple(),
		instance_group_lookup={},
	)
	theory_block = TheoryVariableBlock(
		group_timeslots={},
		requirements={},
		day_patterns={},
		theory_slot_labels=tuple(),
	)
	return VariableCreationResult(lab=lab_block, theory=theory_block, metadata={})


def _build_constraint_model(model: cp_model.CpModel) -> ConstraintModel:
	return ConstraintModel(
		model=model,
		variables=_empty_variables(),
		constraint_results=tuple(),
		metadata={},
	)


def _config_with_output(tmp_path: Path):
	config = default_scheduler_config()
	paths = replace(config.paths, output_root=tmp_path)
	return replace(config, paths=paths)


def test_solver_runner_solves_simple_model(tmp_path: Path) -> None:
	config = _config_with_output(tmp_path)
	runner = SolverRunner(config, logger_=logging.getLogger("tests.solver.simple"))

	model = cp_model.CpModel()
	x = model.NewIntVar(0, 10, "x")
	model.Maximize(x)

	result = runner.solve(_build_constraint_model(model))

	assert result.status == "OPTIMAL"
	assert result.objective_value == pytest.approx(10)
	assert result.log_path and result.log_path.exists()
	assert result.summary_path and result.summary_path.exists()


def test_solver_runner_exports_infeasible_snapshot(tmp_path: Path) -> None:
	config = _config_with_output(tmp_path)
	runner = SolverRunner(config, logger_=logging.getLogger("tests.solver.infeasible"))

	model = cp_model.CpModel()
	x = model.NewBoolVar("x")
	model.Add(x == 0)
	model.Add(x == 1)

	result = runner.solve(_build_constraint_model(model))

	assert result.status == "INFEASIBLE"
	assert result.diagnostics_path and result.diagnostics_path.exists()


def test_solver_runner_applies_yaml_parameters(tmp_path: Path, monkeypatch) -> None:
	params_path = tmp_path / "solver_params.yaml"
	params_path.write_text(
		"""
solver:
  search_branching: portfolio
stopping_conditions:
  max_solutions: 2
""".strip(),
		encoding="utf-8",
	)
	config = _config_with_output(tmp_path / "out")
	runner = SolverRunner(config, solver_params_path=params_path, logger_=logging.getLogger("tests.solver.yaml"))

	captured: dict[str, Tuple[object, ...]] = {}
	original_assign = SolverRunner._assign_parameter

	def spy(self, parameters, name, value):  # type: ignore[override]
		values = list(captured.get(name, ()))
		values.append(value)
		captured[name] = tuple(values)
		return original_assign(self, parameters, name, value)

	monkeypatch.setattr(SolverRunner, "_assign_parameter", spy)

	model = cp_model.CpModel()
	x = model.NewIntVar(0, 5, "x")
	model.Maximize(x)

	runner.solve(_build_constraint_model(model))

	assert "search_branching" in captured
	assert captured["search_branching"][-1] == sat_parameters_pb2.SatParameters.SearchBranching.PORTFOLIO_SEARCH
	assert "solution_limit" in captured
	assert captured["solution_limit"][-1] == 2