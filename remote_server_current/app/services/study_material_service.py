"""
app/services/study_material_service.py
=========================================
CRUD for study content: CourseNotes, ExamPapers, StudyGuides.

Responsibilities
----------------
* ``list_notes`` / ``create_note`` / ``get_note_or_404`` / ``update_note`` / ``delete_note``
* ``list_papers`` / ``create_paper`` / ``get_paper_or_404`` / ``update_paper`` / ``delete_paper``
* ``build_guide`` — create a StudyGuide entry linking a batch to a note or paper.
* ``list_guides`` — return all StudyGuide entries ordered by week.

Architecture note
-----------------
content_text on CourseNote and ExamPaper feeds the Campus Brain RAG pipeline.
A GIN full-text index (gin_trgm_ops) on content_text is created by the Alembic
migration.  This service does NOT trigger RAG ingestion — that is a Celery task.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.logger import logger
from app.models.audit_log import AuditAction
from app.models.study_material import CourseNote, ExamPaper, StudyGuide
from app.schemas.study_material import (
    CourseNoteCreate,
    CourseNoteUpdate,
    ExamPaperCreate,
    ExamPaperUpdate,
    StudyGuideCreate,
)
import app.services.audit_log_service as audit_log_service


# ---------------------------------------------------------------------------
# CourseNote
# ---------------------------------------------------------------------------


async def list_notes(
    db: AsyncSession,
    course_id: uuid.UUID,
    *,
    batch_id: Optional[uuid.UUID] = None,
    skip: int = 0,
    limit: int = 50,
) -> list[CourseNote]:
    q = select(CourseNote).where(CourseNote.course_id == course_id)
    if batch_id is not None:
        q = q.where(CourseNote.batch_id == batch_id)
    q = q.order_by(CourseNote.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


async def get_note_or_404(db: AsyncSession, note_id: uuid.UUID) -> CourseNote:
    result = await db.execute(select(CourseNote).where(CourseNote.id == note_id))
    note = result.scalars().first()
    if note is None:
        raise NotFoundError(f"CourseNote {note_id} not found")
    return note


async def create_note(
    db: AsyncSession,
    payload: CourseNoteCreate,
) -> CourseNote:
    note = CourseNote(**payload.model_dump())
    db.add(note)
    await db.flush()
    logger.info("CourseNote created", note_id=str(note.id), course_id=str(note.course_id))
    await audit_log_service.record(
        db,
        actor_user_id=None,
        actor_role=None,
        action=AuditAction.CREATED,
        entity_type="CourseNote",
        entity_id=note.id,
        entity_label=note.title if hasattr(note, "title") else str(note.id),
        institution_id=None,
        after={"course_id": str(note.course_id)},
    )
    return note


async def update_note(
    db: AsyncSession,
    note_id: uuid.UUID,
    payload: CourseNoteUpdate,
) -> CourseNote:
    note = await get_note_or_404(db, note_id)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(note, field, value)
    await db.flush()
    await audit_log_service.record(
        db,
        actor_user_id=None,
        actor_role=None,
        action=AuditAction.UPDATED,
        entity_type="CourseNote",
        entity_id=note_id,
        institution_id=None,
        after={k: str(v) if v is not None else None for k, v in changes.items()},
    )
    return note


async def delete_note(db: AsyncSession, note_id: uuid.UUID) -> None:
    note = await get_note_or_404(db, note_id)
    _course_id = note.course_id
    await db.delete(note)
    await db.flush()
    logger.info("CourseNote deleted", note_id=str(note_id))
    await audit_log_service.record(
        db,
        actor_user_id=None,
        actor_role=None,
        action=AuditAction.DELETED,
        entity_type="CourseNote",
        entity_id=note_id,
        institution_id=None,
        before={"course_id": str(_course_id)},
    )


# ---------------------------------------------------------------------------
# ExamPaper
# ---------------------------------------------------------------------------


async def list_papers(
    db: AsyncSession,
    course_id: uuid.UUID,
    *,
    skip: int = 0,
    limit: int = 50,
) -> list[ExamPaper]:
    result = await db.execute(
        select(ExamPaper)
        .where(ExamPaper.course_id == course_id)
        .order_by(ExamPaper.year.desc(), ExamPaper.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_paper_or_404(db: AsyncSession, paper_id: uuid.UUID) -> ExamPaper:
    result = await db.execute(select(ExamPaper).where(ExamPaper.id == paper_id))
    paper = result.scalars().first()
    if paper is None:
        raise NotFoundError(f"ExamPaper {paper_id} not found")
    return paper


async def create_paper(
    db: AsyncSession,
    payload: ExamPaperCreate,
) -> ExamPaper:
    paper = ExamPaper(**payload.model_dump())
    db.add(paper)
    await db.flush()
    logger.info("ExamPaper created", paper_id=str(paper.id))
    await audit_log_service.record(
        db,
        actor_user_id=None,
        actor_role=None,
        action=AuditAction.CREATED,
        entity_type="ExamPaper",
        entity_id=paper.id,
        institution_id=None,
        after={"course_id": str(paper.course_id), "year": getattr(paper, "year", None)},
    )
    return paper


async def update_paper(
    db: AsyncSession,
    paper_id: uuid.UUID,
    payload: ExamPaperUpdate,
) -> ExamPaper:
    paper = await get_paper_or_404(db, paper_id)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(paper, field, value)
    await db.flush()
    await audit_log_service.record(
        db,
        actor_user_id=None,
        actor_role=None,
        action=AuditAction.UPDATED,
        entity_type="ExamPaper",
        entity_id=paper_id,
        institution_id=None,
        after={k: str(v) if v is not None else None for k, v in changes.items()},
    )
    return paper


async def delete_paper(db: AsyncSession, paper_id: uuid.UUID) -> None:
    paper = await get_paper_or_404(db, paper_id)
    _course_id = paper.course_id
    await db.delete(paper)
    await db.flush()
    logger.info("ExamPaper deleted", paper_id=str(paper_id))
    await audit_log_service.record(
        db,
        actor_user_id=None,
        actor_role=None,
        action=AuditAction.DELETED,
        entity_type="ExamPaper",
        entity_id=paper_id,
        institution_id=None,
        before={"course_id": str(_course_id)},
    )


# ---------------------------------------------------------------------------
# StudyGuide
# ---------------------------------------------------------------------------


async def list_guides(
    db: AsyncSession,
    batch_id: uuid.UUID,
    *,
    course_id: Optional[uuid.UUID] = None,
) -> list[StudyGuide]:
    q = select(StudyGuide).where(StudyGuide.batch_id == batch_id)
    if course_id is not None:
        # Join via note or paper to filter by course
        q = q.join(CourseNote, StudyGuide.note_id == CourseNote.id, isouter=True).where(
            CourseNote.course_id == course_id
        )
    q = q.order_by(StudyGuide.week_number)
    result = await db.execute(q)
    return list(result.scalars().all())


async def get_guide_or_404(db: AsyncSession, guide_id: uuid.UUID) -> StudyGuide:
    result = await db.execute(select(StudyGuide).where(StudyGuide.id == guide_id))
    guide = result.scalars().first()
    if guide is None:
        raise NotFoundError(f"StudyGuide entry {guide_id} not found")
    return guide


async def build_guide(
    db: AsyncSession,
    payload: StudyGuideCreate,
) -> StudyGuide:
    """
    Add a study guide entry for a batch.

    A guide entry links a batch to a CourseNote or ExamPaper at a specific
    week and position.  At least one of ``note_id`` or ``paper_id`` must be set.
    """
    if payload.note_id is None and payload.exam_paper_id is None:
        from app.core.exceptions import ValidationError
        raise ValidationError("StudyGuide must reference a note_id or exam_paper_id")

    guide = StudyGuide(**payload.model_dump())
    db.add(guide)
    await db.flush()
    logger.info(
        "StudyGuide entry created",
        guide_id=str(guide.id),
        batch_id=str(guide.batch_id),
        week=guide.week_number,
    )
    await audit_log_service.record(
        db,
        actor_user_id=None,
        actor_role=None,
        action=AuditAction.CREATED,
        entity_type="StudyGuide",
        entity_id=guide.id,
        institution_id=None,
        after={"batch_id": str(guide.batch_id), "week_number": guide.week_number},
    )
    return guide


async def delete_guide(db: AsyncSession, guide_id: uuid.UUID) -> None:
    guide = await get_guide_or_404(db, guide_id)
    _batch_id = guide.batch_id
    await db.delete(guide)
    await db.flush()
    logger.info("StudyGuide entry deleted", guide_id=str(guide_id))
    await audit_log_service.record(
        db,
        actor_user_id=None,
        actor_role=None,
        action=AuditAction.DELETED,
        entity_type="StudyGuide",
        entity_id=guide_id,
        institution_id=None,
        before={"batch_id": str(_batch_id)},
    )
