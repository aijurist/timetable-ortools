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
