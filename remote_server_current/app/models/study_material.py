"""
app/models/study_material.py
=============================
Study Material module ORM models.

Tables
------
course_notes    — per-subject notes, syllabus docs uploaded by faculty/admin.
exam_papers     — past exam papers and question banks (study content, not scheduling).
study_guides    — per-batch, week-by-week ordered sequence of notes + papers.

All text content (content_text) is indexed for Campus Brain RAG ingestion via
PostgreSQL GIN full-text search indexes created in the Alembic migration.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class CourseNote(Base):
    """
    A single study document for a course — notes, syllabus, reference material.
    batch_id = None means the note applies to all batches for that course.
    """

    __tablename__ = "course_notes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # NULL = applies to all batches for this course
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(
        String(10), nullable=False
    )  # "pdf" | "doc" | "link" | "text"
    content_url: Mapped[str | None] = mapped_column(Text, nullable=True)   # S3 / Drive URL
    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)  # inline text for RAG
    semester: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Author — any user (faculty, admin, or HOD) can upload course notes.
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False
    )

    # Relationships
    study_guide_entries: Mapped[list["StudyGuide"]] = relationship(
        "StudyGuide", back_populates="note", foreign_keys="StudyGuide.note_id"
    )

    # GIN FTS index created in migration; listed here for documentation.
    __table_args__ = (
        Index(
            "idx_course_notes_fts",
            "content_text",
            postgresql_using="gin",
            postgresql_ops={"content_text": "gin_trgm_ops"},
        ),
    )

    def __repr__(self) -> str:
        return f"<CourseNote title={self.title!r} course={self.course_id}>"


class ExamPaper(Base):
    """
    Past exam paper or question bank entry — study content, not scheduling data.
    Separate from `exam_assignments` (solver output) in the exam module.
    """

    __tablename__ = "exam_papers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    paper_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # "past_paper" | "model_paper" | "question_bank"
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    semester: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_url: Mapped[str | None] = mapped_column(Text, nullable=True)   # S3 / Drive URL
    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)  # inline text for RAG

    # Author — any user (faculty, admin, or HOD) can upload exam papers.
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False
    )

    # Relationships
    study_guide_entries: Mapped[list["StudyGuide"]] = relationship(
        "StudyGuide", back_populates="exam_paper", foreign_keys="StudyGuide.exam_paper_id"
    )

    __table_args__ = (
        Index(
            "idx_exam_papers_fts",
            "content_text",
            postgresql_using="gin",
            postgresql_ops={"content_text": "gin_trgm_ops"},
        ),
    )

    def __repr__(self) -> str:
        return f"<ExamPaper title={self.title!r} type={self.paper_type} year={self.year}>"


class StudyGuide(Base):
    """
    Per-batch, week-by-week ordered collection of notes and exam papers.
    Each row pins one piece of content (note OR paper) to a week in a semester.
    """

    __tablename__ = "study_guides"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # references scheduling_targets.id (the batch this guide belongs to)
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scheduling_targets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    semester: Mapped[int] = mapped_column(Integer, nullable=False)
    week_number: Mapped[int] = mapped_column(Integer, nullable=False)

    note_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("course_notes.id"),
        nullable=True,
    )
    exam_paper_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("exam_papers.id"),
        nullable=True,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    note: Mapped["CourseNote | None"] = relationship(
        "CourseNote", back_populates="study_guide_entries", foreign_keys=[note_id]
    )
    exam_paper: Mapped["ExamPaper | None"] = relationship(
        "ExamPaper", back_populates="study_guide_entries", foreign_keys=[exam_paper_id]
    )

    __table_args__ = (
        UniqueConstraint("batch_id", "semester", "week_number", "note_id",
                         name="uq_study_guide_note"),
        UniqueConstraint("batch_id", "semester", "week_number", "exam_paper_id",
                         name="uq_study_guide_paper"),
    )

    def __repr__(self) -> str:
        return (
            f"<StudyGuide batch={self.batch_id} sem={self.semester} week={self.week_number}>"
        )
