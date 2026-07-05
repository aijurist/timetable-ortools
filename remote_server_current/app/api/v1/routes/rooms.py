"""
Rooms router — room catalogue CRUD.

GET    /rooms          List rooms for an institution (paginated).
POST   /rooms          Create a room.
GET    /rooms/{id}     Get a room.
PATCH  /rooms/{id}     Update a room.
DELETE /rooms/{id}     Soft-delete (sets is_active=False).
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import (
    CurrentUser, PaginationParams, get_current_user, get_db, get_pagination,
    assert_same_institution, actor_institution_id, require_admin, require_hod,
)
from app.models.room import RoomType
from app.schemas.room import RoomCreate, RoomListResponse, RoomResponse, RoomUpdate
import app.services.room_service as room_svc

# Bulk import
from fastapi import UploadFile
from app.schemas.bulk_upload import (
    BulkImportRequest, BulkImportResult,
    BulkUploadPreview, BulkUploadPreviewResponse,
)
from app.services.bulk import base as bulk_base
from app.services.bulk import room_import as bulk_room

router = APIRouter()


@router.get(
    "/buildings",
    response_model=list[str],
    summary="List distinct building names for an institution",
)
async def list_buildings(
    institution_id: uuid.UUID = Query(..., description="Scope to institution"),
    active_only: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> list[str]:
    assert_same_institution(current_user, institution_id)
    return await room_svc.list_distinct_buildings(
        db, institution_id, active_only=active_only,
    )


@router.get(
    "",
    response_model=RoomListResponse,
    summary="List rooms for an institution",
)
async def list_rooms(
    institution_id: uuid.UUID,
    room_type: Optional[RoomType] = Query(default=None),
    building: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None, description="Search by code or name"),
    active_only: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
    pagination: PaginationParams = Depends(get_pagination),
    current_user: CurrentUser = Depends(get_current_user),
) -> RoomListResponse:
    assert_same_institution(current_user, institution_id)
    total = await room_svc.count_by_institution(
        db,
        institution_id,
        room_type=room_type,
        building=building,
        search=search,
        active_only=active_only,
    )
    items = await room_svc.list_by_institution(
        db,
        institution_id,
        room_type=room_type,
        building=building,
        search=search,
        active_only=active_only,
        skip=pagination.skip,
        limit=pagination.limit,
    )
    type_counts = await room_svc.get_type_counts(
        db, institution_id, active_only=active_only,
    )
    return RoomListResponse(
        items=[RoomResponse.model_validate(r) for r in items],
        total=total,
        skip=pagination.skip,
        limit=pagination.limit,
        type_counts=type_counts,
    )


@router.post(
    "",
    response_model=RoomResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a room",
)
async def create_room(
    payload: RoomCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin),
) -> RoomResponse:
    inst_id = actor_institution_id(current_user, payload.institution_id)
    room = await room_svc.create(
        db, inst_id, payload,
        actor_user_id=current_user.user_uuid,
        actor_role=current_user.role.value,
    )
    await db.commit()
    await db.refresh(room)
    return RoomResponse.model_validate(room)


@router.get(
    "/{room_id}",
    response_model=RoomResponse,
    summary="Get a room",
)
async def get_room(
    room_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> RoomResponse:
    room = await room_svc.get_or_404(db, room_id)
    assert_same_institution(current_user, room.institution_id)
    return RoomResponse.model_validate(room)


@router.patch(
    "/{room_id}",
    response_model=RoomResponse,
    summary="Update a room",
)
async def update_room(
    room_id: uuid.UUID,
    payload: RoomUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin),
) -> RoomResponse:
    existing = await room_svc.get_or_404(db, room_id)
    assert_same_institution(current_user, existing.institution_id)
    room = await room_svc.update(
        db, room_id, payload,
        actor_user_id=current_user.user_uuid,
        actor_role=current_user.role.value,
    )
    await db.commit()
    await db.refresh(room)
    return RoomResponse.model_validate(room)


@router.delete(
    "/{room_id}/permanent",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
    summary="Permanently delete a room (admin only)",
)
async def hard_delete_room(
    room_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin),
) -> None:
    existing = await room_svc.get_or_404(db, room_id)
    assert_same_institution(current_user, existing.institution_id)
    await room_svc.hard_delete(
        db, room_id,
        actor_user_id=current_user.user_uuid,
        actor_role=current_user.role.value,
    )
    await db.commit()
    return None


@router.delete(
    "/{room_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
    summary="Soft-delete a room (sets is_active=False)",
)
async def delete_room(
    room_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin),
) -> None:
    existing = await room_svc.get_or_404(db, room_id)
    assert_same_institution(current_user, existing.institution_id)
    await room_svc.soft_delete(
        db, room_id,
        actor_user_id=current_user.user_uuid,
        actor_role=current_user.role.value,
    )
    await db.commit()
    return None


# ---------------------------------------------------------------------------
# Bulk import
# ---------------------------------------------------------------------------


@router.post(
    "/bulk-preview",
    response_model=BulkUploadPreviewResponse,
    summary="Preview a CSV/XLSX room import",
)
async def bulk_room_preview(
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> BulkUploadPreviewResponse:
    from fastapi import HTTPException
    from app.core.upload import ALLOWED_EXTENSIONS
    from app.api.v1.deps import actor_institution_id
    ext = file.filename.split(".")[-1].lower() if file.filename else ""
    if f".{ext}" not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}")
    institution_id = actor_institution_id(current_user)
    temp_path = await bulk_base.save_upload_to_temp(file)
    try:
        parsed = bulk_base.parse_file(temp_path)
        if len(parsed) > 1000:
            parsed = parsed[:1000]
        if not parsed:
            raise HTTPException(status_code=400, detail="File contains no data rows")
        preview = await bulk_room.preview_import(db, parsed, institution_id)
        return BulkUploadPreviewResponse(resource="rooms", preview=preview)
    finally:
        bulk_base.cleanup_temp(temp_path)


@router.post(
    "/bulk-import",
    response_model=BulkImportResult,
    summary="Execute a room bulk import",
)
async def bulk_room_import(
    payload: BulkImportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> BulkImportResult:
    from fastapi import HTTPException
    from app.api.v1.deps import actor_institution_id
    institution_id = actor_institution_id(current_user)
    result = await bulk_room.execute_import(
        db, payload.rows, institution_id,
        actor_user_id=current_user.user_uuid,
        actor_role=current_user.role.value,
    )
    return result
