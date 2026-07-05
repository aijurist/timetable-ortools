from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """
    Shared declarative base for all ORM models.

    Import all model modules here so Alembic autogenerate can
    discover every table when `env.py` imports this module.
    """
    pass


# Import all models so Alembic sees them — add each as it is created.
from app.models import (  # noqa: E402, F401
    scenario,
    schedule,
    constraint,
    course,
    room,
    faculty,
    time_grid,
    # New module models
    exam,
    reservation,
    analytics,
    study_material,
    # Agent conversation context
    agent,
    # User identity & roles
    user,
    # Infrastructure: institutions, departments, academic_terms
    institution,
    # Curriculum: scheduling_targets, offering_buckets, course_offerings, target_requirements
    curriculum,
    # Solver audit: solver_jobs, job_conflicts
    solver_job,
    # Student profiles, FFCS registrations, wishlists
    student,
)
