from __future__ import annotations

import logging
from types import SimpleNamespace

from ortools.sat.python import cp_model

from src.constraints.base import ConstraintMetadata
from src.constraints.context import ConstraintContext
from src.constraints.cross_system.combined_lab import build_combined_lab_constraint
from src.constraints.schema import ConstraintStatus
from src.data.schemas import ExtendedDataContainer
from src.models.schema import (
    LabCourseRequirement,
    LabVariableBlock,
    TheoryVariableBlock,
    VariableCreationResult,
)


def _metadata() -> ConstraintMetadata:
    return ConstraintMetadata(
        id="cross_system.combined_lab",
        name="Combined DBMS/OOPS Lab Blocks",
        category="cross_system",
        priority=3,
    )


def test_selected_combined_lab_pair_stays_together_across_all_blocks() -> None:
    model = cp_model.CpModel()
    first_monday = model.NewBoolVar("first_monday")
    first_tuesday = model.NewBoolVar("first_tuesday")
    second_monday = model.NewBoolVar("second_monday")
    second_tuesday = model.NewBoolVar("second_tuesday")
    assignments = {
        "T1": {
            "DBMS1": {
                0: {"L1": {"R1": first_monday}},
                1: {"L1": {"R1": first_tuesday}},
            }
        },
        "T2": {
            "DBMS2": {
                0: {"L1": {"R1": second_monday}},
                1: {"L1": {"R1": second_tuesday}},
            }
        },
    }
    requirements = {
        instance_id: LabCourseRequirement(
            course_instance_id=instance_id,
            course_code="CS23332",
            teacher_id=teacher_id,
            group_id="G1",
            department="Engineering",
            semester=3,
            practical_hours=8,
            required_sessions=4,
            student_count=65,
            preferred_room_type=None,
            required_room_type="Core-Lab",
        )
        for instance_id, teacher_id in (("DBMS1", "T1"), ("DBMS2", "T2"))
    }
    lab_block = LabVariableBlock(
        assignments=assignments,
        requirements=requirements,
        teacher_courses={"T1": ("DBMS1",), "T2": ("DBMS2",)},
        day_patterns={
            "DBMS1": ("Monday", "Tuesday"),
            "DBMS2": ("Monday", "Tuesday"),
        },
        lab_session_names=("L1",),
        room_ids=("R1",),
        instance_group_lookup={"DBMS1": "G1", "DBMS2": "G1"},
    )
    config = SimpleNamespace(
        model=SimpleNamespace(
            combined_lab_courses={"course_codes": ("CS23332", "CS23333")},
            objective_weights={},
        )
    )
    context = ConstraintContext(
        model=model,
        config=config,
        data=ExtendedDataContainer(raw=SimpleNamespace(), preprocessing=SimpleNamespace()),
        variables=VariableCreationResult(
            lab=lab_block,
            theory=TheoryVariableBlock(),
            metadata={},
        ),
        logger=logging.getLogger("tests.constraints.combined_lab"),
    )

    result = build_combined_lab_constraint(
        metadata=_metadata(),
        params={"enforce_stable_pairing": True, "solo_penalty_weight": 0},
    ).apply(context)

    assert result.status == ConstraintStatus.APPLIED
    assert result.details["candidate_pairs"] == 1
    model.Add(first_monday == 1)
    model.Add(second_monday == 1)
    model.Add(first_tuesday == 1)
    model.Add(second_tuesday == 0)
    assert cp_model.CpSolver().Solve(model) == cp_model.INFEASIBLE
