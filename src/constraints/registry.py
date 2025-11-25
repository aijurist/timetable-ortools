
"""Constraint registry consumed by the modular model builder."""

from __future__ import annotations

from typing import Callable, Mapping, Sequence

from ..config.schemas import ConstraintSetting, SchedulerConfig
from .base import ConstraintMetadata
from .cross_system.five_pm_policy import build_five_pm_policy_constraint
from .cross_system.lunch_alignment import build_lunch_alignment_constraint
from .lab.core_lab import build_core_lab_mapping_constraint
from .lab.requirements import build_lab_session_coverage_constraint
from .lab.room_single_assignment import build_lab_room_single_assignment_constraint
from .lab.slot_caps import (
	build_computing_group_slot_cap_constraint,
	build_core_lab_group_slot_cap_constraint,
	build_semester_lab_slot_cap_constraint,
)
from .lab.teacher_max_consecutive import build_teacher_max_consecutive_lab_constraint
from .theory.adjacency import build_no_three_consecutive_slots_constraint
from .theory.requirements import (
	build_theory_daily_slot_cap_constraint,
	build_theory_slot_coverage_constraint,
)
from .schema import ConstraintRegistration


LAB_CONSTRAINT_DEFINITIONS = {
	"session_coverage": {
		"title": "Lab Session Coverage",
		"description": "Ensure each lab course receives the configured number of sessions per week.",
		"factory": build_lab_session_coverage_constraint,
		"tags": ("lab", "coverage"),
	},
	"room_single_assignment": {
		"title": "Lab Room Single Assignment",
		"description": "Prevent double-booking lab rooms and multi-room sessions for any course instance.",
		"factory": build_lab_room_single_assignment_constraint,
		"tags": ("lab", "rooms", "exclusivity"),
	},
	"core_lab_mapping": {
		"title": "Core Lab Room Mapping",
		"description": "Restrict mapped core labs to their designated laboratory rooms while keeping others flexible.",
		"factory": build_core_lab_mapping_constraint,
		"tags": ("lab", "rooms", "core"),
	},
	"core_group_slot_cap": {
		"title": "Core Group Slot Cap",
		"description": "Prefer core lab groups to occupy no more than the configured number of unique lab slots (soft cap).",
		"factory": build_core_lab_group_slot_cap_constraint,
		"tags": ("lab", "core", "slots"),
	},
	"computing_group_slot_cap": {
		"title": "Computing Group Slot Cap",
		"description": "Limit computing department lab groups to a strict maximum of unique lab slots (hard cap).",
		"factory": build_computing_group_slot_cap_constraint,
		"tags": ("lab", "slots", "computing"),
	},
	"semester_slot_cap": {
		"title": "Semester Lab Slot Cap",
		"description": "Cap the number of non-core lab slots consumed by each department-semester pair.",
		"factory": build_semester_lab_slot_cap_constraint,
		"tags": ("lab", "slots", "semester"),
	},
	"teacher_max_consecutive": {
		"title": "Teacher Max Consecutive Lab Sessions",
		"description": "Limit teachers to at most two consecutive lab sessions, with optional soft overrides per department.",
		"factory": build_teacher_max_consecutive_lab_constraint,
		"tags": ("lab", "teachers", "adjacency"),
	},
}


THEORY_CONSTRAINT_DEFINITIONS = {
	"slot_coverage": {
		"title": "Theory Slot Coverage",
		"description": "Match each theory group with its exact required number of weekly slots.",
		"factory": build_theory_slot_coverage_constraint,
		"tags": ("theory", "coverage"),
	},
	"daily_slot_cap": {
		"title": "Theory Daily Slot Cap",
		"description": "Limit how many unique theory slots a department may occupy per day.",
		"factory": build_theory_daily_slot_cap_constraint,
		"tags": ("theory", "load"),
	},
	"no_three_consecutive": {
		"title": "No Three Consecutive Theory Slots",
		"description": "Block any group from holding three consecutive theory slots.",
		"factory": build_no_three_consecutive_slots_constraint,
		"tags": ("theory", "adjacency"),
	},
}


CROSS_SYSTEM_CONSTRAINT_DEFINITIONS = {
	"lunch_alignment": {
		"title": "Unified Lunch Alignment",
		"description": "Reserve a shared lunch window across lab and theory (flexible departments allowed).",
		"factory": build_lunch_alignment_constraint,
		"tags": ("cross-system", "lunch"),
	},
	"five_pm_policy": {
		"title": "Department 5PM Policy",
		"description": "Block or penalize late sessions for configured departments across lab and theory.",
		"factory": build_five_pm_policy_constraint,
		"tags": ("cross-system", "time", "policy"),
	},
}


def get_constraint_registrations(config: SchedulerConfig) -> Sequence[ConstraintRegistration]:
	"""Return the ordered list of constraint registrations."""

	registrations = []
	registrations.extend(
		_build_domain_registrations(
			domain="lab",
			definitions=LAB_CONSTRAINT_DEFINITIONS,
			settings=config.constraints.lab,
		)
	)
	registrations.extend(
		_build_domain_registrations(
			domain="theory",
			definitions=THEORY_CONSTRAINT_DEFINITIONS,
			settings=config.constraints.theory,
		)
	)
	registrations.extend(
		_build_domain_registrations(
			domain="cross_system",
			definitions=CROSS_SYSTEM_CONSTRAINT_DEFINITIONS,
			settings=config.constraints.cross_system,
		)
	)
	return tuple(registrations)


def _build_domain_registrations(
	domain: str,
	definitions: Mapping[str, Mapping[str, object]],
	settings: Mapping[str, ConstraintSetting],
) -> Sequence[ConstraintRegistration]:
	entries = []
	for identifier, definition in definitions.items():
		setting = settings.get(identifier)
		if setting is None:
			continue
		metadata = ConstraintMetadata(
			id=f"{domain}.{identifier}",
			name=definition["title"],
			category=domain,
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
