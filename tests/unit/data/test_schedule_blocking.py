from pathlib import Path

from src.data.schedule_blocking import build_schedule_blocking_mask


def test_fixed_locks_block_staff_and_rooms_across_lab_and_theory(tmp_path: Path):
    lab_path = tmp_path / "lab.csv"
    lab_path.write_text(
        "day,session_name,course_instance_id,teacher_id,room_id\n"
        "tuesday,L1,fixed_lab,211.0,R1\n",
        encoding="utf-8",
    )
    theory_path = tmp_path / "theory.csv"
    theory_path.write_text(
        "day,slot_index,course_instance_id,teacher_id,room_id\n"
        "wed,0,fixed_theory,212,R2\n",
        encoding="utf-8",
    )

    mask = build_schedule_blocking_mask(
        lab_path,
        theory_path,
        lab_session_to_theory_mapping={"L1": (0, 1), "L2": (2, 3)},
        working_days=("monday", "tuesday", "wed", "thur", "fri"),
    )

    # Exact fixed assignments stay available so their lock can force them to 1.
    assert not mask.is_lab_variable_blocked("211", "fixed_lab", "tuesday", "L1", "R1")
    assert not mask.is_theory_variable_blocked("212.0", "fixed_theory", "wed", 0, "R2")

    # Fixed lab -> new theory: both teacher and room are unavailable.
    assert mask.is_theory_variable_blocked("211", "new", "tuesday", 0, "R9")
    assert mask.is_theory_variable_blocked("999", "new", "tuesday", 1, "R1")

    # Fixed theory -> new lab: both teacher and room are unavailable.
    assert mask.is_lab_variable_blocked("212.0", "new", "wednesday", "L1", "R9")
    assert mask.is_lab_variable_blocked("999", "new", "wednesday", "L1", "R2")
