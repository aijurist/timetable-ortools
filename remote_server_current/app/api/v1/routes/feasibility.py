"""
Feasibility check endpoint.

GET  /scenarios/{scenario_id}/feasibility
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Any, Literal

from app.api.v1.deps import CurrentUser, assert_same_institution, get_current_user, get_db
import app.services.scenario_service as scenario_svc
from app.services.feasibility_checker import run_feasibility_check, FeasibilityReport, FeasibilityIssue

router = APIRouter()


class FeasibilityIssueOut(BaseModel):
    severity: Literal["ERROR", "WARNING"]
    code: str
    message: str
    entity: str | None = None
    detail: dict = {}


class FeasibilityReportOut(BaseModel):
    feasible: bool
    issues: list[FeasibilityIssueOut]
    summary: dict[str, Any] = {}


@router.get(
    "/scenarios/{scenario_id}/feasibility",
    response_model=FeasibilityReportOut,
    summary="Run pre-solve feasibility check",
)
async def get_feasibility(
    scenario_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> FeasibilityReportOut:
    scenario = await scenario_svc.get_or_404(db, scenario_id)
    assert_same_institution(current_user, scenario.institution_id)
    report = await run_feasibility_check(db, scenario)
    return FeasibilityReportOut(
        feasible=report.feasible,
        issues=[
            FeasibilityIssueOut(
                severity=issue.severity,
                code=issue.code,
                message=issue.message,
                entity=issue.entity,
                detail=issue.detail,
            )
            for issue in report.issues
        ],
        summary=report.summary,
    )
