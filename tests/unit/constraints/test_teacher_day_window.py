import pytest

from src.constraints.cross_system.teacher_day_window import _normalize_forced_windows


def test_explicit_teacher_windows_normalize_ids_and_aliases() -> None:
	assert _normalize_forced_windows({"529.0": "Mon-Fri", 495: "Tue-Sat"}) == {
		"529": "mon_fri",
		"495": "tue_sat",
	}


def test_invalid_explicit_teacher_window_fails_fast() -> None:
	with pytest.raises(ValueError, match="Invalid teacher day window"):
		_normalize_forced_windows({"529": "weekends"})
