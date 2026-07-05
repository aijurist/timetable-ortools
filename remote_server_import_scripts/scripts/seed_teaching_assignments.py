"""
scripts/seed_teaching_assignments.py
======================================
NON-DESTRUCTIVE seed — adds TeachingAssignments for CSE + IT and creates
a ready-to-use DRAFT Scenario so you can test the COHORT panel immediately.

Requires that seed_full.py has already been run (institution, departments,
academic term, faculty, and courses must exist).

Run from the backend root:

    cd backend
    python -m scripts.seed_teaching_assignments

Idempotent:
  - Teaching assignments are inserted with ON CONFLICT DO NOTHING.
  - A scenario is only created if none exist for the term; otherwise the
    first existing scenario is printed so you know which one to use.

Teaching plan layout (mirrors seed_full.py ASSIGNMENT_LAYOUT):
  Each dept has 5 courses × 5 sections = 25 total offerings per dept.

  Course 0 (theory, 4h): faculty[0]×2  faculty[1]×2  faculty[2]×1
  Course 1 (theory, 4h): faculty[3]×2  faculty[4]×2  faculty[5]×1
  Course 2 (theory, 3h): faculty[6]×2  faculty[7]×2  faculty[8]×1
  Course 3 (theory, 3h): faculty[9]×2  faculty[10]×2 faculty[11]×1
  Course 4 (lab,   2h): faculty[12]×3 faculty[13]×2

Credentials (same as seed_full.py — Admin@1234)
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC  = os.path.join(_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, ".env"))

DATABASE_URL = os.environ["DATABASE_URL"]
engine       = create_async_engine(DATABASE_URL, echo=False)
Session      = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

# Teaching plan layout shared by both depts:
# (faculty_list_index, course_list_index, section_count)
ASSIGNMENT_LAYOUT = [
    (0,  0, 2), (1,  0, 2), (2,  0, 1),   # course 0 → 5 sections
    (3,  1, 2), (4,  1, 2), (5,  1, 1),   # course 1 → 5 sections
    (6,  2, 2), (7,  2, 2), (8,  2, 1),   # course 2 → 5 sections
    (9,  3, 2), (10, 3, 2), (11, 3, 1),   # course 3 → 5 sections
    (12, 4, 3), (13, 4, 2),               # course 4 → 5 sections (lab)
]


# ─── Lookup helpers ───────────────────────────────────────────────────────────

async def _fetch_one(db: AsyncSession, sql: str, params: dict):
    result = await db.execute(text(sql), params)
    row = result.fetchone()
    return row


async def _fetch_all(db: AsyncSession, sql: str, params: dict = {}):
    result = await db.execute(text(sql), params)
    return result.fetchall()


async def resolve_institution(db: AsyncSession) -> tuple[uuid.UUID, str]:
    row = await _fetch_one(db,
        "SELECT id, name FROM institutions WHERE is_active = true ORDER BY created_at LIMIT 1",
        {},
    )
    if row is None:
        raise RuntimeError(
            "No institution found. Run `python -m scripts.seed_full` first."
        )
    return row.id, row.name


async def resolve_active_term(db: AsyncSession, inst_id: uuid.UUID) -> tuple[uuid.UUID, str]:
    row = await _fetch_one(db,
        "SELECT id, name FROM academic_terms WHERE institution_id = :inst AND status = 'ACTIVE' LIMIT 1",
        {"inst": inst_id},
    )
    if row is None:
        raise RuntimeError(
            "No ACTIVE academic term found. Run `python -m scripts.seed_full` first."
        )
    return row.id, row.name


async def resolve_department(db: AsyncSession, inst_id: uuid.UUID, code: str) -> tuple[uuid.UUID, str]:
    row = await _fetch_one(db,
        "SELECT id, name FROM departments WHERE institution_id = :inst AND code = :code LIMIT 1",
        {"inst": inst_id, "code": code},
    )
    if row is None:
        raise RuntimeError(
            f"Department '{code}' not found for institution {inst_id}. "
            "Run `python -m scripts.seed_full` first."
        )
    return row.id, row.name


async def resolve_faculty_ids(
    db: AsyncSession, inst_id: uuid.UUID, dept_id: uuid.UUID
) -> list[uuid.UUID]:
    rows = await _fetch_all(db,
        """
        SELECT id FROM faculty
        WHERE institution_id = :inst AND department_id = :dept AND is_active = true
        ORDER BY name
        """,
        {"inst": inst_id, "dept": dept_id},
    )
    return [r.id for r in rows]


async def resolve_course_ids(
    db: AsyncSession, inst_id: uuid.UUID, dept_id: uuid.UUID
) -> list[uuid.UUID]:
    rows = await _fetch_all(db,
        """
        SELECT id FROM courses
        WHERE institution_id = :inst AND department_id = :dept AND is_active = true
        ORDER BY code
        """,
        {"inst": inst_id, "dept": dept_id},
    )
    return [r.id for r in rows]


async def resolve_time_grid(
    db: AsyncSession, term_id: uuid.UUID
) -> uuid.UUID | None:
    row = await _fetch_one(db,
        "SELECT id FROM time_grids WHERE academic_term_id = :term AND is_active = true LIMIT 1",
        {"term": term_id},
    )
    return row.id if row else None


# ─── Teaching Assignment seeding ─────────────────────────────────────────────

async def seed_teaching_assignments(
    db: AsyncSession,
    inst_id: uuid.UUID,
    term_id: uuid.UUID,
    dept_id: uuid.UUID,
    dept_code: str,
    faculty_ids: list[uuid.UUID],
    course_ids: list[uuid.UUID],
) -> int:
    inserted = 0
    skipped  = 0

    for fac_idx, course_idx, section_count in ASSIGNMENT_LAYOUT:
        if fac_idx >= len(faculty_ids):
            print(f"  [!] {dept_code}: not enough faculty (need index {fac_idx}, have {len(faculty_ids)}), skipping")
            continue
        if course_idx >= len(course_ids):
            print(f"  [!] {dept_code}: not enough courses (need index {course_idx}, have {len(course_ids)}), skipping")
            continue

        fac_id    = faculty_ids[fac_idx]
        course_id = course_ids[course_idx]
        aid       = uuid.uuid4()

        result = await db.execute(
            text("""
                INSERT INTO teaching_assignments
                    (id, institution_id, academic_term_id, department_id,
                     faculty_id, course_id, section_count, is_active)
                VALUES
                    (:id, :inst, :term, :dept, :fac, :course, :sec, true)
                ON CONFLICT (academic_term_id, department_id, faculty_id, course_id)
                DO NOTHING
            """),
            {
                "id":     aid,
                "inst":   inst_id,
                "term":   term_id,
                "dept":   dept_id,
                "fac":    fac_id,
                "course": course_id,
                "sec":    section_count,
            },
        )
        if result.rowcount > 0:
            inserted += 1
        else:
            skipped += 1

    return inserted, skipped


# ─── Scenario creation ────────────────────────────────────────────────────────

async def ensure_scenario(
    db: AsyncSession,
    inst_id: uuid.UUID,
    term_id: uuid.UUID,
    grid_id: uuid.UUID | None,
) -> tuple[uuid.UUID, bool]:
    """
    Return (scenario_id, created).
    If a scenario already exists for this institution+term, return the first one.
    Otherwise create a new DRAFT scenario.
    """
    existing = await _fetch_one(db,
        """
        SELECT id, name FROM scenarios
        WHERE institution_id = :inst AND academic_term_id = :term
        ORDER BY created_at
        LIMIT 1
        """,
        {"inst": inst_id, "term": term_id},
    )
    if existing:
        return existing.id, False

    sid = uuid.uuid4()
    await db.execute(
        text("""
            INSERT INTO scenarios
                (id, institution_id, academic_term_id, selected_time_grid_id,
                 name, status, is_dirty)
            VALUES
                (:id, :inst, :term, :grid,
                 :name, 'DRAFT', true)
        """),
        {
            "id":   sid,
            "inst": inst_id,
            "term": term_id,
            "grid": grid_id,
            "name": "Even Sem 2026 — Teaching Plan Test",
        },
    )
    return sid, True


# ─── Main ─────────────────────────────────────────────────────────────────────

async def seed() -> None:
    async with Session() as db:

        # ── Resolve existing data ─────────────────────────────────────────────
        print("\n-- Resolving existing data ----------------------------------")
        inst_id, inst_name = await resolve_institution(db)
        print(f"  [✓] Institution : {inst_name}  ({inst_id})")

        term_id, term_name = await resolve_active_term(db, inst_id)
        print(f"  [✓] Term        : {term_name}  ({term_id})")

        grid_id = await resolve_time_grid(db, term_id)
        if grid_id:
            print(f"  [✓] Time grid   : {grid_id}")
        else:
            print(f"  [!] No active time grid found — scenario will have NULL grid")

        cse_dept_id, _ = await resolve_department(db, inst_id, "CSE")
        it_dept_id,  _ = await resolve_department(db, inst_id, "IT")
        print(f"  [✓] Dept CSE    : {cse_dept_id}")
        print(f"  [✓] Dept IT     : {it_dept_id}")

        cse_faculty = await resolve_faculty_ids(db, inst_id, cse_dept_id)
        it_faculty  = await resolve_faculty_ids(db, inst_id, it_dept_id)
        print(f"  [✓] CSE faculty : {len(cse_faculty)} members")
        print(f"  [✓] IT  faculty : {len(it_faculty)} members")

        cse_courses = await resolve_course_ids(db, inst_id, cse_dept_id)
        it_courses  = await resolve_course_ids(db, inst_id, it_dept_id)
        print(f"  [✓] CSE courses : {len(cse_courses)}")
        print(f"  [✓] IT  courses : {len(it_courses)}")

        if len(cse_faculty) < 14 or len(it_faculty) < 14:
            print("\n  [!] WARNING: fewer than 14 faculty found in a department.")
            print("      Run `python -m scripts.seed_full` first for a complete dataset.")

        # ── Teaching Assignments ──────────────────────────────────────────────
        print("\n-- Teaching Assignments (CSE) --------------------------------")
        cse_ins, cse_skip = await seed_teaching_assignments(
            db, inst_id, term_id, cse_dept_id, "CSE", cse_faculty, cse_courses,
        )
        print(f"  inserted={cse_ins}  skipped(already exist)={cse_skip}")

        print("\n-- Teaching Assignments (IT) ---------------------------------")
        it_ins, it_skip = await seed_teaching_assignments(
            db, inst_id, term_id, it_dept_id, "IT", it_faculty, it_courses,
        )
        print(f"  inserted={it_ins}  skipped(already exist)={it_skip}")

        # ── Scenario ─────────────────────────────────────────────────────────
        print("\n-- Scenario -------------------------------------------------")
        scenario_id, created = await ensure_scenario(db, inst_id, term_id, grid_id)
        if created:
            print(f"  [+] Created DRAFT scenario: {scenario_id}")
            print(f"      Name: 'Even Sem 2026 — Teaching Plan Test'")
        else:
            print(f"  [~] Using existing scenario: {scenario_id}")

        await db.commit()

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  Teaching Assignment seed complete.")
    print("=" * 60)
    total_ins = cse_ins + it_ins
    total_skip = cse_skip + it_skip
    print(f"\n  CSE assignments : {cse_ins} inserted, {cse_skip} already existed")
    print(f"  IT  assignments : {it_ins} inserted, {it_skip} already existed")
    print(f"  Total           : {total_ins} new rows  ({total_skip} skipped)")
    print(f"\n  Scenario ID  : {scenario_id}  ({'NEW' if created else 'EXISTING'})")
    print(f"\n  Next steps:")
    print(f"    1. Open the Timetable module → select the scenario above")
    print(f"    2. Go to the Teaching Plan tab — you should see both depts' assignments")
    print(f"    3. Use the COHORT setup panel to create CSE and IT cohorts")
    print(f"       (the panel reads TeachingAssignments to auto-generate buckets)")
    print(f"    4. Trigger POST /scenarios/{scenario_id}/solve to run the scheduler")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(seed())
