"""CSE Semester 7 per-group PE pool rules (6 cohort pools + half-cohort selection).

Only CSE S7 uses separate PE buckets per scheduling group (G1–G6) with a
G1–G3 / G4–G6 half split. All other departments keep merged PE pools.
"""

from __future__ import annotations

import re

CSE_LEGACY_DEPT_NAME = "Computer Science & Engineering"
CSE_S7_STUDY_SEMESTER = 7
CSE_S7_PER_GROUP_PE_GENERAL_CODES = frozenset({"CS23PE41", "CS23PE42", "CS23PE43"})
# General PE pool code → slot course codes used on offerings (pe_course_map.csv).
CSE_S7_PE_GENERAL_TO_SLOTS: dict[str, tuple[str, ...]] = {
    "CS23PE41": ("CS23634",),
    "CS23PE42": ("IT23C12",),
    "CS23PE43": ("CS23A31", "IT23B33"),
}
CSE_S7_PE_HALVES: tuple[list[int], list[int]] = ([1, 2, 3], [4, 5, 6])

CSE_S7_PE_BUCKET_NAME_RE = re.compile(
    rf"^{re.escape(CSE_LEGACY_DEPT_NAME)} Sem {CSE_S7_STUDY_SEMESTER} · PE · G(\d+)\s*$",
    re.IGNORECASE,
)


def is_cse_s7_per_group_pe_pool(pe_pool_key: tuple[str, int, str] | None) -> bool:
    """True when a pe_course_map pool row is a CSE S7 per-group PE pool."""
    if pe_pool_key is None:
        return False
    legacy_dept, sem, general_code = pe_pool_key
    return (
        legacy_dept == CSE_LEGACY_DEPT_NAME
        and sem == CSE_S7_STUDY_SEMESTER
        and general_code in CSE_S7_PER_GROUP_PE_GENERAL_CODES
    )


def is_cse_s7_per_group_pe_bucket_name(name: str | None) -> bool:
    return bool(CSE_S7_PE_BUCKET_NAME_RE.match(name or ""))


def cse_s7_bucket_group_number(name: str | None) -> int | None:
    m = CSE_S7_PE_BUCKET_NAME_RE.match(name or "")
    return int(m.group(1)) if m else None


def is_cse_s7_per_group_pe_context(*, study_semester: int, bucket_names: list[str]) -> bool:
    """True when selection menu belongs to CSE S7 with per-group PE buckets."""
    if study_semester != CSE_S7_STUDY_SEMESTER:
        return False
    return any(is_cse_s7_per_group_pe_bucket_name(n) for n in bucket_names)
