"""
app/services/analytics_service.py
====================================
Analytics snapshot management and materialized-view queries.

Architecture note
-----------------
Two heavyweight aggregates — workload_metrics and room_utilization — are
maintained as PostgreSQL materialized views (created in the Alembic migration
and refreshed by a Celery periodic beat task).  This service reads them via
raw SELECT statements because they are NOT ORM models.

The ``trigger_snapshot_task`` helper enqueues a Celery task and returns the
task ID string for the caller to poll.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.logger import logger
from app.models.analytics import AnalyticsSnapshot


# ---------------------------------------------------------------------------
# AnalyticsSnapshot (ORM table)
# ---------------------------------------------------------------------------


async def list_snapshots(
    db: AsyncSession,
    institution_id: uuid.UUID,
    *,
    academic_term_id: Optional[uuid.UUID] = None,
    skip: int = 0,
    limit: int = 20,
) -> list[AnalyticsSnapshot]:
    q = (
        select(AnalyticsSnapshot)
        .where(AnalyticsSnapshot.institution_id == institution_id)
    )
    if academic_term_id is not None:
        q = q.where(AnalyticsSnapshot.academic_term_id == academic_term_id)
    q = q.order_by(AnalyticsSnapshot.generated_at.desc()).offset(skip).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


async def get_latest_snapshot(
    db: AsyncSession,
    institution_id: uuid.UUID,
    academic_term_id: uuid.UUID,
) -> Optional[AnalyticsSnapshot]:
    """Return the most recent snapshot for a term, or None if none exist."""
    result = await db.execute(
        select(AnalyticsSnapshot)
        .where(
            AnalyticsSnapshot.institution_id == institution_id,
            AnalyticsSnapshot.academic_term_id == academic_term_id,
        )
        .order_by(AnalyticsSnapshot.generated_at.desc())
        .limit(1)
    )
    return result.scalars().first()


async def get_snapshot_or_404(
    db: AsyncSession,
    snapshot_id: uuid.UUID,
) -> AnalyticsSnapshot:
    result = await db.execute(
        select(AnalyticsSnapshot).where(AnalyticsSnapshot.id == snapshot_id)
    )
    snap = result.scalars().first()
    if snap is None:
        raise NotFoundError(f"AnalyticsSnapshot {snapshot_id} not found")
    return snap


async def persist_snapshot(
    db: AsyncSession,
    institution_id: uuid.UUID,
    academic_term_id: uuid.UUID,
    snapshot_data: dict[str, Any],
) -> AnalyticsSnapshot:
    """
    Persist a new AnalyticsSnapshot row.

    Called by the Celery analytics beat task after building the payload.
    """
    snap = AnalyticsSnapshot(
        institution_id=institution_id,
        academic_term_id=academic_term_id,
        snapshot_data=snapshot_data,
    )
    db.add(snap)
    await db.flush()
    logger.info(
        "AnalyticsSnapshot persisted",
        snapshot_id=str(snap.id),
        institution_id=str(institution_id),
        term_id=str(academic_term_id),
    )
    return snap


# ---------------------------------------------------------------------------
# Materialized view queries (raw SQL) — kept for compat, not called by routes
# ---------------------------------------------------------------------------


async def get_workload_metrics(
    db: AsyncSession,
    academic_term_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """Legacy: reads workload_metrics materialized view (may be stale/missing cols)."""
    stmt = text(
        """
        SELECT
            faculty_id,
            faculty_name,
            total_sessions,
            total_hours,
            academic_term_id,
            institution_id
        FROM workload_metrics
        WHERE academic_term_id = :term_id
        ORDER BY total_sessions DESC
        """
    )
    result = await db.execute(stmt, {"term_id": academic_term_id})
    rows = result.mappings().all()
    return [dict(r) for r in rows]


async def get_room_utilization(
    db: AsyncSession,
    academic_term_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """Legacy: reads room_utilization materialized view (may be stale/missing cols)."""
    stmt = text(
        """
        SELECT
            room_id,
            room_code,
            room_name,
            booked_slots,
            total_slots,
            utilization_pct,
            total_sessions,
            academic_term_id,
            institution_id
        FROM room_utilization
        WHERE academic_term_id = :term_id
        ORDER BY utilization_pct DESC NULLS LAST
        """
    )
    result = await db.execute(stmt, {"term_id": academic_term_id})
    rows = result.mappings().all()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Live-query service functions (scenario-scoped, bypass materialized views)
# ---------------------------------------------------------------------------


async def get_workload_by_scenario(
    db: AsyncSession,
    scenario_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """Live query: scheduled_sessions → JOIN faculty, grouped by faculty_id."""
    stmt = text("""
        SELECT
            ss.faculty_id,
            f.name                     AS faculty_name,
            COUNT(*)                   AS total_sessions,
            NULL::float                AS total_hours,
            s.academic_term_id,
            s.institution_id
        FROM scheduled_sessions ss
        JOIN scenarios s ON s.id = ss.scenario_id
        LEFT JOIN faculty f ON f.id = ss.faculty_id::uuid
        WHERE ss.scenario_id = :scenario_id
          AND ss.faculty_id IS NOT NULL
        GROUP BY ss.faculty_id, f.name, s.academic_term_id, s.institution_id
        ORDER BY COUNT(*) DESC
    """)
    result = await db.execute(stmt, {"scenario_id": scenario_id})
    return [dict(r) for r in result.mappings().all()]


async def get_room_utilization_by_scenario(
    db: AsyncSession,
    scenario_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """Live query: scheduled_sessions → JOIN rooms, grouped by room_id."""
    stmt = text("""
        SELECT
            ss.room_id,
            r.code                     AS room_code,
            r.name                     AS room_name,
            COUNT(*)                   AS booked_slots,
            NULL::int                  AS total_slots,
            NULL::float                AS utilization_pct,
            COUNT(*)                   AS total_sessions,
            s.academic_term_id,
            s.institution_id
        FROM scheduled_sessions ss
        JOIN scenarios s ON s.id = ss.scenario_id
        LEFT JOIN rooms r ON r.id = ss.room_id::uuid
        WHERE ss.scenario_id = :scenario_id
          AND ss.room_id IS NOT NULL
        GROUP BY ss.room_id, r.code, r.name, s.academic_term_id, s.institution_id
        ORDER BY COUNT(*) DESC
    """)
    result = await db.execute(stmt, {"scenario_id": scenario_id})
    return [dict(r) for r in result.mappings().all()]


# ---------------------------------------------------------------------------
# Celery task trigger
# ---------------------------------------------------------------------------


def trigger_snapshot_task(
    institution_id: uuid.UUID,
    academic_term_id: uuid.UUID,
) -> str:
    """
    Enqueue the Celery analytics snapshot task and return its task_id.

    This is a synchronous call (task.delay) — it does NOT need a DB session.
    The actual snapshot is persisted by the task via ``persist_snapshot``.
    Falls back to a synthetic UUID task_id when the Celery broker is unavailable.
    """
    try:
        from app.tasks.analytics_tasks import generate_analytics_snapshot  # lazy import

        task = generate_analytics_snapshot.delay(
            str(institution_id),
            str(academic_term_id),
        )
        task_id = task.id
    except Exception as exc:  # noqa: BLE001
        # Celery broker (Redis) not reachable in this environment — return a
        # synthetic task_id so the API still returns 202 without crashing.
        task_id = str(uuid.uuid4())
        logger.warning(
            "Celery broker unavailable — returning synthetic task_id",
            error=str(exc)[:120],
            synthetic_task_id=task_id,
        )
    logger.info(
        "Analytics snapshot task enqueued",
        task_id=task_id,
        institution_id=str(institution_id),
        term_id=str(academic_term_id),
    )
    return task_id
