"""
app/services/elective_pool_service.py
======================================
CRUD for ElectivePool (PE-1, OE-1 … groupings in the Planning section).
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.models.course import ElectiveType
from app.models.curriculum import TeachingAssignment
from app.models.elective_pool import ElectivePool


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


async def list_pools(
    db: AsyncSession,
    institution_id: uuid.UUID,
    *,
    academic_term_id: uuid.UUID | None = None,
    department_id: uuid.UUID | None = None,
    study_semester: int | None = None,
    elective_type: ElectiveType | None = None,
    active_only: bool = True,
) -> list[ElectivePool]:
    stmt = select(ElectivePool).where(ElectivePool.institution_id == institution_id)
    if academic_term_id:
        stmt = stmt.where(ElectivePool.academic_term_id == academic_term_id)
    if department_id:
        stmt = stmt.where(ElectivePool.department_id == department_id)
    if study_semester is not None:
        stmt = stmt.where(ElectivePool.study_semester == study_semester)
    if elective_type is not None:
        stmt = stmt.where(ElectivePool.elective_type == elective_type)
    if active_only:
        stmt = stmt.where(ElectivePool.is_active == True)  # noqa: E712
    stmt = stmt.order_by(ElectivePool.study_semester, ElectivePool.label)
    return list((await db.execute(stmt)).scalars().all())


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


async def create_pool(
    db: AsyncSession,
    *,
    institution_id: uuid.UUID,
    academic_term_id: uuid.UUID,
    department_id: uuid.UUID,
    study_semester: int,
    label: str,
    elective_type: ElectiveType = ElectiveType.PROFESSIONAL,
) -> ElectivePool:
    # Reject duplicate label within the same dept+term+semester
    exists_stmt = select(ElectivePool).where(
        ElectivePool.academic_term_id == academic_term_id,
        ElectivePool.department_id == department_id,
        ElectivePool.study_semester == study_semester,
        ElectivePool.label == label,
    )
    if (await db.execute(exists_stmt)).scalar_one_or_none() is not None:
        raise ValidationError(
            f"Pool '{label}' already exists for this department in semester {study_semester}."
        )
    pool = ElectivePool(
        institution_id=institution_id,
        academic_term_id=academic_term_id,
        department_id=department_id,
        study_semester=study_semester,
        label=label,
        elective_type=elective_type,
    )
    db.add(pool)
    await db.flush()
    return pool


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


async def update_pool(
    db: AsyncSession,
    pool_id: uuid.UUID,
    patch: dict[str, Any],
) -> ElectivePool:
    pool = await _get_or_404(db, pool_id)
    for key, val in patch.items():
        setattr(pool, key, val)
    await db.flush()
    return pool


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


async def delete_pool(db: AsyncSession, pool_id: uuid.UUID) -> None:
    pool = await _get_or_404(db, pool_id)
    # DB CASCADE (SET NULL) on elective_pool_id handles TA unlinking automatically.
    await db.delete(pool)
    await db.flush()


# ---------------------------------------------------------------------------
# Assign / unassign TAs
# ---------------------------------------------------------------------------


async def assign_ta_to_pool(
    db: AsyncSession,
    ta_id: uuid.UUID,
    pool_id: uuid.UUID | None,
) -> TeachingAssignment:
    """Set (or clear) elective_pool_id on a TeachingAssignment."""
    ta = (
        await db.execute(select(TeachingAssignment).where(TeachingAssignment.id == ta_id))
    ).scalar_one_or_none()
    if ta is None:
        raise NotFoundError(f"TeachingAssignment {ta_id} not found")
    if pool_id is not None:
        pool = await _get_or_404(db, pool_id)
        # Auto-enforce merged when section_count > 1 inside a pool
        if ta.section_count > 1:
            ta.is_merged_session = True
        _ = pool  # ensure loaded
    ta.elective_pool_id = pool_id
    await db.flush()
    return ta


# ---------------------------------------------------------------------------
# Pool summary (for UI preview)
# ---------------------------------------------------------------------------


async def get_pool_summary(
    db: AsyncSession,
    pool_id: uuid.UUID,
) -> dict[str, Any]:
    """Returns pool + list of TAs with section info."""
    pool = await _get_or_404(db, pool_id)
    tas_result = await db.execute(
        select(TeachingAssignment).where(TeachingAssignment.elective_pool_id == pool_id)
    )
    tas = list(tas_result.scalars().all())
    total_sections = sum(ta.section_count for ta in tas)
    return {
        "pool_id": str(pool.id),
        "label": pool.label,
        "elective_type": pool.elective_type.value,
        "study_semester": pool.study_semester,
        "total_sections": total_sections,
        "assignments": [
            {
                "ta_id": str(ta.id),
                "course_id": str(ta.course_id),
                "faculty_id": str(ta.faculty_id) if ta.faculty_id else None,
                "section_count": ta.section_count,
                "is_merged": ta.is_merged_session,
            }
            for ta in tas
        ],
    }


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------


async def _get_or_404(db: AsyncSession, pool_id: uuid.UUID) -> ElectivePool:
    pool = (
        await db.execute(select(ElectivePool).where(ElectivePool.id == pool_id))
    ).scalar_one_or_none()
    if pool is None:
        raise NotFoundError(f"ElectivePool {pool_id} not found")
    return pool
