"""Unit tests for cross-system course day spread constraints."""

from __future__ import annotations

import logging
from types import SimpleNamespace

from ortools.sat.python import cp_model

from src.constraints.base import ConstraintMetadata
from src.constraints.context import ConstraintContext
from src.constraints.cross_system.course_day_spread import build_course_day_spread_constraint
from src.constraints.schema import ConstraintStatus
from src.data.schemas import ExtendedDataContainer
from src.models.schema import (
    LabCourseRequirement,
    LabVariableBlock,
    TheoryCourseRequirement,
    TheoryVariableBlock,
    VariableCreationResult,
)


def _metadata(label: str = "hard") -> ConstraintMetadata:
    return ConstraintMetadata(
        id=f"cross.course_day_spread.{label}",
        name=f"Course Day Spread {label}",
        category="cross_system",
        priority=9,
    )


def _build_context() -> tuple[ConstraintContext, dict[str, cp_model.IntVar]]:
    model = cp_model.CpModel()
    variables = {
        "lab_d0": model.NewBoolVar("lab_d0"),
        "lab_d1": model.NewBoolVar("lab_d1"),
        "theory_d0": model.NewBoolVar("theory_d0"),
        "theory_d1": model.NewBoolVar("theory_d1"),
    }

    lab_requirement = LabCourseRequirement(
        course_instance_id="CS23632_LAB",
        course_code="CS23632",
        teacher_id="T1",
        group_id="G1",
        department="Computer Science & Design",
        semester=5,
        practical_hours=2,
        required_sessions=1,
        student_count=70,
        preferred_room_type=None,
        required_room_type=None,
    )
    lab_block = LabVariableBlock(
        assignments={
            "T1": {
                "CS23632_LAB": {
                    0: {"L2": {"R1": variables["lab_d0"]}},
                    1: {"L2": {"R1": variables["lab_d1"]}},
                }
            }
        },
        requirements={"CS23632_LAB": lab_requirement},
        teacher_courses={"T1": ("CS23632_LAB",)},
        day_patterns={"CS23632_LAB": ("monday", "tuesday")},
        lab_session_names=("L2",),
        room_ids=("R1",),
        instance_group_lookup={"CS23632_LAB": "G1"},
    )

    theory_requirement = TheoryCourseRequirement(
        course_instance_id="CS23632_TH",
        course_code="CS23632",
        group_id="G1",
        teacher_id="T1",
        department="Computer Science & Design",
        semester=5,
        required_slots=1,
        lecture_hours=1,
        tutorial_hours=0,
        student_count=70,
        preferred_room_type=None,
        required_room_type=None,
    )
    theory_block = TheoryVariableBlock(
        assignments={
            "T1": {
                "CS23632_TH": {
                    0: {0: variables["theory_d0"]},
                    1: {0: variables["theory_d1"]},
                }
            }
        },
        course_requirements={"CS23632_TH": theory_requirement},
        teacher_courses={"T1": ("CS23632_TH",)},
        course_day_patterns={"CS23632_TH": ("monday", "tuesday")},
        theory_slot_labels=("8:00 - 8:50",),
        instance_group_lookup={"CS23632_TH": "G1"},
    )

    data = ExtendedDataContainer(raw=SimpleNamespace(), preprocessing=SimpleNamespace())
    constraint_context = ConstraintContext(
        model=model,
        config=SimpleNamespace(),
        data=data,
        variables=VariableCreationResult(lab=lab_block, theory=theory_block, metadata={}),
        logger=logging.getLogger("tests.constraints.course_day_spread"),
    )
    return constraint_context, variables


def test_course_day_spread_blocks_mixed_course_on_one_day() -> None:
    context, variables = _build_context()
    constraint = build_course_day_spread_constraint(metadata=_metadata())

    result = constraint.apply(context)

    assert result.status == ConstraintStatus.APPLIED
    assert result.details["hard_constraints"] == 1

    context.model.Add(variables["lab_d0"] == 1)
    context.model.Add(variables["theory_d0"] == 1)
    context.model.Add(variables["lab_d1"] == 0)
    context.model.Add(variables["theory_d1"] == 0)

    solver = cp_model.CpSolver()
    assert solver.Solve(context.model) == cp_model.INFEASIBLE


def test_course_day_spread_allows_mixed_course_split_across_days() -> None:
    context, variables = _build_context()
    constraint = build_course_day_spread_constraint(metadata=_metadata("split"))
    constraint.apply(context)

    context.model.Add(variables["lab_d0"] == 1)
    context.model.Add(variables["theory_d0"] == 0)
    context.model.Add(variables["lab_d1"] == 0)
    context.model.Add(variables["theory_d1"] == 1)

    solver = cp_model.CpSolver()
    assert solver.Solve(context.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
