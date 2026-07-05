"""
scripts/seed_dev.py
====================
Development seed — populates one institution with a user for every role,
linked Faculty rows, departments, an academic term, and student profiles.

Run from the backend root (with the virtualenv active):

    cd backend
    python -m scripts.seed_dev

Or with explicit module path:

    python scripts/seed_dev.py

Idempotent: running twice will print "already exists" for every entity
and make no changes (checks by email / unique fields before inserting).

Credentials created
-------------------
  Role         Email                           Password
  ──────────── ─────────────────────────────── ─────────────
  super_admin  superadmin@exovance.io          Admin@1234
  admin        admin@campus.edu                Admin@1234
  hod          hod.cse@campus.edu              Admin@1234
  teacher      teacher1.cse@campus.edu         Admin@1234
  teacher      teacher2.ece@campus.edu         Admin@1234
  student      student1.cse@campus.edu         Admin@1234
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import os
import sys
import uuid

# ── Make sure src/ is on the path when run as a script ────────────────────
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import bcrypt
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.user import User, UserRole
from app.models.faculty import Faculty, EmploymentType
from app.models.institution import AcademicTerm, SchedulingMode, AcademicTermStatus
from app.models.student import StudentProfile

# Load .env so DATABASE_URL is available
from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, ".env"))

DATABASE_URL = os.environ["DATABASE_URL"]

# ── Engine (sync-compatible asyncpg URL) ─────────────────────────────────
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

# ── Password helper ───────────────────────────────────────────────────────
DEFAULT_PASSWORD = "Admin@1234"


@dataclass(slots=True)
class SeedInstitution:
    id: uuid.UUID
    name: str


@dataclass(slots=True)
class SeedDepartment:
    id: uuid.UUID
    code: str
    name: str

def _hash(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


# ── Helpers ───────────────────────────────────────────────────────────────

async def _get_table_columns(db: AsyncSession, table_name: str) -> set[str]:
    result = await db.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = :table_name
            """
        ),
        {"table_name": table_name},
    )
    return set(result.scalars().all())


async def _get_or_create_institution(db: AsyncSession) -> SeedInstitution:
    result = await db.execute(
        text(
            """
            SELECT id, name
            FROM institutions
            WHERE name = :name
            LIMIT 1
            """
        ),
        {"name": "Exovance Demo University"},
    )
    row = result.mappings().first()
    if row:
        inst = SeedInstitution(id=row["id"], name=row["name"])
        print(f"  [skip] Institution already exists: {inst.name} (id={inst.id})")
        return inst

    institution_id = uuid.uuid4()
    columns = await _get_table_columns(db, "institutions")
    values: dict[str, object] = {
        "id": institution_id,
        "name": "Exovance Demo University",
        "domain": "demo.exovance.io",
        "scheduling_mode": SchedulingMode.TRADITIONAL.value,
        "timezone": "Asia/Kolkata",
        "is_active": True,
    }
    if "regulatory_body" in columns:
        values["regulatory_body"] = "UGC"
    if "default_class_size" in columns:
        values["default_class_size"] = 60

    column_sql = ", ".join(values.keys())
    bind_sql = ", ".join(f":{column_name}" for column_name in values)
    await db.execute(
        text(f"INSERT INTO institutions ({column_sql}) VALUES ({bind_sql})"),
        values,
    )

    inst = SeedInstitution(id=institution_id, name="Exovance Demo University")
    print(f"  [+] Institution: {inst.name} (id={inst.id})")
    return inst


async def _get_or_create_department(
    db: AsyncSession,
    institution_id: uuid.UUID,
    name: str,
    code: str,
    description: str,
) -> SeedDepartment:
    result = await db.execute(
        text(
            """
            SELECT id, code, name
            FROM departments
            WHERE institution_id = :institution_id AND code = :code
            LIMIT 1
            """
        ),
        {"institution_id": institution_id, "code": code},
    )
    row = result.mappings().first()
    if row:
        dept = SeedDepartment(id=row["id"], code=row["code"], name=row["name"])
        print(f"  [skip] Department already exists: {code}")
        return dept

    department_id = uuid.uuid4()
    await db.execute(
        text(
            """
            INSERT INTO departments (id, institution_id, name, code, description)
            VALUES (:id, :institution_id, :name, :code, :description)
            """
        ),
        {
            "id": department_id,
            "institution_id": institution_id,
            "name": name,
            "code": code,
            "description": description,
        },
    )

    dept = SeedDepartment(id=department_id, code=code, name=name)
    print(f"  [+] Department: {code} — {name}")
    return dept


async def _get_or_create_term(
    db: AsyncSession,
    institution_id: uuid.UUID,
) -> AcademicTerm:
    from datetime import date
    result = await db.execute(
        select(AcademicTerm).where(
            AcademicTerm.institution_id == institution_id,
            AcademicTerm.name == "Fall 2026",
        )
    )
    term = result.scalars().first()
    if term:
        print(f"  [skip] Academic term already exists: Fall 2026")
        return term

    term = AcademicTerm(
        id=uuid.uuid4(),
        institution_id=institution_id,
        name="Fall 2026",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 11, 30),
        status=AcademicTermStatus.PLANNING,
    )
    db.add(term)
    await db.flush()
    print(f"  [+] Academic term: Fall 2026")
    return term


async def _get_or_create_faculty(
    db: AsyncSession,
    institution_id: uuid.UUID,
    department_id: uuid.UUID,  # kept for call-site compat; department lives on User
    name: str,
    email: str,
    employment_type: EmploymentType,
    max_weekly_hours: int,
) -> Faculty:
    result = await db.execute(
        select(Faculty).where(Faculty.name == name)
    )
    fac = result.scalars().first()
    if fac:
        print(f"  [skip] Faculty already exists: {name}")
        return fac

    fac = Faculty(
        id=uuid.uuid4(),
        institution_id=institution_id,
        name=name,
        employment_type=employment_type,
        max_weekly_hours=max_weekly_hours,
        availability_blacklist=[],
        preferences={},
        is_active=True,
    )
    db.add(fac)
    await db.flush()
    print(f"  [+] Faculty: {name} <{email}>")
    return fac


async def _get_or_create_user(
    db: AsyncSession,
    institution_id: uuid.UUID | None,
    email: str,
    full_name: str,
    role: UserRole,
    department: str | None = None,  # kept for call-site compat, not passed to model
    department_id: uuid.UUID | None = None,
) -> User:
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalars().first()
    if user:
        print(f"  [skip] User already exists: {email} [{role.value}]")
        return user

    user = User(
        id=uuid.uuid4(),
        email=email,
        hashed_password=_hash(DEFAULT_PASSWORD),
        full_name=full_name,
        role=role,
        institution_id=institution_id,
        department_id=department_id,
        is_active=True,
        is_verified=True,
    )
    db.add(user)
    await db.flush()
    print(f"  [+] User: {full_name} <{email}> [{role.value}]")
    return user


async def _get_or_create_student_profile(
    db: AsyncSession,
    user_id: uuid.UUID,
    enrollment_number: str,
    program: str,
    semester: int,
    year_of_study: int,
) -> StudentProfile:
    result = await db.execute(select(StudentProfile).where(StudentProfile.user_id == user_id))
    profile = result.scalars().first()
    if profile:
        print(f"  [skip] StudentProfile already exists for user {user_id}")
        return profile

    profile = StudentProfile(
        id=uuid.uuid4(),
        user_id=user_id,
        enrollment_number=enrollment_number,
        program=program,
        semester=semester,
        year_of_study=year_of_study,
    )
    db.add(profile)
    await db.flush()
    print(f"  [+] StudentProfile: {enrollment_number} — {program}, Sem {semester}")
    return profile


# ── Main seed ─────────────────────────────────────────────────────────────

async def seed() -> None:
    async with AsyncSessionLocal() as db:
        print("\n── Institution ─────────────────────────────────────────────")
        inst = await _get_or_create_institution(db)

        print("\n── Departments ─────────────────────────────────────────────")
        dept_cse = await _get_or_create_department(db, inst.id, "Computer Science & Engineering", "CSE", "B.Tech CSE")
        dept_ece = await _get_or_create_department(db, inst.id, "Electronics & Communication", "ECE", "B.Tech ECE")
        dept_mech = await _get_or_create_department(db, inst.id, "Mechanical Engineering", "MECH", "B.Tech MECH")

        print("\n── Academic Term ────────────────────────────────────────────")
        await _get_or_create_term(db, inst.id)

        print("\n── Faculty rows (solver resources) ─────────────────────────")
        fac1 = await _get_or_create_faculty(
            db, inst.id, dept_cse.id,
            name="Dr. Priya Krishnamurthy",
            email="teacher1.cse@campus.edu",
            employment_type=EmploymentType.FULL_TIME,
            max_weekly_hours=18,
        )
        fac2 = await _get_or_create_faculty(
            db, inst.id, dept_ece.id,
            name="Prof. Rajan Pillai",
            email="teacher2.ece@campus.edu",
            employment_type=EmploymentType.FULL_TIME,
            max_weekly_hours=20,
        )
        # HOD also gets a Faculty row so constraints can reference them
        fac_hod = await _get_or_create_faculty(
            db, inst.id, dept_cse.id,
            name="Prof. Ramesh Iyer",
            email="hod.cse.faculty@campus.edu",
            employment_type=EmploymentType.FULL_TIME,
            max_weekly_hours=10,
        )

        print("\n── Users ────────────────────────────────────────────────────")

        # SUPER_ADMIN — no institution, no department
        await _get_or_create_user(
            db,
            institution_id=None,
            email="superadmin@exovance.io",
            full_name="Super Admin",
            role=UserRole.SUPER_ADMIN,
        )

        # ADMIN — institution-wide, no department restriction
        await _get_or_create_user(
            db,
            institution_id=inst.id,
            email="admin@campus.edu",
            full_name="Campus Admin",
            role=UserRole.ADMIN,
        )

        # HOD — scoped to CSE; linked to their Faculty row
        hod_user = await _get_or_create_user(
            db,
            institution_id=inst.id,
            email="hod.cse@campus.edu",
            full_name="Prof. Ramesh Iyer",
            role=UserRole.HOD,
            department="CSE",
            department_id=dept_cse.id,
        )
        fac_hod.user_id = hod_user.id
        # SeedDepartment is a plain dataclass — update the DB row directly
        await db.execute(
            text("UPDATE departments SET hod_faculty_id = :hod_id WHERE id = :dept_id"),
            {"hod_id": fac_hod.id, "dept_id": dept_cse.id},
        )

        # TEACHER 1 — CSE; linked to Faculty row
        teacher1_user = await _get_or_create_user(
            db,
            institution_id=inst.id,
            email="teacher1.cse@campus.edu",
            full_name="Dr. Priya Krishnamurthy",
            role=UserRole.TEACHER,
            department="CSE",
            department_id=dept_cse.id,
        )
        fac1.user_id = teacher1_user.id

        # TEACHER 2 — ECE; linked to Faculty row
        teacher2_user = await _get_or_create_user(
            db,
            institution_id=inst.id,
            email="teacher2.ece@campus.edu",
            full_name="Prof. Rajan Pillai",
            role=UserRole.TEACHER,
            department="ECE",
            department_id=dept_ece.id,
        )
        fac2.user_id = teacher2_user.id

        # STUDENT — CSE, Semester 5 (3rd year)
        student_user = await _get_or_create_user(
            db,
            institution_id=inst.id,
            email="student1.cse@campus.edu",
            full_name="Arjun Sharma",
            role=UserRole.STUDENT,
            department="CSE",
            department_id=dept_cse.id,
        )

        print("\n── Student Profile ──────────────────────────────────────────")
        await _get_or_create_student_profile(
            db,
            user_id=student_user.id,
            enrollment_number="21CSE001",
            program="B.Tech Computer Science Engineering",
            semester=5,
            year_of_study=3,
        )

        await db.commit()

        print("\n" + "═" * 60)
        print("  Seed complete. Login credentials:")
        print("═" * 60)
        rows = [
            ("super_admin", "superadmin@exovance.io",     DEFAULT_PASSWORD, "No institution (platform-wide)"),
            ("admin",       "admin@campus.edu",            DEFAULT_PASSWORD, "Exovance Demo University"),
            ("hod",         "hod.cse@campus.edu",          DEFAULT_PASSWORD, "CSE dept — linked to Faculty row"),
            ("teacher",     "teacher1.cse@campus.edu",     DEFAULT_PASSWORD, "CSE — Faculty: Dr. Priya Krishnamurthy"),
            ("teacher",     "teacher2.ece@campus.edu",     DEFAULT_PASSWORD, "ECE — Faculty: Prof. Rajan Pillai"),
            ("student",     "student1.cse@campus.edu",     DEFAULT_PASSWORD, "CSE Sem 5 — Enrollment: 21CSE001"),
        ]
        print(f"  {'Role':<14} {'Email':<34} {'Password':<14} Notes")
        print(f"  {'─'*14} {'─'*34} {'─'*14} {'─'*30}")
        for role, email, pw, notes in rows:
            print(f"  {role:<14} {email:<34} {pw:<14} {notes}")
        print("═" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(seed())
