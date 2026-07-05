"""
app/schemas/allocation_rule.py
==============================
Pydantic V2 schemas for AllocationRule.
"""
import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


# ---------------------------------------------------------------------------
# Catalogue (seeded per scenario on creation)
# ---------------------------------------------------------------------------

ALLOCATION_RULE_CATALOGUE: list[dict] = [
    {
        "rule_code": "WORKLOAD_CAP",
        "is_enabled": True,
        "params": {},
        "description": "Block assignments that exceed faculty max_weekly_hours",
        "category": "WORKLOAD",
    },
    {
        "rule_code": "BALANCE_WORKLOAD",
        "is_enabled": True,
        "params": {},
        "description": "Minimise the max-min workload gap across all faculty",
        "category": "WORKLOAD",
    },
    {
        "rule_code": "EQUAL_SECTION_DISTRIBUTION",
        "is_enabled": True,
        "params": {},
        "description": "Limit each teacher to one section per course per group — prevents a single teacher covering multiple sections of the same course in the same cohort",
        "category": "WORKLOAD",
    },
    {
        "rule_code": "SOLVER_FILL_ENABLED",
        "is_enabled": True,
        "params": {},
        "description": "Allow solver to auto-assign unassigned sections from eligible faculty",
        "category": "ASSIGNMENT_FILL",
    },
    {
        "rule_code": "MAX_COURSES_PER_FACULTY",
        "is_enabled": False,
        "params": {"max_courses": 3},
        "description": "Cap the number of distinct courses per faculty",
        "category": "ASSIGNMENT_FILL",
    },
    {
        "rule_code": "CROSS_DEPT_ALLOWED",
        "is_enabled": True,
        "params": {},
        "description": "Allow solver-fill to draw faculty from other departments",
        "category": "CROSS_DEPARTMENT",
    },
    {
        "rule_code": "DEPT_PREFERENCE",
        "is_enabled": True,
        "params": {"penalty": 0.3},
        "description": "Penalise cross-department fills vs same-department assignments",
        "category": "CROSS_DEPARTMENT",
    },
]


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class AllocationRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    scenario_id: uuid.UUID
    rule_code: str
    is_enabled: bool
    params: Optional[dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime


class AllocationRuleUpdate(BaseModel):
    is_enabled: Optional[bool] = None
    params: Optional[dict[str, Any]] = None
