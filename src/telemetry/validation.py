"""Telemetry builders that project validation issues into dashboard-friendly payloads."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Optional, Sequence

from ..runtime.validator import ValidationIssue, ValidationReport


@dataclass
class ValidationTelemetryBuilder:
    """Summarise schedule-validator output for room and LTPC monitoring."""

    report: ValidationReport
    day_labels: Sequence[str] = ()
    timestamp: Optional[datetime] = None

    def build(self) -> Mapping[str, Any]:
        bucket = _bucket_issues(self.report.issues)
        room_conflicts = _build_room_conflicts(
            bucket.get("lab_room_conflict", ()),
            bucket.get("theory_room_conflict", ()),
            self.day_labels,
        )
        ltp_presence = _build_ltp_presence(bucket.get("ltp_presence", ()))
        return {
            "generated_at": (self.timestamp or datetime.now(timezone.utc)).isoformat(),
            "executed_checks": list(self.report.executed_checks),
            "severity_counts": dict(self.report.severity_counts),
            "room_conflicts": room_conflicts,
            "ltp_presence": ltp_presence,
        }

    def write(self, destination: Path) -> Path:
        payload = self.build()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return destination


def _bucket_issues(issues: Iterable[ValidationIssue]) -> Mapping[str, Sequence[ValidationIssue]]:
    bucket: MutableMapping[str, list[ValidationIssue]] = {}
    for issue in issues:
        bucket.setdefault(issue.category, []).append(issue)
    return bucket


def _build_room_conflicts(
    lab_issues: Sequence[ValidationIssue],
    theory_issues: Sequence[ValidationIssue],
    day_labels: Sequence[str],
) -> Mapping[str, Any]:
    conflicts: list[Mapping[str, Any]] = []
    lab_count = 0
    theory_count = 0
    for issue in lab_issues:
        conflicts.append(_format_room_conflict(issue, day_labels, "lab"))
        lab_count += 1
    for issue in theory_issues:
        conflicts.append(_format_room_conflict(issue, day_labels, "theory"))
        theory_count += 1
    conflicts.sort(
        key=lambda entry: (
            str(entry.get("room_id") or ""),
            entry.get("day_index") or 0,
            str(entry.get("window_label") or ""),
            entry.get("window_type") or "",
        )
    )
    rooms_impacted = {entry.get("room_id") for entry in conflicts if entry.get("room_id")}
    conflict_windows = {
        (entry.get("room_id"), entry.get("day_index"), entry.get("window_label"), entry.get("window_type"))
        for entry in conflicts
    }
    return {
        "summary": {
            "conflict_count": len(conflicts),
            "rooms_impacted": len(rooms_impacted),
            "windows_impacted": len(conflict_windows),
            "lab_conflicts": lab_count,
            "theory_conflicts": theory_count,
        },
        "conflicts": conflicts,
    }


def _format_room_conflict(
    issue: ValidationIssue,
    day_labels: Sequence[str],
    kind: str,
) -> Mapping[str, Any]:
    context = dict(issue.context)
    day_index = _to_int(context.get("day_index"))
    label = context.get("day_label") or _day_label(day_index, day_labels)
    window_label = context.get("session") or context.get("slot_label")
    return {
        "room_id": context.get("room_id"),
        "day_index": day_index,
        "day_label": label,
        "window_label": window_label,
        "window_type": kind,
        "session": context.get("session"),
        "slot_index": _to_int(context.get("slot_index")),
        "slot_label": context.get("slot_label"),
        "course_instance_ids": list(context.get("course_instance_ids", []) or []),
        "group_ids": list(context.get("group_ids", []) or []),
        "severity": issue.severity,
        "message": issue.message,
    }


def _build_ltp_presence(issues: Sequence[ValidationIssue]) -> Mapping[str, Any]:
    lab_gaps: list[Mapping[str, Any]] = []
    theory_gaps: list[Mapping[str, Any]] = []
    for issue in issues:
        context = dict(issue.context)
        entry = {
            "course_instance_id": context.get("course_instance_id"),
            "course_code": context.get("course_code"),
            "department": context.get("department"),
            "semester": context.get("semester"),
            "group_id": context.get("group_id"),
            "expected_hours": _to_int(context.get("expected_hours")),
            "message": issue.message,
            "severity": issue.severity,
        }
        if entry["expected_hours"]:
            theory_gaps.append(entry)
        else:
            lab_gaps.append(entry)
    lab_gaps.sort(key=lambda item: (item.get("department") or "", item.get("course_instance_id") or ""))
    theory_gaps.sort(key=lambda item: (item.get("department") or "", item.get("group_id") or ""))
    return {
        "summary": {
            "lab_gaps": len(lab_gaps),
            "theory_gaps": len(theory_gaps),
        },
        "lab_gaps": lab_gaps,
        "theory_gaps": theory_gaps,
    }


def _day_label(index: Optional[int], day_labels: Sequence[str]) -> Optional[str]:
    if index is None:
        return None
    if 0 <= index < len(day_labels):
        return day_labels[index]
    return f"Day {index + 1}"


def _to_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = ["ValidationTelemetryBuilder"]
