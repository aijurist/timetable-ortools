"""
app/services/scenario_service.py
=================================
CRUD and lifecycle operations for timetable Scenarios.

Responsibilities
----------------
* List / retrieve scenarios scoped to an institution.
* Create, update, soft-delete scenarios.
* ``mark_dirty`` — set is_dirty=True after a data change so the frontend shows
  "⚠ Changes pending — re-run to apply".
* ``clone`` — deep-copy a scenario and its rules to a new DRAFT.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
import uuid
from typing import Any, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from fastapi import HTTPException, status

from app.core.exceptions import NotFoundError
from app.core.logger import logger
from app.models.constraint import ScenarioRule
from app.models.curriculum import CourseOffering, OfferingBucket, SchedulingTarget, TargetRequirement
from app.models.scenario import Scenario, ScenarioStatus
from app.models.schedule import ScheduledSession
from app.models.solver_job import SolverJobStatus
from app.models.time_grid import TimeGrid
from app.schemas.scenario import ScenarioCreate, ScenarioUpdate


_RESTORABLE_JOB_STATUSES: tuple[SolverJobStatus, ...] = (
    SolverJobStatus.OPTIMAL,
    SolverJobStatus.FEASIBLE,
)


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


async def list_by_institution(
    db: AsyncSession,
    institution_id: uuid.UUID,
    *,
    skip: int = 0,
    limit: int = 50,
) -> list[Scenario]:
    """Return paginated scenarios for *institution_id*, newest first."""
    q = (
        select(Scenario)
        .where(
            Scenario.institution_id == institution_id,
            Scenario.deleted_at.is_(None),
        )
        .order_by(Scenario.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(q)
    return list(result.scalars().all())


async def count_by_institution(
    db: AsyncSession,
    institution_id: uuid.UUID,
) -> int:
    q = select(func.count()).select_from(Scenario).where(
        Scenario.institution_id == institution_id,
        Scenario.deleted_at.is_(None),
    )
    result = await db.execute(q)
    return result.scalar_one()


async def get_by_id(db: AsyncSession, scenario_id: uuid.UUID) -> Optional[Scenario]:
    result = await db.execute(
        select(Scenario).where(
            Scenario.id == scenario_id,
            Scenario.deleted_at.is_(None),
        )
    )
    return result.scalars().first()


async def get_or_404(db: AsyncSession, scenario_id: uuid.UUID) -> Scenario:
    scenario = await get_by_id(db, scenario_id)
    if scenario is None:
        raise NotFoundError(f"Scenario {scenario_id} not found")
    return scenario


async def get_with_rules(db: AsyncSession, scenario_id: uuid.UUID) -> Scenario:
    """Load a scenario with its rules (eager-loaded) or raise 404."""
    result = await db.execute(
        select(Scenario)
        .where(Scenario.id == scenario_id, Scenario.deleted_at.is_(None))
        .options(selectinload(Scenario.rules))
    )
    scenario = result.scalars().first()
    if scenario is None:
        raise NotFoundError(f"Scenario {scenario_id} not found")
    return scenario


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


async def create(
    db: AsyncSession,
    institution_id: uuid.UUID,
    payload: ScenarioCreate,
    *,
    actor_user_id: uuid.UUID | None = None,
    actor_role: str | None = None,
) -> Scenario:
    if payload.selected_time_grid_id is not None:
        grid_result = await db.execute(
            select(TimeGrid).where(TimeGrid.id == payload.selected_time_grid_id)
        )
        selected_grid = grid_result.scalar_one_or_none()
        if selected_grid is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="selected_time_grid_id does not exist",
            )
        if selected_grid.academic_term_id != payload.academic_term_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="selected_time_grid_id must belong to scenario academic_term_id",
            )

    scenario = Scenario(
        institution_id=institution_id,
        academic_term_id=payload.academic_term_id,
        selected_time_grid_id=payload.selected_time_grid_id,
        name=payload.name,
        solver_config=payload.solver_config,
        scheduling_mode=payload.scheduling_mode,
        status=ScenarioStatus.DRAFT,
        is_dirty=True,
    )
    db.add(scenario)
    await db.flush()
    logger.info("Scenario created", scenario_id=str(scenario.id), name=scenario.name)

    # Seed default distribution rule based on scheduling mode
    from app.models.constraint import RuleType  # noqa: PLC0415
    from app.services.distribution import MODE_DEFAULT_DIST  # noqa: PLC0415
    _sched_mode = payload.scheduling_mode
    mode_name = _sched_mode.value if _sched_mode is not None else "TRADITIONAL"
    dist_code = MODE_DEFAULT_DIST.get(mode_name, "TRADITIONAL_DIST")
    db.add(ScenarioRule(
        scenario_id=scenario.id,
        definition_code=dist_code,
        tier=2,
        rule_type=RuleType.DISTRIBUTION,
        params={},
        is_hard_constraint=True,
        is_enabled=True,
    ))
    # Auto-seed MAX_ROOM_SIZE: soft Tier 3, size_factor=2.0
    # Prevents assigning a 60-student class to a 500-seat hall.
    # Coordinators can tighten or disable via Settings → Rules.
    db.add(ScenarioRule(
        scenario_id=scenario.id,
        definition_code="MAX_ROOM_SIZE",
        tier=3,
        rule_type=RuleType.CONSTRAINT,
        params={"size_factor": 2.0},
        is_hard_constraint=False,
        is_enabled=True,
    ))
    await db.flush()

    from app.services import audit_log_service  # noqa: PLC0415
    from app.models.audit_log import AuditAction  # noqa: PLC0415
    await audit_log_service.record(
        db,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action=AuditAction.CREATED,
        entity_type="Scenario",
        entity_id=scenario.id,
        entity_label=scenario.name,
        institution_id=institution_id,
    )
    return scenario


async def update(
    db: AsyncSession,
    scenario_id: uuid.UUID,
    payload: ScenarioUpdate,
    *,
    actor_user_id: uuid.UUID | None = None,
    actor_role: str | None = None,
) -> Scenario:
    scenario = await get_or_404(db, scenario_id)
    changes = payload.model_dump(exclude_unset=True)

    if "selected_time_grid_id" in changes:
        selected_grid_id = changes["selected_time_grid_id"]
        if selected_grid_id is not None:
            grid_result = await db.execute(
                select(TimeGrid).where(TimeGrid.id == selected_grid_id)
            )
            selected_grid = grid_result.scalar_one_or_none()
            if selected_grid is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="selected_time_grid_id does not exist",
                )
            if selected_grid.academic_term_id != scenario.academic_term_id:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="selected_time_grid_id must belong to scenario academic_term_id",
                )

    for field, value in changes.items():
        setattr(scenario, field, value)
    if any(field != "auto_publish_latest" for field in changes):
        scenario.is_dirty = True
    await db.flush()
    logger.info("Scenario updated", scenario_id=str(scenario_id))

    from app.services import audit_log_service  # noqa: PLC0415
    from app.models.audit_log import AuditAction  # noqa: PLC0415
    await audit_log_service.record(
        db,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action=AuditAction.UPDATED,
        entity_type="Scenario",
        entity_id=scenario_id,
        entity_label=scenario.name,
        institution_id=scenario.institution_id,
        after={k: str(v) if not isinstance(v, (str, int, float, bool, type(None))) else v for k, v in changes.items()},
    )
    return scenario


async def publish_job(
    db: AsyncSession,
    scenario_id: uuid.UUID,
    job_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Scenario:
    import app.services.solver_job_service as solver_job_svc

    scenario = await get_or_404(db, scenario_id)
    job = await solver_job_svc.get_job_for_scenario_or_404(db, scenario_id, job_id)
    if job.status not in _RESTORABLE_JOB_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Only successful solver jobs can be published",
        )

    if scenario.published_job_id == job.id:
        logger.info(
            "Scenario already published on this job — skipping invalidation",
            scenario_id=str(scenario_id),
            job_id=str(job_id),
        )
        return scenario

    scenario.published_job_id = job.id
    scenario.published_at = datetime.now(timezone.utc)
    scenario.published_by_user_id = user_id
    await db.flush()
    logger.info(
        "Scenario published",
        scenario_id=str(scenario_id),
        job_id=str(job_id),
        published_by=str(user_id),
    )

    from app.services import audit_log_service  # noqa: PLC0415
    from app.models.audit_log import AuditAction  # noqa: PLC0415
    await audit_log_service.record(
        db,
        actor_user_id=user_id,
        actor_role=None,
        action=AuditAction.PUBLISHED,
        entity_type="Scenario",
        entity_id=scenario_id,
        entity_label=scenario.name,
        institution_id=scenario.institution_id,
    )

    import app.services.selection_invalidation_service as invalidation_svc
    from app.services.selection_invalidation_service import INVALIDATION_TIMETABLE_CHANGED

    await invalidation_svc.invalidate_for_scenario(
        db,
        scenario_id,
        reason=INVALIDATION_TIMETABLE_CHANGED,
        institution_id=scenario.institution_id,
        actor_user_id=user_id,
    )

    # Notify all admins in this institution that the timetable was published
    from app.services import notification_service  # noqa: PLC0415
    from app.models.notification import NotificationType  # noqa: PLC0415
    from app.models.user import UserRole  # noqa: PLC0415
    await notification_service.send_to_role(
        db,
        institution_id=scenario.institution_id,
        role=UserRole.ADMIN,
        notification_type=NotificationType.TIMETABLE_PUBLISHED,
        title="Timetable Published",
        body=f"Scenario '{scenario.name}' has been published.",
        metadata={"scenario_id": str(scenario_id), "deep_link": f"/timetable?scenario={scenario_id}"},
    )

    await notification_service.send_to_role(
        db,
        institution_id=scenario.institution_id,
        role=UserRole.HOD,
        notification_type=NotificationType.TIMETABLE_PUBLISHED,
        title="Department Timetable Published",
        body=f"The published timetable for '{scenario.name}' is now available.",
        metadata={"scenario_id": str(scenario_id), "deep_link": "/timetable"},
    )

    # Notify affected teachers that their schedule is now available
    try:
        from app.models.curriculum import TeachingAssignment as _TA  # noqa: PLC0415
        from app.models.faculty import Faculty as _Faculty  # noqa: PLC0415
        from app.models.user import User as _User  # noqa: PLC0415

        faculty_ids_result = await db.execute(
            select(_TA.faculty_id)
            .where(
                _TA.institution_id == scenario.institution_id,
                _TA.academic_term_id == scenario.academic_term_id,
                _TA.faculty_id.is_not(None),
            )
            .distinct()
        )
        faculty_ids = [fid for fid in faculty_ids_result.scalars().all() if fid is not None]
        if faculty_ids:
            teacher_users_result = await db.execute(
                select(_User)
                .join(_Faculty, _Faculty.user_id == _User.id)
                .where(_Faculty.id.in_(faculty_ids))
            )
            teacher_users = list(teacher_users_result.scalars().all())
            if teacher_users:
                await notification_service.send(
                    db,
                    institution_id=scenario.institution_id,
                    notification_type=NotificationType.SCHEDULE_AVAILABLE,
                    recipients=teacher_users,
                    title="Timetable Available",
                    body=f"The '{scenario.name}' timetable is now published. View your schedule.",
                    metadata={
                        "scenario_id": str(scenario_id),
                        "deep_link": "/dashboard",
                    },
                )
    except Exception:
        logger.warning("Failed to notify teachers of schedule availability", exc_info=True)

    # Auto-allocate unassigned students in the institution for the academic term
    try:
        from app.models.student import StudentProfile
        from app.models.user import User
        from app.services.student_service import bulk_auto_allocate_batch

        unassigned_students_result = await db.execute(
            select(StudentProfile.id)
            .join(User, StudentProfile.user_id == User.id)
            .where(
                User.institution_id == scenario.institution_id,
                StudentProfile.batch_id.is_(None),
            )
        )
        unassigned_student_ids = unassigned_students_result.scalars().all()
        if unassigned_student_ids:
            allocated_count = await bulk_auto_allocate_batch(
                db,
                list(unassigned_student_ids),
                scenario.academic_term_id,
            )
            logger.info(
                "Auto-allocated students on scenario publish",
                scenario_id=str(scenario_id),
                allocated_count=allocated_count,
            )
    except Exception:
        logger.warning(
            "Failed to auto-allocate students on scenario publish",
            scenario_id=str(scenario_id),
            exc_info=True,
        )

    return scenario


async def unpublish(
    db: AsyncSession,
    scenario_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Scenario:
    """Clear published job and invalidate linked student selections."""
    scenario = await get_or_404(db, scenario_id)
    if scenario.published_job_id is None:
        return scenario

    import app.services.selection_invalidation_service as invalidation_svc
    from app.services.selection_invalidation_service import INVALIDATION_SCENARIO_UNPUBLISHED

    await invalidation_svc.invalidate_for_scenario(
        db,
        scenario_id,
        reason=INVALIDATION_SCENARIO_UNPUBLISHED,
        institution_id=scenario.institution_id,
        actor_user_id=user_id,
    )

    scenario.published_job_id = None
    scenario.published_at = None
    scenario.published_by_user_id = None
    await db.flush()

    from app.services import audit_log_service  # noqa: PLC0415
    from app.models.audit_log import AuditAction  # noqa: PLC0415
    await audit_log_service.record(
        db,
        actor_user_id=user_id,
        actor_role=None,
        action=AuditAction.UPDATED,
        entity_type="Scenario",
        entity_id=scenario_id,
        entity_label=scenario.name,
        institution_id=scenario.institution_id,
        after={"published_job_id": None},
    )
    logger.info("Scenario unpublished", scenario_id=str(scenario_id))
    return scenario


def _snapshot_to_sessions(snapshot_rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    sessions: list[dict[str, Any]] = []
    for row in snapshot_rows:
        sessions.append(
            {
                "session_id": row["session_id"],
                "course_id": row["course_id"],
                "faculty_id": row["faculty_id"],
                "room_id": row["room_id"],
                "slot_code": row["slot_code"],
                "offering_id": row.get("offering_id"),
            }
        )
    return sessions


async def restore_job_as_current(
    db: AsyncSession,
    scenario_id: uuid.UUID,
    job_id: uuid.UUID,
) -> Scenario:
    import app.services.schedule_service as schedule_svc
    import app.services.solver_job_service as solver_job_svc

    scenario = await get_or_404(db, scenario_id)
    job = await solver_job_svc.get_job_for_scenario_or_404(db, scenario_id, job_id)
    if job.status not in _RESTORABLE_JOB_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Only successful solver jobs can be restored as current",
        )
    if not job.result_schedule:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Selected solver job has no schedule snapshot to restore",
        )

    await schedule_svc.clear_and_persist(
        db,
        scenario_id,
        _snapshot_to_sessions(job.result_schedule),
    )
    scenario.current_job_id = job.id
    scenario.status = ScenarioStatus.COMPLETED
    scenario.is_dirty = False
    scenario.celery_task_id = None
    await db.flush()
    logger.info(
        "Scenario current schedule restored from history",
        scenario_id=str(scenario_id),
        job_id=str(job_id),
    )
    return scenario


async def mark_dirty(db: AsyncSession, scenario_id: uuid.UUID) -> None:
    """Set is_dirty=True.  Called whenever rules or data linked to the scenario change."""
    scenario = await get_or_404(db, scenario_id)
    scenario.is_dirty = True
    await db.flush()


async def clone(
    db: AsyncSession,
    scenario_id: uuid.UUID,
    new_name: str,
    *,
    actor_user_id: uuid.UUID | None = None,
    actor_role: str | None = None,
) -> Scenario:
    """
    Deep-copy *scenario* (including rules, SchedulingTargets, OfferingBuckets,
    CourseOfferings, and TargetRequirements) into a new DRAFT scenario.

    Returns the new unsaved scenario (caller must commit).
    """
    source = await get_with_rules(db, scenario_id)

    cloned = Scenario(
        institution_id=source.institution_id,
        academic_term_id=source.academic_term_id,
        name=new_name,
        solver_config=source.solver_config,
        scheduling_mode=source.scheduling_mode,
        status=ScenarioStatus.DRAFT,
        is_dirty=True,
        parent_scenario_id=source.id,
    )
    db.add(cloned)
    await db.flush()  # get cloned.id

    # ── Clone ScenarioRules ───────────────────────────────────────────────────
    for rule in source.rules:
        new_rule = ScenarioRule(
            scenario_id=cloned.id,
            definition_code=rule.definition_code,
            tier=rule.tier,
            rule_type=rule.rule_type,
            params=rule.params,
            script_trigger=rule.script_trigger,
            script_logic=rule.script_logic,
            is_hard_constraint=rule.is_hard_constraint,
            penalty_weight=rule.penalty_weight,
            soft_tier=rule.soft_tier,
            target_id=rule.target_id,
            is_enabled=rule.is_enabled,
            created_by_agent=rule.created_by_agent,
            original_prompt=rule.original_prompt,
            agent_reasoning=rule.agent_reasoning,
        )
        db.add(new_rule)

    # ── Clone SchedulingTargets scoped to source scenario ────────────────────
    targets_result = await db.execute(
        select(SchedulingTarget).where(
            SchedulingTarget.scenario_id == source.id
        ).order_by(
            # COHORTs (parent_id IS NULL) first so parent FK is available when
            # BATCHes are inserted.
            SchedulingTarget.parent_id.is_(None).desc(),
            SchedulingTarget.created_at,
        )
    )
    source_targets = targets_result.scalars().all()

    old_to_new_target: dict[uuid.UUID, uuid.UUID] = {}
    for old_target in source_targets:
        new_id = uuid.uuid4()
        old_to_new_target[old_target.id] = new_id
        new_parent_id = (
            old_to_new_target.get(old_target.parent_id)
            if old_target.parent_id else None
        )
        db.add(SchedulingTarget(
            id=new_id,
            scenario_id=cloned.id,
            parent_id=new_parent_id,
            institution_id=old_target.institution_id,
            academic_term_id=old_target.academic_term_id,
            name=old_target.name,
            target_type=old_target.target_type,
            size=old_target.size,
            department_id=old_target.department_id,
            extra_data=old_target.extra_data,
            allowed_shifts=old_target.allowed_shifts,
            is_active=old_target.is_active,
            class_count=old_target.class_count,
        ))

    # ── Clone OfferingBuckets scoped to source scenario ──────────────────────
    buckets_result = await db.execute(
        select(OfferingBucket).where(OfferingBucket.scenario_id == source.id)
    )
    source_buckets = buckets_result.scalars().all()

    old_to_new_bucket: dict[uuid.UUID, uuid.UUID] = {}
    for old_bucket in source_buckets:
        new_id = uuid.uuid4()
        old_to_new_bucket[old_bucket.id] = new_id
        db.add(OfferingBucket(
            id=new_id,
            scenario_id=cloned.id,
            institution_id=old_bucket.institution_id,
            academic_term_id=old_bucket.academic_term_id,
            department_id=old_bucket.department_id,
            name=old_bucket.name,
            description=old_bucket.description,
            min_selection=old_bucket.min_selection,
            max_selection=old_bucket.max_selection,
            force_parallel_slots=old_bucket.force_parallel_slots,
            selection_policy=old_bucket.selection_policy,
            is_active=old_bucket.is_active,
        ))

    await db.flush()  # ensure new bucket IDs are available for FK references

    # ── Clone CourseOfferings — reset solver output fields ───────────────────
    if old_to_new_bucket:
        offerings_result = await db.execute(
            select(CourseOffering).where(
                CourseOffering.bucket_id.in_(list(old_to_new_bucket.keys()))
            )
        )
        for old_offering in offerings_result.scalars().all():
            db.add(CourseOffering(
                id=uuid.uuid4(),
                bucket_id=old_to_new_bucket[old_offering.bucket_id],
                course_id=old_offering.course_id,
                faculty_id=old_offering.faculty_id,
                min_capacity=old_offering.min_capacity,
                max_room_capacity=old_offering.max_room_capacity,
                target_room_ids=old_offering.target_room_ids,
                target_lab_room_ids=old_offering.target_lab_room_ids,
                target_room_ids_soft=old_offering.target_room_ids_soft,
                target_room_tags=old_offering.target_room_tags,
                target_lab_room_tags=old_offering.target_lab_room_tags,
                max_seats=old_offering.max_seats,
                is_frozen=old_offering.is_frozen,
                fixed_slot_id=old_offering.fixed_slot_id,
                # solver output fields reset to NULL
                slot_code=None,
                room_id=None,
                slot_family=None,
            ))

    # ── Clone TargetRequirements — remap both bucket and target IDs ──────────
    if old_to_new_bucket:
        reqs_result = await db.execute(
            select(TargetRequirement).where(
                TargetRequirement.bucket_id.in_(list(old_to_new_bucket.keys()))
            )
        )
        for old_req in reqs_result.scalars().all():
            new_bucket_id = old_to_new_bucket.get(old_req.bucket_id)
            if new_bucket_id is None:
                continue
            new_target_id = old_to_new_target.get(old_req.target_id, old_req.target_id)
            db.add(TargetRequirement(
                id=uuid.uuid4(),
                target_id=new_target_id,
                bucket_id=new_bucket_id,
            ))

    await db.flush()
    logger.info(
        "Scenario cloned",
        source_id=str(scenario_id),
        clone_id=str(cloned.id),
        name=new_name,
        targets_cloned=len(source_targets),
        buckets_cloned=len(source_buckets),
    )

    from app.services import audit_log_service  # noqa: PLC0415
    from app.models.audit_log import AuditAction  # noqa: PLC0415
    await audit_log_service.record(
        db,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action=AuditAction.CREATED,
        entity_type="Scenario",
        entity_id=cloned.id,
        entity_label=new_name,
        institution_id=cloned.institution_id,
        after={"cloned_from": str(scenario_id), "name": new_name},
    )
    return cloned


async def delete_preserve_history(
    db: AsyncSession,
    scenario_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID | None = None,
    actor_role: str | None = None,
) -> None:
    """
    Purge scenario-owned operational rows but preserve solver history.

    The Scenario row remains as a tombstoned shell so SolverJob rows and their
    JobConflicts remain addressable through the existing FK.
    """
    scenario = await get_or_404(db, scenario_id)

    await db.execute(
        delete(ScenarioRule).where(ScenarioRule.scenario_id == scenario_id)
    )
    await db.execute(
        delete(ScheduledSession).where(ScheduledSession.scenario_id == scenario_id)
    )
    await db.execute(
        delete(OfferingBucket).where(OfferingBucket.scenario_id == scenario_id)
    )
    await db.execute(
        delete(SchedulingTarget).where(SchedulingTarget.scenario_id == scenario_id)
    )

    scenario.selected_time_grid_id = None
    scenario.celery_task_id = None
    scenario.best_hint = None
    scenario.solver_config = None
    scenario.current_job_id = None
    scenario.published_job_id = None
    scenario.published_at = None
    scenario.published_by_user_id = None
    scenario.auto_publish_latest = False
    scenario.is_dirty = False
    scenario.deleted_at = datetime.now(timezone.utc)

    await db.flush()
    logger.info(
        "Scenario operational data purged; solver history preserved",
        scenario_id=str(scenario_id),
    )

    from app.services import audit_log_service  # noqa: PLC0415
    from app.models.audit_log import AuditAction  # noqa: PLC0415
    await audit_log_service.record(
        db,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action=AuditAction.DELETED,
        entity_type="Scenario",
        entity_id=scenario_id,
        entity_label=scenario.name,
        institution_id=scenario.institution_id,
    )
