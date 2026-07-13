from __future__ import annotations

from dataclasses import replace

import pandas as pd

from src.config.defaults import default_scheduler_config
from src.data.combined_lab_preallocation import CombinedLabPreallocator
from src.data.schemas import (
    DepartmentSemesterKey,
    LabSessionDetail,
    NormalizedCourseInstance,
    RoomCollections,
    TimeSystemArtifacts,
)
from tests.unit.runtime.runtime_test_helpers import build_extended_container


ROOMS = ("ANEW101", "ANEW102", "ANEW103", "ANEW104", "ANEW201", "ANEW202")
DAYS = ("monday", "tuesday", "wednesday", "thursday")


def _instance(instance_id: str, course_code: str, department: str, teacher_id: str) -> NormalizedCourseInstance:
    return NormalizedCourseInstance(
        instance_id=instance_id,
        course_id=instance_id,
        course_code=course_code,
        course_name=course_code,
        course_type="lab",
        semester=3,
        student_dept=department,
        course_dept="External Delivery",
        teacher_id=teacher_id,
        teacher_name=teacher_id,
        assistant_teacher_id=None,
        assistant_teacher_name=None,
        has_lab=True,
        has_theory=False,
        lecture_hours=0,
        tutorial_hours=0,
        practical_hours=8,
        student_count=60,
        requires_special_scheduling=False,
        requires_assistant=False,
        preferred_lab_type="Core-Lab",
        preferred_room_type=None,
        required_room_type="Core-Lab",
        pe_flag=False,
        tags=("combined_lab", "external_staff_proxy"),
    )


def test_preallocator_pairs_across_departments_and_caps_each_course_to_four_slots() -> None:
    base = default_scheduler_config()
    cross_system = dict(base.constraints.cross_system)
    cross_system["lunch_alignment"] = replace(
        cross_system["lunch_alignment"],
        enabled=True,
        params={
            "lunch_slot_window": (1, 2, 3),
            "minimum_free_slots": 1,
            "soft_departments": (),
            "flexible_departments": (),
        },
    )
    config = replace(
        base,
        model=replace(
            base.model,
            combined_lab_courses={
                "course_codes": ("CS23332", "CS23333"),
                "room_numbers": ROOMS,
                "blocks": 4,
                "preallocate_slots": True,
                "max_unique_slots_per_course": 4,
                "preallocation_time_limit_sec": 10,
                "preallocation_workers": 1,
                "preallocation_seed": 23,
            },
        ),
        constraints=replace(base.constraints, cross_system=cross_system),
    )

    raw = build_extended_container().raw
    time = TimeSystemArtifacts(
        theory_slots=("T0", "T1", "T2", "T3"),
        lab_slots=("S0", "S1", "S2", "S3", "S4", "S5"),
        lab_sessions={
            "L1": LabSessionDetail("L1", (0, 1), "08:00-09:40"),
            "L2": LabSessionDetail("L2", (2, 3), "10:00-11:40"),
            "L3": LabSessionDetail("L3", (4, 5), "11:40-13:20"),
        },
        working_days=DAYS,
        lab_slot_to_theory={},
        theory_slot_to_lab={},
        lab_session_to_theory={"L1": (0,), "L2": (1,), "L3": (1, 2, 3)},
    )
    departments = replace(
        raw.departments,
        day_patterns={"__default__": DAYS, "Dept A": DAYS, "Dept B": DAYS},
        lunch_slot_windows={"__default__": (1, 2, 3), "Dept A": (1, 2, 3), "Dept B": (1, 2, 3)},
        flexible_lunch_departments=tuple(),
    )
    room_rows = [
        {"id": f"R{index}", "room_number": room, "block": "ANEW", "capacity": 200}
        for index, room in enumerate(ROOMS, start=1)
    ]
    rooms_df = pd.DataFrame(room_rows)
    room_ids = tuple(row["id"] for row in room_rows)
    rooms = RoomCollections(
        lab_rooms=rooms_df,
        theory_rooms=rooms_df,
        lab_room_ids=room_ids,
        theory_room_ids=room_ids,
        laboratory_room_ids=room_ids,
    )
    data = replace(
        raw,
        config=config,
        time=time,
        departments=departments,
        rooms_df=rooms_df,
        rooms=rooms,
        room_registry={row["id"]: row for row in room_rows},
    )

    normalized = {}
    for department in ("Dept A", "Dept B"):
        instances = []
        for course_code in ("CS23332", "CS23333"):
            for ordinal in range(3):
                instances.append(
                    _instance(
                        f"{course_code}_{department[-1]}_{ordinal}",
                        course_code,
                        department,
                        f"T_{course_code}_{department[-1]}_{ordinal}",
                    )
                )
        normalized[DepartmentSemesterKey(department, 3)] = tuple(instances)

    allocations, stats = CombinedLabPreallocator(config).plan(normalized, data)

    assert len(allocations) == 6
    assert all(len(allocation.instance_ids) == 2 for allocation in allocations)
    assert all(allocation.departments == ("Dept A", "Dept B") for allocation in allocations)
    assert all(len(allocation.cells) == 4 for allocation in allocations)
    assert stats["unique_slots_by_course"] == {"CS23332": 4, "CS23333": 4}
    assert all(count <= 4 for count in stats["unique_slots_by_course"].values())
    assert all(cell.session_name != "L3" for allocation in allocations for cell in allocation.cells)
