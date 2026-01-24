
import sys
import os
import logging
from unittest.mock import MagicMock, patch
from pathlib import Path

# Mock ortools BEFORE importing the module that uses it
sys.modules["ortools"] = MagicMock()
sys.modules["ortools.sat"] = MagicMock()
sys.modules["ortools.sat.python"] = MagicMock()
sys.modules["ortools.sat.python.cp_model"] = MagicMock()

# Add project root to path
sys.path.append(r"d:\timetable-scheduler")

# Now import
from src.constraints.cross_system.dept_slot_blocking import build_dept_slot_blocking_constraint

# Mock logging to capture output
logging.basicConfig(level=logging.INFO)

def verify_constraint():
    print("Verifying DeptSlotBlockingConstraint...")
    
    # Mock settings params
    params = {
        "lab_csv_path": "data/sem2026/1st year/lab.csv",
        "lock_assignments": True,
        "block_dept_slots": True,
        "block_dept_slots_course_codes": ["CS23231", "CB23231"]
    }
    
    # Mock Metadata
    metadata = MagicMock()
    metadata.name = "dept_slot_blocking"
    metadata.category = "cross_system"
    metadata.priority = 10
    
    constraint = build_dept_slot_blocking_constraint(metadata, params=params)
    
    # Mock Context
    context = MagicMock()
    context.model = MagicMock()
    context.variables = MagicMock()
    context.variables.lab.assignments = {} 
    context.variables.theory.assignments = {}
    context.extra = {}
    
    # Run apply
    result = constraint.apply(context)
    
    print(f"Status: {result.status}")
    print(f"Details: {result.details}")
    
    # specific checks
    logs = result.details
    
    # Check 1: Missing vars should be 0 because we ignored CS23231/CB23231 in the locking loop
    if logs.get("missing_lab_vars") == 0:
        print("SUCCESS: No missing lab variables reported for ignored courses.")
    else:
        print(f"FAILURE: Reported {logs.get('missing_lab_vars')} missing lab variables.")

    # Check 2: Blocking logic should have run (keys in stats)
    if "blocked_dept_lab_vars" in logs:
         print(f"SUCCESS: Blocking logic ran (blocked_dept_lab_vars present).")
    
if __name__ == "__main__":
    verify_constraint()
