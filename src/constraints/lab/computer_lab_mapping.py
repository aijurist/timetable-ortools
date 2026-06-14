"""Computer lab preference mappings by department and course code."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional, Set, Tuple

import pandas as pd

from ..base import Constraint, ConstraintMetadata
from ..context import ConstraintContext
from ..schema import ConstraintApplicationResult, ConstraintStatus
from ..utils import ensure_extra_bucket, iter_lab_session_variables, register_objective_penalty
from .core_lab import CoreLabMappingConstraint


MappingKey = Tuple[str, str]


@dataclass
class ComputerLabPreference:
	room_ids: Set[str] = field(default_factory=set)
	mode: str = "soft"
	penalty_weight: int = 500


@dataclass
class ComputerLabMappingStats:
	mapped_course_instances: int = 0
	soft_penalties: int = 0
	hard_blocks: int = 0
	mapping_rows: int = 0
	hard_mapping_rows: int = 0
	soft_mapping_rows: int = 0
	unresolved_rows: list[str] = field(default_factory=list)
	missing_mapped_assignments: list[str] = field(default_factory=list)


class ComputerLabMappingConstraint(Constraint):
	"""Prefer configured computer labs for matching department/course pairs."""

	CACHE_KEY = "computer_lab_mapping"
	DEFAULT_DEPARTMENT_ALIASES = {
		"aids": ("artificial intelligence and data science",),
		"aiml": ("artificial intelligence and machine learning",),
		"auto": ("automobile engineering",),
		"biot": ("biotechnology",),
		"bt": ("biotechnology",),
		"csbs": ("computer science and business systems",),
		"csd": ("computer science and design",),
		"ce2": ("civil engineering",),
		"civil": ("civil engineering",),
		"cse": ("computer science and engineering",),
		"be": ("biomedical engineering",),
		"bme": ("biomedical engineering",),
		"ece": ("electronics and communication engineering",),
		"eee": ("electrical and electronics engineering",),
		"me": ("mechanical engineering",),
		"it": ("information technology",),
	}
	DEFAULT_ROOM_COLUMNS = (
		"preferred_lab",
		"preferred_lab_room",
		"computer_lab",
		"computer_lab_room",
		"lab",
		"lab_room",
		"room",
		"room_id",
	)

	def __init__(self, metadata: ConstraintMetadata, params: Optional[Mapping[str, object]] = None) -> None:
		super().__init__(metadata, params=params)
		settings = dict(params or {})
		self._mode = str(settings.get("mode", "soft")).strip().lower()
		if self._mode not in {"soft", "hard"}:
			self._mode = "soft"
		self._penalty_weight = max(0, int(settings.get("penalty_weight", 150)))
		self._block_penalty_weight = max(0, int(settings.get("block_penalty_weight", 500)))
		raw_room_columns = settings.get("room_columns", self.DEFAULT_ROOM_COLUMNS)
		if isinstance(raw_room_columns, str):
			raw_room_columns = (raw_room_columns,)
		self._room_columns = tuple(
			str(column).strip()
			for column in raw_room_columns
			if str(column).strip()
		)
		self._department_aliases = self._build_department_aliases(settings.get("department_aliases"))

	def apply(self, context: ConstraintContext) -> ConstraintApplicationResult:
		logger = context.child_logger("computer_lab_mapping")
		stats = ComputerLabMappingStats()
		mapping = self._ensure_mapping(context, logger, stats)
		if not mapping:
			return self._result(ConstraintStatus.SKIPPED, stats, {"reason": "no_computer_lab_mapping"})

		for course_id, requirement in context.variables.lab.requirements.items():
			key = (
				self._normalise_department(getattr(requirement, "department", "")),
				self._normalise_course_code(getattr(requirement, "course_code", "")),
			)
			preference = mapping.get(key)
			if not preference or not preference.room_ids:
				continue

			assignments = list(iter_lab_session_variables(context, course_instance_id=course_id))
			if not assignments:
				stats.missing_mapped_assignments.append(course_id)
				continue

			stats.mapped_course_instances += 1
			for _teacher_id, _course_id, _day_idx, _session, room_id, variable in assignments:
				if str(room_id) in preference.room_ids:
					continue
				if preference.mode == "hard":
					context.model.Add(variable == 0)
					stats.hard_blocks += 1
				elif preference.penalty_weight > 0:
					register_objective_penalty(
						context,
						variable,
						weight=preference.penalty_weight,
						tag=f"computer_lab_mapping:{key[0]}:{key[1]}",
					)
					stats.soft_penalties += 1

		status = ConstraintStatus.APPLIED if (stats.soft_penalties or stats.hard_blocks) else ConstraintStatus.SKIPPED
		return self._result(status, stats)

	def _ensure_mapping(
		self,
		context: ConstraintContext,
		logger,
		stats: ComputerLabMappingStats,
	) -> Mapping[MappingKey, ComputerLabPreference]:
		extra = ensure_extra_bucket(context, self.CACHE_KEY)
		if "room_map" in extra:
			return extra["room_map"]  # type: ignore[return-value]

		mapping_df = getattr(context.data.raw, "computer_lab_mapping_df", None)
		rooms_df = getattr(context.data.raw, "rooms_df", None)
		if mapping_df is None or rooms_df is None or getattr(mapping_df, "empty", True):
			extra["room_map"] = {}
			return {}

		room_lookup = CoreLabMappingConstraint._build_room_lookup(rooms_df)
		block_lookup = self._build_computer_lab_block_lookup(rooms_df)
		room_map = self._build_room_map(mapping_df, room_lookup, block_lookup, logger, stats)
		extra["room_map"] = room_map
		return room_map

	def _build_room_map(
		self,
		mapping_df: pd.DataFrame,
		room_lookup: Mapping[str, str],
		block_lookup: Mapping[str, Set[str]],
		logger,
		stats: ComputerLabMappingStats,
	) -> Mapping[MappingKey, ComputerLabPreference]:
		room_map: Dict[MappingKey, ComputerLabPreference] = {}
		for row_index, row in mapping_df.iterrows():
			department = self._normalise_department(self._first_value(row, ("department", "dept", "student_dept")))
			course_code = self._normalise_course_code(self._first_value(row, ("course_code", "subject_code", "code")))
			if not department or not course_code:
				continue

			specific_room_requested = self._has_specific_room_request(row)
			specific_room_ids = self._extract_specific_room_ids(row, room_lookup)
			block_room_ids = self._extract_block_room_ids(row, block_lookup)
			if specific_room_requested and specific_room_ids:
				row_preference = ComputerLabPreference(
					room_ids=specific_room_ids,
					mode="hard",
					penalty_weight=0,
				)
				stats.hard_mapping_rows += 1
			elif not specific_room_requested and block_room_ids:
				row_preference = ComputerLabPreference(
					room_ids=block_room_ids,
					mode="soft",
					penalty_weight=self._block_penalty_weight,
				)
				stats.soft_mapping_rows += 1
			else:
				label = f"{department}:{course_code}:row_{row_index + 2}"
				stats.unresolved_rows.append(label)
				logger.debug("No computer lab room matches found for %s", label)
				continue

			for department_key in self._department_keys(department, course_code):
				key = (department_key, course_code)
				existing = room_map.get(key)
				room_map[key] = self._merge_preference(existing, row_preference)
			stats.mapping_rows += 1

		return room_map

	def _has_specific_room_request(self, row: pd.Series) -> bool:
		return any(
			not self._is_blank(row.get(column))
			for column in self._candidate_room_columns(row)
		)

	def _extract_specific_room_ids(
		self,
		row: pd.Series,
		room_lookup: Mapping[str, str],
	) -> Set[str]:
		resolved: Set[str] = set()
		for column in self._candidate_room_columns(row):
			value = row.get(column)
			if self._is_blank(value):
				continue

			column_lower = str(column).strip().lower()
			block_value = None
			if column_lower.endswith("_room"):
				prefix = column_lower[:-5]
				block_value = self._first_value(row, (f"{prefix}_block",))

			for token in self._split_room_tokens(value):
				room_id = CoreLabMappingConstraint._resolve_room(str(token), block_value, room_lookup)
				if room_id:
					resolved.add(room_id)
		return resolved

	def _extract_block_room_ids(
		self,
		row: pd.Series,
		block_lookup: Mapping[str, Set[str]],
	) -> Set[str]:
		resolved: Set[str] = set()
		for column in self._candidate_block_columns(row):
			for token in self._split_room_tokens(row.get(column)):
				resolved.update(block_lookup.get(CoreLabMappingConstraint._normalise(token), set()))
		return resolved

	@staticmethod
	def _merge_preference(
		existing: Optional[ComputerLabPreference],
		incoming: ComputerLabPreference,
	) -> ComputerLabPreference:
		if existing is None:
			return ComputerLabPreference(
				room_ids=set(incoming.room_ids),
				mode=incoming.mode,
				penalty_weight=incoming.penalty_weight,
			)
		if existing.mode == "hard":
			if incoming.mode == "hard":
				existing.room_ids.update(incoming.room_ids)
			return existing
		if incoming.mode == "hard":
			return ComputerLabPreference(
				room_ids=set(incoming.room_ids),
				mode="hard",
				penalty_weight=0,
			)
		existing.room_ids.update(incoming.room_ids)
		existing.penalty_weight = max(existing.penalty_weight, incoming.penalty_weight)
		return existing

	def _candidate_room_columns(self, row: pd.Series) -> Tuple[str, ...]:
		columns: list[str] = []
		row_lookup = {str(column).strip().lower(): str(column) for column in row.index}
		for configured in self._room_columns:
			actual = row_lookup.get(configured.lower())
			if actual is not None and actual not in columns:
				columns.append(actual)

		for column in row.index:
			name = str(column).strip()
			lower = name.lower()
			if name in columns:
				continue
			if lower.endswith("_block"):
				continue
			if lower.startswith("lab_") or lower.startswith("computer_lab_"):
				columns.append(name)
		return tuple(columns)

	def _candidate_block_columns(self, row: pd.Series) -> Tuple[str, ...]:
		columns: list[str] = []
		row_lookup = {str(column).strip().lower(): str(column) for column in row.index}

		for column in row.index:
			name = str(column).strip()
			lower = name.lower()
			if lower in {"block", "preferred_block", "preferred_lab_blocks", "computer_lab_blocks"}:
				columns.append(name)
				continue
			if not lower.endswith("_block"):
				continue

			prefix = lower[:-6]
			paired_room_column = row_lookup.get(f"{prefix}_room")
			if paired_room_column and not self._is_blank(row.get(paired_room_column)):
				continue
			columns.append(name)

		return tuple(dict.fromkeys(columns))

	@staticmethod
	def _build_computer_lab_block_lookup(rooms_df: pd.DataFrame) -> Mapping[str, Set[str]]:
		lookup: Dict[str, Set[str]] = {}
		for _, row in rooms_df.iterrows():
			room_id = str(row.get("id") or "").strip()
			block = row.get("block")
			if not room_id or ComputerLabMappingConstraint._is_blank(block):
				continue
			if not ComputerLabMappingConstraint._is_computer_lab_room(row):
				continue
			key = CoreLabMappingConstraint._normalise(str(block))
			if key:
				lookup.setdefault(key, set()).add(room_id)
		return lookup

	@staticmethod
	def _is_computer_lab_room(row: pd.Series) -> bool:
		room_type = str(row.get("room_type") or "").strip().lower()
		description = str(row.get("description") or "").strip().lower()
		return "computer" in room_type or "computer lab" in description

	def _department_keys(self, department: str, course_code: str) -> Set[str]:
		keys = {department}
		keys.update(self._department_aliases.get(department, ()))

		# The source sheets sometimes use "ae" for Automobile rows with AT course
		# codes, while AE-prefixed course codes belong to Aeronautical.
		if department == "ae":
			if course_code.startswith("AT"):
				keys.add("automobile engineering")
			elif course_code.startswith("AE"):
				keys.add("aeronautical engineering")
			else:
				keys.update(("aeronautical engineering", "automobile engineering"))

		return {key for key in keys if key}

	def _build_department_aliases(self, raw_aliases: object) -> Mapping[str, Tuple[str, ...]]:
		aliases: Dict[str, Set[str]] = {
			key: set(values)
			for key, values in self.DEFAULT_DEPARTMENT_ALIASES.items()
		}
		if isinstance(raw_aliases, Mapping):
			for raw_key, raw_value in raw_aliases.items():
				key = self._normalise_department(raw_key)
				if not key:
					continue
				values = raw_value if isinstance(raw_value, (list, tuple, set)) else (raw_value,)
				for value in values:
					normalised = self._normalise_department(value)
					if normalised:
						aliases.setdefault(key, set()).add(normalised)
		return {key: tuple(sorted(values)) for key, values in aliases.items()}

	@staticmethod
	def _split_room_tokens(value: object) -> Tuple[str, ...]:
		if ComputerLabMappingConstraint._is_blank(value):
			return tuple()
		text = str(value).strip()
		parts = [part.strip() for part in text.replace("|", ",").replace(";", ",").split(",")]
		return tuple(part for part in parts if part)

	@staticmethod
	def _first_value(row: pd.Series, columns: Tuple[str, ...]) -> str:
		lookup = {str(column).strip().lower(): column for column in row.index}
		for column in columns:
			key = lookup.get(column.lower())
			if key is None:
				continue
			value = row.get(key)
			if not ComputerLabMappingConstraint._is_blank(value):
				return str(value).strip()
		return ""

	@staticmethod
	def _is_blank(value: object) -> bool:
		if value is None:
			return True
		try:
			if pd.isna(value):
				return True
		except (TypeError, ValueError):
			pass
		text = str(value).strip()
		return not text or text.lower() in {"nan", "none", "null", "-"}

	@staticmethod
	def _normalise_department(value: object) -> str:
		text = str(value or "").strip().lower()
		return " ".join(text.replace("&", "and").split())

	@staticmethod
	def _normalise_course_code(value: object) -> str:
		return str(value or "").strip().upper()

	def _result(
		self,
		status: str,
		stats: ComputerLabMappingStats,
		extra_details: Optional[Mapping[str, object]] = None,
	) -> ConstraintApplicationResult:
		details = {
			"mode": self._mode,
			"penalty_weight": self._penalty_weight,
			"block_penalty_weight": self._block_penalty_weight,
			"mapping_rows": stats.mapping_rows,
			"hard_mapping_rows": stats.hard_mapping_rows,
			"soft_mapping_rows": stats.soft_mapping_rows,
			"mapped_course_instances": stats.mapped_course_instances,
			"soft_penalties": stats.soft_penalties,
			"hard_blocks": stats.hard_blocks,
			"unresolved_rows": tuple(stats.unresolved_rows),
			"missing_mapped_assignments": tuple(stats.missing_mapped_assignments),
		}
		if extra_details:
			details.update(extra_details)
		return ConstraintApplicationResult(
			name=self.metadata.name,
			domain=self.metadata.category,
			priority=self.metadata.priority,
			enabled=True,
			status=status,
			details=details,
		)


def build_computer_lab_mapping_constraint(
	metadata: ConstraintMetadata,
	*,
	params: Optional[Mapping[str, object]] = None,
) -> ComputerLabMappingConstraint:
	return ComputerLabMappingConstraint(metadata=metadata, params=params)


__all__ = [
	"ComputerLabMappingConstraint",
	"build_computer_lab_mapping_constraint",
]
