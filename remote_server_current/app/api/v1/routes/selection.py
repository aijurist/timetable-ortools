"""Student-facing HYBRID selection endpoints."""
import asyncio
import json
import uuid
from typing import Annotated, AsyncGenerator, Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import CurrentUser, UserRole, assert_same_institution, get_current_user_sse, get_db, require_role
from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.rate_limiter import limiter
from app.schemas.schedule import ScheduledSessionResponse
from app.schemas.selection import (
    ConfirmSelectionResponse,
    GroupSelectionResponse,
    MyTimetableResponse,
    SelectionMenuResponse,
    SelectionPicksPayload,
    SelectionWindowResponse,
)

import app.services.hybrid_selection_service as selection_svc
import app.services.institution_service as institution_svc
import app.services.offering_seat_bundle_service as seat_bundle_svc
import app.services.selection_cache_service as cache_svc
import app.services.selection_window_service as window_svc
import app.services.student_service as student_svc

router = APIRouter()

# NOTE: No `from __future__ import annotations` at module level here.
# slowapi's @limiter.limit() resolves annotations in slowapi's __globals__;
# future annotations break POST body binding on rate-limited routes (payload → query).

OptionalTermId = Annotated[
    uuid.UUID | None,
    Query(description="Optional — defaults to the institution's active academic term"),
]

PicksBody = Annotated[
    SelectionPicksPayload,
    Body(description="Map of bucket_id → offering_id picks"),
]


async def _student_profile(db: AsyncSession, current_user: CurrentUser):
    if current_user.role != UserRole.STUDENT:
        raise HTTPException(status_code=403, detail="Students only")
    profile = await student_svc.get_profile_by_user(db, current_user.user_uuid)
    if profile is None:
        raise HTTPException(status_code=404, detail="Student profile not found")
    return profile


async def _resolve_academic_term_id(
    db: AsyncSession,
    current_user: CurrentUser,
    academic_term_id: uuid.UUID | None,
) -> uuid.UUID:
    if academic_term_id is not None:
        term = await institution_svc.get_term_by_id(db, academic_term_id)
        if term is None:
            raise HTTPException(status_code=404, detail="Academic term not found")
        assert_same_institution(current_user, term.institution_id)
        return academic_term_id

    if current_user.institution_id is None:
        raise HTTPException(status_code=400, detail="No institution assigned to your account")

    term = await institution_svc.resolve_active_academic_term(
        db, uuid.UUID(current_user.institution_id)
    )
    if term is None:
        raise HTTPException(status_code=404, detail="No active academic term found")
    return term.id


# ---------------------------------------------------------------------------
# Read endpoints
# ---------------------------------------------------------------------------

@router.get("/window", response_model=Optional[SelectionWindowResponse])
async def get_my_window(
    academic_term_id: OptionalTermId = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(UserRole.STUDENT)),
) -> Optional[SelectionWindowResponse]:
    profile = await _student_profile(db, current_user)
    if profile.semester is None:
        return None
    term_id = await _resolve_academic_term_id(db, current_user, academic_term_id)
    from app.models.user import User  # noqa: PLC0415
    u = await db.get(User, current_user.user_uuid)
    if u is None or u.department_id is None:
        return None
    window = await window_svc.get_window(db, term_id, u.department_id, profile.semester)
    if window is None:
        return None
    phase = window_svc.compute_effective_phase(window)
    return SelectionWindowResponse(
        id=window.id,
        institution_id=window.institution_id,
        academic_term_id=window.academic_term_id,
        department_id=window.department_id,
        study_semester=window.study_semester,
        status=window.status,
        effective_phase=phase,
        preview_opens_at=window.preview_opens_at,
        registration_opens_at=window.registration_opens_at,
        registration_closes_at=window.registration_closes_at,
        allow_changes_until=window.allow_changes_until,
        timezone=window.timezone,
        published_scenario_id=window.published_scenario_id,
        max_selections_per_student=window.max_selections_per_student,
        created_at=window.created_at,
        updated_at=window.updated_at,
    )


@router.get("/menu", response_model=SelectionMenuResponse)
async def get_selection_menu(
    academic_term_id: OptionalTermId = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(UserRole.STUDENT)),
) -> SelectionMenuResponse:
    import asyncio  # noqa: PLC0415

    from app.models.user import User  # noqa: PLC0415
    from app.core.redis_client import get_redis  # noqa: PLC0415

    profile = await _student_profile(db, current_user)
    term_id = await _resolve_academic_term_id(db, current_user, academic_term_id)

    # Resolve dept_id + semester for the cohort cache key (cheap single-row lookups)
    u = await db.get(User, current_user.user_uuid)
    study_semester = profile.semester
    dept_id = u.department_id if u is not None else None

    lock_key = None
    lock_acquired = False

    # ── Cache fast-path ──────────────────────────────────────────────────────
    # The menu structure is identical for every student in the same cohort
    # (dept + semester). Cache it in Redis for 30 s. Seat counts are included
    # but stay fresh via the SSE seat-update channel (every 3 s).
    if dept_id is not None and study_semester is not None:
        cached = await cache_svc.get_cached_menu(dept_id, study_semester)
        if cached is not None:
            try:
                menu = SelectionMenuResponse.model_validate(cached)
                await cache_svc.set_sse_stream_context(
                    current_user.user_uuid, dept_id, study_semester
                )
                return menu
            except Exception:  # noqa: BLE001
                pass  # corrupted cache entry — fall through to DB

        # ── Thundering-herd guard: distributed lock ──────────────────────────
        # Only one coroutine computes the menu from DB; others wait and re-check.
        lock_key = f"selection:menu:lock:{dept_id}:{study_semester}"
        lock_acquired = False
        skip_herd_wait = False
        try:
            async with get_redis() as r:
                lock_acquired = bool(await r.set(lock_key, "1", nx=True, ex=5))
        except Exception:  # noqa: BLE001
            # Redis unavailable — compute from DB directly; do NOT delete a lock we never held
            skip_herd_wait = True

        if not lock_acquired and not skip_herd_wait:
            # Another worker is computing — wait up to 10 s then re-check cache
            for _ in range(40):
                await asyncio.sleep(0.25)
                cached = await cache_svc.get_cached_menu(dept_id, study_semester)
                if cached is not None:
                    try:
                        menu = SelectionMenuResponse.model_validate(cached)
                        await cache_svc.set_sse_stream_context(
                            current_user.user_uuid, dept_id, study_semester
                        )
                        return menu
                    except Exception:  # noqa: BLE001
                        break  # Bad cache entry — compute from DB

    # ── DB computation ────────────────────────────────────────────────────────
    try:
        menu = await selection_svc.get_selection_menu(db, profile, term_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # ── Populate cache + SSE context ─────────────────────────────────────────
    if dept_id is not None and study_semester is not None:
        try:
            await cache_svc.set_cached_menu(
                dept_id, study_semester,
                menu.model_dump(mode="json"),
                ttl_seconds=30,  # 30 s: short enough for seat freshness
            )
            await cache_svc.set_sse_stream_context(
                current_user.user_uuid, dept_id, study_semester
            )
            # Release the distributed lock
            if lock_key and lock_acquired:
                async with get_redis() as r:
                    await r.delete(lock_key)
        except Exception as exc:  # noqa: BLE001
            from app.core.logger import logger  # noqa: PLC0415
            logger.warning("Menu cache write failed", error=str(exc))
    else:
        # No cohort key — still seed SSE context from old path
        try:
            if study_semester is not None and u is not None and dept_id is not None:
                await cache_svc.set_sse_stream_context(
                    current_user.user_uuid, dept_id, study_semester
                )
        except Exception as exc:  # noqa: BLE001
            from app.core.logger import logger  # noqa: PLC0415
            logger.warning("SSE stream context cache write failed", error=str(exc))

    return menu



@router.get("/draft", response_model=Optional[GroupSelectionResponse])
async def get_draft(
    academic_term_id: OptionalTermId = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(UserRole.STUDENT)),
) -> Optional[GroupSelectionResponse]:
    profile = await _student_profile(db, current_user)
    term_id = await _resolve_academic_term_id(db, current_user, academic_term_id)
    study_year = selection_svc._study_year_from_profile(profile)
    study_semester = profile.semester
    if study_semester is None:
        return None
    return await selection_svc.get_current_selection(
        db, profile.id, term_id, study_year, study_semester
    )


# ---------------------------------------------------------------------------
# Write endpoints
# ---------------------------------------------------------------------------

@router.post("/draft", response_model=GroupSelectionResponse)
async def save_draft(
    payload: PicksBody,
    academic_term_id: OptionalTermId = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(UserRole.STUDENT)),
) -> GroupSelectionResponse:
    profile = await _student_profile(db, current_user)
    term_id = await _resolve_academic_term_id(db, current_user, academic_term_id)
    try:
        result = await selection_svc.save_draft(db, profile, term_id, payload)
        await db.commit()
        return result
    except (ValidationError, ConflictError) as exc:
        await db.rollback()
        status = 409 if isinstance(exc, ConflictError) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Concurrent draft update — please retry") from None


@router.post("/confirm", response_model=ConfirmSelectionResponse, status_code=201)
@limiter.limit("3/minute")
async def confirm_selection(
    request: Request,
    payload: PicksBody,
    academic_term_id: OptionalTermId = None,
    idempotency_key: Annotated[Optional[str], Header(alias="Idempotency-Key")] = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(UserRole.STUDENT)),
) -> ConfirmSelectionResponse:
    # Scope idempotency key to the user so keys from different students never collide.
    scoped_idem_key = (
        f"{current_user.user_uuid}:{idempotency_key}" if idempotency_key else None
    )
    if scoped_idem_key:
        cached = await cache_svc.get_idempotency_result(scoped_idem_key)
        if cached:
            return ConfirmSelectionResponse.model_validate(cached)

    profile = await _student_profile(db, current_user)
    term_id = await _resolve_academic_term_id(db, current_user, academic_term_id)
    try:
        result = await selection_svc.confirm_selection(db, profile, term_id, payload)
        await db.commit()
    except ConflictError as exc:
        await db.rollback()
        # Do NOT delete Redis seat counters here. ConflictError is always raised before
        # _sync_redis_after_book runs (verify_seats_available fires pre-flush), so this
        # transaction never wrote any Redis keys. Deleting them would remove valid counters
        # written by other successful transactions, causing spurious fast-fail rejections.
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValidationError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Write idempotency result AFTER successful commit so retries get a committed response.
    if scoped_idem_key:
        await cache_svc.set_idempotency_result(
            scoped_idem_key, result.model_dump(mode="json")
        )

    return result


@router.delete("/selection", response_model=GroupSelectionResponse)
async def drop_selection(
    academic_term_id: OptionalTermId = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(UserRole.STUDENT)),
) -> GroupSelectionResponse:
    profile = await _student_profile(db, current_user)
    term_id = await _resolve_academic_term_id(db, current_user, academic_term_id)

    try:
        result = await selection_svc.drop_selection(db, profile, term_id)
        await db.commit()
    except (NotFoundError, ValidationError) as exc:
        await db.rollback()
        status_code = 404 if isinstance(exc, NotFoundError) else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    return result


@router.get("/my-timetable", response_model=MyTimetableResponse)
async def get_my_timetable(
    academic_term_id: OptionalTermId = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(UserRole.STUDENT)),
) -> MyTimetableResponse:
    profile = await _student_profile(db, current_user)
    term_id = await _resolve_academic_term_id(db, current_user, academic_term_id)
    sessions, slot_definitions = await selection_svc.get_my_timetable(
        db, profile, term_id
    )
    return MyTimetableResponse(sessions=sessions, slot_definitions=slot_definitions)


# ---------------------------------------------------------------------------
# SSE — real-time seat count stream
# ---------------------------------------------------------------------------

@router.get("/seats/stream")
async def selection_seats_stream(
    current_user: CurrentUser = Depends(get_current_user_sse),
) -> StreamingResponse:
    """Server-Sent Events stream for real-time per-offering seat counts.

    Subscribes to ``selection:seats:{dept_id}:{study_semester}`` on Redis.
    One channel per department+semester — all students in that cohort share
    the same subscription so a single PUBLISH fans out to everyone.

    A background broadcaster publishes a full cohort snapshot every
    ``SELECTION_SEATS_STREAM_INTERVAL_SECONDS`` (default 3 s) for channels
    with active subscribers.  Confirm/drop also pushes immediate partial updates.

    Events
    ------
    ``event: connected``   — emitted immediately on connection.
    ``event: seat_update`` — periodic full snapshot or post confirm/drop partial;
        data is JSON:
        ``{"type": "seat_update", "scope": "full"|"partial", "offerings": [...]}``
    ``: heartbeat``        — SSE comment when no pub/sub message within the
        poll window (keeps the connection alive through proxies).
    """
    from app.core.logger import logger  # noqa: PLC0415

    if current_user.role != UserRole.STUDENT:
        raise HTTPException(status_code=403, detail="Student access required")

    ctx = await cache_svc.get_sse_stream_context(current_user.user_uuid)
    if ctx is None:
        if current_user.department_id is None:
            raise HTTPException(status_code=400, detail="Student has no department assigned")
        raise HTTPException(
            status_code=400,
            detail="Load the selection menu before subscribing to seat updates",
        )

    dept_id, study_semester = ctx
    channel = cache_svc.seats_pub_sub_channel(dept_id, study_semester)
    poll_seconds = settings.SELECTION_SEATS_STREAM_INTERVAL_SECONDS

    async def _event_generator() -> AsyncGenerator[str, None]:
        from app.core.redis_client import create_pubsub_redis  # noqa: PLC0415

        r = create_pubsub_redis()
        pubsub = r.pubsub()
        registered = False
        try:
            await pubsub.subscribe(channel)
            await cache_svc.register_seats_stream(dept_id, study_semester)
            registered = True
            yield "event: connected\ndata: {}\n\n"

            while True:
                try:
                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=poll_seconds
                    )
                    if message and message.get("type") == "message":
                        data = message.get("data", "{}")
                        yield f"event: seat_update\ndata: {data}\n\n"
                    else:
                        yield ": heartbeat\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Seat stream pub/sub error — retrying",
                        error=str(exc),
                        channel=channel,
                    )
                    await asyncio.sleep(1)
        finally:
            if registered:
                try:
                    await cache_svc.unregister_seats_stream(dept_id, study_semester)
                except Exception:
                    pass
            try:
                await pubsub.unsubscribe(channel)
                await pubsub.aclose()
            except Exception:
                pass
            try:
                await r.aclose()
            except Exception:
                pass

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Admin Selection Management
# ---------------------------------------------------------------------------

from app.schemas.selection import AdminSelectionListItem, AdminBookSelectionRequest
from app.models.selection import StudentGroupSelection, GroupSelectionStatus
from app.models.student import StudentProfile, StudentRegistration, RegistrationStatus
from app.models.user import User
from app.api.v1.deps import require_hod, hod_dept_filter
from sqlalchemy import select, or_, delete
import app.services.curriculum_service as curriculum_svc

@router.get("/admin/list", response_model=list[AdminSelectionListItem])
async def admin_list_selections(
    academic_term_id: uuid.UUID | None = Query(None),
    department_id: uuid.UUID | None = Query(None),
    study_semester: int | None = Query(None),
    search: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> list[AdminSelectionListItem]:
    # Check HOD department scope
    dept_filter = hod_dept_filter(current_user)
    if dept_filter is not None:
        department_id = dept_filter

    stmt = (
        select(
            StudentGroupSelection.id,
            StudentGroupSelection.student_id,
            User.full_name,
            StudentProfile.enrollment_number,
            User.email,
            StudentGroupSelection.department_id,
            StudentGroupSelection.study_semester,
            StudentGroupSelection.status,
            StudentGroupSelection.selection_payload,
            StudentGroupSelection.confirmed_at,
        )
        .join(StudentProfile, StudentGroupSelection.student_id == StudentProfile.id)
        .join(User, StudentProfile.user_id == User.id)
    )

    if academic_term_id is not None:
        stmt = stmt.where(StudentGroupSelection.academic_term_id == academic_term_id)
    if department_id is not None:
        stmt = stmt.where(StudentGroupSelection.department_id == department_id)
    if study_semester is not None:
        stmt = stmt.where(StudentGroupSelection.study_semester == study_semester)
    if search:
        search_like = f"%{search}%"
        stmt = stmt.where(
            or_(
                User.full_name.ilike(search_like),
                User.email.ilike(search_like),
                StudentProfile.enrollment_number.ilike(search_like),
            )
        )

    stmt = stmt.order_by(User.full_name)
    result = await db.execute(stmt)
    rows = result.all()

    return [
        AdminSelectionListItem(
            id=row.id,
            student_id=row.student_id,
            student_name=row.full_name,
            student_enrollment=row.enrollment_number,
            student_email=row.email,
            department_id=row.department_id,
            study_semester=row.study_semester,
            status=row.status,
            selection_payload=row.selection_payload,
            confirmed_at=row.confirmed_at,
        )
        for row in rows
    ]


@router.get("/admin/menu", response_model=SelectionMenuResponse)
async def admin_get_student_selection_menu(
    student_id: uuid.UUID,
    academic_term_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> SelectionMenuResponse:
    profile = await db.get(StudentProfile, student_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Student profile not found")

    # Check HOD department scope
    dept_filter = hod_dept_filter(current_user)
    if dept_filter is not None and profile.user.department_id != dept_filter:
        raise HTTPException(status_code=403, detail="Not your department")

    try:
        menu = await selection_svc.get_selection_menu(db, profile, academic_term_id)
        return menu
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/admin/book", response_model=ConfirmSelectionResponse, status_code=201)
async def admin_book_selection(
    body: AdminBookSelectionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> ConfirmSelectionResponse:
    # Get student profile
    profile = await db.get(StudentProfile, body.student_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Student profile not found")

    # Check HOD department scope
    dept_filter = hod_dept_filter(current_user)
    if dept_filter is not None and profile.user.department_id != dept_filter:
        raise HTTPException(status_code=403, detail="Not your department")

    # Map Picks payload
    from app.schemas.selection import SelectionPicksPayload
    payload = SelectionPicksPayload(picks=body.picks)

    try:
        result = await selection_svc.confirm_selection(db, profile, body.academic_term_id, payload)
        await db.commit()
        return result
    except ConflictError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValidationError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/admin/bulk-clear", status_code=204)
async def admin_bulk_clear_selections(
    academic_term_id: uuid.UUID = Query(...),
    department_id: uuid.UUID = Query(...),
    study_semester: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> None:
    # Check HOD department scope
    dept_filter = hod_dept_filter(current_user)
    if dept_filter is not None and department_id != dept_filter:
        raise HTTPException(status_code=403, detail="Not your department")

    # Find all group selections for this cohort
    sel_result = await db.execute(
        select(StudentGroupSelection).where(
            StudentGroupSelection.academic_term_id == academic_term_id,
            StudentGroupSelection.department_id == department_id,
            StudentGroupSelection.study_semester == study_semester,
        )
    )
    selections = list(sel_result.scalars().all())

    if not selections:
        return None

    # Get all registration IDs to delete and release
    sel_ids = [s.id for s in selections]
    reg_result = await db.execute(
        select(StudentRegistration).where(
            StudentRegistration.student_group_selection_id.in_(sel_ids)
        )
    )
    regs = list(reg_result.scalars().all())

    # Release seats in DB and Redis
    released_offering_ids = []
    for reg in regs:
        if reg.status == RegistrationStatus.CONFIRMED:
            await curriculum_svc.release_seat(db, reg.offering_id)
            released_offering_ids.append(str(reg.offering_id))
        await db.delete(reg)

    for sel in selections:
        await db.delete(sel)

    await db.commit()

    # Publish seat updates for all released offerings
    if released_offering_ids:
        try:
            unique_oids = list(set(released_offering_ids))
            live = await cache_svc.get_live_seat_counts(unique_oids)
            max_map = await cache_svc.get_cohort_max_seats_map(department_id, study_semester)
            partial = []
            for oid in unique_oids:
                remaining = live.get(oid)
                max_seats = max_map.get(oid)
                booked = max(0, max_seats - remaining) if (max_seats is not None and remaining is not None) else 0
                partial.append({
                    "offering_id": oid,
                    "booked_seats": booked,
                    "seats_remaining": remaining,
                    "is_frozen": False,
                })
            await cache_svc.publish_seat_update(
                department_id, study_semester, partial, scope="partial"
            )
        except Exception as exc:
            from app.core.logger import logger
            logger.warning("SSE seat publish failed in admin_bulk_clear_selections", error=str(exc))

    return None


@router.delete("/admin/{selection_id}", status_code=204)
async def admin_delete_selection(
    selection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_hod),
) -> None:
    sel = await db.get(StudentGroupSelection, selection_id)
    if not sel:
        raise HTTPException(status_code=404, detail="Selection not found")

    # Check HOD department scope
    dept_filter = hod_dept_filter(current_user)
    if dept_filter is not None and sel.department_id != dept_filter:
        raise HTTPException(status_code=403, detail="Not your department")

    # Release seats and delete registrations + group selection
    reg_result = await db.execute(
        select(StudentRegistration).where(
            StudentRegistration.student_group_selection_id == sel.id
        )
    )
    regs = list(reg_result.scalars().all())
    released_offering_ids = []
    for reg in regs:
        if reg.status == RegistrationStatus.CONFIRMED:
            await curriculum_svc.release_seat(db, reg.offering_id)
            released_offering_ids.append(str(reg.offering_id))
        await db.delete(reg)

    if released_offering_ids:
        try:
            live = await cache_svc.get_live_seat_counts(released_offering_ids)
            max_map = await cache_svc.get_cohort_max_seats_map(sel.department_id, sel.study_semester)
            partial = []
            for oid in released_offering_ids:
                remaining = live.get(oid)
                max_seats = max_map.get(oid)
                booked = max(0, max_seats - remaining) if (max_seats is not None and remaining is not None) else 0
                partial.append({
                    "offering_id": oid,
                    "booked_seats": booked,
                    "seats_remaining": remaining,
                    "is_frozen": False,
                })
            await cache_svc.publish_seat_update(
                sel.department_id, sel.study_semester, partial, scope="partial"
            )
        except Exception as exc:
            from app.core.logger import logger
            logger.warning("SSE seat publish failed in admin_delete_selection", error=str(exc))

    await db.delete(sel)
    await db.commit()
    return None

