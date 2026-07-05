"""
Shared Celery application instance.

Import this module wherever you need to enqueue tasks or inspect results:

    from app.core.celery_app import celery_app

    task = celery_app.send_task("app.tasks.solver_tasks.run_solver", kwargs={...})
    result = AsyncResult(task.id, app=celery_app)
"""
from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "exovance_scheduler",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["tasks.schedule_tasks", "tasks.notification_tasks", "tasks.selection_window_tasks"],
)

celery_app.conf.beat_schedule = {
    "check-selection-windows-every-minute": {
        "task": "tasks.selection_window_tasks.check_selection_windows",
        "schedule": 60.0,
    },
}

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Task routing — solver tasks run on a dedicated queue.
    # Module path is "tasks.schedule_tasks.*" (no "app." prefix).
    task_routes={
        "tasks.schedule_tasks.*": {"queue": "solver"},
        "app.tasks.analytics_tasks.*": {"queue": "analytics"},
        "tasks.notification_tasks.*": {"queue": "notifications"},
        "tasks.selection_window_tasks.*": {"queue": "notifications"},
    },
    # Allow storing full exception tracebacks in the result backend
    task_track_started=True,
    result_extended=True,
    # Pool and concurrency are set at worker launch time via CLI flags or
    # environment variables (CELERYD_POOL / CELERYD_CONCURRENCY), not here.
    # On Windows dev, run: celery worker --pool=solo
    # On Linux production, run: celery worker --pool=prefork --concurrency=8
)
