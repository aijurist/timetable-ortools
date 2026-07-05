"""Redis cache helpers for student selection menu, seat counts, and idempotency.

Two-layer caching strategy
--------------------------
* **Structure cache** (``selection:menu:{dept}:{sem}``):
    Caches the menu skeleton — buckets, offering metadata, course/faculty names.
    TTL = 5 minutes.  Invalidated on structural changes (offering freeze, window
    phase change) but NOT on every confirm/drop, because seat counts are not
    stored here.

* **Seat-count counters** (``offering:seats:{offering_id}``):
    Redis atomic integers maintained by ``offering_seat_bundle_service`` and
    ``curriculum_service``.  Never cached inside the menu snapshot — always
    read live via ``get_live_seat_counts``.  This means seat counts are always
    accurate regardless of menu cache state.

* **SSE seat-update channel** (``selection:seats:{dept}:{sem}``):
    Redis pub/sub channel.  A background broadcaster publishes a full cohort
    snapshot every ``SELECTION_SEATS_STREAM_INTERVAL_SECONDS`` (default 3 s)
    for channels with live subscribers; confirm/drop also publishes partial
    updates immediately.

* **Idempotency keys** (``selection:idempotency:{key}``):
    24-hour cache of successful confirm responses to handle client retries.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Optional

from app.core.redis_client import get_redis, offering_seats_key


# ---------------------------------------------------------------------------
# Key helpers
# ---------------------------------------------------------------------------

def _menu_key(dept_id: uuid.UUID, study_semester: int) -> str:
    return f"selection:menu:{dept_id}:{study_semester}"


def _seats_channel(dept_id: uuid.UUID, study_semester: int) -> str:
    """Redis pub/sub channel for real-time seat-count updates."""
    return f"selection:seats:{dept_id}:{study_semester}"


def _active_channel_member(dept_id: uuid.UUID, study_semester: int) -> str:
    return f"{dept_id}:{study_semester}"


def _active_channel_ref_key(dept_id: uuid.UUID, study_semester: int) -> str:
    return f"selection:seats:refs:{dept_id}:{study_semester}"


ACTIVE_SEATS_CHANNELS_KEY = "selection:seats:active_channels"


def _idempotency_key(key: str) -> str:
    return f"selection:idempotency:{key}"


def _sse_user_context_key(user_id: uuid.UUID | str) -> str:
    return f"selection:sse:ctx:{user_id}"


async def set_sse_stream_context(
    user_id: uuid.UUID | str,
    dept_id: uuid.UUID,
    study_semester: int,
) -> None:
    """Cache dept+semester for the seat SSE route (avoids DB on every reconnect)."""
    async with get_redis() as r:
        await r.set(
            _sse_user_context_key(user_id),
            json.dumps(
                {"dept_id": str(dept_id), "study_semester": study_semester},
            ),
            ex=7200,
        )


async def get_sse_stream_context(
    user_id: uuid.UUID | str,
) -> tuple[uuid.UUID, int] | None:
    """Return cached (dept_id, study_semester) for seat SSE, or None if cold."""
    async with get_redis() as r:
        raw = await r.get(_sse_user_context_key(user_id))
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return uuid.UUID(data["dept_id"]), int(data["study_semester"])
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------------
# Menu structure cache (excludes seat counts)
# ---------------------------------------------------------------------------

async def get_cached_menu(
    dept_id: uuid.UUID, study_semester: int
) -> Optional[dict[str, Any]]:
    async with get_redis() as r:
        raw = await r.get(_menu_key(dept_id, study_semester))
        if raw:
            return json.loads(raw)
        return None


async def set_cached_menu(
    dept_id: uuid.UUID,
    study_semester: int,
    payload: dict[str, Any],
    ttl_seconds: int = 300,  # 5 min — structural changes are infrequent
) -> None:
    async with get_redis() as r:
        await r.set(
            _menu_key(dept_id, study_semester),
            json.dumps(payload, default=str),
            ex=ttl_seconds,
        )


async def invalidate_menu_cache(
    dept_id: uuid.UUID, study_semester: int
) -> None:
    async with get_redis() as r:
        await r.delete(_menu_key(dept_id, study_semester))


# ---------------------------------------------------------------------------
# Live seat-count reads (never cached — always current)
# ---------------------------------------------------------------------------

async def get_live_seat_counts(offering_ids: list[str]) -> dict[str, int]:
    """Fetch remaining-seat counts for a batch of offerings from Redis.

    Returns a mapping of offering_id → remaining seats.  Offerings whose
    counter key is absent (not yet seeded) are omitted; callers fall back to
    the DB ``booked_seats`` column for those.

    Uses a single MGET pipeline to minimise round-trips.
    """
    if not offering_ids:
        return {}
    keys = [offering_seats_key(oid) for oid in offering_ids]
    async with get_redis() as r:
        values = await r.mget(*keys)
    result: dict[str, int] = {}
    for oid, val in zip(offering_ids, values):
        if val is not None:
            try:
                result[oid] = int(val)
            except (ValueError, TypeError):
                pass
    return result


# ---------------------------------------------------------------------------
# Seat-count update helpers (called by booking services)
# ---------------------------------------------------------------------------

_UNCAPPED_SENTINEL = 10_000  # Written for uncapped offerings to keep fast-fail path warm


async def seed_missing_seat_counters(
    offerings: list[tuple[str, int, int | None]],
) -> None:
    """Populate ``offering:seats:{id}`` for keys that are not yet in Redis.

    Called on menu load so the first student to open the portal seeds counters
    from the durable ``booked_seats`` column.  Uses SET NX so concurrent menu
    loads do not overwrite fresher values written by a recent confirm.

    Uncapped offerings (max_seats=None) get a large sentinel value so the
    Redis fast-fail path stays warm and DB lock contention stays low.
    """
    if not offerings:
        return
    async with get_redis() as r:
        for oid, booked, max_seats in offerings:
            remaining = (
                max(0, max_seats - booked) if max_seats is not None else _UNCAPPED_SENTINEL
            )
            key = offering_seats_key(oid)
            await r.set(key, remaining, ex=3600, nx=True)


async def update_seat_counter(
    offering_id: str | uuid.UUID,
    *,
    remaining: int,
    max_seats: int | None,
) -> None:
    """Write the remaining-seat count to Redis after a DB booking/release.

    TTL is 5 min when full (seat is a hot key — re-check DB after expiry)
    and 1 hour otherwise.
    """
    key = offering_seats_key(offering_id)
    ttl = 300 if remaining <= 0 else 3600
    async with get_redis() as r:
        await r.set(key, remaining, ex=ttl)


async def fast_fail_check(offering_id: str | uuid.UUID) -> bool:
    """Return True if Redis counter says the offering is full.

    False means either there are seats left OR the key is not yet seeded
    (in which case the DB FOR UPDATE is the authority).
    """
    async with get_redis() as r:
        val = await r.get(offering_seats_key(offering_id))
    if val is None:
        return False  # not seeded — let DB decide
    try:
        return int(val) <= 0
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# SSE seat-update pub/sub
# ---------------------------------------------------------------------------

async def register_seats_stream(
    dept_id: uuid.UUID,
    study_semester: int,
) -> None:
    """Track an open SSE connection so the broadcaster ticks this channel."""
    member = _active_channel_member(dept_id, study_semester)
    ref_key = _active_channel_ref_key(dept_id, study_semester)
    
    script = """
    local count = redis.call('INCR', KEYS[1])
    if count == 1 then
        redis.call('SADD', KEYS[2], ARGV[1])
    end
    redis.call('EXPIRE', KEYS[1], 7200)
    return count
    """
    async with get_redis() as r:
        count = await r.eval(script, 2, ref_key, ACTIVE_SEATS_CHANNELS_KEY, member)

    if count == 1:
        await publish_cohort_seat_update(dept_id, study_semester, scope="full")


async def unregister_seats_stream(
    dept_id: uuid.UUID,
    study_semester: int,
) -> None:
    """Decrement SSE ref-count; remove channel from active set when last client leaves."""
    member = _active_channel_member(dept_id, study_semester)
    ref_key = _active_channel_ref_key(dept_id, study_semester)
    
    script = """
    local count = redis.call('DECR', KEYS[1])
    if count <= 0 then
        redis.call('SET', KEYS[1], 0, 'EX', 60)
        redis.call('SREM', KEYS[2], ARGV[1])
    end
    return count
    """
    async with get_redis() as r:
        await r.eval(script, 2, ref_key, ACTIVE_SEATS_CHANNELS_KEY, member)


def _cohort_seat_index_key(dept_id: uuid.UUID, study_semester: int) -> str:
    """Offering metadata for SSE snapshots — survives menu structure invalidation."""
    return f"selection:cohort_seats:{dept_id}:{study_semester}"


async def refresh_cohort_seat_index(
    dept_id: uuid.UUID,
    study_semester: int,
    offerings: list[dict[str, Any]],
) -> None:
    """Persist offering ids + caps for the SSE broadcaster (not per-student)."""
    if not offerings:
        return
    async with get_redis() as r:
        await r.set(
            _cohort_seat_index_key(dept_id, study_semester),
            json.dumps(offerings, default=str),
            ex=7200,
        )


async def _load_cohort_offering_rows(
    dept_id: uuid.UUID,
    study_semester: int,
) -> list[tuple[str, int | None, bool]]:
    """Return (offering_id, max_seats, is_frozen) rows for a dept cohort."""
    async with get_redis() as r:
        raw = await r.get(_cohort_seat_index_key(dept_id, study_semester))
    if raw:
        try:
            rows = json.loads(raw)
            return [
                (
                    str(row["offering_id"]),
                    row.get("max_seats"),
                    bool(row.get("is_frozen", False)),
                )
                for row in rows
                if row.get("offering_id")
            ]
        except (TypeError, KeyError, json.JSONDecodeError):
            pass

    cached = await get_cached_menu(dept_id, study_semester)
    if cached is None:
        return []

    fallback: list[tuple[str, int | None, bool]] = []
    for bucket in cached.get("bucket_items", []):
        for offering in bucket.get("offerings", []):
            fallback.append(
                (
                    str(offering["id"]),
                    offering.get("max_seats"),
                    bool(offering.get("is_frozen", False)),
                )
            )
    return fallback


async def get_cohort_max_seats_map(
    dept_id: uuid.UUID,
    study_semester: int,
) -> dict[str, int | None]:
    """Return offering_id → max_seats from the cohort index (or menu cache fallback)."""
    rows = await _load_cohort_offering_rows(dept_id, study_semester)
    return {oid: max_s for oid, max_s, _ in rows}


async def build_cohort_seat_snapshot(
    dept_id: uuid.UUID,
    study_semester: int,
) -> list[dict[str, Any]]:
    """Build a full cohort seat snapshot from cohort index + live Redis counters."""
    offering_rows = await _load_cohort_offering_rows(dept_id, study_semester)
    if not offering_rows:
        return []

    offering_ids = [row[0] for row in offering_rows]
    live_seats = await get_live_seat_counts(offering_ids)

    snapshot: list[dict[str, Any]] = []
    for oid, max_seats, is_frozen in offering_rows:
        remaining = live_seats.get(oid)
        if remaining is not None and max_seats is not None:
            booked = max(0, max_seats - remaining)
        elif remaining is not None:
            booked = 0
        else:
            booked = 0
        snapshot.append(
            {
                "offering_id": oid,
                "booked_seats": booked,
                "seats_remaining": remaining,
                "is_frozen": is_frozen,
            }
        )
    return snapshot


async def publish_cohort_seat_update(
    dept_id: uuid.UUID,
    study_semester: int,
    *,
    scope: str = "full",
) -> None:
    """Build and publish a cohort-wide seat snapshot (no-op when index is cold)."""
    snapshot = await build_cohort_seat_snapshot(dept_id, study_semester)
    if snapshot:
        await publish_seat_update(dept_id, study_semester, snapshot, scope=scope)


async def publish_seat_update(
    dept_id: uuid.UUID,
    study_semester: int,
    offerings_snapshot: list[dict[str, Any]],
    *,
    scope: str = "partial",
) -> None:
    """Publish a seat-count snapshot to the SSE channel.

    ``offerings_snapshot`` is a list of dicts with keys:
        offering_id, booked_seats, seats_remaining, is_frozen

    ``scope`` is ``"full"`` for periodic cohort broadcasts or ``"partial"`` after
    confirm/drop.  Clients use this to decide whether to refetch the menu.

    One PUBLISH call fans out to all uvicorn workers that have students
    subscribed via ``GET /api/v1/selection/seats/stream``.
    """
    channel = _seats_channel(dept_id, study_semester)
    payload = json.dumps(
        {
            "type": "seat_update",
            "scope": scope,
            "offerings": offerings_snapshot,
        },
        default=str,
    )
    async with get_redis() as r:
        await r.publish(channel, payload)


def seats_pub_sub_channel(dept_id: uuid.UUID, study_semester: int) -> str:
    """Public accessor for the channel key — used by the SSE route."""
    return _seats_channel(dept_id, study_semester)


# ---------------------------------------------------------------------------
# Idempotency cache
# ---------------------------------------------------------------------------

async def get_idempotency_result(key: str) -> Optional[dict[str, Any]]:
    async with get_redis() as r:
        raw = await r.get(_idempotency_key(key))
        if raw:
            return json.loads(raw)
        return None


async def set_idempotency_result(
    key: str, payload: dict[str, Any], ttl_seconds: int = 86400
) -> None:
    async with get_redis() as r:
        await r.set(
            _idempotency_key(key),
            json.dumps(payload, default=str),
            ex=ttl_seconds,
        )
