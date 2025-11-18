"""CP-SAT solver orchestration utilities."""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

import yaml
from ortools.sat import cp_model_pb2, sat_parameters_pb2
from ortools.sat.python import cp_model

from ..config.schemas import SchedulerConfig
from ..models.model_builder import ConstraintModel
from .solver_schema import BoundEvent, SolverResult, _BoundTracker

LOGGER = logging.getLogger(__name__)


class SolverRunner:
	"""High-level CP-SAT solver wrapper that manages parameters and logging."""

	DEFAULT_PARAM_PATH = Path("config/solver_params.yaml")
	_STATUS_LABELS = {
		cp_model.OPTIMAL: "OPTIMAL",
		cp_model.FEASIBLE: "FEASIBLE",
		cp_model.INFEASIBLE: "INFEASIBLE",
		cp_model.UNKNOWN: "UNKNOWN",
		cp_model.MODEL_INVALID: "MODEL_INVALID",
	}

	def __init__(
		self,
		config: SchedulerConfig,
		*,
		solver_params_path: Optional[Path | str] = None,
		logger_: Optional[logging.Logger] = None,
	) -> None:
		self._config = config
		self._logger = logger_ or LOGGER.getChild("SolverRunner")
		self._solver_params_path = Path(solver_params_path).resolve() if solver_params_path else self.DEFAULT_PARAM_PATH
		self._params_payload = self._load_solver_params(self._solver_params_path)

	def solve(
		self,
		constraint_model: ConstraintModel,
		*,
		log_dir: Optional[Path | str] = None,
	) -> SolverResult:
		model = constraint_model.model
		solver = cp_model.CpSolver()
		self._apply_yaml_parameters(solver.parameters)
		self._apply_runtime_parameters(solver.parameters)

		has_objective = self._model_has_objective(model)
		callback = _BoundTracker(has_objective=has_objective)
		self._logger.info(
			"Starting CP-SAT solve (time_limit=%s, workers=%s)",
			solver.parameters.max_time_in_seconds or "default",
			solver.parameters.num_search_workers or 1,
		)
		start_time = time.perf_counter()
		status_code = solver.Solve(model, callback)
		elapsed = time.perf_counter() - start_time

		best_bound = self._normalise_bound(solver.BestObjectiveBound()) if has_objective else None
		callback.finalize(best_bound)
		status_label = self._STATUS_LABELS.get(status_code, f"STATUS_{status_code}")
		objective_value = None
		if has_objective and status_code in (cp_model.OPTIMAL, cp_model.FEASIBLE):
			objective_value = solver.ObjectiveValue()
		gap = self._compute_relative_gap(objective_value, best_bound)

		response = solver.ResponseProto()
		solver_stats = {
			"wall_time": solver.WallTime(),
			"user_time": solver.UserTime(),
			"branches": solver.NumBranches(),
			"conflicts": solver.NumConflicts(),
		}
		deterministic_time = getattr(response, "deterministic_time", None)
		if deterministic_time not in (None, 0):
			solver_stats["deterministic_time"] = deterministic_time

		log_directory = self._resolve_log_dir(log_dir)
		timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
		log_path = self._write_solver_log(log_directory, solver.ResponseStats(), timestamp)
		diagnostics_path = None
		if status_code == cp_model.INFEASIBLE:
			diagnostics_path = self._export_infeasible_snapshot(model, log_directory, timestamp)

		result = SolverResult(
			status=status_label,
			status_code=status_code,
			objective_value=objective_value,
			best_bound=best_bound,
			gap=gap,
			wall_time=elapsed,
			solution_count=callback.solution_count,
			best_bound_history=callback.events,
			solver_statistics=solver_stats,
			response_stats=solver.ResponseStats(),
			response=response,
			log_path=log_path,
			diagnostics_path=diagnostics_path,
		)

		summary_path = log_directory / f"solver_{timestamp}.json"
		result.write_summary(summary_path)
		return result

	def _apply_runtime_parameters(self, parameters: sat_parameters_pb2.SatParameters) -> None:
		runtime = self._config.runtime
		if runtime.time_limit_sec:
			parameters.max_time_in_seconds = runtime.time_limit_sec
		parameters.num_search_workers = max(1, runtime.thread_count)
		if runtime.solution_limit:
			self._apply_solution_limit(parameters, runtime.solution_limit, source="runtime")
		parameters.use_lns = bool(runtime.enable_lns)
		if runtime.enable_trace:
			parameters.log_search_progress = True

	def _apply_yaml_parameters(self, parameters: sat_parameters_pb2.SatParameters) -> None:
		payload = self._params_payload
		solver_section = payload.get("solver", {})
		for key, value in solver_section.items():
			mapped_key = {
				"time_limit_sec": "max_time_in_seconds",
				"thread_count": "num_search_workers",
				"solution_limit": "solution_limit",
				"enable_lns": "use_lns",
				"enable_trace": "log_search_progress",
			}.get(key, key)
			if mapped_key == "solution_limit":
				self._apply_solution_limit(parameters, value, source="solver")
				continue
			if mapped_key in {"max_time_in_seconds", "num_search_workers", "use_lns", "log_search_progress"}:
				# These are controlled via runtime config and will be applied later
				continue
			self._assign_parameter(parameters, mapped_key, value)

		logging_section = payload.get("logging", {})
		if "log_search_progress" in logging_section and not self._config.runtime.enable_trace:
			self._assign_parameter(parameters, "log_search_progress", logging_section["log_search_progress"])
		if "log_to_stdout" in logging_section:
			self._assign_parameter(parameters, "log_to_stdout", logging_section["log_to_stdout"])

		stopping_section = payload.get("stopping_conditions", {})
		if stopping_section.get("best_objective_gap") is not None:
			self._assign_parameter(parameters, "absolute_gap_limit", stopping_section["best_objective_gap"])
		if stopping_section.get("max_failures") is not None:
			self._assign_parameter(parameters, "max_number_of_conflicts", stopping_section["max_failures"])
		max_solutions = stopping_section.get("max_solutions")
		if max_solutions is not None:
			self._apply_solution_limit(parameters, max_solutions, source="stopping_conditions")

	def _assign_parameter(self, parameters: sat_parameters_pb2.SatParameters, name: str, value: object) -> None:
		if value is None:
			return
		try:
			setattr(parameters, name, value)
			return
		except (AttributeError, TypeError, ValueError):
			pass

		if name == "search_branching" and isinstance(value, str):
			enum_value = self._coerce_search_branching(value)
			if enum_value is not None:
				setattr(parameters, name, enum_value)
				return

		self._logger.warning("Unsupported or invalid solver parameter '%s'", name)

	@staticmethod
	def _coerce_search_branching(value: str) -> Optional[int]:
		token = value.upper().strip()
		candidates = [token]
		if not token.endswith("_SEARCH"):
			candidates.append(f"{token}_SEARCH")
		for candidate in candidates:
			try:
				return sat_parameters_pb2.SatParameters.SearchBranching.Value(candidate)
			except ValueError:
				continue
		return None

	def _apply_solution_limit(self, parameters: sat_parameters_pb2.SatParameters, value: object, *, source: str) -> None:
		if value in (None, 0):
			return
		try:
			limit = int(value)
		except (TypeError, ValueError):
			self._logger.warning("%s provided non-integer solution limit %r; ignoring", source, value)
			return
		if limit <= 0:
			self._logger.warning("%s provided non-positive solution limit %s; ignoring", source, value)
			return
		if limit == 1:
			self._assign_parameter(parameters, "stop_after_first_solution", True)
		else:
			self._logger.warning(
				"%s requested solution_limit=%s but limiting beyond the first solution is not supported; ignoring",
				source,
				limit,
			)

	def _load_solver_params(self, path: Path) -> Mapping[str, Dict[str, object]]:
		if not path.exists():
			self._logger.debug("Solver parameter file %s not found; using defaults", path)
			return {}
		try:
			with path.open("r", encoding="utf-8") as handle:
				payload = yaml.safe_load(handle) or {}
			self._logger.info("Loaded solver parameter overrides from %s", path)
			return payload
		except yaml.YAMLError as exc:  # pragma: no cover - defensive branch
			self._logger.warning("Failed to parse solver parameter file %s (%s)", path, exc)
			return {}

	def _resolve_log_dir(self, log_dir: Optional[Path | str]) -> Path:
		if log_dir is not None:
			return Path(log_dir).resolve()
		return (self._config.paths.output_root / "solver_logs").resolve()

	@staticmethod
	def _normalise_bound(value: float) -> Optional[float]:
		if math.isinf(value) or math.isnan(value):
			return None
		return value

	@staticmethod
	def _compute_relative_gap(objective_value: Optional[float], best_bound: Optional[float]) -> Optional[float]:
		if objective_value is None or best_bound is None:
			return None
		if not math.isfinite(objective_value) or not math.isfinite(best_bound):
			return None
		denominator = max(1.0, abs(objective_value))
		if denominator == 0:
			denominator = 1.0
		return abs(objective_value - best_bound) / denominator

	@staticmethod
	def _model_has_objective(model: cp_model.CpModel) -> bool:
		proto = model.Proto()
		return proto.HasField("objective") and bool(proto.objective.vars)

	def _write_solver_log(self, directory: Path, stats: str, timestamp: str) -> Path:
		directory.mkdir(parents=True, exist_ok=True)
		path = directory / f"solver_{timestamp}.stats.txt"
		path.write_text(stats, encoding="utf-8")
		return path

	def _export_infeasible_snapshot(
		self,
		model: cp_model.CpModel,
		directory: Path,
		timestamp: str,
	) -> Path:
		proto = cp_model_pb2.CpModelProto()
		proto.CopyFrom(model.Proto())
		path = directory / f"infeasible_{timestamp}.pb"
		with path.open("wb") as handle:
			handle.write(proto.SerializeToString())
		return path


__all__ = ["SolverRunner", "SolverResult", "BoundEvent"]

if __name__ == "__main__":
	from ortools.sat.python import cp_model
	from ..config.manager import ConfigManager
	from ..data.data_loader import DataLoader
	from ..data.preprocessing import DataPreprocessor
	from ..models.model_builder import ModelBuilder
	
	from pathlib import Path

	base_dir = Path.cwd()
	config_manager = ConfigManager(base_dir=base_dir)
	config = config_manager.load()
	data_loader = DataLoader(config, base_dir=base_dir)
	res = data_loader.load()

	pre = DataPreprocessor(config)
	output = pre.build_extended_container(data=res)
	
	
	builder = ModelBuilder(config=config)
	constraint_model = builder.build(data=output)
	runner = SolverRunner(config=config)
	final_res = runner.solve(constraint_model)
	print(final_res.to_dict())