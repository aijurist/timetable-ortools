"""
curriculum.py
=============
Curriculum & demand layer CRUD — SchedulingTarget, OfferingBucket,
CourseOffering, and TargetRequirement.

Scheduling Targets router  (prefix /scheduling-targets)
--------------------------------------------------------
GET    /scheduling-targets                         List targets (filterable)
POST   /scheduling-targets                         Create a target
GET    /scheduling-targets/{id}                    Get a target
PATCH  /scheduling-targets/{id}                    Update a target
DELETE /scheduling-targets/{id}                    Soft-delete a target
GET    /scheduling-targets/{id}/requirements       List bucket requirements for a target
POST   /scheduling-targets/{id}/requirements       Add a bucket requirement
DELETE /scheduling-targets/requirements/{req_id}   Remove a requirement

Offering Buckets router  (prefix /offering-buckets)
----------------------------------------------------
GET    /offering-buckets                           List buckets (filterable)
POST   /offering-buckets                           Create a bucket
GET    /offering-buckets/offerings                  List all offerings (bulk, filterable)
GET    /offering-buckets/{id}                      Get a bucket
PATCH  /offering-buckets/{id}                      Update a bucket
DELETE /offering-buckets/{id}                      Soft-delete a bucket
GET    /offering-buckets/{id}/offerings            List offerings in a bucket

Course Offerings router  (prefix /course-offerings)
----------------------------------------------------
POST   /course-offerings                           Create an offering
GET    /course-offerings/{id}                      Get an offering
PATCH  /course-offerings/{id}                      Update an offering (incl. solver writes)
POST   /course-offerings/{id}/freeze               Freeze offering (block new registrations)
POST   /course-offerings/{id}/book-seat            FFCS Phase 2 — atomic seat increment
POST   /course-offerings/{id}/release-seat         FFCS Phase 2 — atomic seat decrement
"""
from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import (
    CurrentUser,
    PaginationParams,
    get_current_user,
    get_db,
    get_pagination,
    require_hod,
    assert_same_institution,
)
from app.core.exceptions import ValidationError
from app.models.curriculum import TargetType
from app.schemas.curriculum import (
    CohortSetupResponse,
    CourseOfferingCreate,
    CourseOfferingListResponse,
    CourseOfferingResponse,
    CourseOfferingUpdate,
    OfferingBucketCreate,
    OfferingBucketListResponse,
    OfferingBucketResponse,
    OfferingBucketUpdate,
    SchedulingTargetCreate,
    SchedulingTargetListResponse,
    SchedulingTargetResponse,
    SchedulingTargetUpdate,
    TargetRequirementCreate,
    TargetRequirementListResponse,
    TargetRequirementResponse,
)
import app.services.curriculum_service as curriculum_svc
import app.services.scenario_service as scenario_svc
import app.services.selection_monitor_service as monitor_svc

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

targets_router = APIRouter()
buckets_router = APIRouter()
offerings_router = APIRouter()


# ===========================================================================
# Scheduling Targets
# ===========================================================================


@targets_router.get(
    "",
    response_model=SchedulingTargetListResponse,
    summary="List scheduling targets",
)
async def list_targets(
    institution_id: Optional[uuid.UUID] = Query(default=None),
    academic_term_id: Optional[uuid.UUID] = Query(default=None),
    department_id: Optional[uuid.UUID] = Query(default=None),
    target_type: Optional[str] = Query(default=None, description="Filter by type: BATCH, COHORT, CLUSTER, VIRTUAL"),
    parent_id: Optional[uuid.UUID] = Query(default=None, description="Filter BATCH children by COHORT parent"),
    scenario_id: Optional[uuid.UUID] = Query(default=None, description="Filter by scenario (returns only that scenario's targets)"),
    active_only: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
    pagination: PaginationParams = Depends(get_pagination),
    current_user: CurrentUser = Depends(get_current_user),
) -> SchedulingTargetListResponse:
    if institution_id is not None:
        assert_same_institution(current_user, institution_id)
    elif not current_user.is_super_admin and current_user.institution_id:
        import uuid as _uuid
        institution_id = _uuid.UUID(current_user.institution_id)
    items = await curriculum_svc.list_targets(
        db,
        institution_id=institution_id,
        academic_term_id=academic_term_id,
        department_id=department_id,
        target_type=target_type,
        parent_id=parent_id,
        scenario_id=scenario_id,
        active_only=active_only,
        skip=pagination.skip,
        limit=pagination.limit,
    )
    return SchedulingTargetListResponse(
        items=[SchedulingTargetResponse.model_validate(t) for t in items],
        total=len(items),
        skip=pagination.skip,
        limit=pagination.limit,
    )


@targets_router.post(
    "",
    response_model=None,   # dynamic: SchedulingTargetResponse or CohortSetupResponse
    status_code=status.HTTP_201_CREATED,
    summary="Create a scheduling target (batch / program group / COHORT intake)",
)
async def create_target(
    payload: SchedulingTargetCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
):
    result = await curriculum_svc.create_target(db, payload)

    if payload.scenario_id:
        await scenario_svc.mark_dirty(db, payload.scenario_id)

    await db.commit()

    # COHORT returns CohortSetupResponse (already built — no ORM refresh needed)
    if payload.target_type == TargetType.COHORT:
        return result

    # Regular BATCH / CLUSTER / VIRTUAL
    await db.refresh(result)
    return SchedulingTargetResponse.model_validate(result)


@targets_router.get(
    "/{target_id}",
    response_model=SchedulingTargetResponse,
    summary="Get a scheduling target",
)
async def get_target(
    target_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> SchedulingTargetResponse:
    target = await curriculum_svc.get_target_or_404(db, target_id)
    assert_same_institution(current_user, target.institution_id)
    return SchedulingTargetResponse.model_validate(target)


@targets_router.patch(
    "/{target_id}",
    response_model=SchedulingTargetResponse,
    summary="Update a scheduling target",
)
async def update_target(
    target_id: uuid.UUID,
    payload: SchedulingTargetUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> SchedulingTargetResponse:
    existing = await curriculum_svc.get_target_or_404(db, target_id)
    assert_same_institution(current_user, existing.institution_id)
    target = await curriculum_svc.update_target(db, target_id, payload)
    await db.commit()
    await db.refresh(target)
    return SchedulingTargetResponse.model_validate(target)


@targets_router.delete(
    "/{target_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
    summary="Hard-delete a scheduling target; COHORT deletes cascade to batches, buckets, and offerings",
)
async def delete_target(
    target_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> None:
    target = await curriculum_svc.get_target_or_404(db, target_id)
    assert_same_institution(current_user, target.institution_id)
    if target.target_type == TargetType.COHORT:
        await curriculum_svc.delete_cohort_cascade(db, target_id)
    else:
        await db.delete(target)
        await db.flush()
    await db.commit()
    return None


@targets_router.get(
    "/{target_id}/children",
    response_model=List[SchedulingTargetResponse],
    summary="List BATCH children of a COHORT target",
)
async def list_children(
    target_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> List[SchedulingTargetResponse]:
    children = await curriculum_svc.list_children(db, target_id)
    return [SchedulingTargetResponse.model_validate(c) for c in children]


# ---------------------------------------------------------------------------
# Target Requirements (bucket assignments) — nested under target
# ---------------------------------------------------------------------------


@targets_router.get(
    "/{target_id}/requirements",
    response_model=TargetRequirementListResponse,
    summary="List offering bucket requirements for a scheduling target",
)
async def list_requirements(
    target_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> TargetRequirementListResponse:
    items = await curriculum_svc.list_requirements(db, target_id)
    return TargetRequirementListResponse(
        items=[TargetRequirementResponse.model_validate(r) for r in items],
        total=len(items),
        skip=0,
        limit=len(items),
    )


@targets_router.post(
    "/{target_id}/requirements",
    response_model=TargetRequirementResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a bucket requirement to a scheduling target",
)
async def add_requirement(
    target_id: uuid.UUID,
    payload: TargetRequirementCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> TargetRequirementResponse:
    req = await curriculum_svc.add_requirement(db, payload)
    await db.commit()
    await db.refresh(req)
    return TargetRequirementResponse.model_validate(req)


@targets_router.delete(
    "/requirements/{requirement_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
    summary="Remove a bucket requirement from a scheduling target",
)
async def remove_requirement(
    requirement_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> None:
    await curriculum_svc.remove_requirement(db, requirement_id)
    await db.commit()
    return None


# ===========================================================================
# Offering Buckets
# ===========================================================================


@buckets_router.get(
    "",
    response_model=OfferingBucketListResponse,
    summary="List offering buckets",
)
async def list_buckets(
    institution_id: Optional[uuid.UUID] = Query(default=None),
    academic_term_id: Optional[uuid.UUID] = Query(default=None),
    department_id: Optional[uuid.UUID] = Query(default=None),
    scenario_id: Optional[uuid.UUID] = Query(default=None, description="Filter by scenario (returns only that scenario's buckets)"),
    active_only: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
    pagination: PaginationParams = Depends(get_pagination),
    current_user: CurrentUser = Depends(get_current_user),
) -> OfferingBucketListResponse:
    if institution_id is not None:
        assert_same_institution(current_user, institution_id)
    elif not current_user.is_super_admin and current_user.institution_id:
        import uuid as _uuid
        institution_id = _uuid.UUID(current_user.institution_id)
    items = await curriculum_svc.list_buckets(
        db,
        institution_id=institution_id,
        academic_term_id=academic_term_id,
        department_id=department_id,
        scenario_id=scenario_id,
        active_only=active_only,
        skip=pagination.skip,
        limit=pagination.limit,
    )
    return OfferingBucketListResponse(
        items=[OfferingBucketResponse.model_validate(b) for b in items],
        total=len(items),
        skip=pagination.skip,
        limit=pagination.limit,
    )


@buckets_router.get(
    "/offerings",
    response_model=CourseOfferingListResponse,
    summary="List all course offerings for matching buckets (bulk)",
)
async def list_offerings_bulk(
    institution_id: Optional[uuid.UUID] = Query(default=None),
    academic_term_id: Optional[uuid.UUID] = Query(default=None),
    department_id: Optional[uuid.UUID] = Query(default=None),
    scenario_id: Optional[uuid.UUID] = Query(
        default=None,
        description="Filter by scenario (returns offerings in that scenario's buckets)",
    ),
    active_only: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
    pagination: PaginationParams = Depends(get_pagination),
    current_user: CurrentUser = Depends(get_current_user),
) -> CourseOfferingListResponse:
    if institution_id is not None:
        assert_same_institution(current_user, institution_id)
    elif not current_user.is_super_admin and current_user.institution_id:
        import uuid as _uuid

        institution_id = _uuid.UUID(current_user.institution_id)
    if institution_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="institution_id is required",
        )
    items = await curriculum_svc.list_offerings_for_buckets(
        db,
        institution_id,
        academic_term_id=academic_term_id,
        department_id=department_id,
        scenario_id=scenario_id,
        active_only=active_only,
        skip=pagination.skip,
        limit=pagination.limit,
    )
    enriched = await curriculum_svc.enrich_offerings(db, items)
    return CourseOfferingListResponse(
        items=enriched,
        total=len(enriched),
        skip=pagination.skip,
        limit=pagination.limit,
    )


@buckets_router.post(
    "",
    response_model=OfferingBucketResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an offering bucket",
)
async def create_bucket(
    payload: OfferingBucketCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> OfferingBucketResponse:
    bucket = await curriculum_svc.create_bucket(db, payload)
    await db.commit()
    await db.refresh(bucket)
    return OfferingBucketResponse.model_validate(bucket)


@buckets_router.get(
    "/{bucket_id}",
    response_model=OfferingBucketResponse,
    summary="Get an offering bucket",
)
async def get_bucket(
    bucket_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> OfferingBucketResponse:
    bucket = await curriculum_svc.get_bucket_or_404(db, bucket_id)
    assert_same_institution(current_user, bucket.institution_id)
    return OfferingBucketResponse.model_validate(bucket)


@buckets_router.patch(
    "/{bucket_id}",
    response_model=OfferingBucketResponse,
    summary="Update an offering bucket",
)
async def update_bucket(
    bucket_id: uuid.UUID,
    payload: OfferingBucketUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> OfferingBucketResponse:
    existing = await curriculum_svc.get_bucket_or_404(db, bucket_id)
    assert_same_institution(current_user, existing.institution_id)
    bucket = await curriculum_svc.update_bucket(db, bucket_id, payload)
    await db.commit()
    await db.refresh(bucket)
    return OfferingBucketResponse.model_validate(bucket)


@buckets_router.delete(
    "/{bucket_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
    summary="Soft-delete an offering bucket (sets is_active=False)",
)
async def delete_bucket(
    bucket_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> None:
    existing = await curriculum_svc.get_bucket_or_404(db, bucket_id)
    assert_same_institution(current_user, existing.institution_id)
    await curriculum_svc.soft_delete_bucket(db, bucket_id)
    await db.commit()
    return None


@buckets_router.get(
    "/{bucket_id}/offerings",
    response_model=CourseOfferingListResponse,
    summary="List course offerings in a bucket",
)
async def list_offerings_by_bucket(
    bucket_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    pagination: PaginationParams = Depends(get_pagination),
    current_user: CurrentUser = Depends(get_current_user),
) -> CourseOfferingListResponse:
    items = await curriculum_svc.list_offerings(db, bucket_id, skip=pagination.skip, limit=pagination.limit)
    enriched = await curriculum_svc.enrich_offerings(db, items)
    return CourseOfferingListResponse(
        items=enriched,
        total=len(enriched),
        skip=pagination.skip,
        limit=pagination.limit,
    )


# ===========================================================================
# Course Offerings
# ===========================================================================


@offerings_router.post(
    "",
    response_model=CourseOfferingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a course offering",
)
async def create_offering(
    payload: CourseOfferingCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> CourseOfferingResponse:
    offering = await curriculum_svc.create_offering(db, payload)
    await db.commit()
    await db.refresh(offering)
    return CourseOfferingResponse.model_validate(offering)


@offerings_router.get(
    "/{offering_id}",
    response_model=CourseOfferingResponse,
    summary="Get a course offering",
)
async def get_offering(
    offering_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> CourseOfferingResponse:
    offering = await curriculum_svc.get_offering_or_404(db, offering_id)
    assert_same_institution(current_user, offering.institution_id)
    return CourseOfferingResponse.model_validate(offering)


@offerings_router.patch(
    "/{offering_id}",
    response_model=CourseOfferingResponse,
    summary="Update a course offering (also used by solver to write slot_code / room_id)",
)
async def update_offering(
    offering_id: uuid.UUID,
    payload: CourseOfferingUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> CourseOfferingResponse:
    existing = await curriculum_svc.get_offering_or_404(db, offering_id)
    bucket = await curriculum_svc.get_bucket_or_404(db, existing.bucket_id)
    assert_same_institution(current_user, bucket.institution_id)
    seat_fields = {"max_seats", "is_frozen", "booked_seats"}
    touches_seats = bool(seat_fields & payload.model_dump(exclude_unset=True).keys())
    try:
        offering = await curriculum_svc.update_offering(db, offering_id, payload)
        await db.commit()
        await db.refresh(offering)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if touches_seats:
        await monitor_svc.sync_offering_seats_after_admin_update(db, offering)
    return CourseOfferingResponse.model_validate(offering)


@offerings_router.post(
    "/{offering_id}/freeze",
    response_model=CourseOfferingResponse,
    summary="Freeze a course offering — blocks new FFCS registrations",
)
async def freeze_offering(
    offering_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> CourseOfferingResponse:
    existing = await curriculum_svc.get_offering_or_404(db, offering_id)
    bucket = await curriculum_svc.get_bucket_or_404(db, existing.bucket_id)
    assert_same_institution(current_user, bucket.institution_id)
    offering = await curriculum_svc.freeze_offering(db, offering_id, frozen=True)
    await db.commit()
    await db.refresh(offering)
    await monitor_svc.sync_offering_seats_after_admin_update(db, offering)
    return CourseOfferingResponse.model_validate(offering)


@offerings_router.post(
    "/{offering_id}/book-seat",
    response_model=CourseOfferingResponse,
    summary="FFCS Phase 2 — atomically increment booked_seats (SELECT FOR UPDATE)",
)
async def book_seat(
    offering_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> CourseOfferingResponse:
    """
    Raises 409 if the offering is frozen or booked_seats >= max_seats.
    Uses SELECT FOR UPDATE to prevent race conditions under high load.
    """
    offering = await curriculum_svc.book_seat(db, offering_id)
    await db.commit()
    await db.refresh(offering)
    return CourseOfferingResponse.model_validate(offering)


@offerings_router.post(
    "/{offering_id}/release-seat",
    response_model=CourseOfferingResponse,
    summary="FFCS Phase 2 — atomically decrement booked_seats (SELECT FOR UPDATE)",
)
async def release_seat(
    offering_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> CourseOfferingResponse:
    """
    Decrements booked_seats — floor is 0 (never goes negative).
    Uses SELECT FOR UPDATE to prevent race conditions.
    """
    offering = await curriculum_svc.release_seat(db, offering_id)
    await db.commit()
    await db.refresh(offering)
    return CourseOfferingResponse.model_validate(offering)


# ===========================================================================
# Course Share Configs  (admin-only; prefix /course-share-configs)
# ===========================================================================

from app.schemas.curriculum import (  # noqa: E402
    CourseShareConfigCreate,
    CourseShareConfigListResponse,
    CourseShareConfigResponse,
    CourseShareConfigUpdate,
)

share_configs_router = APIRouter()


@share_configs_router.get(
    "",
    response_model=CourseShareConfigListResponse,
    summary="List course share configs",
)
async def list_share_configs(
    institution_id: Optional[uuid.UUID] = Query(default=None),
    academic_term_id: Optional[uuid.UUID] = Query(default=None),
    course_id: Optional[uuid.UUID] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    pagination: PaginationParams = Depends(get_pagination),
    current_user: CurrentUser = Depends(get_current_user),
) -> CourseShareConfigListResponse:
    from sqlalchemy import select as _select
    from app.models.curriculum import CourseShareConfig
    q = _select(CourseShareConfig)
    if institution_id is not None:
        q = q.where(CourseShareConfig.institution_id == institution_id)
    if academic_term_id is not None:
        q = q.where(CourseShareConfig.academic_term_id == academic_term_id)
    if course_id is not None:
        q = q.where(CourseShareConfig.course_id == course_id)
    q = q.offset(pagination.skip).limit(pagination.limit)
    result = await db.execute(q)
    items = list(result.scalars().all())
    return CourseShareConfigListResponse(
        items=[CourseShareConfigResponse.model_validate(c) for c in items],
        total=len(items),
        skip=pagination.skip,
        limit=pagination.limit,
    )


@share_configs_router.post(
    "",
    response_model=CourseShareConfigResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a course share config (admin only)",
)
async def create_share_config(
    payload: CourseShareConfigCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> CourseShareConfigResponse:
    from app.models.curriculum import CourseShareConfig
    cfg = CourseShareConfig(**payload.model_dump())
    db.add(cfg)
    await db.flush()
    await db.commit()
    await db.refresh(cfg)
    return CourseShareConfigResponse.model_validate(cfg)


@share_configs_router.patch(
    "/{config_id}",
    response_model=CourseShareConfigResponse,
    summary="Update a course share config",
)
async def update_share_config(
    config_id: uuid.UUID,
    payload: CourseShareConfigUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> CourseShareConfigResponse:
    from sqlalchemy import select as _select
    from app.models.curriculum import CourseShareConfig
    from app.core.exceptions import NotFoundError
    result = await db.execute(_select(CourseShareConfig).where(CourseShareConfig.id == config_id))
    cfg = result.scalar_one_or_none()
    if cfg is None:
        raise NotFoundError(f"CourseShareConfig {config_id} not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(cfg, field, value)
    await db.flush()
    await db.commit()
    await db.refresh(cfg)
    return CourseShareConfigResponse.model_validate(cfg)


@share_configs_router.delete(
    "/{config_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
    summary="Delete a course share config",
)
async def delete_share_config(
    config_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> None:
    from sqlalchemy import select as _select
    from app.models.curriculum import CourseShareConfig
    from app.core.exceptions import NotFoundError
    result = await db.execute(_select(CourseShareConfig).where(CourseShareConfig.id == config_id))
    cfg = result.scalar_one_or_none()
    if cfg is None:
        raise NotFoundError(f"CourseShareConfig {config_id} not found")
    await db.delete(cfg)
    await db.commit()
    return None
