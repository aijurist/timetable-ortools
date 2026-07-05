"""
app/schemas/bulk_upload.py
===========================
Schemas for bulk upload preview and import.
"""

from __future__ import annotations

import enum
import uuid
from typing import Any

from pydantic import BaseModel, Field


class BulkRowStatus(str, enum.Enum):
    CREATE = "create"
    UPDATE = "update"
    ERROR = "error"


class BulkUploadRow(BaseModel):
    row_number: int
    status: BulkRowStatus
    data: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    existing_id: str | None = None


class BulkUploadPreview(BaseModel):
    total_rows: int
    to_create: list[BulkUploadRow]
    to_update: list[BulkUploadRow]
    errors: list[BulkUploadRow]
    workload_deltas: dict[str, int] = Field(default_factory=dict)


class BulkImportResult(BaseModel):
    imported: int
    updated: int
    failed: int
    errors: list[BulkUploadRow]
    workload_impact: list[dict[str, Any]] = Field(default_factory=list)


class BulkImportRequest(BaseModel):
    rows: list[BulkUploadRow]


class BulkUploadPreviewResponse(BaseModel):
    resource: str
    preview: BulkUploadPreview
