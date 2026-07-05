"""
app/api/v1/routes/
==================
FastAPI APIRouter modules, one file per domain resource.

  auth.py            -> POST /auth/register|login|refresh, GET /auth/me
  users.py           -> GET/POST/PATCH /users  (admin user management)
  schedules.py       -> POST /schedules/generate, GET /schedules/{id}, etc.
  scenarios.py       -> Scenario management (create, clone, activate)
  constraints.py     -> CRUD for constraint_definitions and scenario_rules
  courses.py         -> Course catalogue CRUD
  rooms.py           -> Room catalogue CRUD
  faculty.py         -> Faculty profile CRUD + availability
  institution.py     -> Institution / Department / AcademicTerm CRUD
  curriculum.py      -> SchedulingTarget / OfferingBucket / CourseOffering
  exam.py            -> ExamScenario / ExamSlot / ExamAssignment CRUD
  reservations.py    -> Ad-hoc room reservations with conflict detection
  solver_job.py      -> SolverJob read + JobConflict list
  student.py         -> StudentProfile / StudentRegistration / StudentWishlist
  time_grids.py      -> TimeGrid CRUD + surgical slot patch
  study_materials.py -> CourseNote / ExamPaper / StudyGuide CRUD
  analytics.py       -> Analytics snapshots + materialized view queries
  agent.py           -> POST /agent/chat  natural-language constraint config
"""

from fastapi import APIRouter

from .agent import router as agent_router
from .department_plans import router as department_plans_router
from .group_distribution import router as group_distribution_router
from .selection import router as selection_router
from .selection_windows import router as selection_windows_router
from .selection_access_config import router as selection_access_config_router
from .audit_logs import router as audit_logs_router
from .notifications import router as notifications_router
from .allocation import router as allocation_router
from .allocation_rules import router as allocation_rules_router
from .feasibility import router as feasibility_router
from .analytics import router as analytics_router
from .auth import router as auth_router
from .constraints import router as constraints_router
from .courses import router as courses_router
from .curriculum import buckets_router, offerings_router, share_configs_router, targets_router
from .teaching_assignments import router as teaching_assignments_router
from .exam import router as exam_router
from .faculty import router as faculty_router
from .institution import departments_router, institutions_router, terms_router
from .reservations import router as reservations_router
from .rooms import router as rooms_router
from .scenarios import router as scenarios_router
from .schedules import router as schedules_router
from .solver_job import router as solver_job_router
from .elective_pools import router as elective_pools_router
from .student import router as student_router
from .study_materials import guides_router, notes_router, papers_router
from .time_grids import router as time_grids_router
from .users import router as users_router

v1_router = APIRouter()

# Auth & identity
v1_router.include_router(auth_router,          prefix="/auth",                   tags=["auth"])
v1_router.include_router(users_router,         prefix="/users",                  tags=["users"])

# Core scheduling resources
v1_router.include_router(schedules_router,     prefix="/schedules",              tags=["schedules"])
v1_router.include_router(scenarios_router,     prefix="/scenarios",              tags=["scenarios"])
v1_router.include_router(constraints_router,   prefix="/constraints",            tags=["constraints"])
v1_router.include_router(courses_router,       prefix="/courses",                tags=["courses"])
v1_router.include_router(rooms_router,         prefix="/rooms",                  tags=["rooms"])
v1_router.include_router(faculty_router,       prefix="/faculty",                tags=["faculty"])

# Infrastructure layer
v1_router.include_router(institutions_router,  prefix="/institutions",           tags=["institutions"])
v1_router.include_router(departments_router,   prefix="/departments",            tags=["institutions"])
v1_router.include_router(terms_router,         prefix="/terms",                  tags=["institutions"])
v1_router.include_router(time_grids_router,    prefix="/time-grids",             tags=["time-grids"])

# Curriculum / demand layer & FFCS
v1_router.include_router(targets_router,              prefix="/scheduling-targets",     tags=["curriculum"])
v1_router.include_router(buckets_router,              prefix="/offering-buckets",       tags=["curriculum"])
v1_router.include_router(offerings_router,            prefix="/course-offerings",       tags=["curriculum"])
v1_router.include_router(teaching_assignments_router, prefix="/teaching-assignments",   tags=["curriculum"])
v1_router.include_router(share_configs_router,        prefix="/course-share-configs",   tags=["curriculum"])

# Exam scheduling
v1_router.include_router(exam_router,          prefix="/exam-scenarios",         tags=["exam"])

# Reservations
v1_router.include_router(reservations_router,  prefix="/reservations",           tags=["reservations"])

# Solver audit
v1_router.include_router(solver_job_router,    prefix="/solver-jobs",            tags=["solver-jobs"])

# Students & FFCS
v1_router.include_router(student_router,       prefix="/students",               tags=["students"])

# Elective pools (PE / OE planning)
v1_router.include_router(elective_pools_router, prefix="",                       tags=["elective-pools"])

# Study materials (Campus Brain)
v1_router.include_router(notes_router,         prefix="/study-materials/notes",  tags=["study-materials"])
v1_router.include_router(papers_router,        prefix="/study-materials/papers", tags=["study-materials"])
v1_router.include_router(guides_router,        prefix="/study-materials/guides", tags=["study-materials"])

# Analytics & reporting
v1_router.include_router(analytics_router,     prefix="/analytics",              tags=["analytics"])

# Agent
v1_router.include_router(agent_router,         prefix="/agent",                  tags=["agent"])

# Pre-solve allocation
v1_router.include_router(allocation_router,    prefix="",                        tags=["allocation"])

# Allocation rules (per-scenario toggles)
v1_router.include_router(allocation_rules_router, prefix="",                     tags=["allocation-rules"])

# Feasibility check
v1_router.include_router(feasibility_router,   prefix="",                        tags=["feasibility"])

# Audit log (admin only)
v1_router.include_router(audit_logs_router,    prefix="/audit-logs",             tags=["audit-logs"])

# Notifications (all authenticated users)
v1_router.include_router(notifications_router, prefix="/notifications",          tags=["notifications"])

# Department plan publish/approve workflow
v1_router.include_router(department_plans_router, prefix="",                     tags=["department-plans"])

# Group distribution (HYBRID/FFCS pre-solve)
v1_router.include_router(group_distribution_router, prefix="",                   tags=["group-distribution"])

# HYBRID student selection
v1_router.include_router(selection_router,       prefix="/selection",            tags=["selection"])
v1_router.include_router(selection_windows_router, prefix="/selection-windows",  tags=["selection-windows"])
v1_router.include_router(selection_access_config_router, prefix="/selection-windows", tags=["selection-windows"])
