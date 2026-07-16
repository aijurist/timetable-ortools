import pytest

from src.data.teacher_day_window_plan import (
	TeacherWindowAssignment,
	build_teacher_day_window_plan,
)


MF = ("monday", "tuesday", "wed", "thur", "fri")
TS = ("tuesday", "wed", "thur", "fri", "saturday")


def test_mixed_teacher_uses_larger_workload_window() -> None:
	plan = build_teacher_day_window_plan(
		[
			TeacherWindowAssignment("10", MF, workload=3),
			TeacherWindowAssignment("10", TS, workload=5),
		]
	)

	assert plan.forced_windows["10"] == "tue_sat"
	assert plan.mixed_pattern_teachers == ("10",)


def test_mixed_teacher_tie_is_deterministically_mon_fri() -> None:
	plan = build_teacher_day_window_plan(
		[
			TeacherWindowAssignment("10", TS, workload=3),
			TeacherWindowAssignment("10", MF, workload=3),
		]
	)

	assert plan.forced_windows["10"] == "mon_fri"


def test_production_boundary_overrides_workload_choice() -> None:
	plan = build_teacher_day_window_plan(
		[
			TeacherWindowAssignment("10", MF, workload=10),
			TeacherWindowAssignment("10", TS, workload=1),
		],
		fixed_days={"10.0": ["Saturday"]},
	)

	assert plan.forced_windows["10"] == "tue_sat"
	assert plan.reasons["10"] == "production_lock"


def test_pop_boundary_is_used_when_production_has_no_boundary() -> None:
	plan = build_teacher_day_window_plan(
		[TeacherWindowAssignment("10", MF, workload=3)],
		fixed_days={"10": ["Wednesday"]},
		pop_days={"10": ["Tuesday", "Saturday"]},
	)

	assert plan.forced_windows["10"] == "tue_sat"


def test_conflicting_production_boundaries_fail_before_solving() -> None:
	with pytest.raises(ValueError, match="both Monday and Saturday"):
		build_teacher_day_window_plan(
			[TeacherWindowAssignment("10", MF)],
			fixed_days={"10": ["Monday", "Saturday"]},
		)
