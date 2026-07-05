"""
app/services/bulk/course_import.py
====================================
Bulk import for Course records. Duplicate check by code + institution_id.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Course, SessionType
from app.schemas.bulk_upload import (
    BulkImportResult,
    BulkUploadPreview,
    BulkUploadRow,
    BulkRowStatus,
)
from app.services.bulk.base import (
    coerce_int,
    map_columns,
    resolve_department,
)

REQUIRED_FIELDS = ["code", "name", "department_id", "credits", "lecture_hours", "tutorial_hours", "practical_hours"]


def _derive_session_type(L: int, T: int, P: int) -> SessionType:
    has_theory = L > 0 or T > 0
    has_practical = P > 0
    if has_theory and has_practical:
        return SessionType.BOTH
    if has_practical:
        return SessionType.LAB
    return SessionType.THEORY


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
    dept_cache: dict[str, uuid.UUID | None] = {}

    for idx, raw in enumerate(rows):
        row_num = idx + 2
        mapped = {field: raw.get(col, "") for col, field in column_map.items()}
        row_errors: list[str] = []

        for f in REQUIRED_FIELDS:
            if not mapped.get(f):
                row_errors.append(f"Missing required field: {f}")

        dept_id = None
        if mapped.get("department_id"):
            dept_id = await resolve_department(db, mapped["department_id"], institution_id, dept_cache)
            if not dept_id:
                row_errors.append(f"Department '{mapped['department_id']}' not found")

        existing = None
        if mapped.get("code") and not row_errors:
            result = await db.execute(
                select(Course).where(
                    Course.code.ilike(mapped["code"]),
                    Course.institution_id == institution_id,
                )
            )
            existing = result.scalar_one_or_none()

        L = T = P = 0
        if not row_errors:
            for key, name in [("lecture_hours", "L"), ("tutorial_hours", "T"), ("practical_hours", "P")]:
                try:
                    val = coerce_int(mapped.get(key, ""), name)
                    if name == "L":
                        L = val or 0
                    elif name == "T":
                        T = val or 0
                    else:
                        P = val or 0
                except ValueError as e:
                    row_errors.append(str(e))

        data = {
            "code": mapped.get("code", ""),
            "name": mapped.get("name", ""),
            "department_id": str(dept_id) if dept_id else "",
        }
        if not row_errors:
            data["structure"] = {"L": L, "T": T, "P": P}
            data["weekly_hours"] = L + T + P
            data["session_type"] = _derive_session_type(L, T, P).value
        if mapped.get("credits") and not row_errors:
            try:
                data["credits"] = coerce_int(mapped["credits"], "credits")
            except ValueError as e:
                row_errors.append(str(e))
        if mapped.get("elective_type"):
            raw = mapped["elective_type"].strip().lower()
            if raw in ("professional", "prof", "pe"):
                data["elective_type"] = "PROFESSIONAL"
            elif raw in ("open", "oe"):
                data["elective_type"] = "OPEN"
        if mapped.get("elective_semester"):
            try:
                data["elective_semester"] = coerce_int(mapped["elective_semester"], "elective_semester")
            except ValueError as e:
                row_errors.append(str(e))

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
                dept_id = uuid.UUID(row.data["department_id"]) if row.data.get("department_id") else None
                code = row.data.get("code", "")

                if row.status == BulkRowStatus.CREATE:
                    course = Course(
                        institution_id=institution_id,
                        department_id=dept_id,
                        code=code,
                        name=row.data.get("name", ""),
                        weekly_hours=row.data.get("weekly_hours"),
                        credits=row.data.get("credits"),
                        session_type=row.data.get("session_type"),
                        structure=row.data.get("structure"),
                        elective_type=row.data.get("elective_type"),
                        elective_semester=row.data.get("elective_semester"),
                    )
                    db.add(course)
                    await db.flush()

                    await audit_log_service.record(
                        db, actor_user_id=actor_user_id, actor_role=actor_role,
                        action=AuditAction.CREATED, entity_type="Course",
                        entity_id=course.id, entity_label=code, institution_id=institution_id,
                    )
                    imported += 1

                elif row.status == BulkRowStatus.UPDATE and row.existing_id:
                    result = await db.execute(select(Course).where(Course.id == uuid.UUID(row.existing_id)))
                    course = result.scalar_one_or_none()
                    if not course:
                        failed += 1
                        fail_errors.append(BulkUploadRow(row_number=row.row_number, status=BulkRowStatus.ERROR, data=row.data, errors=["Course not found"]))
                        continue

                    if row.data.get("name"):
                        course.name = row.data["name"]
                    if row.data.get("weekly_hours") is not None:
                        course.weekly_hours = row.data["weekly_hours"]
                    if row.data.get("credits") is not None:
                        course.credits = row.data["credits"]
                    if row.data.get("session_type"):
                        course.session_type = row.data["session_type"]
                    if row.data.get("structure") is not None:
                        course.structure = row.data["structure"]
                    if "elective_type" in row.data:
                        course.elective_type = row.data["elective_type"]
                    if row.data.get("elective_semester") is not None:
                        course.elective_semester = row.data["elective_semester"]
                    if dept_id:
                        course.department_id = dept_id

                    await audit_log_service.record(
                        db, actor_user_id=actor_user_id, actor_role=actor_role,
                        action=AuditAction.UPDATED, entity_type="Course",
                        entity_id=course.id, entity_label=code or course.code,
                        institution_id=institution_id,
                    )
                    updated += 1

        except Exception as e:
            failed += 1
            fail_errors.append(BulkUploadRow(row_number=row.row_number, status=BulkRowStatus.ERROR, data=row.data, errors=[str(e)]))

    await db.commit()
    return BulkImportResult(imported=imported, updated=updated, failed=failed, errors=fail_errors)
