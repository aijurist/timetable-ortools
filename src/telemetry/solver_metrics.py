"""Telemetry builder for solver-level performance metrics."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

from ..runtime.solver_schema import SolverResult


@dataclass
class SolverMetricsTelemetryBuilder:
    """Project solver stats and model metadata into time-series friendly payloads."""

    solver_result: SolverResult
    model_metadata: Mapping[str, Any]
    run_label: Optional[str] = None
    timestamp: Optional[datetime] = None

    def build(self) -> Mapping[str, Any]:
        stats = dict(self.solver_result.solver_statistics)
        generated_at = (self.timestamp or datetime.now(timezone.utc)).isoformat()
        solver_payload = {
            "status": self.solver_result.status,
            "status_code": self.solver_result.status_code,
            "wall_time": self.solver_result.wall_time,
            "solution_count": self.solver_result.solution_count,
            "num_conflicts": stats.get("conflicts"),
            "num_branches": stats.get("branches"),
            "user_time": stats.get("user_time") or stats.get("user_time_seconds"),
            "deterministic_time": stats.get("deterministic_time"),
            "best_bound": self.solver_result.best_bound,
            "objective_value": self.solver_result.objective_value,
            "gap": self.solver_result.gap,
        }
        payload = {
            "generated_at": generated_at,
            "run_label": self.run_label,
            "solver": solver_payload,
            "model": dict(self.model_metadata or {}),
        }
        return payload

    def write(self, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(self.build(), indent=2), encoding="utf-8")
        return destination

    def append(self, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(self.build()) + "\n")
        return destination


__all__ = ["SolverMetricsTelemetryBuilder"]
