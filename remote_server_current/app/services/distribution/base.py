"""
app/services/distribution/base.py
=================================
DistributionStrategy ABC + mode→default-rule map.

Strategies write DB records (stateful, one-time at cohort creation) — contrast
with solver constraints which add CP-SAT clauses (pure, every solve). Same ABC
idea, different execution context. Concrete strategies live in traditional.py /
hybrid.py / ffcs.py and are wired by engine.py.

Supersedes the stub app/services/distribution_strategies.py (which delegated to
allocation.service._run_inline_allocation).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.services.distribution.contracts import DistributionDemand, DistributionResult


class DistributionStrategy(ABC):
    """Turns a cohort's DistributionDemand into persisted buckets + offerings."""

    code: str

    @abstractmethod
    async def build(
        self,
        db: "AsyncSession",
        demand: "DistributionDemand",
    ) -> "DistributionResult":
        """Create SchedulingTarget children / OfferingBuckets / CourseOfferings.

        Implementations flush but do not commit — the caller owns the transaction.
        """


# Mode → base distribution rule code (seeded at scenario creation).
MODE_DEFAULT_DIST: dict[str, str] = {
    "TRADITIONAL": "TRADITIONAL_DIST",
    "HYBRID": "HYBRID_DIST",
    "FFCS": "FFCS_DIST",
    "ELECTIVE": "FFCS_DIST",
}
