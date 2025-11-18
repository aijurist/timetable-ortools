
"""Constraint registry consumed by the modular model builder."""

from __future__ import annotations

from typing import Callable, Mapping, Sequence

from ..config.schemas import ConstraintSetting, SchedulerConfig
from .base import ConstraintMetadata
from .lab.core_lab import build_core_lab_mapping_constraint
from .lab.requirements import build_lab_session_coverage_constraint
from .schema import ConstraintRegistration


LAB_CONSTRAINT_DEFINITIONS = {
	"session_coverage": {
		"title": "Lab Session Coverage",
		"description": "Ensure each lab course receives the configured number of sessions per week.",
		"factory": build_lab_session_coverage_constraint,
		"tags": ("lab", "coverage"),
	},
	"core_lab_mapping": {
		"title": "Core Lab Room Mapping",
		"description": "Restrict mapped core labs to their designated laboratory rooms while keeping others flexible.",
		"factory": build_core_lab_mapping_constraint,
		"tags": ("lab", "rooms", "core"),
	},
}


def get_constraint_registrations(config: SchedulerConfig) -> Sequence[ConstraintRegistration]:
	"""Return the ordered list of constraint registrations."""

	registrations = []
	registrations.extend(_build_lab_registrations(config.constraints.lab))
	return tuple(registrations)


def _build_lab_registrations(settings: Mapping[str, ConstraintSetting]) -> Sequence[ConstraintRegistration]:
	entries = []
	for identifier, definition in LAB_CONSTRAINT_DEFINITIONS.items():
		setting = settings.get(identifier)
		if setting is None:
			continue
		metadata = ConstraintMetadata(
			id=f"lab.{identifier}",
			name=definition["title"],
			category="lab",
			priority=setting.priority,
			description=definition["description"],
			tags=definition["tags"],
			weight=setting.weight,
			params=setting.params,
		)
		constraint = definition["factory"](metadata=metadata, params=setting.params)
		entries.append(
			ConstraintRegistration(
				name=metadata.name,
				domain=metadata.category,
				priority=metadata.priority,
				enabled=setting.enabled,
				builder=_wrap_builder(constraint),
				tags=metadata.tags,
				parameters=setting.params,
			)
		)
	return tuple(entries)


def _wrap_builder(constraint) -> Callable:
	def _builder(context):
		return constraint.apply(context)

	return _builder


__all__ = ["ConstraintRegistration", "get_constraint_registrations"]
