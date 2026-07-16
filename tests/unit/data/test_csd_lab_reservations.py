import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def _rows(path: Path):
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _reservation_key(row):
    return (
        row["day"],
        row["session_name"],
        row["course_instance_id"],
        row["room_id"],
    )


def test_csd_cd23321_has_three_owned_tlgl34_reservations():
    reservations = _rows(ROOT / "prod" / "csd-dept_block.csv")
    expected = {
        ("tuesday", "L3", "1120__s0", "9007"),
        ("thur", "L5", "1120__s0", "9007"),
        ("friday", "L4", "1120__s0", "9007"),
    }

    assert {_reservation_key(row) for row in reservations} == expected
    assert {row["room_number"] for row in reservations} == {"TLGL3/4"}

    fixed_rows = _rows(ROOT / "prod" / "lab_schedule_lock.csv")
    matching_fixed_rows = [
        row for row in fixed_rows if _reservation_key(row) in expected
    ]
    fixed_keys = {_reservation_key(row) for row in matching_fixed_rows}
    assert expected <= fixed_keys
    assert len(matching_fixed_rows) == 3


def test_cd23321_keeps_six_hours_and_only_tlgl34_mapping():
    courses = _rows(
        ROOT / "data" / "2" / "2" / "Computer Science and Design_course_data.csv"
    )
    course = next(row for row in courses if row["course_code"] == "CD23321")
    assert course["practical_hours"] == "6"

    mappings = _rows(ROOT / "data" / "computer_lab_mapping.csv")
    mapping = next(
        row for row in mappings
        if row["department"] == "csd" and row["course_code"] == "CD23321"
    )
    assert mapping["preferred_lab_room"] == "TLGL3/4"
