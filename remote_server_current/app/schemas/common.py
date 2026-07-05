"""
common.py
=========
Shared Pydantic building blocks used across all schema modules.
"""

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """
    Generic paginated list wrapper.

    Usage::
        PaginatedResponse[CourseResponse](
            items=[...], total=42, skip=0, limit=20
        )
    """

    items: list[T]
    total: int
    skip: int
    limit: int
