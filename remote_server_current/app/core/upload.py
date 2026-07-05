"""
app/core/upload.py
======================
Bulk upload configuration.
"""
from __future__ import annotations

MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_EXTENSIONS: set[str] = {".csv", ".xlsx"}
MAX_BULK_ROWS = 1000
STUDENT_DEFAULT_PASSWORD = "DefaultPassword@123"
FACULTY_DEFAULT_PASSWORD = "DefaultPassword@123"
