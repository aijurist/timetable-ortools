"""Atomic multi-offering seat booking for HYBRID selection confirm.

Seat-counting strategy
----------------------
Redis is the **authoritative live counter** for seat availability.  PostgreSQL
``course_offerings.booked_seats`` is the durable audit trail.

Book flow
~~~~~~~~~
1. For each offering: ``GET offering:seats:{id}``
   - If value exists and ≤ 0 → ``ConflictError`` immediately (no DB touch).
   - If key absent (not yet seeded) → proceed to DB; seed after success.
2. ``SELECT CourseOffering FOR UPDATE`` in sorted order (deadlock-safe).
3. DB check (frozen, max_seats) — source of truth guard.
4. ``booked_seats += 1``, create/reactivate ``StudentRegistration``.
5. ``await db.flush()``
6. Write updated remaining count back to Redis.

Release flow
~~~~~~~~~~~~
1. ``SELECT FOR UPDATE`` on each offering.
2. ``booked_seats -= 1`` (floor 0).
3. ``flush()``.
4. ``INCR offering:seats:{id}`` (or seed from fresh DB value).

The Redis fast-fail at step 1 means that once an offering fills up, all
subsequent confirm attempts for that offering are rejected in <1 ms without
consuming a DB connection — freeing the shared pool for students booking other
classes.
"""
from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, ValidationError
from app.core.logger import logger
from app.models.curriculum import CourseOffering
from app.models.student import RegistrationStatus, StudentRegistration
from app.models.selection import GroupSelectionStatus, StudentGroupSelection

import app.services.selection_cache_service as cache_svc


async def lock_offerings_ordered(
    db: AsyncSession, offering_ids: Sequence[uuid.UUID]
) -> list[CourseOffering]:
    """SELECT FOR UPDATE on all offerings in deterministic (sorted UUID) order.

    Sorting prevents deadlocks when two concurrent transactions try to lock
    overlapping sets of offerings.
    """
    sorted_ids = sorted(set(offering_ids), key=str)
    if not sorted_ids:
        raise ValidationError("No offerings to book")

    result = await db.execute(
        select(CourseOffering)
        .where(CourseOffering.id.in_(sorted_ids))
        .order_by(CourseOffering.id)
        .with_for_update()
        .execution_options(populate_existing=True)  # force-refresh identity map after lock
    )
    offerings = list(result.scalars().all())
    if len(offerings) != len(sorted_ids):
        found = {o.id for o in offerings}
        missing = [oid for oid in sorted_ids if oid not in found]
        raise ValidationError(f"Offerings not found: {missing}")
    return offerings


def verify_seats_available(
    offerings: Sequence[CourseOffering],
    effective_max_map: dict[str, int] | None = None,
) -> None:
    """DB-level guard (runs after the FOR UPDATE lock)."""
    for offering in offerings:
        if offering.is_frozen:
            raise ValidationError(
                f"Offering {offering.id} is frozen — registration blocked"
            )
        eff_max = offering.max_seats
        if eff_max is None and effective_max_map:
            eff_max = effective_max_map.get(str(offering.id))
        if eff_max is not None and offering.booked_seats >= eff_max:
            raise ConflictError(
                f"Offering {offering.id} is full "
                f"({offering.booked_seats}/{eff_max} seats)"
            )


_UNCAPPED_SENTINEL = 10_000  # Sentinel written for offerings with no max_seats


async def _redis_fast_fail(offering_ids: Sequence[uuid.UUID]) -> None:
    """Pre-check Redis counters before touching the DB pool.

    Raises ``ConflictError`` for the first offering whose counter shows ≤ 0
    seats remaining.  Offerings without a cached counter are skipped (the DB
    FOR UPDATE is the authority for those).  Values ≥ _UNCAPPED_SENTINEL
    indicate an uncapped offering and are never rejected here.

    This is NOT the source of truth — it's a short-circuit optimisation that
    lets 930 out of 1 000 rushing students hear "full" in <1 ms without ever
    competing for a DB connection.
    """
    live = await cache_svc.get_live_seat_counts([str(oid) for oid in offering_ids])
    for oid in offering_ids:
        remaining = live.get(str(oid))
        if remaining is None:
            continue  # no counter yet — let DB FOR UPDATE decide
        if remaining >= _UNCAPPED_SENTINEL:
            continue  # sentinel for uncapped offering — never reject here
        if remaining <= 0:
            raise ConflictError(
                "One of your selected offerings is full — all seats are taken. "
                "Please choose another option."
            )


async def _sync_redis_after_book(
    offerings: Sequence[CourseOffering],
    effective_max_map: dict[str, int] | None = None,
) -> None:
    """Write updated seat counts to Redis after a successful DB increment.

    ``effective_max_map`` maps offering_id str → effective cap (from
    SelectionAccessConfig) used when the offering itself has no max_seats.

    For uncapped offerings (no max_seats, no effective_max) we write a large
    sentinel (10 000) so the Redis fast-fail path stays warm and avoids 100%
    DB lock contention on every booking.  The DB FOR UPDATE is still the
    authoritative guard; the sentinel just means the fast-fail never fires.
    """
    for offering in offerings:
        eff_max = offering.max_seats
        if eff_max is None and effective_max_map:
            eff_max = effective_max_map.get(str(offering.id))
        if eff_max is not None:
            remaining = max(0, eff_max - offering.booked_seats)
        else:
            remaining = _UNCAPPED_SENTINEL
        await cache_svc.update_seat_counter(
            offering.id, remaining=remaining, max_seats=eff_max
        )


async def book_selection_bundle(
    db: AsyncSession,
    *,
    student_id: uuid.UUID,
    offering_ids: Sequence[uuid.UUID],
    group_selection: StudentGroupSelection,
    effective_max_map: dict[str, int] | None = None,
) -> list[StudentRegistration]:
    """Atomically book all offerings and create registration rows.

    1. Redis fast-fail (no DB connection used for obviously-full offerings).
    2. SELECT FOR UPDATE on all offerings (deadlock-safe sorted order).
    3. DB-level seat/frozen guard.
    4. Reuse DROPPED rows (post-invalidation re-confirm) or INSERT new ones.
    5. Sync Redis counters.

    Returns the list of ``StudentRegistration`` rows (flushed but not committed).
    """
    # Step 1 — Redis pre-check (reject in <1 ms if already full)
    await _redis_fast_fail(offering_ids)

    # Step 2 — acquire row-level locks in sorted order
    offerings = await lock_offerings_ordered(db, offering_ids)

    # Step 3 — authoritative DB guard
    verify_seats_available(offerings, effective_max_map=effective_max_map)

    existing_result = await db.execute(
        select(StudentRegistration).where(
            StudentRegistration.student_id == student_id,
            StudentRegistration.offering_id.in_([o.id for o in offerings]),
        )
    )
    existing_by_offering = {
        reg.offering_id: reg for reg in existing_result.scalars().all()
    }

    registrations: list[StudentRegistration] = []
    for offering in offerings:
        existing = existing_by_offering.get(offering.id)
        if existing is not None:
            if existing.status == RegistrationStatus.CONFIRMED:
                raise ConflictError(
                    f"Student already has an active registration for offering {offering.id}"
                )
            if existing.status == RegistrationStatus.WAITLISTED:
                # Waitlisted rows must be handled by admin — do not auto-promote
                # here as the waitlist position and notification logic lives
                # outside this service.
                raise ConflictError(
                    f"You are on the waitlist for offering {offering.id}. "
                    "Contact your department office to confirm your place."
                )
            # DROPPED → reactivate (re-check cap; seat was released when dropped)
            eff_max = offering.max_seats
            if eff_max is None and effective_max_map:
                eff_max = effective_max_map.get(str(offering.id))
            if eff_max is not None and offering.booked_seats >= eff_max:
                raise ConflictError(
                    f"Offering {offering.id} is full "
                    f"({offering.booked_seats}/{eff_max} seats)"
                )
            offering.booked_seats += 1
            existing.status = RegistrationStatus.CONFIRMED
            existing.student_group_selection_id = group_selection.id
            registrations.append(existing)
            continue

        offering.booked_seats += 1
        reg = StudentRegistration(
            student_id=student_id,
            offering_id=offering.id,
            status=RegistrationStatus.CONFIRMED,
            student_group_selection_id=group_selection.id,
        )
        db.add(reg)
        registrations.append(reg)

    await db.flush()

    # Step 5 — update Redis counters (non-critical; failures are logged, not raised)
    try:
        await _sync_redis_after_book(offerings, effective_max_map=effective_max_map)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis seat counter sync failed after bundle book", error=str(exc))

    logger.info(
        "Selection bundle booked",
        student_id=str(student_id),
        selection_id=str(group_selection.id),
        offerings=len(offerings),
    )
    return registrations


async def release_selection_bundle(
    db: AsyncSession,
    group_selection: StudentGroupSelection,
) -> None:
    """Release seats for all registrations in a bundle."""
    import app.services.curriculum_service as curriculum_svc  # noqa: PLC0415

    result = await db.execute(
        select(StudentRegistration).where(
            StudentRegistration.student_group_selection_id == group_selection.id,
            StudentRegistration.status == RegistrationStatus.CONFIRMED,
        )
    )
    regs = list(result.scalars().all())
    for reg in regs:
        await curriculum_svc.release_seat(db, reg.offering_id)
        reg.status = RegistrationStatus.DROPPED

    group_selection.status = GroupSelectionStatus.DROPPED
    await db.flush()


async def get_released_offerings_snapshot(
    db: AsyncSession,
    offering_ids: Sequence[uuid.UUID],
) -> list[dict]:
    """Load offerings by ID and return seat-count snapshot dicts for SSE publish.

    Prefers live Redis counters (already updated by _sync_redis_after_book)
    over DB columns so the SSE event reflects the effective cap even when
    CourseOffering.max_seats is NULL.
    """
    if not offering_ids:
        return []
    result = await db.execute(
        select(CourseOffering).where(CourseOffering.id.in_(list(offering_ids)))
    )
    offerings = result.scalars().all()

    # Read live Redis counters — these were just written by _sync_redis_after_book
    # and already incorporate the effective_max_seats fallback.
    live_seats = await cache_svc.get_live_seat_counts([str(o.id) for o in offerings])

    return [
        {
            "offering_id": str(o.id),
            "booked_seats": o.booked_seats,
            "seats_remaining": (
                live_seats[str(o.id)]
                if str(o.id) in live_seats
                else (max(0, o.max_seats - o.booked_seats) if o.max_seats is not None else None)
            ),
            "is_frozen": o.is_frozen,
        }
        for o in offerings
    ]
