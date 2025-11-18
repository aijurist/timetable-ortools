from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Tuple
import json
import math
import time

from ortools.sat import cp_model_pb2
from ortools.sat.python import cp_model


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