"""
app/services/distribution/persistence.py
=========================================
Shared DB helpers for distribution strategies.

Strategies own *what* the data model should look like per mode; these helpers own
the *how* of writing it (idempotent bucket/offering creation, safe reset on
re-distribution). All functions flush but never commit — the caller owns the
transaction boundary.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.curriculum import (
    CourseOffering,
    OfferingBucket,
    SelectionPolicy,
    TargetRequirement,
)


async def find_or_create_bucket(
    db: AsyncSession,
    *,
    institution_id: uuid.UUID,
    academic_term_id: uuid.UUID,
    department_id: uuid.UUID | None,
    name: str,
    selection_policy: SelectionPolicy,
    scenario_id: uuid.UUID | None,
    min_selection: int = 1,
    max_selection: int = 1,
    force_parallel_slots: bool = False,
) -> tuple[OfferingBucket, bool]:
    """Return (bucket, created). Matches on (institution, term, dept, name, policy, scenario).

    department_id is part of the match so same-named buckets in different
    departments (e.g. each cohort's "Group 1") never collide.
    """
    stmt = select(OfferingBucket).where(
        OfferingBucket.institution_id == institution_id,
        OfferingBucket.academic_term_id == academic_term_id,
        OfferingBucket.department_id == department_id,
        OfferingBucket.name == name,
        OfferingBucket.selection_policy == selection_policy,
        OfferingBucket.scenario_id == scenario_id,
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        return existing, False

    bucket = OfferingBucket(
        institution_id=institution_id,
        academic_term_id=academic_term_id,
        department_id=department_id,
        name=name,
        selection_policy=selection_policy,
        min_selection=min_selection,
        max_selection=max_selection,
        force_parallel_slots=force_parallel_slots,
        scenario_id=scenario_id,
    )
    db.add(bucket)
    await db.flush()
    return bucket, True


async def create_bucket(
    db: AsyncSession,
    *,
    institution_id: uuid.UUID,
    academic_term_id: uuid.UUID,
    department_id: uuid.UUID | None,
    name: str,
    selection_policy: SelectionPolicy,
    scenario_id: uuid.UUID | None,
    min_selection: int = 1,
    max_selection: int = 1,
    force_parallel_slots: bool = False,
) -> OfferingBucket:
    """Always create a fresh bucket (never reuse by name).

    Group buckets belong to exactly ONE cohort, so they must NOT be matched by
    name — otherwise two cohorts in the same dept (same-named "Group 1") would
    share a bucket and deleting one cohort would destroy the other's offerings.
    """
    bucket = OfferingBucket(
        institution_id=institution_id,
        academic_term_id=academic_term_id,
        department_id=department_id,
        name=name,
        selection_policy=selection_policy,
        min_selection=min_selection,
        max_selection=max_selection,
        force_parallel_slots=force_parallel_slots,
        scenario_id=scenario_id,
    )
    db.add(bucket)
    await db.flush()
    return bucket


async def ensure_target_requirement(
    db: AsyncSession,
    *,
    target_id: uuid.UUID,
    bucket_id: uuid.UUID,
) -> bool:
    """Create the target→bucket link if absent. Returns True if created."""
    stmt = select(TargetRequirement).where(
        TargetRequirement.target_id == target_id,
        TargetRequirement.bucket_id == bucket_id,
    )
    if (await db.execute(stmt)).scalar_one_or_none() is not None:
        return False
    db.add(TargetRequirement(target_id=target_id, bucket_id=bucket_id))
    await db.flush()
    return True


async def create_offering(
    db: AsyncSession,
    *,
    bucket_id: uuid.UUID | None,
    course_id: uuid.UUID,
    faculty_id: uuid.UUID | None,
    min_capacity: int | None,
    is_frozen: bool = False,
    group_number: int | None = None,
    study_year: int | None = None,
    study_semester: int | None = None,
    ta_kwargs: dict[str, Any] | None = None,
) -> CourseOffering:
    """Create a CourseOffering. group_number/study_* are set atomically here."""
    offering = CourseOffering(
        bucket_id=bucket_id,
        course_id=course_id,
        faculty_id=faculty_id,
        min_capacity=min_capacity,
        is_frozen=is_frozen,
        group_number=group_number,
        study_year=study_year,
        study_semester=study_semester,
        **(ta_kwargs or {}),
    )
    db.add(offering)
    await db.flush()
    return offering


async def reset_prior_distribution(
    db: AsyncSession,
    cohort_id: uuid.UUID,
    *,
    full_reset: bool = False,
) -> int:
    """Clear a cohort's auto-created distribution so it can be rebuilt.

    By default (``full_reset=False``) only deletes offerings with ``slot_code IS NULL``
    and drops buckets that become empty — preserving solved placements.

    ``full_reset=True`` removes every offering in the cohort's buckets, then deletes
    all linked buckets and TargetRequirements. Used by solver regroup retries and
    forced re-distribution so stale solved groups cannot accumulate.
    """
    req_rows = (
        await db.execute(
            select(TargetRequirement).where(TargetRequirement.target_id == cohort_id)
        )
    ).scalars().all()
    bucket_ids = [r.bucket_id for r in req_rows]
    if not bucket_ids:
        return 0

    offerings = (
        await db.execute(
            select(CourseOffering).where(CourseOffering.bucket_id.in_(bucket_ids))
        )
    ).scalars().all()

    deleted = 0
    for off in offerings:
        if full_reset or off.slot_code is None:
            await db.delete(off)
            deleted += 1
    await db.flush()

    if full_reset:
        for req in req_rows:
            await db.delete(req)
        for bid in bucket_ids:
            bucket = (
                await db.execute(select(OfferingBucket).where(OfferingBucket.id == bid))
            ).scalar_one_or_none()
            if bucket is not None:
                await db.delete(bucket)
        await db.flush()
        return deleted

    # Drop buckets that are now empty (all offerings removed) + their requirement link.
    for bid in bucket_ids:
        remaining = (
            await db.execute(
                select(CourseOffering.id).where(CourseOffering.bucket_id == bid).limit(1)
            )
        ).first()
        if remaining is not None:
            continue
        req = (
            await db.execute(
                select(TargetRequirement).where(
                    TargetRequirement.target_id == cohort_id,
                    TargetRequirement.bucket_id == bid,
                )
            )
        ).scalar_one_or_none()
        if req is not None:
            await db.delete(req)
        bucket = (
            await db.execute(select(OfferingBucket).where(OfferingBucket.id == bid))
        ).scalar_one_or_none()
        if bucket is not None:
            await db.delete(bucket)
    await db.flush()

    return deleted
