"""Regression tests for fixed-schedule teacher occupancy propagation."""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

from ortools.sat.python import cp_model

from src.constraints.base import ConstraintMetadata
from src.constraints.context import ConstraintContext
from src.constraints.cross_system.teacher_daily_workload import build_teacher_daily_workload_constraint
from src.constraints.cross_system.teacher_day_window import build_teacher_day_window_constraint
from src.constraints.lab.teacher_daily_presence_lab import build_teacher_daily_presence_lab_constraint
from src.constraints.lab.teacher_max_consecutive import build_teacher_max_consecutive_lab_constraint
from src.data.schemas import ExtendedDataContainer
from src.models.schema import (
    LabCourseRequirement,
    LabVariableBlock,
    TheoryCourseRequirement,
    TheoryVariableBlock,
    VariableCreationResult,
)


WORKING_DAYS = ("monday", "tuesday", "wed", "thur", "fri", "saturday")


def _metadata(name: str, domain: str = "cross_system") -> ConstraintMetadata:
    return ConstraintMetadata(
        id=f"{domain}.{name}",
        name=name,
        category=domain,
        priority=9,
    )


def _write_csv(path: Path, header: str, rows: tuple[str, ...]) -> Path:
    path.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return path


def _config_with_fixed(*, lab_csv: Path | None = None, theory_csv: Path | None = None):
    params = {}
    if lab_csv is not None:
        params["lab_csv_path"] = str(lab_csv)
    if theory_csv is not None:
        params["theory_csv_path"] = str(theory_csv)
    return SimpleNamespace(
        time=SimpleNamespace(working_days=WORKING_DAYS),
        constraints=SimpleNamespace(
            cross_system={
                "fixed_schedule_lock": SimpleNamespace(enabled=True, params=params),
            }
        ),
    )


def _empty_lab_block() -> LabVariableBlock:
    return LabVariableBlock(
        assignments={},
        requirements={},
        teacher_courses={},
        day_patterns={},
        lab_session_names=tuple(),
        room_ids=tuple(),
        instance_group_lookup={},
    )


def _empty_theory_block() -> TheoryVariableBlock:
    return TheoryVariableBlock(
        assignments={},
        room_assignments={},
        course_requirements={},
        teacher_courses={},
        course_day_patterns={},
        group_timeslots={},
        requirements={},
        day_patterns={},
        theory_slot_labels=("S1", "S2", "S3"),
    )


def _raw_time():
    return SimpleNamespace(
        working_days=WORKING_DAYS,
        lab_session_to_theory={"L1": (0, 1), "L2": (2, 3), "L3": (4, 5)},
    )


def test_fixed_theory_hours_reduce_teacher_daily_workload_capacity(tmp_path: Path) -> None:
    fixed_theory = _write_csv(
        tmp_path / "fixed_theory.csv",
        "teacher_id,course_instance_id,day,slot_index,room_id",
        ("T1,OLD,monday,0,R_FIXED",),
    )

    model = cp_model.CpModel()
    slot_1 = model.NewBoolVar("new_slot_1")
    slot_2 = model.NewBoolVar("new_slot_2")
    theory_block = TheoryVariableBlock(
        assignments={"T1": {"NEW": {0: {1: slot_1, 2: slot_2}}}},
        course_requirements={
            "NEW": TheoryCourseRequirement(
                course_instance_id="NEW",
                course_code="NEW101",
                group_id="G1",
                teacher_id="T1",
                department="Dept",
                semester=3,
                required_slots=2,
                lecture_hours=2,
                tutorial_hours=0,
                student_count=40,
                preferred_room_type=None,
                required_room_type=None,
            )
        },
        teacher_courses={"T1": ("NEW",)},
        course_day_patterns={"NEW": ("monday",)},
        theory_slot_labels=("S1", "S2", "S3"),
    )
    context = ConstraintContext(
        model=model,
        config=_config_with_fixed(theory_csv=fixed_theory),
        data=ExtendedDataContainer(raw=SimpleNamespace(time=_raw_time()), preprocessing=SimpleNamespace()),
        variables=VariableCreationResult(lab=_empty_lab_block(), theory=theory_block, metadata={}),
        logger=logging.getLogger("tests.fixed.workload"),
    )

    constraint = build_teacher_daily_workload_constraint(
        metadata=_metadata("teacher_daily_workload"),
        params={"max_daily_hours": 2, "mode": "hard"},
    )
    result = constraint.apply(context)
    assert result.details["fixed_hours_applied"] == 1

    model.Add(slot_1 == 1)
    model.Add(slot_2 == 1)
    assert cp_model.CpSolver().Solve(model) == cp_model.INFEASIBLE


def test_fixed_saturday_activity_forces_teacher_tue_sat_window(tmp_path: Path) -> None:
    fixed_lab = _write_csv(
        tmp_path / "fixed_lab.csv",
        "teacher_id,course_instance_id,day,session_name,room_id",
        ("T1,OLD,saturday,L1,R_FIXED",),
    )

    model = cp_model.CpModel()
    monday_lab = model.NewBoolVar("monday_lab")
    lab_block = LabVariableBlock(
        assignments={"T1": {"NEW_LAB": {0: {"L1": {"R1": monday_lab}}}}},
        requirements={},
        teacher_courses={"T1": ("NEW_LAB",)},
        day_patterns={"NEW_LAB": ("monday",)},
        lab_session_names=("L1",),
        room_ids=("R1",),
        instance_group_lookup={},
    )
    context = ConstraintContext(
        model=model,
        config=_config_with_fixed(lab_csv=fixed_lab),
        data=ExtendedDataContainer(raw=SimpleNamespace(time=_raw_time()), preprocessing=SimpleNamespace()),
        variables=VariableCreationResult(lab=lab_block, theory=_empty_theory_block(), metadata={}),
        logger=logging.getLogger("tests.fixed.window"),
    )

    constraint = build_teacher_day_window_constraint(metadata=_metadata("teacher_day_window"))
    constraint.apply(context)

    model.Add(monday_lab == 1)
    assert cp_model.CpSolver().Solve(model) == cp_model.INFEASIBLE


def test_fixed_lab_session_counts_for_daily_presence_and_consecutive_limits(tmp_path: Path) -> None:
    fixed_lab = _write_csv(
        tmp_path / "fixed_lab.csv",
        "teacher_id,course_instance_id,day,session_name,room_id",
        ("T1,OLD,monday,L1,R_FIXED",),
    )

    model = cp_model.CpModel()
    l2 = model.NewBoolVar("new_l2")
    l3 = model.NewBoolVar("new_l3")
    requirements = {
        "NEW_L2": LabCourseRequirement(
            course_instance_id="NEW_L2",
            course_code="LAB2",
            teacher_id="T1",
            group_id="G1",
            department="Dept",
            semester=3,
            practical_hours=2,
            required_sessions=1,
            student_count=30,
            preferred_room_type=None,
            required_room_type=None,
        ),
        "NEW_L3": LabCourseRequirement(
            course_instance_id="NEW_L3",
            course_code="LAB3",
            teacher_id="T1",
            group_id="G2",
            department="Dept",
            semester=3,
            practical_hours=2,
            required_sessions=1,
            student_count=30,
            preferred_room_type=None,
            required_room_type=None,
        ),
    }
    lab_block = LabVariableBlock(
        assignments={
            "T1": {
                "NEW_L2": {0: {"L2": {"R1": l2}}},
                "NEW_L3": {0: {"L3": {"R1": l3}}},
            }
        },
        requirements=requirements,
        teacher_courses={"T1": ("NEW_L2", "NEW_L3")},
        day_patterns={"NEW_L2": ("monday",), "NEW_L3": ("monday",)},
        lab_session_names=("L1", "L2", "L3"),
        room_ids=("R1",),
        instance_group_lookup={"NEW_L2": "G1", "NEW_L3": "G2"},
    )
    context = ConstraintContext(
        model=model,
        config=_config_with_fixed(lab_csv=fixed_lab),
        data=ExtendedDataContainer(raw=SimpleNamespace(time=_raw_time()), preprocessing=SimpleNamespace()),
        variables=VariableCreationResult(lab=lab_block, theory=_empty_theory_block(), metadata={}),
        logger=logging.getLogger("tests.fixed.lab_presence"),
    )

    build_teacher_daily_presence_lab_constraint(
        metadata=_metadata("teacher_daily_presence_lab", domain="lab"),
        params={"max_daily_sessions": 2},
    ).apply(context)
    build_teacher_max_consecutive_lab_constraint(
        metadata=_metadata("teacher_max_consecutive", domain="lab"),
        params={"max_consecutive_sessions": 2},
    ).apply(context)

    model.Add(l2 == 1)
    model.Add(l3 == 1)
    assert cp_model.CpSolver().Solve(model) == cp_model.INFEASIBLE


def test_fixed_early_and_late_day_does_not_invalidate_other_days(tmp_path: Path) -> None:
    fixed_lab = _write_csv(
        tmp_path / "fixed_lab.csv",
        "teacher_id,course_instance_id,day,session_name,room_id",
        (
            "T1,OLD_EARLY,monday,L1,R_FIXED",
            "T1,OLD_LATE,monday,L5,R_FIXED",
        ),
    )

    model = cp_model.CpModel()
    monday_l2 = model.NewBoolVar("monday_l2")
    tuesday_l2 = model.NewBoolVar("tuesday_l2")
    requirement = LabCourseRequirement(
        course_instance_id="NEW",
        course_code="LAB2",
        teacher_id="T1",
        group_id="G1",
        department="Dept",
        semester=3,
        practical_hours=2,
        required_sessions=1,
        student_count=30,
        preferred_room_type=None,
        required_room_type=None,
    )
    lab_block = LabVariableBlock(
        assignments={
            "T1": {
                "NEW": {
                    0: {"L2": {"R1": monday_l2}},
                    1: {"L2": {"R1": tuesday_l2}},
                }
            }
        },
        requirements={"NEW": requirement},
        teacher_courses={"T1": ("NEW",)},
        day_patterns={"NEW": ("monday", "tuesday")},
        lab_session_names=("L1", "L2", "L5"),
        room_ids=("R1",),
        instance_group_lookup={"NEW": "G1"},
    )
    context = ConstraintContext(
        model=model,
        config=_config_with_fixed(lab_csv=fixed_lab),
        data=ExtendedDataContainer(raw=SimpleNamespace(time=_raw_time()), preprocessing=SimpleNamespace()),
        variables=VariableCreationResult(lab=lab_block, theory=_empty_theory_block(), metadata={}),
        logger=logging.getLogger("tests.fixed.lab_presence.residual"),
    )

    build_teacher_daily_presence_lab_constraint(
        metadata=_metadata("teacher_daily_presence_lab", domain="lab"),
        params={
            "max_daily_sessions": 2,
            "early_sessions": ("L1",),
            "buffer_sessions": ("L3",),
            "late_sessions": ("L5",),
        },
    ).apply(context)

    model.Add(monday_l2 == 0)
    model.Add(tuesday_l2 == 1)
    assert cp_model.CpSolver().Solve(model) in (cp_model.FEASIBLE, cp_model.OPTIMAL)
