"""Core lab mapping constraints for specialised laboratory assignments."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional, Sequence, Set, Tuple

import pandas as pd

from ..base import Constraint, ConstraintMetadata
from ..context import ConstraintContext
from ..schema import ConstraintApplicationResult, ConstraintStatus
from ..utils import ensure_extra_bucket, iter_lab_session_variables


@dataclass
class CoreLabStats:
	mapped_courses: int = 0
	general_courses: int = 0
	catalog_courses: int = 0
	forbidden_assignments: int = 0
	skipped_courses: list[str] = field(default_factory=list)
	missing_mappings: list[str] = field(default_factory=list)
	unresolved_catalog_courses: list[str] = field(default_factory=list)


class CoreLabMappingConstraint(Constraint):
	"""Ensure mapped courses stay within their dedicated laboratory rooms."""

	CACHE_KEY = "core_lab_mapping"

	def apply(self, context: ConstraintContext) -> ConstraintApplicationResult:
		logger = context.child_logger("core_lab")
		stats = CoreLabStats()

		mapping, general_rooms, catalog = self._ensure_payload(context, logger)
		if mapping is None or general_rooms is None:
			logger.info("Core lab mapping data unavailable; skipping constraint")
			return self._result(ConstraintStatus.SKIPPED, stats)

		general_room_set = set(general_rooms)

		for course_id, requirement in context.variables.lab.requirements.items():
			assignments = list(iter_lab_session_variables(context, course_instance_id=course_id))
			if not assignments:
				continue

			course_code = self._normalise_course_code(requirement.course_code)
			core_rooms = mapping.get(course_code)
			in_catalog = course_code in catalog
			if in_catalog:
				stats.catalog_courses += 1

			if core_rooms:
				stats.mapped_courses += 1
				allowed_rooms: Set[str] = set(core_rooms)
			elif in_catalog:
				stats.unresolved_catalog_courses.append(course_code)
				allowed_rooms = general_room_set
				if not allowed_rooms:
					stats.skipped_courses.append(requirement.course_code)
					continue
			else:
				stats.general_courses += 1
				allowed_rooms = general_room_set
				if not allowed_rooms:
					stats.skipped_courses.append(requirement.course_code)
					continue

			added_constraint = False
			for assignment in assignments:
				# assignment tuple format from iter_lab_session_variables:
				# (teacher_id, course_id, day_index, session_name, room_id, var)
				_, _, _, _, room_identifier, variable = assignment
				if room_identifier not in allowed_rooms:
					context.model.Add(variable == 0)
					stats.forbidden_assignments += 1
					added_constraint = True

			if added_constraint and not core_rooms and in_catalog:
				stats.missing_mappings.append(requirement.course_code)

		status = ConstraintStatus.APPLIED if stats.forbidden_assignments else ConstraintStatus.SKIPPED
		return self._result(status, stats)

	def _result(self, status: str, stats: CoreLabStats) -> ConstraintApplicationResult:
		return ConstraintApplicationResult(
			name=self.metadata.name,
			domain=self.metadata.category,
			priority=self.metadata.priority,
			enabled=True,
			status=status,
			details={
				"mapped_courses": stats.mapped_courses,
				"general_courses": stats.general_courses,
				"catalog_courses": stats.catalog_courses,
				"forbidden_assignments": stats.forbidden_assignments,
				"skipped_courses": tuple(stats.skipped_courses),
				"missing_mappings": tuple(stats.missing_mappings),
				"unresolved_catalog_courses": tuple(stats.unresolved_catalog_courses),
			},
		)

	def _ensure_payload(
		self,
		context: ConstraintContext,
		logger,
	) -> Tuple[Optional[Mapping[str, Set[str]]], Optional[Sequence[str]], Set[str]]:
		extra = ensure_extra_bucket(context, self.CACHE_KEY)
		if {"room_map", "general_rooms", "catalog"} <= extra.keys():
			return extra["room_map"], extra["general_rooms"], extra["catalog"]

		core_df = getattr(context.data.raw, "core_lab_mapping_df", None)
		rooms_df = getattr(context.data.raw, "rooms_df", None)
		rooms = getattr(context.data.raw, "rooms", None)
		general_rooms = None
		if rooms is not None:
			lab_ids = getattr(rooms, "laboratory_room_ids", ())
			general_rooms = tuple(str(room_id) for room_id in lab_ids)
		if not general_rooms:
			general_rooms = context.variables.lab.room_ids

		catalog = self._build_catalog(core_df)
		if core_df is None or rooms_df is None or core_df.empty:
			extra["room_map"] = None
			extra["general_rooms"] = general_rooms
			extra["catalog"] = catalog
			return None, general_rooms, catalog

		room_map = self._build_room_map(core_df, rooms_df, logger)
		extra["room_map"] = room_map
		extra["general_rooms"] = general_rooms
		extra["catalog"] = catalog
		return room_map, general_rooms, catalog

	def _build_room_map(
		self,
		core_df: pd.DataFrame,
		rooms_df: pd.DataFrame,
		logger,
	) -> Mapping[str, Set[str]]:
		lookup = self._build_room_lookup(rooms_df)
		mapping: Dict[str, Set[str]] = {}

		for _, row in core_df.iterrows():
			course_code = self._normalise_course_code(row.get("course_code"))
			if not course_code:
				continue

			room_ids = self._extract_room_ids(row, lookup)
			if not room_ids:
				logger.debug("No room matches found for core course %s", course_code)
				continue

			bucket = mapping.setdefault(course_code, set())
			bucket.update(room_ids)

		return mapping

	@staticmethod
	def _build_room_lookup(rooms_df: pd.DataFrame) -> Mapping[str, str]:
		lookup: Dict[str, str] = {}
		for _, row in rooms_df.iterrows():
			room_id = str(row.get("id"))
			if not room_id:
				continue

			names = [row.get("room_number"), row.get("room_name"), row.get("description")]
			block = row.get("block")
			if row.get("room_number") and block:
				names.append(f"{row.get('room_number')}_{block}")
				names.append(f"{row.get('room_number')} {block}")

			for name in names:
				key = CoreLabMappingConstraint._normalise(name)
				if key:
					lookup[key] = room_id

			lookup[CoreLabMappingConstraint._normalise(room_id)] = room_id

		return lookup

	def _extract_room_ids(
		self,
		row: pd.Series,
		lookup: Mapping[str, str],
	) -> Set[str]:
		resolved: Set[str] = set()
		for column, value in row.items():
			if not column.lower().startswith("lab_"):
				continue
			if value is None:
				continue

			column_lower = column.lower()
			if column_lower.endswith("_block"):
				continue

			if column_lower.endswith("_room"):
				num_token = column_lower.split("_")[1]
				block_value = row.get(f"lab_{num_token}_block")
				room_id = self._resolve_room(str(value), block_value, lookup)
			else:
				room_id = self._resolve_room(str(value), None, lookup)

			if room_id:
				resolved.add(room_id)

		return resolved

	@staticmethod
	def _resolve_room(name: Optional[str], block: Optional[str], lookup: Mapping[str, str]) -> Optional[str]:
		candidates = [CoreLabMappingConstraint._normalise(name)]
		if block:
			candidates.append(CoreLabMappingConstraint._normalise(f"{name}_{block}"))
			candidates.append(CoreLabMappingConstraint._normalise(f"{name} {block}"))
		for key in candidates:
			if key and key in lookup:
				return lookup[key]
		return None

	@staticmethod
	def _normalise(value: Optional[str]) -> str:
		if not value:
			return ""
		return "".join(ch for ch in str(value).lower() if ch.isalnum())

	@staticmethod
	def _normalise_course_code(value: Optional[str]) -> str:
		return str(value or "").strip().upper()

	def _build_catalog(self, core_df: Optional[pd.DataFrame]) -> Set[str]:
		if core_df is None or core_df.empty:
			return set()
		catalog: Set[str] = set()
		for raw_code in core_df.get("course_code", tuple()):
			normalised = self._normalise_course_code(raw_code)
			if normalised:
				catalog.add(normalised)
		return catalog


def build_core_lab_mapping_constraint(
	metadata: ConstraintMetadata,
	*,
	params: Optional[Mapping[str, object]] = None,
) -> CoreLabMappingConstraint:
	"""Factory helper used by the registry."""

	return CoreLabMappingConstraint(metadata=metadata, params=params)


__all__ = [
	"CoreLabMappingConstraint",
	"build_core_lab_mapping_constraint",
]
