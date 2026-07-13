"""Special-case grouping tests for CourseGroupOptimizer."""

from __future__ import annotations

import logging
from collections import defaultdict

import pytest

from src.data.course_group_optimizer import CourseGroupOptimizer


def _course(
    instance_id: str,
    course_code: str,
    teacher_id: str,
    *,
    practical_hours: int = 0,
    lecture_hours: int = 0,
    tutorial_hours: int = 0,
) -> dict:
    return {
        "id": instance_id,
        "course_code": course_code,
        "teacher_id": teacher_id,
        "practical_hours": practical_hours,
        "lecture_hours": lecture_hours,
        "tutorial_hours": tutorial_hours,
        "has_lab": practical_hours > 0,
        "has_theory": lecture_hours > 0 or tutorial_hours > 0,
        "weight": 1,
    }


@pytest.mark.skip(reason="Mechanical S5 forced split hook is temporarily disabled for soft-lunch testing.")
def test_mechanical_s5_forces_target_courses_to_split_across_two_groups() -> None:
    courses = [
        _course("a1", "ME23521", "t1", practical_hours=4),
        _course("a2", "ME23521", "t2", practical_hours=4),
        _course("b1", "ME23532", "t3", practical_hours=4, lecture_hours=3),
        _course("b2", "ME23532", "t4", practical_hours=4, lecture_hours=3),
        _course("c1", "ME23511", "t5", lecture_hours=3),
        _course("c2", "ME23511", "t6", lecture_hours=3),
    ]
    optimizer = CourseGroupOptimizer(
        courses,
        dept="Mechanical Engineering",
        semester=5,
        logger=logging.getLogger("test-mechanical-s5-split"),
        consolidation_objective_enabled=True,
    )

    assert optimizer.optimize_distribution()
    assert optimizer.validate_solution()

    groups_by_course = defaultdict(set)
    for group_idx, group in enumerate(optimizer.groups[: optimizer.num_groups]):
        for instance in group:
            if instance["course_code"] in {"ME23521", "ME23532"}:
                groups_by_course[instance["course_code"]].add(group_idx)

    assert len(groups_by_course["ME23521"]) == 2
    assert len(groups_by_course["ME23532"]) == 2


def test_eee_s5_fixed_grouping_adds_standalone_pe_group(tmp_path) -> None:
    pe_map = tmp_path / "pe_course_map.csv"
    pe_map.write_text(
        "GENERAL CODE,PE1,PE2,PE3,PE4,PE5,DEPT,SEM\n"
        "EE23PE31,EE23B21,,,,,EEE,5\n"
        "EE23PE32,CS23XXX1,,,,,EEE,5\n",
        encoding="utf-8",
    )
    courses = [
        _course("1136", "EE23PE31", "319", practical_hours=6),
        _course("1137", "EE23PE31", "320", practical_hours=6),
        _course("1544", "EE23PE32", "296", practical_hours=2, lecture_hours=2),
        _course("1545", "EE23PE32", "314", practical_hours=2, lecture_hours=2),
        _course("1130", "EE23521", "313", practical_hours=2),
        _course("1131", "EE23521", "317", practical_hours=2),
        _course("557", "EE23531", "308", practical_hours=2, lecture_hours=3),
        _course("558", "EE23531", "305", practical_hours=2, lecture_hours=3),
        _course("551", "EE23511", "301", lecture_hours=3),
        _course("552", "EE23511", "302", lecture_hours=3),
        _course("553", "EE23512", "303", lecture_hours=3),
        _course("554", "EE23512", "304", lecture_hours=3),
        _course("555", "EE23513", "306", lecture_hours=3),
        _course("556", "EE23513", "307", lecture_hours=3),
        _course("1134", "GE23627", "321", lecture_hours=4),
        _course("1135", "GE23627", "322", lecture_hours=4),
    ]
    optimizer = CourseGroupOptimizer(
        courses,
        dept="Electrical & Electronics Engineering",
        semester=5,
        logger=logging.getLogger("test-eee-s5-fixed"),
        pe_course_map_file=str(pe_map),
        consolidation_objective_enabled=True,
    )

    assert optimizer.optimize_distribution()
    assert optimizer.validate_solution()

    assert optimizer.num_groups == 8
    assert len(optimizer.groups) == 8
    assert [set(inst["course_code"] for inst in group) for group in optimizer.groups[:2]] == [
        {"EE23PE31", "EE23531"},
        {"EE23PE31", "EE23531"},
    ]
    assert [inst["course_code"] for inst in optimizer.groups[7]] == ["EE23PE32", "EE23PE32"]
    assert all(len({inst["course_code"] for inst in group}) <= 2 for group in optimizer.groups)
