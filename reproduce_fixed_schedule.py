
import json
import logging
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

# Add src to path - ensure this points to the project root
project_root = str(Path(__file__).parent.absolute())
if project_root not in sys.path:
    sys.path.append(project_root)

# Try imports
try:
    from ortools.sat.python import cp_model
    from src.constraints.base import ConstraintMetadata
    from src.constraints.context import ConstraintContext
    from src.constraints.cross_system.fixed_schedule_lock import build_fixed_schedule_lock_constraint
    from src.models.variables import (
        LabCourseRequirement,
        LabVariableBlock,
        TheoryVariableBlock,
        VariableCreationResult,
        GroupTimeslotRequirement
    )
    from src.data.schemas import ExtendedDataContainer, LabSessionDetail
except ImportError as e:
    print(f"Import Error: {e}")
    sys.exit(1)

def _build_context() -> ConstraintContext:
    model = cp_model.CpModel()
    
    # Create variables for a conflict
    # Teacher T1, Course C1, Day monday, Session L1, Room R1
    # We will lock T1 to use R1 in L1.
    
    # 1. Setup Lab Block for T1 (Locked Owner)
    lab_assignment_var = model.NewBoolVar("T1_C1_monday_L1_R1")
    lab_assignment_var2 = model.NewBoolVar("T1_C1_monday_L1_R2")
    
    # 2. Setup Lab Block for T2 (Intruder) - wants R1
    lab_assignment_var3 = model.NewBoolVar("T2_C2_monday_L1_R1")
    
    # 3. Setup Lab Block for T1 (Intruder Conflict) - wants R2
    # This simulates T1 trying to double book
    lab_assignment_var4 = model.NewBoolVar("T1_C3_monday_L1_R3")

    assignments = {
        "T1": {
            "C1": {
                0: {
                    "L1": {
                        "R1": lab_assignment_var,
                        "R2": lab_assignment_var2
                    }
                }
            },
            "C3": {
                 0: {
                    "L1": {
                        "R3": lab_assignment_var4
                    }
                 }
            }
        },
        "T2": {
            "C2": {
                0: {
                    "L1": {
                        "R1": lab_assignment_var3
                    }
                }
            }
        }
    }
    
    lab_requirements = {
        "C1": LabCourseRequirement(
            course_instance_id="C1",
            course_code="CODE1",
            teacher_id="T1",
            group_id="G1",
            department="Dept",
            semester=1,
            practical_hours=2,
            required_sessions=1,
            student_count=10,
            preferred_room_type=None,
            required_room_type=None,
        ),
         "C2": LabCourseRequirement(
            course_instance_id="C2",
            course_code="CODE2",
            teacher_id="T2",
            group_id="G2",
            department="Dept",
            semester=1,
            practical_hours=2,
            required_sessions=1,
            student_count=10,
            preferred_room_type=None,
            required_room_type=None,
        ),
        "C3": LabCourseRequirement(
            course_instance_id="C3",
            course_code="CODE3",
            teacher_id="T1",
            group_id="G3",
            department="Dept",
            semester=1,
            practical_hours=2,
            required_sessions=1,
            student_count=10,
            preferred_room_type=None,
            required_room_type=None,
        )
    }

    lab_block = LabVariableBlock(
        assignments=assignments,
        requirements=lab_requirements,
        teacher_courses={"T1": ("C1","C3"), "T2": ("C2",)},
        day_patterns={"C1": ("monday",), "C2": ("monday",), "C3": ("monday",)},
        lab_session_names=("L1",),
        room_ids=("R1", "R2", "R3"),
        instance_group_lookup={"C1": "G1", "C2": "G2", "C3": "G3"},
    )
    
    # Dummy theory block
    theory_block = SimpleNamespace(
        assignments={},
        room_assignments={},
        course_day_patterns={},
    )
    
    # Data
    time_ns = SimpleNamespace(
        lab_sessions={"L1": LabSessionDetail(name="L1", slots=(0, 1), time_range="8-10")},
        working_days=("monday",),
    )
    raw = SimpleNamespace(
        time=time_ns,
        departments=SimpleNamespace(day_patterns={}),
    )
    data = ExtendedDataContainer(raw=raw, preprocessing=SimpleNamespace())

    return ConstraintContext(
        model=model,
        config=SimpleNamespace(),
        data=data,
        variables=VariableCreationResult(lab=lab_block, theory=theory_block, metadata={}),
        logger=logging.getLogger("test_repro"),
    )

def main():
    logging.basicConfig(level=logging.INFO)
    try:
        # Create the snapshot file
        snapshot_data = {
            "lab_assignments": [
                {
                    "teacher_id": "T1",
                    "course_instance_id": "C1",
                    "day": "monday",
                    "session_name": "L1",
                    "room_id": "R1" # We lock R1 for T1
                }
            ]
        }
        snapshot_path = Path("repro_snapshot.json")
        snapshot_path.write_text(json.dumps(snapshot_data))
        
        context = _build_context()
        
        # Create constraint
        metadata = ConstraintMetadata(
            id="fixed_lock", name="Fixed Lock", category="test", priority=1, description=""
        )
        constraint = build_fixed_schedule_lock_constraint(
            metadata,
            params={
                "snapshot_path": str(snapshot_path),
                "lock_assignments": True,
                "block_rooms": True,
                "block_teachers": True
            }
        )
        
        print("Applying constraint...")
        result = constraint.apply(context)
        print(f"Status: {result.status}")
        print(f"Details: {result.details}")
        
    except Exception:
        traceback.print_exc()
    
    finally:
        # Clean up
        path = Path("repro_snapshot.json")
        if path.exists():
            path.unlink()

if __name__ == "__main__":
    main()
