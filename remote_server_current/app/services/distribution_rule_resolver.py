"""
app/services/distribution_rule_resolver.py
==========================================
Resolve the active distribution rule for a given course.

Distribution rules are ScenarioRule rows with rule_type=DISTRIBUTION.
CROSS_DEPT_SHARING (per-course override) wins over the base mode rule.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.constraint import ScenarioRule

# Codes treated as "base" distribution rules (one per scenario)
BASE_DIST_CODES: frozenset[str] = frozenset({
    "TRADITIONAL_DIST",
    "HYBRID_DIST",
    "FFCS_DIST",
})


def resolve_distribution_rule(
    course_id: str,
    active_dist_rules: list["ScenarioRule"],
) -> "ScenarioRule | None":
    """
    Return the most specific DISTRIBUTION rule for a course.

    Priority:
      1. CROSS_DEPT_SHARING with course_id in params.course_ids
      2. Base rule (TRADITIONAL_DIST / HYBRID_DIST / FFCS_DIST)
      3. None if no distribution rules are configured
    """
    for rule in active_dist_rules:
        if rule.definition_code == "CROSS_DEPT_SHARING":
            course_ids = (rule.params or {}).get("course_ids", [])
            if course_id in [str(c) for c in course_ids]:
                return rule

    for rule in active_dist_rules:
        if rule.definition_code in BASE_DIST_CODES:
            return rule

    return None
