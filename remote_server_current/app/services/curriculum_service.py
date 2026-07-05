"""
app/services/curriculum_service.py
====================================
CRUD for the Curriculum / Demand layer:
  SchedulingTarget, OfferingBucket, CourseOffering, TargetRequirement.

Architecture notes
------------------
These four models power the solver's "demand matrix":

  SchedulingTarget  → who needs a timetable (batch / cluster / virtual)
  OfferingBucket    → container of course offerings + constraint metadata
  CourseOffering    → one faculty×course slot assignment (solver INPUT + OUTPUT)
  TargetRequirement → M2M link: target must attend bucket

FFCS Seat operations
---------------------
  ``book_seat``   — atomic booked_seats++ checked against max_seats.
  ``release_seat`` — atomic booked_seats-- for drops / cancellations.

Both use ``with_for_update()`` to prevent race conditions on the counter.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.logger import logger
import app.services.audit_log_service as audit_log_service
from app.models.audit_log import AuditAction
from app.models.curriculum import (
    CourseOffering,
    OfferingBucket,
    SchedulingTarget,
    TargetCourseDemand,
    TargetRequirement,
)
from app.schemas.curriculum import (
    CourseOfferingCreate,
    CourseOfferingResponse,
    CourseOfferingUpdate,
    CohortSetupResponse,
    OfferingBucketCreate,
    OfferingBucketUpdate,
    SchedulingTargetCreate,
    SchedulingTargetUpdate,
    TargetRequirementCreate,
)


def _infer_batch_name_from_bucket_name(bucket_name: str | None) -> str | None:
    if not bucket_name or " — " not in bucket_name:
        return None

    inferred = bucket_name.rsplit(" — ", 1)[-1].strip()
    return inferred or None


# ---------------------------------------------------------------------------
# SchedulingTarget
# ---------------------------------------------------------------------------


async def list_targets(
    db: AsyncSession,
    institution_id: Optional[uuid.UUID] = None,
    *,
    academic_term_id: Optional[uuid.UUID] = None,
    department_id: Optional[uuid.UUID] = None,
    target_type: Optional[str] = None,
    parent_id: Optional[uuid.UUID] = None,
    scenario_id: Optional[uuid.UUID] = None,
    active_only: bool = True,
    skip: int = 0,
    limit: int = 100,
) -> list[SchedulingTarget]:
    from app.models.curriculum import TargetType as _TargetType
    q = select(SchedulingTarget)
    if institution_id is not None:
        q = q.where(SchedulingTarget.institution_id == institution_id)
    if academic_term_id is not None:
        q = q.where(SchedulingTarget.academic_term_id == academic_term_id)
    if department_id is not None:
        q = q.where(SchedulingTarget.department_id == department_id)
    if target_type is not None:
        try:
            tt = _TargetType(target_type.upper())
            q = q.where(SchedulingTarget.target_type == tt)
        except ValueError:
            pass  # ignore unknown type filter
    if parent_id is not None:
        q = q.where(SchedulingTarget.parent_id == parent_id)
    if scenario_id is not None:
        q = q.where(or_(
            SchedulingTarget.scenario_id == scenario_id,
            SchedulingTarget.scenario_id.is_(None),  # include legacy term-level targets
        ))
    if active_only:
        q = q.where(SchedulingTarget.is_active == True)  # noqa: E712
    q = q.order_by(SchedulingTarget.name).offset(skip).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


async def get_target_or_404(
    db: AsyncSession, target_id: uuid.UUID
) -> SchedulingTarget:
    result = await db.execute(
        select(SchedulingTarget).where(SchedulingTarget.id == target_id)
    )
    obj = result.scalars().first()
    if obj is None:
        raise NotFoundError(f"SchedulingTarget {target_id} not found")
    return obj


async def create_target(
    db: AsyncSession,
    payload: SchedulingTargetCreate,
) -> "SchedulingTarget | CohortSetupResponse":
    """
    Create a SchedulingTarget.

    If target_type=COHORT, delegates to cohort_service.setup_cohort()
    which reads TeachingAssignments and creates BATCH children + demands +
    buckets + offerings atomically. Returns CohortSetupResponse in that case.
    """
    from app.models.curriculum import TargetType
    if payload.target_type == TargetType.COHORT:
        from app.services.cohort_service import setup_cohort
        return await setup_cohort(db, payload)

    target = SchedulingTarget(**payload.model_dump(exclude={"scheduling_mode"}))
    db.add(target)
    await db.flush()
    logger.info(
        "SchedulingTarget created",
        target_id=str(target.id),
        name=target.name,
        type=target.target_type.value,
    )
    await audit_log_service.record(
        db,
        actor_user_id=None,
        actor_role=None,
        action=AuditAction.CREATED,
        entity_type="SchedulingTarget",
        entity_id=target.id,
        entity_label=target.name,
        institution_id=target.institution_id,
    )
    return target


async def create_batch_target(
    db: AsyncSession,
    payload: SchedulingTargetCreate,
) -> SchedulingTarget:
    """
    Thin wrapper for creating a BATCH child target directly (bypasses COHORT delegation).
    Called by cohort_service so it doesn't need to import SchedulingTarget ORM directly.
    """
    target = SchedulingTarget(**payload.model_dump(exclude={"scheduling_mode"}))
    db.add(target)
    await db.flush()
    logger.info(
        "BATCH child target created",
        target_id=str(target.id),
        name=target.name,
        parent_id=str(target.parent_id) if target.parent_id else None,
    )
    return target


async def update_target(
    db: AsyncSession,
    target_id: uuid.UUID,
    payload: SchedulingTargetUpdate,
) -> SchedulingTarget:
    target = await get_target_or_404(db, target_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(target, field, value)
    await db.flush()
    logger.info("SchedulingTarget updated", target_id=str(target_id))
    await audit_log_service.record(
        db,
        actor_user_id=None,
        actor_role=None,
        action=AuditAction.UPDATED,
        entity_type="SchedulingTarget",
        entity_id=target_id,
        entity_label=target.name,
        institution_id=target.institution_id,
    )
    return target


async def soft_delete_target(
    db: AsyncSession, target_id: uuid.UUID
) -> SchedulingTarget:
    target = await get_target_or_404(db, target_id)
    target.is_active = False
    await db.flush()
    logger.info("SchedulingTarget deactivated", target_id=str(target_id))
    await audit_log_service.record(
        db,
        actor_user_id=None,
        actor_role=None,
        action=AuditAction.DELETED,
        entity_type="SchedulingTarget",
        entity_id=target_id,
        entity_label=target.name,
        institution_id=target.institution_id,
    )
    return target


async def delete_cohort_cascade(
    db: AsyncSession, cohort_id: uuid.UUID
) -> None:
    """
    Hard-delete a COHORT and all data it owns.

    Covers both scheduling modes:
    - TRADITIONAL: TargetRequirements link BATCH children → buckets
    - HYBRID:      TargetRequirements link the COHORT itself → buckets

    Steps:
    1. Collect BATCH children.
    2. Build all_target_ids = [cohort] + [children] so we find requirements
       regardless of whether they were attached to the cohort or its batches.
    3. Collect all linked OfferingBucket IDs via TargetRequirement.
    4. Hard-delete TargetCourseDemand for all targets (no DB cascade on this FK).
    5. Hard-delete each OfferingBucket (DB cascade deletes CourseOffering +
       TargetRequirement rows on that bucket automatically).
    6. Hard-delete the COHORT (DB cascade deletes BATCH children).
    """
    cohort = await get_target_or_404(db, cohort_id)

    # 1. BATCH children
    children = await list_children(db, cohort_id)
    child_ids = [c.id for c in children]

    # 2. All target IDs: COHORT + its BATCH children
    all_target_ids = [cohort_id] + child_ids

    # 3. Collect bucket IDs linked to ANY of the targets (cohort-level for
    #    HYBRID, batch-level for TRADITIONAL)
    req_result = await db.execute(
        select(TargetRequirement.bucket_id).where(
            TargetRequirement.target_id.in_(all_target_ids)
        )
    )
    bucket_ids = list({row[0] for row in req_result.all()})

    # 4. Hard-delete TargetCourseDemand (no DB-level cascade on target_id FK)
    await db.execute(
        delete(TargetCourseDemand).where(
            TargetCourseDemand.target_id.in_(all_target_ids)
        )
    )

    # 5. Hard-delete OfferingBuckets → cascades to CourseOffering + TargetRequirement.
    #    BUT only buckets owned EXCLUSIVELY by this cohort. If a bucket is also
    #    required by another target (legacy shared/duplicate data), just unlink
    #    this cohort's requirement so the other cohort keeps its offerings.
    for bucket_id in bucket_ids:
        shared = (await db.execute(
            select(TargetRequirement.id).where(
                TargetRequirement.bucket_id == bucket_id,
                TargetRequirement.target_id.notin_(all_target_ids),
            ).limit(1)
        )).first()
        if shared is not None:
            await db.execute(
                delete(TargetRequirement).where(
                    TargetRequirement.bucket_id == bucket_id,
                    TargetRequirement.target_id.in_(all_target_ids),
                )
            )
            logger.warning(
                "Skipped deleting shared bucket during cohort delete",
                bucket_id=str(bucket_id),
                cohort_id=str(cohort_id),
            )
            continue
        bucket = await db.get(OfferingBucket, bucket_id)
        if bucket is not None:
            await db.delete(bucket)

    # 6. Hard-delete COHORT → DB cascade deletes BATCH children
    await db.delete(cohort)
    await db.flush()
    logger.info(
        "COHORT hard-deleted with cascade",
        cohort_id=str(cohort_id),
        child_count=len(child_ids),
        bucket_count=len(bucket_ids),
    )
    await audit_log_service.record(
        db,
        actor_user_id=None,
        actor_role=None,
        action=AuditAction.DELETED,
        entity_type="SchedulingTarget",
        entity_id=cohort_id,
        entity_label=cohort.name,
        institution_id=cohort.institution_id,
        after={"child_count": len(child_ids), "bucket_count": len(bucket_ids)},
    )


# ---------------------------------------------------------------------------
# OfferingBucket
# ---------------------------------------------------------------------------


async def list_buckets(
    db: AsyncSession,
    institution_id: uuid.UUID,
    *,
    academic_term_id: Optional[uuid.UUID] = None,
    department_id: Optional[uuid.UUID] = None,
    scenario_id: Optional[uuid.UUID] = None,
    active_only: bool = True,
    skip: int = 0,
    limit: int = 100,
) -> list[OfferingBucket]:
    q = select(OfferingBucket).where(OfferingBucket.institution_id == institution_id)
    if academic_term_id is not None:
        q = q.where(OfferingBucket.academic_term_id == academic_term_id)
    if department_id is not None:
        q = q.where(OfferingBucket.department_id == department_id)
    if scenario_id is not None:
        q = q.where(or_(
            OfferingBucket.scenario_id == scenario_id,
            OfferingBucket.scenario_id.is_(None),  # include legacy term-level buckets
        ))
    if active_only:
        q = q.where(OfferingBucket.is_active == True)  # noqa: E712
    q = q.order_by(OfferingBucket.name).offset(skip).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


async def get_bucket_or_404(
    db: AsyncSession, bucket_id: uuid.UUID
) -> OfferingBucket:
    result = await db.execute(
        select(OfferingBucket).where(OfferingBucket.id == bucket_id)
    )
    obj = result.scalars().first()
    if obj is None:
        raise NotFoundError(f"OfferingBucket {bucket_id} not found")
    return obj


async def create_bucket(
    db: AsyncSession,
    payload: OfferingBucketCreate,
) -> OfferingBucket:
    bucket = OfferingBucket(**payload.model_dump())
    db.add(bucket)
    await db.flush()
    logger.info(
        "OfferingBucket created",
        bucket_id=str(bucket.id),
        name=bucket.name,
        policy=bucket.selection_policy.value,
    )
    await audit_log_service.record(
        db,
        actor_user_id=None,
        actor_role=None,
        action=AuditAction.CREATED,
        entity_type="OfferingBucket",
        entity_id=bucket.id,
        entity_label=bucket.name,
        institution_id=bucket.institution_id,
    )
    return bucket


async def update_bucket(
    db: AsyncSession,
    bucket_id: uuid.UUID,
    payload: OfferingBucketUpdate,
) -> OfferingBucket:
    bucket = await get_bucket_or_404(db, bucket_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(bucket, field, value)
    await db.flush()
    logger.info("OfferingBucket updated", bucket_id=str(bucket_id))
    await audit_log_service.record(
        db,
        actor_user_id=None,
        actor_role=None,
        action=AuditAction.UPDATED,
        entity_type="OfferingBucket",
        entity_id=bucket_id,
        entity_label=bucket.name,
        institution_id=bucket.institution_id,
    )
    return bucket


async def soft_delete_bucket(
    db: AsyncSession, bucket_id: uuid.UUID
) -> OfferingBucket:
    bucket = await get_bucket_or_404(db, bucket_id)
    bucket.is_active = False
    await db.flush()
    logger.info("OfferingBucket deactivated", bucket_id=str(bucket_id))
    await audit_log_service.record(
        db,
        actor_user_id=None,
        actor_role=None,
        action=AuditAction.DELETED,
        entity_type="OfferingBucket",
        entity_id=bucket_id,
        entity_label=bucket.name,
        institution_id=bucket.institution_id,
    )
    return bucket


# ---------------------------------------------------------------------------
# CourseOffering
# ---------------------------------------------------------------------------


async def list_offerings(
    db: AsyncSession,
    bucket_id: uuid.UUID,
    *,
    skip: int = 0,
    limit: int = 100,
) -> list[CourseOffering]:
    result = await db.execute(
        select(CourseOffering)
        .where(CourseOffering.bucket_id == bucket_id)
        .order_by(CourseOffering.created_at)
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


async def list_offerings_for_buckets(
    db: AsyncSession,
    institution_id: uuid.UUID,
    *,
    academic_term_id: Optional[uuid.UUID] = None,
    department_id: Optional[uuid.UUID] = None,
    scenario_id: Optional[uuid.UUID] = None,
    active_only: bool = True,
    skip: int = 0,
    limit: int = 10000,
) -> list[CourseOffering]:
    """List all offerings across buckets matching the same filters as list_buckets."""
    q = (
        select(CourseOffering)
        .join(OfferingBucket, CourseOffering.bucket_id == OfferingBucket.id)
        .where(OfferingBucket.institution_id == institution_id)
    )
    if academic_term_id is not None:
        q = q.where(OfferingBucket.academic_term_id == academic_term_id)
    if department_id is not None:
        q = q.where(OfferingBucket.department_id == department_id)
    if scenario_id is not None:
        q = q.where(
            or_(
                OfferingBucket.scenario_id == scenario_id,
                OfferingBucket.scenario_id.is_(None),
            )
        )
    if active_only:
        q = q.where(OfferingBucket.is_active == True)  # noqa: E712
    q = q.order_by(CourseOffering.created_at).offset(skip).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


async def enrich_offerings(
    db: AsyncSession,
    offerings: list[CourseOffering],
) -> list[CourseOfferingResponse]:
    """
    Batch-fetch course, faculty, bucket, and batch names for a list of
    CourseOffering ORM objects and return enriched response dicts.
    """
    if not offerings:
        return []

    from app.models.faculty import Faculty
    from app.models.course import Course

    # --- courses ---
    course_ids = list({o.course_id for o in offerings})
    course_map: dict[str, tuple[str, str, str]] = {}
    if course_ids:
        rows = await db.execute(
            select(Course.id, Course.code, Course.name, Course.session_type)
            .where(Course.id.in_(course_ids))
        )
        for row in rows.all():
            stype = (
                row.session_type.value
                if hasattr(row.session_type, "value")
                else str(row.session_type or "")
            )
            course_map[str(row.id)] = (row.code or "", row.name or "", stype)

    # --- faculty ---
    faculty_ids = list({o.faculty_id for o in offerings if o.faculty_id})
    faculty_map: dict[str, str] = {}
    if faculty_ids:
        rows = await db.execute(
            select(Faculty.id, Faculty.name).where(Faculty.id.in_(faculty_ids))
        )
        for row in rows.all():
            faculty_map[str(row.id)] = row.name or ""

    # --- buckets + linked batch targets ---
    bucket_ids = list({o.bucket_id for o in offerings})
    bucket_map: dict[str, str] = {}
    batch_map: dict[str, str] = {}   # bucket_id → first linked target name
    if bucket_ids:
        b_rows = await db.execute(
            select(OfferingBucket.id, OfferingBucket.name)
            .where(OfferingBucket.id.in_(bucket_ids))
        )
        for row in b_rows.all():
            bucket_map[str(row.id)] = row.name or ""

        t_rows = await db.execute(
            select(TargetRequirement.bucket_id, SchedulingTarget.name)
            .join(SchedulingTarget, SchedulingTarget.id == TargetRequirement.target_id)
            .where(TargetRequirement.bucket_id.in_(bucket_ids))
        )
        for row in t_rows.all():
            bid = str(row.bucket_id)
            if bid not in batch_map:
                batch_map[bid] = row.name or ""

        for bucket_id, bucket_name in bucket_map.items():
            if batch_map.get(bucket_id):
                continue

            inferred_batch_name = _infer_batch_name_from_bucket_name(bucket_name)
            if inferred_batch_name:
                batch_map[bucket_id] = inferred_batch_name
                logger.warning(
                    "Offering bucket missing TargetRequirement; inferred batch name from bucket name",
                    bucket_id=bucket_id,
                    bucket_name=bucket_name,
                    inferred_batch_name=inferred_batch_name,
                )

    enriched: list[CourseOfferingResponse] = []
    for o in offerings:
        base = CourseOfferingResponse.model_validate(o)
        code, cname, stype = course_map.get(str(o.course_id), ("", "", ""))
        base.course_code = code or None
        base.course_name = cname or None
        base.course_session_type = stype or None
        base.faculty_name = faculty_map.get(str(o.faculty_id)) if o.faculty_id else None
        base.bucket_name = bucket_map.get(str(o.bucket_id))
        base.batch_name = batch_map.get(str(o.bucket_id))
        enriched.append(base)

    return enriched


async def get_offering_or_404(
    db: AsyncSession, offering_id: uuid.UUID
) -> CourseOffering:
    result = await db.execute(
        select(CourseOffering).where(CourseOffering.id == offering_id)
    )
    obj = result.scalars().first()
    if obj is None:
        raise NotFoundError(f"CourseOffering {offering_id} not found")
    return obj


async def create_offering(
    db: AsyncSession,
    payload: CourseOfferingCreate,
) -> CourseOffering:
    # Verify parent bucket exists
    await get_bucket_or_404(db, payload.bucket_id)
    offering = CourseOffering(**payload.model_dump())
    db.add(offering)
    await db.flush()
    logger.info(
        "CourseOffering created",
        offering_id=str(offering.id),
        course_id=str(offering.course_id),
        bucket_id=str(offering.bucket_id),
    )
    await audit_log_service.record(
        db,
        actor_user_id=None,
        actor_role=None,
        action=AuditAction.CREATED,
        entity_type="CourseOffering",
        entity_id=offering.id,
        entity_label=str(offering.course_id),
        institution_id=offering.institution_id if hasattr(offering, "institution_id") else None,
    )
    return offering


async def update_offering(
    db: AsyncSession,
    offering_id: uuid.UUID,
    payload: CourseOfferingUpdate,
) -> CourseOffering:
    """Update offering fields — used by the solver to write slot_code + room_id."""
    offering = await get_offering_or_404(db, offering_id)
    payload_data = payload.model_dump(exclude_unset=True)
    if "max_seats" in payload_data:
        new_max = payload_data["max_seats"]
        if new_max is not None and offering.booked_seats > new_max:
            raise ValidationError(
                f"max_seats ({new_max}) cannot be less than booked_seats "
                f"({offering.booked_seats})"
            )
    for field, value in payload_data.items():
        setattr(offering, field, value)
    await db.flush()
    logger.info("CourseOffering updated", offering_id=str(offering_id))
    return offering


async def freeze_offering(
    db: AsyncSession, offering_id: uuid.UUID, frozen: bool
) -> CourseOffering:
    """Set is_frozen=True/False to block or unblock FFCS registrations."""
    offering = await get_offering_or_404(db, offering_id)
    offering.is_frozen = frozen
    await db.flush()
    logger.info(
        "CourseOffering freeze toggled",
        offering_id=str(offering_id),
        frozen=frozen,
    )
    return offering


async def book_seat(
    db: AsyncSession, 
    offering_id: uuid.UUID,
    department_id: uuid.UUID | None = None,
    dept_override: int | None = None,
) -> CourseOffering:
    """
    Atomically increment booked_seats for FFCS Phase 2 registration.

    Integrates a Redis fast-fail cache check to avoid DB lock contention for
    full offerings, while maintaining PostgreSQL row locks as the source of truth.

    Raises
    ------
    ValidationError   if the offering is frozen.
    ConflictError     if booked_seats >= max_seats.
    """
    # Try Redis fast-fail check first
    from app.core.redis_client import get_async_redis
    redis_client = get_async_redis()
    seats_key = f"offering:seats:{offering_id}"
    try:
        redis_val = await redis_client.get(seats_key)
        if redis_val is not None:
            seats_left = int(redis_val)
            if seats_left <= 0:
                raise ConflictError(
                    f"CourseOffering {offering_id} is full (fast-failed via cache)"
                )
    except ConflictError:
        raise
    except Exception as e:
        logger.warning("Redis fast-fail check error", error=str(e))
    finally:
        await redis_client.aclose()

    # Fall back to transactional PostgreSQL write lock (source of truth)
    result = await db.execute(
        select(CourseOffering)
        .where(CourseOffering.id == offering_id)
        .with_for_update()
    )
    offering = result.scalars().first()
    if offering is None:
        raise NotFoundError(f"CourseOffering {offering_id} not found")

    if offering.is_frozen:
        raise ValidationError(
            f"CourseOffering {offering_id} is frozen — registrations are blocked"
        )

    # Check department-level seat override
    if dept_override is not None and department_id is not None:
        from app.models.student import StudentRegistration, StudentProfile, RegistrationStatus
        from app.models.user import User
        from sqlalchemy import func
        
        dept_count_res = await db.execute(
            select(func.count())
            .select_from(StudentRegistration)
            .join(StudentProfile, StudentRegistration.student_id == StudentProfile.id)
            .join(User, StudentProfile.user_id == User.id)
            .where(
                StudentRegistration.offering_id == offering_id,
                StudentRegistration.status == RegistrationStatus.CONFIRMED,
                User.department_id == department_id
            )
        )
        dept_count = dept_count_res.scalar() or 0
        if dept_count >= dept_override:
            raise ConflictError(
                f"CourseOffering {offering_id} is full for your department (max {dept_override} seats)."
            )

    max_seats = offering.max_seats
    current_booked = offering.booked_seats

    if max_seats is not None and current_booked >= max_seats:
        # Cache full status in Redis for 5 minutes to prevent further DB hits
        redis_client = get_async_redis()
        try:
            await redis_client.set(seats_key, 0, ex=300)
        except Exception as e:
            logger.warning("Redis set full status error", error=str(e))
        finally:
            await redis_client.aclose()

        raise ConflictError(
            f"CourseOffering {offering_id} is full "
            f"({offering.booked_seats}/{offering.max_seats} seats)"
        )

    offering.booked_seats += 1
    await db.flush()

    # Update Redis cache with updated remaining seats (cached for 1 hour)
    redis_client = get_async_redis()
    try:
        if max_seats is not None:
            seats_left = max_seats - offering.booked_seats
            await redis_client.set(seats_key, seats_left, ex=3600)
    except Exception as e:
        logger.warning("Redis update seat count error", error=str(e))
    finally:
        await redis_client.aclose()

    logger.info(
        "Seat booked",
        offering_id=str(offering_id),
        booked=offering.booked_seats,
        max=offering.max_seats,
    )
    await audit_log_service.record(
        db,
        actor_user_id=None,
        actor_role=None,
        action=AuditAction.UPDATED,
        entity_type="CourseOffering",
        entity_id=offering_id,
        entity_label=f"seat booked ({offering.booked_seats}/{offering.max_seats})",
        institution_id=offering.institution_id if hasattr(offering, "institution_id") else None,
        after={"booked_seats": offering.booked_seats, "max_seats": offering.max_seats},
    )
    return offering


async def release_seat(
    db: AsyncSession, offering_id: uuid.UUID
) -> CourseOffering:
    """
    Atomically decrement booked_seats when a student drops a registration.

    Uses SELECT FOR UPDATE to maintain counter integrity.
    Does not go below 0.
    """
    result = await db.execute(
        select(CourseOffering)
        .where(CourseOffering.id == offering_id)
        .with_for_update()
    )
    offering = result.scalars().first()
    if offering is None:
        raise NotFoundError(f"CourseOffering {offering_id} not found")

    if offering.booked_seats > 0:
        offering.booked_seats -= 1

    await db.flush()

    # Sync Redis cache with new seat availability
    from app.core.redis_client import get_async_redis
    redis_client = get_async_redis()
    seats_key = f"offering:seats:{offering_id}"
    try:
        eff_max = offering.max_seats
        if eff_max is None and offering.bucket_id:
            from app.models.curriculum import OfferingBucket
            bucket = await db.get(OfferingBucket, offering.bucket_id)
            if bucket:
                from app.services.hybrid_selection_service import _resolve_effective_max_seats
                eff_max = await _resolve_effective_max_seats(
                    db,
                    institution_id=bucket.institution_id,
                    academic_term_id=bucket.academic_term_id,
                    department_id=bucket.department_id,
                )
        if eff_max is not None:
            seats_left = eff_max - offering.booked_seats
            await redis_client.set(seats_key, seats_left, ex=3600)
        else:
            seats_left = 10_000 - offering.booked_seats
            await redis_client.set(seats_key, seats_left, ex=3600)
    except Exception as e:
        logger.warning("Redis release seat count error", error=str(e))
    finally:
        await redis_client.aclose()

    logger.info(
        "Seat released",
        offering_id=str(offering_id),
        booked=offering.booked_seats,
    )
    await audit_log_service.record(
        db,
        actor_user_id=None,
        actor_role=None,
        action=AuditAction.UPDATED,
        entity_type="CourseOffering",
        entity_id=offering_id,
        entity_label=f"seat released ({offering.booked_seats}/{offering.max_seats})",
        institution_id=offering.institution_id if hasattr(offering, "institution_id") else None,
        after={"booked_seats": offering.booked_seats, "max_seats": offering.max_seats},
    )
    return offering


# ---------------------------------------------------------------------------
# TargetRequirement  (M2M join)
# ---------------------------------------------------------------------------


async def list_requirements(
    db: AsyncSession,
    target_id: uuid.UUID,
) -> list[TargetRequirement]:
    """Return all bucket requirements for a scheduling target."""
    result = await db.execute(
        select(TargetRequirement)
        .where(TargetRequirement.target_id == target_id)
        .order_by(TargetRequirement.created_at)
    )
    return list(result.scalars().all())


async def add_requirement(
    db: AsyncSession,
    payload: TargetRequirementCreate,
) -> TargetRequirement:
    """
    Link a SchedulingTarget to an OfferingBucket.

    The DB has a unique constraint on (target_id, bucket_id) — raises
    ConflictError if the link already exists.
    """
    existing = await db.execute(
        select(TargetRequirement).where(
            TargetRequirement.target_id == payload.target_id,
            TargetRequirement.bucket_id == payload.bucket_id,
        )
    )
    if existing.scalars().first() is not None:
        raise ConflictError(
            f"TargetRequirement already exists for target={payload.target_id} "
            f"bucket={payload.bucket_id}"
        )

    req = TargetRequirement(**payload.model_dump())
    db.add(req)
    await db.flush()
    logger.info(
        "TargetRequirement added",
        req_id=str(req.id),
        target_id=str(payload.target_id),
        bucket_id=str(payload.bucket_id),
    )
    return req


async def remove_requirement(
    db: AsyncSession,
    requirement_id: uuid.UUID,
) -> None:
    """Hard-delete a target→bucket requirement link."""
    result = await db.execute(
        select(TargetRequirement).where(TargetRequirement.id == requirement_id)
    )
    req = result.scalars().first()
    if req is None:
        raise NotFoundError(f"TargetRequirement {requirement_id} not found")
    await db.delete(req)
    await db.flush()
    logger.info("TargetRequirement removed", req_id=str(requirement_id))


async def list_children(
    db: AsyncSession,
    cohort_id: uuid.UUID,
) -> list[SchedulingTarget]:
    """Return all BATCH children of a COHORT target."""
    result = await db.execute(
        select(SchedulingTarget)
        .where(SchedulingTarget.parent_id == cohort_id)
        .order_by(SchedulingTarget.name)
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# COHORT helpers (used by cohort_service)
# ---------------------------------------------------------------------------


def _resolve_class_size(dept: Optional[object], institution: Optional[object]) -> Optional[int]:
    """
    Resolution chain: dept.class_size > institution.default_class_size.
    Returns None if neither is set.
    """
    if dept is not None:
        val = getattr(dept, "class_size", None)
        if val is not None:
            return val
    if institution is not None:
        val = getattr(institution, "default_class_size", None)
        if val is not None:
            return val
    return None


def _label(index: int) -> str:
    """
    Convert 0-based index to alphabetic label.
    0→'A', 1→'B', ..., 25→'Z', 26→'AA', 27→'AB', etc.
    """
    result = ""
    n = index
    while True:
        result = chr(ord("A") + (n % 26)) + result
        n = n // 26 - 1
        if n < 0:
            break
    return result
