from __future__ import annotations

from dataclasses import replace

import pandas as pd
import pytest
from ortools.sat.python import cp_model

from src.config.defaults import default_scheduler_config
from src.data.kutty_pairing import KuttyBundlePlanner
from src.data.preprocessing import DataPreprocessor, DepartmentCourseGrouper
from src.data.schedule_blocking import ScheduleBlockingMask, build_schedule_blocking_mask
from src.data.schemas import (
    CourseGroup,
    DepartmentSchedulingPackage,
    DepartmentSemesterKey,
    ExtendedDataContainer,
    GroupRequirement,
    GroupSummary,
    NormalizedCourseInstance,
    PreprocessingResult,
)
from src.models.variables import VariableCreator
from tests.unit.runtime.runtime_test_helpers import build_extended_container


KEY = DepartmentSemesterKey("Engineering", 3)


def _instance(
    instance_id: str,
    course_code: str,
    teacher_id: str,
    *,
    lecture_hours: int = 1,
    tutorial_hours: int = 0,
    practical_hours: int = 0,
    student_count: int = 60,
) -> NormalizedCourseInstance:
    return NormalizedCourseInstance(
        instance_id=instance_id,
        course_id=instance_id,
        course_code=course_code,
        course_name=course_code,
        course_type="T",
        semester=3,
        student_dept="Engineering",
        course_dept="Engineering",
        teacher_id=teacher_id,
        teacher_name=teacher_id,
        assistant_teacher_id=None,
        assistant_teacher_name=None,
        has_lab=False,
        has_theory=True,
        lecture_hours=lecture_hours,
        tutorial_hours=tutorial_hours,
        practical_hours=practical_hours,
        student_count=student_count,
        requires_special_scheduling=False,
        requires_assistant=False,
        preferred_lab_type=None,
        preferred_room_type=None,
        required_room_type=None,
        pe_flag=False,
    )


def _group(ordinal: int, instance: NormalizedCourseInstance) -> CourseGroup:
    return CourseGroup(
        key=KEY,
        group_id=f"G{ordinal}",
        ordinal=ordinal,
        is_professional_elective=False,
        course_instance_ids=(instance.instance_id,),
        teacher_ids=(instance.teacher_id,),
        course_codes=(instance.course_code,),
        summary=GroupSummary(
            num_instances=1,
            num_courses=1,
            num_teachers=1,
            lab_instances=0,
            theory_instances=1,
            total_student_count=instance.student_count,
            lab_hours=instance.practical_hours,
            theory_hours=instance.lecture_hours + instance.tutorial_hours,
        ),
        tags=("selection_course_group",),
    )


def _raw_data(*, blocking_mask: ScheduleBlockingMask | None = None):
    container = build_extended_container()
    room_df = pd.DataFrame(
        [{"id": "A202", "room_number": "A202", "block": "A", "capacity": 70, "room_type": "Classroom"}]
    )
    rooms = replace(container.raw.rooms, theory_rooms=room_df, theory_room_ids=("A202",))
    time = replace(
        container.raw.time,
        theory_slots=("08:00-08:50", "09:00-09:50", "10:00-10:50", "11:00-11:50"),
    )
    return replace(
        container.raw,
        config=default_scheduler_config(),
        rooms_df=room_df,
        rooms=rooms,
        time=time,
        room_registry={"A202": room_df.iloc[0].to_dict()},
        blocking_mask=blocking_mask,
    )


def test_pairing_uses_fixed_staff_intersection_and_reports_odd_fallback() -> None:
    first = _instance("A1", "A", "T1")
    blocked = _instance("B1", "B", "T2")
    available = _instance("C1", "C", "T3")
    instances = (first, blocked, available)
    groups = tuple(_group(index, instance) for index, instance in enumerate(instances, start=1))
    mask = ScheduleBlockingMask(
        blocked_theory_teacher_slots={
            ("T2", "monday", 0),
            ("T2", "monday", 1),
            ("T2", "tuesday", 0),
        }
    )
    raw = _raw_data(blocking_mask=mask)

    planner = KuttyBundlePlanner(raw.config.grouping)
    planned, stats = planner.plan({KEY: instances}, {KEY: groups}, raw)

    paired = [bundle for bundle in planned[KEY] if bundle.is_paired]
    singletons = [bundle for bundle in planned[KEY] if not bundle.is_paired]
    assert [bundle.instance_ids for bundle in paired] == [("A1", "C1")]
    assert [bundle.instance_ids for bundle in singletons] == [("B1",)]
    assert stats == {
        "cohorts": 1,
        "paired_bundles": 1,
        "singletons": 1,
        "verified_bundles": 2,
    }
    assert "full 50-minute" in planner.warnings[0]


def test_variable_creator_aliases_both_halves_to_one_slot_and_room() -> None:
    first = _instance("A1", "A", "T1")
    second = _instance("B1", "B", "T2")
    instances = (first, second)
    groups = tuple(_group(index, instance) for index, instance in enumerate(instances, start=1))
    raw = _raw_data()
    bundles, _ = KuttyBundlePlanner(raw.config.grouping).plan({KEY: instances}, {KEY: groups}, raw)
    requirements = tuple(
        GroupRequirement(
            group_id=group.group_id,
            department=KEY.department,
            semester=KEY.semester,
            has_lab=False,
            required_lab_sessions=0,
            prefer_consecutive_labs=False,
            lunch_slot_window=tuple(),
            five_pm_policy=None,
        )
        for group in groups
    )
    preprocessing = PreprocessingResult(
        normalized_instances={KEY: instances},
        groups={KEY: groups},
        scheduling_packages={
            KEY: DepartmentSchedulingPackage(
                key=KEY,
                requirements=requirements,
                penalties=tuple(),
                teacher_workload={},
            )
        },
        warnings=tuple(),
        stats={},
        kutty_bundles=bundles,
    )
    model = cp_model.CpModel()
    variables = VariableCreator(ExtendedDataContainer(raw=raw, preprocessing=preprocessing)).create(model)

    first_slot = variables.theory.assignments["T1"]["A1"][0][0]
    second_slot = variables.theory.assignments["T2"]["B1"][0][0]
    first_room = variables.theory.room_assignments["T1"]["A1"][0][0]["A202"]
    second_room = variables.theory.room_assignments["T2"]["B1"][0][0]["A202"]
    assert first_slot.Index() == second_slot.Index()
    assert first_room.Index() == second_room.Index()
    assert variables.theory.course_requirements["A1"].required_slots == 2
    assert variables.theory.course_requirements["A1"].half_index == 1
    assert variables.theory.course_requirements["B1"].half_index == 2


def test_unequal_theory_loads_pair_common_halves_and_keep_full_slot_remainder() -> None:
    aero = _instance(
        "A1",
        "AE23333",
        "T1",
        lecture_hours=2,
        tutorial_hours=1,
        practical_hours=2,
    )
    maths = _instance(
        "M1",
        "MA23311",
        "T2",
        lecture_hours=3,
        tutorial_hours=1,
    )
    instances = (aero, maths)
    groups = tuple(_group(index, instance) for index, instance in enumerate(instances, start=1))
    raw = _raw_data()

    bundles, stats = KuttyBundlePlanner(raw.config.grouping).plan({KEY: instances}, {KEY: groups}, raw)

    assert stats["paired_bundles"] == 1
    assert stats["singletons"] == 0
    bundle = bundles[KEY][0]
    assert bundle.instance_ids == ("A1", "M1")
    assert bundle.required_blocks == 6
    assert bundle.first_remainder_blocks == 0
    assert bundle.second_remainder_blocks == 1

    requirements = tuple(
        GroupRequirement(
            group_id=group.group_id,
            department=KEY.department,
            semester=KEY.semester,
            has_lab=False,
            required_lab_sessions=0,
            prefer_consecutive_labs=False,
            lunch_slot_window=tuple(),
            five_pm_policy=None,
        )
        for group in groups
    )
    preprocessing = PreprocessingResult(
        normalized_instances={KEY: instances},
        groups={KEY: groups},
        scheduling_packages={
            KEY: DepartmentSchedulingPackage(
                key=KEY,
                requirements=requirements,
                penalties=tuple(),
                teacher_workload={},
            )
        },
        warnings=tuple(),
        stats={},
        kutty_bundles=bundles,
    )
    model = cp_model.CpModel()
    variables = VariableCreator(ExtendedDataContainer(raw=raw, preprocessing=preprocessing)).create(model)

    shared_aero = variables.theory.assignments["T1"]["A1"][0][0]
    shared_maths = variables.theory.assignments["T2"]["M1"][0][0]
    assert shared_aero.Index() == shared_maths.Index()
    remainder_ids = [
        component_id
        for component_id, requirement in variables.theory.course_requirements.items()
        if requirement.source_instance_id == "M1" and requirement.schedule_component == "kutty_remainder"
    ]
    assert len(remainder_ids) == 1
    remainder_id = remainder_ids[0]
    remainder = variables.theory.course_requirements[remainder_id]
    assert remainder.required_slots == 1
    assert remainder.delivery_mode == "kutty_remainder_full_slot"
    assert remainder.half_minutes == 50
    assert remainder.session_sequence_offset == 3


def test_feasible_staff_pair_is_not_dropped_for_a_large_quality_penalty() -> None:
    first = _instance("A1", "A", "T1", student_count=60)
    second = _instance("B1", "B", "T2", student_count=30_000)
    instances = (first, second)
    groups = tuple(_group(index, instance) for index, instance in enumerate(instances, start=1))
    raw = replace(
        _raw_data(),
        room_registry={"A202": {"id": "A202", "capacity": 40_000}},
    )

    bundles, stats = KuttyBundlePlanner(raw.config.grouping).plan(
        {KEY: instances},
        {KEY: groups},
        raw,
    )

    assert stats["paired_bundles"] == 1
    assert stats["singletons"] == 0
    assert bundles[KEY][0].instance_ids == ("A1", "B1")


def test_fixed_course_pair_is_applied_before_automatic_matching() -> None:
    instances = (
        _instance("A1", "A", "T1"),
        _instance("B1", "B", "T2"),
        _instance("C1", "C", "T3"),
        _instance("D1", "D", "T4"),
    )
    groups = tuple(_group(index, instance) for index, instance in enumerate(instances, start=1))
    raw = _raw_data()
    config = replace(
        raw.config.grouping,
        kutty_fixed_course_pairs={"Engineering_S3": (("A", "C"),)},
    )

    bundles, stats = KuttyBundlePlanner(config).plan({KEY: instances}, {KEY: groups}, raw)

    course_pairs = {
        frozenset(
            next(instance.course_code for instance in instances if instance.instance_id == instance_id)
            for instance_id in bundle.instance_ids
        )
        for bundle in bundles[KEY]
        if bundle.is_paired
    }
    assert course_pairs == {frozenset(("A", "C")), frozenset(("B", "D"))}
    fixed_bundle = next(
        bundle
        for bundle in bundles[KEY]
        if frozenset(bundle.instance_ids) == frozenset(("A1", "C1"))
    )
    assert "fixed_course_pair" in fixed_bundle.tags
    assert stats["singletons"] == 0


def test_fixed_course_pair_fails_fast_when_staff_matching_is_impossible() -> None:
    first = _instance("A1", "A", "T1")
    second = _instance("B1", "B", "T1")
    instances = (first, second)
    groups = tuple(_group(index, instance) for index, instance in enumerate(instances, start=1))
    raw = _raw_data()
    config = replace(
        raw.config.grouping,
        kutty_fixed_course_pairs={"Engineering|3": (("A", "B"),)},
    )

    with pytest.raises(ValueError, match="no feasible staff-offering matching"):
        KuttyBundlePlanner(config).plan({KEY: instances}, {KEY: groups}, raw)


def test_second_year_grouper_forces_one_course_code_per_group(tmp_path) -> None:
    instances = (
        _instance("A1", "A", "T1"),
        _instance("A2", "A", "T2"),
        _instance("B1", "B", "T3"),
    )
    grouper = DepartmentCourseGrouper(default_scheduler_config(), base_dir=tmp_path)
    grouped = grouper.group({KEY: instances})[KEY]
    assert [group.course_codes for group in grouped] == [("A",), ("B",)]
    assert grouped[0].course_instance_ids == ("A1", "A2")


def test_roomless_fixed_row_still_blocks_repeated_teacher(tmp_path) -> None:
    theory_csv = tmp_path / "theory.csv"
    theory_csv.write_text(
        "teacher_id,course_instance_id,day,slot_index,room_id\n"
        "T1,OLD,monday,1,\n",
        encoding="utf-8",
    )
    mask = build_schedule_blocking_mask(None, theory_csv)
    assert mask.is_theory_slot_blocked("T1", "NEW", "monday", 1)
    assert ("monday", 1, "") not in mask.blocked_theory_rooms


def test_combined_lab_courses_are_excluded_from_kutty_pairing(tmp_path) -> None:
    dbms = _instance("DBMS1", "CS23332", "T1")
    oops = _instance("OOPS1", "CS23333", "T2")
    first = _instance("A1", "A", "T3")
    second = _instance("B1", "B", "T4")
    instances = (dbms, oops, first, second)
    groups = tuple(_group(index, instance) for index, instance in enumerate(instances, start=1))
    raw = _raw_data()

    planner = KuttyBundlePlanner(
        raw.config.grouping,
        excluded_course_codes=("CS23332", "CS23333"),
    )
    bundles, stats = planner.plan({KEY: instances}, {KEY: groups}, raw)

    bundled_instance_ids = {
        instance_id
        for bundle in bundles[KEY]
        for instance_id in bundle.instance_ids
    }
    assert bundled_instance_ids == {"A1", "B1"}
    assert stats["paired_bundles"] == 1


def test_combined_lab_override_creates_four_blocks_in_only_configured_rooms(tmp_path) -> None:
    base_config = default_scheduler_config()
    config = replace(
        base_config,
        model=replace(
            base_config.model,
            combined_lab_courses={
                "course_codes": ("CS23332", "CS23333"),
                "room_numbers": ("ANEW101", "ANEW201"),
                "blocks": 4,
                "block_len": 2,
                "ignore_teacher_constraints": True,
            },
        ),
    )
    dbms = _instance("DBMS1", "CS23332", "T1")
    preprocessor = DataPreprocessor(config, base_dir=tmp_path)
    overridden = preprocessor._apply_combined_lab_overrides({KEY: (dbms,)})[KEY][0]

    assert overridden.has_lab is True
    assert overridden.has_theory is False
    assert overridden.practical_hours == 8
    assert overridden.lecture_hours == 0
    assert overridden.tutorial_hours == 0
    assert {"combined_lab", "kutty_excluded", "external_staff_proxy"}.issubset(
        overridden.tags
    )

    group = _group(1, overridden)
    requirement = GroupRequirement(
        group_id=group.group_id,
        department=KEY.department,
        semester=KEY.semester,
        has_lab=True,
        required_lab_sessions=4,
        prefer_consecutive_labs=False,
        lunch_slot_window=tuple(),
        five_pm_policy=None,
    )
    preprocessing = PreprocessingResult(
        normalized_instances={KEY: (overridden,)},
        groups={KEY: (group,)},
        scheduling_packages={
            KEY: DepartmentSchedulingPackage(
                key=KEY,
                requirements=(requirement,),
                penalties=tuple(),
                teacher_workload={},
            )
        },
        warnings=tuple(),
        stats={},
        kutty_bundles={},
    )
    raw = replace(
        _raw_data(),
        config=config,
        room_registry={
            "101": {"room_number": "ANEW101", "capacity": 165},
            "201": {"room_number": "ANEW201", "capacity": 355},
            "999": {"room_number": "OTHER", "capacity": 500},
        },
    )
    variables = VariableCreator(
        ExtendedDataContainer(raw=raw, preprocessing=preprocessing)
    ).create(cp_model.CpModel())

    assert variables.lab.requirements["DBMS1"].required_sessions == 4
    room_ids = {
        room_id
        for day_map in variables.lab.assignments["T1"]["DBMS1"].values()
        for session_map in day_map.values()
        for room_id in session_map
    }
    assert room_ids == {"101", "201"}


def test_external_delivery_ignores_fixed_teacher_but_keeps_fixed_room_block() -> None:
    mask = ScheduleBlockingMask(
        blocked_lab_teacher_sessions={("T1", "monday", "L1")},
        blocked_lab_rooms={("monday", "L1", "R1")},
    )

    assert not mask.is_lab_variable_blocked(
        teacher_id="T1",
        course_id="DBMS1",
        day_label="monday",
        session_name="L1",
        room_id="R2",
        ignore_teacher=True,
    )
    assert mask.is_lab_variable_blocked(
        teacher_id="T1",
        course_id="DBMS1",
        day_label="monday",
        session_name="L1",
        room_id="R1",
        ignore_teacher=True,
    )
