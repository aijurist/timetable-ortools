from pathlib import Path

import pytest

from scripts.run_full_second_year import LOCK_FILES, _require_locks


def test_local_production_locks_do_not_require_remote_branch_hashes(tmp_path: Path):
    for relative in LOCK_FILES:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"locally updated {relative}", encoding="utf-8")

    assert _require_locks(tmp_path) == LOCK_FILES


def test_missing_local_production_lock_is_rejected(tmp_path: Path):
    first = tmp_path / LOCK_FILES[0]
    first.parent.mkdir(parents=True, exist_ok=True)
    first.write_text("present", encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="Required production lock is missing"):
        _require_locks(tmp_path)
