"""Load blocking masks from a partial schedule (CSV) and block department slots.

This constraint loads an existing CSV schedule (e.g. a partial one) and:
1. Identifies department slots occupied by configured high-priority courses.
2. Blocks those slots for the entire department to prevent conflicts.
3. Optionally locks other assignments found in the CSV.
"""

from __future__ import annotations

import csv
import logging
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence, Set, Tuple

from ortools.sat.python import cp_model

from ..base import Constraint, ConstraintMetadata
from ..context import ConstraintContext
from ..schema import ConstraintApplicationResult, ConstraintStatus
from ..utils import (
    ensure_extra_bucket,
    iter_course_timeslot_variables,
    iter_lab_session_variables,
    iter_theory_room_variables,
)
from ...utils.time_utils import DayNormalizer, TimeParser

LOGGER = logging.getLogger(__name__)


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


@dataclass(frozen=True)
class DeptSlotBlockingSettings:
    lab_csv_path: Optional[Path] = None
    theory_csv_path: Optional[Path] = None
    lock_assignments: bool = True
    block_rooms: bool = True
    block_teachers: bool = True
    block_teachers_across_domains: bool = True
    block_dept_slots: bool = False
    block_dept_slots_lab: bool = True
    block_dept_slots_theory: bool = True
    block_dept_slots_course_codes: Tuple[str, ...] = ()
    lock_blocking_assignments: bool = False

    @classmethod
    def from_params(cls, params: Mapping[str, object]) -> "DeptSlotBlockingSettings":
        raw_lab_csv = str(params.get("lab_csv_path") or "").strip()
        raw_theory_csv = str(params.get("theory_csv_path") or "").strip()
        raw_codes = params.get("block_dept_slots_course_codes") or ()
        codes: Tuple[str, ...] = tuple(
            str(code).strip().upper() for code in raw_codes if str(code).strip()
        ) if isinstance(raw_codes, Iterable) else ()
        return cls(
            lab_csv_path=Path(raw_lab_csv) if raw_lab_csv else None,
            theory_csv_path=Path(raw_theory_csv) if raw_theory_csv else None,
            lock_assignments=_as_bool(params.get("lock_assignments"), True),
            block_rooms=_as_bool(params.get("block_rooms"), True),
            block_teachers=_as_bool(params.get("block_teachers"), True),
            block_teachers_across_domains=_as_bool(
                params.get("block_teachers_across_domains"), True
            ),
            block_dept_slots=_as_bool(params.get("block_dept_slots"), False),
            block_dept_slots_lab=_as_bool(params.get("block_dept_slots_lab"), True),
            block_dept_slots_theory=_as_bool(params.get("block_dept_slots_theory"), True),
            block_dept_slots_course_codes=codes,
            lock_blocking_assignments=_as_bool(
                params.get("lock_blocking_assignments"), False
            ),
        )


class DeptSlotBlockingConstraint(Constraint):
    """Freeze assignments from a partial CSV schedule and apply related blocks."""

    def __init__(self, metadata: ConstraintMetadata, params: Optional[Mapping[str, object]] = None) -> None:
        super().__init__(metadata, params=params)
        self._settings = DeptSlotBlockingSettings.from_params(self.params)
        self._logger = LOGGER.getChild("dept_slot_blocking")

    def apply(self, context: ConstraintContext) -> ConstraintApplicationResult:
        settings = self._settings
        
        # Check if CSV paths are provided
        if not settings.lab_csv_path and not settings.theory_csv_path:
             return self._result(
                ConstraintStatus.SKIPPED,
                {"reason": "no_csv_paths_provided"},
            )

        lab_records, theory_records, source_info = self._load_from_csv(settings)
        if not lab_records and not theory_records:
            return self._result(
                ConstraintStatus.SKIPPED,
                {"reason": "csv_files_empty_or_missing", "source_info": source_info},
            )

        self._logger.info(
            "Dept slot blocking loader loading from %s (lab=%d, theory=%d)",
            source_info,
            len(lab_records),
            len(theory_records),
        )

        model = context.model
        stats = {
            "source_info": source_info,
            "source_lab_records": len(lab_records),
            "source_theory_records": len(theory_records),
            "locked_lab": 0,
            "locked_theory": 0,
            "blocked_lab_room_vars": 0,
            "blocked_theory_room_vars": 0,
            "blocked_lab_teacher_vars": 0,
            "blocked_theory_teacher_vars": 0,
            "blocked_cross_domain_teacher_vars": 0,
            "blocked_dept_lab_vars": 0,
            "blocked_dept_theory_vars": 0,
            "blocked_dept_group_theory_vars": 0,
            "missing_lab_vars": 0,
            "missing_theory_vars": 0,
        }

        allowed_lab_keys: Set[Tuple[str, str, str, str, str]] = set()
        allowed_theory_room_keys: Set[Tuple[str, str, str, int, str]] = set()
        allowed_theory_slot_keys: Set[Tuple[str, str, str, int]] = set()

        occupied_lab_rooms: Set[Tuple[str, str, str]] = set()
        occupied_lab_teachers: Set[Tuple[str, str, str]] = set()
        occupied_theory_rooms: Set[Tuple[str, int, str]] = set()
        occupied_theory_teachers: Set[Tuple[str, str, int]] = set()
        dept_lab_slots: dict[str, Set[Tuple[str, str]]] = defaultdict(set)
        dept_lab_slot_ranges: dict[str, Set[Tuple[str, str, str]]] = defaultdict(set)

        for record in lab_records:
            teacher_id = str(record.get("teacher_id") or "").strip()
            course_id = str(record.get("course_instance_id") or "").strip()
            session_name = str(record.get("session_name") or "").strip()
            room_id = str(record.get("room_id") or "").strip()
            day_label = self._normalize_day_label(record.get("day"))
            if not day_label:
                day_index = _safe_int(record.get("day_index"))
                if day_index is not None and course_id:
                    day_label = self._resolve_var_day_label(
                        context,
                        day_patterns=context.variables.lab.day_patterns,
                        course_id=course_id,
                        day_index=day_index,
                    )
            if not teacher_id or not session_name or not room_id or not day_label:
                continue
            occupied_lab_rooms.add((day_label, session_name, room_id))
            occupied_lab_teachers.add((teacher_id, day_label, session_name))
            if teacher_id and course_id:
                allowed_lab_keys.add((teacher_id, course_id, day_label, session_name, room_id))

            if settings.block_dept_slots and settings.block_dept_slots_course_codes:
                course_code = str(record.get("course_code") or "").strip().upper()
                if course_code in settings.block_dept_slots_course_codes:
                    dept = str(record.get("department") or "").strip()
                    if dept:
                        dept_key = self._normalise_department(dept)
                        dept_lab_slots[dept_key].add((day_label, session_name))
                        time_range = str(record.get("time_range") or "").strip()
                        if time_range:
                            dept_lab_slot_ranges[dept_key].add((day_label, session_name, time_range))

        for record in theory_records:
            teacher_id = str(record.get("teacher_id") or "").strip()
            course_id = str(record.get("course_instance_id") or "").strip()
            room_id = str(record.get("room_id") or "").strip()
            day_label = self._normalize_day_label(record.get("day"))
            if not day_label:
                day_index = _safe_int(record.get("day_index"))
                if day_index is not None and course_id:
                    theory_patterns = getattr(context.variables.theory, "course_day_patterns", {}) or {}
                    day_label = self._resolve_var_day_label(
                        context,
                        day_patterns=theory_patterns,
                        course_id=course_id,
                        day_index=day_index,
                    )
            slot_index = _safe_int(record.get("slot_index"))
            if not teacher_id or not room_id or not day_label or slot_index is None:
                continue
            occupied_theory_rooms.add((day_label, slot_index, room_id))
            occupied_theory_teachers.add((teacher_id, day_label, slot_index))
            if teacher_id and course_id:
                allowed_theory_room_keys.add((teacher_id, course_id, day_label, slot_index, room_id))
                allowed_theory_slot_keys.add((teacher_id, course_id, day_label, slot_index))
            
            # FUTURE: Theory side blocking for dept slots if needed (not implemented in original logic fully yet)

        # 1) Lock explicit assignments.
        if settings.lock_assignments:
            stats["locked_lab"] = self._lock_lab_assignments(
                context,
                model,
                lab_records,
                settings,
            )
            stats["locked_theory"] = self._lock_theory_assignments(
                context,
                model,
                theory_records,
                settings,
            )

            missing_bucket = context.extra.get("dept_slot_blocking_missing")
            if isinstance(missing_bucket, Mapping):
                stats["missing_lab_vars"] = int(missing_bucket.get("lab", 0) or 0)
                stats["missing_theory_vars"] = int(missing_bucket.get("theory", 0) or 0)

        # 2) Block conflicting room usage.
        if settings.block_rooms and occupied_lab_rooms:
            blocked = 0
            for tid, cid, day_idx, session_name, room_id, var in iter_lab_session_variables(context):
                var_day = self._resolve_var_day_label(
                    context,
                    day_patterns=context.variables.lab.day_patterns,
                    course_id=cid,
                    day_index=day_idx,
                )
                if (var_day, str(session_name).strip(), str(room_id).strip()) in occupied_lab_rooms:
                     # Skip if allowed
                    if (str(tid).strip(), str(cid).strip(), var_day, str(session_name).strip(), str(room_id).strip()) in allowed_lab_keys:
                        continue
                    model.Add(var == 0)
                    blocked += 1
            stats["blocked_lab_room_vars"] = blocked

        if settings.block_rooms and occupied_theory_rooms:
            blocked = 0
            for tid, cid, day_idx, slot_idx, room_id, var in iter_theory_room_variables(context):
                theory_patterns = getattr(context.variables.theory, "course_day_patterns", {}) or {}
                var_day = self._resolve_var_day_label(
                    context,
                    day_patterns=theory_patterns,
                    course_id=cid,
                    day_index=day_idx,
                )
                if (var_day, slot_idx, str(room_id).strip()) in occupied_theory_rooms:
                    if (str(tid).strip(), str(cid).strip(), var_day, slot_idx, str(room_id).strip()) in allowed_theory_room_keys:
                        continue
                    model.Add(var == 0)
                    blocked += 1
            stats["blocked_theory_room_vars"] = blocked

        # 3) Block conflicting teacher usage.
        if settings.block_teachers and occupied_lab_teachers:
            blocked = 0
            for tid, cid, day_idx, session_name, room_id, var in iter_lab_session_variables(context):
                var_day = self._resolve_var_day_label(
                    context,
                    day_patterns=context.variables.lab.day_patterns,
                    course_id=cid,
                    day_index=day_idx,
                )
                s_tid = str(tid).strip()
                if s_tid.endswith(".0"): s_tid = s_tid[:-2]
                
                if (s_tid, var_day, str(session_name).strip()) in occupied_lab_teachers:
                    if (s_tid, str(cid).strip(), var_day, str(session_name).strip(), str(room_id).strip()) in allowed_lab_keys:
                        continue
                    model.Add(var == 0)
                    blocked += 1
            stats["blocked_lab_teacher_vars"] = blocked

        if settings.block_teachers and occupied_theory_teachers:
            blocked = 0
            for tid, cid, day_idx, slot_idx, var in iter_course_timeslot_variables(context):
                theory_patterns = getattr(context.variables.theory, "course_day_patterns", {}) or {}
                var_day = self._resolve_var_day_label(
                    context,
                    day_patterns=theory_patterns,
                    course_id=cid,
                    day_index=day_idx,
                )
                s_tid = str(tid).strip()
                if s_tid.endswith(".0"): s_tid = s_tid[:-2]

                if (s_tid, var_day, slot_idx) in occupied_theory_teachers:
                    if (s_tid, str(cid).strip(), var_day, slot_idx) in allowed_theory_slot_keys:
                        continue
                    model.Add(var == 0)
                    blocked += 1
            stats["blocked_theory_teacher_vars"] = blocked

        # 4) Cross-domain blocking
        if settings.block_teachers_across_domains:
            blocked_cross = self._block_teachers_across_domains(
                context,
                model,
                occupied_lab_teachers=occupied_lab_teachers,
                occupied_theory_teachers=occupied_theory_teachers,
                allowed_lab_keys=allowed_lab_keys,
                allowed_theory_slot_keys=allowed_theory_slot_keys,
            )
            stats["blocked_cross_domain_teacher_vars"] = blocked_cross

        # 5) Block department slots
        if settings.block_dept_slots and dept_lab_slots:
            self._logger.info("Dept blocking enabled. Loaded slots for %d depts. Keys: %s", len(dept_lab_slots), list(dept_lab_slots.keys()))
            
            blocked_lab = 0
            if settings.block_dept_slots_lab:
                lab_requirements = context.variables.lab.requirements
                for tid, cid, day_idx, session_name, room_id, var in iter_lab_session_variables(context):
                    requirement = lab_requirements.get(cid) or lab_requirements.get(str(cid))
                    if requirement is None: continue
                    dept = str(getattr(requirement, "department", "") or "").strip()
                    if not dept: continue
                    dept_key = self._normalise_department(dept)
                    slots = dept_lab_slots.get(dept_key)
                    if not slots:
                         # Log sample miss for diagnostics once
                         if blocked_lab == 0 and "artificial" in dept_key:
                             self._logger.debug("Missed department match for %s (key=%s). Available keys: %s", dept, dept_key, list(dept_lab_slots.keys()))
                         continue

                    var_day = self._resolve_var_day_label(
                        context,
                        day_patterns=context.variables.lab.day_patterns,
                        course_id=cid,
                        day_index=day_idx,
                    )
                    
                    s_session = str(session_name).strip()
                    if (var_day, s_session) not in slots:
                        if blocked_lab == 0 and "artificial" in dept_key and "tuesday" in var_day:
                            self._logger.debug("Missed slot match for %s, %s (day=%s, sess=%s). Blocked slots: %s", dept, cid, var_day, s_session, slots)
                        continue
                    
                    if (str(tid).strip(), str(cid).strip(), var_day, s_session, str(room_id).strip()) in allowed_lab_keys:
                        continue
                    
                    model.Add(var == 0)
                    blocked_lab += 1
            stats["blocked_dept_lab_vars"] = blocked_lab

            blocked_theory = 0
            blocked_group_theory = 0
            if settings.block_dept_slots_theory:
                # Map partial lab slots to theory slots to block theory for other courses in same dept
                time_cfg = getattr(getattr(context.data, "raw", None), "time", None)
                mapping = getattr(time_cfg, "lab_session_to_theory", {}) or {}
                theory_slots_cfg = tuple(getattr(time_cfg, "theory_slots", ()) or ())
                dept_theory_slots: dict[str, Set[Tuple[str, int]]] = defaultdict(set)
                
                # Fill dept_theory_slots from dept_lab_slots
                for dept_key, lab_slots in dept_lab_slots.items():
                    for day_label, session_name in lab_slots:
                        slots = mapping.get(session_name) or ()
                        for slot_idx in slots:
                            idx = _safe_int(slot_idx)
                            if idx is not None:
                                dept_theory_slots[dept_key].add((day_label, idx))
                
                # Also handle precise time ranges if available
                if theory_slots_cfg and dept_lab_slot_ranges:
                     def _slot_overlap_indices(range_str: str) -> Set[int]:
                        parsed = TimeParser.parse_time_range(range_str, separator='-')
                        if not parsed: return set()
                        start, end = parsed
                        start_min = start.hour * 60 + start.minute
                        end_min = end.hour * 60 + end.minute
                        overlaps: Set[int] = set()
                        for idx, slot in enumerate(theory_slots_cfg):
                            t_range = TimeParser.parse_time_range(str(slot), separator='-')
                            if not t_range: continue
                            t_start, t_end = t_range
                            t_start_min = t_start.hour * 60 + t_start.minute
                            t_end_min = t_end.hour * 60 + t_end.minute
                            if max(start_min, t_start_min) < min(end_min, t_end_min):
                                overlaps.add(idx)
                        return overlaps

                     for dept_key, lab_ranges in dept_lab_slot_ranges.items():
                        for day_label, _session_name, time_range in lab_ranges:
                            indices = _slot_overlap_indices(time_range)
                            for idx in indices:
                                dept_theory_slots[dept_key].add((day_label, idx))

                theory_requirements = (
                    getattr(context.variables.theory, "course_requirements", {}) or {}
                )
                for tid, cid, day_idx, slot_idx, var in iter_course_timeslot_variables(context):
                    requirement = theory_requirements.get(cid) or theory_requirements.get(str(cid))
                    if requirement is None: continue
                    dept = str(getattr(requirement, "department", "") or "").strip()
                    if not dept: continue
                    dept_key = self._normalise_department(dept)
                    slots = dept_theory_slots.get(dept_key)
                    if not slots: continue

                    theory_patterns = getattr(context.variables.theory, "course_day_patterns", {}) or {}
                    var_day = self._resolve_var_day_label(
                        context,
                        day_patterns=theory_patterns,
                        course_id=cid,
                        day_index=day_idx,
                    )
                    
                    if (var_day, slot_idx) not in slots: continue
                    if (str(tid).strip(), str(cid).strip(), var_day, slot_idx) in allowed_theory_slot_keys: continue
                    
                    model.Add(var == 0)
                    blocked_theory += 1

                # Group variables logic if exists
                group_requirements = getattr(context.variables.theory, "requirements", {}) or {}
                group_day_patterns = getattr(context.variables.theory, "day_patterns", {}) or {}
                group_timeslots = getattr(context.variables.theory, "group_timeslots", {}) or {}
                for group_id, day_map in group_timeslots.items():
                    # Check requirements for the group (assuming group_id maps to something in requirements or via first course)
                    # For simplicty, try direct lookup
                    requirement = group_requirements.get(group_id) or group_requirements.get(str(group_id))
                    if requirement is None: continue
                    dept = str(getattr(requirement, "department", "") or "").strip()
                    if not dept: continue
                    dept_key = self._normalise_department(dept)
                    slots = dept_theory_slots.get(dept_key)
                    if not slots: continue
                    
                    for day_idx, slot_map in day_map.items():
                        var_day = self._resolve_var_day_label(
                            context,
                            day_patterns=group_day_patterns,
                            course_id=group_id,
                            day_index=day_idx,
                        )
                        for slot_idx, var in slot_map.items():
                            if (var_day, slot_idx) not in slots: continue
                            model.Add(var == 0)
                            blocked_group_theory += 1

            stats["blocked_dept_theory_vars"] = blocked_theory
            stats["blocked_dept_group_theory_vars"] = blocked_group_theory

        extra = ensure_extra_bucket(context, "dept_slot_blocking")
        extra.update(stats)
        
        applied_any = any(stats[k] > 0 for k in stats if isinstance(stats[k], int) and stats[k] > 0)
        self._logger.info("Dept slot blocking stats: %s", stats)
        
        return self._result(ConstraintStatus.APPLIED if applied_any else ConstraintStatus.SKIPPED, stats)

    def _lock_lab_assignments(self, context, model, records, settings):
        locked = 0
        missing = 0
        lab_map = context.variables.lab.assignments or {}
        for record in records:
            course_code = str(record.get("course_code") or "").strip().upper()
            if (
                course_code
                and course_code in settings.block_dept_slots_course_codes
                and not settings.lock_blocking_assignments
            ):
                continue

            teacher_id = str(record.get("teacher_id") or "").strip()
            course_id = str(record.get("course_instance_id") or "").strip()
            room_id = str(record.get("room_id") or "").strip()
            session_name = str(record.get("session_name") or "").strip()
            day_index = _safe_int(record.get("day_index"))
            day_label = self._normalize_day_label(record.get("day"))
            if not teacher_id or not course_id or not room_id or not session_name: continue
            
            teacher_map = lab_map.get(teacher_id)
            if teacher_map is None: teacher_map = lab_map.get(f"{teacher_id}.0") or {}
            course_map = teacher_map.get(course_id) or {}
            if day_index is None:
                if not day_label: continue
                detected = self._find_day_index(context, course_id=course_id, course_day_map=course_map, day_patterns=context.variables.lab.day_patterns, scheduled_day=day_label)
                if detected is None:
                    missing += 1
                    continue
                day_index = detected
            
            day_map = course_map.get(day_index) or {}
            session_map = day_map.get(session_name) or {}
            var = session_map.get(room_id)
            if var is None:
                missing += 1
                continue
            model.Add(var == 1)
            for other_room, other_var in session_map.items():
                if other_room != room_id: model.Add(other_var == 0)
            locked += 1
        
        bucket = ensure_extra_bucket(context, "dept_slot_blocking_missing")
        bucket["lab"] = missing
        return locked

    def _lock_theory_assignments(self, context, model, records, settings):
        locked = 0
        missing = 0
        theory_block = context.variables.theory
        assignment_map = getattr(theory_block, "assignments", {}) or {}
        room_map = getattr(theory_block, "room_assignments", {}) or {}
        course_day_patterns = getattr(theory_block, "course_day_patterns", {}) or {}

        for record in records:
            course_code = str(record.get("course_code") or "").strip().upper()
            if (
                course_code
                and course_code in settings.block_dept_slots_course_codes
                and not settings.lock_blocking_assignments
            ):
                continue

            teacher_id = str(record.get("teacher_id") or "").strip()
            course_id = str(record.get("course_instance_id") or "").strip()
            room_id = str(record.get("room_id") or "").strip()
            day_index = _safe_int(record.get("day_index"))
            day_label = self._normalize_day_label(record.get("day"))
            slot_index = _safe_int(record.get("slot_index"))
            if not teacher_id or not course_id or not room_id or slot_index is None: continue

            teacher_bucket = assignment_map.get(teacher_id) or assignment_map.get(f"{teacher_id}.0") or {}
            course_bucket = teacher_bucket.get(course_id) or {}
            if day_index is None:
                if not day_label: continue
                detected = self._find_day_index(context, course_id=course_id, course_day_map=course_bucket, day_patterns=course_day_patterns, scheduled_day=day_label)
                if detected is None:
                    missing += 1
                    continue
                day_index = detected
            
            day_bucket = course_bucket.get(day_index) or {}
            slot_var = day_bucket.get(slot_index)
            
            room_teacher_bucket = room_map.get(teacher_id) or room_map.get(f"{teacher_id}.0") or {}
            room_course_bucket = room_teacher_bucket.get(course_id) or {}
            room_day_bucket = room_course_bucket.get(day_index) or {}
            room_slot_bucket = room_day_bucket.get(slot_index) or {}
            room_var = room_slot_bucket.get(room_id)

            if slot_var is None or room_var is None:
                missing += 1
                continue
            
            model.Add(slot_var == 1)
            model.Add(room_var == 1)
            for other_room, other_var in room_slot_bucket.items():
                if other_room != room_id: model.Add(other_var == 0)
            locked += 1

        bucket = ensure_extra_bucket(context, "dept_slot_blocking_missing")
        bucket["theory"] = missing
        return locked

    def _block_teachers_across_domains(self, context, model, *, occupied_lab_teachers, occupied_theory_teachers, allowed_lab_keys, allowed_theory_slot_keys):
        time_cfg = getattr(getattr(context.data, "raw", None), "time", None)
        mapping = getattr(time_cfg, "lab_session_to_theory", {}) or {}
        if not mapping: return 0

        inv: dict[int, set[str]] = defaultdict(set)
        for session_name, slots in mapping.items():
            for slot in slots or ():
                idx = _safe_int(slot)
                if idx is not None: inv[idx].add(str(session_name).strip())

        blocked_theory_slots = set()
        for tid, day_label, session_name in occupied_lab_teachers:
            slots = mapping.get(session_name)
            if not slots: continue
            for s in slots:
                idx = _safe_int(s)
                if idx is not None: blocked_theory_slots.add((tid, day_label, idx))
        
        blocked_lab_sessions = set()
        for tid, day_label, slot_idx in occupied_theory_teachers:
            sessions = inv.get(slot_idx)
            if not sessions: continue
            for s_session in sessions: blocked_lab_sessions.add((tid, day_label, s_session))

        blocked = 0
        if blocked_theory_slots:
            for tid, cid, day_idx, slot_idx, var in iter_course_timeslot_variables(context):
                theory_patterns = getattr(context.variables.theory, "course_day_patterns", {}) or {}
                var_day = self._resolve_var_day_label(context, day_patterns=theory_patterns, course_id=cid, day_index=day_idx)
                s_tid = str(tid).strip()
                if s_tid.endswith(".0"): s_tid = s_tid[:-2]
                
                if (s_tid, var_day, slot_idx) not in blocked_theory_slots: continue
                if (s_tid, str(cid).strip(), var_day, slot_idx) in allowed_theory_slot_keys: continue
                model.Add(var == 0)
                blocked += 1
        
        if blocked_lab_sessions:
            for tid, cid, day_idx, session_name, room_id, var in iter_lab_session_variables(context):
                var_day = self._resolve_var_day_label(context, day_patterns=context.variables.lab.day_patterns, course_id=cid, day_index=day_idx)
                s_tid = str(tid).strip()
                if s_tid.endswith(".0"): s_tid = s_tid[:-2]
                
                if (s_tid, var_day, str(session_name).strip()) not in blocked_lab_sessions: continue
                if (s_tid, str(cid).strip(), var_day, str(session_name).strip(), str(room_id).strip()) in allowed_lab_keys: continue
                model.Add(var == 0)
                blocked += 1
                
        return blocked

    def _load_from_csv(self, settings):
        lab_records = []
        theory_records = []
        source_paths = []

        if settings.lab_csv_path:
            lab_path = self._resolve_path(settings.lab_csv_path)
            if lab_path.exists():
                source_paths.append(str(lab_path))
                try:
                    with open(lab_path, 'r', encoding='utf-8') as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            lab_records.append({
                                "teacher_id": row.get("teacher_id"),
                                "course_instance_id": row.get("course_instance_id"),
                                "day": row.get("day"),
                                "session_name": row.get("session_name"),
                                "time_range": row.get("time_range"),
                                "room_id": row.get("room_id"),
                                "course_code": row.get("course_code"),
                                "department": row.get("department") or row.get("student_dept"),
                            })
                except Exception as e:
                    self._logger.warning("Failed to read lab CSV %s: %s", lab_path, e)
        
        if settings.theory_csv_path:
             theory_path = self._resolve_path(settings.theory_csv_path)
             if theory_path.exists():
                source_paths.append(str(theory_path))
                try:
                    with open(theory_path, 'r', encoding='utf-8') as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            theory_records.append({
                                "teacher_id": row.get("teacher_id"),
                                "course_instance_id": row.get("course_instance_id"),
                                "day": row.get("day"),
                                "slot_index": row.get("slot_index"),
                                "room_id": row.get("room_id"),
                            })
                except Exception as e:
                    self._logger.warning("Failed to read theory CSV %s: %s", theory_path, e)

        return tuple(lab_records), tuple(theory_records), ", ".join(source_paths)

    @staticmethod
    def _normalise_department(value: str) -> str:
        """Match src/data/preprocessing.py _normalise_department logic."""
        if not value:
            return value
        collapsed = " ".join(value.replace("&", " & ").split())
        return collapsed.replace("  ", " ").strip().lower()

    @staticmethod
    def _normalize_day_label(value: object) -> str:
        label = str(value or "").strip()
        normalized = DayNormalizer.normalize_day_name(label)
        return normalized or label.lower()

    def _resolve_var_day_label(self, context, *, day_patterns, course_id, day_index):
        pattern = day_patterns.get(course_id)
        label = None
        if pattern and 0 <= day_index < len(pattern):
            label = pattern[day_index]
        else:
            working_days = getattr(context.data.raw.time, "working_days", ())
            if 0 <= day_index < len(working_days):
                label = working_days[day_index]
        normalized = DayNormalizer.normalize_day_name(label or "")
        if normalized: return normalized
        return f"day_{day_index}"

    def _find_day_index(self, context, *, course_id, course_day_map, day_patterns, scheduled_day):
        for candidate in course_day_map.keys():
            idx = _safe_int(candidate)
            if idx is None: continue
            var_day = self._resolve_var_day_label(context, day_patterns=day_patterns, course_id=course_id, day_index=idx)
            if var_day == scheduled_day: return idx
        return None

    @staticmethod
    def _resolve_path(candidate: Path) -> Path:
        if candidate.is_absolute(): return candidate
        return (Path.cwd() / candidate).resolve()

    def _result(self, status: str, details: Mapping[str, object]) -> ConstraintApplicationResult:
        return ConstraintApplicationResult(
            name=self.metadata.name,
            domain=self.metadata.category,
            priority=self.metadata.priority,
            enabled=True,
            status=status,
            details=details,
        )


def _safe_int(value: object) -> Optional[int]:
    if value is None: return None
    try: return int(value)
    except (TypeError, ValueError):
        try: return int(float(str(value)))
        except (TypeError, ValueError): return None


def build_dept_slot_blocking_constraint(metadata: ConstraintMetadata, *, params: Optional[Mapping[str, object]] = None) -> DeptSlotBlockingConstraint:
    return DeptSlotBlockingConstraint(metadata=metadata, params=params)
