"""Room eligibility pruning tests."""

from __future__ import annotations

import pandas as pd

from src.data.room_eligibility import build_room_eligibility_index


def test_theory_rooms_are_ranked_and_capped_for_small_courses() -> None:
    rooms_df = pd.DataFrame(
        [
            {"id": "A40", "block": "A Block", "capacity": 40},
            {"id": "A55", "block": "A Block", "capacity": 55},
            {"id": "B45", "block": "B Block", "capacity": 45},
            {"id": "B70", "block": "B Block", "capacity": 70},
            {"id": "C40", "block": "C Block", "capacity": 40},
            {"id": "A140", "block": "A Block", "capacity": 140},
            {"id": "B140", "block": "B Block", "capacity": 140},
        ]
    )
    index = build_room_eligibility_index(
        core_lab_df=None,
        rooms_df=rooms_df,
        lab_room_ids=tuple(),
        theory_room_ids=tuple(rooms_df["id"]),
        theory_room_candidate_limit=4,
        theory_room_min_candidates=3,
        theory_room_anchor_candidates=2,
    )

    rooms = index.get_eligible_theory_rooms(
        student_count=35,
        semester=5,
        course_id="CS101",
        group_id="CSE_S5_G1",
    )

    assert len(rooms) == 4
    assert "A140" not in rooms
    assert "B140" not in rooms
    assert rooms[0:2] == ("A40", "A55")
    assert set(rooms).issubset({"A40", "A55", "B45", "B70"})


def test_theory_rooms_keep_large_course_tier_filter() -> None:
    rooms_df = pd.DataFrame(
        [
            {"id": "A120", "block": "A Block", "capacity": 120},
            {"id": "220", "block": "A Block", "capacity": 150},
            {"id": "221", "block": "A Block", "capacity": 180},
            {"id": "222", "block": "B Block", "capacity": 180},
            {"id": "223", "block": "A Block", "capacity": 150},
            {"id": "224", "block": "B Block", "capacity": 150},
            {"id": "225", "block": "A Block", "capacity": 240},
        ]
    )
    index = build_room_eligibility_index(
        core_lab_df=None,
        rooms_df=rooms_df,
        lab_room_ids=tuple(),
        theory_room_ids=tuple(rooms_df["id"]),
        theory_room_candidate_limit=12,
        theory_room_min_candidates=4,
        theory_room_anchor_candidates=4,
    )

    rooms = index.get_eligible_theory_rooms(
        student_count=145,
        semester=7,
        course_id="ME401",
        group_id="ME_S7_G1",
    )

    assert set(rooms) == {"220", "223", "224"}
    assert "221" not in rooms
    assert "222" not in rooms
    assert "225" not in rooms
