import pandas as pd
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple\

from ..config.schemas import (
    DepartmentSettings,
    SchedulerConfig,
)

@dataclass(frozen=True)
class LabSessionDetail:
    """Snapshot of a lab session window (L1–L6) in the legacy scheduler."""

    name: str
    slots: Tuple[int, ...]
    time_range: str

    @property
    def start_slot(self) -> int:
        return self.slots[0]

    @property
    def end_slot(self) -> int:
        return self.slots[-1]


@dataclass(frozen=True)
class TimeSystemArtifacts:
    """Aggregated time-system data mirroring legacy combined scheduler semantics."""

    theory_slots: Tuple[str, ...]
    lab_slots: Tuple[str, ...]
    lab_sessions: Dict[str, LabSessionDetail]
    working_days: Tuple[str, ...]
    lab_slot_to_theory: Dict[int, Tuple[int, ...]]
    theory_slot_to_lab: Dict[int, Tuple[int, ...]]
    lab_session_to_theory: Dict[str, Tuple[int, ...]]

    @property
    def num_lab_slots(self) -> int:
        return len(self.lab_slots)

    @property
    def num_theory_slots(self) -> int:
        return len(self.theory_slots)

    @property
    def num_lab_sessions(self) -> int:
        return len(self.lab_sessions)


@dataclass(frozen=True)
class ShiftDefinitionSnapshot:
    """Adapts `ShiftTemplate` into the structure used by the legacy scheduler."""

    identifier: str
    theory_slots: Tuple[int, ...]
    lab_sessions: Tuple[str, ...]
    start_time: str
    end_time: str
    label: str


@dataclass(frozen=True)
class DepartmentArtifacts:
    """Department-level defaults and overrides used downstream."""

    default_settings: DepartmentSettings
    overrides: Dict[str, DepartmentSettings]
    day_patterns: Dict[str, Tuple[str, ...]]
    lunch_break_slots: Dict[str, Optional[int]]
    lunch_slot_windows: Dict[str, Tuple[int, ...]]
    shift_assignments: Dict[str, str]
    shift_definitions: Dict[str, ShiftDefinitionSnapshot]
    valid_shift_patterns: Tuple[Tuple[int, int], ...]
    flexible_lunch_departments: Tuple[str, ...]
    five_pm_constraints: Mapping[str, Mapping[str, Any]]


@dataclass(frozen=True)
class RoomCollections:
    """Convenience grouping for room subsets needed by the scheduler."""

    lab_rooms: pd.DataFrame
    theory_rooms: pd.DataFrame
    lab_room_ids: Tuple[str, ...]
    theory_room_ids: Tuple[str, ...]
    laboratory_room_ids: Tuple[str, ...]


@dataclass(frozen=True)
class DataLoadResult:
    """Structured view of all artefacts produced during data loading."""

    config: SchedulerConfig
    courses_df: pd.DataFrame
    rooms_df: pd.DataFrame
    day_order_df: Optional[pd.DataFrame]
    core_lab_mapping_df: Optional[pd.DataFrame]
    teacher_preferences_df: Optional[pd.DataFrame]
    time: TimeSystemArtifacts
    departments: DepartmentArtifacts
    rooms: RoomCollections
    teachers: Tuple[str, ...]
    departments_list: Tuple[str, ...]
    room_registry: Dict[str, Dict[str, Any]]
    load_timestamp: datetime

    def to_legacy_dict(self) -> Dict[str, Any]:
        """Provide a dict closely matching the combined scheduler runtime state."""

        time = self.time
        departments = self.departments
        rooms = self.rooms

        lab_sessions_payload = {
            name: {"slots": detail.slots, "time_range": detail.time_range}
            for name, detail in time.lab_sessions.items()
        }

        shift_payload = {
            identifier: {
                "name": snapshot.label,
                "theory_slots": snapshot.theory_slots,
                "lab_sessions": snapshot.lab_sessions,
                "start_time": snapshot.start_time,
                "end_time": snapshot.end_time,
            }
            for identifier, snapshot in departments.shift_definitions.items()
        }

        shift_departments = {
            dept: {
                "enabled": True,
                "shift_id": shift_id,
                "description": f"Department assigned to {shift_id}",
            }
            for dept, shift_id in departments.shift_assignments.items()
        }

        return {
            "courses_df": self.courses_df,
            "rooms_df": self.rooms_df,
            "day_order_df": self.day_order_df,
            "lab_time_slots": time.lab_slots,
            "num_lab_slots": time.num_lab_slots,
            "lab_sessions": lab_sessions_payload,
            "lab_sessions_details": lab_sessions_payload,
            "num_lab_sessions": time.num_lab_sessions,
            "theory_time_slots": time.theory_slots,
            "num_theory_slots": time.num_theory_slots,
            "lab_to_theory_mapping": time.lab_slot_to_theory,
            "theory_to_lab_mapping": time.theory_slot_to_lab,
            "lab_session_to_theory_mapping": time.lab_session_to_theory,
            "shift_definitions": shift_payload,
            "valid_shift_patterns": departments.valid_shift_patterns,
            "shift_departments": shift_departments,
            "lunch_slot_windows": departments.lunch_slot_windows,
            "flexible_lunch_departments": departments.flexible_lunch_departments,
            "five_pm_constraints": departments.five_pm_constraints,
            "lab_rooms": rooms.lab_rooms,
            "theory_rooms": rooms.theory_rooms,
            "lab_room_ids": rooms.lab_room_ids,
            "theory_room_ids": rooms.theory_room_ids,
            "laboratory_room_ids": rooms.laboratory_room_ids,
            "teachers": self.teachers,
            "departments": self.departments_list,
            "room_registry": self.room_registry,
            "core_lab_mapping_df": self.core_lab_mapping_df,
            "teacher_preferences_df": self.teacher_preferences_df,
            "working_days": time.working_days,
            "num_days": len(time.working_days),
            "horizon": len(time.working_days) * time.num_theory_slots,
            "load_timestamp": self.load_timestamp.isoformat(timespec="seconds"),
        }
