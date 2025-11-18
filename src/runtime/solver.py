"""CP-SAT solver orchestration utilities."""

from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

import yaml
from ortools.sat import sat_parameters_pb2
from ortools.sat.python import cp_model, cp_model_pb2

from ..config.schemas import SchedulerConfig
from ..models.model_builder import ConstraintModel

LOGGER = logging.getLogger(__name__)


@dataclass
class BoundEvent:
	timestamp: float
	best_bound: Optional[float]
	objective_value: Optional[float]
	solution_index: int

	def to_dict(self) -> Dict[str, float | None]:
		return {
			"timestamp": self.timestamp,
			"best_bound": self.best_bound,
			"objective_value": self.objective_value,
			"solution_index": self.solution_index,
		}


@dataclass
class SolverResult:
	status: str
	status_code: int
	objective_value: Optional[float]
	best_bound: Optional[float]
	gap: Optional[float]
	wall_time: float
	solution_count: int
	best_bound_history: Tuple[BoundEvent, ...]
	solver_statistics: Mapping[str, float]
	response_stats: str
	response: cp_model_pb2.CpSolverResponse = field(repr=False)
	log_path: Optional[Path] = None
	summary_path: Optional[Path] = None
	diagnostics_path: Optional[Path] = None

	def to_dict(self) -> Dict[str, object]:
		return {
			"status": self.status,
			"status_code": self.status_code,
			"objective_value": self.objective_value,
			"best_bound": self.best_bound,
			"gap": self.gap,
			"wall_time": self.wall_time,
			"solution_count": self.solution_count,
			"solver_statistics": dict(self.solver_statistics),
			"best_bound_history": [event.to_dict() for event in self.best_bound_history],
			"response_stats": self.response_stats,
			"log_path": str(self.log_path) if self.log_path else None,
			"summary_path": str(self.summary_path) if self.summary_path else None,
			"diagnostics_path": str(self.diagnostics_path) if self.diagnostics_path else None,
		}

	def write_summary(self, destination: Path) -> Path:
		destination.parent.mkdir(parents=True, exist_ok=True)
		destination.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
		self.summary_path = destination
		return destination


class _BoundTracker(cp_model.CpSolverSolutionCallback):
	def __init__(self, *, has_objective: bool) -> None:
		super().__init__()
		self._has_objective = has_objective
		self._start = time.perf_counter()
		self._events: List[BoundEvent] = []
		self.solution_count = 0

	def on_solution_callback(self) -> None:  # pragma: no cover - executed inside CP-SAT
		self.solution_count += 1
		timestamp = time.perf_counter() - self._start
		best_bound = self.BestObjectiveBound() if self._has_objective else None
		if best_bound is not None and math.isinf(best_bound):
			best_bound = None
		objective_value = self.ObjectiveValue() if self._has_objective else None
		self._events.append(
			BoundEvent(
				timestamp=timestamp,
				best_bound=best_bound,
				objective_value=objective_value,
				solution_index=self.solution_count,
			)
		)

	def finalize(self, best_bound: Optional[float]) -> None:
		if not self._has_objective:
			return
		if best_bound is None:
			return
		if self._events and self._events[-1].best_bound == best_bound:
			return
		timestamp = time.perf_counter() - self._start
		self._events.append(
			BoundEvent(
				timestamp=timestamp,
				best_bound=best_bound,
				objective_value=None,
				solution_index=self.solution_count,
			)
		)

	@property
	def events(self) -> Tuple[BoundEvent, ...]:
		return tuple(self._events)


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
		status_code = solver.SolveWithSolutionCallback(model, callback)
		elapsed = time.perf_counter() - start_time

		best_bound = self._normalise_bound(solver.BestObjectiveBound()) if has_objective else None
		callback.finalize(best_bound)
		status_label = self._STATUS_LABELS.get(status_code, f"STATUS_{status_code}")
		objective_value = None
		gap = None
		if has_objective and status_code in (cp_model.OPTIMAL, cp_model.FEASIBLE):
			objective_value = solver.ObjectiveValue()
			gap = solver.RelativeGap()
		elif has_objective and best_bound is not None:
			gap = solver.RelativeGap()

		solver_stats = {
			"wall_time": solver.WallTime(),
			"user_time": solver.UserTime(),
			"deterministic_time": solver.DeterministicTime(),
			"branches": solver.NumBranches(),
			"conflicts": solver.NumConflicts(),
		}

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
			response=solver.ResponseProto(),
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
			parameters.solution_limit = runtime.solution_limit
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
			if mapped_key in {"max_time_in_seconds", "num_search_workers", "solution_limit", "use_lns", "log_search_progress"}:
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
		if stopping_section.get("max_solutions") is not None:
			self._assign_parameter(parameters, "solution_limit", stopping_section["max_solutions"])

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
