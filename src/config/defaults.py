"""Default configuration factory for the modular timetable scheduler."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Mapping, Sequence, Tuple

from .schemas import (
    ConstraintConfig,
    ConstraintSetting,
    DataSourceConfig,
    DepartmentConfig,
    DepartmentSettings,
    GroupingConfig,
    LoggingConfig,
    MetaConfig,
    ModelConfig,
    PathConfig,
    PreprocessingConfig,
    RuntimeConfig,
    SchedulerConfig,
    ShiftTemplate,
    TimeSystemConfig,
    ValidationConfig,
    WarmStartConfig,
)



DEFAULT_THEORY_SLOTS: Tuple[str, ...] = (
    "8:00 - 8:50", "9:00 - 9:50", "10:00 - 10:50", "11:00 - 11:50",
    "12:00 - 12:50", "1:00 - 1:50", "2:00 - 2:50", "3:00 - 3:50", 
    "4:00 - 4:50", "5:00 - 5:50", "6:00 - 6:50"
)

DEFAULT_LUNCH_SLOT_WINDOW: Tuple[int, ...] = (3, 4, 5, 6)

DEFAULT_LAB_SLOTS: Tuple[str, ...] = (
    "8:00 - 8:50", "8:50 - 9:40", "9:50 - 10:40", "10:40 - 11:30",
    "11:50 - 12:40", "12:40 - 1:30", "1:50 - 2:40", "2:40 - 3:30", 
    "3:50 - 4:40", "4:40 - 5:30", "5:30 - 6:20", "6:20 - 7:10"
)

DEFAULT_LAB_SESSIONS: Mapping[str, Tuple[int, int]] = {
    "L1": (0, 1),
    "L2": (2, 3),
    "L3": (4, 5),
    "L4": (6, 7),
    "L5": (8, 9),
    "L6": (10, 11),
}

DEFAULT_WORKING_DAYS: Tuple[str, ...] = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
)


SHIFT_TEMPLATES: Mapping[str, ShiftTemplate] = {
    "SHIFT_1": ShiftTemplate(
        theory_slots=tuple(range(0, 7)),
        lab_sessions=("L1", "L2", "L3", "L4"),
        label="Shift 1 (08:00-15:00)",
    ),
    "SHIFT_2": ShiftTemplate(
        theory_slots=tuple(range(2, 9)),
        lab_sessions=("L2", "L3", "L4", "L5"),
        label="Shift 2 (10:00-17:00)",
    ),
}


DEPARTMENT_OVERRIDES: Mapping[str, DepartmentSettings] = {
    "Computer Science & Engineering": DepartmentSettings(
        day_pattern=DEFAULT_WORKING_DAYS,
        lunch_break_slot=None,
        lunch_slot_window=DEFAULT_LUNCH_SLOT_WINDOW,
        shift_id="SHIFT_1",
        flexible_lunch=False,
    ),
    "Computer Science & Engineering (Cyber Security)": DepartmentSettings(
        day_pattern=DEFAULT_WORKING_DAYS,
        lunch_break_slot=None,
        lunch_slot_window=DEFAULT_LUNCH_SLOT_WINDOW,
        shift_id="SHIFT_1",
        flexible_lunch=False,
    ),
    "Electronics & Communication Engineering": DepartmentSettings(
        day_pattern=DEFAULT_WORKING_DAYS,
        lunch_break_slot=None,
        lunch_slot_window=DEFAULT_LUNCH_SLOT_WINDOW,
        shift_id="SHIFT_2",
        flexible_lunch=False,
    ),
    "Electrical & Electronics Engineering": DepartmentSettings(
        day_pattern=DEFAULT_WORKING_DAYS,
        lunch_break_slot=None,
        lunch_slot_window=DEFAULT_LUNCH_SLOT_WINDOW,
        shift_id="SHIFT_2",
        flexible_lunch=False,
    ),
    "Information Technology": DepartmentSettings(
        day_pattern=DEFAULT_WORKING_DAYS,
        lunch_break_slot=None,
        lunch_slot_window=DEFAULT_LUNCH_SLOT_WINDOW,
        shift_id="SHIFT_1",
        flexible_lunch=False,
    ),
    "Mechanical Engineering": DepartmentSettings(
        day_pattern=DEFAULT_WORKING_DAYS,
        lunch_break_slot=None,
        lunch_slot_window=DEFAULT_LUNCH_SLOT_WINDOW,
        shift_id="SHIFT_1",
        flexible_lunch=False,
    ),
    "Civil Engineering": DepartmentSettings(
        day_pattern=DEFAULT_WORKING_DAYS,
        lunch_break_slot=None,
        lunch_slot_window=DEFAULT_LUNCH_SLOT_WINDOW,
        shift_id="SHIFT_2",
        flexible_lunch=False,
    ),
    "Artificial Intelligence & Data Science": DepartmentSettings(
        day_pattern=DEFAULT_WORKING_DAYS,
        lunch_break_slot=None,
        lunch_slot_window=DEFAULT_LUNCH_SLOT_WINDOW,
        shift_id="SHIFT_2",
        flexible_lunch=False,
    ),
    "Artificial Intelligence & Machine Learning": DepartmentSettings(
        day_pattern=DEFAULT_WORKING_DAYS,
        lunch_break_slot=None,
        lunch_slot_window=DEFAULT_LUNCH_SLOT_WINDOW,
        shift_id="SHIFT_2",
        flexible_lunch=False,
    ),
    "Computer Science & Business Systems": DepartmentSettings(
        day_pattern=DEFAULT_WORKING_DAYS,
        lunch_break_slot=None,
        lunch_slot_window=DEFAULT_LUNCH_SLOT_WINDOW,
        shift_id="SHIFT_1",
        flexible_lunch=False,
    ),
    "Computer Science & Design": DepartmentSettings(
        day_pattern=DEFAULT_WORKING_DAYS,
        lunch_break_slot=None,
        lunch_slot_window=DEFAULT_LUNCH_SLOT_WINDOW,
        shift_id="SHIFT_1",
        flexible_lunch=False,
    ),
    "Robotics & Automation": DepartmentSettings(
        day_pattern=DEFAULT_WORKING_DAYS,
        lunch_break_slot=None,
        lunch_slot_window=DEFAULT_LUNCH_SLOT_WINDOW,
        shift_id="SHIFT_2",
        flexible_lunch=False,
    ),
    "Automobile Engineering": DepartmentSettings(
        day_pattern=DEFAULT_WORKING_DAYS,
        lunch_break_slot=None,
        lunch_slot_window=DEFAULT_LUNCH_SLOT_WINDOW,
        shift_id="SHIFT_1",
        flexible_lunch=False,
    ),
    "Aeronautical Engineering": DepartmentSettings(
        day_pattern=DEFAULT_WORKING_DAYS,
        lunch_break_slot=None,
        lunch_slot_window=DEFAULT_LUNCH_SLOT_WINDOW,
        shift_id="SHIFT_2",
        flexible_lunch=False,
    ),
    "Biotechnology": DepartmentSettings(
        day_pattern=DEFAULT_WORKING_DAYS,
        lunch_break_slot=None,
        lunch_slot_window=DEFAULT_LUNCH_SLOT_WINDOW,
        shift_id="SHIFT_2",
        flexible_lunch=False,
    ),
    "Food Technology": DepartmentSettings(
        day_pattern=DEFAULT_WORKING_DAYS,
        lunch_break_slot=None,
        lunch_slot_window=DEFAULT_LUNCH_SLOT_WINDOW,
        shift_id="SHIFT_2",
        flexible_lunch=False,
    ),
    "Chemical Engineering": DepartmentSettings(
        day_pattern=DEFAULT_WORKING_DAYS,
        lunch_break_slot=None,
        lunch_slot_window=DEFAULT_LUNCH_SLOT_WINDOW,
        shift_id="SHIFT_1",
        flexible_lunch=False,
    ),
    "Biomedical Engineering": DepartmentSettings(
        day_pattern=DEFAULT_WORKING_DAYS,
        lunch_break_slot=None,
        lunch_slot_window=DEFAULT_LUNCH_SLOT_WINDOW,
        shift_id="SHIFT_2",
        flexible_lunch=False,
    ),
    "Mechatronics Engineering": DepartmentSettings(
        day_pattern=DEFAULT_WORKING_DAYS,
        lunch_break_slot=None,
        lunch_slot_window=DEFAULT_LUNCH_SLOT_WINDOW,
        shift_id="SHIFT_1",
        flexible_lunch=False,
    ),
}

FLEXIBLE_LUNCH_DEPARTMENTS: Tuple[str, ...] = (
    "Master of Business Administration",
)


HARD_5PM_DEPARTMENTS: Tuple[str, ...] = (
    "Artificial Intelligence & Data Science",
    "Artificial Intelligence & Machine Learning_S3",
    "Artificial Intelligence & Machine Learning_S5",
    "Artificial Intelligence & Machine Learning_S7",
    "Computer Science & Business Systems",
    "Computer Science & Engineering (Cyber Security)",
    "Information Technology",
    "Chemical Engineering_S5",
    "Chemical Engineering_S3",
    "Civil Engineering",
    "Robotics & Automation",
    "Automobile Engineering",
    "Mechatronics Engineering_S3",
    "Mechatronics Engineering_S5",
    "Mechatronics Engineering_S7",
    "Aeronautical Engineering_S3",
    "Aeronautical Engineering_S5",
    "Aeronautical Engineering_S7",
    "Computer Science & Design_S3",
    "Computer Science & Design_S5",
    "Computer Science & Design_S7",
    "Computer Science & Engineering_S5",
    "Computer Science & Engineering_S7",
    "Food Technology_S3",
    "Food Technology_S5",
    "Food Technology_S7",
    "Biotechnology_S3",
    "Biotechnology_S5",
    "Biotechnology_S7",
    "Mechanical Engineering_S3",
    "Mechanical Engineering_S5",
    "Mechanical Engineering_S7",
    "Electrical & Electronics Engineering_S3",
    "Electrical & Electronics Engineering_S7",
    "Biomedical Engineering_S3",
    "Biomedical Engineering_S5",
    "Biomedical Engineering_S7",
    "Electronics & Communication Engineering_S7",
    "Chemical Engineering_S7",
)

SOFT_5PM_DEPARTMENTS: Tuple[str, ...] = (
    "Computer Science & Engineering_S3",
    "Electronics & Communication Engineering_S3",
    "Electronics & Communication Engineering_S5",
    "Electrical & Electronics Engineering_S5",
)

FIVE_PM_CONSTRAINTS: Mapping[str, Mapping[str, Sequence[str] | Sequence[int]]] = {
    "hard": {
        "departments": HARD_5PM_DEPARTMENTS,
        "blocked_theory_slots": (9, 10),
        "blocked_lab_sessions": ("L6",),
    },
    "soft": {
        "departments": SOFT_5PM_DEPARTMENTS,
        "discouraged_theory_slots": (9, 10),
        "discouraged_lab_sessions": ("L5", "L6"),
    },
}


def default_meta_config() -> MetaConfig:
    return MetaConfig(name="timetable_scheduler", version="1.0.0", environment="local")


def default_path_config() -> PathConfig:
    return PathConfig(
        courses_csv=Path("data/final.csv"),
        rooms_csv=Path("data/block_wise/techlongue.csv"),
        day_order_csv=Path("data/day_order.csv"),
        core_lab_mapping_csv=Path("data/og-final.csv"),
        preferences_csv=Path("data/pop.csv"),
        output_root=Path("output"),
    )


def default_data_source_config() -> DataSourceConfig:
    return DataSourceConfig(
        encoding="utf-8",
        delimiter=",",
        quotechar='"',
        required_columns={
            "courses": (
                "course_code",
                "course_name",
                "department",
                "semester",
                "teacher",
                "student_count",
            ),
            "rooms": ("room_number", "capacity", "block"),
        },
        optional_columns={
            "courses": (
                "teaching_dept",
                "course_type",
                "sessions_lab",
                "sessions_theory",
                "sessions_tutorial",
            ),
            "rooms": ("room_type", "equipment"),
        },
        trim_strings=True,
        fill_missing_with={"teacher": "TBD", "course_type": "elective"},
    )


def default_time_system_config() -> TimeSystemConfig:
    return TimeSystemConfig(
        theory_slots=DEFAULT_THEORY_SLOTS,
        lab_slots=DEFAULT_LAB_SLOTS,
        lab_sessions=DEFAULT_LAB_SESSIONS,
        working_days=DEFAULT_WORKING_DAYS,
    )


def default_department_config() -> DepartmentConfig:
    return DepartmentConfig(
        default_settings=DepartmentSettings(
            day_pattern=DEFAULT_WORKING_DAYS,
            lunch_break_slot=None,
            lunch_slot_window=DEFAULT_LUNCH_SLOT_WINDOW,
            shift_id="SHIFT_1",
            flexible_lunch=False,
        ),
        overrides=DEPARTMENT_OVERRIDES,
        shift_templates=SHIFT_TEMPLATES,
        flexible_lunch_departments=FLEXIBLE_LUNCH_DEPARTMENTS,
        five_pm_constraints=FIVE_PM_CONSTRAINTS,
    )


def default_preprocessing_config() -> PreprocessingConfig:
    return PreprocessingConfig(
        enable_visualizations=False,
        fill_missing_students=True,
        student_cap=120,
        normalise_teacher_names=True,
        normalise_department_names=True,
        deduplicate_courses=True,
    )


def default_grouping_config() -> GroupingConfig:
    return GroupingConfig(
        strategy="exact",
        max_groups_per_dept_sem=6,
        hall_theorem_tolerance=0.05,
        consecutive_lab_pairs=True,
        random_seed=42,
    )


def default_constraint_config() -> ConstraintConfig:
    lab_constraints = {
        "session_coverage": ConstraintSetting(priority=10, weight=1.0, enabled=True),
        "room_capacity": ConstraintSetting(priority=9, weight=1.0, enabled=True),
        "room_single_assignment": ConstraintSetting(priority=9, weight=1.0, enabled=True),
        "core_lab_mapping": ConstraintSetting(priority=8, weight=0.8, enabled=True),
        "shift_alignment": ConstraintSetting(priority=9, weight=0.9, enabled=True),
    }
    theory_constraints = {
        "course_daily_limit": ConstraintSetting(priority=9, weight=1.0, enabled=True, params={"max_daily_slots": 2}),
        "teacher_daily_limit": ConstraintSetting(priority=9, weight=1.0, enabled=True),
        "student_conflict": ConstraintSetting(priority=10, weight=1.0, enabled=True),
        "room_assignment": ConstraintSetting(priority=8, weight=0.7, enabled=True),
        "shift_alignment": ConstraintSetting(priority=8, weight=0.6, enabled=True),
    }
    cross_constraints = {
        "group_non_overlap": ConstraintSetting(priority=9, weight=1.0, enabled=True),
        "teacher_overlap": ConstraintSetting(priority=10, weight=1.0, enabled=True),
        "lunch_alignment": ConstraintSetting(priority=6, weight=0.4, enabled=True),
        "five_pm_policy": ConstraintSetting(priority=7, weight=0.5, enabled=True),
        "shift_pattern": ConstraintSetting(
            priority=8,
            weight=0.7,
            enabled=True,
            params={
                "shift_templates": ("SHIFT_1", "SHIFT_2"),
                "allowed_patterns": ((3, 2), (2, 3)),
                "penalty_weight": 12,
            },
        ),
    }
    return ConstraintConfig(
        lab=lab_constraints,
        theory=theory_constraints,
        cross_system=cross_constraints,
    )


def default_model_config() -> ModelConfig:
    return ModelConfig(
        big_m_value=1000.0,
        objective_weights={
            "lab_balance": 1.0,
            "theory_balance": 1.0,
            "teacher_spread": 0.5,
        },
        slack_penalty=1.0,
        use_sparse_variables=True,
    )


def default_warm_start_config() -> WarmStartConfig:
    return WarmStartConfig()


def default_runtime_config() -> RuntimeConfig:
    return RuntimeConfig(
        time_limit_sec=900,
        thread_count=8,
        enable_lns=True,
        enable_trace=False,
        solution_limit=None,
        stop_after_first_solution=False,
        probing_level=None,
        search_branching=None,
        restart_log_size=None,
        max_number_of_conflicts=None,
        warm_start=default_warm_start_config(),
    )


def default_logging_config() -> LoggingConfig:
    return LoggingConfig(level="INFO", log_file=Path("output/scheduler.log"), structured=False)


def default_validation_config() -> ValidationConfig:
    return ValidationConfig(
        enforce_room_capacity=True,
        enforce_teacher_continuity=True,
        max_conflicts_allowed=0,
    )


def default_scheduler_config() -> SchedulerConfig:
    return SchedulerConfig(
        meta=default_meta_config(),
        paths=default_path_config(),
        data=default_data_source_config(),
        time=default_time_system_config(),
        departments=default_department_config(),
        preprocessing=default_preprocessing_config(),
        grouping=default_grouping_config(),
        constraints=default_constraint_config(),
        model=default_model_config(),
        runtime=default_runtime_config(),
        logging=default_logging_config(),
        validation=default_validation_config(),
    )


__all__ = [
    "default_meta_config",
    "default_path_config",
    "default_data_source_config",
    "default_time_system_config",
    "default_department_config",
    "default_preprocessing_config",
    "default_grouping_config",
    "default_constraint_config",
    "default_model_config",
    "default_warm_start_config",
    "default_runtime_config",
    "default_logging_config",
    "default_validation_config",
    "default_scheduler_config",
]
