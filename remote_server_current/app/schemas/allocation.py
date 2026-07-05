"""
app/schemas/allocation.py
==========================
Pydantic schemas for the pre-solve allocation layer.

Flow:
  1. Coordinator POSTs TargetCourseDemandCreate entries to define curriculum demand.
  2. Coordinator POSTs AllocationRunRequest with per-course faculty eligibility.
  3. System runs CP-SAT mini-solver → creates OfferingBuckets + CourseOfferings.
  4. AllocationResult returned for review.
  5. GET /scenarios/{id}/allocation → AllocationState (is_ready_for_solve flag).
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# TargetCourseDemand schemas
# ---------------------------------------------------------------------------


class TargetCourseDemandCreate(BaseModel):
    institution_id: uuid.UUID
    academic_term_id: uuid.UUID
    target_id: uuid.UUID
    course_id: uuid.UUID
    required_sections: int = Field(default=1, ge=1, le=100)
    notes: str | None = None


class TargetCourseDemandBulkCreate(BaseModel):
    """Create multiple demand entries for one target in one request."""
    institution_id: uuid.UUID
    academic_term_id: uuid.UUID
    target_id: uuid.UUID
    course_ids: list[uuid.UUID]
    required_sections: int = Field(
        default=1, ge=1, le=100,
        description="Applied to all courses in this bulk request",
    )
    notes: str | None = None


class TargetCourseDemandResponse(BaseModel):
    id: uuid.UUID
    institution_id: uuid.UUID
    academic_term_id: uuid.UUID
    target_id: uuid.UUID
    course_id: uuid.UUID
    required_sections: int
    notes: str | None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Allocation run schemas
# ---------------------------------------------------------------------------


class PinnedAssignment(BaseModel):
    """Explicit teacher→section pin for TRADITIONAL mode."""

    target_id: uuid.UUID = Field(..., description="Actual BATCH target UUID")
    faculty_id: uuid.UUID


class CourseAssignment(BaseModel):
    """Per-course coordinator input: which faculty are eligible + bucket scope."""

    course_id: uuid.UUID
    faculty_ids: list[uuid.UUID] = Field(
        description="Eligible faculty for this course at allocation time"
    )
    pinned: list[PinnedAssignment] | None = Field(
        default=None,
        description="TRADITIONAL only: explicit target→faculty overrides; these sections bypass CP-SAT",
    )
    allocation_mode: Literal[
        "per_section",
        "shared_dept",
        "shared_cross_dept",
        "open_pool",
    ] | None = Field(
        default=None,
        description=(
            "None → derived from institution.scheduling_mode: "
            "TRADITIONAL→per_section, HYBRID→shared_dept, "
            "ELECTIVE→per_section, FFCS→open_pool"
        ),
    )


class AllocationRunRequest(BaseModel):
    assignments: list[CourseAssignment] = Field(
        description="Per-course faculty eligibility and bucket scope"
    )
    overwrite_existing: bool = Field(
        default=False,
        description="Re-assign faculty on already-created offerings",
    )
    dry_run: bool = Field(
        default=False,
        description="Preview the allocation without writing to DB",
    )


# ---------------------------------------------------------------------------
# Allocation result schemas
# ---------------------------------------------------------------------------


class AllocationOfferingDetail(BaseModel):
    target_id: uuid.UUID
    target_name: str
    course_id: uuid.UUID
    course_name: str
    faculty_id: uuid.UUID | None
    faculty_name: str | None
    offering_id: uuid.UUID | None   # NULL if dry_run
    bucket_id: uuid.UUID | None
    is_new: bool                    # True if created by this allocation run


class AllocationResult(BaseModel):
    demands_processed: int
    buckets_created: int
    offerings_created: int
    offerings_updated: int
    warnings: list[str]
    unassigned: list[str]   # "course / target" pairs with no eligible faculty
    details: list[AllocationOfferingDetail]
    is_dry_run: bool


# ---------------------------------------------------------------------------
# Allocation state schemas (GET /scenarios/{id}/allocation)
# ---------------------------------------------------------------------------


class AllocationStateOffering(BaseModel):
    offering_id: uuid.UUID
    course_id: uuid.UUID
    course_name: str
    faculty_id: uuid.UUID | None
    faculty_name: str | None
    bucket_id: uuid.UUID
    selection_policy: str


class AllocationState(BaseModel):
    scenario_id: uuid.UUID
    demands_total: int
    demands_with_faculty: int       # CourseOfferings that have faculty_id set
    demands_without_faculty: int    # Still TBA
    offerings: list[AllocationStateOffering]
    is_ready_for_solve: bool        # True when demands_without_faculty == 0
