"""
FastAPI dependency injection helpers for API v1.

Usage in route handlers:
    @router.get("/")
    async def list_items(
        db: AsyncSession = Depends(get_db),
        pagination: PaginationParams = Depends(get_pagination),
        current_user: CurrentUser = Depends(get_current_user),
    ):
        ...
"""

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Query, status
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logger import logger
from app.db.session import get_db  # re-export for convenience
from app.models.user import UserRole

__all__ = [
    "get_db",
    "get_current_user",
    "get_current_user_sse",
    "get_pagination",
    "require_admin",
    "require_super_admin",
    "require_hod",
    "require_role",
    "assert_same_institution",
    "actor_institution_id",
    "hod_dept_filter",
    "CurrentUser",
    "PaginationParams",
    "UserRole",
]


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

@dataclass
class PaginationParams:
    skip: int
    limit: int


def get_pagination(
    skip: int = Query(default=0, ge=0, description="Number of records to skip"),
    limit: int = Query(default=20, ge=1, le=10000, description="Max records to return"),
) -> PaginationParams:
    return PaginationParams(skip=skip, limit=limit)


# ---------------------------------------------------------------------------
# Typed identity returned by get_current_user
# ---------------------------------------------------------------------------

@dataclass
class CurrentUser:
    """
    Decoded JWT payload as a typed object.

    Populated from JWT claims:
        sub             → user_id       (UUID string)
        role            → UserRole enum member
        institution_id  → UUID string (None for SUPER_ADMIN)
        dept            → department code string (None for ADMIN/SUPER_ADMIN)
        department_id   → department UUID string (None for ADMIN/SUPER_ADMIN)
    """
    user_id: str
    role: UserRole
    institution_id: str | None
    department: str | None
    department_id: str | None = None

    # Convenience helpers --------------------------------------------------
    @property
    def is_admin(self) -> bool:
        return self.role in (UserRole.ADMIN, UserRole.SUPER_ADMIN)

    @property
    def is_super_admin(self) -> bool:
        return self.role == UserRole.SUPER_ADMIN

    @property
    def is_hod(self) -> bool:
        return self.role in (UserRole.HOD, UserRole.ADMIN, UserRole.SUPER_ADMIN)

    @property
    def user_uuid(self) -> uuid.UUID:
        return uuid.UUID(self.user_id)

    @property
    def department_uuid(self) -> uuid.UUID | None:
        return uuid.UUID(self.department_id) if self.department_id else None

# ---------------------------------------------------------------------------
# Auth / JWT
# ---------------------------------------------------------------------------

async def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
) -> CurrentUser:
    """
    Decode the Bearer JWT and return a typed ``CurrentUser``.

    Expected JWT payload shape::
        {
            "sub":            "<user_uuid>",
            "role":           "student|teacher|hod|admin|super_admin",
            "institution_id": "<uuid>|null",
            "dept":           "<dept_code>|null"
        }
    """
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not authorization:
        raise credentials_exc

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise credentials_exc

    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
    except JWTError as exc:
        logger.debug("JWT decode failed", error=str(exc))
        raise credentials_exc from exc

    user_id: str | None = payload.get("sub")
    raw_role: str | None = payload.get("role")
    if not user_id or not raw_role:
        raise credentials_exc

    try:
        role = UserRole(raw_role)
    except ValueError:
        raise credentials_exc

    return CurrentUser(
        user_id=user_id,
        role=role,
        institution_id=payload.get("institution_id"),
        department=payload.get("dept"),
        department_id=payload.get("department_id"),
    )


async def get_current_user_sse(
    token: Annotated[str | None, Query()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> CurrentUser:
    """Auth dependency for SSE endpoints.

    Prefer ``Authorization: Bearer`` (fetch-based SSE proxy). The ``?token=``
    query parameter is rejected in production because it leaks JWTs via logs
    and browser history.
    """
    if token:
        if settings.APP_ENV == "production":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Token query parameter is not allowed",
            )
        authorization = f"Bearer {token}"
    return await get_current_user(authorization=authorization)


# ---------------------------------------------------------------------------
# Role guards — use as FastAPI dependencies
# ---------------------------------------------------------------------------

async def require_admin(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> CurrentUser:
    """Raises 403 unless caller is ADMIN or SUPER_ADMIN."""
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


async def require_super_admin(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> CurrentUser:
    """Raises 403 unless caller is SUPER_ADMIN."""
    if not current_user.is_super_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super-admin access required",
        )
    return current_user


async def require_hod(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> CurrentUser:
    """Raises 403 unless caller is HOD, ADMIN, or SUPER_ADMIN."""
    if not current_user.is_hod:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="HOD or Admin access required",
        )
    return current_user


def assert_same_institution(
    current_user: "CurrentUser",
    resource_institution_id: "uuid.UUID | None",
) -> None:
    """Raise 403 if the resource belongs to a different institution.

    Super-admins bypass this check entirely.
    """
    if current_user.is_super_admin:
        return
    if current_user.institution_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No institution assigned to your account",
        )
    if resource_institution_id is None or str(resource_institution_id) != current_user.institution_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: resource belongs to a different institution",
        )


def actor_institution_id(
    current_user: "CurrentUser",
    payload_institution_id: "uuid.UUID | None" = None,
) -> uuid.UUID:
    """Return the institution_id to use for create/list operations.

    - Super-admins: use payload_institution_id (required).
    - All others: institution_id from the JWT (payload value is ignored).
    """
    if current_user.is_super_admin:
        if payload_institution_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="institution_id is required for super_admin operations",
            )
        return payload_institution_id
    if current_user.institution_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No institution assigned to your account",
        )
    return uuid.UUID(current_user.institution_id)


def require_role(*allowed_roles: UserRole):
    """
    Factory that returns a dependency raising 403 if the caller's role
    is not in ``allowed_roles``.

    Usage::
        @router.post("/")
        async def create(
            current_user: CurrentUser = Depends(require_role(UserRole.ADMIN, UserRole.HOD)),
        ): ...
    """
    async def _guard(
        current_user: Annotated[CurrentUser, Depends(get_current_user)],
    ) -> CurrentUser:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access requires one of: {[r.value for r in allowed_roles]}",
            )
        return current_user
    return _guard


def hod_dept_filter(current_user: CurrentUser) -> uuid.UUID | None:
    """Return department_id to scope queries when caller is strict HOD; None for ADMIN+.

    Use this to automatically filter list endpoints to only show a HOD's own department data.
    ADMIN and SUPER_ADMIN always get None (no department filter applied).
    """
    if current_user.role == UserRole.HOD:
        return current_user.department_uuid
    return None