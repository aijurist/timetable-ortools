"""
app/services/distribution/hybrid.py
===================================
HYBRID distribution: teacher-pool groups via the group_optimizer sub-solver.
Buckets use CHOOSE_FACULTY; group_number is written atomically (see grouped.py).
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.curriculum import SelectionPolicy
from app.services.distribution.base import DistributionStrategy
from app.services.distribution.contracts import DistributionDemand, DistributionResult
from app.services.distribution.grouped import build_grouped


class HybridDistribution(DistributionStrategy):
    code = "HYBRID_DIST"

    async def build(
        self, db: AsyncSession, demand: DistributionDemand
    ) -> DistributionResult:
        return await build_grouped(
            db,
            demand,
            scheduling_mode="HYBRID",
            selection_policy=SelectionPolicy.CHOOSE_FACULTY,
        )
