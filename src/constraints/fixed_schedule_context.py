"""Shared fixed-schedule occupancy helpers for teacher constraints.

The fixed schedule lock may run after other teacher constraints because
constraint priority controls application order.  These helpers let constraints
read the same previous schedule inputs directly, so prior-year teacher activity
is visible to daily workload/window/presence rules even before the lock applies
its hard blocking clauses.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping, MutableMapping, Optional, Sequence, Tuple

from .context import ConstraintContext
from ..utils.normalization import normalize_session_name, normalize_teacher_id, safe_int
from ..utils.time_utils import DayNormalizer


@dataclass(frozen=True)
class FixedScheduleOccupancy:
    lab_teacher_sessions: Mapping[str, Mapping[str, Tuple[str, ...]]]
    theory_teacher_slots: Mapping[str, Mapping[str, Tuple[int, ...]]]
    teacher_daily_hours: Mapping[Tuple[str, str], int]
    teacher_days: Mapping[str, Tuple[str, ...]]
    source_lab_records: int = 0
    source_theory_records: int = 0
    sources: Tuple[str, ...] = field(default_factory=tuple)

    def lab_sessions_for(self, teacher_id: object, day_label: object) -> Tuple[str, ...]:
        teacher_key = normalize_teacher_id(teacher_id)
        day_key = normalize_day_label(day_label)
        if not teacher_key or not day_key:
            return tuple()
        return self.lab_teacher_sessions.get(teacher_key, {}).get(day_key, tuple())

    def hours_for(self, teacher_id: object, day_label: object) -> int:
        teacher_key = normalize_teacher_id(teacher_id)
        day_key = normalize_day_label(day_label)
        if not teacher_key or not day_key:
            return 0
        return int(self.teacher_daily_hours.get((teacher_key, day_key), 0) or 0)


class _OccupancyBuilder:
    def __init__(self, context: ConstraintContext) -> None:
        self.context = context
        self.lab_sessions: MutableMapping[str, MutableMapping[str, set[str]]] = {}
        self.theory_slots: MutableMapping[str, MutableMapping[str, set[int]]] = {}
        self.daily_hours: Dict[Tuple[str, str], int] = {}
        self.counted_lab: set[Tuple[str, str, str]] = set()
        self.counted_theory: set[Tuple[str, str, int]] = set()
        self.source_lab_records = 0
        self.source_theory_records = 0
        self.sources: list[str] = []

    def add_lab(self, teacher_id: object, day_label: object, session_name: object) -> None:
        teacher_key = normalize_teacher_id(teacher_id)
        day_key = normalize_day_label(day_label)
        session_key = normalize_session_name(session_name)
        if not teacher_key or not day_key or not session_key:
            return
        self.lab_sessions.setdefault(teacher_key, {}).setdefault(day_key, set()).add(session_key)
        counted_key = (teacher_key, day_key, session_key)
        if counted_key not in self.counted_lab:
            self.counted_lab.add(counted_key)
            hours = _lab_session_hours(self.context, session_key)
            self.daily_hours[(teacher_key, day_key)] = self.daily_hours.get((teacher_key, day_key), 0) + hours

    def add_theory(self, teacher_id: object, day_label: object, slot_index: object) -> None:
        teacher_key = normalize_teacher_id(teacher_id)
        day_key = normalize_day_label(day_label)
        slot_key = safe_int(slot_index)
        if not teacher_key or not day_key or slot_key is None:
            return
        self.theory_slots.setdefault(teacher_key, {}).setdefault(day_key, set()).add(slot_key)
        counted_key = (teacher_key, day_key, slot_key)
        if counted_key not in self.counted_theory:
            self.counted_theory.add(counted_key)
            self.daily_hours[(teacher_key, day_key)] = self.daily_hours.get((teacher_key, day_key), 0) + 1

    def build(self) -> FixedScheduleOccupancy:
        teacher_days: Dict[str, Tuple[str, ...]] = {}
        all_teachers = set(self.lab_sessions) | set(self.theory_slots)
        for teacher_id in all_teachers:
            days = set(self.lab_sessions.get(teacher_id, {})) | set(self.theory_slots.get(teacher_id, {}))
            teacher_days[teacher_id] = tuple(sorted(days, key=_day_sort_key))
        return FixedScheduleOccupancy(
            lab_teacher_sessions={
                teacher: {
                    day: tuple(sorted(sessions))
                    for day, sessions in day_map.items()
                }
                for teacher, day_map in self.lab_sessions.items()
            },
            theory_teacher_slots={
                teacher: {
                    day: tuple(sorted(slots))
                    for day, slots in day_map.items()
                }
                for teacher, day_map in self.theory_slots.items()
            },
            teacher_daily_hours=dict(self.daily_hours),
            teacher_days=teacher_days,
            source_lab_records=self.source_lab_records,
            source_theory_records=self.source_theory_records,
            sources=tuple(self.sources),
        )


def get_fixed_schedule_occupancy(context: ConstraintContext) -> FixedScheduleOccupancy:
    """Return normalized teacher occupancy from previous schedule inputs."""

    cache = context.extra.setdefault("fixed_schedule_occupancy", {})
    cached = cache.get("value") if isinstance(cache, MutableMapping) else None
    if isinstance(cached, FixedScheduleOccupancy):
        return cached

    builder = _OccupancyBuilder(context)
    _collect_from_blocking_mask(context, builder)
    _collect_from_fixed_lock_config(context, builder)
    occupancy = builder.build()
    if isinstance(cache, MutableMapping):
        cache["value"] = occupancy
    return occupancy


def normalize_day_label(value: object) -> str:
    label = str(value or "").strip()
    normalized = DayNormalizer.normalize_day_name(label)
    return normalized or label.lower()


def resolve_day_label(
    context: ConstraintContext,
    *,
    day_value: object = None,
    day_index_value: object = None,
    course_id: object = None,
    is_lab: bool,
) -> str:
    day_label = normalize_day_label(day_value)
    if day_label:
        return day_label

    day_index = safe_int(day_index_value)
    if day_index is None:
        return ""

    course_key = str(course_id or "").strip()
    if is_lab:
        patterns = getattr(context.variables.lab, "day_patterns", {}) or {}
    else:
        patterns = getattr(context.variables.theory, "course_day_patterns", {}) or {}
    pattern = patterns.get(course_key)
    if not pattern:
        pattern = getattr(context.data.raw.time, "working_days", tuple()) or tuple()
    if pattern and 0 <= day_index < len(pattern):
        return normalize_day_label(pattern[day_index])
    return f"day_{day_index}"


def _collect_from_blocking_mask(context: ConstraintContext, builder: _OccupancyBuilder) -> None:
    mask = getattr(context.data.raw, "blocking_mask", None)
    if not mask:
        return
    lab_sessions = getattr(mask, "blocked_lab_teacher_sessions", set()) or set()
    theory_slots = getattr(mask, "blocked_theory_teacher_slots", set()) or set()
    for teacher_id, day_label, session_name in lab_sessions:
        builder.add_lab(teacher_id, day_label, session_name)
    for teacher_id, day_label, slot_index in theory_slots:
        builder.add_theory(teacher_id, day_label, slot_index)
    if lab_sessions or theory_slots:
        builder.source_lab_records += len(lab_sessions)
        builder.source_theory_records += len(theory_slots)
        builder.sources.append("blocking_mask")


def _collect_from_fixed_lock_config(context: ConstraintContext, builder: _OccupancyBuilder) -> None:
    setting = _fixed_lock_setting(context)
    if not setting:
        return
    enabled = _setting_value(setting, "enabled", True)
    if not _as_bool(enabled, True):
        return
    params = _setting_value(setting, "params", {}) or {}
    if not isinstance(params, Mapping):
        return

    lab_records, theory_records, source = _load_records_from_params(params)
    if not lab_records and not theory_records:
        return

    for record in lab_records:
        day_label = resolve_day_label(
            context,
            day_value=record.get("day"),
            day_index_value=record.get("day_index"),
            course_id=record.get("course_instance_id"),
            is_lab=True,
        )
        builder.add_lab(record.get("teacher_id"), day_label, record.get("session_name"))

    for record in theory_records:
        day_label = resolve_day_label(
            context,
            day_value=record.get("day"),
            day_index_value=record.get("day_index"),
            course_id=record.get("course_instance_id"),
            is_lab=False,
        )
        builder.add_theory(record.get("teacher_id"), day_label, record.get("slot_index"))

    builder.source_lab_records += len(lab_records)
    builder.source_theory_records += len(theory_records)
    builder.sources.append(source)


def _fixed_lock_setting(context: ConstraintContext) -> Optional[object]:
    constraints = getattr(context.config, "constraints", None)
    cross_system = getattr(constraints, "cross_system", None)
    if not cross_system:
        return None
    getter = getattr(cross_system, "get", None)
    if callable(getter):
        return getter("fixed_schedule_lock")
    if isinstance(cross_system, Mapping):
        return cross_system.get("fixed_schedule_lock")
    return None


def _load_records_from_params(
    params: Mapping[str, object],
) -> tuple[Tuple[Mapping[str, Any], ...], Tuple[Mapping[str, Any], ...], str]:
    raw_lab_csv = str(params.get("lab_csv_path") or "").strip()
    raw_theory_csv = str(params.get("theory_csv_path") or "").strip()
    if raw_lab_csv or raw_theory_csv:
        return _load_from_csv(raw_lab_csv, raw_theory_csv)

    raw_path = (
        str(params.get("snapshot_path") or "").strip()
        or str(params.get("schedule_path") or "").strip()
        or str(params.get("schedule_json_path") or "").strip()
    )
    if not raw_path:
        return tuple(), tuple(), "fixed_schedule_lock"
    path = _resolve_path(Path(raw_path))
    if not path.exists():
        return tuple(), tuple(), str(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return tuple(), tuple(), str(path)
    lab, theory = normalize_schedule_payload(payload)
    return lab, theory, str(path)


def normalize_schedule_payload(
    payload: Mapping[str, Any],
) -> tuple[Tuple[Mapping[str, Any], ...], Tuple[Mapping[str, Any], ...]]:
    """Normalize warm-start or schedule.json payloads into compact records."""

    if "lab_assignments" in payload or "theory_assignments" in payload:
        return tuple(payload.get("lab_assignments") or ()), tuple(payload.get("theory_assignments") or ())

    if "lab_entries" not in payload and "theory_entries" not in payload:
        return tuple(), tuple()

    lab = []
    for entry in payload.get("lab_entries") or ():
        if not isinstance(entry, Mapping):
            continue
        lab.append(
            {
                "teacher_id": entry.get("teacher_id"),
                "course_instance_id": entry.get("course_instance_id"),
                "day": entry.get("day"),
                "day_index": entry.get("day_index"),
                "session_name": entry.get("session_name"),
                "room_id": entry.get("room_id"),
            }
        )

    theory = []
    for entry in payload.get("theory_entries") or ():
        if not isinstance(entry, Mapping):
            continue
        theory.append(
            {
                "teacher_id": entry.get("teacher_id"),
                "course_instance_id": entry.get("course_instance_id"),
                "day": entry.get("day"),
                "day_index": entry.get("day_index"),
                "slot_index": entry.get("slot_index"),
                "room_id": entry.get("room_id"),
            }
        )
    return tuple(lab), tuple(theory)


def _load_from_csv(
    lab_path_text: str,
    theory_path_text: str,
) -> tuple[Tuple[Mapping[str, Any], ...], Tuple[Mapping[str, Any], ...], str]:
    lab_records: list[Mapping[str, Any]] = []
    theory_records: list[Mapping[str, Any]] = []
    if lab_path_text:
        path = _resolve_path(Path(lab_path_text))
        if path.exists():
            with path.open("r", encoding="utf-8") as handle:
                for row in csv.DictReader(handle):
                    lab_records.append(
                        {
                            "teacher_id": row.get("teacher_id"),
                            "course_instance_id": row.get("course_instance_id"),
                            "day": row.get("day"),
                            "day_index": row.get("day_index"),
                            "session_name": row.get("session_name"),
                            "room_id": row.get("room_id"),
                        }
                    )
    if theory_path_text:
        path = _resolve_path(Path(theory_path_text))
        if path.exists():
            with path.open("r", encoding="utf-8") as handle:
                for row in csv.DictReader(handle):
                    theory_records.append(
                        {
                            "teacher_id": row.get("teacher_id"),
                            "course_instance_id": row.get("course_instance_id"),
                            "day": row.get("day"),
                            "day_index": row.get("day_index"),
                            "slot_index": row.get("slot_index"),
                            "room_id": row.get("room_id"),
                        }
                    )
    sources = []
    if lab_path_text:
        sources.append(f"lab={lab_path_text}")
    if theory_path_text:
        sources.append(f"theory={theory_path_text}")
    return tuple(lab_records), tuple(theory_records), ", ".join(sources)


def _lab_session_hours(context: ConstraintContext, session_name: str) -> int:
    mapping = getattr(context.data.raw.time, "lab_session_to_theory", {}) or {}
    for key, slots in mapping.items():
        if normalize_session_name(key) == session_name:
            return max(1, len(tuple(slots or ())))
    return 2


def _setting_value(setting: object, key: str, default: object = None) -> object:
    if isinstance(setting, Mapping):
        return setting.get(key, default)
    return getattr(setting, key, default)


def _as_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _resolve_path(candidate: Path) -> Path:
    if candidate.is_absolute():
        return candidate
    return (Path.cwd() / candidate).resolve()


def _day_sort_key(day: str) -> tuple[int, str]:
    order = {
        "monday": 0,
        "tuesday": 1,
        "wed": 2,
        "wednesday": 2,
        "thur": 3,
        "thursday": 3,
        "fri": 4,
        "friday": 4,
        "saturday": 5,
    }
    return order.get(day, 99), day


__all__ = [
    "FixedScheduleOccupancy",
    "get_fixed_schedule_occupancy",
    "normalize_day_label",
    "normalize_schedule_payload",
    "resolve_day_label",
]
