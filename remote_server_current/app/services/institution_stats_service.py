"""
app/services/institution_stats_service.py
===========================================
Aggregate resource counts for an institution.
Bypasses HOD department filters — only returns counts, not individual records.
"""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Course
from app.models.faculty import Faculty
from app.models.institution import Department
from app.models.room import Room
from app.schemas.institution import InstitutionStatsResponse


async def get_institution_stats(
    db: AsyncSession,
    institution_id: uuid.UUID,
) -> InstitutionStatsResponse:
    faculty_total = await db.scalar(
        select(func.count(Faculty.id)).where(
            Faculty.institution_id == institution_id,
            Faculty.is_active == True,
        )
    ) or 0

    course_total = await db.scalar(
        select(func.count(Course.id)).where(
            Course.institution_id == institution_id,
            Course.is_active == True,
        )
    ) or 0

    room_total = await db.scalar(
        select(func.count(Room.id)).where(
            Room.institution_id == institution_id,
            Room.is_active == True,
        )
    ) or 0

    department_total = await db.scalar(
        select(func.count(Department.id)).where(
            Department.institution_id == institution_id,
            Department.is_active == True,
        )
    ) or 0

    return InstitutionStatsResponse(
        faculty_total=faculty_total,
        course_total=course_total,
        room_total=room_total,
        department_total=department_total,
    )
