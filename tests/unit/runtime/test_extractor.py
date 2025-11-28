from __future__ import annotations

import json
from pathlib import Path

from src.runtime.extractor import ScheduleExtractor
from tests.unit.runtime.runtime_test_helpers import (
	build_constraint_model,
	build_extended_container,
	build_solver_result,
)


def test_schedule_extractor_builds_and_exports(tmp_path: Path) -> None:
	data = build_extended_container()
	constraint_model = build_constraint_model()
	extractor = ScheduleExtractor(data, constraint_model)
	solver_result = build_solver_result(constraint_model.model)
	result = extractor.export(solver_result, output_dir=tmp_path, write_json=True, write_csv=True)

	assert len(result.lab_entries) == 1
	assert result.lab_entries[0].is_lunch_window is True
	assert result.lab_entries[0].five_pm_flag is True
	assert len(result.theory_entries) == 1
	assert result.theory_entries[0].five_pm_flag is False
	assert "C1" in result.instance_index

	schedule_json = tmp_path / "schedule.json"
	assert schedule_json.exists()
	payload = json.loads(schedule_json.read_text(encoding="utf-8"))
	assert payload["lab_entries"], "Lab schedule missing from JSON payload"

	csv_dir = tmp_path / "csv"
	lab_csv = csv_dir / "lab_schedule.csv"
	theory_csv = csv_dir / "theory_schedule.csv"
	assert lab_csv.exists()
	assert theory_csv.exists()


def test_theory_block_metadata_is_applied() -> None:
	data = build_extended_container()
	constraint_model = build_constraint_model()
	extractor = ScheduleExtractor(data, constraint_model)
	solver_result = build_solver_result(constraint_model.model)
	result = extractor.extract(solver_result)
	assert result.theory_entries, "Expected at least one theory entry"
	entry = result.theory_entries[0]
	assert entry.block == "A Block"
	assert entry.room_number == "A202"
	assert entry.room_id == "A202"
