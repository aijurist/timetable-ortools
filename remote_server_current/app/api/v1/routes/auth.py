"""
app/api/v1/routes/auth.py
==========================
Authentication endpoints — register, login, token refresh, current user.

Endpoints
---------
POST   /api/v1/auth/register   → Create account + return token pair
POST   /api/v1/auth/login      → Email/password login → token pair
POST   /api/v1/auth/refresh    → Exchange refresh token → new token pair
GET    /api/v1/auth/me         → Return the calling user's profile (requires Bearer)
"""
# NOTE: No `from __future__ import annotations` here.
# slowapi's @limiter.limit() wrapper is defined in slowapi's module, so FastAPI
# resolves type annotations in slowapi's __globals__, not this module's globals.
# Eager annotation evaluation (the Python default) ensures Pydantic body-schema
# classes are resolved correctly at function-definition time.

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import CurrentUser, get_current_user, get_db
from app.core.config import settings
from app.core.rate_limiter import limiter
from app.schemas.agent import RefreshRequest, TokenResponse
from app.schemas.user import UserCreate, UserResponse
import app.services.auth_service as auth_svc
import app.services.user_service as user_svc


# ---------------------------------------------------------------------------
# Internal schemas — request bodies (not exported to schemas package)
# Must be defined BEFORE the route handlers so annotations are eagerly resolved.
# ---------------------------------------------------------------------------


class _LoginRequest(BaseModel):
    """Login credentials."""

    email: EmailStr
    password: str
    client_app: Literal["student_portal", "admin"] | None = Field(
        default=None,
        description='Optional client gate: "student_portal" or "admin"',
    )

    @field_validator("client_app", mode="before")
    @classmethod
    def normalize_empty_client_app(cls, value: object) -> object:
        if value == "":
            return None
        return value

    model_config = {
        "json_schema_extra": {
            "example": {
                "email": "hod@university.edu",
                "password": "secret123",
                "client_app": "admin",
            }
        }
    }


class _GoogleLoginRequest(BaseModel):
    """Google login payload."""

    id_token: str
    client_app: Literal["student_portal", "admin"] | None = Field(
        default=None,
        description='Optional client gate: "student_portal" or "admin"',
    )

    @field_validator("client_app", mode="before")
    @classmethod
    def normalize_empty_client_app(cls, value: object) -> object:
        if value == "":
            return None
        return value

    model_config = {
        "json_schema_extra": {
            "example": {
                "id_token": "some-google-jwt-token",
                "client_app": "student_portal",
            }
        }
    }


class _ForgotPasswordRequest(BaseModel):
    """Forgot-password request body."""

    email: EmailStr

    model_config = {"json_schema_extra": {"example": {"email": "teacher1.cse@campus.edu"}}}


class _ResetPasswordRequest(BaseModel):
    """Reset-password request body."""

    token: str = Field(..., description="The reset token received from /forgot-password")
    new_password: str = Field(..., min_length=8, description="The new password (min 8 chars)")

    model_config = {
        "json_schema_extra": {
            "example": {"token": "<jwt-reset-token>", "new_password": "NewPass@9999"}
        }
    }


class _ChangePasswordRequest(BaseModel):
    """Change-password request body (authenticated user)."""

    current_password: str = Field(..., description="The user's current password")
    new_password: str = Field(..., min_length=8, description="The new password (min 8 chars)")

    model_config = {
        "json_schema_extra": {
            "example": {"current_password": "OldPass@1234", "new_password": "NewPass@9999"}
        }
    }


# ---------------------------------------------------------------------------

_REFRESH_COOKIE_MAX_AGE = 7 * 24 * 3600  # 7 days — matches auth_service._REFRESH_TOKEN_EXPIRE_DAYS


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key="refresh_token",
        value=token,
        httponly=True,
        secure=settings.APP_ENV == "production",
        samesite="lax",
        max_age=_REFRESH_COOKIE_MAX_AGE,
        path="/api/v1/auth",
    )


router = APIRouter()


# ---------------------------------------------------------------------------
# POST /register
# ---------------------------------------------------------------------------


@router.post(
    "/register",
    status_code=status.HTTP_403_FORBIDDEN,
    include_in_schema=False,   # hide from public OpenAPI docs
    summary="Self-registration is disabled",
)
async def register() -> dict:
    """
    Self-registration is disabled.
    User accounts are created by an ADMIN via POST /users.
    """
    from fastapi import HTTPException
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Self-registration is disabled. Contact your campus administrator to get an account.",
    )


# ---------------------------------------------------------------------------
# POST /login
# ---------------------------------------------------------------------------


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login with email and password",
    description=(
        "Authenticates using email + password and returns a JWT token pair. "
        "Use the `access_token` in `Authorization: Bearer <token>` headers for "
        "all protected endpoints."
    ),
)
@limiter.limit("5/minute")
async def login(
    request: Request,
    payload: _LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    token_dict = await auth_svc.login(
        db,
        payload.email,
        payload.password,
        client_app=payload.client_app,
    )
    _set_refresh_cookie(response, token_dict["refresh_token"])
    return TokenResponse(**token_dict)


# ---------------------------------------------------------------------------
# POST /google  (DEV BYPASS — stress test only, requires MOCK_AUTH_BYPASS=true)
# ---------------------------------------------------------------------------


class _DevGoogleRequest(BaseModel):
    """Accepted body for the dev bypass endpoint."""
    # stress test sends: {"id_token": "mock-token-<email>", "client_app": "..."}
    id_token:   str = ""
    email:      str = ""          # alternative: pass email directly
    client_app: str = "student_portal"


@router.post(
    "/google",
    response_model=TokenResponse,
    include_in_schema=False,   # hidden from public OpenAPI docs
    summary="Dev bypass — stress test login (MOCK_AUTH_BYPASS=true only)",
)
async def dev_google_login(
    payload: _DevGoogleRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """
    Zero-cost login endpoint for stress testing.

    - Only active when ``MOCK_AUTH_BYPASS=true`` in the environment.
    - Accepts the stress-test convention: ``id_token = "mock-token-<email>"``
      or a plain ``email`` field.
    - Skips all bcrypt / Google token verification → no CPU spike.
    - Returns the same TokenResponse as POST /login so the stress test
      can reuse the existing response parsing.
    """
    if not settings.MOCK_AUTH_BYPASS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not found",
        )

    # Resolve the email from whichever field the caller populated
    email = payload.email.strip()
    if not email and payload.id_token.startswith("mock-token-"):
        email = payload.id_token[len("mock-token-"):]

    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide either 'email' or 'id_token' starting with 'mock-token-'.",
        )

    user = await user_svc.get_by_email(db, email)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown user")

    # Build tokens directly — no bcrypt, no Google round-trip
    token_dict = auth_svc._build_token_dict(user, client_app=payload.client_app)
    _set_refresh_cookie(response, token_dict["refresh_token"])
    return TokenResponse(**token_dict)


# ---------------------------------------------------------------------------
# GET /google/authorize
# ---------------------------------------------------------------------------


@router.get("/google/authorize", summary="Redirect to Google OAuth 2.0 Sign-In")
async def google_authorize(client_app: str = "student_portal", bind: str | None = None):
    from fastapi.responses import RedirectResponse
    import re

    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google Client ID is not configured."
        )
    state = client_app
    if bind is not None:
        if client_app != auth_svc._CLIENT_STUDENT_PORTAL:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="bind is only supported for student_portal",
            )
        if not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", bind):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid bind token",
            )
        state = f"{client_app}.{bind}"
    google_auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={settings.GOOGLE_CLIENT_ID}"
        f"&redirect_uri={settings.GOOGLE_CALLBACK_URL}"
        "&response_type=code"
        "&scope=openid%20email%20profile"
        f"&state={state}"
    )
    return RedirectResponse(url=google_auth_url)


# ---------------------------------------------------------------------------
# GET /google/callback
# ---------------------------------------------------------------------------


@router.get("/google/callback", summary="Google OAuth 2.0 Callback Handler")
async def google_callback(
    code: str,
    state: str = "student_portal",
    db: AsyncSession = Depends(get_db),
):
    from fastapi.responses import RedirectResponse
    from app.core.exceptions import AuthorizationError
    import app.services.audit_log_service as audit_log_service
    from app.models.audit_log import AuditAction
    from jose import jwt as jose_jwt
    import httpx
    from urllib.parse import quote
    from app.core.logger import logger

    # Determine the frontend base URL early so all error paths can redirect there
    client_app = state
    bind_token: str | None = None
    if "." in state:
        client_app, bind_token = state.split(".", 1)
    frontend_base = settings.STUDENT_PORTAL_URL if client_app == "student_portal" else settings.ADMIN_PORTAL_URL

    def redirect_error(message: str) -> RedirectResponse:
        return RedirectResponse(
            url=f"{frontend_base}/login?error=oauth_failed&message={quote(message)}"
        )

    email: str | None = None

    # Handle mock auth bypass for testing/stress tests
    if settings.MOCK_AUTH_BYPASS and code.startswith("mock-code-"):
        email = code.replace("mock-code-", "")
    else:
        if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
            return redirect_error("Google Sign-In is not configured on this server.")
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Step 1: Exchange authorization code for tokens
                token_res = await client.post(
                    "https://oauth2.googleapis.com/token",
                    data={
                        "code": code,
                        "client_id": settings.GOOGLE_CLIENT_ID,
                        "client_secret": settings.GOOGLE_CLIENT_SECRET,
                        "redirect_uri": settings.GOOGLE_CALLBACK_URL,
                        "grant_type": "authorization_code",
                    },
                )
                if token_res.status_code != 200:
                    logger.error("Step 1 Google token exchange failed with status %s", token_res.status_code)
                    return redirect_error("Failed to verify Google sign-in. Please try again.")

                token_data = token_res.json()
                id_token_str = token_data.get("id_token")
                if not id_token_str:
                    logger.error("No id_token in response from Google token exchange")
                    return redirect_error("Failed to verify Google sign-in. Please try again.")

                # Step 2: Verify the id_token via Google's tokeninfo endpoint (fully async)
                verify_res = await client.get(
                    "https://oauth2.googleapis.com/tokeninfo",
                    params={"id_token": id_token_str},
                )
                if verify_res.status_code != 200:
                    logger.error("Step 2 Google tokeninfo failed with status %s", verify_res.status_code)
                    return redirect_error("Failed to verify Google sign-in. Please try again.")

                idinfo = verify_res.json()

                # Validate the token is for our application
                if idinfo.get("aud") != settings.GOOGLE_CLIENT_ID:
                    logger.error(
                        "Audience mismatch in Google token validation: got=%s, expected=%s",
                        idinfo.get("aud"),
                        settings.GOOGLE_CLIENT_ID,
                    )
                    return redirect_error("Failed to verify Google sign-in. Please try again.")

                # Hardening checks: issuer (iss) and email_verified
                iss = idinfo.get("iss")
                if iss not in ("https://accounts.google.com", "accounts.google.com"):
                    logger.error("Issuer mismatch in Google token validation: %s", iss)
                    return redirect_error("Failed to verify Google sign-in. Please try again.")

                if idinfo.get("email_verified") not in (True, "true"):
                    logger.error("Email not verified by Google")
                    return redirect_error("Failed to verify Google sign-in. Please try again.")

                email = idinfo.get("email")

        except Exception:
            logger.exception("Google authentication exception occurred")
            return redirect_error("Failed to verify Google sign-in. Please try again.")

    if not email:
        return redirect_error("Could not retrieve your email from Google. Please try again.")

    # Perform user resolution
    user = await user_svc.get_by_email(db, email)
    if user is None:
        return redirect_error("No account found for this Google address. Contact your administrator.")

    if not user.is_active:
        return redirect_error("Your account has been disabled. Contact your administrator.")

    try:
        auth_svc.assert_client_app_allows_login(user, client_app)
        if client_app == auth_svc._CLIENT_STUDENT_PORTAL:
            await auth_svc.assert_student_portal_access(db, user)
    except AuthorizationError as exc:
        await audit_log_service.record(
            db,
            actor_user_id=user.id,
            actor_role=user.role.value,
            action=AuditAction.LOGIN,
            entity_type="User",
            entity_id=user.id,
            entity_label=user.email,
            institution_id=user.institution_id,
            after={"client_app": client_app, "rejected": True, "method": "google-code-flow"},
        )
        await db.commit()
        return redirect_error(str(exc))

    # Issue tokens
    await audit_log_service.record(
        db,
        actor_user_id=user.id,
        actor_role=user.role.value,
        action=AuditAction.LOGIN,
        entity_type="User",
        entity_id=user.id,
        entity_label=user.email,
        institution_id=user.institution_id,
        after={"method": "google-code-flow"},
    )
    await db.commit()

    token_dict = auth_svc._build_token_dict(user, client_app=client_app)
    new_payload = jose_jwt.decode(token_dict["refresh_token"], settings.SECRET_KEY, algorithms=[auth_svc._ALGORITHM])
    if jti := new_payload.get("jti"):
        await auth_svc._store_jti(str(user.id), jti)

    # Generate a short-lived one-time exchange code
    import secrets
    import json
    import app.core.redis_client as redis_client
    exchange_code = f"oauth_ex_{secrets.token_urlsafe(32)}"

    exchange_payload: dict[str, str] = dict(token_dict)
    if bind_token is not None:
        exchange_payload["_bind"] = bind_token

    r = redis_client.get_async_redis()
    try:
        await r.setex(
            f"google_oauth_exchange:{exchange_code}",
            60,
            json.dumps(exchange_payload),
        )
    finally:
        await r.aclose()

    redirect_url = f"{frontend_base}/api/auth/google-callback?code={exchange_code}"
    return RedirectResponse(url=redirect_url)


# ---------------------------------------------------------------------------
# POST /google/exchange
# ---------------------------------------------------------------------------


class _ExchangeCodeRequest(BaseModel):
    code: str
    bind: str | None = None


@router.post(
    "/google/exchange",
    response_model=TokenResponse,
    summary="Exchange short-lived one-time code for access and refresh tokens"
)
async def exchange_google_code(
    payload: _ExchangeCodeRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    import json
    import app.core.redis_client as redis_client

    code = payload.code
    if not code.startswith("oauth_ex_"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid exchange code format"
        )

    r = redis_client.get_async_redis()
    try:
        redis_key = f"google_oauth_exchange:{code}"
        token_data_str = await r.get(redis_key)
        if not token_data_str:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Exchange code expired or invalid"
            )
        await r.delete(redis_key)
    finally:
        await r.aclose()

    token_dict = json.loads(token_data_str)
    stored_bind = token_dict.pop("_bind", None)
    if stored_bind is not None:
        if payload.bind != stored_bind:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid exchange binding",
            )
    return TokenResponse(**token_dict)


# ---------------------------------------------------------------------------
# POST /refresh
# ---------------------------------------------------------------------------


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh access token",
    description=(
        "Exchange a valid refresh token for a new access + refresh token pair. "
        "The old refresh token is invalidated by rotation (the new one replaces it)."
    ),
)
@limiter.limit("30/minute")
async def refresh_token(
    request: Request,
    payload: RefreshRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    token = payload.refresh_token or request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token missing or expired. Please log in again.",
        )
    token_dict = await auth_svc.refresh(db, token)
    _set_refresh_cookie(response, token_dict["refresh_token"])
    return TokenResponse(**token_dict)


# ---------------------------------------------------------------------------
# POST /logout
# ---------------------------------------------------------------------------


@router.post(
    "/logout",
    summary="Clear refresh token cookie",
    description="Revokes the refresh token and clears the httpOnly cookie.",
)
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict:
    user_id: str | None = None
    actor_role: str | None = None

    # 1. Try refresh token cookie
    refresh_token = request.cookies.get("refresh_token")
    if refresh_token:
        try:
            payload = auth_svc.decode_token(refresh_token)
            user_id = payload.get("sub")
            actor_role = payload.get("role")
        except Exception:
            pass  # expired or invalid — fall through to access token

    # 2. Fallback: Authorization Bearer header (Swagger / mobile clients)
    if user_id is None:
        bearer = request.headers.get("Authorization", "")
        if bearer.startswith("Bearer "):
            try:
                payload = auth_svc.decode_token(bearer[7:])
                user_id = payload.get("sub")
                actor_role = payload.get("role")
            except Exception:
                pass

    if user_id:
        await auth_svc.logout(db, user_id, actor_role=actor_role)

    response.delete_cookie(key="refresh_token", path="/api/v1/auth")
    return {"detail": "Logged out"}


# ---------------------------------------------------------------------------
# POST /change-password
# ---------------------------------------------------------------------------


@router.post(
    "/change-password",
    summary="Change password for the authenticated user",
    description="Validates the current password and sets a new one. Requires Bearer token.",
)
async def change_password(
    payload: _ChangePasswordRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> dict:
    await auth_svc.change_password(
        db,
        user_id=current_user.user_id,
        current_password=payload.current_password,
        new_password=payload.new_password,
    )
    return {"detail": "Password updated successfully."}


# ---------------------------------------------------------------------------
# GET /me
# ---------------------------------------------------------------------------


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user profile",
    description="Returns the full profile of the authenticated user (requires Bearer token).",
)
async def get_me(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    import uuid

    from sqlalchemy import select

    from app.models.faculty import Faculty
    from app.models.institution import Department

    user = await user_svc.get_or_404(db, uuid.UUID(current_user.user_id))
    faculty_id = await db.scalar(
        select(Faculty.id).where(Faculty.user_id == user.id)
    )
    department_name: str | None = None
    if user.department_id:
        department_name = await db.scalar(
            select(Department.name).where(Department.id == user.department_id)
        )
    base = UserResponse.model_validate(user)
    return base.model_copy(update={"faculty_id": faculty_id, "department_name": department_name})


# ---------------------------------------------------------------------------
# POST /forgot-password
# ---------------------------------------------------------------------------


@router.post(
    "/forgot-password",
    summary="Request a password reset link",
    description=(
        "Accepts an email address, generates a short-lived reset token (30 min), "
        "and sends it to the user's email inbox. "
        "Always returns HTTP 200 regardless of whether the email is registered "
        "(prevents email enumeration)."
    ),
)
@limiter.limit("3/minute")
async def forgot_password(
    request: Request,
    payload: _ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await auth_svc.forgot_password(db, payload.email)


# ---------------------------------------------------------------------------
# POST /reset-password
# ---------------------------------------------------------------------------


@router.post(
    "/reset-password",
    summary="Reset password using a reset token",
    description=(
        "Validates the reset token (issued by /forgot-password) and updates "
        "the user's password. The token is a signed JWT with a 30-minute expiry."
    ),
)
@limiter.limit("5/minute")
async def reset_password(
    request: Request,
    payload: _ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await auth_svc.reset_password(db, payload.token, payload.new_password)
    return {"detail": "Password updated successfully."}
