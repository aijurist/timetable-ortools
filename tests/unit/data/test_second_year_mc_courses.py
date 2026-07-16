import csv
from pathlib import Path


COURSE_DATA_ROOT = Path("data/2/2")


def _rows(filename: str) -> list[dict[str, str]]:
	with (COURSE_DATA_ROOT / filename).open(newline="", encoding="utf-8-sig") as handle:
		return list(csv.DictReader(handle))


def test_environmental_science_is_one_lecture_hour_in_production_inputs() -> None:
	rows = []
	for path in COURSE_DATA_ROOT.glob("*_course_data.csv"):
		rows.extend(
			row
			for row in _rows(path.name)
			if str(row.get("course_code", "")).strip().upper().startswith("MC23")
		)

	assert rows
	assert {row["lecture_hours"] for row in rows} == {"1"}
	assert {row["practical_hours"] for row in rows} == {"0"}
	assert {row["tutorial_hours"] for row in rows} == {"0"}


def test_aiml_has_one_unique_dummy_mc_teacher_per_section() -> None:
	rows = [
		row
		for row in _rows("Artificial Intelligence and Machine Learning_course_data.csv")
		if str(row.get("course_code", "")).strip().upper() == "MC23112"
	]

	assert len(rows) == 4
	assert len({row["teacher_id"] for row in rows}) == 4
	assert all(row["teacher_role"] == "Placeholder" for row in rows)
