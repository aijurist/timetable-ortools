"""
app/services/distribution
=========================
Unified cohort distribution engine — the single owner of the
demand → (targets + buckets + offerings + group assignment) transformation.

Public API:
    from app.services.distribution.engine import distribute
    from app.services.distribution import DistributionDemand, CourseLine

`__init__` deliberately re-exports only the lightweight contracts + ABC and does
NOT import `engine`/strategies, so a strategy importing `persistence` through the
package does not create an import cycle. Import `distribute` from `.engine`.
"""
from __future__ import annotations

from app.services.distribution.base import MODE_DEFAULT_DIST, DistributionStrategy
from app.services.distribution.contracts import (
    CourseLine,
    DistributionDemand,
    DistributionResult,
    RelaxationHint,
)

__all__ = [
    "DistributionDemand",
    "DistributionResult",
    "RelaxationHint",
    "CourseLine",
    "DistributionStrategy",
    "MODE_DEFAULT_DIST",
]
