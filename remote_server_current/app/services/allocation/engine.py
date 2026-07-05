# DEPRECATED: logic moved to solver_engine/allocation_optimizer/.
# Re-exported here for backward compatibility only.
from solver_engine.allocation_optimizer.contracts import AllocationInput, AllocationOutput
from solver_engine.allocation_optimizer.optimizer import run_allocation_solver

__all__ = ["AllocationInput", "AllocationOutput", "run_allocation_solver"]
