"""
department_plans.py
====================
HOD → Admin plan submission workflow endpoints.

Routes (prefix: none — flat under /api/v1/)
-------------------------------------------
GET  /department-plans/{term_id}/{dept_id}              → plan status    [hod+]
POST /department-plans/{term_id}/{dept_id}/submit       → HOD submits    [hod+]
POST /department-plans/{term_id}/{dept_id}/recall       → HOD recalls    [hod+]
GET  /department-plans/{term_id}/{dept_id}/export/csv   → CSV download   [hod+]
GET  /department-plans/{term_id}/{dept_id}/export/html  → HTML print     [hod+]
GET  /department-plans/{term_id}/{dept_id}/export/excel → Excel download [hod+]

GET  /department-plans/admin/overview                   → all dept statuses [admin]
GET  /department-plans/admin/export/excel               → all-dept workbook [admin]
POST /department-plans/{term_id}/{dept_id}/approve      → Admin approves    [admin]
POST /department-plans/{term_id}/{dept_id}/send-back    → Admin sends back  [admin]
POST /department-plans/{term_id}/{dept_id}/unpublish    → Admin unpublishes [admin]
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import CurrentUser, get_db, require_admin, require_hod
from app.models.department_plan import PlanStatus

import app.services.department_plan_service as plan_svc

router = APIRouter()


def _resolve_institution_id(current_user: CurrentUser) -> uuid.UUID:
    if not current_user.institution_id:
        raise HTTPException(
            status_code=403,
            detail="This endpoint requires an institution-scoped account.",
        )
    return uuid.UUID(current_user.institution_id)


def _plan_to_dict(plan: Any | None, dept_id: uuid.UUID, term_id: uuid.UUID) -> dict:
    if plan is None:
        return {
            "status": PlanStatus.DRAFT.value,
            "submitted_at": None,
            "approved_at": None,
            "sent_back_at": None,
            "sent_back_reason": None,
        }
    return {
        "id": str(plan.id),
        "department_id": str(dept_id),
        "academic_term_id": str(term_id),
        "status": plan.status.value,
        "submitted_at": plan.submitted_at.isoformat() if plan.submitted_at else None,
        "submitted_by_user_id": str(plan.submitted_by_user_id) if plan.submitted_by_user_id else None,
        "approved_at": plan.approved_at.isoformat() if plan.approved_at else None,
        "approved_by_user_id": str(plan.approved_by_user_id) if plan.approved_by_user_id else None,
        "sent_back_at": plan.sent_back_at.isoformat() if plan.sent_back_at else None,
        "sent_back_reason": plan.sent_back_reason,
    }


# ---------------------------------------------------------------------------
# Admin-only — declared FIRST so /admin/overview is not swallowed by /{term_id}/{dept_id}
# ---------------------------------------------------------------------------


@router.get("/department-plans/admin/overview")
async def get_admin_plan_overview(
    term_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin),
) -> list[dict]:
    return await plan_svc.get_institution_overview(
        db,
        institution_id=_resolve_institution_id(current_user),
        academic_term_id=term_id,
    )


@router.get("/department-plans/admin/export/excel")
async def export_all_depts_excel(
    term_id: uuid.UUID = Query(...),
    semester: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin),
) -> Response:
    """Download an Excel workbook with one sheet per department + a Summary sheet."""
    xlsx = await plan_svc.export_all_depts_excel(
        db,
        institution_id=_resolve_institution_id(current_user),
        academic_term_id=term_id,
        semester_filter=semester,
    )
    return Response(
        content=xlsx,
        media_type=plan_svc._XLSX_MIME,
        headers={"Content-Disposition": "attachment; filename=teaching_plan_all_depts.xlsx"},
    )


class SendBackBody(BaseModel):
    reason: str | None = None


@router.post("/department-plans/{term_id}/{dept_id}/approve")
async def approve_dept_plan(
    term_id: uuid.UUID,
    dept_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin),
) -> dict:
    plan = await plan_svc.approve_plan(
        db,
        institution_id=_resolve_institution_id(current_user),
        academic_term_id=term_id,
        department_id=dept_id,
        actor_user_id=current_user.user_uuid,
        actor_role=current_user.role.value,
    )
    await db.commit()
    return _plan_to_dict(plan, dept_id, term_id)


@router.post("/department-plans/{term_id}/{dept_id}/send-back")
async def send_back_dept_plan(
    term_id: uuid.UUID,
    dept_id: uuid.UUID,
    body: SendBackBody = SendBackBody(),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin),
) -> dict:
    reason: str | None = body.reason
    plan = await plan_svc.send_back_plan(
        db,
        institution_id=_resolve_institution_id(current_user),
        academic_term_id=term_id,
        department_id=dept_id,
        actor_user_id=current_user.user_uuid,
        reason=reason,
        actor_role=current_user.role.value,
    )
    await db.commit()
    return _plan_to_dict(plan, dept_id, term_id)


@router.post("/department-plans/{term_id}/{dept_id}/unpublish")
async def unpublish_dept_plan(
    term_id: uuid.UUID,
    dept_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin),
) -> dict:
    plan = await plan_svc.admin_unpublish_plan(
        db,
        institution_id=_resolve_institution_id(current_user),
        academic_term_id=term_id,
        department_id=dept_id,
        actor_user_id=current_user.user_uuid,
        actor_role=current_user.role.value,
    )
    await db.commit()
    return _plan_to_dict(plan, dept_id, term_id)


# ---------------------------------------------------------------------------
# HOD + Admin shared — path-param routes declared AFTER static /admin/overview
# ---------------------------------------------------------------------------


@router.post("/department-plans/{term_id}/{dept_id}/recall")
async def recall_dept_plan(
    term_id: uuid.UUID,
    dept_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> dict:
    plan = await plan_svc.hod_recall_plan(
        db,
        institution_id=_resolve_institution_id(current_user),
        academic_term_id=term_id,
        department_id=dept_id,
        actor_user_id=current_user.user_uuid,
        actor_role=current_user.role.value,
    )
    await db.commit()
    return _plan_to_dict(plan, dept_id, term_id)


@router.get("/department-plans/{term_id}/{dept_id}")
async def get_dept_plan_status(
    term_id: uuid.UUID,
    dept_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> dict:
    plan = await plan_svc.get_plan_status(
        db,
        institution_id=_resolve_institution_id(current_user),
        academic_term_id=term_id,
        department_id=dept_id,
    )
    return _plan_to_dict(plan, dept_id, term_id)


@router.post("/department-plans/{term_id}/{dept_id}/submit")
async def submit_dept_plan(
    term_id: uuid.UUID,
    dept_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> dict:
    result = await plan_svc.submit_plan(
        db,
        institution_id=_resolve_institution_id(current_user),
        academic_term_id=term_id,
        department_id=dept_id,
        actor_user_id=current_user.user_uuid,
        actor_role=current_user.role.value,
    )
    await db.commit()
    return result


@router.get("/department-plans/{term_id}/{dept_id}/export/csv")
async def export_plan_csv(
    term_id: uuid.UUID,
    dept_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> Response:
    csv_content = await plan_svc.export_plan_csv(
        db,
        institution_id=_resolve_institution_id(current_user),
        academic_term_id=term_id,
        department_id=dept_id,
    )
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=teaching_plan_{dept_id}.csv"},
    )


@router.get("/department-plans/{term_id}/{dept_id}/export/html", response_class=HTMLResponse)
async def export_plan_html(
    term_id: uuid.UUID,
    dept_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> str:
    return await plan_svc.export_plan_html(
        db,
        institution_id=_resolve_institution_id(current_user),
        academic_term_id=term_id,
        department_id=dept_id,
    )


@router.get("/department-plans/{term_id}/{dept_id}/export/excel")
async def export_plan_excel(
    term_id: uuid.UUID,
    dept_id: uuid.UUID,
    semester: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> Response:
    """Download an Excel (.xlsx) teaching plan for one department."""
    xlsx = await plan_svc.export_plan_excel(
        db,
        institution_id=_resolve_institution_id(current_user),
        academic_term_id=term_id,
        department_id=dept_id,
        semester_filter=semester,
    )
    return Response(
        content=xlsx,
        media_type=plan_svc._XLSX_MIME,
        headers={"Content-Disposition": f"attachment; filename=teaching_plan_{dept_id}.xlsx"},
    )

