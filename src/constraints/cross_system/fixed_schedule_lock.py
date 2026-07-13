"""Lock (freeze) selected schedule assignments from a previous run.

This constraint can consume either:
- The warm-start snapshot written by :class:`src.runtime.warm_start.WarmStartManager`
	("warm_start_snapshot.json").
- A previously generated schedule file ("schedule.json") that contains
	"lab_entries" and "theory_entries".

Goal
- Keep already scheduled sessions immutable so future solves don't disturb them.
- Reserve the corresponding room/time and teacher/time resources so other
  activities cannot be assigned there.

The implementation is intentionally hard-constraint only: it sets decision
variables to 1 for locked assignments and to 0 for conflicting assignments.
"""

from __future__ import annotations

import csv
import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence, Set, Tuple

from ortools.sat.python import cp_model

from ..base import Constraint, ConstraintMetadata

logger = logging.getLogger(__name__)
from ..context import ConstraintContext
from ..schema import ConstraintApplicationResult, ConstraintStatus
from ..utils import (
	ensure_extra_bucket,
	iter_course_timeslot_variables,
	iter_lab_session_variables,
	iter_theory_room_variables,
)
from ...utils.time_utils import DayNormalizer
from ...utils.course_rules import ignores_teacher_constraints

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
class FixedScheduleLockSettings:
	snapshot_path: Path
	lab_csv_path: Optional[Path] = None
	theory_csv_path: Optional[Path] = None
	lock_assignments: bool = True
	block_rooms: bool = True
	block_teachers: bool = True
	block_teachers_across_domains: bool = True

	@classmethod
	def from_params(cls, params: Mapping[str, object]) -> "FixedScheduleLockSettings":
		raw_path = (
			str(params.get("snapshot_path") or "").strip()
			or str(params.get("schedule_path") or "").strip()
			or str(params.get("schedule_json_path") or "").strip()
		)
		raw_lab_csv = str(params.get("lab_csv_path") or "").strip()
		raw_theory_csv = str(params.get("theory_csv_path") or "").strip()
		return cls(
			snapshot_path=Path(raw_path) if raw_path else Path(""),
			lab_csv_path=Path(raw_lab_csv) if raw_lab_csv else None,
			theory_csv_path=Path(raw_theory_csv) if raw_theory_csv else None,
			lock_assignments=_as_bool(params.get("lock_assignments"), True),
			block_rooms=_as_bool(params.get("block_rooms"), True),
			block_teachers=_as_bool(params.get("block_teachers"), True),
			block_teachers_across_domains=_as_bool(
				params.get("block_teachers_across_domains"), True
			),
		)


class FixedScheduleLockConstraint(Constraint):
	"""Freeze room/time and teacher/time usage from a prior schedule."""

	def __init__(self, metadata: ConstraintMetadata, params: Optional[Mapping[str, object]] = None) -> None:
		super().__init__(metadata, params=params)
		self._settings = FixedScheduleLockSettings.from_params(self.params)
		self._logger = LOGGER.getChild("fixed_schedule_lock")

	def apply(self, context: ConstraintContext) -> ConstraintApplicationResult:
		settings = self._settings
		
		# Check if CSV paths are provided
		if settings.lab_csv_path or settings.theory_csv_path:
			lab_records, theory_records, source_format = self._load_from_csv(settings)
			if not lab_records and not theory_records:
				return self._result(
					ConstraintStatus.SKIPPED,
					{"reason": "csv_files_empty_or_missing"},
				)
			# Create a descriptive source info for CSV loading
			csv_sources = []
			if settings.lab_csv_path:
				csv_sources.append(f"lab={settings.lab_csv_path}")
			if settings.theory_csv_path:
				csv_sources.append(f"theory={settings.theory_csv_path}")
			source_info = ", ".join(csv_sources)
		else:
			# Fall back to JSON loading
			if not str(settings.snapshot_path):
				return self._result(ConstraintStatus.SKIPPED, {"reason": "snapshot_path_missing"})

			snapshot_path = self._resolve_path(settings.snapshot_path)
			if not snapshot_path.exists():
				return self._result(
					ConstraintStatus.SKIPPED,
					{"reason": "snapshot_not_found", "snapshot_path": str(snapshot_path)},
				)

			try:
				payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
			except json.JSONDecodeError:
				return self._result(
					ConstraintStatus.SKIPPED,
					{"reason": "snapshot_invalid_json", "snapshot_path": str(snapshot_path)},
				)

			lab_records, theory_records, source_format = self._normalize_payload(payload)
			if not lab_records and not theory_records:
				return self._result(
					ConstraintStatus.SKIPPED,
					{
						"reason": "snapshot_empty_or_unrecognized",
						"snapshot_path": str(snapshot_path),
						"source_format": source_format,
					},
				)
			source_info = str(snapshot_path)

		self._logger.info(
			"Fixed schedule lock loading %s from %s (lab=%d, theory=%d)",
			source_format,
			source_info,
			len(lab_records),
			len(theory_records),
		)

		model = context.model
		stats = {
			"source_info": source_info,
			"source_format": source_format,
			"source_lab_records": len(lab_records),
			"source_theory_records": len(theory_records),
			"locked_lab": 0,
			"locked_theory": 0,
			"blocked_lab_room_vars": 0,
			"blocked_theory_room_vars": 0,
			"blocked_lab_teacher_vars": 0,
			"blocked_theory_teacher_vars": 0,
			"blocked_cross_domain_teacher_vars": 0,
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
			if not teacher_id or not session_name or not day_label:
				continue
			occupied_lab_teachers.add((teacher_id, day_label, session_name))
			if room_id:
				occupied_lab_rooms.add((day_label, session_name, room_id))
			if course_id and room_id:
				allowed_lab_keys.add((teacher_id, course_id, day_label, session_name, room_id))

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
			if not teacher_id or not day_label or slot_index is None:
				continue
			occupied_theory_teachers.add((teacher_id, day_label, slot_index))
			if room_id:
				occupied_theory_rooms.add((day_label, slot_index, room_id))
			if course_id and room_id:
				allowed_theory_room_keys.add((teacher_id, course_id, day_label, slot_index, room_id))
				allowed_theory_slot_keys.add((teacher_id, course_id, day_label, slot_index))

		teacher_key_hits = self._count_teacher_key_hits(
			context,
			occupied_lab_teachers=occupied_lab_teachers,
			occupied_theory_teachers=occupied_theory_teachers,
		)
		stats.update(teacher_key_hits)
		self._logger.info(
			"Fixed schedule lock teacher key intersection: lab=%d theory=%d cross=%d "
			"(occupied_lab=%d occupied_theory=%d)",
			teacher_key_hits["lab_teacher_key_hits"],
			teacher_key_hits["theory_teacher_key_hits"],
			teacher_key_hits["cross_domain_teacher_key_hits"],
			len(occupied_lab_teachers),
			len(occupied_theory_teachers),
		)

		# 1) Lock explicit assignments where matching variables exist.
		if settings.lock_assignments:
			stats["locked_lab"] = self._lock_lab_assignments(
				context,
				model,
				lab_records,
			)
			stats["locked_theory"] = self._lock_theory_assignments(
				context,
				model,
				theory_records,
			)

			# Recompute missing counts (lock helpers update counters in extra bucket).
			missing_bucket = context.extra.get("fixed_schedule_lock_missing")
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
				# Cast to string for consistent lookup
				s_session = str(session_name).strip()
				s_room = str(room_id).strip()
				s_tid = str(tid).strip()
				s_cid = str(cid).strip()

				if (var_day, s_session, s_room) not in occupied_lab_rooms:
					continue
				is_external = self._lab_course_ignores_teacher_constraints(context, s_cid)
				if not is_external and (s_tid, s_cid, var_day, s_session, s_room) in allowed_lab_keys:
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
				# Cast to string for consistent lookup
				s_room = str(room_id).strip()
				s_tid = str(tid).strip()
				s_cid = str(cid).strip()

				if (var_day, slot_idx, s_room) not in occupied_theory_rooms:
					continue
				if (s_tid, s_cid, var_day, slot_idx, s_room) in allowed_theory_room_keys:
					continue
				model.Add(var == 0)
				blocked += 1
			stats["blocked_theory_room_vars"] = blocked

		# 3) Block conflicting teacher usage.
		if settings.block_teachers and occupied_lab_teachers:
			blocked = 0
			for tid, cid, day_idx, session_name, room_id, var in iter_lab_session_variables(context):
				if self._lab_course_ignores_teacher_constraints(context, str(cid)):
					continue
				var_day = self._resolve_var_day_label(
					context,
					day_patterns=context.variables.lab.day_patterns,
					course_id=cid,
					day_index=day_idx,
				)
				s_session = str(session_name).strip()
				s_tid = str(tid).strip()
				if s_tid.endswith(".0"):
					s_tid = s_tid[:-2]

				if (s_tid, var_day, s_session) in occupied_lab_teachers:
					# Check if this strictly matches an allowed assignment
					if (s_tid, str(cid), var_day, s_session, str(room_id)) in allowed_lab_keys:
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
				if s_tid.endswith(".0"):
					s_tid = s_tid[:-2]

				# The set stores (teacher_id, day, slot_idx)
				if (s_tid, var_day, slot_idx) in occupied_theory_teachers:
					if (s_tid, str(cid), var_day, slot_idx) in allowed_theory_slot_keys:
						continue

					model.Add(var == 0)
					blocked += 1
			stats["blocked_theory_teacher_vars"] = blocked

		# 4) Optionally block teacher overlaps across lab<->theory using the time mapping.
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

		extra = ensure_extra_bucket(context, "fixed_schedule_lock")
		extra.update(stats)

		applied_any = any(
			stats[key] > 0
			for key in (
				"locked_lab",
				"locked_theory",
				"blocked_lab_room_vars",
				"blocked_theory_room_vars",
				"blocked_lab_teacher_vars",
				"blocked_theory_teacher_vars",
				"blocked_cross_domain_teacher_vars",
			)
		)
		self._logger.info(
			"Fixed schedule lock stats: locked_lab=%d locked_theory=%d blocked_room(lab=%d theory=%d) blocked_teacher(lab=%d theory=%d) blocked_cross=%d missing(lab=%d theory=%d)",
			stats["locked_lab"],
			stats["locked_theory"],
			stats["blocked_lab_room_vars"],
			stats["blocked_theory_room_vars"],
			stats["blocked_lab_teacher_vars"],
			stats["blocked_theory_teacher_vars"],
			stats["blocked_cross_domain_teacher_vars"],
			stats["missing_lab_vars"],
			stats["missing_theory_vars"],
		)
		return self._result(ConstraintStatus.APPLIED if applied_any else ConstraintStatus.SKIPPED, stats)

	def _lock_lab_assignments(
		self,
		context: ConstraintContext,
		model: cp_model.CpModel,
		records: Sequence[Mapping[str, Any]],
	) -> int:
		locked = 0
		missing = 0
		lab_map = context.variables.lab.assignments or {}
		for record in records:
			teacher_id = str(record.get("teacher_id") or "").strip()
			course_id = str(record.get("course_instance_id") or "").strip()
			room_id = str(record.get("room_id") or "").strip()
			session_name = str(record.get("session_name") or "").strip()
			day_index = _safe_int(record.get("day_index"))
			day_label = self._normalize_day_label(record.get("day"))
			if not teacher_id or not course_id or not room_id or not session_name:
				continue
			if self._lab_course_ignores_teacher_constraints(context, course_id):
				continue
			
			# Try lookup with clean ID first, then fallback to appended .0
			teacher_map = lab_map.get(teacher_id)
			if teacher_map is None:
				teacher_map = lab_map.get(f"{teacher_id}.0") or {}
			
			course_map = teacher_map.get(course_id) or {}
			if day_index is None:
				if not day_label:
					continue
				detected = self._find_day_index(
					context,
					course_id=course_id,
					course_day_map=course_map,
					day_patterns=context.variables.lab.day_patterns,
					scheduled_day=day_label,
				)
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
			# Ensure the room choice is frozen.
			for other_room, other_var in session_map.items():
				if other_room != room_id:
					model.Add(other_var == 0)
			locked += 1

		bucket = ensure_extra_bucket(context, "fixed_schedule_lock_missing")
		bucket["lab"] = missing
		return locked

	def _lock_theory_assignments(
		self,
		context: ConstraintContext,
		model: cp_model.CpModel,
		records: Sequence[Mapping[str, Any]],
	) -> int:
		locked = 0
		missing = 0
		theory_block = context.variables.theory
		assignment_map = getattr(theory_block, "assignments", {}) or {}
		room_map = getattr(theory_block, "room_assignments", {}) or {}
		course_day_patterns = getattr(theory_block, "course_day_patterns", {}) or {}
		course_requirements = getattr(theory_block, "course_requirements", {}) or {}

		for record in records:
			teacher_id = str(record.get("teacher_id") or "").strip()
			course_id = str(record.get("course_instance_id") or "").strip()
			component_id = self._resolve_theory_component_id(record, course_id, course_requirements)
			room_id = str(record.get("room_id") or "").strip()
			day_index = _safe_int(record.get("day_index"))
			day_label = self._normalize_day_label(record.get("day"))
			slot_index = _safe_int(record.get("slot_index"))
			if not teacher_id or not course_id or not room_id or slot_index is None:
				continue

			# Try lookup with clean ID first, then fallback to appended .0
			teacher_bucket = assignment_map.get(teacher_id)
			if teacher_bucket is None:
				teacher_bucket = assignment_map.get(f"{teacher_id}.0") or {}

			course_bucket = teacher_bucket.get(component_id) or {}
			if day_index is None:
				if not day_label:
					continue
				detected = self._find_day_index(
					context,
					course_id=component_id,
					course_day_map=course_bucket,
					day_patterns=course_day_patterns,
					scheduled_day=day_label,
				)
				if detected is None:
					missing += 1
					continue
				day_index = detected
			day_bucket = course_bucket.get(day_index) or {}
			slot_var = day_bucket.get(slot_index)

			# Try lookup with clean ID first, then fallback to appended .0
			room_teacher_bucket = room_map.get(teacher_id)
			if room_teacher_bucket is None:
				room_teacher_bucket = room_map.get(f"{teacher_id}.0") or {}

			room_course_bucket = room_teacher_bucket.get(component_id) or {}
			room_day_bucket = room_course_bucket.get(day_index) or {}
			room_slot_bucket = room_day_bucket.get(slot_index) or {}
			room_var = room_slot_bucket.get(room_id)

			if slot_var is None or room_var is None:
				missing += 1
				continue

			model.Add(slot_var == 1)
			model.Add(room_var == 1)
			for other_room, other_var in room_slot_bucket.items():
				if other_room != room_id:
					model.Add(other_var == 0)
			locked += 1

		bucket = ensure_extra_bucket(context, "fixed_schedule_lock_missing")
		bucket["theory"] = missing
		return locked

	def _block_teachers_across_domains(
		self,
		context: ConstraintContext,
		model: cp_model.CpModel,
		*,
		occupied_lab_teachers: Set[Tuple[str, str, str]],
		occupied_theory_teachers: Set[Tuple[str, str, int]],
		allowed_lab_keys: Set[Tuple[str, str, str, str, str]],
		allowed_theory_slot_keys: Set[Tuple[str, str, str, int]],
	) -> int:
		"""Block teacher overlaps across lab/theory using lab_session_to_theory."""

		time_cfg = getattr(getattr(context.data, "raw", None), "time", None)
		mapping = getattr(time_cfg, "lab_session_to_theory", {}) or {}
		if not mapping:
			return 0

		# Build inverse map: theory_slot -> list of lab_sessions
		# mapping: session_name -> [slot_index, ...]
		inv: dict[int, set[str]] = defaultdict(set)
		for session_name, slots in mapping.items():
			s_session = str(session_name).strip()
			for slot in slots or ():
				idx = _safe_int(slot)
				if idx is not None:
					inv[idx].add(s_session)

		blocked_theory_slots: Set[Tuple[str, str, int]] = set()
		for tid, day_label, session_name in occupied_lab_teachers:
			slots = mapping.get(session_name)
			if not slots:
				continue
			for s in slots:
				idx = _safe_int(s)
				if idx is not None:
					blocked_theory_slots.add((tid, day_label, idx))

		blocked_lab_sessions: Set[Tuple[str, str, str]] = set()
		for tid, day_label, slot_idx in occupied_theory_teachers:
			sessions = inv.get(slot_idx)
			if not sessions:
				continue
			for s_session in sessions:
				blocked_lab_sessions.add((tid, day_label, s_session))

		blocked = 0

		# 1) Block theory vars if teacher is busy in lab
		if blocked_theory_slots:
			for tid, cid, day_idx, slot_idx, var in iter_course_timeslot_variables(context):
				theory_patterns = getattr(context.variables.theory, "course_day_patterns", {}) or {}
				var_day = self._resolve_var_day_label(
					context,
					day_patterns=theory_patterns,
					course_id=cid,
					day_index=day_idx,
				)
				s_tid = str(tid).strip()
				if s_tid.endswith(".0"):
					s_tid = s_tid[:-2]
				s_cid = str(cid).strip()

				if (s_tid, var_day, slot_idx) not in blocked_theory_slots:
					continue
				
				# If this specific assignment is allowed (part of the fixed schedule), skip blocking
				if (s_tid, s_cid, var_day, slot_idx) in allowed_theory_slot_keys:
					continue
				
				model.Add(var == 0)
				blocked += 1

		# 2) Block lab vars if teacher is busy in theory
		if blocked_lab_sessions:
			for tid, cid, day_idx, session_name, room_id, var in iter_lab_session_variables(context):
				if self._lab_course_ignores_teacher_constraints(context, str(cid)):
					continue
				var_day = self._resolve_var_day_label(
					context,
					day_patterns=context.variables.lab.day_patterns,
					course_id=cid,
					day_index=day_idx,
				)
				s_tid = str(tid).strip()
				if s_tid.endswith(".0"):
					s_tid = s_tid[:-2]
				s_cid = str(cid).strip()
				s_session = str(session_name).strip()
				s_room = str(room_id).strip()

				if (s_tid, var_day, s_session) not in blocked_lab_sessions:
					continue

				# If this specific assignment is allowed, skip blocking
				if (s_tid, s_cid, var_day, s_session, s_room) in allowed_lab_keys:
					continue

				model.Add(var == 0)
				blocked += 1

		return blocked

	def _count_teacher_key_hits(
		self,
		context: ConstraintContext,
		*,
		occupied_lab_teachers: Set[Tuple[str, str, str]],
		occupied_theory_teachers: Set[Tuple[str, str, int]],
	) -> dict[str, int]:
		lab_hits = 0
		for tid, _cid, day_idx, session_name, _room_id, _var in iter_lab_session_variables(context):
			if self._lab_course_ignores_teacher_constraints(context, str(_cid)):
				continue
			var_day = self._resolve_var_day_label(
				context,
				day_patterns=context.variables.lab.day_patterns,
				course_id=str(_cid),
				day_index=day_idx,
			)
			s_tid = str(tid).strip()
			if s_tid.endswith(".0"):
				s_tid = s_tid[:-2]
			if (s_tid, var_day, str(session_name).strip()) in occupied_lab_teachers:
				lab_hits += 1

		theory_hits = 0
		for tid, _cid, day_idx, slot_idx, _var in iter_course_timeslot_variables(context):
			theory_patterns = getattr(context.variables.theory, "course_day_patterns", {}) or {}
			var_day = self._resolve_var_day_label(
				context,
				day_patterns=theory_patterns,
				course_id=str(_cid),
				day_index=day_idx,
			)
			s_tid = str(tid).strip()
			if s_tid.endswith(".0"):
				s_tid = s_tid[:-2]
			if (s_tid, var_day, slot_idx) in occupied_theory_teachers:
				theory_hits += 1

		cross_hits = 0
		time_cfg = getattr(getattr(context.data, "raw", None), "time", None)
		mapping = getattr(time_cfg, "lab_session_to_theory", {}) or {}
		if mapping:
			blocked_theory_slots: Set[Tuple[str, str, int]] = set()
			for tid, day_label, session_name in occupied_lab_teachers:
				for slot in mapping.get(session_name, ()) or ():
					idx = _safe_int(slot)
					if idx is not None:
						blocked_theory_slots.add((tid, day_label, idx))
			for tid, _cid, day_idx, slot_idx, _var in iter_course_timeslot_variables(context):
				theory_patterns = getattr(context.variables.theory, "course_day_patterns", {}) or {}
				var_day = self._resolve_var_day_label(
					context,
					day_patterns=theory_patterns,
					course_id=str(_cid),
					day_index=day_idx,
				)
				s_tid = str(tid).strip()
				if s_tid.endswith(".0"):
					s_tid = s_tid[:-2]
				if (s_tid, var_day, slot_idx) in blocked_theory_slots:
					cross_hits += 1

			inv: dict[int, set[str]] = defaultdict(set)
			for session_name, slots in mapping.items():
				for slot in slots or ():
					idx = _safe_int(slot)
					if idx is not None:
						inv[idx].add(str(session_name).strip())
			blocked_lab_sessions: Set[Tuple[str, str, str]] = set()
			for tid, day_label, slot_idx in occupied_theory_teachers:
				for session_name in inv.get(slot_idx, ()):
					blocked_lab_sessions.add((tid, day_label, session_name))
			for tid, _cid, day_idx, session_name, _room_id, _var in iter_lab_session_variables(context):
				if self._lab_course_ignores_teacher_constraints(context, str(_cid)):
					continue
				var_day = self._resolve_var_day_label(
					context,
					day_patterns=context.variables.lab.day_patterns,
					course_id=str(_cid),
					day_index=day_idx,
				)
				s_tid = str(tid).strip()
				if s_tid.endswith(".0"):
					s_tid = s_tid[:-2]
				if (s_tid, var_day, str(session_name).strip()) in blocked_lab_sessions:
					cross_hits += 1

		return {
			"lab_teacher_key_hits": lab_hits,
			"theory_teacher_key_hits": theory_hits,
			"cross_domain_teacher_key_hits": cross_hits,
		}

	@staticmethod
	def _lab_course_ignores_teacher_constraints(context: ConstraintContext, course_id: str) -> bool:
		requirements = getattr(context.variables.lab, "requirements", {}) or {}
		return ignores_teacher_constraints(requirements.get(str(course_id)))

	def _normalize_payload(
		self,
		payload: Mapping[str, Any],
	) -> tuple[Tuple[Mapping[str, Any], ...], Tuple[Mapping[str, Any], ...], str]:
		"""Accept either warm_start_snapshot.json or schedule.json."""

		if "lab_assignments" in payload or "theory_assignments" in payload:
			lab = tuple(payload.get("lab_assignments") or ())
			theory = tuple(payload.get("theory_assignments") or ())
			return lab, theory, "warm_start_snapshot"

		if "lab_entries" in payload or "theory_entries" in payload:
			lab_entries = tuple(payload.get("lab_entries") or ())
			theory_entries = tuple(payload.get("theory_entries") or ())
			lab: list[Mapping[str, Any]] = []
			for entry in lab_entries:
				if not isinstance(entry, Mapping):
					continue
				lab.append(
					{
						"teacher_id": entry.get("teacher_id"),
						"course_instance_id": entry.get("course_instance_id"),
						"day": entry.get("day"),
						"session_name": entry.get("session_name"),
						"room_id": entry.get("room_id"),
					}
				)
			theory: list[Mapping[str, Any]] = []
			for entry in theory_entries:
				if not isinstance(entry, Mapping):
					continue
				theory.append(
					{
						"teacher_id": entry.get("teacher_id"),
						"course_instance_id": entry.get("course_instance_id"),
						"day": entry.get("day"),
						"slot_index": entry.get("slot_index"),
						"room_id": entry.get("room_id"),
					}
				)
			return tuple(lab), tuple(theory), "schedule_json"

		return tuple(), tuple(), "unknown"

	def _load_from_csv(
		self,
		settings: FixedScheduleLockSettings,
	) -> tuple[Tuple[Mapping[str, Any], ...], Tuple[Mapping[str, Any], ...], str]:
		"""Load schedule data from CSV files."""
		lab_records: list[Mapping[str, Any]] = []
		theory_records: list[Mapping[str, Any]] = []
		
		# Load lab schedule if path provided
		if settings.lab_csv_path:
			lab_path = self._resolve_path(settings.lab_csv_path)
			if lab_path.exists():
				self._logger.info("Loading lab schedule from CSV: %s", lab_path)
				try:
					with open(lab_path, 'r', encoding='utf-8-sig') as f:
						reader = csv.DictReader(f)
						self._logger.debug("Fixed schedule lock lab CSV headers: %s", reader.fieldnames)
						incomplete = 0
						for row in reader:
							record = {
								"teacher_id": _csv_value(row, "teacher_id", "faculty_id", "teacher"),
								"course_instance_id": _csv_value(
									row,
									"course_instance_id",
									"course_id",
									"instance_id",
								),
								"day": _csv_value(row, "day", "day_label"),
								"day_index": _csv_value(row, "day_index"),
								"session_name": _csv_value(row, "session_name", "lab_session", "session"),
								"room_id": _csv_value(row, "room_id"),
							}
							if not _has_required_csv_values(
								record,
								("teacher_id", "course_instance_id", "day", "session_name", "room_id"),
							):
								incomplete += 1
							lab_records.append(record)
						if incomplete:
							self._logger.warning(
								"Fixed schedule lock found %d/%d incomplete lab assignment rows; "
								"available teacher/time occupancy is still retained.",
								incomplete,
								len(lab_records),
							)
				except Exception as e:
					self._logger.warning("Failed to read lab CSV %s: %s", lab_path, e)
		
		# Load theory schedule if path provided
		if settings.theory_csv_path:
			theory_path = self._resolve_path(settings.theory_csv_path)
			if theory_path.exists():
				self._logger.info("Loading theory schedule from CSV: %s", theory_path)
				try:
					with open(theory_path, 'r', encoding='utf-8-sig') as f:
						reader = csv.DictReader(f)
						self._logger.debug("Fixed schedule lock theory CSV headers: %s", reader.fieldnames)
						incomplete = 0
						for row in reader:
							record = {
								"teacher_id": _csv_value(row, "teacher_id", "faculty_id", "teacher"),
								"course_instance_id": _csv_value(
									row,
									"course_instance_id",
									"course_id",
									"instance_id",
								),
								"day": _csv_value(row, "day", "day_label"),
								"day_index": _csv_value(row, "day_index"),
								"slot_index": _csv_value(row, "slot_index", "slot", "timeslot_index"),
								"room_id": _csv_value(row, "room_id"),
							}
							if not _has_required_csv_values(
								record,
								("teacher_id", "course_instance_id", "day", "slot_index", "room_id"),
							):
								incomplete += 1
							theory_records.append(record)
						if incomplete:
							self._logger.warning(
								"Fixed schedule lock found %d/%d incomplete theory assignment rows; "
								"available teacher/time occupancy is still retained.",
								incomplete,
								len(theory_records),
							)
				except Exception as e:
					self._logger.warning("Failed to read theory CSV %s: %s", theory_path, e)
		
		return tuple(lab_records), tuple(theory_records), "csv_files"

	@staticmethod
	def _resolve_theory_component_id(
		record: Mapping[str, Any],
		course_id: str,
		requirements: Mapping[str, Any],
	) -> str:
		delivery_mode = str(record.get("delivery_mode") or "legacy_full_slot")
		for component_id, requirement in requirements.items():
			source_id = str(getattr(requirement, "source_instance_id", None) or component_id)
			if source_id != course_id:
				continue
			if str(getattr(requirement, "delivery_mode", "legacy_full_slot")) == delivery_mode:
				return component_id
		return course_id

	@staticmethod
	def _normalize_day_label(value: object) -> str:
		label = str(value or "").strip()
		normalized = DayNormalizer.normalize_day_name(label)
		return normalized or label.lower()

	def _resolve_var_day_label(
		self,
		context: ConstraintContext,
		*,
		day_patterns: Mapping[str, Sequence[str]],
		course_id: str,
		day_index: int,
	) -> str:
		pattern = day_patterns.get(course_id)
		label: Optional[str] = None
		if pattern and 0 <= day_index < len(pattern):
			label = pattern[day_index]
		else:
			working_days = getattr(context.data.raw.time, "working_days", ())
			if 0 <= day_index < len(working_days):
				label = working_days[day_index]
		normalized = DayNormalizer.normalize_day_name(label or "")
		if normalized:
			return normalized
		return f"day_{day_index}"

	def _find_day_index(
		self,
		context: ConstraintContext,
		*,
		course_id: str,
		course_day_map: Mapping[int, Any],
		day_patterns: Mapping[str, Sequence[str]],
		scheduled_day: str,
	) -> Optional[int]:
		for candidate in course_day_map.keys():
			idx = _safe_int(candidate)
			if idx is None:
				continue
			var_day = self._resolve_var_day_label(
				context,
				day_patterns=day_patterns,
				course_id=course_id,
				day_index=idx,
			)
			if var_day == scheduled_day:
				return idx
		return None

	@staticmethod
	def _resolve_path(candidate: Path) -> Path:
		if candidate.is_absolute():
			return candidate
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
	if value is None:
		return None
	try:
		return int(value)
	except (TypeError, ValueError):
		try:
			return int(float(str(value)))
		except (TypeError, ValueError):
			return None


def _csv_value(row: Mapping[str, Any], *names: str) -> object:
	if not row or not names:
		return None
	lower_lookup = {_normalize_csv_header(key): value for key, value in row.items()}
	for name in names:
		value = row.get(name)
		if value is not None and str(value).strip():
			return value
		value = lower_lookup.get(_normalize_csv_header(name))
		if value is not None and str(value).strip():
			return value
	return None


def _normalize_csv_header(value: object) -> str:
	return str(value or "").replace("\ufeff", "").strip().lower()


def _has_required_csv_values(record: Mapping[str, Any], keys: Sequence[str]) -> bool:
	return all(str(record.get(key) or "").strip() for key in keys)


def build_fixed_schedule_lock_constraint(
	metadata: ConstraintMetadata,
	*,
	params: Optional[Mapping[str, object]] = None,
) -> FixedScheduleLockConstraint:
	return FixedScheduleLockConstraint(metadata=metadata, params=params)


__all__ = ["FixedScheduleLockConstraint", "build_fixed_schedule_lock_constraint"]
