"""
user.py
=======
Pydantic V2 schemas for the User domain.

Never include ``hashed_password`` in any response schema.
"""

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.upload import FACULTY_DEFAULT_PASSWORD
from app.models.faculty import DesignationType
from app.models.user import GenderType, UserRole


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class UserCreate(BaseModel):
    """Body for POST /auth/register and POST /users (admin only)."""

    email: EmailStr
    password: str = Field(default=FACULTY_DEFAULT_PASSWORD, min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=255)
    role: UserRole = UserRole.STUDENT
    institution_id: Optional[uuid.UUID] = None
    department_id: Optional[uuid.UUID] = Field(default=None, description="FK → departments.id")
    academic_title: Optional[DesignationType] = None
    phone: Optional[str] = Field(default=None, max_length=20)
    gender: Optional[GenderType] = None


class UserUpdate(BaseModel):
    """Body for PATCH /users/{id} — all fields optional."""

    email: Optional[EmailStr] = None
    password: Optional[str] = Field(default=None, min_length=8, max_length=128)
    full_name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    role: Optional[UserRole] = None
    department_id: Optional[uuid.UUID] = Field(default=None, description="FK → departments.id")
    academic_title: Optional[DesignationType] = None
    phone: Optional[str] = Field(default=None, max_length=20)
    gender: Optional[GenderType] = None
    is_active: Optional[bool] = None
    avatar_url: Optional[str] = Field(default=None, max_length=500)


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class UserResponse(BaseModel):
    """Returned by all user-facing endpoints. No hashed_password."""

    id: uuid.UUID
    email: EmailStr
    full_name: str
    role: UserRole
    institution_id: Optional[uuid.UUID]
    department_id: Optional[uuid.UUID]
    department_name: Optional[str] = None
    is_active: bool
    is_verified: bool
    avatar_url: Optional[str]
    academic_title: Optional[DesignationType] = None
    phone: Optional[str] = None
    gender: Optional[GenderType] = None
    last_login_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    faculty_id: Optional[uuid.UUID] = None

    model_config = {"from_attributes": True}
