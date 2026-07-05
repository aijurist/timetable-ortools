"""
app/tasks/analytics_tasks.py
============================
Celery task for analytics snapshot generation.

The task is fire-and-forget: it reads scheduled sessions and produces
an AnalyticsSnapshot row via analytics_svc.persist_snapshot.
"""
from __future__ import annotations

import asyncio
import uuid

from app.core.celery_app import celery_app
from app.core.logger import logger


@celery_app.task(name="app.tasks.analytics_tasks.generate_analytics_snapshot", bind=True)
def generate_analytics_snapshot(
    self,
    institution_id: str,
    academic_term_id: str,
) -> dict:
    """
    Generate and persist an analytics snapshot for the given institution + term.

    Args:
        institution_id: UUID string of the institution.
        academic_term_id: UUID string of the academic term.

    Returns:
        dict with snapshot_id and status.
    """
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

    from app.core.config import settings
    from app.services import analytics_service as analytics_svc

    logger.info(
        "Analytics snapshot task started",
        task_id=self.request.id,
        institution_id=institution_id,
        term_id=academic_term_id,
    )

    engine = create_async_engine(settings.DATABASE_URL)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

    async def _run() -> str:
        snapshot_data: dict = {
            "institution_id": institution_id,
            "academic_term_id": academic_term_id,
            "generated_by": "celery_task",
            "note": "Snapshot generation via Celery worker.",
        }
        async with session_factory() as db:
            snap = await analytics_svc.persist_snapshot(
                db,
                uuid.UUID(institution_id),
                uuid.UUID(academic_term_id),
                snapshot_data,
            )
            await db.commit()
            return str(snap.id)

    snapshot_id = asyncio.run(_run())
    logger.info(
        "Analytics snapshot task completed",
        task_id=self.request.id,
        snapshot_id=snapshot_id,
    )
    return {"snapshot_id": snapshot_id, "status": "completed"}
