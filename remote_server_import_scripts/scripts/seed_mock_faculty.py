"""
scripts/seed_mock_faculty.py
============================
Add extra mock faculty rows and linked teacher users to a target institution.

Run from the backend root:

    python -m scripts.seed_mock_faculty --institution-id <uuid> --count-per-department 25

The script is safe to re-run. It ensures each active department in the
institution has at least N mock teachers with deterministic emails.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
import os
import sys
import uuid

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import bcrypt
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

load_dotenv(os.path.join(_ROOT, ".env"))

DATABASE_URL = os.environ["DATABASE_URL"]
DEFAULT_PASSWORD = "Admin@1234"

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@dataclass(slots=True)
class DepartmentSeedTarget:
    id: uuid.UUID
    code: str
    name: str


def _hash(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def _slugify_dept_code(code: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "." for ch in code).strip(".") or "dept"


def _build_mock_name(dept_code: str, index: int) -> str:
    return f"Dr. {dept_code} Mock Faculty {index:02d}"


def _employment_for_index(index: int) -> tuple[str, int]:
    mod = index % 6
    if mod in (1, 2, 3, 4):
        return ("FULL_TIME", 20)
    if mod == 5:
        return ("PART_TIME", 12)
    return ("ADJUNCT", 8)


async def _load_departments(
    db: AsyncSession,
    institution_id: uuid.UUID,
) -> list[DepartmentSeedTarget]:
    rows = (
        await db.execute(
            text(
                """
                SELECT id, code, name
                FROM departments
                WHERE institution_id = :institution_id AND is_active = true
                ORDER BY code
                """
            ),
            {"institution_id": institution_id},
        )
    ).mappings().all()
    return [
        DepartmentSeedTarget(id=row["id"], code=row["code"], name=row["name"])
        for row in rows
    ]


async def _ensure_institution_exists(db: AsyncSession, institution_id: uuid.UUID) -> str:
    row = (
        await db.execute(
            text("SELECT name FROM institutions WHERE id = :institution_id LIMIT 1"),
            {"institution_id": institution_id},
        )
    ).scalar_one_or_none()
    if row is None:
        raise SystemExit(f"Institution {institution_id} not found.")
    return str(row)


async def _count_existing_mock_faculty(
    db: AsyncSession,
    institution_id: uuid.UUID,
    department_id: uuid.UUID,
    dept_slug: str,
) -> int:
    result = await db.execute(
        text(
            """
            SELECT COUNT(*)
            FROM faculty
            WHERE institution_id = :institution_id
              AND department_id = :department_id
              AND email LIKE :pattern
            """
        ),
        {
            "institution_id": institution_id,
            "department_id": department_id,
            "pattern": f"mockteacher%.{dept_slug}@campus.edu",
        },
    )
    return int(result.scalar_one())


async def _create_mock_faculty(
    db: AsyncSession,
    institution_id: uuid.UUID,
    department: DepartmentSeedTarget,
    dept_slug: str,
    index: int,
) -> None:
    email = f"mockteacher{index:02d}.{dept_slug}@campus.edu"
    existing = await db.execute(
        text("SELECT id FROM users WHERE email = :email LIMIT 1"),
        {"email": email},
    )
    if existing.scalar_one_or_none() is not None:
        return

    faculty_id = uuid.uuid4()
    user_id = uuid.uuid4()
    employment_type, max_hours = _employment_for_index(index)
    name = _build_mock_name(department.code, index)

    await db.execute(
        text(
            """
            INSERT INTO faculty (
                id, institution_id, department_id, name,
                employment_type, max_weekly_hours,
                availability_blacklist, preferences, is_active
            ) VALUES (
                :id, :institution_id, :department_id, :name,
                :employment_type, :max_weekly_hours,
                CAST('[]' AS jsonb), CAST('{}' AS jsonb), true
            )
            """
        ),
        {
            "id": faculty_id,
            "institution_id": institution_id,
            "department_id": department.id,
            "name": name,
            "employment_type": employment_type,
            "max_weekly_hours": max_hours,
        },
    )

    await db.execute(
        text(
            """
            INSERT INTO users (
                id, institution_id, department_id, department,
                email, hashed_password, full_name, role,
                is_active, is_verified
            ) VALUES (
                :id, :institution_id, :department_id, :department_code,
                :email, :hashed_password, :full_name, :role,
                true, true
            )
            """
        ),
        {
            "id": user_id,
            "institution_id": institution_id,
            "department_id": department.id,
            "department_code": department.code,
            "email": email,
            "hashed_password": _hash(DEFAULT_PASSWORD),
            "full_name": name,
            "role": "teacher",
        },
    )

    # Link Faculty → User
    await db.execute(
        text("UPDATE faculty SET user_id = :user_id WHERE id = :faculty_id"),
        {"user_id": user_id, "faculty_id": faculty_id},
    )


async def seed_mock_faculty(institution_id: uuid.UUID, count_per_department: int) -> None:
    async with AsyncSessionLocal() as db:
        institution_name = await _ensure_institution_exists(db, institution_id)
        departments = await _load_departments(db, institution_id)
        if not departments:
            raise SystemExit(f"Institution {institution_id} has no active departments.")

        print(f"Seeding mock faculty for {institution_name} ({institution_id})")
        for department in departments:
            dept_slug = _slugify_dept_code(department.code)
            existing = await _count_existing_mock_faculty(
                db,
                institution_id,
                department.id,
                dept_slug,
            )
            if existing >= count_per_department:
                print(
                    f"  [skip] {department.code}: already has {existing} mock teachers"
                )
                continue

            for index in range(existing + 1, count_per_department + 1):
                await _create_mock_faculty(
                    db,
                    institution_id,
                    department,
                    dept_slug,
                    index,
                )

            print(
                f"  [+] {department.code}: added {count_per_department - existing} mock teachers"
            )

        await db.commit()
        print(f"Done. Default password for mock teachers: {DEFAULT_PASSWORD}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--institution-id", required=True, type=uuid.UUID)
    parser.add_argument("--count-per-department", type=int, default=25)
    args = parser.parse_args()
    asyncio.run(seed_mock_faculty(args.institution_id, args.count_per_department))


if __name__ == "__main__":
    main()