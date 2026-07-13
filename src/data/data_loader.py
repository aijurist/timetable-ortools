"""Configuration-driven data loading aligned with the legacy combined scheduler."""

from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple


import pandas as pd

from ..config.schemas import (
    DepartmentConfig,
    DepartmentSettings,
    SchedulerConfig,
    ShiftTemplate,
    TimeSystemConfig,
)

# for testing purposes
from ..config.manager import ConfigManager
from pathlib import Path

from ..utils.room_utils import RoomRegistry

from .schemas import (
    LabSessionDetail,
    TimeSystemArtifacts,
    ShiftDefinitionSnapshot,
    DepartmentArtifacts,
    RoomCollections,
    DataLoadResult,
)
from .schedule_blocking import build_schedule_blocking_mask

logger = logging.getLogger(__name__)



class DataLoaderError(RuntimeError):
    """Raised when required data cannot be loaded or validated."""


class DataLoader:
    """Load data based on `SchedulerConfig`, preserving legacy semantics."""

    def __init__(self, config: SchedulerConfig, *, base_dir: Optional[Path] = None) -> None:
        self._base_dir = Path(base_dir or Path.cwd()).resolve()
        self._paths = config.paths.resolve(self._base_dir)
        self._config = config

    def load(self) -> DataLoadResult:
        """Load all scheduler artefacts and return a structured result."""

        courses_df = self._read_csv(self._paths.courses_csv, required=True, friendly_name="courses")
        rooms_df = self._read_csv(self._paths.rooms_csv, required=True, friendly_name="rooms")
        day_order_df = self._read_csv(self._paths.day_order_csv, friendly_name="day order")
        core_lab_mapping_df = self._read_csv(
            self._paths.core_lab_mapping_csv,
            friendly_name="core lab mapping",
        )
        computer_lab_mapping_df = self._read_csv(
            self._paths.computer_lab_mapping_csv,
            friendly_name="computer lab mapping",
        )
        teacher_preferences_df = self._read_csv(
            self._paths.preferences_csv,
            friendly_name="teacher preferences",
        )

        courses_df = self._normalise_courses_dataframe(courses_df)
        rooms_df = self._normalise_rooms_dataframe(rooms_df)

        time_artifacts = self._build_time_artifacts(self._config.time)
        department_artifacts = self._build_department_artifacts(self._config.departments, time_artifacts)
        room_collections = self._build_room_collections(rooms_df)
        room_registry = RoomRegistry.build_registry(rooms_df.to_dict("records"), key_field="id")

        teachers = self._extract_sorted_unique(courses_df, ["teacher", "teacher_name", "faculty"], fallback="teacher_id")
        departments = self._extract_sorted_unique(courses_df, ["department", "dept", "course_dept"])

        fixed_lab_path, fixed_theory_path = self._effective_fixed_schedule_paths()
        blocking_mask = build_schedule_blocking_mask(
            lab_csv_path=fixed_lab_path,
            theory_csv_path=fixed_theory_path,
            lab_session_to_theory_mapping=time_artifacts.lab_session_to_theory,
            day_patterns=department_artifacts.day_patterns,
            working_days=time_artifacts.working_days,
        )

        result = DataLoadResult(
            config=self._config,
            courses_df=courses_df,
            rooms_df=rooms_df,
            day_order_df=day_order_df,
            core_lab_mapping_df=core_lab_mapping_df,
            computer_lab_mapping_df=computer_lab_mapping_df,
            teacher_preferences_df=teacher_preferences_df,
            time=time_artifacts,
            departments=department_artifacts,
            rooms=room_collections,
            teachers=teachers,
            departments_list=departments,
            room_registry=room_registry,
            load_timestamp=datetime.utcnow(),
            blocking_mask=blocking_mask,
        )

        logger.info(
            "Loaded %s courses, %s rooms, %s departments, %s teachers",
            len(courses_df),
            len(rooms_df),
            len(result.departments_list),
            len(result.teachers),
        )
        return result

    def _effective_fixed_schedule_paths(self) -> Tuple[Optional[Path], Optional[Path]]:
        """Return the files used by both early pruning and the fixed lock.

        Historically variable creation only read ``paths.fixed_*`` while the
        enabled lock read paths from its constraint params.  That allowed a
        second-year staff bundle to be chosen without seeing the same staff's
        third/fourth-year occupancy.  The enabled constraint is now the source
        of truth, with the legacy path fields retained as fallbacks.
        """

        lab_path = self._paths.fixed_lab_schedule_csv
        theory_path = self._paths.fixed_theory_schedule_csv
        setting = (self._config.constraints.cross_system or {}).get("fixed_schedule_lock")
        if setting is None:
            return lab_path, theory_path
        if not getattr(setting, "enabled", False):
            return None, None

        params = getattr(setting, "params", {}) or {}
        lab_path = self._resolve_optional_path(params.get("lab_csv_path")) or lab_path
        theory_path = self._resolve_optional_path(params.get("theory_csv_path")) or theory_path
        logger.info(
            "Effective fixed schedules for blocking: lab=%s theory=%s",
            lab_path,
            theory_path,
        )
        return lab_path, theory_path

    def _resolve_optional_path(self, value: object) -> Optional[Path]:
        text = str(value or "").strip()
        if not text:
            return None
        path = Path(text)
        return path if path.is_absolute() else (self._base_dir / path).resolve()

    # ------------------------------------------------------------------
    # CSV helpers
    # ------------------------------------------------------------------
    def _read_csv(
        self,
        path: Optional[Path],
        *,
        required: bool = False,
        friendly_name: str = "dataset",
    ) -> Optional[pd.DataFrame]:
        if path is None:
            if required:
                raise DataLoaderError(f"Missing required path for {friendly_name} CSV")
            logger.debug("No path provided for optional %s CSV", friendly_name)
            return None

        try:
            df = pd.read_csv(path)
            logger.debug("Loaded %s CSV from %s (%s rows)", friendly_name, path, len(df))
            return df
        except FileNotFoundError as exc:
            if required:
                raise DataLoaderError(f"Required {friendly_name} CSV not found: {path}") from exc
            logger.warning("Optional %s CSV not found at %s", friendly_name, path)
            return None
        except Exception as exc:  # pragma: no cover - defensive logging
            message = f"Failed to load {friendly_name} CSV at {path}: {exc}"
            if required:
                raise DataLoaderError(message) from exc
            logger.warning(message)
            return None

    # ------------------------------------------------------------------
    # Normalisation helpers
    # ------------------------------------------------------------------
    def _normalise_courses_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        normalised = df.copy()
        self._ensure_primary_column(normalised, "teacher", ["Teacher", "Faculty", "Faculty Name", "faculty_name"])
        self._ensure_primary_column(normalised, "department", ["Department", "Dept", "Department Name"])
        self._ensure_primary_column(normalised, "semester", ["Semester", "Sem"])

        if "teacher" in normalised.columns and "teacher_id" in normalised.columns:
            normalised["teacher"] = normalised["teacher"].fillna(normalised["teacher_id"])

        return normalised

    def _normalise_rooms_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        normalised = df.copy()
        if "id" not in normalised.columns:
            candidate_columns = [col for col in normalised.columns if col.lower() in {"room_number", "room", "id"}]
            if candidate_columns:
                normalised["id"] = normalised[candidate_columns[0]].astype(str)
            else:
                normalised["id"] = normalised.index.to_series().apply(lambda idx: f"ROOM_{idx}")

        normalised["id"] = normalised["id"].fillna("").astype(str)
        normalised.loc[normalised["id"].eq(""), "id"] = normalised.index.astype(str)
        return normalised

    def _ensure_primary_column(self, df: pd.DataFrame, primary: str, aliases: Sequence[str]) -> None:
        if primary in df.columns:
            return
        for alias in aliases:
            if alias in df.columns:
                df.rename(columns={alias: primary}, inplace=True)
                return

    # ------------------------------------------------------------------
    # Artifact builders
    # ------------------------------------------------------------------
    def _build_time_artifacts(self, time_config: TimeSystemConfig) -> TimeSystemArtifacts:
        theory_slots = tuple(time_config.theory_slots)
        lab_slots = tuple(time_config.lab_slots)
        working_days = tuple(time_config.working_days)

        lab_sessions = {
            name: LabSessionDetail(
                name=name,
                slots=tuple(indices),
                time_range=self._derive_session_range(tuple(indices), lab_slots),
            )
            for name, indices in time_config.lab_sessions.items()
        }

        lab_slot_to_theory, theory_slot_to_lab = self._build_slot_overlap_maps(theory_slots, lab_slots)
        lab_session_to_theory = {
            name: tuple(sorted({slot for idx in detail.slots for slot in lab_slot_to_theory.get(idx, ())}))
            for name, detail in lab_sessions.items()
        }

        return TimeSystemArtifacts(
            theory_slots=theory_slots,
            lab_slots=lab_slots,
            lab_sessions=lab_sessions,
            working_days=working_days,
            lab_slot_to_theory=lab_slot_to_theory,
            theory_slot_to_lab=theory_slot_to_lab,
            lab_session_to_theory=lab_session_to_theory,
        )

    def _build_slot_overlap_maps(
        self,
        theory_slots: Sequence[str],
        lab_slots: Sequence[str],
    ) -> Tuple[Dict[int, Tuple[int, ...]], Dict[int, Tuple[int, ...]]]:
        theory_to_lab: Dict[int, Tuple[int, ...]] = {}
        lab_to_theory: Dict[int, Tuple[int, ...]] = {}

        theory_ranges = [self._parse_time_range(slot) for slot in theory_slots]
        lab_ranges = [self._parse_time_range(slot) for slot in lab_slots]

        for theory_idx, theory_range in enumerate(theory_ranges):
            overlaps = [lab_idx for lab_idx, lab_range in enumerate(lab_ranges) if self._ranges_overlap(theory_range, lab_range)]
            theory_to_lab[theory_idx] = tuple(overlaps)

        for lab_idx, lab_range in enumerate(lab_ranges):
            overlaps = [theory_idx for theory_idx, theory_range in enumerate(theory_ranges) if self._ranges_overlap(lab_range, theory_range)]
            lab_to_theory[lab_idx] = tuple(overlaps)

        return lab_to_theory, theory_to_lab

    def _build_department_artifacts(
        self,
        department_config: DepartmentConfig,
        time_artifacts: TimeSystemArtifacts,
    ) -> DepartmentArtifacts:
        default_settings = department_config.default_settings
        overrides = dict(department_config.overrides)

        day_patterns: Dict[str, Tuple[str, ...]] = {"__default__": tuple(default_settings.day_pattern)}
        lunch_break_slots: Dict[str, Optional[int]] = {"__default__": default_settings.lunch_break_slot}
        default_lunch_window = (
            tuple(default_settings.lunch_slot_window)
            if default_settings.lunch_slot_window
            else tuple()
        )
        lunch_slot_windows: Dict[str, Tuple[int, ...]] = {"__default__": default_lunch_window}
        shift_assignments: Dict[str, str] = {}

        for dept, settings in overrides.items():
            day_patterns[dept] = tuple(settings.day_pattern)
            lunch_break_slots[dept] = (
                settings.lunch_break_slot
                if settings.lunch_break_slot is not None
                else default_settings.lunch_break_slot
            )
            window = settings.lunch_slot_window if settings.lunch_slot_window is not None else default_settings.lunch_slot_window
            lunch_slot_windows[dept] = tuple(window) if window else tuple()
            if settings.shift_id:
                shift_assignments[dept] = settings.shift_id

        shift_definitions = self._build_shift_snapshots(department_config.shift_templates, time_artifacts)

        valid_shift_patterns = ((3, 2), (2, 3))
        flexible_lunch_departments = tuple(department_config.flexible_lunch_departments)

        return DepartmentArtifacts(
            default_settings=default_settings,
            overrides=overrides,
            day_patterns=day_patterns,
            lunch_break_slots=lunch_break_slots,
            lunch_slot_windows=lunch_slot_windows,
            shift_assignments=shift_assignments,
            shift_definitions=shift_definitions,
            valid_shift_patterns=valid_shift_patterns,
            flexible_lunch_departments=flexible_lunch_departments,
            five_pm_constraints=department_config.five_pm_constraints,
        )

    def _build_shift_snapshots(
        self,
        shift_templates: Mapping[str, ShiftTemplate],
        time_artifacts: TimeSystemArtifacts,
    ) -> Dict[str, ShiftDefinitionSnapshot]:
        snapshots: Dict[str, ShiftDefinitionSnapshot] = {}

        for identifier, template in shift_templates.items():
            theory_slots = tuple(template.theory_slots)
            lab_sessions = tuple(template.lab_sessions)
            start_time, _ = self._parse_time_bounds(time_artifacts.theory_slots[theory_slots[0]])
            _, end_time = self._parse_time_bounds(time_artifacts.theory_slots[theory_slots[-1]])

            label = template.label or identifier
            snapshots[identifier] = ShiftDefinitionSnapshot(
                identifier=identifier,
                theory_slots=theory_slots,
                lab_sessions=lab_sessions,
                start_time=start_time,
                end_time=end_time,
                label=label,
            )

            lowercase_identifier = identifier.lower()
            if lowercase_identifier not in snapshots:
                snapshots[lowercase_identifier] = snapshots[identifier]

        return snapshots

    def _build_room_collections(self, rooms_df: pd.DataFrame) -> RoomCollections:
        room_type_normalized = self._normalise_room_type_series(rooms_df)

        if "is_lab" in rooms_df.columns:
            lab_mask = rooms_df["is_lab"].fillna(0).astype(int) == 1
        elif "room_type" in rooms_df.columns:
            lab_mask = room_type_normalized.str.contains("lab", na=False)
        else:
            lab_mask = pd.Series(False, index=rooms_df.index)

        lab_rooms = rooms_df.loc[lab_mask].copy()
        theory_rooms = rooms_df.loc[~lab_mask].copy()

        # The active room schema uses "Core-Lab" and "Computer-Lab".
        # Unmapped lab courses should fall back to computer labs only, while
        # core labs remain available through explicit core_lab_mapping.csv rows.
        laboratory_mask = pd.Series(False, index=rooms_df.index)
        if "room_type" in rooms_df.columns:
            laboratory_mask = lab_mask & room_type_normalized.str.contains("computer", na=False)

        lab_room_ids = tuple(lab_rooms["id"].astype(str))
        theory_room_ids = tuple(theory_rooms["id"].astype(str))
        laboratory_room_ids = tuple(rooms_df.loc[laboratory_mask, "id"].astype(str))

        return RoomCollections(
            lab_rooms=lab_rooms,
            theory_rooms=theory_rooms,
            lab_room_ids=lab_room_ids,
            theory_room_ids=theory_room_ids,
            laboratory_room_ids=laboratory_room_ids,
        )

    @staticmethod
    def _normalise_room_type_series(rooms_df: pd.DataFrame) -> pd.Series:
        if "room_type" not in rooms_df.columns:
            return pd.Series("", index=rooms_df.index)
        return (
            rooms_df["room_type"]
            .fillna("")
            .astype(str)
            .str.lower()
            .str.replace(r"[^a-z0-9]+", "", regex=True)
        )

    # ------------------------------------------------------------------
    # Extraction helpers
    # ------------------------------------------------------------------
    def _extract_sorted_unique(
        self,
        df: pd.DataFrame,
        columns: Sequence[str],
        *,
        fallback: Optional[str] = None,
    ) -> Tuple[str, ...]:
        values: Iterable[str] = []
        for column in columns:
            if column in df.columns:
                values = df[column].dropna().astype(str).str.strip()
                break
        else:
            if fallback and fallback in df.columns:
                values = df[fallback].dropna().astype(str).str.strip()
            else:
                return tuple()

        unique = sorted({value for value in values if value})
        return tuple(unique)

    # ------------------------------------------------------------------
    # Time parsing helpers
    # ------------------------------------------------------------------
    def _derive_session_range(self, slots: Tuple[int, ...], lab_slots: Sequence[str]) -> str:
        start_time, _ = self._parse_time_bounds(lab_slots[slots[0]])
        _, end_time = self._parse_time_bounds(lab_slots[slots[-1]])
        return f"{start_time} - {end_time}"

    def _parse_time_bounds(self, slot_label: str) -> Tuple[str, str]:
        start_str, end_str = [part.strip() for part in slot_label.split("-")]
        return start_str, end_str

    def _parse_time_range(self, slot_label: str) -> Tuple[int, int]:
        start_str, end_str = self._parse_time_bounds(slot_label)
        return self._time_to_minutes(start_str), self._time_to_minutes(end_str)

    def _time_to_minutes(self, time_str: str) -> int:
        hour_str, minute_str = time_str.split(":")
        hour = int(hour_str.strip())
        minute = int(minute_str.strip())

        if hour == 12:
            hour = 12
        elif 1 <= hour <= 7:
            hour += 12

        return hour * 60 + minute

    def _ranges_overlap(self, first: Tuple[int, int], second: Tuple[int, int]) -> bool:
        return first[0] < second[1] and first[1] > second[0]


def load_data(config: SchedulerConfig, *, base_dir: Optional[Path] = None) -> DataLoadResult:
    """Convenience wrapper mirroring the legacy `load_data` helper."""

    loader = DataLoader(config, base_dir=base_dir)
    return loader.load()


if __name__ == '__main__':
    base_dir = Path.cwd()
    config_manager = ConfigManager(base_dir=base_dir)
    config = config_manager.load()
    
    data_loader = DataLoader(config, base_dir=base_dir)
    print(data_loader._paths)
    res = data_loader.load()
    print(res)


