"""
app/api/v1/
===========
Version 1 of the public REST API.

  routes/    → Individual APIRouter modules, one per domain.
  deps.py    → FastAPI dependency functions shared across all v1 routes
               (e.g. get_db, get_current_user, get_celery_task_status).

All routers in routes/ are registered into a single `v1_router` (defined in
routes/__init__.py) and mounted at /api/v1 by app.main.
"""
