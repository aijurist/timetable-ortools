"""
app/services/bulk/faculty_import.py
=====================================
Bulk import service for Faculty records.
Creates User + Faculty for new entries; updates existing by email match.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.upload import FACULTY_DEFAULT_PASSWORD
from app.models.faculty import EmploymentType, Faculty
from app.models.user import User
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
    resolve_department,
)

REQUIRED_FIELDS = ["name", "email", "department_id", "designation", "staff_code"]


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
        row_num = idx + 2  # 1-indexed + header row
        mapped = {field: raw.get(col, "") for col, field in column_map.items()}
        row_errors: list[str] = []

        # Required fields
        for f in REQUIRED_FIELDS:
            if not mapped.get(f):
                row_errors.append(f"Missing required field: {f}")

        # Resolve department
        dept_id = None
        if mapped.get("department_id"):
            dept_id = await resolve_department(db, mapped["department_id"], institution_id, dept_cache)
            if not dept_id:
                row_errors.append(f"Department '{mapped['department_id']}' not found")
        else:
            row_errors.append("Missing required field: department_id")

        # Check existing
        existing = None
        if mapped.get("email") and not row_errors:
            result = await db.execute(
                select(Faculty).join(User).where(User.email.ilike(mapped["email"]))
            )
            existing = result.scalar_one_or_none()

        data = {
            "name": mapped.get("name", ""),
            "email": mapped.get("email", ""),
            "department_id": str(dept_id) if dept_id else "",
        }
        if mapped.get("phone"):
            data["phone"] = mapped["phone"]
        if mapped.get("gender"):
            data["gender"] = mapped["gender"].upper()
        if mapped.get("staff_code"):
            data["staff_code"] = mapped["staff_code"]
        if mapped.get("employee_id"):
            data["employee_id"] = mapped["employee_id"]
        if mapped.get("age"):
            try:
                data["age"] = coerce_int(mapped["age"], "age")
            except ValueError as e:
                row_errors.append(str(e))
        if mapped.get("employment_type"):
            try:
                et = coerce_enum(mapped["employment_type"], EmploymentType)
                if et:
                    data["employment_type"] = et.value
            except ValueError as e:
                row_errors.append(str(e))
        if mapped.get("designation"):
            data["designation"] = mapped["designation"]
        if row_errors:
            errors.append(BulkUploadRow(row_number=row_num, status=BulkRowStatus.ERROR, data=data, errors=row_errors))
        elif existing:
            to_update.append(BulkUploadRow(row_number=row_num, status=BulkRowStatus.UPDATE, data=data, existing_id=str(existing.id)))
        else:
            to_create.append(BulkUploadRow(row_number=row_num, status=BulkRowStatus.CREATE, data=data))

    return BulkUploadPreview(
        total_rows=len(rows),
        to_create=to_create,
        to_update=to_update,
        errors=errors,
    )


async def execute_import(
    db: AsyncSession,
    rows: list[BulkUploadRow],
    institution_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    actor_role: str | None,
) -> BulkImportResult:
    from app.services.user_service import hash_password
    from app.models.faculty import Faculty
    from app.models.user import User, UserRole
    from app.services import audit_log_service
    from app.models.audit_log import AuditAction

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
                email = row.data.get("email", "")
                name = row.data.get("name", "")

                if row.status == BulkRowStatus.CREATE:
                    hashed = hash_password(FACULTY_DEFAULT_PASSWORD)
                    user = User(
                        full_name=name,
                        email=email,
                        hashed_password=hashed,
                        role=UserRole.TEACHER,
                        department_id=dept_id,
                        institution_id=institution_id,
                        phone=row.data.get("phone"),
                        gender=row.data.get("gender"),
                    )
                    db.add(user)
                    await db.flush()

                    faculty = Faculty(
                        user_id=user.id,
                        institution_id=institution_id,
                        name=name,
                        staff_code=row.data.get("staff_code"),
                        employee_id=row.data.get("employee_id"),
                        age=row.data.get("age"),
                        employment_type=row.data.get("employment_type"),
                        designation=row.data.get("designation"),
                    )
                    db.add(faculty)
                    await db.flush()

                    await audit_log_service.record(
                        db,
                        actor_user_id=actor_user_id,
                        actor_role=actor_role,
                        action=AuditAction.CREATED,
                        entity_type="Faculty",
                        entity_id=faculty.id,
                        entity_label=email,
                        institution_id=institution_id,
                    )
                    imported += 1

                elif row.status == BulkRowStatus.UPDATE and row.existing_id:
                    faculty_id = uuid.UUID(row.existing_id)
                    result = await db.execute(select(Faculty).where(Faculty.id == faculty_id))
                    faculty = result.scalar_one_or_none()
                    if not faculty:
                        failed += 1
                        fail_errors.append(BulkUploadRow(row_number=row.row_number, status=BulkRowStatus.ERROR, data=row.data, errors=["Faculty record not found"]))
                        continue

                    if name:
                        faculty.name = name
                    if row.data.get("staff_code") is not None:
                        faculty.staff_code = row.data.get("staff_code")
                    if row.data.get("employee_id") is not None:
                        faculty.employee_id = row.data.get("employee_id")
                    if row.data.get("age") is not None:
                        faculty.age = row.data.get("age")
                    if row.data.get("employment_type"):
                        faculty.employment_type = row.data.get("employment_type")
                    if row.data.get("designation"):
                        faculty.designation = row.data.get("designation")
                    result = await db.execute(select(User).where(User.id == faculty.user_id))
                    user = result.scalar_one_or_none()
                    if user:
                        if name:
                            user.full_name = name
                        if dept_id:
                            user.department_id = dept_id
                        if row.data.get("phone") is not None:
                            user.phone = row.data.get("phone")
                        if row.data.get("gender") is not None:
                            user.gender = row.data.get("gender")

                    await db.flush()

                    await audit_log_service.record(
                        db,
                        actor_user_id=actor_user_id,
                        actor_role=actor_role,
                        action=AuditAction.UPDATED,
                        entity_type="Faculty",
                        entity_id=faculty.id,
                        entity_label=email or faculty.name,
                        institution_id=institution_id,
                    )
                    updated += 1

        except Exception as e:
            failed += 1
            fail_errors.append(BulkUploadRow(row_number=row.row_number, status=BulkRowStatus.ERROR, data=row.data, errors=[str(e)]))

    await db.commit()
    return BulkImportResult(imported=imported, updated=updated, failed=failed, errors=fail_errors)
