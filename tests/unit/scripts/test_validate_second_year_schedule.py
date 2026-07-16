from scripts.validate_second_year_schedule import (
    Event,
    _combined_lab_window_violations,
    _find_overlaps,
    _odd_math_singleton_violations,
    _pairing_violations,
    _reserved_lab_assignment_violations,
    _teacher_day_window_violations,
)


def test_only_combined_courses_are_rejected_from_l3():
    rows = [
        {"course_code": "CS23332", "course_instance_id": "dbms", "session_name": "L3", "day": "tuesday"},
        {"course_code": "CS23333", "course_instance_id": "oops", "session_name": "L4", "day": "tuesday"},
        {"course_code": "AE23331", "course_instance_id": "ordinary", "session_name": "L3", "day": "tuesday"},
    ]

    violations = _combined_lab_window_violations(rows)

    assert violations == ["CS23332:dbms uses blocked L3 on tuesday"]


def _theory_row(instance, code, *, paired=False, day="tuesday", teacher="10"):
    return {
        "department": "Department",
        "course_instance_id": instance,
        "course_code": code,
        "is_co_scheduled": "true" if paired else "false",
        "teacher_id": teacher,
        "day": day,
    }


def test_odd_cohort_rejects_paired_ma_course():
    rows = [
        _theory_row("a__s1", "AE23331"),
        _theory_row("b__s1", "AE23332"),
        _theory_row("maths__s1", "MA23311", paired=True),
    ]

    assert _odd_math_singleton_violations(rows) == [
        "Department/s1: odd-cohort maths MA23311:maths__s1 is Kutty-paired"
    ]


def test_even_cohort_allows_ma_course_to_pair():
    rows = [
        _theory_row("a__s1", "AE23331", paired=True),
        _theory_row("maths__s1", "MA23311", paired=True),
    ]

    assert not _odd_math_singleton_violations(rows)


def test_csbs_exception_is_checked_as_odd_math_singleton():
    rows = [
        _theory_row("a__s1", "CB23311"),
        _theory_row("b__s1", "CB23312"),
        _theory_row("statistics__s1", "CB23331", paired=True),
    ]

    assert len(_odd_math_singleton_violations(rows)) == 1


def test_teacher_day_window_includes_production_locks():
    theory = [_theory_row("a__s1", "AE23331", day="saturday", teacher="10")]
    fixed_theory = [_theory_row("senior", "AE99999", day="monday", teacher="10.0")]

    assert _teacher_day_window_violations(theory, [], fixed_theory, []) == [
        "teacher 10: ordinary schedule uses both Monday and Saturday"
    ]


def test_external_combined_course_does_not_create_teacher_window_violation():
    theory = [_theory_row("a__s1", "AE23331", day="monday", teacher="10")]
    external_lab = [_theory_row("dbms", "CS23332", day="saturday", teacher="10")]

    assert not _teacher_day_window_violations(theory, external_lab, [], [])


def test_generated_assignment_does_not_conflict_with_its_own_fixed_lock():
    generated = Event("tuesday", 700, 800, "9007", "1120__s0", "CD23321", "lab", "lab:event")
    fixed = Event("tuesday", 700, 800, "9007", "1120__s0", "CD23321", "fixed_lab", "fixed:event")

    assert not _find_overlaps([generated], [fixed])


def test_reserved_lab_assignment_requires_exact_output_and_free_department_cell():
    reservation = {
        "day": "tuesday",
        "session_name": "L3",
        "time_range": "11:40 - 1:20",
        "course_instance_id": "1120__s0",
        "teacher_id": "211",
        "room_id": "9007",
        "department": "Computer Science & Design",
    }
    generated = dict(reservation)

    assert not _reserved_lab_assignment_violations([], [generated], [reservation])

    conflicting = {
        **generated,
        "course_instance_id": "other__s0",
        "teacher_id": "999",
        "room_id": "9999",
    }
    violations = _reserved_lab_assignment_violations([], [generated, conflicting], [reservation])
    assert violations == ["1120__s0 tuesday L3: overlaps department lab other__s0"]


def test_kutty_pair_rejects_same_normalized_teacher_id():
    first = {
        "department": "Department",
        "course_instance_id": "course_a__s0",
        "course_code": "A",
        "is_co_scheduled": "true",
        "partner_instance_id": "course_b__s0",
        "teacher_id": "211",
        "day": "tuesday",
        "slot_index": "0",
        "room_number": "A101",
    }
    second = {
        **first,
        "course_instance_id": "course_b__s0",
        "course_code": "B",
        "partner_instance_id": "course_a__s0",
        "teacher_id": "211.0",
    }

    violations, _stable_pairs, _physical_sessions = _pairing_violations([first, second])

    assert any("both 25-minute halves use teacher 211" in violation for violation in violations)
