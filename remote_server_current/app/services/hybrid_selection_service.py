"""HYBRID student selection: menu, draft, confirm, timetable."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.sqltypes import String as SAString

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.logger import logger
from app.models.course import Course
from app.models.curriculum import (
    CourseOffering,
    OfferingBucket,
    SelectionPolicy,
    SchedulingTarget,
    TargetRequirement,
    TargetType,
)
from app.models.faculty import Faculty
from app.models.room import Room
from app.models.schedule import ScheduledSession
from app.models.scenario import Scenario
from app.models.selection import GroupSelectionStatus, StudentGroupSelection
from app.models.selection_access_config import SelectionAccessConfig
from app.models.student import StudentProfile
from app.models.user import User
from app.schemas.schedule import ScheduledSessionResponse
from app.schemas.selection import (
    BucketMenuItem,
    ConfirmSelectionResponse,
    GroupSelectionResponse,
    OfferingMenuItem,
    SelectionMenuResponse,
    SelectionPicksPayload,
    SelectionWindowResponse,
)

import app.services.offering_seat_bundle_service as seat_bundle_svc
import app.services.schedule_service as schedule_svc
import app.services.selection_cache_service as cache_svc
import app.services.selection_invalidation_service as invalidation_svc
import app.services.selection_window_service as window_svc
import app.services.student_course_eligibility_service as eligibility_svc
from app.services.time_grid_service import resolve_slots_for_scenario


def _study_year_from_profile(profile: StudentProfile) -> int:
    if profile.year_of_study is not None:
        return profile.year_of_study
    if profile.semester is not None:
        return max(1, (profile.semester + 1) // 2)
    return 1


async def _get_student_department_id(
    db: AsyncSession, profile: StudentProfile
) -> uuid.UUID:
    user = await db.get(User, profile.user_id)
    if user is None or user.department_id is None:
        raise ValidationError("Student has no department assigned")
    return user.department_id


async def _resolve_cohort_id(
    db: AsyncSession,
    profile: StudentProfile,
    *,
    academic_term_id: uuid.UUID,
    department_id: uuid.UUID,
    scenario_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """
    Return the student's cohort (scheduling target) for selection.

    Uses ``profile.batch_id`` when set; otherwise auto-picks the sole active
    BATCH/COHORT target for the department + term when unambiguous.
    """
    if profile.batch_id is not None:
        target = await db.get(SchedulingTarget, profile.batch_id)
        if target is None or not target.is_active:
            raise ValidationError(
                "Your assigned cohort (batch) is no longer active. "
                "Contact your department office."
            )
        if target.academic_term_id != academic_term_id:
            raise ValidationError(
                "Your assigned cohort belongs to a different academic term. "
                "Contact your department office to update your batch."
            )
        return profile.batch_id

    user = await db.get(User, profile.user_id)
    if user is None or user.institution_id is None:
        raise ValidationError("Student has no institution assigned")

    q = select(SchedulingTarget).where(
        SchedulingTarget.institution_id == user.institution_id,
        SchedulingTarget.academic_term_id == academic_term_id,
        SchedulingTarget.department_id == department_id,
        SchedulingTarget.target_type.in_((TargetType.BATCH, TargetType.COHORT)),
        SchedulingTarget.is_active.is_(True),
    )
    if profile.semester is not None:
        q = q.where(
            or_(
                SchedulingTarget.study_semester == profile.semester,
                SchedulingTarget.study_semester.is_(None),
            )
        )
    if scenario_id is not None:
        q = q.where(
            or_(
                SchedulingTarget.scenario_id == scenario_id,
                SchedulingTarget.scenario_id.is_(None),
            )
        )

    targets = list(
        (await db.execute(q.order_by(SchedulingTarget.name))).scalars().all()
    )

    if len(targets) == 1:
        # Verify the single target's semester matches the student's to avoid
        # a Sem-5 student being auto-assigned to a Sem-1 batch.
        if (
            profile.semester is not None
            and targets[0].study_semester is not None
            and targets[0].study_semester != profile.semester
        ):
            raise ValidationError(
                f"The only configured batch is for Semester {targets[0].study_semester}, "
                f"but your profile is Semester {profile.semester}. "
                "Ask your department office to create a batch for your semester."
            )
        logger.info(
            "Auto-resolved cohort for student without batch_id",
            student_id=str(profile.id),
            cohort_id=str(targets[0].id),
        )
        return targets[0].id

    if not targets:
        raise ValidationError(
            "No cohort (batch) is configured for your department this term. "
            "Ask your department office to create a batch and link your profile."
        )

    raise ValidationError(
        "Your student profile is not linked to a cohort (batch). "
        "Multiple batches exist for your department — an administrator must assign "
        "the correct batch on your student record (Settings → Students)."
    )


async def _load_choice_buckets(
    db: AsyncSession,
    cohort_id: uuid.UUID,
    scenario_id: uuid.UUID,
    study_semester: int,
) -> list[OfferingBucket]:
    req_result = await db.execute(
        select(TargetRequirement)
        .where(TargetRequirement.target_id == cohort_id)
        .options(selectinload(TargetRequirement.bucket).selectinload(OfferingBucket.offerings))
    )
    requirements = list(req_result.scalars().all())
    buckets: list[OfferingBucket] = []
    seen: set[uuid.UUID] = set()
    for req in requirements:
        bucket = req.bucket
        if bucket is None or bucket.id in seen:
            continue
        if bucket.scenario_id and bucket.scenario_id != scenario_id:
            continue
        if bucket.selection_policy not in (
            SelectionPolicy.CHOOSE_FACULTY,
            SelectionPolicy.CHOOSE_COURSE,
        ):
            continue
        seen.add(bucket.id)
        buckets.append(bucket)
    buckets.sort(key=lambda b: b.name)
    return buckets


async def _build_offering_menu_item(
    db: AsyncSession,
    offering: CourseOffering,
    course_map: dict[uuid.UUID, Course],
    faculty_map: dict[uuid.UUID, Faculty],
    *,
    live_seats: dict[str, int] | None = None,
    effective_max_seats: int | None = None,
) -> OfferingMenuItem:
    """Build an offering menu item, optionally using live Redis seat counts.

    ``live_seats`` maps offering_id str → remaining seats from the Redis
    atomic counter.  When provided it takes priority over ``booked_seats``
    from the ORM (which may be from a cached response) so callers always
    see real-time availability.

    ``effective_max_seats`` is the institution-level default cap to use when
    the offering has no explicit ``max_seats`` set (from SelectionAccessConfig).
    """
    course = course_map.get(offering.course_id) if offering.course_id else None
    faculty = faculty_map.get(offering.faculty_id) if offering.faculty_id else None

    # Effective cap: prefer the offering's own max_seats; fall back to the
    # institution-level default (from SelectionAccessConfig).
    eff_max = offering.max_seats if offering.max_seats is not None else effective_max_seats

    oid_str = str(offering.id)
    if live_seats is not None and oid_str in live_seats:
        seats_remaining = max(0, live_seats[oid_str])
        booked = (
            (eff_max - seats_remaining)
            if eff_max is not None
            else offering.booked_seats
        )
    else:
        booked = offering.booked_seats
        seats_remaining = (
            max(0, eff_max - booked)
            if eff_max is not None
            else None
        )

    return OfferingMenuItem(
        id=offering.id,
        course_id=offering.course_id,
        course_code=course.code if course else None,
        course_name=course.name if course else None,
        faculty_id=offering.faculty_id,
        faculty_name=faculty.name if faculty else None,
        group_number=offering.group_number,
        batch_number=offering.batch_number,
        max_seats=eff_max,
        booked_seats=booked,
        seats_remaining=seats_remaining,
        is_frozen=offering.is_frozen,
    )


async def _resolve_effective_max_seats(
    db: AsyncSession,
    institution_id: uuid.UUID,
    academic_term_id: uuid.UUID,
    department_id: uuid.UUID,
) -> int | None:
    """Return the effective per-offering seat cap for this dept/term.

    Priority: group_seat_overrides[dept] → default_max_group_size → None.
    """
    cfg_res = await db.execute(
        select(SelectionAccessConfig).where(
            SelectionAccessConfig.institution_id == institution_id,
            SelectionAccessConfig.academic_term_id == academic_term_id,
        )
    )
    cfg = cfg_res.scalars().first()
    if cfg is None:
        return None

    dept_str = str(department_id)
    for override in (cfg.group_seat_overrides or []):
        if isinstance(override, dict) and str(override.get("department_id")) == dept_str:
            val = override.get("max_seats")
            if val is not None:
                return int(val)

    return cfg.default_max_group_size


def _apply_effective_seat_caps(
    bucket_items: list[BucketMenuItem],
    effective_max_seats: int | None,
) -> list[BucketMenuItem]:
    """Fill missing ``max_seats`` / ``seats_remaining`` from institution config.

    Cached menu snapshots may predate ``SelectionAccessConfig`` or were built
    from offerings whose ``max_seats`` column is NULL (theory rows from legacy
    import).  Without a cap the student portal hides the seat bar entirely.
    """
    if effective_max_seats is None:
        return bucket_items
    for bi in bucket_items:
        updated: list[OfferingMenuItem] = []
        for o in bi.offerings:
            eff_max = o.max_seats if o.max_seats is not None else effective_max_seats
            if o.max_seats is None or o.seats_remaining is None:
                o = o.model_copy(
                    update={
                        "max_seats": eff_max,
                        "seats_remaining": max(0, eff_max - o.booked_seats),
                    }
                )
            updated.append(o)
        bi.offerings = updated
    return bucket_items


async def get_selection_menu(
    db: AsyncSession,
    profile: StudentProfile,
    academic_term_id: uuid.UUID,
) -> SelectionMenuResponse:
    """Return the student's selection menu.

    Two-layer caching strategy
    --------------------------
    * **Structure cache** (``selection:menu:{dept}:{sem}``):
      Stores bucket layout, offering metadata, sessions, slot definitions.
      TTL = 5 min.  Validated against ``scenario_id`` so it auto-invalidates
      when a new timetable is published.  Shared across all students in the
      same dept+semester (eligibility filtering is fast and runs every time).

    * **Seat counts** (``offering:seats:{id}``):
      Always read live from Redis via a single MGET pipeline — never cached
      inside the structure snapshot.  Applied as an overlay to both the
      cache-hit and cache-miss paths so clients always see real availability.
    """
    if profile.semester is None:
        raise ValidationError(
            "Your student profile has no semester set. "
            "Ask your department office to update your academic record."
        )
    department_id = await _get_student_department_id(db, profile)
    study_semester = profile.semester
    study_year = _study_year_from_profile(profile)

    # Always-fresh: window, scenario, cohort (fast lookups — not cacheable
    # because they can change at any time).
    window = await window_svc.get_window(
        db, academic_term_id, department_id, study_semester
    )
    if window is None:
        raise NotFoundError("No selection window configured for your department/semester")

    window_svc.assert_student_can_read(window)

    if not window.published_scenario_id:
        raise ValidationError("Selection window has no published scenario linked")

    scenario = await db.get(Scenario, window.published_scenario_id)
    if scenario is None or scenario.published_job_id is None:
        raise ValidationError("Published scenario has no published timetable")

    cohort_id = await _resolve_cohort_id(
        db,
        profile,
        academic_term_id=academic_term_id,
        department_id=department_id,
        scenario_id=scenario.id,
    )

    # ── Structure cache check ─────────────────────────────────────────────────
    cached = await cache_svc.get_cached_menu(department_id, study_semester)
    cache_valid = (
        cached is not None
        and str(cached.get("scenario_id")) == str(scenario.id)
    )

    if cache_valid:
        # Fast path: rebuild from cache — skip expensive bucket/session DB queries.
        bucket_items = [BucketMenuItem.model_validate(b) for b in cached["bucket_items"]]
        sessions_typed: dict[str, list[ScheduledSessionResponse]] = {
            k: [ScheduledSessionResponse.model_validate(s) for s in v]
            for k, v in cached.get("sessions_by_offering_id", {}).items()
        }
        slot_definitions = cached.get("slot_definitions")
    else:
        # Slow path: build from DB then write to structure cache.
        buckets = await _load_choice_buckets(db, cohort_id, scenario.id, study_semester)
        if not buckets:
            raise ValidationError("No selection buckets configured for your cohort")

        buckets = await eligibility_svc.filter_buckets_for_student(
            db,
            buckets,
            profile=profile,
            academic_term_id=academic_term_id,
            department_id=department_id,
            study_semester=study_semester,
        )
        if not buckets:
            raise ValidationError("No eligible courses configured for your profile")

        course_ids: set[uuid.UUID] = set()
        faculty_ids: set[uuid.UUID] = set()
        for bucket in buckets:
            for offering in bucket.offerings:
                if offering.study_semester and offering.study_semester != study_semester:
                    continue
                if offering.course_id:
                    course_ids.add(offering.course_id)
                if offering.faculty_id:
                    faculty_ids.add(offering.faculty_id)

        course_map: dict[uuid.UUID, Course] = {}
        if course_ids:
            cr = await db.execute(select(Course).where(Course.id.in_(course_ids)))
            course_map = {c.id: c for c in cr.scalars().all()}

        faculty_map: dict[uuid.UUID, Faculty] = {}
        if faculty_ids:
            fr = await db.execute(select(Faculty).where(Faculty.id.in_(faculty_ids)))
            faculty_map = {f.id: f for f in fr.scalars().all()}

        # Look up effective per-offering seat cap (institution-level default).
        effective_max_seats: int | None = None
        if window.institution_id:
            effective_max_seats = await _resolve_effective_max_seats(
                db, window.institution_id, academic_term_id, department_id
            )

        # Build bucket items using DB seat counts (live overlay applied below).
        bucket_items = []
        for bucket in buckets:
            offerings_filtered = [
                o for o in bucket.offerings
                if not o.study_semester or o.study_semester == study_semester
            ]
            if not offerings_filtered:
                continue
            primary_course_id = offerings_filtered[0].course_id
            bucket_items.append(
                BucketMenuItem(
                    id=bucket.id,
                    name=bucket.name,
                    selection_policy=bucket.selection_policy.value,
                    min_selection=bucket.min_selection,
                    max_selection=bucket.max_selection,
                    course_id=primary_course_id,
                    parallel_group_number=_parallel_group_number(bucket),
                    offerings=[
                        await _build_offering_menu_item(
                            db, o, course_map, faculty_map,
                            effective_max_seats=effective_max_seats,
                        )
                        for o in offerings_filtered
                    ],
                )
            )

        slot_definitions = await resolve_slots_for_scenario(db, scenario)

        # Build slot_code → day_of_week lookup from slot definitions
        slot_day_map: dict[str, str] = {}
        if isinstance(slot_definitions, dict):
            for code, info in slot_definitions.items():
                if isinstance(info, dict):
                    slot_day_map[code] = info.get("day", code.split("_")[0] if "_" in code else "")
                elif "_" in code:
                    slot_day_map[code] = code.split("_")[0]

        # Build sessions_by_offering from scheduled_sessions table.
        # This works for both solver-produced AND legacy/reimport data, because
        # reimport_all.py populates scheduled_sessions with correct offering_id links.
        # (solver_job_svc.get_result_rows uses result_schedule JSON which is empty
        # for legacy/seeded scenarios.)
        offering_ids_in_menu = [o.id for b in bucket_items for o in b.offerings if o.id]
        sessions_by_offering: dict[str, list[dict[str, Any]]] = {}
        if offering_ids_in_menu:
            ss_result = await db.execute(
                select(
                    ScheduledSession,
                    Course.code.label("course_code"),
                    Course.name.label("course_name"),
                    Faculty.name.label("faculty_name"),
                    Room.name.label("room_name"),
                    Room.code.label("room_code"),
                )
                .outerjoin(Course, cast(Course.id, SAString) == ScheduledSession.course_id)
                .outerjoin(Faculty, cast(Faculty.id, SAString) == ScheduledSession.faculty_id)
                .outerjoin(Room, cast(Room.id, SAString) == ScheduledSession.room_id)
                .where(
                    ScheduledSession.scenario_id == scenario.id,
                    ScheduledSession.offering_id.in_(offering_ids_in_menu),
                )
            )
            for row in ss_result.all():
                ss = row[0]
                oid = str(ss.offering_id)
                sessions_by_offering.setdefault(oid, []).append({
                    "id": str(ss.id),
                    "scenario_id": str(ss.scenario_id),
                    "session_id": ss.session_id,
                    "course_id": ss.course_id,
                    "faculty_id": ss.faculty_id,
                    "room_id": ss.room_id,
                    "slot_code": ss.slot_code,
                    "offering_id": ss.offering_id,
                    "is_pinned": ss.is_pinned,
                    "created_at": ss.created_at,
                    "course_code": row.course_code,
                    "course_name": row.course_name,
                    "faculty_name": row.faculty_name,
                    "room_name": row.room_name,
                    "room_code": row.room_code,
                    "day_of_week": slot_day_map.get(ss.slot_code),
                })

        # ── Merge theory sessions into lab-batch sibling offerings ────────────
        # When a bucket has multiple offerings for the same (course_id, faculty_id),
        # those are lab-batch offerings (B1 / B2 …).  A separate "theory-only"
        # offering may also exist for the same course+faculty (all sessions are
        # _T slots).  We merge those theory sessions into every batch sibling so
        # students see their full schedule, then remove the theory-only offering
        # from the displayed bucket (it is NOT a selectable choice).
        hidden_offering_ids: set[str] = set()

        for bucket in bucket_items:
            # Group offering-ids by (course_id, faculty_id)
            cf_map: dict[tuple[str, str], list[str]] = {}
            for o in bucket.offerings:
                key = (
                    str(o.course_id) if o.course_id else "",
                    str(o.faculty_id) if o.faculty_id else "",
                )
                cf_map.setdefault(key, []).append(str(o.id))

            for key, oids in cf_map.items():
                if len(oids) < 2:
                    continue  # Single offering — no batch grouping needed

                theory_oids: list[str] = []
                batch_oids: list[str] = []
                for oid in oids:
                    slist = sessions_by_offering.get(oid, [])
                    if not slist:
                        # No sessions linked yet → treat as a batch offering
                        batch_oids.append(oid)
                    elif all("_T" in (s.get("slot_code") or "") for s in slist):
                        theory_oids.append(oid)
                    else:
                        batch_oids.append(oid)

                if not theory_oids:
                    continue  # Nothing to merge

                # Collect all theory sessions across theory-only siblings
                theory_sessions: list[dict[str, Any]] = []
                for oid in theory_oids:
                    theory_sessions.extend(sessions_by_offering.get(oid, []))

                # Prepend theory sessions to every batch offering
                for oid in batch_oids:
                    sessions_by_offering[oid] = theory_sessions + sessions_by_offering.get(oid, [])

                # Mark theory-only offerings as hidden (not selectable by the student)
                hidden_offering_ids.update(theory_oids)

        # Rebuild bucket_items without the hidden theory-only offerings
        if hidden_offering_ids:
            bucket_items = [
                b.model_copy(update={
                    "offerings": [o for o in b.offerings if str(o.id) not in hidden_offering_ids]
                })
                for b in bucket_items
            ]

        sessions_typed = {
            k: [ScheduledSessionResponse.model_validate(s) for s in v]
            for k, v in sessions_by_offering.items()
        }

        # Write structure to cache (non-critical; failure is logged, not raised).
        try:
            await cache_svc.set_cached_menu(
                department_id,
                study_semester,
                {
                    "scenario_id": str(scenario.id),
                    "bucket_items": [b.model_dump(mode="json") for b in bucket_items],
                    "sessions_by_offering_id": {
                        k: [s.model_dump(mode="json") for s in v]
                        for k, v in sessions_typed.items()
                    },
                    "slot_definitions": slot_definitions,
                },
                ttl_seconds=300,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Menu structure cache write failed", error=str(exc))

    # ── Effective seat caps (always — cache may predate config / legacy import) ─
    effective_max_seats: int | None = None
    if window.institution_id:
        effective_max_seats = await _resolve_effective_max_seats(
            db, window.institution_id, academic_term_id, department_id
        )
    bucket_items = _apply_effective_seat_caps(bucket_items, effective_max_seats)

    # Seed Redis counters for offerings not yet cached (non-critical).
    try:
        await cache_svc.seed_missing_seat_counters(
            [
                (str(o.id), o.booked_seats, o.max_seats)
                for b in bucket_items
                for o in b.offerings
            ]
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis seat counter seed failed", error=str(exc))

    # ── Live seat overlay (always — whether from cache or DB) ─────────────────
    # One MGET pipeline; results overwrite whatever seat counts are in bucket_items.
    offering_ids_all = [o.id for b in bucket_items for o in b.offerings]
    live_seats: dict[str, int] = await cache_svc.get_live_seat_counts(
        [str(oid) for oid in offering_ids_all]
    )
    for bi in bucket_items:
        updated_offerings = []
        for o in bi.offerings:
            remaining = live_seats.get(str(o.id))
            if remaining is not None:
                o = o.model_copy(
                    update={
                        "seats_remaining": max(0, remaining),
                        "booked_seats": (
                            max(0, o.max_seats - remaining)
                            if o.max_seats is not None
                            else o.booked_seats
                        ),
                    }
                )
            updated_offerings.append(o)
        bi.offerings = updated_offerings

    # Per-student PE/OE: show only offerings for courses this student is eligible for.
    eligible_course_ids = await eligibility_svc.get_eligible_course_ids(
        db,
        profile,
        academic_term_id=academic_term_id,
        department_id=department_id,
        study_semester=study_semester,
    )
    bucket_items = eligibility_svc.filter_menu_items_for_student(
        bucket_items, eligible_course_ids
    )
    visible_offering_ids = {str(o.id) for b in bucket_items for o in b.offerings}
    sessions_typed = {
        k: v for k, v in sessions_typed.items() if k in visible_offering_ids
    }

    # Shared cohort index for SSE broadcaster (survives menu structure invalidation).
    try:
        await cache_svc.refresh_cohort_seat_index(
            department_id,
            study_semester,
            [
                {
                    "offering_id": str(o.id),
                    "max_seats": o.max_seats,
                    "is_frozen": o.is_frozen,
                }
                for b in bucket_items
                for o in b.offerings
            ],
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Cohort seat index refresh failed", error=str(exc))

    # ── Per-student data (always fresh — never cached) ────────────────────────
    active_result = await db.execute(
        select(StudentGroupSelection).where(
            StudentGroupSelection.student_id == profile.id,
            StudentGroupSelection.academic_term_id == academic_term_id,
            StudentGroupSelection.study_year == study_year,
            StudentGroupSelection.study_semester == study_semester,
            StudentGroupSelection.status.in_(
                (GroupSelectionStatus.DRAFT, GroupSelectionStatus.CONFIRMED)
            ),
        )
    )
    active_sel = active_result.scalars().first()
    if active_sel is not None:
        await invalidation_svc.drop_if_publish_snapshot_stale(
            db,
            active_sel,
            window,
            scenario,
            institution_id=window.institution_id,
        )

    current = await get_current_selection(
        db, profile.id, academic_term_id, study_year, study_semester
    )
    selection_reset_reason = await invalidation_svc.get_selection_reset_reason(
        db,
        profile.id,
        academic_term_id,
        study_year,
        study_semester,
    )

    effective_phase = window_svc.compute_effective_phase(window)
    window_resp = SelectionWindowResponse(
        id=window.id,
        institution_id=window.institution_id,
        academic_term_id=window.academic_term_id,
        department_id=window.department_id,
        study_semester=window.study_semester,
        status=window.status,
        effective_phase=effective_phase,
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

    # Derive mode/required/elective from bucket_items (works for both cache paths).
    required_bucket_ids = [b.id for b in bucket_items]
    elective_ids = [
        b.id for b in bucket_items
        if b.selection_policy == SelectionPolicy.CHOOSE_COURSE.value
    ]
    _has_parallel = any(
        b.selection_policy == SelectionPolicy.CHOOSE_FACULTY.value
        and b.parallel_group_number is not None
        for b in bucket_items
    )
    _has_per_course_b = any(
        b.selection_policy == SelectionPolicy.CHOOSE_FACULTY.value
        and b.parallel_group_number is None
        for b in bucket_items
    )
    mode = "per_group_bucket" if _has_parallel and not _has_per_course_b else "per_course"

    return SelectionMenuResponse(
        academic_term_id=academic_term_id,
        department_id=department_id,
        study_year=study_year,
        study_semester=study_semester,
        cohort_id=cohort_id,
        window=window_resp,
        buckets=bucket_items,
        required_bucket_ids=required_bucket_ids,
        selection_mode=mode,
        elective_bucket_ids=elective_ids,
        sessions_by_offering_id=sessions_typed,
        slot_definitions=slot_definitions,
        current_selection=current,
        selection_reset_reason=selection_reset_reason,
    )


async def get_current_selection(
    db: AsyncSession,
    student_id: uuid.UUID,
    academic_term_id: uuid.UUID,
    study_year: int,
    study_semester: int,
) -> Optional[GroupSelectionResponse]:
    result = await db.execute(
        select(StudentGroupSelection).where(
            StudentGroupSelection.student_id == student_id,
            StudentGroupSelection.academic_term_id == academic_term_id,
            StudentGroupSelection.study_year == study_year,
            StudentGroupSelection.study_semester == study_semester,
            StudentGroupSelection.status.in_(
                (GroupSelectionStatus.DRAFT, GroupSelectionStatus.CONFIRMED)
            ),
        )
    )
    sel = result.scalars().first()
    if sel is None:
        return None
    return GroupSelectionResponse.model_validate(sel)


def _parallel_group_number(bucket: OfferingBucket) -> int | None:
    """Return the sole group_number when every offering in the bucket shares one."""
    if bucket.selection_policy != SelectionPolicy.CHOOSE_FACULTY:
        return None
    nums = {o.group_number for o in bucket.offerings}
    if len(nums) == 1 and None not in nums:
        return next(iter(nums))
    return None


def _partition_buckets(
    buckets: list[OfferingBucket],
) -> tuple[list[OfferingBucket], list[OfferingBucket], list[OfferingBucket]]:
    """Split into (parallel_group_buckets, per_course_buckets, elective_buckets)."""
    parallel: list[OfferingBucket] = []
    per_course: list[OfferingBucket] = []
    elective: list[OfferingBucket] = []
    for bucket in buckets:
        if bucket.selection_policy == SelectionPolicy.CHOOSE_COURSE:
            elective.append(bucket)
        elif _parallel_group_number(bucket) is not None:
            parallel.append(bucket)
        else:
            per_course.append(bucket)
    return parallel, per_course, elective


def _selection_mode(buckets: list[OfferingBucket]) -> str:
    parallel, per_course, _ = _partition_buckets(buckets)
    if parallel and not per_course:
        return "per_group_bucket"
    return "per_course"


def _uses_per_group_buckets(buckets: list[OfferingBucket]) -> bool:
    return _selection_mode(buckets) == "per_group_bucket"


def _required_bucket_ids(buckets: list[OfferingBucket]) -> list[uuid.UUID]:
    """Every choice bucket must have exactly one pick on confirm."""
    return [b.id for b in buckets]


async def _resolve_offerings_for_picks(
    db: AsyncSession,
    buckets: list[OfferingBucket],
    picks: dict[str, uuid.UUID],
    *,
    strict: bool = True,
) -> tuple[dict[uuid.UUID, CourseOffering], list[OfferingBucket]]:
    bucket_map = {b.id: b for b in buckets}

    if len(set(picks.values())) != len(picks):
        raise ValidationError("Duplicate offering selected")

    resolved: dict[uuid.UUID, CourseOffering] = {}
    for bucket_id_str, offering_id in picks.items():
        bucket_id = uuid.UUID(bucket_id_str)
        bucket = bucket_map.get(bucket_id)
        if bucket is None:
            raise ValidationError(
                "STALE_MENU: Your course menu has changed since you last loaded "
                "this page. Please refresh and re-select."
            )
        offering = next((o for o in bucket.offerings if o.id == offering_id), None)
        if offering is None:
            raise ValidationError(
                "STALE_MENU: Your course menu has changed since you last loaded "
                "this page. Please refresh and re-select."
            )
        expected_group = _parallel_group_number(bucket)
        if expected_group is not None and offering.group_number != expected_group:
            raise ValidationError(
                f"Offering does not belong to {bucket.name}"
            )
        resolved[bucket_id] = offering

    if strict and len(picks) != len(buckets):
        raise ValidationError(
            f"Must select exactly one offering per bucket ({len(buckets)} required)"
        )

    course_ids = [o.course_id for o in resolved.values()]
    if len(set(course_ids)) != len(course_ids):
        raise ValidationError("Each selected offering must be a different course")

    # Per-course buckets (mixed group_numbers): all faculty picks must share one group.
    # Per-group buckets (Group 1…N): one pick per bucket; group_numbers differ by design.
    if not _uses_per_group_buckets(buckets):
        core = [
            o
            for b_id, o in resolved.items()
            if bucket_map[b_id].selection_policy == SelectionPolicy.CHOOSE_FACULTY
        ]
        if core:
            group_numbers = {o.group_number for o in core}
            if None in group_numbers or len(group_numbers) != 1:
                raise ValidationError(
                    "All core faculty picks must belong to the same group"
                )

    return resolved, buckets


async def save_draft(
    db: AsyncSession,
    profile: StudentProfile,
    academic_term_id: uuid.UUID,
    payload: SelectionPicksPayload,
) -> GroupSelectionResponse:
    if profile.semester is None:
        raise ValidationError(
            "Your student profile has no semester set. "
            "Ask your department office to update your academic record."
        )
    department_id = await _get_student_department_id(db, profile)
    study_semester = profile.semester
    study_year = _study_year_from_profile(profile)

    window = await window_svc.get_window_or_404(
        db, academic_term_id, department_id, study_semester
    )
    window_svc.assert_student_can_write_draft(window)

    if not window.published_scenario_id:
        raise ValidationError("No published scenario on window")

    cohort_id = await _resolve_cohort_id(
        db,
        profile,
        academic_term_id=academic_term_id,
        department_id=department_id,
        scenario_id=window.published_scenario_id,
    )

    buckets = await _load_choice_buckets(
        db, cohort_id, window.published_scenario_id, study_semester  # type: ignore[arg-type]
    )
    buckets = await eligibility_svc.filter_buckets_for_student(
        db,
        buckets,
        profile=profile,
        academic_term_id=academic_term_id,
        department_id=department_id,
        study_semester=study_semester,
    )
    resolved, _ = await _resolve_offerings_for_picks(db, buckets, payload.picks, strict=False)

    core_groups = [
        o.group_number
        for b in buckets
        if b.selection_policy == SelectionPolicy.CHOOSE_FACULTY
        for o in [resolved.get(b.id)]
        if o is not None
    ]
    group_number = core_groups[0] if core_groups else None

    result = await db.execute(
        select(StudentGroupSelection).where(
            StudentGroupSelection.student_id == profile.id,
            StudentGroupSelection.academic_term_id == academic_term_id,
            StudentGroupSelection.study_year == study_year,
            StudentGroupSelection.study_semester == study_semester,
        ).with_for_update()
    )
    sel = result.scalars().first()
    payload_json = {
        "core": {},
        "electives": {},
        "picks": {k: str(v) for k, v in payload.picks.items()},
    }
    for bucket in buckets:
        offering = resolved.get(bucket.id)
        if offering is None:
            continue
        key = (
            "core"
            if bucket.selection_policy == SelectionPolicy.CHOOSE_FACULTY
            else "electives"
        )
        payload_json[key][str(bucket.id)] = str(offering.id)

    if sel is None:
        sel = StudentGroupSelection(
            student_id=profile.id,
            academic_term_id=academic_term_id,
            department_id=department_id,
            study_year=study_year,
            study_semester=study_semester,
            group_number=group_number,
            status=GroupSelectionStatus.DRAFT,
            selection_payload=payload_json,
        )
        db.add(sel)
    else:
        if sel.status == GroupSelectionStatus.CONFIRMED:
            raise ConflictError("Cannot edit a confirmed selection — drop first")
        sel.group_number = group_number
        sel.selection_payload = payload_json
        sel.status = GroupSelectionStatus.DRAFT

    await db.flush()
    return GroupSelectionResponse.model_validate(sel)


async def confirm_selection(
    db: AsyncSession,
    profile: StudentProfile,
    academic_term_id: uuid.UUID,
    payload: SelectionPicksPayload,
) -> ConfirmSelectionResponse:
    if profile.semester is None:
        raise ValidationError(
            "Your student profile has no semester set. "
            "Ask your department office to update your academic record."
        )
    department_id = await _get_student_department_id(db, profile)
    study_semester = profile.semester
    study_year = _study_year_from_profile(profile)

    window = await window_svc.get_window_or_404(
        db, academic_term_id, department_id, study_semester
    )
    window_svc.assert_student_can_confirm(window)

    if not window.published_scenario_id:
        raise ValidationError("No published scenario on window")
    scenario = await db.get(Scenario, window.published_scenario_id)
    if scenario is None or scenario.published_job_id is None:
        raise ValidationError("Published scenario has no published timetable")

    cohort_id = await _resolve_cohort_id(
        db,
        profile,
        academic_term_id=academic_term_id,
        department_id=department_id,
        scenario_id=window.published_scenario_id,
    )

    buckets = await _load_choice_buckets(
        db, cohort_id, window.published_scenario_id, study_semester  # type: ignore[arg-type]
    )
    buckets = await eligibility_svc.filter_buckets_for_student(
        db,
        buckets,
        profile=profile,
        academic_term_id=academic_term_id,
        department_id=department_id,
        study_semester=study_semester,
    )
    resolved, _ = await _resolve_offerings_for_picks(db, buckets, payload.picks)
    offering_ids = [o.id for o in resolved.values()]

    # Lock-then-check pattern: acquire a row-level lock on any existing
    # selection row for this scope BEFORE checking CONFIRMED status.
    # This serialises concurrent confirm requests for the same student +
    # term + semester — the second one waits until the first commits, then
    # sees CONFIRMED and returns 409, preventing double seat booking.
    scope_result = await db.execute(
        select(StudentGroupSelection).where(
            StudentGroupSelection.student_id == profile.id,
            StudentGroupSelection.academic_term_id == academic_term_id,
            StudentGroupSelection.study_year == study_year,
            StudentGroupSelection.study_semester == study_semester,
        ).with_for_update()
    )
    sel = scope_result.scalars().first()

    if sel is not None and sel.status in (
        GroupSelectionStatus.CONFIRMED,
        GroupSelectionStatus.WAITLISTED,
    ):
        raise ConflictError("You already have a confirmed selection for this semester")

    core_groups = [
        o.group_number
        for b in buckets
        if b.selection_policy == SelectionPolicy.CHOOSE_FACULTY
        for o in [resolved.get(b.id)]
        if o is not None
    ]
    group_number = core_groups[0] if core_groups else None

    payload_json = {
        "picks": {k: str(v) for k, v in payload.picks.items()},
    }

    if sel is None:
        sel = StudentGroupSelection(
            student_id=profile.id,
            academic_term_id=academic_term_id,
            department_id=department_id,
            study_year=study_year,
            study_semester=study_semester,
        )
        db.add(sel)

    sel.group_number = group_number
    sel.selection_payload = payload_json
    sel.status = GroupSelectionStatus.CONFIRMED
    sel.confirmed_at = datetime.now(timezone.utc)
    sel.published_scenario_id = window.published_scenario_id
    sel.published_job_id = scenario.published_job_id if scenario else None
    sel.invalidation_reason = None
    await db.flush()

    # Build effective-max map so booking service can enforce the institution-level
    # cap even when CourseOffering.max_seats is NULL (legacy/reimported data).
    eff_max: int | None = None
    if window.institution_id:
        eff_max = await _resolve_effective_max_seats(
            db, window.institution_id, academic_term_id, department_id
        )
    effective_max_map: dict[str, int] | None = None
    if eff_max is not None:
        effective_max_map = {str(oid): eff_max for oid in offering_ids}

    registrations = await seat_bundle_svc.book_selection_bundle(
        db,
        student_id=profile.id,
        offering_ids=offering_ids,
        group_selection=sel,
        effective_max_map=effective_max_map,
    )

    # Publish real-time seat update immediately — do NOT wait for the broadcaster tick.
    try:
        partial = await seat_bundle_svc.get_released_offerings_snapshot(db, offering_ids)
        if partial:
            await cache_svc.publish_seat_update(
                department_id, study_semester, partial, scope="partial"
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("SSE seat publish failed after confirm", error=str(exc))

    return ConfirmSelectionResponse(
        selection=GroupSelectionResponse.model_validate(sel),
        registration_ids=[r.id for r in registrations],
    )


async def drop_selection(
    db: AsyncSession,
    profile: StudentProfile,
    academic_term_id: uuid.UUID,
) -> GroupSelectionResponse:
    if profile.semester is None:
        raise ValidationError(
            "Your student profile has no semester set. "
            "Ask your department office to update your academic record."
        )
    department_id = await _get_student_department_id(db, profile)
    study_semester = profile.semester
    study_year = _study_year_from_profile(profile)

    window = await window_svc.get_window(
        db, academic_term_id, department_id, study_semester
    )
    if window is None:
        raise NotFoundError("Selection window not found")

    phase = window_svc.compute_effective_phase(window)
    now = datetime.now(timezone.utc)
    can_drop = phase in ("OPEN", "PREVIEW") or (
        window.allow_changes_until is not None and now <= window.allow_changes_until
    )
    if not can_drop:
        raise ValidationError("Cannot drop selection — window is closed")

    result = await db.execute(
        select(StudentGroupSelection).where(
            StudentGroupSelection.student_id == profile.id,
            StudentGroupSelection.academic_term_id == academic_term_id,
            StudentGroupSelection.study_year == study_year,
            StudentGroupSelection.study_semester == study_semester,
            StudentGroupSelection.status == GroupSelectionStatus.CONFIRMED,
        ).with_for_update()
    )
    sel = result.scalars().first()
    if sel is None:
        raise NotFoundError("No confirmed selection to drop")

    # Capture released offering IDs before they're marked DROPPED.
    from app.models.student import StudentRegistration, RegistrationStatus  # noqa: PLC0415
    reg_result = await db.execute(
        select(StudentRegistration.offering_id).where(
            StudentRegistration.student_group_selection_id == sel.id,
            StudentRegistration.status == RegistrationStatus.CONFIRMED,
        )
    )
    released_offering_ids = [str(row[0]) for row in reg_result.all()]

    await seat_bundle_svc.release_selection_bundle(db, sel)

    # Publish real-time seat update for the released offerings.
    try:
        if released_offering_ids:
            live = await cache_svc.get_live_seat_counts(released_offering_ids)
            max_map = await cache_svc.get_cohort_max_seats_map(department_id, study_semester)
            partial: list[dict] = []
            for oid in released_offering_ids:
                remaining = live.get(oid)
                max_seats = max_map.get(oid)
                booked = (
                    max(0, max_seats - remaining)
                    if (max_seats is not None and remaining is not None)
                    else 0
                )
                partial.append({
                    "offering_id": oid,
                    "booked_seats": booked,
                    "seats_remaining": remaining,
                    "is_frozen": False,
                })
            await cache_svc.publish_seat_update(
                department_id, study_semester, partial, scope="partial"
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("SSE seat publish failed after drop", error=str(exc))

    return GroupSelectionResponse.model_validate(sel)


async def get_my_timetable(
    db: AsyncSession,
    profile: StudentProfile,
    academic_term_id: uuid.UUID,
) -> tuple[list[ScheduledSessionResponse], dict | None]:
    if profile.semester is None:
        return [], None
    study_semester = profile.semester
    study_year = _study_year_from_profile(profile)

    result = await db.execute(
        select(StudentGroupSelection).where(
            StudentGroupSelection.student_id == profile.id,
            StudentGroupSelection.academic_term_id == academic_term_id,
            StudentGroupSelection.study_year == study_year,
            StudentGroupSelection.study_semester == study_semester,
            StudentGroupSelection.status == GroupSelectionStatus.CONFIRMED,
        )
    )
    sel = result.scalars().first()

    # Always resolve window + scenario — needed for both HYBRID and batch paths
    department_id = await _get_student_department_id(db, profile)
    window = await window_svc.get_window(
        db, academic_term_id, department_id, study_semester
    )
    if window is None or not window.published_scenario_id:
        return [], None

    scenario = await db.get(Scenario, window.published_scenario_id)
    if scenario is None or scenario.published_job_id is None:
        return [], None

    if sel is None:
        # In HYBRID / FFCS / ELECTIVE modes students must confirm their picks first.
        # Showing sessions before confirmation would display every group's sessions
        # (since the student's batch_id → COHORT target → all group buckets).
        scheduling_mode = (scenario.scheduling_mode or "TRADITIONAL").upper()
        if scheduling_mode in ("HYBRID", "FFCS", "ELECTIVE"):
            return [], None

        # TRADITIONAL: no confirmed HYBRID selection — serve all cohort sessions
        # for batch-assigned students (student is pre-assigned to a batch/section).
        if profile.batch_id is None:
            return [], None

        req_result = await db.execute(
            select(TargetRequirement).where(
                TargetRequirement.target_id == profile.batch_id
            )
        )
        requirements = list(req_result.scalars().all())
        if not requirements:
            return [], None

        bucket_ids = [req.bucket_id for req in requirements]
        off_result = await db.execute(
            select(CourseOffering.id).where(
                CourseOffering.bucket_id.in_(bucket_ids)
            )
        )
        offering_ids = {str(r[0]) for r in off_result.all()}
        if not offering_ids:
            return [], None

        rows = await schedule_svc.get_by_scenario(db, scenario.id)
        if offering_ids:
            sessions = [
                ScheduledSessionResponse.model_validate(row)
                for row in rows
                if str(row.get("offering_id")) in offering_ids
            ]
        else:
            # No TargetRequirements for this batch yet — fall back to all
            # sessions for the student's dept/sem so the timetable is never blank.
            dept_id_str = str(department_id)
            sessions = [
                ScheduledSessionResponse.model_validate(row)
                for row in rows
                if (
                    row.get("department_id") == dept_id_str and
                    row.get("study_semester") == study_semester
                )
            ]
        slot_definitions = await resolve_slots_for_scenario(db, scenario)
        return sessions, slot_definitions

    # Confirmed HYBRID selection — check staleness then filter by picks
    if await invalidation_svc.drop_if_publish_snapshot_stale(
        db,
        sel,
        window,
        scenario,
        institution_id=window.institution_id,
    ):
        return [], None

    picks = sel.selection_payload.get("picks", {})
    offering_id_set = {str(v) for v in picks.values()}

    # ── Expand to include theory-sibling offerings ──────────────────────────
    # For batched lab courses the student picks the batch offering (which only
    # has lab sessions).  The shared theory sessions live on a sibling offering
    # in the SAME bucket with the SAME (course_id, faculty_id) that was hidden
    # from the menu.  We must include those sessions in the confirmed timetable.
    if offering_id_set:
        picked_uuids = [uuid.UUID(oid) for oid in offering_id_set if _is_valid_uuid(oid)]
        if picked_uuids:
            off_r = await db.execute(
                select(
                    CourseOffering.id,
                    CourseOffering.bucket_id,
                    CourseOffering.course_id,
                    CourseOffering.faculty_id,
                ).where(CourseOffering.id.in_(picked_uuids))
            )
            picked_rows = off_r.all()
            bucket_ids = list({r.bucket_id for r in picked_rows if r.bucket_id})
            if bucket_ids:
                sib_r = await db.execute(
                    select(
                        CourseOffering.id,
                        CourseOffering.bucket_id,
                        CourseOffering.course_id,
                        CourseOffering.faculty_id,
                        CourseOffering.batch_number,
                    ).where(
                        CourseOffering.bucket_id.in_(bucket_ids),
                        CourseOffering.id.notin_(picked_uuids),
                    )
                )
                # Index picked offerings by (bucket_id, course_id, faculty_id)
                picked_index = {
                    (str(r.bucket_id), str(r.course_id), str(r.faculty_id) if r.faculty_id else "")
                    for r in picked_rows
                }
                for r in sib_r.all():
                    key = (
                        str(r.bucket_id),
                        str(r.course_id),
                        str(r.faculty_id) if r.faculty_id else "",
                    )
                    # Only pull theory siblings (batch_number IS NULL).
                    # Batch siblings (batch_number = 1, 2, …) must NOT be included —
                    # the student chose a specific batch and should only see that batch's
                    # lab sessions, not the other batch's.
                    if key in picked_index and r.batch_number is None:
                        offering_id_set.add(str(r.id))

    rows = await schedule_svc.get_by_scenario(db, scenario.id)
    filtered = [
        ScheduledSessionResponse.model_validate(row)
        for row in rows
        if str(row.get("offering_id")) in offering_id_set
    ]
    slot_definitions = await resolve_slots_for_scenario(db, scenario)
    return filtered, slot_definitions


def _is_valid_uuid(val: str) -> bool:
    try:
        uuid.UUID(val)
        return True
    except (ValueError, AttributeError):
        return False
