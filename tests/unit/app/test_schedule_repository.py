from __future__ import annotations

import json
import os
from pathlib import Path

from src.app.data import ScheduleRepository


def _write_schedule(root: Path, *, modified_at: float) -> None:
    root.mkdir(parents=True, exist_ok=True)
    schedule_path = root / "schedule.json"
    schedule_path.write_text(
        json.dumps({"lab_entries": [], "theory_entries": []}),
        encoding="utf-8",
    )
    os.utime(schedule_path, (modified_at, modified_at))


def test_certified_composed_run_beats_newer_department_fragment(tmp_path: Path) -> None:
    composed = tmp_path / "output" / "timetables" / "core_departments_composed"
    fragment = tmp_path / "output" / "timetables" / "dept_by_dept" / "aeronautical"
    _write_schedule(composed, modified_at=100)
    _write_schedule(fragment, modified_at=200)
    (composed / "full_run_report.json").write_text(
        json.dumps({"status": "PASS", "department_count": 12}),
        encoding="utf-8",
    )

    snapshot = ScheduleRepository(tmp_path).get_latest_snapshot()

    assert snapshot.root == composed


def test_newest_snapshot_wins_without_certified_composed_run(tmp_path: Path) -> None:
    older = tmp_path / "output" / "older"
    newer = tmp_path / "output" / "newer"
    _write_schedule(older, modified_at=100)
    _write_schedule(newer, modified_at=200)

    snapshot = ScheduleRepository(tmp_path).get_latest_snapshot()

    assert snapshot.root == newer
