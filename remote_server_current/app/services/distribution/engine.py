"""
app/services/distribution/engine.py
===================================
The single entry point for turning a cohort's demand into its data model.

    result = await distribute(db, demand)

Dispatches by mode to the concrete strategy, after (for re-distribution) clearing
the cohort's prior auto-distribution. Flush only — the caller owns the commit.
"""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.distribution.base import DistributionStrategy
from app.services.distribution.contracts import DistributionDemand, DistributionResult
from app.services.distribution.ffcs import FfcsDistribution
from app.services.distribution.hybrid import HybridDistribution
from app.services.distribution.persistence import reset_prior_distribution
from app.services.distribution.traditional import TraditionalDistribution

_STRATEGIES: dict[str, DistributionStrategy] = {
    "TRADITIONAL": TraditionalDistribution(),
    "HYBRID": HybridDistribution(),
    "FFCS": FfcsDistribution(),
    "ELECTIVE": FfcsDistribution(),
}


def _normalize_mode(mode: str | None) -> str:
    code = (mode or "TRADITIONAL").upper()
    return code[: -len("_DIST")] if code.endswith("_DIST") else code


async def distribute(
    db: AsyncSession,
    demand: DistributionDemand,
    *,
    reset_first: bool = False,
    full_reset: bool = False,
) -> DistributionResult:
    """Build (or rebuild) a cohort's buckets + offerings for its mode.

    reset_first: clear the cohort's prior distribution before rebuilding.
    full_reset: when True with reset_first, delete all cohort buckets/offerings
    including previously solved rows (solver regroup / force-rerun).
    """
    if reset_first:
        await reset_prior_distribution(
            db,
            uuid.UUID(demand.cohort_id),
            full_reset=full_reset,
        )

    mode = _normalize_mode(demand.mode)
    strategy = _STRATEGIES.get(mode, _STRATEGIES["TRADITIONAL"])
    return await strategy.build(db, demand)
