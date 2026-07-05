"""
app/services/distribution/ffcs.py
=================================
FFCS distribution: open-pool groups via the group_optimizer sub-solver (FFCS
branch — size-balance only). Buckets use OPEN_POOL; group_number is written
atomically (see grouped.py).
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.curriculum import SelectionPolicy
from app.services.distribution.base import DistributionStrategy
from app.services.distribution.contracts import DistributionDemand, DistributionResult
from app.services.distribution.grouped import build_grouped


class FfcsDistribution(DistributionStrategy):
    code = "FFCS_DIST"

    async def build(
        self, db: AsyncSession, demand: DistributionDemand
    ) -> DistributionResult:
        return await build_grouped(
            db,
            demand,
            scheduling_mode="FFCS",
            selection_policy=SelectionPolicy.OPEN_POOL,
        )
