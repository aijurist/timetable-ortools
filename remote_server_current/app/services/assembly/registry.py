"""
app/services/assembly/registry.py
===================================
ASSEMBLY_REGISTRY: maps SelectionPolicy → AssemblyStrategy instance.

Adding a new policy = 2 steps:
  1. Write a new XxxAssembler class in a new file.
  2. Add one line to ASSEMBLY_REGISTRY below.
  No other file touched.
"""

from __future__ import annotations

from app.services.assembly.choice import ChoiceAssembler
from app.services.assembly.fixed_batch import FixedBatchAssembler
from app.services.assembly.open_pool import OpenPoolAssembler


# Import the enum lazily to avoid circular imports at module load
def _get_registry():
    from app.models.curriculum import SelectionPolicy  # type: ignore
    choice = ChoiceAssembler()
    return {
        SelectionPolicy.FIXED_BATCH:    FixedBatchAssembler(),
        SelectionPolicy.CHOOSE_FACULTY: choice,
        SelectionPolicy.CHOOSE_COURSE:  choice,   # same logic — force_parallel_slots flag drives behaviour
        SelectionPolicy.OPEN_POOL:      OpenPoolAssembler(),
    }


# Singleton registry — populated lazily on first access
_REGISTRY = None


def get_assembly_registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _get_registry()
    return _REGISTRY
