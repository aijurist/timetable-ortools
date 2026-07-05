"""
app/schemas/notification.py
============================
Pydantic schemas for notification API.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.models.notification import NotificationChannel, NotificationType


class NotificationResponse(BaseModel):
    id: uuid.UUID
    institution_id: uuid.UUID
    recipient_user_id: uuid.UUID
    notification_type: NotificationType
    title: str
    body: str
    metadata_: dict[str, Any] | None = None
    channel: NotificationChannel
    is_read: bool
    read_at: datetime | None
    created_at: datetime
    expires_at: datetime | None

    model_config = {"from_attributes": True}


class NotificationListResponse(BaseModel):
    items: list[NotificationResponse]
    total: int
    unread_count: int
    skip: int
    limit: int


class NotificationPreferenceResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    email_enabled: bool
    push_enabled: bool
    disabled_types: list[str]

    model_config = {"from_attributes": True}


class NotificationPreferenceUpdate(BaseModel):
    email_enabled: bool | None = None
    push_enabled: bool | None = None
    disabled_types: list[str] | None = None
