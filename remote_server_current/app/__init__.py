"""
app/
====
FastAPI application package for the Exovance Timetable Scheduler backend.

This package wires together all the sub-layers:
  - api/        → versioned route handlers (v1/)
  - core/       → app-wide settings, logger, exceptions, security
  - db/         → async SQLAlchemy engine, session factory, Alembic base
  - models/     → ORM table definitions (SQLAlchemy 2.0 declarative)
  - schemas/    → Pydantic V2 request/response DTOs
  - services/   → business-logic services consumed by route handlers

Entry point: app.main → creates the FastAPI instance via create_app().
"""
