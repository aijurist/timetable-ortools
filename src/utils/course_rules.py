"""Shared predicates for exceptional course-delivery rules."""

from __future__ import annotations


EXTERNAL_STAFF_PROXY_TAG = "external_staff_proxy"


def ignores_teacher_constraints(requirement: object) -> bool:
	"""Return whether a requirement's teacher ID is only a pairing label."""

	tags = getattr(requirement, "tags", ()) or ()
	return EXTERNAL_STAFF_PROXY_TAG in {
		str(tag).strip().lower() for tag in tags if str(tag).strip()
	}


__all__ = ["EXTERNAL_STAFF_PROXY_TAG", "ignores_teacher_constraints"]
