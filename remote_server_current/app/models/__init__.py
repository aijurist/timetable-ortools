"""
app/models/
===========
SQLAlchemy 2.0 async ORM table definitions (mapped dataclasses / DeclarativeBase).

Files map directly to DB schema tables:

  scenario.py      → `scenarios` table — central control record per scheduling run.
                     Key columns:
                       status           Enum: DRAFT|PENDING|RUNNING|COMPLETED
                                              |INFEASIBLE|FAILED|STALE
                       solver_config    JSONB  ← per-scenario SolverConfig overrides
                                               (timeout_seconds, strategy, num_workers)
                       celery_task_id   str|None  ← live task id for revoke/pause
                       best_hint        JSONB  ← warm-start snapshot from last solve
                       is_dirty         bool   ← True when rules/data changed since
                                               last COMPLETED solve; triggers re-solve

  schedule.py      → `schedules` table — generated session-slot assignments (output).

  constraint.py    → `constraint_definitions` table (registry / AI instruction manual)
                       code, tier, param_schema JSONB, keywords[], agent_guide
                     `scenario_rules` table (active constraints per scenario)
                       scenario_id FK, definition_code FK|None, tier,
                       params JSONB, script_trigger, script_logic,
                       is_enabled bool  ← toggle WITHOUT deleting the row

  course.py        → `courses` table — course catalogue.
  room.py          → `rooms` table — room catalogue with capacity.
  faculty.py       → `faculty` table — instructor profiles.
                       user_id      UUID FK → users.id (one-to-one bridge: Faculty ← User)
  time_grid.py     → `time_grids` table — slot dictionary JSON (e.g. A1 = Mon 9-10).

  exam.py          → Exam Scheduling module (3 tables):
                       `exam_scenarios`   — one per exam period; separate CP-SAT solver run.
                       `exam_slots`       — date + time windows within a scenario.
                       `exam_assignments` — solver output: course × slot × room × batch.

  reservation.py   → Ad-hoc Resource Reservation module (1 table):
                       `reservations`     — room booking requests outside the timetable.
                       Conflict detection done at API layer (no solver).

  analytics.py     → Reporting & Analytics module (1 table + 2 materialized views in migration):
                       `analytics_snapshots`  — point-in-time export payload.
                       `workload_metrics`     — materialized view: faculty credit-hour load.
                       `room_utilization`     — materialized view: room booking density.

  study_material.py → Study Material module (3 tables):
                       `course_notes`     — per-subject notes/docs; indexed for RAG.
                       `exam_papers`      — past papers & question banks; indexed for RAG.
                       `study_guides`     — per-batch week-by-week ordered content sequence.

  agent.py         → Agent Conversation Context module (2 tables):
                       `agent_sessions`  — one conversation thread per user × scenario.
                                          Tracks status, token_total, retry_count, and
                                          last_solver_status for self-correction logic.
                       `agent_messages`  — individual messages within a thread.
                          role            Enum: human|ai|tool|system
                          content         Text  ← human-readable body
                          tool_call_id    str|None  ← pairs AI tool-call with TOOL reply
                          tool_name       str|None  ← which tool was invoked
                          raw_payload     JSONB  ← full LangChain BaseMessage.dict() for
                                                   lossless AgentState reconstruction
                          prompt_tokens / completion_tokens / latency_ms  ← cost tracking

  user.py          → User Identity & RBAC module (1 table):
                       `users`           — one row per registered platform user.
                         role             Enum: student|teacher|hod|admin|super_admin
                         institution_id   UUID nullable (null = SUPER_ADMIN cross-tenant)
                         department       str nullable (dept code, e.g. "CSE")
                         hashed_password  bcrypt hash — never exposed in API responses
                          is_active / is_verified / last_login_at / avatar_url

                     Role hierarchy (enforced at service + deps layer):
                       SUPER_ADMIN  Exovance staff — cross-institution
                       ADMIN        Institution registrar — full CRUD for their org
                       HOD          Head of Dept — manage constraints for their dept
                       TEACHER      Linked to a Faculty row — can edit availability
                       STUDENT      Read-only — view published timetables

                     Auth layer:
                       deps.py returns CurrentUser dataclass (typed, not raw dict).
                       JWT claims: { sub, role, institution_id, dept }
                       Guards: require_admin(), require_hod(), require_role(*roles)

  institution.py   → Infrastructure tier (3 tables):
                       `institutions`    — multi-tenant root; carries scheduling_mode.
                       `departments`     — sub-units (CSE, ECE) with dept code for JWT.
                       `academic_terms`  — semester periods with start/end dates + status.
                     All other resource tables reference institution_id / academic_term_id
                     as *loose UUIDs* (no FK) for cross-service decoupling. These tables
                     are the authoritative source for those UUIDs.

  curriculum.py    → Curriculum & demand tier (4 tables):
                       `scheduling_targets`   — batches / clusters who need a timetable.
                       `offering_buckets`     — named container of offerings; carries
                                               min/max_selection + force_parallel_slots.
                       `course_offerings`     — one faculty×course combo; solver writes
                                               slot_code + room_id here.
                       `target_requirements`  — many-to-many: target must satisfy bucket.

  solver_job.py    → Solver audit trail (2 tables):
                       `solver_jobs`    — immutable per-run snapshot (constraints +
                                         config + result); supports rollback & diff.
                       `job_conflicts`  — per-constraint INFEASIBLE records; read by
                                         Agent self-correction loop.

  student.py       → Student academic profile & FFCS registration (3 tables):
                       `student_profiles`       — 1-to-1 extension of users for STUDENT role.
                                                  Carries enrollment_number, program, semester,
                                                  batch_id FK→scheduling_targets (drive RAG +
                                                  NoGroupOverlap constraint lookup).
                       `student_registrations`  — confirmed FFCS offering registrations;
                                                  seat deducted on write.
                       `student_wishlists`      — pre-registration shopping cart (draft;
                                                  no seat lock; JSON offering_ids array).

  audit_log.py    → Audit & Compliance module (1 table):
                       `audit_log`       — immutable event ledger; one row per
                                           significant state change across all domains.
                         actor_user_id   UUID nullable (system/Celery actions have no actor)
                         action          Enum: CREATED|UPDATED|DELETED|PUBLISHED|…
                         entity_type/id  which object was affected
                         before/after    JSONB state snapshots for UPDATED events
                         No UPDATE or DELETE endpoints — append-only.

  notification.py → Notification module (2 tables):
                       `notifications`            — one row per delivered alert.
                         channel                  Enum: IN_APP|EMAIL|PUSH
                         is_read / read_at         user read-state
                       `notification_preferences` — per-user channel opt-in/out.
                         email_enabled / push_enabled  defaults True/False
                         disabled_types            JSONB list of muted NotificationType values

All models inherit from `app.db.base.Base`.
Never import business logic here; keep models pure data definitions.

  department_plan.py → Plan submit/approve workflow (1 table):
                       `department_plans` — one row per (term × department).
                         status           Enum: DRAFT|HOD_PUBLISHED|ADMIN_APPROVED
                         submitted_at / approved_at / sent_back_at — lifecycle timestamps
                         sent_back_reason — optional admin feedback on rejection
"""

# Import to ensure Alembic autogenerate picks up the model.
from app.models.department_plan import DepartmentPlan as DepartmentPlan  # noqa: F401
from app.models.selection import (  # noqa: F401
    DepartmentSelectionWindow as DepartmentSelectionWindow,
    StudentCourseEligibility as StudentCourseEligibility,
    StudentGroupSelection as StudentGroupSelection,
)
from app.models.selection_access_config import (  # noqa: F401
    SelectionAccessConfig as SelectionAccessConfig,
)