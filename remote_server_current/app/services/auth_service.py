"""
app/services/auth_service.py
=============================
JWT issuance, validation, and login flow.

Responsibilities
----------------
* Create access tokens and refresh tokens (HS256 JWTs via python-jose).
* Decode and validate tokens.
* ``login``            — verify credentials and return a token pair.
* ``register``         — thin wrapper over user_service.create that returns a token pair.
* ``forgot_password``  — generate a short-lived reset token (30 min).
* ``reset_password``   — validate reset token and update hashed password.

Does NOT touch the DB directly for user mutations — delegates to user_service.
"""
from __future__ import annotations

import asyncio
import uuid as _uuid_module
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.email import send_email
from app.core.exceptions import AuthenticationError, AuthorizationError, NotFoundError, ValidationError
from app.core.logger import logger
from app.core.redis_client import get_async_redis
from app.models.user import User, UserRole
from app.schemas.user import UserCreate

import app.services.user_service as user_svc
import app.services.audit_log_service as audit_log_service
from app.models.audit_log import AuditAction
from app.models.institution import AcademicTerm
from app.models.selection_access_config import SelectionAccessConfig
from app.models.student import StudentProfile
from sqlalchemy import select

_ALGORITHM = "HS256"
_REFRESH_TOKEN_EXPIRE_DAYS = 7


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------


def create_access_token(
    data: dict[str, Any],
    expires_delta: timedelta | None = None,
) -> str:
    """
    Return a signed JWT access token.

    *data* must include at minimum ``{"sub": str(user.id)}``.
    The ``exp`` claim is added automatically.
    """
    to_encode = data.copy()
    expire = datetime.now(tz=timezone.utc) + (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode["exp"] = expire
    to_encode.setdefault("type", "access")
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=_ALGORITHM)


def create_refresh_token(data: dict[str, Any]) -> str:
    """
    Return a signed JWT refresh token (7-day expiry).

    *data* must include at minimum ``{"sub": str(user.id)}``.
    Each token gets a unique ``jti`` so it can be revoked in Redis on logout.
    """
    to_encode = data.copy()
    to_encode["exp"] = datetime.now(tz=timezone.utc) + timedelta(
        days=_REFRESH_TOKEN_EXPIRE_DAYS
    )
    to_encode["type"] = "refresh"
    to_encode["jti"] = str(_uuid_module.uuid4())
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=_ALGORITHM)


# ---------------------------------------------------------------------------
# Refresh token JTI tracking (Redis-backed revocation)
# ---------------------------------------------------------------------------

_JTI_PREFIX = "refresh_jti:"
_JTI_TTL = _REFRESH_TOKEN_EXPIRE_DAYS * 86_400  # seconds


async def _store_jti(user_id: str, jti: str) -> None:
    r = get_async_redis()
    try:
        await r.setex(f"{_JTI_PREFIX}{user_id}", _JTI_TTL, jti)
    finally:
        await r.aclose()


async def _jti_valid(user_id: str, jti: str) -> bool:
    """Return True if jti matches the stored one, or no entry exists yet (first use after deploy)."""
    r = get_async_redis()
    try:
        stored = await r.get(f"{_JTI_PREFIX}{user_id}")
        return stored is None or stored == jti
    finally:
        await r.aclose()


async def revoke_refresh_token(user_id: str) -> None:
    """Delete the stored JTI, invalidating any outstanding refresh token for this user."""
    r = get_async_redis()
    try:
        await r.delete(f"{_JTI_PREFIX}{user_id}")
    finally:
        await r.aclose()


async def logout(
    db: AsyncSession,
    user_id: str,
    actor_role: str | None = None,
) -> None:
    """Revoke the refresh token and record a LOGOUT audit event."""
    import uuid as _uuid_mod
    try:
        await revoke_refresh_token(user_id)
    except Exception:  # noqa: BLE001
        logger.warning("Token revocation failed during logout", user_id=user_id)
    try:
        uid = _uuid_mod.UUID(user_id)
    except (ValueError, AttributeError):
        uid = None
    await audit_log_service.record(
        db,
        actor_user_id=uid,
        actor_role=actor_role,
        action=AuditAction.LOGOUT,
        entity_type="User",
        entity_id=uid,
    )
    await db.commit()


def decode_token(token: str) -> dict[str, Any]:
    """
    Decode and return the payload of *token*.

    Raises ``ValidationError`` if the token is expired or invalid.
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[_ALGORITHM])
        return payload
    except JWTError as exc:
        raise ValidationError(f"Invalid or expired token: {exc}") from exc


def _build_token_dict(user: User, *, client_app: str | None = None) -> dict[str, str]:
    """Return ``{access_token, refresh_token, token_type}`` for *user*."""
    claims = {
        "sub": str(user.id),
        "role": user.role.value,
        "institution_id": str(user.institution_id) if user.institution_id else None,
        "dept": user.department_rel.code if user.department_rel else None,
        "department_id": str(user.department_id) if user.department_id else None,
    }
    access = create_access_token(claims)
    refresh_claims: dict[str, Any] = {"sub": str(user.id)}
    if client_app in _VALID_CLIENT_APPS:
        refresh_claims["client_app"] = client_app
    refresh = create_refresh_token(refresh_claims)
    return {"access_token": access, "refresh_token": refresh, "token_type": "bearer"}


# ---------------------------------------------------------------------------
# Auth flows
# ---------------------------------------------------------------------------


async def register(db: AsyncSession, payload: UserCreate) -> dict[str, str]:
    """
    Register a new user and return a JWT token pair.

    Delegates creation to ``user_service.create``.
    """
    user = await user_svc.create(db, payload)
    await db.commit()
    user = await user_svc.get_by_id(db, user.id)  # reload with selectinload for department_rel
    logger.info("User registered", user_id=str(user.id))
    return _build_token_dict(user)


_CLIENT_STUDENT_PORTAL = "student_portal"
_CLIENT_ADMIN = "admin"
_VALID_CLIENT_APPS = frozenset({_CLIENT_STUDENT_PORTAL, _CLIENT_ADMIN})
_PORTAL_DENIED = "Login not permitted for this application."


def assert_client_app_allows_login(user: User, client_app: str | None) -> None:
    """Raise when *user*'s role is wrong for *client_app*."""
    if client_app is None:
        return
    if client_app not in _VALID_CLIENT_APPS:
        raise ValidationError("Invalid client_app")
    if client_app == _CLIENT_STUDENT_PORTAL:
        if user.role != UserRole.STUDENT:
            raise AuthorizationError(_PORTAL_DENIED)
    elif user.role == UserRole.STUDENT:
        raise AuthorizationError(_PORTAL_DENIED)


async def assert_student_portal_access(db: AsyncSession, user: User) -> None:
    """
    Check if the student is permitted to log in for the current active term based
    on SelectionAccessConfig. Early access emails bypass all checks.
    """
    if user.role != UserRole.STUDENT:
        return

    # Find the active academic term
    term_res = await db.execute(
        select(AcademicTerm).where(
            AcademicTerm.institution_id == user.institution_id,
            AcademicTerm.is_active == True
        )
    )
    active_term = term_res.scalars().first()
    if not active_term:
        raise AuthorizationError("No active academic term found. Login is currently disabled.")

    # Find the access config
    cfg_res = await db.execute(
        select(SelectionAccessConfig).where(
            SelectionAccessConfig.institution_id == user.institution_id,
            SelectionAccessConfig.academic_term_id == active_term.id
        )
    )
    cfg = cfg_res.scalars().first()
    if not cfg:
        # Default behavior if no config is created: allow all
        return

    # 1. Check early access bypass
    if cfg.early_access_emails and user.email in cfg.early_access_emails:
        return

    # 2. Need student profile to check semester/department
    profile_res = await db.execute(
        select(StudentProfile).where(StudentProfile.user_id == user.id)
    )
    profile = profile_res.scalars().first()
    if not profile:
        raise AuthorizationError("Student profile not found.")

    # 3. Check login gates. Empty arrays mean "block all" for that dimension.
    years_allowed = profile.year_of_study in (cfg.allowed_login_years or [])

    depts_allowed = (
        user.department_id is not None and 
        str(user.department_id) in (cfg.allowed_login_departments or [])
    )

    if not years_allowed or not depts_allowed:
        raise AuthorizationError("Login is not yet open for your batch or department.")


async def login(
    db: AsyncSession,
    email: str,
    password: str,
    *,
    client_app: str | None = None,
) -> dict[str, str]:
    """
    Verify credentials and return a JWT token pair.

    Raises
    ------
    ``NotFoundError`` (401-equivalent) if email not found.
    ``ValidationError`` if password does not match.
    """
    user = await user_svc.get_by_email(db, email)
    if user is None:
        raise AuthenticationError("Incorrect email or password")

    if not user_svc.verify_password(password, user.hashed_password):
        raise AuthenticationError("Incorrect email or password")

    if not user.is_active:
        raise AuthenticationError("Account is disabled")

    try:
        assert_client_app_allows_login(user, client_app)
        if client_app == _CLIENT_STUDENT_PORTAL:
            await assert_student_portal_access(db, user)
    except AuthorizationError as exc:
        logger.warning(
            "Login rejected for client_app",
            user_id=str(user.id),
            role=user.role.value,
            client_app=client_app,
        )
        await audit_log_service.record(
            db,
            actor_user_id=user.id,
            actor_role=user.role.value,
            action=AuditAction.LOGIN,
            entity_type="User",
            entity_id=user.id,
            entity_label=user.email,
            institution_id=user.institution_id,
            after={"client_app": client_app, "rejected": True},
        )
        await db.commit()
        raise

    logger.info("User logged in", user_id=str(user.id), role=user.role.value, client_app=client_app)
    await audit_log_service.record(
        db,
        actor_user_id=user.id,
        actor_role=user.role.value,
        action=AuditAction.LOGIN,
        entity_type="User",
        entity_id=user.id,
        entity_label=user.email,
        institution_id=user.institution_id,
    )
    await db.commit()
    token_dict = _build_token_dict(user, client_app=client_app)
    # Track JTI so the token can be revoked on logout
    new_payload = jwt.decode(token_dict["refresh_token"], settings.SECRET_KEY, algorithms=[_ALGORITHM])
    if jti := new_payload.get("jti"):
        await _store_jti(str(user.id), jti)
    return token_dict


async def refresh(db: AsyncSession, refresh_token: str) -> dict[str, str]:
    """
    Exchange a valid refresh token for a new access + refresh token pair.

    The old token's JTI is validated against Redis and the new JTI is stored,
    so each token can only be used once (rotation + revocation on logout).
    """
    payload = decode_token(refresh_token)
    if payload.get("type") != "refresh":
        raise ValidationError("Provided token is not a refresh token")

    user_id_str: str = payload["sub"]
    jti: str | None = payload.get("jti")

    if jti and not await _jti_valid(user_id_str, jti):
        raise AuthenticationError("Refresh token has been revoked. Please log in again.")

    user_id = _uuid_module.UUID(user_id_str)
    user = await user_svc.get_or_404(db, user_id)

    stored_client_app = payload.get("client_app")
    if isinstance(stored_client_app, str):
        assert_client_app_allows_login(user, stored_client_app)
        if stored_client_app == _CLIENT_STUDENT_PORTAL:
            await assert_student_portal_access(db, user)

    token_dict = _build_token_dict(
        user,
        client_app=stored_client_app if isinstance(stored_client_app, str) else None,
    )
    new_payload = jwt.decode(token_dict["refresh_token"], settings.SECRET_KEY, algorithms=[_ALGORITHM])
    if new_jti := new_payload.get("jti"):
        await _store_jti(user_id_str, new_jti)

    logger.info("Token refreshed", user_id=user_id_str)
    return token_dict


async def change_password(
    db: AsyncSession, user_id: str, current_password: str, new_password: str
) -> None:
    """Validate current_password and update to new_password for an authenticated user."""
    user = await user_svc.get_or_404(db, _uuid_module.UUID(user_id))
    if not user_svc.verify_password(current_password, user.hashed_password):
        raise AuthenticationError("Current password is incorrect")
    user.hashed_password = user_svc.hash_password(new_password)
    db.add(user)
    await audit_log_service.record(
        db,
        actor_user_id=user.id,
        actor_role=user.role.value,
        action=AuditAction.PASSWORD_CHANGED,
        entity_type="User",
        entity_id=user.id,
        entity_label=user.email,
        institution_id=user.institution_id,
    )
    await db.commit()
    logger.info("Password changed", user_id=user_id)


# ---------------------------------------------------------------------------
# Password reset flow
# ---------------------------------------------------------------------------

_RESET_TOKEN_EXPIRE_MINUTES = 30


async def _send_reset_email_async(email: str, token: str) -> None:
    """Fire-and-forget: send the password-reset link via email."""
    try:
        reset_link = f"{settings.RESET_PASSWORD_BASE_URL}/reset-password?token={token}"

        html = f"""\
<html>
<body style="font-family:sans-serif;padding:32px;background:#f5f5f5">
<div style="max-width:480px;margin:auto;background:#fff;border-radius:12px;padding:32px">
<div style="margin-bottom:20px">
<span style="font-weight:700;font-size:16px;color:#222">Exovance Campus Core</span>
</div>
<h2 style="margin-top:0">Reset your Exovance password</h2>
<p>Click the button below to reset your password. This link expires in 30 minutes.</p>
<a href="{reset_link}"
   style="display:inline-block;padding:12px 28px;background:linear-gradient(135deg,#c3c0ff,#3f33d6);color:#fff;border-radius:8px;text-decoration:none;font-weight:600;margin:16px 0">
  Reset Password
</a>
<p style="color:#888;font-size:12px">If you didn't request this, you can safely ignore this email.</p>
</div>
</body>
</html>"""

        await send_email(email, "Reset your Exovance password", html)

    except Exception:
        logger.exception("Failed to send password-reset email to %s", email)


async def forgot_password(db: AsyncSession, email: str) -> dict[str, str]:
    """
    Generate a short-lived password-reset token for *email* and dispatch it
    via email.

    Security: Always returns HTTP 200 regardless of whether the email
    exists — prevents email enumeration attacks. No token is ever returned
    in the response body.
    """
    user = await user_svc.get_by_email(db, email)

    if user is None:
        logger.info("Forgot-password: email not found (silent)", email=email)
        return {"detail": "If that email is registered, a reset link has been sent."}

    if not user.is_active:
        logger.info("Forgot-password: inactive account (silent)", user_id=str(user.id))
        return {"detail": "If that email is registered, a reset link has been sent."}

    reset_token = create_access_token(
        data={"sub": str(user.id), "type": "password_reset"},
        expires_delta=timedelta(minutes=_RESET_TOKEN_EXPIRE_MINUTES),
    )

    asyncio.create_task(_send_reset_email_async(user.email, reset_token))

    return {"detail": "If that email is registered, a reset link has been sent."}


async def reset_password(db: AsyncSession, reset_token: str, new_password: str) -> None:
    """
    Validate *reset_token* and update the user's password.

    Raises
    ------
    ``ValidationError`` — token is expired, invalid, or wrong type.
    ``AuthenticationError`` — account is disabled.
    """
    import uuid

    payload = decode_token(reset_token)

    if payload.get("type") != "password_reset":
        raise ValidationError("Invalid reset token")

    user_id = uuid.UUID(payload["sub"])
    user = await user_svc.get_or_404(db, user_id)

    if not user.is_active:
        raise AuthenticationError("Account is disabled")

    user.hashed_password = user_svc.hash_password(new_password)
    db.add(user)
    await audit_log_service.record(
        db,
        actor_user_id=user.id,
        actor_role=user.role.value,
        action=AuditAction.PASSWORD_CHANGED,
        entity_type="User",
        entity_id=user.id,
        entity_label=user.email,
        institution_id=user.institution_id,
    )
    await db.commit()

    logger.info("Password reset successfully", user_id=str(user_id))
