"""Unit tests for department-level day coverage constraints."""

from __future__ import annotations

import logging
from types import SimpleNamespace

from ortools.sat.python import cp_model

from src.constraints.base import ConstraintMetadata
from src.constraints.context import ConstraintContext
from src.constraints.cross_system.dept_day_coverage import build_department_day_coverage_constraint
from src.constraints.schema import ConstraintStatus
from src.data.schemas import ExtendedDataContainer
from src.models.schema import (
    LabCourseRequirement,
    LabVariableBlock,
    TheoryCourseRequirement,
    TheoryVariableBlock,
    VariableCreationResult,
)


DEPARTMENT = "Aeronautical Engineering"
DAY_PATTERN = ("tuesday", "wed", "thur", "fri", "saturday")


def _metadata(label: str = "hard") -> ConstraintMetadata:
    return ConstraintMetadata(
        id=f"cross.dept_day_coverage.{label}",
        name=f"Department Day Coverage {label}",
        category="cross_system",
        priority=9,
    )


def _build_context() -> tuple[ConstraintContext, dict[str, cp_model.IntVar]]:
    model = cp_model.CpModel()
    variables = {
        "lab_d0": model.NewBoolVar("lab_d0"),
        "lab_d1": model.NewBoolVar("lab_d1"),
        "lab_d4": model.NewBoolVar("lab_d4"),
        "theory_d2": model.NewBoolVar("theory_d2"),
        "theory_d3": model.NewBoolVar("theory_d3"),
        "theory_d4": model.NewBoolVar("theory_d4"),
    }

    lab_requirement = LabCourseRequirement(
        course_instance_id="AERO_LAB",
        course_code="AE23721",
        teacher_id="T1",
        group_id="AERO_G2",
        department=DEPARTMENT,
        semester=7,
        practical_hours=4,
        required_sessions=2,
        student_count=45,
        preferred_room_type=None,
        required_room_type=None,
    )
    lab_block = LabVariableBlock(
        assignments={
            "T1": {
                "AERO_LAB": {
                    0: {"L2": {"R1": variables["lab_d0"]}},
                    1: {"L2": {"R1": variables["lab_d1"]}},
                    4: {"L2": {"R1": variables["lab_d4"]}},
                }
            }
        },
        requirements={"AERO_LAB": lab_requirement},
        teacher_courses={"T1": ("AERO_LAB",)},
        day_patterns={"AERO_LAB": DAY_PATTERN},
        lab_session_names=("L2",),
        room_ids=("R1",),
        instance_group_lookup={"AERO_LAB": "AERO_G2"},
    )

    theory_requirement = TheoryCourseRequirement(
        course_instance_id="AERO_THEORY",
        course_code="AE23A16",
        group_id="AERO_G3",
        teacher_id="T2",
        department=DEPARTMENT,
        semester=7,
        required_slots=3,
        lecture_hours=3,
        tutorial_hours=0,
        student_count=45,
        preferred_room_type=None,
        required_room_type=None,
    )
    theory_block = TheoryVariableBlock(
        assignments={
            "T2": {
                "AERO_THEORY": {
                    2: {0: variables["theory_d2"]},
                    3: {0: variables["theory_d3"]},
                    4: {0: variables["theory_d4"]},
                }
            }
        },
        course_requirements={"AERO_THEORY": theory_requirement},
        teacher_courses={"T2": ("AERO_THEORY",)},
        course_day_patterns={"AERO_THEORY": DAY_PATTERN},
        theory_slot_labels=("8:00 - 8:50",),
        instance_group_lookup={"AERO_THEORY": "AERO_G3"},
    )

    raw = SimpleNamespace(
        time=SimpleNamespace(working_days=DAY_PATTERN),
        departments=SimpleNamespace(day_patterns={DEPARTMENT: DAY_PATTERN, "__default__": DAY_PATTERN}),
    )
    data = ExtendedDataContainer(raw=raw, preprocessing=SimpleNamespace())
    context = ConstraintContext(
        model=model,
        config=SimpleNamespace(),
        data=data,
        variables=VariableCreationResult(lab=lab_block, theory=theory_block, metadata={}),
        logger=logging.getLogger("tests.constraints.dept_day_coverage"),
    )
    return context, variables


def test_dept_day_coverage_blocks_four_day_department_schedule() -> None:
    context, variables = _build_context()
    constraint = build_department_day_coverage_constraint(metadata=_metadata())

    result = constraint.apply(context)

    assert result.status == ConstraintStatus.APPLIED
    assert result.details["hard_constraints"] == 1
    assert result.details["target_days_by_department"] == {f"{DEPARTMENT}_S7": 5}

    context.model.Add(variables["lab_d0"] == 1)
    context.model.Add(variables["lab_d1"] == 1)
    context.model.Add(variables["theory_d2"] == 1)
    context.model.Add(variables["theory_d3"] == 1)
    context.model.Add(variables["lab_d4"] == 0)
    context.model.Add(variables["theory_d4"] == 0)

    solver = cp_model.CpSolver()
    assert solver.Solve(context.model) == cp_model.INFEASIBLE


def test_dept_day_coverage_allows_five_day_department_schedule() -> None:
    context, variables = _build_context()
    constraint = build_department_day_coverage_constraint(metadata=_metadata("split"))
    constraint.apply(context)

    context.model.Add(variables["lab_d0"] == 1)
    context.model.Add(variables["lab_d1"] == 1)
    context.model.Add(variables["theory_d2"] == 1)
    context.model.Add(variables["theory_d3"] == 1)
    context.model.Add(variables["lab_d4"] == 1)
    context.model.Add(variables["theory_d4"] == 0)

    solver = cp_model.CpSolver()
    assert solver.Solve(context.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
