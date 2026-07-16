import csv
from pathlib import Path

from src.data.pop_availability import build_pop_availability


def test_rajalakshmy_window_allows_only_tuesday_to_friday_before_three() -> None:
	availability = build_pop_availability(
		[
			{
				"Teacher ID": "529",
				"Preferred Day 1": "Tue",
				"Preferred Day 2": "Wed",
				"Preferred Day 3": "Thu",
				"day_time_windows": (
					"Tue 08:00-15:00, Wed 08:00-15:00, "
					"Thu 08:00-15:00, Fri 08:00-15:00"
				),
			}
		]
	)["529"]

	assert availability.allows_theory("Tuesday", "8:00 - 8:50")
	assert availability.allows_theory("Fri", "2:00 - 2:50")
	assert not availability.allows_theory("Monday", "8:00 - 8:50")
	assert not availability.allows_theory("Saturday", "8:00 - 8:50")
	assert not availability.allows_theory("Friday", "3:10 - 4:00")


def test_indhu_bala_ece_window_is_monday_to_friday_nine_to_three() -> None:
	pop_path = Path(__file__).resolve().parents[3] / "data" / "pop.csv"
	with pop_path.open(newline="", encoding="utf-8") as handle:
		availability = build_pop_availability(csv.DictReader(handle))["351"]

	for day in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday"):
		assert availability.allows_theory(day, "9:00 - 9:50")
		assert availability.allows_theory(day, "2:00 - 2:50")
		assert not availability.allows_theory(day, "8:00 - 8:50")
		assert not availability.allows_theory(day, "3:10 - 4:00")

	assert not availability.allows_theory("Saturday", "9:00 - 9:50")


def test_yugasini_civil_window_is_tuesday_to_friday_eight_to_five() -> None:
	pop_path = Path(__file__).resolve().parents[3] / "data" / "pop.csv"
	with pop_path.open(newline="", encoding="utf-8") as handle:
		availability = build_pop_availability(csv.DictReader(handle))["175"]

	for day in ("Tuesday", "Wednesday", "Thursday", "Friday"):
		assert availability.allows_theory(day, "8:00 - 8:50")
		assert availability.allows_theory(day, "4:10 - 5:00")

	assert not availability.allows_theory("Monday", "8:00 - 8:50")
	assert not availability.allows_theory("Saturday", "8:00 - 8:50")


def test_s_kaviya_is_not_pop_restricted() -> None:
	pop_path = Path(__file__).resolve().parents[3] / "data" / "pop.csv"
	with pop_path.open(newline="", encoding="utf-8") as handle:
		availability = build_pop_availability(csv.DictReader(handle))

	assert "1037" not in availability
