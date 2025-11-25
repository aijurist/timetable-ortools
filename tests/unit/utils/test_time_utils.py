"""Tests for time utility helpers."""

from src.utils.time_utils import DayNormalizer


def test_day_normalizer_handles_thur_variants() -> None:
	assert DayNormalizer.normalize_day_name("Thur") == "thursday"
	assert DayNormalizer.normalize_day_name("THURS") == "thursday"
	assert DayNormalizer.normalize_day_name("Thu.") == "thursday"
	assert DayNormalizer.normalize_day_name("thur.") == "thursday"
	assert DayNormalizer.normalize_day_name("  Thur, ") == "thursday"
