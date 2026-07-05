"""
app/services/bulk/room_import.py
===================================
Bulk import for Room records. Duplicate check by code + institution_id.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.room import Room, RoomType
from app.schemas.bulk_upload import (
    BulkImportResult,
    BulkUploadPreview,
    BulkUploadRow,
    BulkRowStatus,
)
from app.services.bulk.base import (
    coerce_enum,
    coerce_int,
    map_columns,
)

REQUIRED_FIELDS = ["code", "name", "capacity"]


async def preview_import(
    db: AsyncSession,
    rows: list[dict[str, str]],
    institution_id: uuid.UUID,
) -> BulkUploadPreview:
    if not rows:
        return BulkUploadPreview(total_rows=0, to_create=[], to_update=[], errors=[])

    column_map = map_columns(list(rows[0].keys()))
    to_create: list[BulkUploadRow] = []
    to_update: list[BulkUploadRow] = []
    errors: list[BulkUploadRow] = []

    for idx, raw in enumerate(rows):
        row_num = idx + 2
        mapped = {field: raw.get(col, "") for col, field in column_map.items()}
        row_errors: list[str] = []

        for f in REQUIRED_FIELDS:
            if not mapped.get(f):
                row_errors.append(f"Missing required field: {f}")

        existing = None
        if mapped.get("code") and not row_errors:
            result = await db.execute(
                select(Room).where(
                    Room.code.ilike(mapped["code"]),
                    Room.institution_id == institution_id,
                )
            )
            existing = result.scalar_one_or_none()

        data = {
            "code": mapped.get("code", ""),
            "name": mapped.get("name", ""),
        }
        if mapped.get("capacity"):
            try:
                data["capacity"] = coerce_int(mapped["capacity"], "capacity")
            except ValueError as e:
                row_errors.append(str(e))
        if mapped.get("room_type"):
            try:
                rt = coerce_enum(mapped["room_type"], RoomType)
                if rt:
                    data["room_type"] = rt.value
            except ValueError as e:
                row_errors.append(str(e))
        if mapped.get("building"):
            data["building"] = mapped["building"]
        if mapped.get("campus"):
            data["campus"] = mapped["campus"]
        if mapped.get("tags"):
            data["tags"] = [t.strip() for t in mapped["tags"].split(",") if t.strip()]

        if row_errors:
            errors.append(BulkUploadRow(row_number=row_num, status=BulkRowStatus.ERROR, data=data, errors=row_errors))
        elif existing:
            to_update.append(BulkUploadRow(row_number=row_num, status=BulkRowStatus.UPDATE, data=data, existing_id=str(existing.id)))
        else:
            to_create.append(BulkUploadRow(row_number=row_num, status=BulkRowStatus.CREATE, data=data))

    return BulkUploadPreview(total_rows=len(rows), to_create=to_create, to_update=to_update, errors=errors)


async def execute_import(
    db: AsyncSession,
    rows: list[BulkUploadRow],
    institution_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    actor_role: str | None,
) -> BulkImportResult:
    from app.models.audit_log import AuditAction
    from app.services import audit_log_service

    imported = 0
    updated = 0
    failed = 0
    fail_errors: list[BulkUploadRow] = []

    for row in rows:
        if row.status == BulkRowStatus.ERROR:
            failed += 1
            fail_errors.append(row)
            continue

        try:
            async with await db.begin_nested():
                code = row.data.get("code", "")

                if row.status == BulkRowStatus.CREATE:
                    room = Room(
                        institution_id=institution_id,
                        code=code,
                        name=row.data.get("name", ""),
                        capacity=row.data.get("capacity"),
                        room_type=row.data.get("room_type"),
                        building=row.data.get("building"),
                        campus=row.data.get("campus"),
                        tags=row.data.get("tags"),
                    )
                    db.add(room)
                    await db.flush()

                    await audit_log_service.record(
                        db, actor_user_id=actor_user_id, actor_role=actor_role,
                        action=AuditAction.CREATED, entity_type="Room",
                        entity_id=room.id, entity_label=code, institution_id=institution_id,
                    )
                    imported += 1

                elif row.status == BulkRowStatus.UPDATE and row.existing_id:
                    result = await db.execute(select(Room).where(Room.id == uuid.UUID(row.existing_id)))
                    room = result.scalar_one_or_none()
                    if not room:
                        failed += 1
                        fail_errors.append(BulkUploadRow(row_number=row.row_number, status=BulkRowStatus.ERROR, data=row.data, errors=["Room not found"]))
                        continue

                    if row.data.get("name"):
                        room.name = row.data["name"]
                    if row.data.get("capacity") is not None:
                        room.capacity = row.data["capacity"]
                    if row.data.get("room_type"):
                        room.room_type = row.data["room_type"]
                    if row.data.get("building"):
                        room.building = row.data["building"]
                    if row.data.get("campus"):
                        room.campus = row.data["campus"]
                    if row.data.get("tags"):
                        room.tags = row.data["tags"]

                    await audit_log_service.record(
                        db, actor_user_id=actor_user_id, actor_role=actor_role,
                        action=AuditAction.UPDATED, entity_type="Room",
                        entity_id=room.id, entity_label=code or room.code,
                        institution_id=institution_id,
                    )
                    updated += 1

        except Exception as e:
            failed += 1
            fail_errors.append(BulkUploadRow(row_number=row.row_number, status=BulkRowStatus.ERROR, data=row.data, errors=[str(e)]))

    await db.commit()
    return BulkImportResult(imported=imported, updated=updated, failed=failed, errors=fail_errors)
