"""Utility layer for discovering schedule snapshots and building derived payloads."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Literal, Mapping, MutableMapping, Optional, Sequence, Tuple

DAY_ORDER = ("monday", "tuesday", "wed", "thur", "fri", "saturday")


@dataclass(frozen=True)
class ScheduleSnapshot:
    """Metadata describing a generated schedule artifact inside /output."""

    root: Path
    label: str
    data_kind: Literal["monolithic", "combined"]
    schedule_path: Optional[Path]
    lab_path: Optional[Path]
    theory_path: Optional[Path]
    modified_at: float

    def as_dict(self) -> Dict[str, Any]:
        return {
            "folder": self.label,
            "path": str(self.root),
            "data_kind": self.data_kind,
            "generated_at": datetime.fromtimestamp(self.modified_at, tz=timezone.utc).isoformat(),
        }


class ScheduleRepository:
    """Central accessor that lazily loads the latest solver output."""

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir
        self._output_dir = base_dir / "output"
        self._cached_snapshot: Optional[ScheduleSnapshot] = None
        self._schedule_cache: Dict[Path, Dict[str, Sequence[Mapping[str, Any]]]] = {}
        self._room_cache: Dict[Path, Dict[str, Any]] = {}
        self._metric_cache: Dict[Path, Dict[str, Any]] = {}
        self._slot_cap_cache: Dict[Path, Dict[str, Any]] = {}
        self._teacher_telemetry_cache: Dict[Path, Dict[str, Any]] = {}
        self._grouping_cache: Dict[Path, Dict[str, Any]] = {}
        self._overlap_cache: Dict[Path, Dict[str, Any]] = {}
        self._validation_cache: Dict[Path, Dict[str, Any]] = {}
        self._solver_metrics_cache: Dict[Path, Dict[str, Any]] = {}
        self._warm_start_cache: Dict[Path, Dict[str, Any]] = {}

    def get_latest_snapshot(self) -> ScheduleSnapshot:
        snapshot = self._scan_latest_snapshot()
        cached = self._cached_snapshot
        if not cached or cached.root != snapshot.root or cached.modified_at != snapshot.modified_at:
            # Snapshot changed – purge derived caches so subsequent requests rehydrate.
            self._schedule_cache.clear()
            self._room_cache.clear()
            self._metric_cache.clear()
            self._slot_cap_cache.clear()
            self._teacher_telemetry_cache.clear()
            self._grouping_cache.clear()
            self._overlap_cache.clear()
            self._validation_cache.clear()
            self._solver_metrics_cache.clear()
            self._warm_start_cache.clear()
            self._cached_snapshot = snapshot
        return self._cached_snapshot  # type: ignore[return-value]

    def get_schedule(self) -> Dict[str, Sequence[Mapping[str, Any]]]:
        snapshot = self.get_latest_snapshot()
        if snapshot.root not in self._schedule_cache:
            self._schedule_cache[snapshot.root] = self._load_schedule(snapshot)
        return self._schedule_cache[snapshot.root]

    def get_rooms(self) -> Dict[str, Any]:
        snapshot = self.get_latest_snapshot()
        if snapshot.root not in self._room_cache:
            schedule = self.get_schedule()
            self._room_cache[snapshot.root] = self._build_room_payload(schedule)
        return self._room_cache[snapshot.root]

    def get_metrics(self) -> Dict[str, Any]:
        snapshot = self.get_latest_snapshot()
        if snapshot.root not in self._metric_cache:
            schedule = self.get_schedule()
            self._metric_cache[snapshot.root] = self._build_metrics(schedule, snapshot)
        return self._metric_cache[snapshot.root]

    def get_slot_cap_telemetry(self) -> Dict[str, Any]:
        snapshot = self.get_latest_snapshot()
        if snapshot.root not in self._slot_cap_cache:
            self._slot_cap_cache[snapshot.root] = self._load_slot_cap_telemetry(snapshot)
        return self._slot_cap_cache[snapshot.root]

    def get_teacher_lab_telemetry(self) -> Dict[str, Any]:
        snapshot = self.get_latest_snapshot()
        if snapshot.root not in self._teacher_telemetry_cache:
            self._teacher_telemetry_cache[snapshot.root] = self._load_teacher_lab_telemetry(snapshot)
        return self._teacher_telemetry_cache[snapshot.root]

    def get_grouping_telemetry(self) -> Dict[str, Any]:
        snapshot = self.get_latest_snapshot()
        if snapshot.root not in self._grouping_cache:
            self._grouping_cache[snapshot.root] = self._load_grouping_telemetry(snapshot)
        return self._grouping_cache[snapshot.root]

    def get_overlap_telemetry(self) -> Dict[str, Any]:
        snapshot = self.get_latest_snapshot()
        if snapshot.root not in self._overlap_cache:
            self._overlap_cache[snapshot.root] = self._load_overlap_telemetry(snapshot)
        return self._overlap_cache[snapshot.root]

    def get_validation_telemetry(self) -> Dict[str, Any]:
        snapshot = self.get_latest_snapshot()
        if snapshot.root not in self._validation_cache:
            self._validation_cache[snapshot.root] = self._load_validation_telemetry(snapshot)
        return self._validation_cache[snapshot.root]

    def get_solver_metrics(self) -> Dict[str, Any]:
        snapshot = self.get_latest_snapshot()
        if snapshot.root not in self._solver_metrics_cache:
            self._solver_metrics_cache[snapshot.root] = self._load_solver_metrics(snapshot)
        return self._solver_metrics_cache[snapshot.root]

    def get_warm_start_snapshot_summary(self) -> Dict[str, Any]:
        snapshot = self.get_latest_snapshot()
        if snapshot.root not in self._warm_start_cache:
            self._warm_start_cache[snapshot.root] = self._load_warm_start_snapshot_summary(snapshot)
        return self._warm_start_cache[snapshot.root]

    # ------------------------------------------------------------------
    # Snapshot discovery
    # ------------------------------------------------------------------
    def _scan_latest_snapshot(self) -> ScheduleSnapshot:
        if not self._output_dir.exists():
            raise FileNotFoundError("Output directory not found – generate a schedule first.")

        candidates: List[ScheduleSnapshot] = []
        for child in self._output_dir.iterdir():
            if not child.is_dir():
                continue

            schedule_path = child / "schedule.json"
            if schedule_path.exists():
                candidates.append(
                    ScheduleSnapshot(
                        root=child,
                        label=child.name,
                        data_kind="monolithic",
                        schedule_path=schedule_path,
                        lab_path=None,
                        theory_path=None,
                        modified_at=schedule_path.stat().st_mtime,
                    )
                )
                continue

            lab_path = child / "combined_lab_schedule.json"
            theory_path = child / "combined_theory_schedule.json"
            if lab_path.exists() and theory_path.exists():
                candidates.append(
                    ScheduleSnapshot(
                        root=child,
                        label=child.name,
                        data_kind="combined",
                        schedule_path=None,
                        lab_path=lab_path,
                        theory_path=theory_path,
                        modified_at=max(lab_path.stat().st_mtime, theory_path.stat().st_mtime),
                    )
                )

        if not candidates:
            raise FileNotFoundError("No schedule snapshots found in the output directory.")

        candidates.sort(key=lambda snap: snap.modified_at, reverse=True)
        return candidates[0]

    # ------------------------------------------------------------------
    # Loaders & builders
    # ------------------------------------------------------------------
    def _load_schedule(self, snapshot: ScheduleSnapshot) -> Dict[str, Sequence[Mapping[str, Any]]]:
        if snapshot.data_kind == "monolithic":
            assert snapshot.schedule_path is not None
            with snapshot.schedule_path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            lab_entries: Sequence[Mapping[str, Any]] = payload.get("lab_entries", [])
            theory_entries: Sequence[Mapping[str, Any]] = payload.get("theory_entries", [])
            return {"lab_entries": lab_entries, "theory_entries": theory_entries}

        assert snapshot.lab_path is not None and snapshot.theory_path is not None
        with snapshot.lab_path.open("r", encoding="utf-8") as lab_handle:
            lab_entries = json.load(lab_handle)
        with snapshot.theory_path.open("r", encoding="utf-8") as theory_handle:
            theory_entries = json.load(theory_handle)
        return {"lab_entries": lab_entries, "theory_entries": theory_entries}

    def _build_room_payload(
        self, schedule: Mapping[str, Sequence[Mapping[str, Any]]]
    ) -> Dict[str, Any]:
        rooms: Dict[str, MutableMapping[str, Any]] = {}
        unassigned: List[Mapping[str, Any]] = []
        lab_entries = schedule.get("lab_entries", [])
        theory_entries = schedule.get("theory_entries", [])

        for source in (lab_entries, theory_entries):
            for entry in source:
                room_number = entry.get("room_number") or "TBD"
                room_id = entry.get("room_id") or ""
                block = entry.get("block") or "Unknown Block"
                schedule_type = entry.get("schedule_type", "theory").lower()
                container = rooms.setdefault(
                    room_number,
                    {
                        "room_id": room_id,
                        "room_number": room_number,
                        "block": block,
                        "capacity": entry.get("capacity"),
                        "room_types": set(),
                        "sessions": [],
                    },
                )

                if not container.get("capacity") and entry.get("capacity"):
                    container["capacity"] = entry.get("capacity")

                normalized_session = {
                    "day": entry.get("day"),
                    "room_number": room_number,
                    "block": block,
                    "time_label": entry.get("time_slot")
                    or entry.get("time_range")
                    or entry.get("session_name"),
                    "course_code": entry.get("course_code"),
                    "course_name": entry.get("course_name"),
                    "group_name": entry.get("group_name"),
                    "department": entry.get("department"),
                    "semester": entry.get("semester"),
                    "teacher_name": entry.get("teacher_name"),
                    "teacher_id": entry.get("teacher_id"),
                    "staff_code": entry.get("staff_code"),
                    "schedule_type": schedule_type,
                    "session_kind": entry.get("session_type"),
                    "session_number": entry.get("session_number"),
                    "day_pattern": entry.get("day_pattern"),
                    "course_instance_id": entry.get("course_instance_id"),
                    "partner_instance_id": entry.get("partner_instance_id"),
                    "delivery_mode": entry.get("delivery_mode"),
                    "bundle_id": entry.get("bundle_id"),
                    "bundle_group_id": entry.get("bundle_group_id"),
                    "bundle_label": entry.get("bundle_label"),
                    "bundle_course_codes": entry.get("bundle_course_codes"),
                    "bundle_teacher_ids": entry.get("bundle_teacher_ids"),
                    "half_index": entry.get("half_index"),
                    "half_minutes": entry.get("half_minutes"),
                    "half_time": entry.get("half_time"),
                    "partner_course_code": entry.get("partner_course_code"),
                    "partner_teacher_id": entry.get("partner_teacher_id"),
                    "partner_teacher_name": entry.get("partner_teacher_name"),
                    "pairing_score": entry.get("pairing_score"),
                    "selection_mode": entry.get("selection_mode"),
                }

                if room_number == "TBD" and not entry.get("room_id"):
                    unassigned.append(normalized_session)
                    continue

                container["room_types"].add(schedule_type)
                container["sessions"].append(normalized_session)

        room_list: List[Dict[str, Any]] = []
        for record in rooms.values():
            sessions = record["sessions"]
            day_count = len({session["day"] for session in sessions if session.get("day")})
            physical_session_count = self._count_physical_room_sessions(sessions)
            record["session_count"] = physical_session_count
            record["utilization"] = self._estimate_room_utilization(physical_session_count, day_count)
            record["room_type"] = self._derive_room_type(record["room_types"])
            record.pop("room_types", None)
            # Sort sessions chronologically for that room
            record["sessions"] = sorted(
                sessions,
                key=lambda sess: (self._day_index(sess.get("day")), self._time_sort_key(sess.get("time_label"))),
            )
            room_list.append(dict(record))

        room_list.sort(key=lambda item: (item.get("block", ""), item.get("room_number", "")))
        return {"rooms": room_list, "unassigned": unassigned, "day_order": list(DAY_ORDER)}

    @staticmethod
    def _count_physical_room_sessions(sessions: Sequence[Mapping[str, Any]]) -> int:
        physical_keys = set()
        for index, session in enumerate(sessions):
            if session.get("delivery_mode") == "kutty_25x2" and session.get("bundle_id"):
                physical_keys.add(
                    (
                        "kutty",
                        session.get("bundle_id"),
                        session.get("day"),
                        session.get("time_label"),
                    )
                )
            else:
                physical_keys.add(("standard", index))
        return len(physical_keys)

    def _build_metrics(
        self, schedule: Mapping[str, Sequence[Mapping[str, Any]]], snapshot: ScheduleSnapshot
    ) -> Dict[str, Any]:
        labs = list(schedule.get("lab_entries", []))
        theory = list(schedule.get("theory_entries", []))
        all_sessions = labs + theory

        department_set = {entry.get("department") for entry in all_sessions if entry.get("department")}
        teacher_set = {entry.get("teacher_id") or entry.get("teacher_name") for entry in all_sessions}
        group_set = {entry.get("group_name") for entry in all_sessions if entry.get("group_name")}
        room_set = {
            (entry.get("room_number") or "TBD", entry.get("block") or "Unknown Block")
            for entry in all_sessions
            if entry.get("room_number") or entry.get("room_id")
        }

        day_distribution = Counter(entry.get("day") for entry in all_sessions if entry.get("day"))
        department_load = Counter(entry.get("department") for entry in all_sessions if entry.get("department"))
        semester_load = Counter(entry.get("semester") for entry in all_sessions if entry.get("semester"))
        slot_distribution = Counter(self._time_label(entry) for entry in all_sessions)

        busiest_day = self._most_common(day_distribution)
        busiest_slot = self._most_common(slot_distribution)

        top_rooms = self._top_n_rooms(all_sessions, limit=5)

        return {
            "snapshot": snapshot.as_dict(),
            "totals": {
                "sessions": len(all_sessions),
                "labs": len(labs),
                "theory": len(theory),
                "departments": len(department_set),
                "teachers": len(teacher_set),
                "groups": len(group_set),
                "rooms_used": len(room_set),
            },
            "day_distribution": self._counter_to_series(day_distribution, DAY_ORDER),
            "department_load": self._counter_to_series(department_load),
            "semester_load": self._counter_to_series(semester_load, sort_numeric=True),
            "slot_distribution": self._counter_to_series(slot_distribution),
            "highlights": {
                "busiest_day": busiest_day,
                "peak_slot": busiest_slot,
                "top_rooms": top_rooms,
            },
        }

    def _load_slot_cap_telemetry(self, snapshot: ScheduleSnapshot) -> Dict[str, Any]:
        telemetry_path = snapshot.root / "slot_caps_telemetry.json"
        if not telemetry_path.exists():
            return {
                "generated_at": None,
                "summary": {"groups_monitored": 0, "groups_over_limit": 0, "semesters_over_limit": 0},
                "core_groups": [],
                "computing_groups": [],
                "semesters": [],
                "limits": {},
                "constraints": {},
            }
        with telemetry_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _load_teacher_lab_telemetry(self, snapshot: ScheduleSnapshot) -> Dict[str, Any]:
        telemetry_path = snapshot.root / "teacher_lab_telemetry.json"
        if not telemetry_path.exists():
            return {
                "generated_at": None,
                "policies": {},
                "summary": {
                    "teachers_in_schedule": 0,
                    "days_monitored": 0,
                    "days_over_daily_cap": 0,
                    "teachers_over_daily_cap": 0,
                    "early_late_conflicts": 0,
                    "triple_blocks": 0,
                    "teachers_long_consecutive": 0,
                    "long_consecutive_windows": 0,
                },
                "teachers": [],
                "constraints": {},
            }
        with telemetry_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _load_grouping_telemetry(self, snapshot: ScheduleSnapshot) -> Dict[str, Any]:
        telemetry_path = snapshot.root / "grouping_telemetry.json"
        if not telemetry_path.exists():
            return {
                "generated_at": None,
                "summary": {
                    "total_groups": 0,
                    "departments": 0,
                    "groups_without_lab_sessions": 0,
                    "groups_without_theory_slots": 0,
                },
                "departments": [],
                "constraints": {},
            }
        with telemetry_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _load_overlap_telemetry(self, snapshot: ScheduleSnapshot) -> Dict[str, Any]:
        telemetry_path = snapshot.root / "overlap_telemetry.json"
        if not telemetry_path.exists():
            return {
                "generated_at": None,
                "group_summary": {
                    "dept_semesters": 0,
                    "conflict_windows": 0,
                    "departments_impacted": 0,
                },
                "group_conflicts": [],
                "teacher_summary": {
                    "teachers_with_conflicts": 0,
                    "conflict_windows": 0,
                },
                "teacher_conflicts": [],
                "constraints": {},
            }
        with telemetry_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _load_validation_telemetry(self, snapshot: ScheduleSnapshot) -> Dict[str, Any]:
        telemetry_path = snapshot.root / "validation_telemetry.json"
        if not telemetry_path.exists():
            return {
                "generated_at": None,
                "executed_checks": [],
                "severity_counts": {},
                "room_conflicts": {
                    "summary": {
                        "conflict_count": 0,
                        "rooms_impacted": 0,
                        "windows_impacted": 0,
                    },
                    "conflicts": [],
                },
                "ltp_presence": {
                    "summary": {
                        "lab_gaps": 0,
                        "theory_gaps": 0,
                    },
                    "lab_gaps": [],
                    "theory_gaps": [],
                },
            }
        with telemetry_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _load_solver_metrics(self, snapshot: ScheduleSnapshot) -> Dict[str, Any]:
        metrics_path = snapshot.root / "solver_metrics.json"
        if not metrics_path.exists():
            return {
                "generated_at": None,
                "run_label": snapshot.label,
                "solver": {
                    "status": None,
                    "status_code": None,
                    "wall_time": None,
                    "objective_value": None,
                    "best_bound": None,
                    "gap": None,
                    "solution_count": None,
                },
                "model": {},
            }
        with metrics_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _load_warm_start_snapshot_summary(self, snapshot: ScheduleSnapshot) -> Dict[str, Any]:
        snapshot_path = snapshot.root / "warm_start_snapshot.json"
        if not snapshot_path.exists():
            return {
                "generated_at": None,
                "available": False,
                "metadata": {},
                "counts": {"lab": 0, "theory": 0},
            }

        with snapshot_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)

        metadata = payload.get("metadata") or {}
        lab_assignments = payload.get("lab_assignments") or []
        theory_assignments = payload.get("theory_assignments") or []
        created_at = metadata.get("created_at")

        return {
            "generated_at": created_at,
            "available": True,
            "metadata": metadata,
            "counts": {"lab": len(lab_assignments), "theory": len(theory_assignments)},
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _time_label(entry: Mapping[str, Any]) -> str:
        return (
            entry.get("time_slot")
            or entry.get("time_range")
            or entry.get("session_name")
            or "Unscheduled"
        )

    @staticmethod
    def _derive_room_type(room_types: Iterable[str]) -> str:
        unique = {item for item in room_types if item}
        if not unique:
            return "unknown"
        if len(unique) == 1:
            return next(iter(unique))
        return "mixed"

    @staticmethod
    def _estimate_room_utilization(session_count: int, day_count: int) -> float:
        # Assume ~10 usable slots per day for a rough utilization signal.
        total_slots = max(day_count, 1) * 10
        return round(min(session_count / total_slots * 100, 100), 1)

    @staticmethod
    def _day_index(day: Optional[str]) -> int:
        if not day:
            return len(DAY_ORDER)
        try:
            return DAY_ORDER.index(day)
        except ValueError:
            return len(DAY_ORDER)

    @staticmethod
    def _time_sort_key(label: Optional[str]) -> Tuple[int, int]:
        if not label:
            return (99, 99)
        parts = label.split("-", 1)
        start = parts[0].strip()
        hour_minute = start.split(":")
        if len(hour_minute) == 2:
            hour = int(hour_minute[0])
            minute = int(hour_minute[1])
        else:
            hour = 0
            minute = 0
        return (hour, minute)

    @staticmethod
    def _counter_to_series(counter: Counter, order: Optional[Iterable[Any]] = None, *, sort_numeric: bool = False) -> List[Dict[str, Any]]:
        items: List[Tuple[Any, int]] = []
        if order:
            for key in order:
                items.append((key, counter.get(key, 0)))
        else:
            items = list(counter.items())
            if sort_numeric:
                items.sort(key=lambda kv: (0 if isinstance(kv[0], int) else 1, kv[0]))
            else:
                items.sort(key=lambda kv: kv[1], reverse=True)
        return [{"label": key, "value": value} for key, value in items]

    @staticmethod
    def _most_common(counter: Counter) -> Optional[Dict[str, Any]]:
        if not counter:
            return None
        label, value = counter.most_common(1)[0]
        return {"label": label, "value": value}

    @staticmethod
    def _top_n_rooms(entries: Sequence[Mapping[str, Any]], limit: int = 5) -> List[Dict[str, Any]]:
        room_counter: Counter = Counter()
        for entry in entries:
            room_number = entry.get("room_number") or entry.get("room_id")
            if not room_number:
                continue
            room_counter[room_number] += 1
        return [
            {"room": room, "sessions": count}
            for room, count in room_counter.most_common(limit)
        ]


__all__ = ["ScheduleRepository", "ScheduleSnapshot"]
