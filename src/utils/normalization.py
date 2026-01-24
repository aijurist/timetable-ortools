"""
ID Normalization Utilities

Provides consistent normalization for identifiers to prevent mismatches
such as "130.0" vs "130" when comparing teacher/room/course IDs.
"""

from typing import Optional


def normalize_teacher_id(tid: object) -> str:
    """Normalize teacher ID to canonical string form.
    """
    if tid is None:
        return ""
    s = str(tid).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s


def normalize_room_id(rid: object) -> str:
    """Normalize room ID to canonical string form."""
    if rid is None:
        return ""
    return str(rid).strip()


def normalize_course_id(cid: object) -> str:
    """Normalize course ID to canonical string form.
    """
    if cid is None:
        return ""
    s = str(cid).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s


def normalize_session_name(session: object) -> str:
    """Normalize lab session name to canonical string form."""
    if session is None:
        return ""
    return str(session).strip()


def normalize_day_label(day: object) -> str:
    """Normalize day label to lowercase canonical form."""
    if day is None:
        return ""
    return str(day).strip().lower()


def safe_int(value: object) -> Optional[int]:
    """Safely convert a value to int, returning None on failure."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(str(value)))
        except (TypeError, ValueError):
            return None


__all__ = [
    "normalize_teacher_id",
    "normalize_room_id",
    "normalize_course_id",
    "normalize_session_name",
    "normalize_day_label",
    "safe_int",
]
