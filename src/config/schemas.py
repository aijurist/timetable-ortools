from __future__ import annotations

from collections.abc import Sequence as SequenceCollection
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple


def _to_path(value: Optional[Path | str]) -> Optional[Path]:
    if value is None:
        return None
    return value if isinstance(value, Path) else Path(value)


@dataclass(frozen=True)
class MetaConfig:
    name: str = "timetable_scheduler"
    version: str = "1.0.0"
    environment: str = "local"
    generated_at: Optional[str] = None


@dataclass(frozen=True)
class PathConfig:
    courses_csv: Path
    rooms_csv: Path
    day_order_csv: Optional[Path] = None
    core_lab_mapping_csv: Optional[Path] = None
    preferences_csv: Optional[Path] = None
    output_root: Path = Path("output")

    def __post_init__(self) -> None:
        object.__setattr__(self, "courses_csv", _to_path(self.courses_csv))
        object.__setattr__(self, "rooms_csv", _to_path(self.rooms_csv))
        object.__setattr__(self, "day_order_csv", _to_path(self.day_order_csv))
        object.__setattr__(self, "core_lab_mapping_csv", _to_path(self.core_lab_mapping_csv))
        object.__setattr__(self, "preferences_csv", _to_path(self.preferences_csv))
        object.__setattr__(self, "output_root", _to_path(self.output_root) or Path("output"))

    def resolve(self, base_dir: Optional[Path] = None) -> "PathConfig":
        base = base_dir or Path.cwd()

        def _resolve(path: Optional[Path]) -> Optional[Path]:
            if path is None:
                return None
            return path if path.is_absolute() else (base / path).resolve()

        return replace(
            self,
            courses_csv=_resolve(self.courses_csv),
            rooms_csv=_resolve(self.rooms_csv),
            day_order_csv=_resolve(self.day_order_csv),
            core_lab_mapping_csv=_resolve(self.core_lab_mapping_csv),
            preferences_csv=_resolve(self.preferences_csv),
            output_root=_resolve(self.output_root) or base / "output",
        )


@dataclass(frozen=True)
class DataSourceConfig:
    encoding: str = "utf-8"
    delimiter: str = ","
    quotechar: str = '"'
    required_columns: Mapping[str, Sequence[str]] = field(default_factory=dict)
    optional_columns: Mapping[str, Sequence[str]] = field(default_factory=dict)
    trim_strings: bool = True
    fill_missing_with: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for dataset, columns in self.required_columns.items():
            if not columns:
                raise ValueError(f"Dataset '{dataset}' must declare at least one required column")
        if len(self.delimiter) != 1:
            raise ValueError("CSV delimiter must be a single character")
        if len(self.quotechar) != 1:
            raise ValueError("CSV quotechar must be a single character")


@dataclass(frozen=True)
class ShiftTemplate:
    theory_slots: Sequence[int] = field(default_factory=tuple)
    lab_sessions: Sequence[str] = field(default_factory=tuple)
    label: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "theory_slots", tuple(self.theory_slots))
        object.__setattr__(self, "lab_sessions", tuple(self.lab_sessions))
        if any(index < 0 for index in self.theory_slots):
            raise ValueError("Shift theory slot indices must be non-negative")


@dataclass(frozen=True)
class TimeSystemConfig:
    theory_slots: Sequence[str]
    lab_slots: Sequence[str]
    lab_sessions: Mapping[str, Sequence[int]]
    working_days: Sequence[str]

    def __post_init__(self) -> None:
        if not self.theory_slots:
            raise ValueError("At least one theory slot is required")
        if not self.lab_slots:
            raise ValueError("At least one lab slot is required")
        if not self.working_days:
            raise ValueError("At least one working day is required")

        lab_slot_count = len(self.lab_slots)
        object.__setattr__(self, "theory_slots", tuple(self.theory_slots))
        object.__setattr__(self, "lab_slots", tuple(self.lab_slots))
        object.__setattr__(self, "working_days", tuple(self.working_days))

        sessions: Dict[str, Tuple[int, ...]] = {}
        for session_name, indices in self.lab_sessions.items():
            if not indices:
                raise ValueError(f"Lab session '{session_name}' must include slot indices")
            tuple_indices = tuple(indices)
            for idx in tuple_indices:
                if idx < 0 or idx >= lab_slot_count:
                    raise ValueError(
                        f"Lab session '{session_name}' index {idx} outside 0..{lab_slot_count - 1}"
                    )
            sessions[session_name] = tuple_indices
        object.__setattr__(self, "lab_sessions", sessions)


@dataclass(frozen=True)
class DepartmentSettings:
    day_pattern: Sequence[str]
    lunch_break_slot: Optional[int] = None
    lunch_slot_window: Optional[Sequence[int]] = None
    shift_id: Optional[str] = None
    flexible_lunch: bool = False

    def __post_init__(self) -> None:
        if not self.day_pattern:
            raise ValueError("Department day pattern cannot be empty")
        object.__setattr__(self, "day_pattern", tuple(self.day_pattern))
        if self.lunch_break_slot is not None and self.lunch_break_slot < 0:
            raise ValueError("Lunch break slot index cannot be negative")
        if self.lunch_slot_window is not None:
            window = tuple(self.lunch_slot_window)
            if not window:
                raise ValueError("Lunch slot window cannot be empty when provided")
            if any(slot < 0 for slot in window):
                raise ValueError("Lunch slot window entries must be non-negative")
            object.__setattr__(self, "lunch_slot_window", window)
        else:
            object.__setattr__(self, "lunch_slot_window", None)


@dataclass(frozen=True)
class DepartmentConfig:
    default_settings: DepartmentSettings
    overrides: Mapping[str, DepartmentSettings] = field(default_factory=dict)
    shift_templates: Mapping[str, ShiftTemplate] = field(default_factory=dict)
    flexible_lunch_departments: Sequence[str] = field(default_factory=tuple)
    five_pm_constraints: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "flexible_lunch_departments", tuple(self.flexible_lunch_departments))
        normalized_constraints: Dict[str, Dict[str, Any]] = {}
        for label, payload in self.five_pm_constraints.items():
            normalized_payload: Dict[str, Any] = {}
            for key, value in payload.items():
                if isinstance(value, SequenceCollection) and not isinstance(value, (str, bytes, bytearray)):
                    normalized_payload[key] = tuple(value)
                else:
                    normalized_payload[key] = value
            normalized_constraints[label] = normalized_payload
        object.__setattr__(self, "five_pm_constraints", normalized_constraints)

    def get_settings(self, department: str) -> DepartmentSettings:
        return self.overrides.get(department, self.default_settings)

    def has_shift(self, department: str) -> bool:
        settings = self.get_settings(department)
        return settings.shift_id is not None and settings.shift_id in self.shift_templates


@dataclass(frozen=True)
class PreprocessingConfig:
    enable_visualizations: bool = False
    fill_missing_students: bool = True
    student_cap: Optional[int] = 120
    normalise_teacher_names: bool = True
    normalise_department_names: bool = True
    deduplicate_courses: bool = True

    def __post_init__(self) -> None:
        if self.student_cap is not None and self.student_cap <= 0:
            raise ValueError("student_cap must be positive when provided")


@dataclass(frozen=True)
class GroupingConfig:
    strategy: str = "exact"
    max_groups_per_dept_sem: Optional[int] = None
    hall_theorem_tolerance: float = 0.05
    consecutive_lab_pairs: bool = True
    random_seed: Optional[int] = None

    def __post_init__(self) -> None:
        if self.max_groups_per_dept_sem is not None and self.max_groups_per_dept_sem <= 0:
            raise ValueError("max_groups_per_dept_sem must be positive when provided")
        if self.hall_theorem_tolerance < 0:
            raise ValueError("hall_theorem_tolerance cannot be negative")
        if self.random_seed is not None and self.random_seed < 0:
            raise ValueError("random_seed cannot be negative")


@dataclass(frozen=True)
class ConstraintSetting:
    enabled: bool = True
    priority: int = 10
    weight: float = 1.0
    params: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 1 <= self.priority <= 10:
            raise ValueError("priority must be between 1 and 10 inclusive")
        if self.weight < 0:
            raise ValueError("weight cannot be negative")


@dataclass(frozen=True)
class ConstraintConfig:
    lab: Mapping[str, ConstraintSetting] = field(default_factory=dict)
    theory: Mapping[str, ConstraintSetting] = field(default_factory=dict)
    cross_system: Mapping[str, ConstraintSetting] = field(default_factory=dict)

    def require(self, domain: str, name: str) -> ConstraintSetting:
        domain_map = {
            "lab": self.lab,
            "theory": self.theory,
            "cross_system": self.cross_system,
        }.get(domain)
        if domain_map is None:
            raise KeyError(f"Unknown constraint domain '{domain}'")
        try:
            return domain_map[name]
        except KeyError as exc:  # pragma: no cover
            raise KeyError(f"Constraint '{name}' not defined in domain '{domain}'") from exc


@dataclass(frozen=True)
class ModelConfig:
    big_m_value: float = 1000.0
    objective_weights: Mapping[str, float] = field(default_factory=dict)
    slack_penalty: float = 1.0
    use_sparse_variables: bool = True

    def __post_init__(self) -> None:
        if self.big_m_value <= 0:
            raise ValueError("big_m_value must be positive")
        if self.slack_penalty < 0:
            raise ValueError("slack_penalty cannot be negative")
        for name, weight in self.objective_weights.items():
            if weight < 0:
                raise ValueError(f"objective weight '{name}' cannot be negative")


@dataclass(frozen=True)
class RuntimeConfig:
    time_limit_sec: Optional[int] = 300
    thread_count: int = 4
    enable_lns: bool = False
    enable_trace: bool = False
    solution_limit: Optional[int] = None
    stop_after_first_solution: bool = False
    probing_level: Optional[int] = None
    search_branching: Optional[str] = None
    restart_log_size: Optional[float] = None
    max_number_of_conflicts: Optional[int] = None

    def __post_init__(self) -> None:
        if self.time_limit_sec is not None and self.time_limit_sec <= 0:
            raise ValueError("time_limit_sec must be positive when provided")
        if self.thread_count <= 0:
            raise ValueError("thread_count must be positive")
        if self.solution_limit is not None and self.solution_limit <= 0:
            raise ValueError("solution_limit must be positive when provided")
        if self.probing_level is not None and self.probing_level not in (0, 1, 2):
            raise ValueError("probing_level must be 0, 1, 2, or null for solver default")
        if self.search_branching is not None and not str(self.search_branching).strip():
            raise ValueError("search_branching cannot be empty when provided")
        if self.restart_log_size is not None and self.restart_log_size <= 0:
            raise ValueError("restart_log_size must be positive when provided")
        if self.max_number_of_conflicts is not None and self.max_number_of_conflicts <= 0:
            raise ValueError("max_number_of_conflicts must be positive when provided")


@dataclass(frozen=True)
class LoggingConfig:
    level: str = "INFO"
    log_file: Optional[Path] = None
    structured: bool = False

    def __post_init__(self) -> None:
        valid_levels = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}
        if self.level.upper() not in valid_levels:
            raise ValueError(f"Unsupported logging level '{self.level}'")
        object.__setattr__(self, "level", self.level.upper())
        object.__setattr__(self, "log_file", _to_path(self.log_file))


@dataclass(frozen=True)
class ValidationConfig:
    enforce_room_capacity: bool = True
    enforce_teacher_continuity: bool = True
    max_conflicts_allowed: int = 0

    def __post_init__(self) -> None:
        if self.max_conflicts_allowed < 0:
            raise ValueError("max_conflicts_allowed cannot be negative")


@dataclass(frozen=True)
class SchedulerConfig:
    meta: MetaConfig
    paths: PathConfig
    data: DataSourceConfig
    time: TimeSystemConfig
    departments: DepartmentConfig
    preprocessing: PreprocessingConfig
    grouping: GroupingConfig
    constraints: ConstraintConfig
    model: ModelConfig
    runtime: RuntimeConfig
    logging: LoggingConfig
    validation: ValidationConfig


__all__ = [
    "MetaConfig",
    "PathConfig",
    "DataSourceConfig",
    "ShiftTemplate",
    "TimeSystemConfig",
    "DepartmentSettings",
    "DepartmentConfig",
    "PreprocessingConfig",
    "GroupingConfig",
    "ConstraintSetting",
    "ConstraintConfig",
    "ModelConfig",
    "RuntimeConfig",
    "LoggingConfig",
    "ValidationConfig",
    "SchedulerConfig",
]
