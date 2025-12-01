from datetime import datetime, timezone
from pathlib import Path

from ortools.sat import cp_model_pb2

from src.runtime.solver_schema import SolverResult
from src.telemetry.solver_metrics import SolverMetricsTelemetryBuilder


def _sample_solver_result() -> SolverResult:
    response = cp_model_pb2.CpSolverResponse()
    return SolverResult(
        status="FEASIBLE",
        status_code=cp_model_pb2.CpSolverStatus.FEASIBLE,
        objective_value=123.0,
        best_bound=100.0,
        gap=0.2,
        wall_time=12.5,
        solution_count=3,
        best_bound_history=tuple(),
        solver_statistics={
            "conflicts": 42,
            "branches": 9000,
            "wall_time": 12.5,
            "user_time": 11.2,
            "deterministic_time": 55.0,
        },
        response_stats="conflicts:42",
        response=response,
        log_path=None,
        summary_path=None,
        diagnostics_path=None,
    )


def test_build_payload_contains_solver_and_model_sections(tmp_path: Path) -> None:
    solver_result = _sample_solver_result()
    builder = SolverMetricsTelemetryBuilder(
        solver_result=solver_result,
        model_metadata={"lab_course_count": 10},
        run_label="2025-01-01_00-00-00",
        timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )

    payload = builder.build()

    assert payload["run_label"] == "2025-01-01_00-00-00"
    assert payload["solver"]["num_conflicts"] == 42
    assert payload["solver"]["deterministic_time"] == 55.0
    assert payload["model"]["lab_course_count"] == 10


def test_append_writes_json_line(tmp_path: Path) -> None:
    solver_result = _sample_solver_result()
    builder = SolverMetricsTelemetryBuilder(solver_result=solver_result, model_metadata={})

    destination = tmp_path / "solver_metrics.jsonl"
    builder.append(destination)

    content = destination.read_text(encoding="utf-8").strip()
    assert content.endswith("}")
    assert "num_conflicts" in content
