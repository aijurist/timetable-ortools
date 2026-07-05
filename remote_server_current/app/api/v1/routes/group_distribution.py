"""
Group Distribution router — HYBRID/FFCS pre-solve group assignment.

POST   /group-distribution/run                    Run CP-SAT group optimizer for a cohort
GET    /group-distribution/{cohort_id}             Full group assignments (for GroupAssignmentsPanel)
PATCH  /group-distribution/{cohort_id}/assignments Manual override of specific offering→group mappings
GET    /group-distribution/{cohort_id}/status      Lightweight status check (polled by cohort card badge)
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user, get_db
import app.services.group_distribution_service as gd_svc

router = APIRouter()


# ---------------------------------------------------------------------------
# Dept-level distribution (all departments or a selected subset)
# ---------------------------------------------------------------------------


class CohortDistributeItem(BaseModel):
    department_id: uuid.UUID
    name: str
    size: int
    class_count: int | None = None
    study_semester: int | None = None


class CohortDistributeRequest(BaseModel):
    scenario_id: uuid.UUID
    institution_id: uuid.UUID
    academic_term_id: uuid.UUID
    scheduling_mode: str | None = None
    # Per-department specs. Empty → every active department (server fills defaults).
    items: list[CohortDistributeItem] = Field(default_factory=list)


class CohortDistributeResultItem(BaseModel):
    department_id: str
    name: str
    status: str  # "done" | "error"
    buckets_created: int = 0
    offerings_created: int = 0
    tba_offerings_created: int = 0
    class_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None


class CohortDistributeResponse(BaseModel):
    results: list[CohortDistributeResultItem]
    created: int
    failed: int


@router.post(
    "/cohorts/distribute",
    response_model=CohortDistributeResponse,
    status_code=status.HTTP_200_OK,
    summary="Create + distribute cohorts for all (or selected) departments in one call",
    tags=["group-distribution"],
)
async def distribute_cohorts(
    body: CohortDistributeRequest,
    db: AsyncSession = Depends(get_db),
    _: Any = Depends(get_current_user),
) -> CohortDistributeResponse:
    import app.services.curriculum_service as curriculum_svc
    import app.services.scenario_service as scenario_svc
    from app.models.curriculum import TargetType
    from app.models.institution import Department
    from app.schemas.curriculum import CohortSetupResponse, SchedulingTargetCreate
    from sqlalchemy import select as _select

    items = list(body.items)
    if not items:
        # No explicit specs → one cohort per active department, sized by class_size.
        depts = (await db.execute(
            _select(Department).where(
                Department.institution_id == body.institution_id,
                Department.is_active == True,  # noqa: E712
            )
        )).scalars().all()
        items = [
            CohortDistributeItem(
                department_id=d.id,
                name=d.name,
                size=getattr(d, "class_size", None) or 60,
            )
            for d in depts
        ]

    results: list[CohortDistributeResultItem] = []
    created = 0
    failed = 0
    for item in items:
        payload = SchedulingTargetCreate(
            institution_id=body.institution_id,
            academic_term_id=body.academic_term_id,
            name=item.name,
            target_type=TargetType.COHORT,
            size=item.size,
            department_id=item.department_id,
            class_count=item.class_count,
            study_semester=item.study_semester,
            scenario_id=body.scenario_id,
            scheduling_mode=body.scheduling_mode,
            extra_data=None,
            allowed_shifts=None,
        )
        try:
            res = await curriculum_svc.create_target(db, payload)
            await scenario_svc.mark_dirty(db, body.scenario_id)
            await db.commit()
            r = res if isinstance(res, CohortSetupResponse) else None
            results.append(CohortDistributeResultItem(
                department_id=str(item.department_id),
                name=item.name,
                status="done",
                buckets_created=r.buckets_created if r else 0,
                offerings_created=r.offerings_created if r else 0,
                tba_offerings_created=r.tba_offerings_created if r else 0,
                class_count=r.class_count if r else 0,
                warnings=r.warnings if r else [],
            ))
            created += 1
        except Exception as exc:  # noqa: BLE001 — per-dept isolation
            await db.rollback()
            results.append(CohortDistributeResultItem(
                department_id=str(item.department_id),
                name=item.name,
                status="error",
                error=str(exc),
            ))
            failed += 1

    return CohortDistributeResponse(results=results, created=created, failed=failed)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class GroupDistributionRunRequest(BaseModel):
    cohort_id: uuid.UUID
    scenario_id: uuid.UUID
    force_rerun: bool = False
    params_override: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Optional per-run param overrides (not persisted). "
            "Keys: lab_priority, consolidation_objective, max_groups_per_course, "
            "min_groups_per_course, timeout_seconds, fixed_group_assignments."
        ),
    )


class GroupDistributionRunResponse(BaseModel):
    num_groups: int
    target_group_size: int
    status: str
    warnings: list[str]
    offerings_updated: int


class OfferingInGroup(BaseModel):
    offering_id: str
    course_code: str
    course_name: str
    faculty_id: str | None
    faculty_name: str
    has_lab: bool


class GroupEntry(BaseModel):
    group_number: int | None
    group_label: str | None = None
    study_semester: int | None = None
    selection_policy: str | None = None
    force_parallel_slots: bool = False
    offerings: list[OfferingInGroup]


class GroupAssignmentsOverrideRequest(BaseModel):
    overrides: dict[str, int] = Field(
        description="Map of offering_id (str) → new_group_number (int, 1-based)."
    )


class GroupAssignmentsOverrideResponse(BaseModel):
    updated: int


class GroupDistributionStatusResponse(BaseModel):
    status: str
    num_groups: int
    offerings_total: int
    offerings_distributed: int
    warnings: list[str]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/group-distribution/run",
    response_model=GroupDistributionRunResponse,
    status_code=status.HTTP_200_OK,
    summary="Run CP-SAT group distribution for a HYBRID/FFCS cohort",
    tags=["group-distribution"],
)
async def run_group_distribution(
    body: GroupDistributionRunRequest,
    db: AsyncSession = Depends(get_db),
    _: Any = Depends(get_current_user),
) -> GroupDistributionRunResponse:
    result = await gd_svc.run_group_distribution(
        db=db,
        cohort_id=body.cohort_id,
        scenario_id=body.scenario_id,
        force_rerun=body.force_rerun,
        params_override=body.params_override,
    )
    await db.commit()
    return GroupDistributionRunResponse(
        num_groups=result.num_groups,
        target_group_size=result.target_group_size,
        status=result.status,
        warnings=result.warnings,
        offerings_updated=result.offerings_updated,
    )


@router.get(
    "/group-distribution/{cohort_id}",
    response_model=list[GroupEntry],
    summary="Get full group assignments for a cohort (GroupAssignmentsPanel)",
    tags=["group-distribution"],
)
async def get_group_distribution(
    cohort_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: Any = Depends(get_current_user),
) -> list[GroupEntry]:
    rows = await gd_svc.get_group_distribution(db=db, cohort_id=cohort_id)
    return [
        GroupEntry(
            group_number=r["group_number"],
            group_label=r.get("group_label"),
            study_semester=r.get("study_semester"),
            selection_policy=r.get("selection_policy"),
            force_parallel_slots=r.get("force_parallel_slots", False),
            offerings=[OfferingInGroup(**o) for o in r["offerings"]],
        )
        for r in rows
    ]


@router.patch(
    "/group-distribution/{cohort_id}/assignments",
    response_model=GroupAssignmentsOverrideResponse,
    summary="Manually override group assignments for specific offerings",
    tags=["group-distribution"],
)
async def update_group_assignments(
    cohort_id: uuid.UUID,
    body: GroupAssignmentsOverrideRequest,
    db: AsyncSession = Depends(get_db),
    _: Any = Depends(get_current_user),
) -> GroupAssignmentsOverrideResponse:
    updated = await gd_svc.update_group_assignments(
        db=db,
        cohort_id=cohort_id,
        overrides=body.overrides,
    )
    await db.commit()
    return GroupAssignmentsOverrideResponse(updated=updated)


@router.get(
    "/group-distribution/{cohort_id}/status",
    response_model=GroupDistributionStatusResponse,
    summary="Lightweight status check for cohort group distribution",
    tags=["group-distribution"],
)
async def get_group_distribution_status(
    cohort_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: Any = Depends(get_current_user),
) -> GroupDistributionStatusResponse:
    s = await gd_svc.get_group_distribution_status(db=db, cohort_id=cohort_id)
    return GroupDistributionStatusResponse(**s)
