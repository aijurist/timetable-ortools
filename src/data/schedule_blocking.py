"""
Schedule Blocking Mask

Pre-computed blocking sets for variable pruning during variable creation.
This module loads fixed schedule data and builds occupancy masks to prevent
creating variables for blocked (teacher, day, slot, room) combinations.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Mapping, Optional, Set, Tuple

from ..utils.normalization import (
    normalize_teacher_id,
    normalize_room_id,
    normalize_course_id,
    normalize_session_name,
    normalize_day_label,
    safe_int,
)
from ..utils.time_utils import DayNormalizer

logger = logging.getLogger(__name__)


@dataclass
class ScheduleBlockingMask:
    """Pre-computed blocking sets for variable pruning."""

    locked_lab_assignments: Set[Tuple[str, str, str, str, str]] = field(default_factory=set)
    blocked_lab_rooms: Set[Tuple[str, str, str]] = field(default_factory=set)
    blocked_lab_teacher_sessions: Set[Tuple[str, str, str]] = field(default_factory=set)

    locked_theory_assignments: Set[Tuple[str, str, str, int, str]] = field(default_factory=set)
    blocked_theory_rooms: Set[Tuple[str, int, str]] = field(default_factory=set)
    blocked_theory_teacher_slots: Set[Tuple[str, str, int]] = field(default_factory=set)

    cross_blocked_theory_slots: Set[Tuple[str, str, int]] = field(default_factory=set)
    cross_blocked_lab_sessions: Set[Tuple[str, str, str]] = field(default_factory=set)

    # Fixed schedule hours per teacher per day: (teacher_id, day_label) -> hours
    teacher_daily_fixed_hours: Dict[Tuple[str, str], int] = field(default_factory=dict)

    def is_lab_variable_blocked(
        self,
        teacher_id: str,
        course_id: str,
        day_label: str,
        session_name: str,
        room_id: str,
    ) -> bool:
        """Check if a lab variable should be pruned (not created)."""
        tid = normalize_teacher_id(teacher_id)
        cid = normalize_course_id(course_id)
        day = normalize_day_label(day_label)
        session = normalize_session_name(session_name)
        rid = normalize_room_id(room_id)

        if (tid, cid, day, session, rid) in self.locked_lab_assignments:
            return False

        if (day, session, rid) in self.blocked_lab_rooms:
            return True

        if (tid, day, session) in self.blocked_lab_teacher_sessions:
            return True

        if (tid, day, session) in self.cross_blocked_lab_sessions:
            return True

        return False

    def is_lab_variable_locked(
        self,
        teacher_id: str,
        course_id: str,
        day_label: str,
        session_name: str,
        room_id: str,
    ) -> bool:
        """Check if a lab variable should be locked (var == 1)."""
        tid = normalize_teacher_id(teacher_id)
        cid = normalize_course_id(course_id)
        day = normalize_day_label(day_label)
        session = normalize_session_name(session_name)
        rid = normalize_room_id(room_id)

        return (tid, cid, day, session, rid) in self.locked_lab_assignments

    def is_theory_variable_blocked(
        self,
        teacher_id: str,
        course_id: str,
        day_label: str,
        slot_index: int,
        room_id: str,
    ) -> bool:
        """Check if a theory variable should be pruned (not created)."""
        tid = normalize_teacher_id(teacher_id)
        cid = normalize_course_id(course_id)
        day = normalize_day_label(day_label)
        rid = normalize_room_id(room_id)

        if (tid, cid, day, slot_index, rid) in self.locked_theory_assignments:
            return False

        if (day, slot_index, rid) in self.blocked_theory_rooms:
            return True

        if (tid, day, slot_index) in self.blocked_theory_teacher_slots:
            return True

        if (tid, day, slot_index) in self.cross_blocked_theory_slots:
            return True

        return False

    def is_theory_variable_locked(
        self,
        teacher_id: str,
        course_id: str,
        day_label: str,
        slot_index: int,
        room_id: str,
    ) -> bool:
        """Check if a theory variable should be locked (var == 1)."""
        tid = normalize_teacher_id(teacher_id)
        cid = normalize_course_id(course_id)
        day = normalize_day_label(day_label)
        rid = normalize_room_id(room_id)

        return (tid, cid, day, slot_index, rid) in self.locked_theory_assignments

    def is_theory_slot_blocked(
        self,
        teacher_id: str,
        course_id: str,
        day_label: str,
        slot_index: int,
    ) -> bool:
        """Check if a theory timeslot variable should be pruned."""
        tid = normalize_teacher_id(teacher_id)
        cid = normalize_course_id(course_id)
        day = normalize_day_label(day_label)

        has_locked = any(
            key[0] == tid and key[1] == cid and key[2] == day and key[3] == slot_index
            for key in self.locked_theory_assignments
        )
        if has_locked:
            return False

        if (tid, day, slot_index) in self.blocked_theory_teacher_slots:
            return True

        if (tid, day, slot_index) in self.cross_blocked_theory_slots:
            return True

        return False


def build_schedule_blocking_mask(
    lab_csv_path: Optional[Path],
    theory_csv_path: Optional[Path],
    lab_session_to_theory_mapping: Optional[Mapping[str, Tuple[int, ...]]] = None,
    day_patterns: Optional[Mapping[str, Tuple[str, ...]]] = None,
    working_days: Optional[Tuple[str, ...]] = None,
) -> ScheduleBlockingMask:
    """Load CSV schedules and build blocking masks.

    Args:
        lab_csv_path: Path to lab schedule CSV
        theory_csv_path: Path to theory schedule CSV
        lab_session_to_theory_mapping: Maps lab session names to overlapping theory slot indices
        day_patterns: Course-specific day patterns
        working_days: Default working days

    Returns:
        ScheduleBlockingMask with all blocking sets populated
    """
    mask = ScheduleBlockingMask()

    lab_records = _load_csv_records(lab_csv_path, "lab")
    theory_records = _load_csv_records(theory_csv_path, "theory")

    logger.info(
        "Building blocking mask from %d lab records and %d theory records",
        len(lab_records),
        len(theory_records),
    )

    # Build lab session hours lookup from mapping
    lab_session_hours: Dict[str, int] = {}
    if lab_session_to_theory_mapping:
        for session_name, slots in lab_session_to_theory_mapping.items():
            lab_session_hours[normalize_session_name(session_name)] = max(1, len(slots or ()))
    default_lab_hours = 2  # Default lab session = 2 hours

    # Track which (teacher, day, session) we've already counted to avoid duplicates
    counted_lab_sessions: Set[Tuple[str, str, str]] = set()
    counted_theory_slots: Set[Tuple[str, str, int]] = set()

    for record in lab_records:
        tid = normalize_teacher_id(record.get("teacher_id"))
        cid = normalize_course_id(record.get("course_instance_id"))
        session = normalize_session_name(record.get("session_name"))
        rid = normalize_room_id(record.get("room_id"))
        day = _resolve_day_label(record.get("day"), record.get("day_index"), cid, day_patterns, working_days)

        if not tid or not session or not rid or not day:
            continue

        mask.locked_lab_assignments.add((tid, cid, day, session, rid))
        mask.blocked_lab_rooms.add((day, session, rid))
        mask.blocked_lab_teacher_sessions.add((tid, day, session))

        # Count fixed hours (only once per teacher/day/session)
        session_key = (tid, day, session)
        if session_key not in counted_lab_sessions:
            counted_lab_sessions.add(session_key)
            hours = lab_session_hours.get(session, default_lab_hours)
            key = (tid, day)
            mask.teacher_daily_fixed_hours[key] = mask.teacher_daily_fixed_hours.get(key, 0) + hours

    for record in theory_records:
        tid = normalize_teacher_id(record.get("teacher_id"))
        cid = normalize_course_id(record.get("course_instance_id"))
        rid = normalize_room_id(record.get("room_id"))
        day = _resolve_day_label(record.get("day"), record.get("day_index"), cid, day_patterns, working_days)
        slot_idx = safe_int(record.get("slot_index"))

        if not tid or not rid or not day or slot_idx is None:
            continue

        mask.locked_theory_assignments.add((tid, cid, day, slot_idx, rid))
        mask.blocked_theory_rooms.add((day, slot_idx, rid))
        mask.blocked_theory_teacher_slots.add((tid, day, slot_idx))

        # Count fixed theory hours (1 hour per slot, only once per teacher/day/slot)
        slot_key = (tid, day, slot_idx)
        if slot_key not in counted_theory_slots:
            counted_theory_slots.add(slot_key)
            key = (tid, day)
            mask.teacher_daily_fixed_hours[key] = mask.teacher_daily_fixed_hours.get(key, 0) + 1

    _build_cross_domain_blocks(mask, lab_session_to_theory_mapping)

    logger.info(
        "Built blocking mask: lab_rooms=%d, lab_teachers=%d, theory_rooms=%d, theory_teachers=%d, cross_theory=%d, cross_lab=%d, fixed_hours_entries=%d",
        len(mask.blocked_lab_rooms),
        len(mask.blocked_lab_teacher_sessions),
        len(mask.blocked_theory_rooms),
        len(mask.blocked_theory_teacher_slots),
        len(mask.cross_blocked_theory_slots),
        len(mask.cross_blocked_lab_sessions),
        len(mask.teacher_daily_fixed_hours),
    )

    return mask


def _load_csv_records(csv_path: Optional[Path], schedule_type: str) -> list:
    """Load records from CSV file."""
    if not csv_path:
        return []

    resolved_path = _resolve_path(csv_path)
    if not resolved_path.exists():
        logger.warning("Schedule CSV not found: %s", resolved_path)
        return []

    records = []
    try:
        with open(resolved_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                records.append({_normalize_csv_header(key): value for key, value in row.items()})
        logger.info("Loaded %d %s records from %s", len(records), schedule_type, resolved_path)
    except Exception as e:
        logger.warning("Failed to read %s CSV %s: %s", schedule_type, resolved_path, e)

    return records


def _resolve_day_label(
    day_value: object,
    day_index_value: object,
    course_id: str,
    day_patterns: Optional[Mapping[str, Tuple[str, ...]]],
    working_days: Optional[Tuple[str, ...]],
) -> str:
    """Resolve day label from day name or day index."""
    if day_value:
        label = str(day_value).strip()
        normalized = DayNormalizer.normalize_day_name(label)
        if normalized:
            return normalized
        return label.lower()

    day_idx = safe_int(day_index_value)
    if day_idx is not None:
        pattern = None
        if day_patterns and course_id:
            pattern = day_patterns.get(course_id)
        if not pattern and working_days:
            pattern = working_days

        if pattern and 0 <= day_idx < len(pattern):
            day_str = pattern[day_idx]
            normalized = DayNormalizer.normalize_day_name(day_str)
            if normalized:
                return normalized
            return str(day_str).lower()

    return ""


def _build_cross_domain_blocks(
    mask: ScheduleBlockingMask,
    lab_session_to_theory_mapping: Optional[Mapping[str, Tuple[int, ...]]],
) -> None:
    """Build cross-domain blocking sets.

    Lab occupancy blocks theory slots and vice versa.
    """
    if not lab_session_to_theory_mapping:
        return

    inv_mapping: Dict[int, Set[str]] = {}
    for session_name, slots in lab_session_to_theory_mapping.items():
        for slot in slots or ():
            slot_idx = safe_int(slot)
            if slot_idx is not None:
                if slot_idx not in inv_mapping:
                    inv_mapping[slot_idx] = set()
                inv_mapping[slot_idx].add(normalize_session_name(session_name))

    for tid, day, session in mask.blocked_lab_teacher_sessions:
        slots = lab_session_to_theory_mapping.get(session)
        if not slots:
            continue
        for slot in slots:
            slot_idx = safe_int(slot)
            if slot_idx is not None:
                mask.cross_blocked_theory_slots.add((tid, day, slot_idx))

    for tid, day, slot_idx in mask.blocked_theory_teacher_slots:
        sessions = inv_mapping.get(slot_idx)
        if not sessions:
            continue
        for session in sessions:
            mask.cross_blocked_lab_sessions.add((tid, day, session))


def _resolve_path(candidate: Path) -> Path:
    """Resolve path to absolute."""
    if candidate.is_absolute():
        return candidate
    return (Path.cwd() / candidate).resolve()


def _normalize_csv_header(value: object) -> str:
    """Normalize exported CSV headers, including UTF-8 BOM-prefixed first columns."""
    return str(value or "").replace("\ufeff", "").strip()


__all__ = ["ScheduleBlockingMask", "build_schedule_blocking_mask"]
