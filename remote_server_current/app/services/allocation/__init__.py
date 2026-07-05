"""
app/services/allocation/
========================
Pre-solve allocation layer: converts coordinator demand into DB rows
(OfferingBuckets, CourseOfferings, TargetRequirements) ready for the
assembly layer and solver engine.

Pipeline position:
  target_course_demand + faculty list (coordinator input)
        ↓
  allocation/              ← THIS LAYER — creates DB rows
        ↓
  DB: OfferingBuckets, CourseOfferings, TargetRequirements
        ↓
  assembly/                ← EXISTING — reads DB → SchedulerInput
        ↓
  solver engine

Public API:
  from app.services.allocation.service import (
      get_demand, add_demand, delete_demand,
      get_allocation_state, run_allocation, reset_allocation,
  )
"""

from typing import Protocol, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from app.schemas.allocation import AllocationResult, CourseAssignment


class AllocationStrategy(Protocol):
    """
    Protocol for per-mode allocation strategies.

    Each strategy handles one allocation_mode value
    (per_section / shared_dept / shared_cross_dept / open_pool).
    """

    async def allocate(
        self,
        course_assignment: "CourseAssignment",
        solver_assignments: dict[tuple[str, str], str],
        ctx: Any,
    ) -> "AllocationResult":
        """
        Create OfferingBuckets + CourseOfferings + TargetRequirements for one
        course (and all targets that demand it).

        Parameters
        ----------
        course_assignment : CourseAssignment
            Per-course coordinator input (faculty_ids, allocation_mode, etc.)
        solver_assignments : dict[(target_id, course_id) → faculty_id]
            Output from engine.run_allocation_solver() — only used by per_section mode.
        ctx : AllocationContext
            Read-only context (db session, scenario, demand rows, ORM lookups).

        Returns
        -------
        AllocationResult
            Counts and details for this course's allocation; caller aggregates.
        """
        ...
