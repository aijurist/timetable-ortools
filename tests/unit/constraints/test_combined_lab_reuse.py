from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from ortools.sat.python import cp_model

from src.constraints.cross_system.combined_lab_reuse import (
    annotate_stable_combined_entries,
    bind_stable_prior_footprints,
    collect_footprint_groups,
)


FAMILIES = {"CS23332": "DBMS", "CB23333": "DBMS", "CS23333": "OOPS"}
FOOTPRINT = (
    ("ANEW101", "monday", "L1"),
    ("ANEW101", "tuesday", "L1"),
    ("ANEW101", "wed", "L1"),
    ("ANEW101", "thur", "L1"),
)


@dataclass(frozen=True)
class _Entry:
    course_code: str
    course_instance_id: str
    department: str
    room_number: str
    day: str
    session_name: str
    teacher_id: str
    teacher_name: str
    tags: tuple[str, ...] = ()
    is_co_scheduled: bool = False
    co_schedule_id: str | None = None
    co_schedule_group_size: int = 1
    co_schedule_partner_teachers: str | None = None
    co_schedule_info: str | None = None


def _prior_entries(code: str = "CS23333") -> list[_Entry]:
    return [
        _Entry(
            course_code=code,
            course_instance_id="aids_section_1",
            department="Artificial Intelligence & Data Science",
            room_number=room,
            day=day,
            session_name=session,
            teacher_id="T-AIDS",
            teacher_name="AIDS Trainer",
        )
        for room, day, session in FOOTPRINT
    ]


def _lab_block(model: cp_model.CpModel):
    variables = {}
    day_map = {}
    for day_index, (_room, _day, session) in enumerate(FOOTPRINT):
        variable = model.NewBoolVar(f"prior_cell_{day_index}")
        variables[FOOTPRINT[day_index]] = variable
        day_map[day_index] = {session: {"R1": variable}}
    new_variables = []
    for day_index in range(4):
        variable = model.NewBoolVar(f"new_cell_{day_index}")
        new_variables.append(variable)
        day_map[day_index]["L4"] = {"R1": variable}
    block = SimpleNamespace(
        assignments={"T-CSE": {"cse_section_1": day_map}},
        requirements={
            "cse_section_1": SimpleNamespace(course_code="CS23333", required_sessions=4)
        },
        day_patterns={"cse_section_1": ("monday", "tuesday", "wed", "thur")},
    )
    return block, variables, new_variables


def test_touching_one_prior_cell_forces_the_complete_stable_footprint() -> None:
    model = cp_model.CpModel()
    block, prior_variables, new_variables = _lab_block(model)
    groups = collect_footprint_groups(_prior_entries(), FAMILIES)
    result = bind_stable_prior_footprints(
        model=model,
        lab_block=block,
        prior_groups=groups,
        family_by_code=FAMILIES,
        room_number_by_id={"R1": "ANEW101"},
        cell_occupancy={cell: 1 for cell in FOOTPRINT},
        max_share=lambda _room: 2,
    )
    model.Add(sum([*prior_variables.values(), *new_variables]) == 4)
    model.Add(prior_variables[FOOTPRINT[0]] == 1)

    solver = cp_model.CpSolver()
    assert solver.Solve(model) in (cp_model.FEASIBLE, cp_model.OPTIMAL)
    assert result.candidate_bindings == 1
    assert solver.Value(result.bindings[0].literal) == 1
    assert all(solver.Value(variable) == 1 for variable in prior_variables.values())
    assert all(solver.Value(variable) == 0 for variable in new_variables)


def test_full_prior_room_blocks_reuse_but_allows_a_new_footprint() -> None:
    model = cp_model.CpModel()
    block, prior_variables, new_variables = _lab_block(model)
    groups = collect_footprint_groups(_prior_entries(), FAMILIES)
    result = bind_stable_prior_footprints(
        model=model,
        lab_block=block,
        prior_groups=groups,
        family_by_code=FAMILIES,
        room_number_by_id={"R1": "ANEW101"},
        cell_occupancy={cell: 2 for cell in FOOTPRINT},
        max_share=lambda _room: 2,
    )
    model.Add(sum([*prior_variables.values(), *new_variables]) == 4)

    solver = cp_model.CpSolver()
    assert solver.Solve(model) in (cp_model.FEASIBLE, cp_model.OPTIMAL)
    assert result.candidate_bindings == 0
    assert all(solver.Value(variable) == 0 for variable in prior_variables.values())
    assert all(solver.Value(variable) == 1 for variable in new_variables)


def test_output_metadata_uses_one_id_for_the_whole_footprint() -> None:
    entries = _prior_entries("CS23332")
    entries.extend(
        _Entry(
            course_code="CB23333",
            course_instance_id="csbs_section_1",
            department="Computer Science & Business Systems",
            room_number=room,
            day=day,
            session_name=session,
            teacher_id="T-CSBS",
            teacher_name="CSBS Trainer",
        )
        for room, day, session in FOOTPRINT
    )

    annotated = annotate_stable_combined_entries(entries, FAMILIES)

    assert len({entry.co_schedule_id for entry in annotated}) == 1
    assert all(entry.is_co_scheduled for entry in annotated)
    assert all(entry.co_schedule_group_size == 2 for entry in annotated)
    assert all("stable_combined_reuse" in entry.tags for entry in annotated)
