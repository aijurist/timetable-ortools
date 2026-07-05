"""
users.py
========
Admin user management endpoints.

The /auth router handles self-service registration and login.
This router provides admin/HOD-facing user CRUD (list all users,
get/update any user by ID).

GET    /users              List users for an institution (filterable by role)
POST   /users              Create a user account (admin — bypasses self-registration)
GET    /users/{id}         Get a user
PATCH  /users/{id}         Update a user (role, department, active flag, etc.)
"""
from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import (
    CurrentUser,
    PaginationParams,
    get_db,
    get_pagination,
    require_admin,
    require_hod,
    assert_same_institution,
    actor_institution_id,
    hod_dept_filter,
)
from app.models.user import UserRole
from app.schemas.user import UserCreate, UserResponse, UserUpdate
import app.services.user_service as user_svc

router = APIRouter()


@router.get(
    "",
    response_model=list[UserResponse],
    summary="List users for an institution",
)
async def list_users(
    institution_id: uuid.UUID = Query(..., description="Institution UUID"),
    role: list[UserRole] = Query(default=[], description="Filter by role (repeatable)"),
    db: AsyncSession = Depends(get_db),
    pagination: PaginationParams = Depends(get_pagination),
    current_user: CurrentUser = Depends(require_hod),
) -> list[UserResponse]:
    assert_same_institution(current_user, institution_id)
    items = await user_svc.list_by_institution(
        db, institution_id,
        roles=role or None,
        department_id=hod_dept_filter(current_user),
        skip=pagination.skip,
        limit=pagination.limit,
    )
    return [UserResponse.model_validate(u) for u in items]


@router.post(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a user account (admin only — bypasses self-registration flow)",
)
async def create_user(
    payload: UserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin),
) -> UserResponse:
    if payload.role == UserRole.HOD:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="HOD role cannot be assigned directly. "
                   "Set the HOD via the Department settings instead.",
        )
    if payload.role is not None and payload.role == UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="SUPER_ADMIN role cannot be assigned via this endpoint",
        )
    inst_id = actor_institution_id(current_user, payload.institution_id)
    payload = payload.model_copy(update={"institution_id": inst_id})
    user = await user_svc.create(db, payload)

    # If academic title is set, auto-create a linked Faculty record
    # (for institution-wide leadership roles like Principal, Dean).
    if payload.academic_title is not None:
        from app.models.faculty import EmploymentType, Faculty
        faculty = Faculty(
            institution_id=inst_id,
            name=user.full_name,
            designation=payload.academic_title,
            user_id=user.id,
            employment_type=EmploymentType.FULL_TIME,
            max_weekly_hours=8,
            availability_blacklist=[],
            preferences={},
        )
        db.add(faculty)

    await db.commit()
    await db.refresh(user)
    return UserResponse.model_validate(user)


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    summary="Get a user by ID",
)
async def get_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> UserResponse:
    user = await user_svc.get_or_404(db, user_id)
    assert_same_institution(current_user, user.institution_id)
    return UserResponse.model_validate(user)


@router.patch(
    "/{user_id}",
    response_model=UserResponse,
    summary="Update a user (role / department / is_active / avatar_url)",
)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin),
) -> UserResponse:
    """
    Admins can update any user in their institution.
    HOD role is managed through the Department settings — setting it
    directly via this endpoint is not allowed.
    """
    if payload.role is not None and payload.role == UserRole.HOD:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="HOD role cannot be assigned directly. "
                   "Set the HOD via the Department settings instead.",
        )
    if payload.role is not None and payload.role == UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="SUPER_ADMIN role cannot be assigned via this endpoint",
        )
    existing = await user_svc.get_or_404(db, user_id)
    assert_same_institution(current_user, existing.institution_id)
    if existing.role == UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super-admin accounts cannot be modified via this endpoint",
        )
    if existing.role == UserRole.HOD and payload.role is not None and payload.role != UserRole.HOD:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="HOD role cannot be removed directly. "
                   "Clear the HOD via the Department settings instead.",
        )
    user = await user_svc.update(db, user_id, payload)
    await db.commit()
    await db.refresh(user)
    return UserResponse.model_validate(user)
