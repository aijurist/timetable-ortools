"""Restrict first-year computer labs to designated rooms."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence, Tuple

from ..base import Constraint, ConstraintMetadata
from ..context import ConstraintContext
from ..schema import ConstraintApplicationResult, ConstraintStatus
from ..utils import iter_lab_session_variables


@dataclass
class FirstYearLabRoomConfig:
    allowed_room_tokens: Tuple[str, ...]
    allowed_room_ids: Tuple[str, ...]
    missing_tokens: Tuple[str, ...]
    target_semesters: Tuple[int, ...]
    room_keywords: Tuple[str, ...]

    @staticmethod
    def from_context(context: ConstraintContext, params: Optional[Mapping[str, object]]) -> "FirstYearLabRoomConfig":
        params = params or {}
        tokens = tuple(str(token).strip() for token in params.get("allowed_rooms", ()))
        target_semesters = tuple(int(s) for s in params.get("target_semesters", (1, 2)))
        room_keywords = tuple(str(k).strip().lower() for k in params.get("room_keywords", ("computer",)))
        allowed_room_ids, missing_tokens = _resolve_room_ids(context, tokens)
        return FirstYearLabRoomConfig(
            allowed_room_tokens=tokens,
            allowed_room_ids=allowed_room_ids,
            missing_tokens=missing_tokens,
            target_semesters=target_semesters,
            room_keywords=room_keywords,
        )

    def matches_requirement(self, requirement) -> bool:
        semester = getattr(requirement, "semester", None)
        if semester is None:
            return False
        try:
            semester_int = int(semester)
        except (TypeError, ValueError):
            return False
        if semester_int not in self.target_semesters:
            return False
        return _matches_keyword(requirement, self.room_keywords)


@dataclass
class FirstYearLabRoomStats:
    targeted_courses: int = 0
    constrained_courses: int = 0
    forbidden_assignments: int = 0
    unconstrained_courses: list[str] = field(default_factory=list)


class FirstYearComputerLabConstraint(Constraint):
    """Allow only configured rooms for first-year computer lab sessions."""

    def apply(self, context: ConstraintContext) -> ConstraintApplicationResult:
        config = FirstYearLabRoomConfig.from_context(context, self.params)
        if not config.allowed_room_ids:
            return ConstraintApplicationResult(
                name=self.metadata.name,
                domain=self.metadata.category,
                priority=self.metadata.priority,
                enabled=True,
                status=ConstraintStatus.SKIPPED,
                details={
                    "reason": "no allowed room IDs resolved",
                    "configured_tokens": config.allowed_room_tokens,
                    "missing_tokens": config.missing_tokens,
                },
            )

        stats = FirstYearLabRoomStats()
        for requirement in context.variables.lab.requirements.values():
            if not config.matches_requirement(requirement):
                continue
            stats.targeted_courses += 1
            added_constraint = False
            for _, _, _, _, room_id, var in iter_lab_session_variables(
                context, course_instance_id=requirement.course_instance_id
            ):
                if room_id not in config.allowed_room_ids:
                    context.model.Add(var == 0)
                    stats.forbidden_assignments += 1
                    added_constraint = True
            if added_constraint:
                stats.constrained_courses += 1
            else:
                stats.unconstrained_courses.append(requirement.course_instance_id)

        status = ConstraintStatus.APPLIED if stats.forbidden_assignments else ConstraintStatus.SKIPPED
        return ConstraintApplicationResult(
            name=self.metadata.name,
            domain=self.metadata.category,
            priority=self.metadata.priority,
            enabled=True,
            status=status,
            details={
                "targeted_courses": stats.targeted_courses,
                "constrained_courses": stats.constrained_courses,
                "forbidden_assignments": stats.forbidden_assignments,
                "unconstrained_courses": tuple(stats.unconstrained_courses),
                "allowed_room_ids": config.allowed_room_ids,
                "missing_tokens": config.missing_tokens,
            },
        )


def _resolve_room_ids(context: ConstraintContext, tokens: Sequence[str]) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    registry = getattr(context.data.raw, "room_registry", {}) or {}
    lab_room_ids = {str(room_id) for room_id in getattr(context.variables.lab, "room_ids", tuple())}
    resolved = set()
    missing: list[str] = []

    for token in tokens:
        if not token:
            continue
        normalized = _normalize(token)
        if not normalized:
            continue
        matched_id: Optional[str] = None
        for room_id, attrs in registry.items():
            candidates = [room_id]
            candidates.extend([
                attrs.get("room_number"),
                attrs.get("room_name"),
                attrs.get("description"),
            ])
            for candidate in candidates:
                if candidate is None:
                    continue
                if _normalize(candidate) == normalized:
                    matched_id = str(room_id)
                    break
            if matched_id:
                break
        if matched_id and matched_id in lab_room_ids:
            resolved.add(matched_id)
        else:
            missing.append(token)

    return tuple(sorted(resolved)), tuple(missing)


def _matches_keyword(requirement, keywords: Sequence[str]) -> bool:
    if not keywords:
        return True
    haystack_parts = []
    for value in (
        getattr(requirement, "required_room_type", None),
        getattr(requirement, "preferred_room_type", None),
    ):
        if value:
            haystack_parts.append(str(value))
    tags = getattr(requirement, "tags", None) or ()
    haystack_parts.extend(str(tag) for tag in tags)
    if not haystack_parts:
        return False
    haystack = " ".join(haystack_parts).lower()
    return any(keyword in haystack for keyword in keywords)


def _normalize(value: object) -> str:
    text = str(value or "").lower()
    return "".join(ch for ch in text if ch.isalnum())


def build_first_year_computer_lab_constraint(
    metadata: ConstraintMetadata,
    *,
    params: Optional[Mapping[str, object]] = None,
) -> FirstYearComputerLabConstraint:
    """Factory helper used by the registry."""

    return FirstYearComputerLabConstraint(metadata=metadata, params=params)


__all__ = [
    "FirstYearComputerLabConstraint",
    "build_first_year_computer_lab_constraint",
]
