from __future__ import annotations

from src.runtime.extractor import ScheduleExtractor
from src.runtime.extractor_schema import (
    LabScheduleEntry,
    ScheduleExtractionResult,
    TheoryScheduleEntry,
)
from src.runtime.validator import ScheduleValidator, ValidationSeverity

from tests.unit.runtime.runtime_test_helpers import (
    build_constraint_model,
    build_extended_container,
    build_solver_result,
)


def _build_conflicting_schedule() -> ScheduleExtractionResult:
    lab_entry = LabScheduleEntry(
        teacher_id="t1",
        teacher_name="Teacher One",
        course_instance_id="C1",
        course_code="CS101",
        course_name="Intro to CS",
        group_id="G1",
        department="Engineering",
        semester=3,
        day="monday",
        day_index=0,
        session_name="L1",
        session_slots=(0, 1),
        session_time="08:00-10:00",
        room_id="Lab1",
        student_count=60,
        tags=tuple(),
        is_lunch_window=False,
        five_pm_policy="hard",
        five_pm_flag=True,
    )
    conflicting_lab = LabScheduleEntry(
        teacher_id="t1",
        teacher_name="Teacher One",
        course_instance_id="C1",
        course_code="CS101",
        course_name="Intro to CS",
        group_id="G1",
        department="Engineering",
        semester=3,
        day="monday",
        day_index=0,
        session_name="L1",
        session_slots=(0, 1),
        session_time="08:00-10:00",
        room_id="Lab1",
        student_count=60,
        tags=tuple(),
        is_lunch_window=False,
        five_pm_policy="hard",
        five_pm_flag=True,
    )
    theory_entry_a = TheoryScheduleEntry(
        group_id="G2",
        department="Engineering",
        semester=3,
        day="monday",
        day_index=0,
        slot_index=0,
        slot_label="08:00-09:00",
        teacher_ids=("t1",),
        teacher_names=("Teacher One",),
        course_codes=("CS201",),
        is_lunch_window=False,
        five_pm_policy="hard",
        five_pm_flag=False,
        tags=tuple(),
    )
    theory_entry_b = TheoryScheduleEntry(
        group_id="G3",
        department="Engineering",
        semester=3,
        day="monday",
        day_index=0,
        slot_index=0,
        slot_label="08:00-09:00",
        teacher_ids=("t1",),
        teacher_names=("Teacher One",),
        course_codes=("CS301",),
        is_lunch_window=False,
        five_pm_policy="hard",
        five_pm_flag=False,
        tags=tuple(),
    )
    return ScheduleExtractionResult(
        lab_entries=(lab_entry, conflicting_lab),
        theory_entries=(theory_entry_a, theory_entry_b),
        combined_entries=tuple(),
        instance_index={},
    )


def test_validator_flags_conflicts_and_coverage() -> None:
    data = build_extended_container()
    constraint_model = build_constraint_model()
    validator = ScheduleValidator(data, constraint_model)
    schedule = _build_conflicting_schedule()

    report = validator.validate(schedule)

    categories = {issue.category for issue in report.issues}
    assert "lab_teacher_conflict" in categories
    assert "lab_room_conflict" in categories
    assert "theory_teacher_conflict" in categories
    assert "group_overlap" in categories
    assert "theory_lab_conflict" in categories
    assert "theory_coverage" in categories
    assert report.has_errors
    assert report.severity_counts[ValidationSeverity.ERROR] >= 1


def test_validator_accepts_extractor_schedule() -> None:
    data = build_extended_container()
    constraint_model = build_constraint_model()
    extractor = ScheduleExtractor(data, constraint_model)
    solver_result = build_solver_result(constraint_model.model)
    schedule = extractor.extract(solver_result)
    validator = ScheduleValidator(data, constraint_model)

    report = validator.validate(schedule)

    assert report.has_errors is False
    assert all(issue.severity != ValidationSeverity.ERROR for issue in report.issues)
