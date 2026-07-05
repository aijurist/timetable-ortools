"""
app/services/bulk/teaching_assignment_import.py
=================================================
Bulk import service for Teaching Assignments.

Resolves faculty names + course codes via batch DB queries (3 queries total for the
preview phase), then delegates each row to create_teaching_assignment service.

Two call paths:
  1. HTTP endpoint  → preview_import() → display to user → execute_import()
  2. Agent tool     → bulk_create_assignments calls preview_import() + execute_import()
     internally (1 LangGraph tool call regardless of row count).
"""
from __future__ import annotations

import re
import uuid
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

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

REQUIRED_FIELDS = ["course_code"]


# ---------------------------------------------------------------------------
# Room-hint parser (pure, no DB)
# ---------------------------------------------------------------------------

def parse_room_hint(hint: str) -> dict[str, str]:
    """Parse a room hint string into a notes suffix.

    Returns dict with optional key ``notes_suffix``.
    """
    if not hint:
        return {}
    h = hint.strip()
    if not h:
        return {}

    # Lab / laboratory keyword
    if re.match(r"^lab(oratory)?$", h, re.IGNORECASE):
        return {"notes_suffix": "Requires lab room"}

    # Numeric capacity: ">140", "140+", "160"
    cap_match = re.match(r"^[>≥]?\s*(\d+)\+?$", h)
    if cap_match:
        cap = int(cap_match.group(1))
        return {"notes_suffix": f"Requires room capacity ≥ {cap}"}

    # Anything else (e.g. "LH-301") → preferred room note
    return {"notes_suffix": f"Preferred room: {h}"}


# ---------------------------------------------------------------------------
# Batch index builders
# ---------------------------------------------------------------------------

async def _build_faculty_index(
    db: AsyncSession,
    institution_id: uuid.UUID,
    dept_id: Optional[uuid.UUID],
) -> dict[str, tuple[uuid.UUID, str, int]]:
    """
    Returns { name_lower → (faculty_id, display_name, current_section_count) }.
    Scoped to institution; if dept_id given, scoped to that department only (HOD).
    current_section_count is a placeholder (0) — real count resolved in duplicate step.
    """
    from app.models.faculty import Faculty
    from app.models.user import User

    q = (
        select(Faculty.id, User.full_name)
        .join(User, User.id == Faculty.user_id)
        .where(
            Faculty.institution_id == institution_id,
        )
    )
    if dept_id:
        q = q.where(User.department_id == dept_id)

    result = await db.execute(q)
    rows = result.all()
    index: dict[str, tuple[uuid.UUID, str, int]] = {}
    for fac_id, full_name in rows:
        if full_name:
            normalized = re.sub(r"\s+", " ", full_name.strip())
            index[normalized.lower()] = (fac_id, normalized, 0)
    return index


async def _build_course_index(
    db: AsyncSession,
    institution_id: uuid.UUID,
) -> dict[str, uuid.UUID]:
    """
    Returns { code_lower → course_id } + { name_lower → course_id }.
    """
    from app.models.course import Course

    result = await db.execute(
        select(Course.id, Course.code, Course.name).where(
            Course.institution_id == institution_id,
            Course.is_active == True,  # noqa: E712
        )
    )
    rows = result.all()
    index: dict[str, uuid.UUID] = {}
    for course_id, code, name in rows:
        if code:
            index[code.strip().lower()] = course_id
        if name:
            index[name.strip().lower()] = course_id
    return index


async def _load_section_totals(
    db: AsyncSession,
    institution_id: uuid.UUID,
    term_id: uuid.UUID,
    dept_id: Optional[uuid.UUID],
) -> dict[uuid.UUID, int]:
    """Returns { faculty_id → total section_count } for the given term."""
    from app.models.curriculum import TeachingAssignment
    from sqlalchemy import func as sa_func

    q = (
        select(TeachingAssignment.faculty_id, sa_func.sum(TeachingAssignment.section_count))
        .where(
            TeachingAssignment.institution_id == institution_id,
            TeachingAssignment.academic_term_id == term_id,
            TeachingAssignment.faculty_id.isnot(None),
        )
    )
    if dept_id:
        q = q.where(TeachingAssignment.department_id == dept_id)
    q = q.group_by(TeachingAssignment.faculty_id)

    result = await db.execute(q)
    return {fid: (total or 0) for fid, total in result.all()}


async def _batch_find_existing_tas(
    db: AsyncSession,
    institution_id: uuid.UUID,
    term_id: uuid.UUID,
    dept_id: Optional[uuid.UUID],
    resolved_valid: list[dict],
) -> dict[tuple, Any]:
    """
    Batch-fetch existing TeachingAssignments for all valid resolved rows in one query.

    Returns a dict keyed by (course_id, faculty_id) → TeachingAssignment.
    faculty_id is None for pending rows (no assigned faculty).
    """
    from app.models.curriculum import TeachingAssignment

    course_ids = list({r["course_id"] for r in resolved_valid if r.get("course_id")})
    if not course_ids:
        return {}

    base_where = [
        TeachingAssignment.institution_id == institution_id,
        TeachingAssignment.academic_term_id == term_id,
        TeachingAssignment.course_id.in_(course_ids),
    ]
    if dept_id:
        base_where.append(TeachingAssignment.department_id == dept_id)

    result = await db.execute(select(TeachingAssignment).where(*base_where))
    rows = result.scalars().all()

    lookup: dict[tuple, Any] = {}
    for ta in rows:
        key = (ta.course_id, ta.faculty_id)
        if key not in lookup:
            lookup[key] = ta
    return lookup


# ---------------------------------------------------------------------------
# Name resolution helpers
# ---------------------------------------------------------------------------

def _resolve_faculty_name(
    name: str,
    faculty_index: dict[str, tuple[uuid.UUID, str, int]],
) -> tuple[Optional[uuid.UUID], Optional[str], list[str], list[str]]:
    """
    Try to resolve a faculty name to a faculty_id.

    Returns (faculty_id, display_name, ambiguous_candidates, errors).
    ambiguous_candidates is non-empty when 2+ partial matches found.
    """
    if not name:
        return None, None, [], []

    norm = re.sub(r"\s+", " ", name.strip().lower())

    # Exact match
    if norm in faculty_index:
        fac_id, display, _ = faculty_index[norm]
        return fac_id, display, [], []

    # Partial / substring match
    candidates = [
        (fid, disp) for key, (fid, disp, _) in faculty_index.items()
        if norm in key or key in norm
    ]
    if len(candidates) == 1:
        return candidates[0][0], candidates[0][1], [], []
    if len(candidates) > 1:
        names = [d for _, d in candidates]
        return None, None, names, []

    return None, None, [], [f"Faculty '{name}' not found"]


# ---------------------------------------------------------------------------
# Main preview function
# ---------------------------------------------------------------------------

async def preview_import(
    db: AsyncSession,
    rows: list[dict[str, str]],
    institution_id: uuid.UUID,
    academic_term_id: uuid.UUID,
    dept_id: Optional[uuid.UUID] = None,
    role: str = "",
    auto_assign: bool = False,
) -> BulkUploadPreview:
    if not rows:
        return BulkUploadPreview(total_rows=0, to_create=[], to_update=[], errors=[])

    # Step 1 — Batch load reference indexes
    faculty_index = await _build_faculty_index(
        db, institution_id,
        dept_id if role.upper() == "HOD" else None,
    )
    course_index = await _build_course_index(db, institution_id)
    dept_cache: dict[str, Optional[uuid.UUID]] = {}

    section_totals: dict[uuid.UUID, int] = {}
    auto_assign_rows: list[int] = []

    # Step 2 — Map columns
    column_map = map_columns(list(rows[0].keys()))

    to_create: list[BulkUploadRow] = []
    to_update: list[BulkUploadRow] = []
    errors: list[BulkUploadRow] = []
    workload_deltas: dict[str, int] = {}

    resolved: list[dict] = []

    for idx, raw in enumerate(rows):
        row_num = idx + 2

        # Build mapped field dict (prefer 'code' alias for course_code fallback)
        mapped: dict[str, str] = {}
        for col, field in column_map.items():
            val = raw.get(col, "")
            # Map 'code' alias to 'course_code' if not already mapped
            if field == "code" and "course_code" not in mapped:
                mapped["course_code"] = val
            elif field not in mapped:
                mapped[field] = val

        row_errors: list[str] = []
        data: dict[str, Any] = {}

        # Resolve course (required)
        course_raw = (mapped.get("course_code") or "").strip()
        if not course_raw:
            row_errors.append("Missing required field: course_code")
            course_id = None
        else:
            course_id = course_index.get(course_raw.lower())
            if not course_id:
                row_errors.append(f"Course '{course_raw}' not found")
            else:
                data["course_code"] = course_raw

        # Resolve faculty (required unless auto_assign)
        faculty_raw = (mapped.get("faculty_name") or "").strip()
        faculty_id: Optional[uuid.UUID] = None
        faculty_display: Optional[str] = None
        if faculty_raw:
            faculty_id, faculty_display, ambiguous, fac_errors = _resolve_faculty_name(
                faculty_raw, faculty_index
            )
            if ambiguous:
                row_errors.append(
                    f"Ambiguous faculty '{faculty_raw}': matches {', '.join(ambiguous[:3])}"
                )
            row_errors.extend(fac_errors)
        elif auto_assign:
            auto_assign_rows.append(idx)
        else:
            row_errors.append("Missing required field: faculty_name")

        data["faculty_name"] = faculty_display or faculty_raw or "(pending)"

        # Section count
        section_count = 1
        if mapped.get("section_count"):
            try:
                sc = coerce_int(mapped["section_count"], "section_count")
                if sc and sc > 0:
                    section_count = sc
            except ValueError as e:
                row_errors.append(str(e))
        data["section_count"] = section_count

        # year_of_study and semester are required
        if not mapped.get("year_of_study"):
            row_errors.append("Missing required field: year_of_study")
        else:
            try:
                data["study_year"] = coerce_int(mapped["year_of_study"], "study_year")
            except ValueError as e:
                row_errors.append(str(e))

        if not mapped.get("semester"):
            row_errors.append("Missing required field: semester")
        else:
            try:
                data["study_semester"] = coerce_int(mapped["semester"], "study_semester")
            except ValueError as e:
                row_errors.append(str(e))
        if mapped.get("notes"):
            data["notes"] = mapped["notes"]

        # Room hint
        if mapped.get("room_hint"):
            hint_result = parse_room_hint(mapped["room_hint"])
            if hint_result.get("notes_suffix"):
                existing_notes = data.get("notes", "")
                data["notes"] = (
                    f"{existing_notes}; {hint_result['notes_suffix']}"
                    if existing_notes
                    else hint_result["notes_suffix"]
                )

        # Requested department (cross-dept)
        if mapped.get("requested_dept"):
            req_dept_id = await resolve_department(
                db, mapped["requested_dept"], institution_id, dept_cache
            )
            if req_dept_id:
                data["requested_dept_id"] = str(req_dept_id)
            else:
                row_errors.append(f"Requested department '{mapped['requested_dept']}' not found")

        # Store resolved IDs for execute phase
        data["_course_id"] = str(course_id) if course_id else None
        data["_faculty_id"] = str(faculty_id) if faculty_id else None

        if row_errors:
            errors.append(
                BulkUploadRow(
                    row_number=row_num,
                    status=BulkRowStatus.ERROR,
                    data=data,
                    errors=row_errors,
                )
            )
            resolved.append({"row_num": row_num, "valid": False})
        else:
            resolved.append({
                "row_num": row_num,
                "valid": True,
                "course_id": course_id,
                "faculty_id": faculty_id,
                "faculty_display": faculty_display,
                "section_count": section_count,
                "data": data,
            })

    # Step 4 — Auto-assign blanks if requested
    if auto_assign and auto_assign_rows:
        section_totals = await _load_section_totals(db, institution_id, academic_term_id, dept_id)
        sorted_faculty = sorted(
            faculty_index.items(),
            key=lambda kv: section_totals.get(kv[1][0], 0),
        )
        assign_pool = [
            (fid, disp)
            for _, (fid, disp, _) in sorted_faculty
        ]
        for pool_idx, row_idx in enumerate(auto_assign_rows):
            res = resolved[row_idx]
            if not res.get("valid"):
                continue
            if assign_pool:
                fac_id, fac_disp = assign_pool[pool_idx % len(assign_pool)]
                res["faculty_id"] = fac_id
                res["faculty_display"] = fac_disp
                res["data"]["faculty_name"] = fac_disp
                res["data"]["_faculty_id"] = str(fac_id)
                res["auto_assigned"] = True

    # Step 5 — Duplicate detection + workload deltas (single batch query)
    valid_resolved = [r for r in resolved if r.get("valid")]
    existing_map = await _batch_find_existing_tas(
        db, institution_id, academic_term_id, dept_id, valid_resolved
    )

    for res in resolved:
        if not res.get("valid"):
            continue

        row_num = res["row_num"]
        course_id = res["course_id"]
        faculty_id = res.get("faculty_id")
        section_count = res["section_count"]
        data = res["data"]

        existing = existing_map.get((course_id, faculty_id))

        if existing:
            to_update.append(
                BulkUploadRow(
                    row_number=row_num,
                    status=BulkRowStatus.UPDATE,
                    data=data,
                    existing_id=str(existing.id),
                )
            )
        else:
            to_create.append(
                BulkUploadRow(
                    row_number=row_num,
                    status=BulkRowStatus.CREATE,
                    data=data,
                )
            )

        # Accumulate workload deltas
        if faculty_id:
            key = data.get("faculty_name", str(faculty_id))
            workload_deltas[key] = workload_deltas.get(key, 0) + section_count

    return BulkUploadPreview(
        total_rows=len(rows),
        to_create=to_create,
        to_update=to_update,
        errors=errors,
        workload_deltas=workload_deltas,
    )


# ---------------------------------------------------------------------------
# Execute import
# ---------------------------------------------------------------------------

async def execute_import(
    db: AsyncSession,
    rows: list[BulkUploadRow],
    institution_id: uuid.UUID,
    academic_term_id: uuid.UUID,
    dept_id: Optional[uuid.UUID],
    actor_user_id: Optional[uuid.UUID],
    actor_role: Optional[str],
) -> BulkImportResult:
    from app.db.session import AsyncSessionLocal
    from app.schemas.curriculum import TeachingAssignmentCreate
    import app.services.teaching_assignment_service as ta_svc

    # Use a DEDICATED session for all mutations so we never conflict with the
    # shared `db` session owned by the LangGraph agent.  The shared `db` may
    # be flushed/committed concurrently by other graph operations, causing
    # "Session is already flushing" errors if we call .commit() or .flush()
    # on it here.
    async with AsyncSessionLocal() as write_db:
        imported = 0
        updated = 0
        failed = 0
        fail_errors: list[BulkUploadRow] = []

        # Track sections before for workload impact
        section_totals_before = await _load_section_totals(write_db, institution_id, academic_term_id, dept_id)

        for row in rows:
            if row.status == BulkRowStatus.ERROR:
                failed += 1
                fail_errors.append(row)
                continue

            try:
                async with write_db.begin_nested():
                    course_id_str = row.data.get("_course_id")
                    faculty_id_str = row.data.get("_faculty_id")
                    req_dept_str = row.data.get("requested_dept_id")

                    if not course_id_str:
                        raise ValueError("course_id missing from row data")

                    course_id = uuid.UUID(course_id_str)
                    faculty_id = uuid.UUID(faculty_id_str) if faculty_id_str else None
                    requested_dept_id = uuid.UUID(req_dept_str) if req_dept_str else None
                    section_count = int(row.data.get("section_count", 1))

                    payload = TeachingAssignmentCreate(
                        institution_id=institution_id,
                        academic_term_id=academic_term_id,
                        department_id=dept_id,
                        faculty_id=faculty_id,
                        requested_dept_id=requested_dept_id,
                        course_id=course_id,
                        section_count=section_count,
                        notes=row.data.get("notes"),
                        study_year=row.data.get("study_year"),
                        study_semester=row.data.get("study_semester"),
                    )

                    if row.status == BulkRowStatus.CREATE:
                        await ta_svc.create_teaching_assignment(
                            write_db, payload,
                            actor_user_id=actor_user_id,
                            actor_role=actor_role,
                        )
                        imported += 1
                    elif row.status == BulkRowStatus.UPDATE and row.existing_id:
                        from app.schemas.curriculum import TeachingAssignmentUpdate
                        update_payload = TeachingAssignmentUpdate(
                            faculty_id=faculty_id,
                            section_count=section_count,
                            notes=row.data.get("notes"),
                            study_year=row.data.get("study_year"),
                            study_semester=row.data.get("study_semester"),
                        )
                        await ta_svc.update_teaching_assignment(
                            write_db, uuid.UUID(row.existing_id), update_payload,
                            actor_user_id=actor_user_id,
                            actor_role=actor_role,
                        )
                        updated += 1

            except Exception as e:
                failed += 1
                fail_errors.append(
                    BulkUploadRow(
                        row_number=row.row_number,
                        status=BulkRowStatus.ERROR,
                        data=row.data,
                        errors=[str(e)],
                    )
                )

        await write_db.commit()

        # Compute workload impact
        section_totals_after = await _load_section_totals(write_db, institution_id, academic_term_id, dept_id)
        workload_impact = _compute_workload_impact(
            section_totals_before, section_totals_after, rows
        )

        return BulkImportResult(
            imported=imported,
            updated=updated,
            failed=failed,
            errors=fail_errors,
            workload_impact=workload_impact,
        )


def _compute_workload_impact(
    before: dict[uuid.UUID, int],
    after: dict[uuid.UUID, int],
    rows: list[BulkUploadRow],
) -> list[dict]:
    """Build workload_impact list: only faculty whose count actually changed."""
    all_fac_ids = set(after.keys()) | set(before.keys())
    changed = []

    # Compute avg
    totals = list(after.values())
    avg = sum(totals) / len(totals) if totals else 0

    # Build name map from rows
    name_map: dict[str, str] = {}
    for row in rows:
        fid_str = row.data.get("_faculty_id")
        name = row.data.get("faculty_name")
        if fid_str and name:
            name_map[fid_str] = name

    for fac_id in all_fac_ids:
        sections_before = before.get(fac_id, 0)
        sections_after = after.get(fac_id, 0)
        if sections_after != sections_before:
            flag = "HIGH" if avg > 0 and sections_after > avg * 1.5 else ""
            changed.append({
                "faculty": name_map.get(str(fac_id), str(fac_id)[:8] + "…"),
                "sections_before": sections_before,
                "sections_after": sections_after,
                "flag": flag,
            })

    changed.sort(key=lambda x: (-x["sections_after"], x["faculty"]))
    return changed
