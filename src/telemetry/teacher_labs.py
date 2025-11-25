"""Telemetry utilities for teacher-focused lab constraints."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Optional, Sequence, Tuple

from ..constraints.schema import ConstraintApplicationResult
from ..runtime.extractor_schema import LabScheduleEntry, ScheduleExtractionResult

DAY_ORDER: Tuple[str, ...] = ("monday", "tuesday", "wed", "thur", "fri", "saturday")
DEFAULT_MAX_DAILY_SESSIONS = 2
DEFAULT_MAX_CONSECUTIVE = 2
DEFAULT_EARLY_SESSIONS: Tuple[str, ...] = ("L1",)
DEFAULT_BUFFER_SESSIONS: Tuple[str, ...] = ("L5",)
DEFAULT_LATE_SESSIONS: Tuple[str, ...] = ("L6",)

CONSTRAINT_TITLES = {
    "daily_presence": "Teacher Daily Lab Presence",
    "max_consecutive": "Teacher Max Consecutive Lab Sessions",
}


@dataclass(frozen=True)
class TeacherPolicy:
    max_daily_sessions: int = DEFAULT_MAX_DAILY_SESSIONS
    max_consecutive_sessions: int = DEFAULT_MAX_CONSECUTIVE
    early_sessions: Tuple[str, ...] = DEFAULT_EARLY_SESSIONS
    buffer_sessions: Tuple[str, ...] = DEFAULT_BUFFER_SESSIONS
    late_sessions: Tuple[str, ...] = DEFAULT_LATE_SESSIONS

    @property
    def early_lookup(self) -> set[str]:
        return {label.upper() for label in self.early_sessions}

    @property
    def buffer_lookup(self) -> set[str]:
        return {label.upper() for label in self.buffer_sessions}

    @property
    def late_lookup(self) -> set[str]:
        return {label.upper() for label in self.late_sessions}

    def to_dict(self) -> Mapping[str, Any]:
        return {
            "max_daily_sessions": self.max_daily_sessions,
            "max_consecutive_sessions": self.max_consecutive_sessions,
            "early_sessions": self.early_sessions,
            "buffer_sessions": self.buffer_sessions,
            "late_sessions": self.late_sessions,
        }


@dataclass
class TeacherLabTelemetryBuilder:
    """Aggregate teacher slot usage with constraint diagnostics."""

    constraint_results: Sequence[ConstraintApplicationResult]
    timestamp: Optional[datetime] = None

    def build(self, schedule: ScheduleExtractionResult) -> Mapping[str, Any]:
        lab_entries = schedule.lab_entries if schedule else tuple()
        policy = self._derive_policy()
        usage = _aggregate_teacher_usage(lab_entries)
        teachers, summary = _summarize_usage(usage, policy)

        payload = {
            "generated_at": (self.timestamp or datetime.now(timezone.utc)).isoformat(),
            "policies": policy.to_dict(),
            "summary": summary,
            "teachers": teachers,
            "constraints": self._serialize_constraints(),
        }
        return payload

    def write(self, schedule: ScheduleExtractionResult, destination: Path) -> Path:
        payload = self.build(schedule)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return destination

    def _derive_policy(self) -> TeacherPolicy:
        presence_result = self._find_constraint(CONSTRAINT_TITLES["daily_presence"])
        consecutive_result = self._find_constraint(CONSTRAINT_TITLES["max_consecutive"])

        presence_details = presence_result.details if presence_result else {}
        max_daily = _to_int(presence_details.get("max_daily_sessions")) or DEFAULT_MAX_DAILY_SESSIONS
        early_sessions = _parse_session_labels(presence_details.get("early_sessions"), DEFAULT_EARLY_SESSIONS)
        buffer_sessions = _parse_session_labels(presence_details.get("buffer_sessions"), DEFAULT_BUFFER_SESSIONS)
        late_sessions = _parse_session_labels(presence_details.get("late_sessions"), DEFAULT_LATE_SESSIONS)

        consecutive_details = consecutive_result.details if consecutive_result else {}
        max_consecutive = _to_int(consecutive_details.get("max_consecutive_sessions")) or DEFAULT_MAX_CONSECUTIVE

        return TeacherPolicy(
            max_daily_sessions=max_daily,
            max_consecutive_sessions=max_consecutive,
            early_sessions=early_sessions,
            buffer_sessions=buffer_sessions,
            late_sessions=late_sessions,
        )

    def _find_constraint(self, title: str) -> Optional[ConstraintApplicationResult]:
        for result in self.constraint_results:
            if result.name.lower() == title.lower():
                return result
        return None

    def _serialize_constraints(self) -> Mapping[str, Mapping[str, Any]]:
        payload: Dict[str, Mapping[str, Any]] = {}
        for key, title in CONSTRAINT_TITLES.items():
            result = self._find_constraint(title)
            if result is None:
                continue
            payload[key] = {
                "name": result.name,
                "status": result.status,
                "enabled": result.enabled,
                "priority": result.priority,
                "details": _normalize(result.details),
            }
        return payload


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------

def _aggregate_teacher_usage(entries: Sequence[LabScheduleEntry]) -> Mapping[str, Mapping[str, Any]]:
    usage: Dict[str, Dict[str, Any]] = {}
    for entry in entries:
        teacher_id = entry.teacher_id or entry.teacher_name
        if not teacher_id:
            continue
        teacher_key = str(teacher_id)
        record = usage.setdefault(
            teacher_key,
            {
                "teacher_name": entry.teacher_name or teacher_key,
                "departments": set(),
                "courses": set(),
                "day_sessions": {},
            },
        )
        if entry.teacher_name and not record.get("teacher_name"):
            record["teacher_name"] = entry.teacher_name
        if entry.department:
            record.setdefault("departments", set()).add(entry.department)
        if entry.course_code:
            record.setdefault("courses", set()).add(entry.course_code)

        day = (entry.day or "unspecified").strip().lower() or "unspecified"
        day_bucket: MutableMapping[str, list[Dict[str, Any]]] = record.setdefault("day_sessions", {})  # type: ignore[assignment]
        sessions = day_bucket.setdefault(day, [])
        sessions.append(
            {
                "session": entry.session_name,
                "time": entry.session_time,
                "course_code": entry.course_code,
                "group_id": entry.group_id,
                "department": entry.department,
                "semester": entry.semester,
                "slot_index": entry.session_slots[0] if entry.session_slots else None,
            }
        )
    return usage


def _summarize_usage(
    usage: Mapping[str, Mapping[str, Any]],
    policy: TeacherPolicy,
) -> Tuple[Sequence[Mapping[str, Any]], Mapping[str, Any]]:
    summary = {
        "teachers_in_schedule": 0,
        "days_monitored": 0,
        "days_over_daily_cap": 0,
        "teachers_over_daily_cap": 0,
        "early_late_conflicts": 0,
        "triple_blocks": 0,
        "teachers_long_consecutive": 0,
        "long_consecutive_windows": 0,
    }
    over_daily_teachers: set[str] = set()
    long_run_teachers: set[str] = set()

    teacher_payload: list[Mapping[str, Any]] = []
    for teacher_id in sorted(usage.keys()):
        record = usage[teacher_id]
        day_sessions: Mapping[str, Sequence[Mapping[str, Any]]] = record.get("day_sessions", {})  # type: ignore[assignment]
        day_entries: list[Mapping[str, Any]] = []
        for day in sorted(day_sessions.keys(), key=_day_sort_key):
            sessions = list(day_sessions[day])
            if not sessions:
                continue
            day_summary = _summarize_day(day, sessions, policy)
            day_entries.append(day_summary)
            summary["days_monitored"] += 1
            if day_summary["flags"]["over_daily_cap"]:
                summary["days_over_daily_cap"] += 1
                over_daily_teachers.add(teacher_id)
            if day_summary["flags"]["early_and_late"]:
                summary["early_late_conflicts"] += 1
            if day_summary["flags"]["triple_block"]:
                summary["triple_blocks"] += 1
            if day_summary["flags"]["long_consecutive_run"]:
                summary["long_consecutive_windows"] += 1
                long_run_teachers.add(teacher_id)

        if not day_entries:
            continue

        teacher_payload.append(
            {
                "teacher_id": teacher_id,
                "teacher_name": record.get("teacher_name") or teacher_id,
                "departments": sorted(record.get("departments", set())),
                "courses": sorted(record.get("courses", set())),
                "total_sessions": sum(day["session_count"] for day in day_entries),
                "day_usage": day_entries,
                "flags": {
                    "over_daily_cap": teacher_id in over_daily_teachers,
                    "long_consecutive_run": teacher_id in long_run_teachers,
                },
            }
        )

    summary["teachers_in_schedule"] = len(teacher_payload)
    summary["teachers_over_daily_cap"] = len(over_daily_teachers)
    summary["teachers_long_consecutive"] = len(long_run_teachers)
    return tuple(teacher_payload), summary


def _summarize_day(day: str, sessions: Sequence[Mapping[str, Any]], policy: TeacherPolicy) -> Mapping[str, Any]:
    sorted_sessions = sorted(
        sessions,
        key=lambda item: (
            _day_slot_key(item.get("slot_index")),
            str(item.get("session")),
        ),
    )
    slot_indices = [idx for idx in (session.get("slot_index") for session in sorted_sessions) if idx is not None]
    longest_run = _longest_run(slot_indices)

    session_payload: list[Mapping[str, Any]] = []
    early = late = buffer = 0
    for session in sorted_sessions:
        label = str(session.get("session") or "").strip()
        session_payload.append(
            {
                "session": label or None,
                "time": session.get("time"),
                "course_code": session.get("course_code"),
                "group_id": session.get("group_id"),
                "department": session.get("department"),
                "semester": session.get("semester"),
            }
        )
        if label.upper() in policy.early_lookup:
            early += 1
        if label.upper() in policy.late_lookup:
            late += 1
        if label.upper() in policy.buffer_lookup:
            buffer += 1

    session_count = len(sorted_sessions)
    over_daily_cap = session_count > policy.max_daily_sessions
    early_late = bool(early and late)
    triple_block = bool(early and buffer and late)
    long_consecutive = longest_run > policy.max_consecutive_sessions

    return {
        "day": _format_day(day),
        "session_count": session_count,
        "longest_run": longest_run,
        "sessions": session_payload,
        "flags": {
            "over_daily_cap": over_daily_cap,
            "early_and_late": early_late,
            "triple_block": triple_block,
            "long_consecutive_run": long_consecutive,
        },
    }


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _day_sort_key(day: str) -> Tuple[int, str]:
    normalized = day.lower()
    try:
        return (DAY_ORDER.index(normalized), normalized)
    except ValueError:
        return (len(DAY_ORDER), normalized)


def _format_day(day: str) -> str:
    token = day.strip()
    if not token:
        return "Unspecified"
    return token.capitalize()


def _day_slot_key(index: Optional[int]) -> Tuple[int, int]:
    if index is None:
        return (99, 99)
    return (0, int(index))


def _longest_run(indices: Sequence[int]) -> int:
    if not indices:
        return 0
    unique = sorted(set(indices))
    longest = current = 1
    previous = unique[0]
    for value in unique[1:]:
        if value == previous + 1:
            current += 1
        else:
            current = 1
        if current > longest:
            longest = current
        previous = value
    return longest


def _parse_session_labels(value: Any, fallback: Sequence[str]) -> Tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        labels = [str(item).strip() for item in value if str(item).strip()]
        if labels:
            return tuple(labels)
    return tuple(fallback)


def _normalize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _normalize(val) for key, val in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_normalize(item) for item in value]
    return value


def _to_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = ["TeacherLabTelemetryBuilder", "TeacherPolicy"]
