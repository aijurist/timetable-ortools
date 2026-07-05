"""
app/models/selection_access_config.py
======================================
Per-institution / per-term student access configuration.

  allowed_login_years       — which study years can log in to the portal.
  allowed_booking_years     — which study years can register/book courses.
                              (independent from login years)
  allowed_login_departments — which department's students can log in.
  allowed_booking_departments — which department's students can book courses.
  early_access_emails       — specific student emails that bypass ALL gates above.
                              These students can always log in and register.
  group_seat_overrides      — per-department max students per group.
  default_max_group_size    — global fallback cap.
  notes                     — internal admin memo.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SelectionAccessConfig(Base):
    __tablename__ = "selection_access_configs"
    __table_args__ = (
        UniqueConstraint(
            "institution_id",
            "academic_term_id",
            name="uq_access_config_inst_term",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    institution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    academic_term_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )

    # --- Login gate ---
    # Study years (1-8) allowed to log in. Empty = all years.
    allowed_login_years: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    # Department UUIDs whose students can log in. Empty = all departments.
    allowed_login_departments: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    # --- Booking gate (independent from login) ---
    # Study years (1-8) allowed to register courses. Empty = all years.
    allowed_booking_years: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    # Department UUIDs whose students can book courses. Empty = all.
    allowed_booking_departments: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    # --- Early access bypass list ---
    # Specific student emails (e.g. 230701094@college.edu) that bypass
    # ALL login/booking year and department restrictions.
    early_access_emails: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    # --- Group seat limits ---
    # Per-department overrides: [{"department_id": "<uuid>", "max_seats": 30}, ...]
    group_seat_overrides: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    # Global fallback (null = no global cap).
    default_max_group_size: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )

    # Internal admin memo — never shown to students.
    notes: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
