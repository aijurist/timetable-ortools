"""
app/services/user_service.py
============================
User identity & password management.

Responsibilities
----------------
* CRUD operations on the ``users`` table.
* Password hashing / verification (bcrypt via passlib).
* Does NOT issue JWTs — that is auth_service's job.
"""
from __future__ import annotations

import uuid
from typing import Optional

import bcrypt as _bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.logger import logger
from app.models.user import User, UserRole
from app.schemas.user import UserCreate, UserUpdate


# ---------------------------------------------------------------------------
# Password helpers (direct bcrypt — avoids passlib 1.7.4 / bcrypt 4+ incompatibility)
# ---------------------------------------------------------------------------


def hash_password(plain: str) -> str:
    """Return a bcrypt hash of *plain*."""
    return _bcrypt.hashpw(plain.encode("utf-8"), _bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if *plain* matches *hashed*."""
    return _bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


async def get_by_email(db: AsyncSession, email: str) -> Optional[User]:
    """Return the User with *email*, or None if not found."""
    result = await db.execute(
        select(User).where(User.email == email).options(selectinload(User.department_rel))
    )
    return result.scalars().first()


async def get_by_id(db: AsyncSession, user_id: uuid.UUID) -> Optional[User]:
    """Return the User with *user_id*, or None if not found."""
    result = await db.execute(
        select(User).where(User.id == user_id).options(selectinload(User.department_rel))
    )
    return result.scalars().first()


async def get_or_404(db: AsyncSession, user_id: uuid.UUID) -> User:
    """Return the User or raise ``NotFoundError``."""
    user = await get_by_id(db, user_id)
    if user is None:
        raise NotFoundError(f"User {user_id} not found")
    return user


async def _assert_department_institution(
    db: AsyncSession, department_id: uuid.UUID, institution_id: uuid.UUID
) -> None:
    from app.models.institution import Department  # noqa: PLC0415
    result = await db.execute(select(Department).where(Department.id == department_id))
    dept = result.scalars().first()
    if dept is None:
        raise NotFoundError(f"Department {department_id} not found")
    if dept.institution_id != institution_id:
        raise ValidationError("department_id does not belong to this institution")


async def list_by_institution(
    db: AsyncSession,
    institution_id: uuid.UUID,
    *,
    roles: list[UserRole] | None = None,
    department_id: uuid.UUID | None = None,
    skip: int = 0,
    limit: int = 50,
) -> list[User]:
    """Return users for *institution_id*, optionally filtered by *roles* and *department_id*."""
    q = select(User).where(User.institution_id == institution_id)
    if roles:
        q = q.where(User.role.in_(roles))
    if department_id is not None:
        q = q.where(User.department_id == department_id)
    q = q.offset(skip).limit(limit).order_by(User.created_at.desc())
    result = await db.execute(q)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


async def create(db: AsyncSession, payload: UserCreate) -> User:
    """
    Create a new User.

    Raises ``ConflictError`` if the e-mail is already registered.
    """
    existing = await get_by_email(db, payload.email)
    if existing is not None:
        raise ConflictError(f"Email '{payload.email}' is already registered")

    if payload.department_id is not None and payload.institution_id is not None:
        await _assert_department_institution(db, payload.department_id, payload.institution_id)

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        role=payload.role,
        institution_id=payload.institution_id,
        department_id=payload.department_id,
        academic_title=payload.academic_title,
        phone=payload.phone,
        gender=payload.gender,
    )
    db.add(user)
    await db.flush()  # populate user.id without committing
    logger.info("User created", user_id=str(user.id), role=user.role.value)

    from app.services import audit_log_service  # noqa: PLC0415
    from app.models.audit_log import AuditAction  # noqa: PLC0415
    await audit_log_service.record(
        db,
        actor_user_id=None,
        actor_role=None,
        action=AuditAction.CREATED,
        entity_type="User",
        entity_id=user.id,
        entity_label=user.email,
        institution_id=user.institution_id,
        after={"role": user.role.value},
    )
    return user


async def update(
    db: AsyncSession, user_id: uuid.UUID, payload: UserUpdate
) -> User:
    """
    Partially update a User.

    Returns the updated User or raises ``NotFoundError``.
    """
    user = await get_or_404(db, user_id)
    update_data = payload.model_dump(exclude_unset=True)

    if "email" in update_data and update_data["email"] != user.email:
        existing = await get_by_email(db, update_data["email"])
        if existing is not None and existing.id != user.id:
            raise ConflictError(f"Email '{update_data['email']}' is already registered")

    if "department_id" in update_data and update_data["department_id"] is not None:
        await _assert_department_institution(db, update_data["department_id"], user.institution_id)

    # If caller is changing password, re-hash it.
    if "password" in update_data:
        update_data["hashed_password"] = hash_password(update_data.pop("password"))

    for field, value in update_data.items():
        setattr(user, field, value)

    await db.flush()
    logger.info("User updated", user_id=str(user_id))

    from app.services import audit_log_service  # noqa: PLC0415
    from app.models.audit_log import AuditAction  # noqa: PLC0415
    safe_after = {k: v for k, v in update_data.items() if k != "hashed_password"}
    await audit_log_service.record(
        db,
        actor_user_id=None,
        actor_role=None,
        action=AuditAction.UPDATED,
        entity_type="User",
        entity_id=user_id,
        entity_label=user.email,
        institution_id=user.institution_id,
        after=safe_after if safe_after else None,
    )
    return user
