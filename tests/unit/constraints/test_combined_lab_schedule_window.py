from __future__ import annotations

from types import SimpleNamespace

from ortools.sat.python import cp_model

from src.constraints.base import ConstraintMetadata
from src.constraints.cross_system.combined_lab import CombinedLabConstraint


def _context(model, assignments, requirements, day_patterns):
    return SimpleNamespace(
        model=model,
        config=SimpleNamespace(
            model=SimpleNamespace(
                combined_lab_courses={
                    "course_codes": ["CS23332"],
                    "blocks": 4,
                    "block_len": 2,
                },
                objective_weights={},
            )
        ),
        data=SimpleNamespace(raw=SimpleNamespace(room_registry={})),
        variables=SimpleNamespace(
            lab=SimpleNamespace(
                assignments=assignments,
                requirements=requirements,
                day_patterns=day_patterns,
            )
        ),
        extra={},
    )


def _constraint(**params):
    metadata = ConstraintMetadata(
        id="combined_lab",
        name="Combined Lab",
        category="cross_system",
        priority=3,
    )
    return CombinedLabConstraint(metadata=metadata, params=params)


def test_l3_is_hard_blocked_for_combined_courses():
    model = cp_model.CpModel()
    l1 = model.NewBoolVar("l1")
    l3 = model.NewBoolVar("l3")
    assignments = {"t1": {"cse": {0: {"L1": {"r": l1}, "L3": {"r": l3}}}}}
    requirements = {
        "cse": SimpleNamespace(course_code="CS23332", department="Computer Science and Engineering")
    }
    context = _context(model, assignments, requirements, {"cse": ("monday",)})

    _constraint(enforce_stable_pairing=False, blocked_sessions=["L3"]).apply(context)
    model.Maximize(l3)

    solver = cp_model.CpSolver()
    assert solver.Solve(model) == cp_model.OPTIMAL
    assert solver.Value(l3) == 0


def test_cross_department_pairing_matches_actual_day_names():
    model = cp_model.CpModel()
    cse_vars = [model.NewBoolVar(f"cse_{index}") for index in range(5)]
    aids_vars = [model.NewBoolVar(f"aids_{index}") for index in range(5)]
    assignments = {
        "t1": {"cse": {index: {"L1": {"r": var}} for index, var in enumerate(cse_vars)}},
        "t2": {"aids": {index: {"L1": {"r": var}} for index, var in enumerate(aids_vars)}},
    }
    requirements = {
        "cse": SimpleNamespace(course_code="CS23332", department="Computer Science and Engineering"),
        "aids": SimpleNamespace(course_code="CS23332", department="Artificial Intelligence and Data Science"),
    }
    context = _context(
        model,
        assignments,
        requirements,
        {
            "cse": ("monday", "tuesday", "wed", "thur", "fri"),
            "aids": ("tuesday", "wed", "thur", "fri", "saturday"),
        },
    )

    _constraint(enforce_stable_pairing=True, solo_penalty_weight=1000).apply(context)
    # Both sections meet on Tuesday, which is index 1 for CSE but index 0 for A.I.D.S.
    for index, var in enumerate(cse_vars):
        model.Add(var == (1 if index == 1 else 0))
    for index, var in enumerate(aids_vars):
        model.Add(var == (1 if index == 0 else 0))
    solo_vars = [entry[1] for entry in context.extra["objective"]["penalties"]]
    model.Add(sum(solo_vars) == 0)

    solver = cp_model.CpSolver()
    assert solver.Solve(model) == cp_model.OPTIMAL


def test_three_sections_can_form_one_stable_group_for_ks02_capacity():
    model = cp_model.CpModel()
    section_vars = [model.NewBoolVar(f"section_{index}") for index in range(3)]
    assignments = {
        f"t{index}": {f"section_{index}": {0: {"L1": {"ks02": variable}}}}
        for index, variable in enumerate(section_vars)
    }
    requirements = {
        f"section_{index}": SimpleNamespace(
            course_code="CS23332",
            department="Computer Science and Engineering",
        )
        for index in range(3)
    }
    context = _context(
        model,
        assignments,
        requirements,
        {f"section_{index}": ("monday",) for index in range(3)},
    )

    _constraint(
        enforce_stable_pairing=True,
        max_stable_group_size=3,
        solo_penalty_weight=1000,
    ).apply(context)
    for variable in section_vars:
        model.Add(variable == 1)
    solo_vars = [entry[1] for entry in context.extra["objective"]["penalties"]]
    model.Add(sum(solo_vars) == 0)

    solver = cp_model.CpSolver()
    assert solver.Solve(model) == cp_model.OPTIMAL
