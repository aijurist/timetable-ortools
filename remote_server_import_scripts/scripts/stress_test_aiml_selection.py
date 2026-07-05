"""
AIML Semester 5 & 7 — Selection Stress Test
============================================

Tests the concurrent student selection flow end-to-end via the real
service layer (SQLAlchemy async sessions + Redis fast-fail) — no HTTP needed.

Run AFTER scripts/fix_selection_data.py (clears state, seeds PE eligibility).

Scheduling target IDs (scheduling_targets table):
  AIML S5: 1c08accb-6faa-4f47-83b0-f4ab49b6a5b7
  AIML S7: 07730e55-08c1-447e-868f-5596a33a96aa

Bucket structure (AIML S5):
  02b56a34  CHOOSE_FACULTY  AI23531  bat=1/2 max=35, theory max=70
  123304d0  CHOOSE_FACULTY  AI23521  theory-only max=70/140
  2bc47673  CHOOSE_FACULTY  AD23632  bat=1/2 max=35, theory max=70
  5008b7c3  CHOOSE_FACULTY  AI23512/CS23532  theory-only
  549a5009  CHOOSE_FACULTY  CS23532/AI23512  bat=1/2 max=35 + theory
  5f0d117e  CHOOSE_COURSE   AI23PE31  4 offerings max=70 each
  dc3b6b2d  FIXED_BATCH     (supplementary, not student-selectable)

Cross-bucket uniqueness (S5): 5008b7c3 & 549a5009 share AI23512/CS23532.

Bucket structure (AIML S7):
  19a48222  CHOOSE_FACULTY  IT23731  bat=1/2 max=35, theory max=70
  e4531c49  CHOOSE_FACULTY  AI23711/AD23731  theory-only max=70
  fbc0c733  CHOOSE_FACULTY  AD23731/AI23711  theory-only
  c69892ad  CHOOSE_COURSE   AI23PE41  1 offering max=165 (35 students expected 409)
"""

from __future__ import annotations

import asyncio
import sys
import os
import time
import uuid
from dataclasses import dataclass, field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DATABASE_URL = "postgresql+asyncpg://postgres:dev@localhost:5432/exovance_dev"
REDIS_URL    = "redis://localhost:6379/0"

TERM_ID        = uuid.UUID("fd9f461a-1d43-4dd1-bc61-bfefa93ee363")
AIML_DEPT      = uuid.UUID("6b778751-dfeb-4ad3-ac7a-848bbc595dde")
# These are scheduling_targets.id values (NOT cohort IDs)
AIML_S5_TARGET = "1c08accb-6faa-4f47-83b0-f4ab49b6a5b7"
AIML_S7_TARGET = "07730e55-08c1-447e-868f-5596a33a96aa"


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class OfferingInfo:
    offering_id: str
    course_id: str
    max_seats: int | None
    batch_number: int | None


@dataclass
class BucketInfo:
    bucket_id: str
    policy: str

    offerings: list[OfferingInfo]

    @property
    def is_pe(self) -> bool:
        return self.policy == "CHOOSE_COURSE"

    @property
    def course_ids(self) -> set[str]:
        return {o.course_id for o in self.offerings}

    def bat_offerings(self, batch_number: int) -> list[OfferingInfo]:
        return [o for o in self.offerings if o.batch_number == batch_number]

    def theory_offerings(self) -> list[OfferingInfo]:
        return [o for o in self.offerings if o.batch_number is None]


@dataclass
class CohortData:
    students: list[str]
    buckets: list[BucketInfo]
    semester: int

    @property
    def pe_bucket(self) -> BucketInfo | None:
        return next((b for b in self.buckets if b.is_pe), None)

    @property
    def core_buckets(self) -> list[BucketInfo]:
        return [b for b in self.buckets if not b.is_pe]


@dataclass
class TestResult:
    phase: str
    successes: int = 0
    failures_409: int = 0
    failures_400: int = 0
    failures_other: int = 0
    errors: list[str] = field(default_factory=list)
    elapsed_s: float = 0.0

    @property
    def total(self) -> int:
        return self.successes + self.failures_409 + self.failures_400 + self.failures_other

    def print(self) -> None:
        print(f"\n{'--'*25}")
        print(f"Phase: {self.phase}")
        print(f"  Attempts   : {self.total}")
        print(f"  Succeeded  : {self.successes}")
        print(f"  Full / 409 : {self.failures_409}")
        print(f"  Bad picks  : {self.failures_400}")
        print(f"  Other err  : {self.failures_other}")
        print(f"  Elapsed    : {self.elapsed_s:.2f}s")
        if self.errors:
            print(f"  Sample errors:")
            for e in self.errors[:5]:
                print(f"    {e}")


# ---------------------------------------------------------------------------
# DB loading
# ---------------------------------------------------------------------------

async def load_cohort_data(
    session: AsyncSession,
    target_id: str,
    department_id: uuid.UUID,
    semester: int,
) -> CohortData:
    """Load students + buckets + offerings for a scheduling_target."""

    r = await session.execute(text("""
        SELECT sp.id::text
        FROM student_profiles sp
        JOIN users u ON u.id = sp.user_id
        WHERE u.department_id = :dept AND sp.semester = :sem
        ORDER BY sp.id
    """), {"dept": str(department_id), "sem": semester})
    students = [row[0] for row in r.all()]

    r = await session.execute(text("""
        SELECT ob.id::text, ob.selection_policy
        FROM target_requirements tr
        JOIN offering_buckets ob ON ob.id = tr.bucket_id
        WHERE tr.target_id = :tid
          AND ob.selection_policy IN ('CHOOSE_FACULTY', 'CHOOSE_COURSE')
        ORDER BY ob.selection_policy, ob.id
    """), {"tid": target_id})
    raw_buckets = r.all()

    buckets: list[BucketInfo] = []
    for b_id, policy in raw_buckets:
        r2 = await session.execute(text("""
            SELECT co.id::text, co.course_id::text, co.max_seats, co.batch_number
            FROM course_offerings co
            WHERE co.bucket_id = :bid
            ORDER BY co.batch_number NULLS LAST, co.id
        """), {"bid": b_id})
        offerings = [OfferingInfo(row[0], row[1], row[2], row[3]) for row in r2.all()]
        buckets.append(BucketInfo(b_id, policy, offerings))

    return CohortData(students, buckets, semester)


# ---------------------------------------------------------------------------
# Pick assignment
# ---------------------------------------------------------------------------

def build_picks(student_index: int, data: CohortData) -> dict[str, str] | None:
    """Build a course-unique picks dict for one student.

    For each bucket (processed in load order), selects one offering such that
    no two picks share the same course_id. Uses batch-preferred round-robin.
    """
    picks: dict[str, str] = {}
    picked_course_ids: set[str] = set()

    for bucket in data.buckets:
        if not bucket.offerings:
            return None

        if bucket.is_pe:
            idx = student_index % len(bucket.offerings)
            o = bucket.offerings[idx]
            picks[bucket.bucket_id] = o.offering_id
            picked_course_ids.add(o.course_id)
            continue

        bat = 1 if (student_index % 2 == 0) else 2
        bat_offers   = bucket.bat_offerings(bat)
        alt_bat      = bucket.bat_offerings(3 - bat)
        theory       = bucket.theory_offerings()

        chosen = None
        for pool in (bat_offers, alt_bat, theory):
            valid = [o for o in pool if o.course_id not in picked_course_ids]
            if valid:
                capped = [o for o in valid if o.max_seats is not None]
                sel = capped if capped else valid
                chosen = sel[student_index % len(sel)]
                break

        if chosen is None:
            valid_all = [o for o in bucket.offerings if o.course_id not in picked_course_ids]
            if not valid_all:
                return None
            capped = [o for o in valid_all if o.max_seats is not None]
            pool = capped if capped else valid_all
            chosen = pool[student_index % len(pool)]

        picks[bucket.bucket_id] = chosen.offering_id
        picked_course_ids.add(chosen.course_id)

    return picks if picks else None


# ---------------------------------------------------------------------------
# Service-layer confirm
# ---------------------------------------------------------------------------

async def confirm_for_student(
    session_factory: async_sessionmaker,
    student_id: str,
    picks: dict[str, str],
    semaphore: asyncio.Semaphore,
) -> tuple[bool, str]:
    async with semaphore:
        async with session_factory() as db:
            try:
                from app.models.student import StudentProfile
                from app.schemas.selection import SelectionPicksPayload
                import app.services.hybrid_selection_service as svc

                profile = await db.get(StudentProfile, uuid.UUID(student_id))
                if profile is None:
                    return False, f"Profile {student_id[:8]} not found"

                payload = SelectionPicksPayload(
                    picks={k: uuid.UUID(v) for k, v in picks.items()}
                )
                await svc.confirm_selection(db, profile, TERM_ID, payload)
                await db.commit()
                return True, ""
            except Exception as exc:
                await db.rollback()
                return False, f"{type(exc).__name__}: {str(exc)[:160]}"


def _classify_error(err: str) -> str:
    if not err:
        return "ok"
    e = err.lower()
    if ("is full" in e or "all seats are taken" in e or "already have" in e
            or "already has a confirmed" in e or "waitlist" in e):
        return "409"
    if ("validationerror" in e or "must select" in e or "different course" in e
            or "stale_menu" in e or "no selection window" in e or "window" in e
            or "no published" in e or "not found" in e or "no cohort" in e
            or "semester" in e):
        return "400"
    return "other"


# ---------------------------------------------------------------------------
# Phases
# ---------------------------------------------------------------------------

async def phase0_check(session_factory: async_sessionmaker) -> bool:
    print("\n" + "=" * 60)
    print("PHASE 0 — Prerequisite check")
    print("=" * 60)
    ok = True
    async with session_factory() as db:
        for sem in (5, 7):
            r = await db.execute(text("""
                SELECT status, published_scenario_id
                FROM department_selection_windows
                WHERE department_id = :dept AND study_semester = :sem
            """), {"dept": str(AIML_DEPT), "sem": sem})
            row = r.first()
            if not row:
                print(f"  S{sem}: NO WINDOW")
                ok = False
            else:
                pub = "ok" if row[1] else "NO SCENARIO"
                print(f"  S{sem}: window={row[0]}, scenario={pub}")
                if row[0] not in ("OPEN", "PREVIEW"):
                    ok = False

        r = await db.execute(text("""
            SELECT COUNT(*) FROM offering_buckets
            WHERE selection_policy='CHOOSE_FACULTY' AND name ILIKE '%Sup%'
        """))
        sup = r.scalar() or 0
        print(f"  Supplementary CHOOSE_FACULTY buckets remaining: {sup} {'(OK)' if sup == 0 else '(FAIL — run fix script)'}")
        if sup > 0:
            ok = False

        for sem in (5, 7):
            r = await db.execute(text("""
                SELECT COUNT(DISTINCT sce.student_id)
                FROM student_course_eligibility sce
                JOIN student_profiles sp ON sp.id = sce.student_id
                JOIN users u ON u.id = sp.user_id
                WHERE u.department_id = :dept AND sp.semester = :sem AND sce.source='PE'
            """), {"dept": str(AIML_DEPT), "sem": sem})
            cnt = r.scalar() or 0
            r2 = await db.execute(text("""
                SELECT COUNT(*) FROM student_profiles sp
                JOIN users u ON u.id = sp.user_id
                WHERE u.department_id = :dept AND sp.semester = :sem
            """), {"dept": str(AIML_DEPT), "sem": sem})
            total = r2.scalar() or 0
            print(f"  S{sem}: {total} students, {cnt} with PE eligibility")
            if cnt == 0 and total > 0:
                ok = False

    print("  => PASSED" if ok else "  => FAILED — fix prerequisites first")
    return ok


async def phase1_seat_limit(session_factory: async_sessionmaker, data: CohortData) -> TestResult:
    print("\n" + "=" * 60)
    print("PHASE 1 — Seat limit (80 students racing for 1 offering, max=35)")
    print("=" * 60)

    target_bucket: BucketInfo | None = None
    target_offering: OfferingInfo | None = None
    for b in data.core_buckets:
        bat1 = b.bat_offerings(1)
        if bat1 and bat1[0].max_seats == 35:
            target_bucket = b
            target_offering = sorted(bat1, key=lambda o: o.offering_id)[0]
            break

    if not target_bucket or not target_offering:
        print("  SKIP: no bat=1 max=35 offering found")
        return TestResult("Phase 1 — seat limit", errors=["no target"])

    print(f"  Bucket:   {target_bucket.bucket_id[:8]} ({len(target_bucket.offerings)} offerings)")
    print(f"  Offering: {target_offering.offering_id[:8]} (max=35, course={target_offering.course_id[:8]})")

    test_students = data.students[:80]
    result = TestResult("Phase 1 — seat limit (80 students, 1 offering max=35)")
    semaphore = asyncio.Semaphore(20)

    async def _run(idx: int, sid: str) -> None:
        picks = build_picks(idx, data)
        if picks is None:
            result.failures_other += 1
            result.errors.append(f"no picks for idx={idx}")
            return
        picks[target_bucket.bucket_id] = target_offering.offering_id
        success, err = await confirm_for_student(session_factory, sid, picks, semaphore)
        if success:
            result.successes += 1
        else:
            kind = _classify_error(err)
            if kind == "409":
                result.failures_409 += 1
            elif kind == "400":
                result.failures_400 += 1
                if len(result.errors) < 5:
                    result.errors.append(f"[400] {err}")
            else:
                result.failures_other += 1
                if len(result.errors) < 5:
                    result.errors.append(f"[other] {err}")

    t0 = time.monotonic()
    await asyncio.gather(*[_run(i, sid) for i, sid in enumerate(test_students)])
    result.elapsed_s = time.monotonic() - t0

    await _reset_students(session_factory, test_students)
    result.print()

    if result.failures_400 > 0:
        print(f"  FAIL: pick-validation errors (course uniqueness or window bug)")
    elif result.successes <= 35 and result.failures_409 >= 40:
        print(f"  PASS: seat cap enforced — {result.successes} confirmed, {result.failures_409} rejected")
    else:
        print(f"  WARN: {result.successes}/35 confirmed — investigate cap logic")

    return result


async def phase2_full_s5(session_factory: async_sessionmaker, data: CohortData) -> TestResult:
    print("\n" + "=" * 60)
    print(f"PHASE 2 — Full S5 enrollment ({len(data.students)} concurrent)")
    print("=" * 60)

    for b in data.core_buckets:
        bat1 = sum(o.max_seats or 0 for o in b.bat_offerings(1))
        bat2 = sum(o.max_seats or 0 for o in b.bat_offerings(2))
        theory = sum(o.max_seats or 0 for o in b.theory_offerings())
        courses = "/".join(sorted({o.course_id[:8] for o in b.offerings}))
        print(f"  {b.bucket_id[:8]}: bat1={bat1} bat2={bat2} theory={theory}  courses=[{courses}]")
    if data.pe_bucket:
        pe_cap = sum(o.max_seats or 0 for o in data.pe_bucket.offerings)
        print(f"  PE {data.pe_bucket.bucket_id[:8]}: cap={pe_cap} ({len(data.pe_bucket.offerings)} offerings)")

    result = TestResult(f"Phase 2 — full S5 ({len(data.students)} students)")
    semaphore = asyncio.Semaphore(30)

    async def _run(idx: int, sid: str) -> None:
        picks = build_picks(idx, data)
        if picks is None:
            result.failures_other += 1
            result.errors.append(f"S5[{idx}]: no valid picks")
            return
        success, err = await confirm_for_student(session_factory, sid, picks, semaphore)
        if success:
            result.successes += 1
        else:
            kind = _classify_error(err)
            if kind == "409":
                result.failures_409 += 1
                if len(result.errors) < 3:
                    result.errors.append(f"[409] {err}")
            elif kind == "400":
                result.failures_400 += 1
                if len(result.errors) < 5:
                    result.errors.append(f"[400] {err}")
            else:
                result.failures_other += 1
                if len(result.errors) < 5:
                    result.errors.append(f"[other] {err}")

    t0 = time.monotonic()
    await asyncio.gather(*[_run(i, sid) for i, sid in enumerate(data.students)])
    result.elapsed_s = time.monotonic() - t0
    result.print()

    if result.failures_400 > 0:
        print(f"  FAIL: {result.failures_400} validation errors (service bug)")
    elif result.failures_other > 0:
        print(f"  FAIL: {result.failures_other} unexpected errors")
    elif result.failures_409 > 0:
        print(f"  WARN: {result.failures_409} overflow — offerings under-capacity for {len(data.students)}")
    elif result.successes == len(data.students):
        print(f"  PASS: all {len(data.students)} confirmed")

    return result


async def phase3_pe_dist(session_factory: async_sessionmaker, data: CohortData) -> None:
    print("\n" + "=" * 60)
    print("PHASE 3 — PE/OE distribution check")
    print("=" * 60)
    pe = data.pe_bucket
    if not pe:
        print("  SKIP")
        return
    async with session_factory() as db:
        r = await db.execute(text("""
            SELECT co.id::text, co.booked_seats, co.max_seats, f.name
            FROM course_offerings co
            LEFT JOIN faculty f ON f.id = co.faculty_id
            WHERE co.bucket_id = :bid
            ORDER BY co.booked_seats DESC
        """), {"bid": pe.bucket_id})
        rows = r.all()
    total = sum(r[1] for r in rows)
    print(f"  {len(rows)} PE offerings, {total} total booked:")
    for row in rows:
        cap = row[2] if row[2] is not None else "uncapped"
        over = " ** OVER-CAP **" if row[2] and row[1] > row[2] else ""
        print(f"    {row[0][:8]}  [{str(row[3] or 'n/a'):22}] {row[1]:4}/{cap}{over}")
    cap_viol = [r for r in rows if r[2] is not None and r[1] > r[2]]
    if cap_viol:
        print(f"  FAIL: {len(cap_viol)} offering(s) over cap")
    else:
        spread = (max(r[1] for r in rows) - min(r[1] for r in rows)) if rows else 0
        print(f"  PASS: no cap violations, spread={spread}")


async def phase4_full_s7(session_factory: async_sessionmaker) -> TestResult:
    print("\n" + "=" * 60)
    print("PHASE 4 — Full S7 enrollment (200 students)")
    print("=" * 60)

    async with session_factory() as db:
        data = await load_cohort_data(db, AIML_S7_TARGET, AIML_DEPT, 7)

    pe_cap = sum(o.max_seats or 0 for o in data.pe_bucket.offerings) if data.pe_bucket else 9999
    expected_409 = max(0, len(data.students) - pe_cap)
    print(f"  S7: {len(data.students)} students | {len(data.core_buckets)} core | PE cap={pe_cap}")
    if expected_409 > 0:
        print(f"  Expected ~{expected_409} PE-overflow rejections (intentional cap)")

    result = TestResult(f"Phase 4 — S7 ({len(data.students)} students)")
    semaphore = asyncio.Semaphore(30)

    async def _run(idx: int, sid: str) -> None:
        picks = build_picks(idx, data)
        if picks is None:
            result.failures_other += 1
            result.errors.append(f"S7[{idx}]: no valid picks")
            return
        success, err = await confirm_for_student(session_factory, sid, picks, semaphore)
        if success:
            result.successes += 1
        else:
            kind = _classify_error(err)
            if kind == "409":
                result.failures_409 += 1
                if len(result.errors) < 3:
                    result.errors.append(f"[409] {err}")
            elif kind == "400":
                result.failures_400 += 1
                if len(result.errors) < 5:
                    result.errors.append(f"[400] {err}")
            else:
                result.failures_other += 1
                if len(result.errors) < 5:
                    result.errors.append(f"[other] {err}")

    t0 = time.monotonic()
    await asyncio.gather(*[_run(i, sid) for i, sid in enumerate(data.students)])
    result.elapsed_s = time.monotonic() - t0
    result.print()

    if result.failures_400 > 0:
        print(f"  FAIL: {result.failures_400} pick-validation errors")
    elif result.failures_other > 0:
        print(f"  FAIL: {result.failures_other} unexpected errors")
    elif result.failures_409 <= expected_409 + 5:
        print(f"  PASS: {result.successes} confirmed, {result.failures_409} PE-cap rejections (expected ~{expected_409})")
    else:
        print(f"  WARN: {result.failures_409} failures exceeds expected PE overflow of {expected_409}")

    return result


async def phase5_integrity(session_factory: async_sessionmaker) -> None:
    print("\n" + "=" * 60)
    print("PHASE 5 — Seat count integrity")
    print("=" * 60)
    async with session_factory() as db:
        r = await db.execute(text("""
            SELECT co.id::text, co.booked_seats, co.max_seats,
                   COUNT(sr.id) FILTER (WHERE sr.status = 'CONFIRMED') AS reg_count
            FROM course_offerings co
            LEFT JOIN student_registrations sr ON sr.offering_id = co.id
            JOIN target_requirements tr ON tr.bucket_id = co.bucket_id
            WHERE tr.target_id IN (:s5, :s7)
            GROUP BY co.id, co.booked_seats, co.max_seats
            HAVING co.booked_seats > 0 OR COUNT(sr.id) FILTER (WHERE sr.status='CONFIRMED') > 0
            ORDER BY co.booked_seats DESC
            LIMIT 40
        """), {"s5": AIML_S5_TARGET, "s7": AIML_S7_TARGET})
        rows = r.all()

    mismatch = cap_viol = 0
    for oid, booked, max_s, reg_count in rows:
        if booked != reg_count:
            print(f"  MISMATCH {oid[:8]}: booked_seats={booked} vs confirmed_registrations={reg_count}")
            mismatch += 1
        if max_s is not None and booked > max_s:
            print(f"  OVER-CAP  {oid[:8]}: booked={booked} > max={max_s}")
            cap_viol += 1

    if mismatch == 0 and cap_viol == 0:
        print(f"  PASS: {len(rows)} offerings checked — no integrity violations")
    else:
        print(f"  FAIL: {mismatch} mismatches, {cap_viol} cap violations")

    try:
        import redis as redis_lib
        rc = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
        checked = mismatches = 0
        for oid, booked, max_s, _ in rows[:15]:
            if max_s is None:
                continue
            val = rc.get(f"offering:seats:{oid}")
            if val is not None:
                expected = max_s - booked
                if int(val) != expected:
                    print(f"  Redis {oid[:8]}: expected remaining={expected} got={val}")
                    mismatches += 1
                checked += 1
        if mismatches == 0:
            print(f"  Redis: {checked} counters match DB")
    except Exception as exc:
        print(f"  Redis check skipped: {exc}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _reset_students(session_factory: async_sessionmaker, student_ids: list[str]) -> None:
    """Delete selections for specific students. Uses IN with individual params (asyncpg-safe)."""
    if not student_ids:
        return
    # asyncpg text() doesn't support list params; use individual named placeholders
    params = {f"id{i}": sid for i, sid in enumerate(student_ids)}
    in_clause = ", ".join(f":id{i}" for i in range(len(student_ids)))
    async with session_factory() as db:
        await db.execute(
            text(f"DELETE FROM student_registrations WHERE student_id::text IN ({in_clause})"),
            params,
        )
        await db.execute(
            text(f"DELETE FROM student_group_selections WHERE student_id::text IN ({in_clause})"),
            params,
        )
        await db.execute(text("""
            UPDATE course_offerings SET booked_seats = (
                SELECT COUNT(*) FROM student_registrations sr
                WHERE sr.offering_id = course_offerings.id AND sr.status = 'CONFIRMED'
            )
        """))
        await db.commit()


async def cleanup(session_factory: async_sessionmaker) -> None:
    print("\n" + "=" * 60)
    print("CLEANUP")
    print("=" * 60)
    async with session_factory() as db:
        r1 = await db.execute(text("DELETE FROM student_registrations"))
        r2 = await db.execute(text("DELETE FROM student_group_selections"))
        await db.execute(text("UPDATE course_offerings SET booked_seats = 0 WHERE booked_seats > 0"))
        await db.commit()
        print(f"  Cleared {r1.rowcount} registrations, {r2.rowcount} group selections")
    try:
        import redis as redis_lib
        rc = redis_lib.Redis.from_url(REDIS_URL)
        keys = (rc.keys("offering:seats:*")
                + rc.keys("selection:menu:*")
                + rc.keys("selection:idempotency:*"))
        if keys:
            rc.delete(*keys)
        print(f"  Redis: flushed {len(keys)} keys")
    except Exception as exc:
        print(f"  Redis flush: {exc}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    engine = create_async_engine(
        DATABASE_URL, pool_size=20, max_overflow=30, pool_timeout=30, echo=False
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)

    if not await phase0_check(factory):
        await engine.dispose()
        return

    async with factory() as db:
        s5 = await load_cohort_data(db, AIML_S5_TARGET, AIML_DEPT, 5)

    print(f"\nAIML S5: {len(s5.students)} students | "
          f"{len(s5.core_buckets)} core buckets | "
          f"PE={'yes' if s5.pe_bucket else 'no'}")

    # Quick sanity check
    for i in range(3):
        p = build_picks(i, s5)
        status = f"{len(p)} buckets" if p else "NONE (bug!)"
        print(f"  Picks check [{i}]: {status}")

    r1 = await phase1_seat_limit(factory, s5)
    r2 = await phase2_full_s5(factory, s5)

    if r2.failures_400 == 0:
        await phase3_pe_dist(factory, s5)
    else:
        print("\nSkipping PE check — Phase 2 had validation errors")

    r4 = await phase4_full_s7(factory)
    await phase5_integrity(factory)

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for result in (r1, r2, r4):
        bad = result.failures_400 + result.failures_other
        flag = "PASS" if bad == 0 else "FAIL"
        print(f"  [{flag}] {result.phase}")
        print(f"         ok={result.successes} | full={result.failures_409} | bad={result.failures_400} | err={result.failures_other} | {result.elapsed_s:.1f}s")

    await cleanup(factory)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
