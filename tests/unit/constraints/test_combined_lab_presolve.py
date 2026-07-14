from __future__ import annotations

from collections import Counter, defaultdict

from src.constraints.cross_system.combined_lab_presolve import (
    PreallocationInstance,
    build_maximal_section_groups,
    solve_combined_preallocation,
)


MF = ("monday", "tuesday", "wed", "thur", "fri")
TS = ("tuesday", "wed", "thur", "fri", "saturday")
SESSIONS = ("L1", "L2", "L4", "L5")


def _cells(rooms, days):
    return tuple((room, day, session) for room in rooms for day in days for session in SESSIONS)


def _instance(index, family, pattern, rooms, *, required=4, department="dept"):
    return PreallocationInstance(
        department_key=department,
        instance_id=f"{family}_{index}",
        family=family,
        course_code="CS23332" if family == "DBMS" else "CS23333",
        teacher_id=f"teacher_{index}",
        section_key=(department, str(index)),
        day_pattern=pattern,
        required_sessions=required,
        allowed_cells=_cells(rooms, pattern),
    )


def test_grouping_maximizes_six_ks02_triples_then_pairs():
    capacities = {"PAIR_A": 2, "PAIR_B": 2, "KS02": 3}
    instances = [
        *[_instance(index, "DBMS", MF, capacities) for index in range(16)],
        *[_instance(100 + index, "DBMS", TS, capacities) for index in range(18)],
    ]

    groups = build_maximal_section_groups(instances, capacities)

    assert Counter(group.size for group in groups) == {3: 6, 2: 8}
    assert all(len(group.allowed_cells) >= 4 for group in groups)


def test_oops_odd_section_count_keeps_only_one_singleton():
    capacities = {"OOPS_A": 2, "OOPS_B": 2, "OOPS_C": 2}
    instances = [
        *[_instance(index, "OOPS", MF, capacities) for index in range(15)],
        *[_instance(100 + index, "OOPS", TS, capacities) for index in range(18)],
    ]

    groups = build_maximal_section_groups(instances, capacities)

    assert Counter(group.size for group in groups) == {2: 16, 1: 1}


def test_presolve_locks_stable_footprints_and_prevents_section_overlap():
    capacities = {"DBMS_ROOM": 2, "OOPS_ROOM": 2}
    days = ("monday", "tuesday")
    dbms = [
        _instance(index, "DBMS", days, ("DBMS_ROOM",), required=2)
        for index in range(2)
    ]
    oops = [
        _instance(index, "OOPS", days, ("OOPS_ROOM",), required=2)
        for index in range(2)
    ]
    groups = build_maximal_section_groups((*dbms, *oops), capacities)

    plan = solve_combined_preallocation(
        groups=groups,
        room_capacities=capacities,
        time_limit_seconds=10,
        workers=1,
    )

    assert plan.status in {"OPTIMAL", "FEASIBLE"}
    group_footprints = defaultdict(set)
    section_times = defaultdict(set)
    section_days = defaultdict(Counter)
    for group in plan.groups:
        for member in group.members:
            footprint = plan.assignments[member.key]
            group_footprints[group.group_id].add(footprint)
            for _room, day, session in footprint:
                time = (day, session)
                assert time not in section_times[member.section_key]
                section_times[member.section_key].add(time)
                section_days[member.section_key][day] += 1
    assert all(len(footprints) == 1 for footprints in group_footprints.values())
    assert all(max(day_counts.values()) <= 2 for day_counts in section_days.values())
    selected_footprints = [next(iter(footprints)) for footprints in group_footprints.values()]
    for index, first in enumerate(selected_footprints):
        for second in selected_footprints[index + 1 :]:
            assert not (set(first) & set(second)) or first == second


def test_preferred_local_pairs_survive_global_triple_packing():
    capacities = {"KS02": 3}
    instances = [
        *[_instance(index, "DBMS", MF, capacities, department="dept_a") for index in range(4)],
        _instance(0, "DBMS", MF, capacities, department="dept_b"),
    ]

    groups = build_maximal_section_groups(
        instances,
        capacities,
        preferred_clusters={
            ("dept_a", "DBMS"): (("0", "2"), ("1", "3")),
        },
    )

    member_sets = [
        {(member.department_key, member.section_key[1]) for member in group.members}
        for group in groups
    ]
    assert any({("dept_a", "0"), ("dept_a", "2")} <= members for members in member_sets)
    assert any({("dept_a", "1"), ("dept_a", "3")} <= members for members in member_sets)
    assert Counter(group.size for group in groups) == {3: 1, 2: 1}
