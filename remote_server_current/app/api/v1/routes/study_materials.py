"""
study_materials.py
==================
Study content management — CourseNotes, ExamPapers, and StudyGuides.

Architecture Note
-----------------
``uploaded_by`` references ``users.id`` — not ``faculty.id``.
Admins, HODs, and faculty all upload content as Users.

The ``content_text`` field on notes & papers feeds the Campus Brain RAG
pipeline. GIN full-text index is on content_text (gin_trgm_ops). The RAG
ingestion is triggered by a separate Celery task outside this router.

CourseNotes  (prefix /study-materials/notes)
--------------------------------------------
GET    /study-materials/notes                  List notes for a course
POST   /study-materials/notes                  Create a note
GET    /study-materials/notes/{id}             Get a note
PATCH  /study-materials/notes/{id}             Update a note
DELETE /study-materials/notes/{id}             Delete a note

ExamPapers  (prefix /study-materials/papers)
--------------------------------------------
GET    /study-materials/papers                 List papers for a course
POST   /study-materials/papers                 Create a paper
GET    /study-materials/papers/{id}            Get a paper
PATCH  /study-materials/papers/{id}            Update a paper
DELETE /study-materials/papers/{id}            Delete a paper

StudyGuides  (prefix /study-materials/guides)
---------------------------------------------
GET    /study-materials/guides                 List guide entries for a batch
POST   /study-materials/guides                 Build a guide entry
GET    /study-materials/guides/{id}            Get a guide entry
DELETE /study-materials/guides/{id}            Delete a guide entry
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import (
    CurrentUser,
    PaginationParams,
    get_current_user,
    get_db,
    get_pagination,
    require_hod,
)
from app.schemas.study_material import (
    CourseNoteCreate,
    CourseNoteListResponse,
    CourseNoteResponse,
    CourseNoteUpdate,
    ExamPaperCreate,
    ExamPaperListResponse,
    ExamPaperResponse,
    ExamPaperUpdate,
    StudyGuideCreate,
    StudyGuideListResponse,
    StudyGuideResponse,
)
import app.services.study_material_service as study_svc

notes_router = APIRouter()
papers_router = APIRouter()
guides_router = APIRouter()


# ===========================================================================
# CourseNotes
# ===========================================================================


@notes_router.get(
    "",
    response_model=CourseNoteListResponse,
    summary="List notes for a course",
)
async def list_notes(
    course_id: uuid.UUID = Query(..., description="Course UUID"),
    batch_id: Optional[uuid.UUID] = Query(default=None, description="Filter by batch (None = all batches)"),
    db: AsyncSession = Depends(get_db),
    pagination: PaginationParams = Depends(get_pagination),
    current_user: CurrentUser = Depends(get_current_user),
) -> CourseNoteListResponse:
    items = await study_svc.list_notes(
        db, course_id, batch_id=batch_id, skip=pagination.skip, limit=pagination.limit
    )
    return CourseNoteListResponse(
        items=[CourseNoteResponse.model_validate(n) for n in items],
        total=len(items),
        skip=pagination.skip,
        limit=pagination.limit,
    )


@notes_router.post(
    "",
    response_model=CourseNoteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload / create a course note",
)
async def create_note(
    payload: CourseNoteCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> CourseNoteResponse:
    note = await study_svc.create_note(db, payload)
    await db.commit()
    await db.refresh(note)
    return CourseNoteResponse.model_validate(note)


@notes_router.get(
    "/{note_id}",
    response_model=CourseNoteResponse,
    summary="Get a course note",
)
async def get_note(
    note_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> CourseNoteResponse:
    note = await study_svc.get_note_or_404(db, note_id)
    return CourseNoteResponse.model_validate(note)


@notes_router.patch(
    "/{note_id}",
    response_model=CourseNoteResponse,
    summary="Update a course note",
)
async def update_note(
    note_id: uuid.UUID,
    payload: CourseNoteUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> CourseNoteResponse:
    note = await study_svc.update_note(db, note_id, payload)
    await db.commit()
    await db.refresh(note)
    return CourseNoteResponse.model_validate(note)


@notes_router.delete(
    "/{note_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
    summary="Delete a course note",
)
async def delete_note(
    note_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> None:
    await study_svc.delete_note(db, note_id)
    await db.commit()
    return None


# ===========================================================================
# ExamPapers
# ===========================================================================


@papers_router.get(
    "",
    response_model=ExamPaperListResponse,
    summary="List past papers / question banks for a course",
)
async def list_papers(
    course_id: uuid.UUID = Query(..., description="Course UUID"),
    db: AsyncSession = Depends(get_db),
    pagination: PaginationParams = Depends(get_pagination),
    current_user: CurrentUser = Depends(get_current_user),
) -> ExamPaperListResponse:
    items = await study_svc.list_papers(
        db, course_id, skip=pagination.skip, limit=pagination.limit
    )
    return ExamPaperListResponse(
        items=[ExamPaperResponse.model_validate(p) for p in items],
        total=len(items),
        skip=pagination.skip,
        limit=pagination.limit,
    )


@papers_router.post(
    "",
    response_model=ExamPaperResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload / create an exam paper (past paper, model paper, or question bank)",
)
async def create_paper(
    payload: ExamPaperCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> ExamPaperResponse:
    paper = await study_svc.create_paper(db, payload)
    await db.commit()
    await db.refresh(paper)
    return ExamPaperResponse.model_validate(paper)


@papers_router.get(
    "/{paper_id}",
    response_model=ExamPaperResponse,
    summary="Get an exam paper",
)
async def get_paper(
    paper_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> ExamPaperResponse:
    paper = await study_svc.get_paper_or_404(db, paper_id)
    return ExamPaperResponse.model_validate(paper)


@papers_router.patch(
    "/{paper_id}",
    response_model=ExamPaperResponse,
    summary="Update an exam paper",
)
async def update_paper(
    paper_id: uuid.UUID,
    payload: ExamPaperUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> ExamPaperResponse:
    paper = await study_svc.update_paper(db, paper_id, payload)
    await db.commit()
    await db.refresh(paper)
    return ExamPaperResponse.model_validate(paper)


@papers_router.delete(
    "/{paper_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
    summary="Delete an exam paper",
)
async def delete_paper(
    paper_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> None:
    await study_svc.delete_paper(db, paper_id)
    await db.commit()
    return None


# ===========================================================================
# StudyGuides
# ===========================================================================


@guides_router.get(
    "",
    response_model=StudyGuideListResponse,
    summary="List study guide entries for a batch",
)
async def list_guides(
    batch_id: uuid.UUID = Query(..., description="Batch (SchedulingTarget) UUID"),
    course_id: Optional[uuid.UUID] = Query(default=None, description="Filter by course"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> StudyGuideListResponse:
    items = await study_svc.list_guides(db, batch_id, course_id=course_id)
    return StudyGuideListResponse(
        items=[StudyGuideResponse.model_validate(g) for g in items],
        total=len(items),
        skip=0,
        limit=len(items),
    )


@guides_router.post(
    "",
    response_model=StudyGuideResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Build a study guide entry — pin a note or paper to a batch/week",
)
async def build_guide(
    payload: StudyGuideCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> StudyGuideResponse:
    """
    Exactly one of ``note_id`` or ``exam_paper_id`` must be provided.
    Raises 422 if both or neither are set.
    """
    guide = await study_svc.build_guide(db, payload)
    await db.commit()
    await db.refresh(guide)
    return StudyGuideResponse.model_validate(guide)


@guides_router.get(
    "/{guide_id}",
    response_model=StudyGuideResponse,
    summary="Get a study guide entry",
)
async def get_guide(
    guide_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> StudyGuideResponse:
    guide = await study_svc.get_guide_or_404(db, guide_id)
    return StudyGuideResponse.model_validate(guide)


@guides_router.delete(
    "/{guide_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
    summary="Delete a study guide entry",
)
async def delete_guide(
    guide_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> None:
    await study_svc.delete_guide(db, guide_id)
    await db.commit()
    return None
