"""
app/services/
=============
Business-logic layer between route handlers and the solver / agent / DB.

All service functions:
  - Are ``async`` and accept ``AsyncSession`` as first argument.
  - Call ``db.flush()`` (not ``db.commit()``) — commit is the caller's responsibility.
  - Raise domain exceptions from ``app.core.exceptions`` (never raw HTTPException).

Modules
-------
  user_service        — ``get_by_email``, ``get_or_404``, ``create``, ``update``,
                        ``hash_password``, ``verify_password``
  auth_service        — ``register``, ``login``, ``refresh``,
                        ``create_access_token``, ``decode_token``
  scenario_service    — ``list_by_institution``, ``get_or_404``, ``create``,
                        ``update``, ``mark_dirty``, ``clone``
  course_service      — ``list_by_institution``, ``get_or_404``, ``create``,
                        ``update``, ``soft_delete``
  room_service        — ``list_by_institution``, ``get_or_404``, ``create``,
                        ``update``, ``soft_delete``
  faculty_service     — ``list_by_institution``, ``get_or_404``, ``create``,
                        ``update``, ``update_availability``, ``soft_delete``
  constraint_service  — ``list_definitions``, ``search_definitions``,
                        ``list_rules``, ``add_rule``, ``toggle_rule``,
                        ``delete_rule``
  schedule_service    — ``get_by_scenario``, ``clear_and_persist``, ``clear``
  time_grid_service   — ``get_by_term``, ``get_or_404``, ``create``, ``update``,
                        ``patch_slots``, ``delete``
  exam_service        — ``create_scenario``, ``update_scenario``,
                        ``add_slot``, ``list_slots``, ``update_slot``,
                        ``get_assignments``, ``clear_assignments``
  study_material_service  — ``list_notes``, ``create_note``, ``update_note``,
                            ``delete_note``, ``list_papers``, ``create_paper``,
                            ``update_paper``, ``delete_paper``, ``build_guide``,
                            ``list_guides``
  reservation_service — ``create``, ``approve``, ``reject``, ``cancel``,
                        ``check_conflicts``, ``list_by_institution``
  analytics_service   — ``get_latest_snapshot``, ``list_snapshots``,
                        ``get_workload_metrics``, ``get_room_utilization``,
                        ``trigger_snapshot_task``
  institution_service — ``create_institution``, ``list_institutions``,
                        ``create_department``, ``list_departments``,
                        ``create_term``, ``list_terms``, ``set_term_status``
  curriculum_service  — ``list_targets``, ``create_target``,
                        ``list_buckets``, ``create_bucket``,
                        ``list_offerings``, ``create_offering``,
                        ``book_seat``, ``release_seat``,
                        ``add_requirement``, ``remove_requirement``
  solver_job_service  — ``create_job``, ``mark_complete``,
                        ``list_jobs``, ``get_latest_job``,
                        ``list_conflicts``, ``create_conflict``,
                        ``bulk_create_conflicts``
  student_service     — ``create_profile``, ``update_profile``,
                        ``register_offering``, ``drop_registration``,
                        ``create_wishlist``, ``update_wishlist``
"""

from app.services import (
    analytics_service,
    auth_service,
    constraint_service,
    course_service,
    curriculum_service,
    exam_service,
    faculty_service,
    institution_service,
    reservation_service,
    room_service,
    scenario_service,
    schedule_service,
    solver_job_service,
    student_service,
    study_material_service,
    time_grid_service,
    user_service,
)

__all__ = [
    "user_service",
    "auth_service",
    "institution_service",
    "scenario_service",
    "course_service",
    "room_service",
    "faculty_service",
    "constraint_service",
    "schedule_service",
    "time_grid_service",
    "exam_service",
    "curriculum_service",
    "solver_job_service",
    "student_service",
    "study_material_service",
    "reservation_service",
    "analytics_service",
]
