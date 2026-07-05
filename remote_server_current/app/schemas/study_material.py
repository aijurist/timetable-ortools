"""
study_material.py
=================
Pydantic V2 schemas for the Study Material domain.

Three tables:
  course_notes    — per-subject notes / syllabus docs
  exam_papers     — past papers / question banks (study content, NOT scheduling)
  study_guides    — per-batch, week-by-week ordered content sequences
"""

import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.schemas.common import PaginatedResponse

ContentType = Literal["pdf", "doc", "link", "text"]
PaperType = Literal["past_paper", "model_paper", "question_bank"]


# ---------------------------------------------------------------------------
# CourseNote
# ---------------------------------------------------------------------------

class CourseNoteCreate(BaseModel):
    course_id: uuid.UUID
    batch_id: Optional[uuid.UUID] = Field(
        default=None,
        description="None means the note applies to ALL batches for the course.",
    )
    title: str = Field(min_length=1, max_length=255)
    content_type: ContentType
    content_url: Optional[str] = None
    content_text: Optional[str] = None
    semester: Optional[int] = Field(default=None, ge=1, le=12)
    uploaded_by: Optional[uuid.UUID] = None


class CourseNoteUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    content_url: Optional[str] = None
    content_text: Optional[str] = None
    semester: Optional[int] = Field(default=None, ge=1, le=12)


class CourseNoteResponse(BaseModel):
    id: uuid.UUID
    course_id: uuid.UUID
    batch_id: Optional[uuid.UUID]
    title: str
    content_type: str
    content_url: Optional[str]
    content_text: Optional[str]
    semester: Optional[int]
    uploaded_by: Optional[uuid.UUID]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


CourseNoteListResponse = PaginatedResponse[CourseNoteResponse]


# ---------------------------------------------------------------------------
# ExamPaper
# ---------------------------------------------------------------------------

class ExamPaperCreate(BaseModel):
    course_id: uuid.UUID
    title: str = Field(min_length=1, max_length=255)
    paper_type: PaperType
    year: Optional[int] = Field(default=None, ge=1990, le=2100)
    semester: Optional[int] = Field(default=None, ge=1, le=12)
    content_url: Optional[str] = None
    content_text: Optional[str] = None
    uploaded_by: Optional[uuid.UUID] = None


class ExamPaperUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    paper_type: Optional[PaperType] = None
    year: Optional[int] = Field(default=None, ge=1990, le=2100)
    semester: Optional[int] = Field(default=None, ge=1, le=12)
    content_url: Optional[str] = None
    content_text: Optional[str] = None


class ExamPaperResponse(BaseModel):
    id: uuid.UUID
    course_id: uuid.UUID
    title: str
    paper_type: str
    year: Optional[int]
    semester: Optional[int]
    content_url: Optional[str]
    content_text: Optional[str]
    uploaded_by: Optional[uuid.UUID]
    created_at: datetime

    model_config = {"from_attributes": True}


ExamPaperListResponse = PaginatedResponse[ExamPaperResponse]


# ---------------------------------------------------------------------------
# StudyGuide
# ---------------------------------------------------------------------------

class StudyGuideCreate(BaseModel):
    """
    Pin one piece of content (note OR paper, not both) to a batch/semester/week.
    """

    batch_id: uuid.UUID
    semester: int = Field(ge=1, le=12)
    week_number: int = Field(ge=1, le=52)
    note_id: Optional[uuid.UUID] = None
    exam_paper_id: Optional[uuid.UUID] = None
    description: Optional[str] = None


class StudyGuideUpdate(BaseModel):
    week_number: Optional[int] = Field(default=None, ge=1, le=52)
    note_id: Optional[uuid.UUID] = None
    exam_paper_id: Optional[uuid.UUID] = None
    description: Optional[str] = None


class StudyGuideResponse(BaseModel):
    id: uuid.UUID
    batch_id: uuid.UUID
    semester: int
    week_number: int
    note_id: Optional[uuid.UUID]
    exam_paper_id: Optional[uuid.UUID]
    description: Optional[str]

    model_config = {"from_attributes": True}


StudyGuideListResponse = PaginatedResponse[StudyGuideResponse]
