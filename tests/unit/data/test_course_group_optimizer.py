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
