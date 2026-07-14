from __future__ import annotations

import logging
from types import SimpleNamespace

from ortools.sat.python import cp_model

from src.constraints.base import ConstraintMetadata
from src.constraints.context import ConstraintContext
from src.constraints.cross_system.section_late_day import build_section_late_day_constraint
from src.data.schemas import ExtendedDataContainer
from src.models.schema import (
    LabCourseRequirement,
    LabVariableBlock,
    TheoryCourseRequirement,
    TheoryVariableBlock,
    VariableCreationResult,
)


DEPARTMENT = "Computer Science and Engineering"


def _theory_requirement(instance: str, code: str, teacher: str) -> TheoryCourseRequirement:
    return TheoryCourseRequirement(
        course_instance_id=instance,
        course_code=code,
        group_id="CSE_S3_SEC1",
        teacher_id=teacher,
        department=DEPARTMENT,
        semester=3,
        required_slots=1,
        lecture_hours=1,
        tutorial_hours=0,
        student_count=64,
        preferred_room_type=None,
        required_room_type=None,
        section_id=1,
    )


def _lab_requirement(instance: str, code: str, teacher: str) -> LabCourseRequirement:
    return LabCourseRequirement(
        course_instance_id=instance,
        course_code=code,
        teacher_id=teacher,
        group_id="CSE_S3_SEC1",
        department=DEPARTMENT,
        semester=3,
        practical_hours=2,
        required_sessions=1,
        student_count=64,
        preferred_room_type=None,
        required_room_type=None,
        section_id=1,
    )


def _context(*, include_ordinary_late_lab: bool) -> tuple[ConstraintContext, list[cp_model.IntVar]]:
    model = cp_model.CpModel()
    ordinary_theory = model.NewBoolVar("ordinary_theory_late")
    dbms_theory = model.NewBoolVar("dbms_theory_late")
    dbms_lab = model.NewBoolVar("dbms_lab_late")
    selected = [ordinary_theory, dbms_theory, dbms_lab]

    theory = TheoryVariableBlock(
        assignments={
            "T1": {"ordinary": {0: {7: ordinary_theory}}},
            "T2": {"dbms_theory": {1: {7: dbms_theory}}},
        },
        course_requirements={
            "ordinary": _theory_requirement("ordinary", "CS23331", "T1"),
            "dbms_theory": _theory_requirement("dbms_theory", "CS23332", "T2"),
        },
        instance_group_lookup={"ordinary": "CSE_S3_SEC1", "dbms_theory": "CSE_S3_SEC1"},
    )

    lab_requirements = {"dbms_lab": _lab_requirement("dbms_lab", "CS23332", "T2")}
    lab_assignments = {"T2": {"dbms_lab": {2: {"L5": {"R1": dbms_lab}}}}}
    if include_ordinary_late_lab:
        ordinary_lab = model.NewBoolVar("ordinary_lab_late")
        selected.append(ordinary_lab)
        lab_requirements["ordinary_lab"] = _lab_requirement("ordinary_lab", "CS23331", "T3")
        lab_assignments["T3"] = {"ordinary_lab": {3: {"L5": {"R2": ordinary_lab}}}}

    lab = LabVariableBlock(
        assignments=lab_assignments,
        requirements=lab_requirements,
        teacher_courses={},
        day_patterns={},
        lab_session_names=("L5",),
        room_ids=("R1", "R2"),
        instance_group_lookup={},
    )
    raw = SimpleNamespace(time=SimpleNamespace(working_days=("monday", "tuesday", "wed", "thur", "fri")))
    context = ConstraintContext(
        model=model,
        config=SimpleNamespace(),
        data=ExtendedDataContainer(raw=raw, preprocessing=SimpleNamespace()),
        variables=VariableCreationResult(lab=lab, theory=theory, metadata={}),
        logger=logging.getLogger("tests.section_late_day"),
    )
    return context, selected


def _apply(context: ConstraintContext):
    return build_section_late_day_constraint(
        metadata=ConstraintMetadata(
            id="cross.section_late_day",
            name="Section Late-Day Cap",
            category="cross_system",
            priority=6,
        ),
        params={
            "mode": "hard",
            "max_late_days": 1,
            "single_section_max_late_days": 1,
            "late_theory_slots": [7, 8],
            "late_lab_sessions": ["L5"],
            "excluded_course_codes": ["CS23332", "CS23333", "CB23333"],
        },
    ).apply(context)


def test_external_combined_courses_do_not_consume_late_days() -> None:
    context, selected = _context(include_ordinary_late_lab=False)
    result = _apply(context)
    for variable in selected:
        context.model.Add(variable == 1)

    assert result.details["excluded_course_codes"] == ["CB23333", "CS23332", "CS23333"]
    assert cp_model.CpSolver().Solve(context.model) in (cp_model.FEASIBLE, cp_model.OPTIMAL)


def test_ordinary_courses_still_obey_hard_late_day_cap() -> None:
    context, selected = _context(include_ordinary_late_lab=True)
    _apply(context)
    for variable in selected:
        context.model.Add(variable == 1)

    assert cp_model.CpSolver().Solve(context.model) == cp_model.INFEASIBLE
