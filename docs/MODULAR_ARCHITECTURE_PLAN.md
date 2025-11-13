# Modular Scheduler Architecture Plan

## Overview

Transform the monolithic `combined_scheduler.py` (9778 lines) into a clean, modular architecture with:
- **Separation of concerns** across specialized modules
- **Reusable constraint builders** in the `constraints/` folder
- **Clear data flow** from data loader → model builder → constraints → solver
- **Easy testing** through isolated components

---

## 1. Current Structure Analysis

### Before (Monolithic - ❌)
```
old/src/
└── combined_scheduler.py (9778 lines)
    ├── Data loading logic
    ├── Variable creation
    ├── Constraint definitions (30+ constraints)
    ├── Solving logic
    ├── Extraction logic
    └── Reporting logic
```

### After (Modular - ✅)
```
src/
├── data_loader.py (✅ DONE - 478 lines)
├── models/
│   ├── __init__.py
│   ├── variables.py (→ Variable creators)
│   └── constraints_registry.py (→ Metadata about constraints)
├── constraints/
│   ├── __init__.py
│   ├── registry.py (✅ Done - metadata)
│   ├── base.py (→ Base constraint class)
│   ├── lab/
│   │   ├── __init__.py
│   │   ├── requirements.py
│   │   ├── room_allocation.py
│   │   ├── capacity_analysis.py
│   │   ├── shift_based.py
│   │   └── core_lab.py
│   ├── theory/
│   │   ├── __init__.py
│   │   ├── group_scheduling.py
│   │   ├── room_capacity.py
│   │   ├── teacher_presence.py
│   │   ├── daily_limits.py
│   │   └── consecutive_slots.py
│   ├── cross_system/
│   │   ├── __init__.py
│   │   ├── teacher_clash.py
│   │   ├── department_conflicts.py
│   │   └── time_mapping.py
│   └── utility/
│       ├── __init__.py
│       ├── lunch_break.py
│       ├── 5pm_constraints.py
│       └── teacher_preferences.py
├── model_builder.py (→ Orchestrates everything)
├── solver.py (→ Solves the model)
├── extractor.py (→ Extracts results)
├── validator.py (→ Validates output)
├── metrics.py (→ Computes statistics)
├── orchestrator.py (→ High-level API)
└── cli.py (→ Command-line interface)

config/
├── constraint.yaml (→ Constraint configuration)
└── solver_params.yaml (→ Solver parameters)

tests/
├── unit/
│   ├── test_variables.py
│   ├── test_constraints_lab.py
│   ├── test_constraints_theory.py
│   └── test_constraints_cross.py
└── integration/
    └── test_scheduler_pipeline.py
```

---

## 2. Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. DATA LAYER                                                   │
├─────────────────────────────────────────────────────────────────┤
│ CSV Files (courses, rooms) → data_loader.py → Cleaned Data      │
│                                 ↓                                 │
│                    Returns: DataContainer                         │
│                    {                                              │
│                      courses: [],                                 │
│                      teachers: [],                                │
│                      departments: [],                             │
│                      rooms: {},                                   │
│                      time_slots: {},                              │
│                      days: [],                                    │
│                      config: {}                                   │
│                    }                                              │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ 2. PREPROCESSING LAYER                                          │
├─────────────────────────────────────────────────────────────────┤
│ DataContainer → Intermediate Processing → Extended Data          │
│                 ├── Group Creation (dept/semester)               │
│                 ├── Group Requirements Calculation               │
│                 ├── Instance-to-Group Mapping                    │
│                 ├── Lab Requirements Extraction                  │
│                 └── Core Lab Mapping                             │
│                                 ↓                                 │
│                    Returns: ExtendedDataContainer                │
│                    {                                              │
│                      (all from DataContainer)                    │
│                      groups: {},                                 │
│                      group_requirements: {},                     │
│                      instance_group_mapping: {},                 │
│                      lab_requirements: {},                       │
│                      core_lab_mapping: {}                        │
│                    }                                              │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ 3. MODEL LAYER                                                  │
├─────────────────────────────────────────────────────────────────┤
│ ExtendedDataContainer → model_builder.py → CP-SAT Model          │
│                         ├── VariableCreator                      │
│                         │   ├── create_lab_variables()           │
│                         │   └── create_theory_variables()        │
│                         │                                         │
│                         └── ConstraintBuilder                    │
│                             ├── add_lab_constraints()            │
│                             ├── add_theory_constraints()         │
│                             └── add_cross_constraints()          │
│                                 ↓                                 │
│                    Returns: ConstraintModel                      │
│                    {                                              │
│                      cp_model: CpModel,                           │
│                      variables: {                                │
│                        lab_vars: {},                              │
│                        theory_vars: {}                            │
│                      },                                           │
│                      constraint_info: {                          │
│                        applied: [],                               │
│                        metadata: {}                               │
│                      }                                            │
│                    }                                              │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ 4. SOLVER LAYER                                                 │
├─────────────────────────────────────────────────────────────────┤
│ ConstraintModel → solver.py → Solution                           │
│                   ├── Configure solver params                    │
│                   ├── Execute CP-SAT solver                      │
│                   ├── Handle infeasibility                       │
│                   └── Return solution status                     │
│                                 ↓                                 │
│                    Returns: SolverResult                         │
│                    {                                              │
│                      status: 'OPTIMAL' | 'FEASIBLE' | 'INFEASIBLE',
│                      solver: CpSolver,                            │
│                      statistics: {}                               │
│                    }                                              │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ 5. EXTRACTION LAYER                                             │
├─────────────────────────────────────────────────────────────────┤
│ SolverResult → extractor.py → Human-Readable Schedules           │
│                ├── Extract lab assignments                       │
│                ├── Extract theory assignments                    │
│                ├── Distribute theory within groups               │
│                ├── Assign teachers to instances                  │
│                └── Assign rooms to sessions                      │
│                                 ↓                                 │
│                    Returns: Schedule                             │
│                    {                                              │
│                      lab_schedule: [],                            │
│                      theory_schedule: [],                         │
│                      combined_schedule: []                        │
│                    }                                              │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ 6. VALIDATION & REPORTING LAYER                                 │
├─────────────────────────────────────────────────────────────────┤
│ Schedule → validator.py → Validated Results                      │
│ Schedule → metrics.py → Performance Statistics                   │
│ Schedule → Report Generators → HTML/JSON/CSV Exports             │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Modular Code Structure - Detailed Breakdown

### Level 1: Core Modules (High-Level Interface)

#### File: `src/data_loader.py` (✅ DONE)
**Purpose**: Load and validate all input data
**Status**: Complete with 24 utility classes integrated
**Exports**:
```python
class DataLoader:
    def load_all_data(self) -> DataContainer
    def validate_data() -> bool
    def get_data() -> DataContainer
```

#### File: `src/models/variables.py` (→ CREATE NEXT)
**Purpose**: Create CP-SAT decision variables
**Complexity**: Medium
**Key Classes**:
```python
class VariableCreator:
    def __init__(self, data: ExtendedDataContainer)
    def create_lab_variables(model) → dict
    def create_theory_variables(model) → dict
    def create_group_timeslot_variables(model) → dict
```

#### File: `src/model_builder.py` (→ CREATE)
**Purpose**: Orchestrate model setup and constraint application
**Complexity**: High
**Key Classes**:
```python
class ModelBuilder:
    def __init__(self, data: ExtendedDataContainer, config: dict)
    def build_model() → ConstraintModel
    def apply_all_constraints(model, variables) → model
    def setup_objectives(model, variables) → model
```

#### File: `src/solver.py` (→ CREATE)
**Purpose**: Execute CP-SAT solver
**Complexity**: Low-Medium
**Key Classes**:
```python
class Solver:
    def __init__(self, config: dict)
    def solve(model, variables) → SolverResult
    def get_statistics() → dict
```

#### File: `src/extractor.py` (→ CREATE)
**Purpose**: Extract and format solution
**Complexity**: High
**Key Classes**:
```python
class ScheduleExtractor:
    def __init__(self, data: DataContainer, solver_result: SolverResult)
    def extract_lab_schedule() → list
    def extract_theory_schedule() → list
    def distribute_theory_within_groups() → list
    def combine_schedules() → list
```

#### File: `src/orchestrator.py` (→ UPDATE)
**Purpose**: High-level API tying everything together
**Complexity**: Medium
**Key Classes**:
```python
class Scheduler:
    def __init__(self, config_path: str)
    def run() → Schedule  # Main entry point
    def get_schedule() → Schedule
    def save_schedules(output_dir) → bool
```

---

### Level 2: Constraint Modules (Modular Constraints)

#### Base Constraint Class: `src/constraints/base.py`
**Purpose**: Provide base class for all constraints
**Key Methods**:
```python
class Constraint:
    """Base class for all constraints."""
    def __init__(self, name: str, data: ExtendedDataContainer)
        self.name = name
        self.data = data
    
    def apply(self, model, variables) → model:
        """Apply this constraint to the model."""
        raise NotImplementedError()
    
    def get_metadata() → dict:
        """Return constraint metadata."""
        raise NotImplementedError()
```

---

### Lab Constraints: `src/constraints/lab/`

#### `src/constraints/lab/__init__.py`
```python
from .requirements import CourseLabRequirementsConstraint
from .room_allocation import LabRoomAllocationConstraint
from .capacity_analysis import LabCapacityAnalysisConstraint
from .shift_based import LabShiftBasedConstraint
from .core_lab import CoreLabRestrictionConstraint, CoreLabMappingConstraint

__all__ = [
    'CourseLabRequirementsConstraint',
    'LabRoomAllocationConstraint',
    'LabCapacityAnalysisConstraint',
    'LabShiftBasedConstraint',
    'CoreLabRestrictionConstraint',
    'CoreLabMappingConstraint',
]
```

#### `src/constraints/lab/requirements.py` (→ CREATE)
**Purpose**: Ensure all lab sessions are scheduled
**Source lines from combined_scheduler.py**: 2680-2956
**Key method**:
```python
class CourseLabRequirementsConstraint(Constraint):
    """Ensure every lab course gets required number of sessions."""
    
    def apply(self, model, variables) → model:
        """
        For each course instance:
        - Sum of (day, session, room) assignments ≥ lab_sessions_needed
        """
```

#### `src/constraints/lab/room_allocation.py` (→ CREATE)
**Purpose**: Single room assignment per session, block preferences
**Source lines from combined_scheduler.py**: 3074-3317
**Key methods**:
```python
class LabRoomAllocationConstraint(Constraint):
    """Ensure proper lab room allocation and single assignment."""
    
    def apply(self, model, variables) → model:
        """
        - Each session assigned to exactly one room
        - Prefer departmental blocks
        - Account for TIFAC rooms
        """
```

#### `src/constraints/lab/capacity_analysis.py` (→ CREATE)
**Purpose**: Room capacity matching for 35-cap and 140-cap strategies
**Source lines from combined_scheduler.py**: 3320-3422
**Key methods**:
```python
class LabCapacityAnalysisConstraint(Constraint):
    """Handle 35-capacity and 140-capacity lab room constraints."""
    
    def apply(self, model, variables) → model:
        """
        - 35-cap strategy: one group per room per session
        - 140-cap strategy: co-schedule compatible groups
        """
```

#### `src/constraints/lab/shift_based.py` (→ CREATE)
**Purpose**: Enforce department shift patterns for labs
**Source lines from combined_scheduler.py**: 8765-8930
**Key methods**:
```python
class LabShiftBasedConstraint(Constraint):
    """Enforce shift-based scheduling for departments."""
    
    def apply(self, model, variables) → model:
        """
        - Shift 1: 8AM-3:30PM (slots 0-6, sessions L1-L4)
        - Shift 2: 10AM-5:30PM (slots 2-8, sessions L2-L5)
        - Pattern: 3 days Shift1, 2 days Shift2
        """
```

#### `src/constraints/lab/core_lab.py` (→ CREATE)
**Purpose**: Core lab restrictions and mapping
**Source lines from combined_scheduler.py**: 2981-3071, 3540-3657
**Key methods**:
```python
class CoreLabRestrictionConstraint(Constraint):
    """Core labs restricted to core groups only."""
    def apply(self, model, variables) → model:
        """Only core-group students in core lab courses."""

class CoreLabMappingConstraint(Constraint):
    """Map core groups to core lab courses."""
    def apply(self, model, variables) → model:
        """Each core group assigned to compatible core lab."""
```

---

### Theory Constraints: `src/constraints/theory/`

#### `src/constraints/theory/__init__.py`
```python
from .group_scheduling import GroupBasedSchedulingConstraint
from .room_capacity import ProperTheoryRoomCapacityConstraint
from .teacher_presence import TeacherDailyPresenceConstraint
from .daily_limits import DailyTheorySlotLimitConstraint
from .consecutive_slots import NoThreeConsecutiveSlotsConstraint

__all__ = [
    'GroupBasedSchedulingConstraint',
    'ProperTheoryRoomCapacityConstraint',
    'TeacherDailyPresenceConstraint',
    'DailyTheorySlotLimitConstraint',
    'NoThreeConsecutiveSlotsConstraint',
]
```

#### `src/constraints/theory/group_scheduling.py` (→ CREATE)
**Purpose**: Theory sessions distributed within groups
**Source lines from combined_scheduler.py**: 3427-3537
**Key method**:
```python
class GroupBasedSchedulingConstraint(Constraint):
    """Distribute theory sessions within allocated group timeslots."""
    
    def apply(self, model, variables) → model:
        """
        - Each course instance in group assigned once per group timeslot
        - Teacher assignment within group instances
        - No duplicate course instances on same day
        """
```

#### `src/constraints/theory/room_capacity.py` (→ CREATE)
**Purpose**: Match theory rooms to group capacity
**Source lines from combined_scheduler.py**: 4194-4277, 4462-4728
**Key methods**:
```python
class ProperTheoryRoomCapacityConstraint(Constraint):
    """Assign theory rooms based on group capacity."""
    
    def apply(self, model, variables) → model:
        """
        - 140+ capacity: use large lecture halls
        - <140 capacity: use appropriate classrooms
        - Priority: preferred departments' blocks
        """

class LargeCapacityTheoryConstraint(Constraint):
    """Handle 140+ capacity groups specially."""
    def apply(self, model, variables) → model:
        """Assign 140+ groups to large lecture halls."""
```

#### `src/constraints/theory/teacher_presence.py` (→ CREATE)
**Purpose**: Teacher availability and presence rules
**Source lines from combined_scheduler.py**: 4731-4846
**Key method**:
```python
class TeacherDailyPresenceConstraint(Constraint):
    """Enforce teacher availability for assigned slots."""
    
    def apply(self, model, variables) → model:
        """
        - Teacher present on assigned days
        - No back-to-back excessive days
        - Shift compatibility
        """
```

#### `src/constraints/theory/daily_limits.py` (→ CREATE)
**Purpose**: Limit daily theory slot assignments
**Source lines from combined_scheduler.py**: 4849-4951
**Key method**:
```python
class DailyTheorySlotLimitConstraint(Constraint):
    """Limit number of slots per day per group."""
    
    def apply(self, model, variables) → model:
        """
        - Max 3 consecutive slots per day
        - Max 11 slots per day total
        - Prefer earlier slots (objective)
        """
```

#### `src/constraints/theory/consecutive_slots.py` (→ CREATE)
**Purpose**: Avoid excessive consecutive slots
**Source lines from combined_scheduler.py**: 4087-4191
**Key method**:
```python
class NoThreeConsecutiveSlotsConstraint(Constraint):
    """Prevent more than 3 consecutive theory slots."""
    
    def apply(self, model, variables) → model:
        """
        - At most 3 consecutive slots in theory schedule
        - Breaks at slot boundaries
        """
```

---

### Cross-System Constraints: `src/constraints/cross_system/`

#### `src/constraints/cross_system/__init__.py`
```python
from .teacher_clash import UnifiedTeacherClashConstraint
from .department_conflicts import DepartmentSemesterConflictConstraint
from .time_mapping import TimeSystemMappingConstraint

__all__ = [
    'UnifiedTeacherClashConstraint',
    'DepartmentSemesterConflictConstraint',
    'TimeSystemMappingConstraint',
]
```

#### `src/constraints/cross_system/teacher_clash.py` (→ CREATE)
**Purpose**: Prevent teacher double-booking across lab and theory
**Source lines from combined_scheduler.py**: 5220-5418
**Key method**:
```python
class UnifiedTeacherClashConstraint(Constraint):
    """Prevent teacher from teaching lab and theory same time."""
    
    def apply(self, model, variables) → model:
        """
        - Lab session time slot → theory time slots mapping
        - Cross-check all teacher assignments
        - No overlap in mapped times
        """
```

#### `src/constraints/cross_system/department_conflicts.py` (→ CREATE)
**Purpose**: Prevent department-semester double-booking
**Source lines from combined_scheduler.py**: 5098-5217
**Key method**:
```python
class DepartmentSemesterConflictConstraint(Constraint):
    """Prevent dept-semester conflicts across systems."""
    
    def apply(self, model, variables) → model:
        """
        - Same dept-semester group can't have concurrent sessions
        - Check lab and theory across departments
        """
```

#### `src/constraints/cross_system/time_mapping.py` (→ CREATE)
**Purpose**: Map lab and theory time slots for overlap detection
**Source lines from combined_scheduler.py**: 1544-1610
**Key method**:
```python
class TimeSystemMappingConstraint(Constraint):
    """Map lab times to theory times for conflict detection."""
    
    def apply(self, model, variables) → model:
        """
        - Lab session hours → theory slot mapping
        - Used by clash detection
        """
```

---

### Utility Constraints: `src/constraints/utility/`

#### `src/constraints/utility/__init__.py`
```python
from .lunch_break import LunchBreakConstraint, FlexibleLunchConstraint
from .teacher_preferences import TeacherDayPreferenceConstraint
from .five_pm import FivePmConstraint

__all__ = [
    'LunchBreakConstraint',
    'FlexibleLunchConstraint',
    'TeacherDayPreferenceConstraint',
    'FivePmConstraint',
]
```

#### `src/constraints/utility/lunch_break.py` (→ CREATE)
**Purpose**: Enforce lunch break slots
**Source lines from combined_scheduler.py**: 8284-8521
**Key methods**:
```python
class LunchBreakConstraint(Constraint):
    """Fix lunch break slots for departments."""
    def apply(self, model, variables) → model:
        """11:00-1:30 lunch break enforcement."""

class FlexibleLunchConstraint(Constraint):
    """Allow flexible lunch for some departments."""
    def apply(self, model, variables) → model:
        """Model decides lunch slot (3, 4, or 5)."""
```

#### `src/constraints/utility/teacher_preferences.py` (→ CREATE)
**Purpose**: Enforce teacher day preferences from pop.csv
**Source lines from combined_scheduler.py**: 4954-5078
**Key method**:
```python
class TeacherDayPreferenceConstraint(Constraint):
    """Honor teacher day preferences when possible."""
    
    def apply(self, model, variables) → model:
        """
        - Load preferences from pop.csv
        - Apply as soft constraints (objectives)
        """
```

#### `src/constraints/utility/five_pm.py` (→ CREATE)
**Purpose**: Enforce 5:30 PM cutoff for some departments
**Source lines from combined_scheduler.py**: 5630-5785
**Key method**:
```python
class FivePmConstraint(Constraint):
    """Enforce 5:30 PM end time for specified departments."""
    
    def apply(self, model, variables) → model:
        """
        - Hard constraint: some departments end by 5:30 PM
        - Soft constraint: others as objectives
        """
```

---

### Constraint Registry: `src/constraints/registry.py` (✅ PARTIALLY DONE)

**Purpose**: Metadata about all constraints
**Key contents**:
```python
CONSTRAINT_REGISTRY = {
    'lab': {
        'requirements': {
            'class': CourseLabRequirementsConstraint,
            'priority': 10,
            'type': 'hard',
            'description': 'Ensure all lab sessions are scheduled',
        },
        # ... more constraints
    },
    'theory': {
        # ... theory constraints
    },
    'cross_system': {
        # ... cross constraints
    },
    'utility': {
        # ... utility constraints
    }
}
```

---

## 4. Step-by-Step Implementation Plan

### Phase 1: Preprocessing & Variable Creation (Week 1)

#### Step 1.1: Create `src/models/variables.py` (→ NEXT)
**Time**: 2-3 hours
**Dependencies**: data_loader.py, utils/*
**Tasks**:
- [ ] Create VariableCreator class
- [ ] Implement create_lab_variables()
- [ ] Implement create_theory_variables()
- [ ] Implement create_group_timeslot_variables()
- [ ] Add unit tests

**Key code pattern**:
```python
class VariableCreator:
    def __init__(self, data: ExtendedDataContainer):
        self.data = data
        self.logger = logging.getLogger(__name__)
    
    def create_lab_variables(self, model):
        """
        lab_assignments[teacher][course][day_idx][session][room] = BoolVar
        """
        lab_assignments = {}
        for teacher_id, lab_courses in self.data.lab_requirements.items():
            lab_assignments[teacher_id] = {}
            for course in lab_courses:
                # Create variables...
        return lab_assignments
    
    def create_theory_variables(self, model):
        """
        group_timeslot_vars[group_name][day_idx][slot_idx] = BoolVar
        """
        return self.create_group_timeslot_variables(model)
```

#### Step 1.2: Create intermediate data processing in `src/data_loader.py` (→ EXTEND)
**Time**: 3-4 hours
**Dependencies**: data_loader.py existing code
**Tasks**:
- [ ] Add course_groups creation (by dept/semester)
- [ ] Add group_requirements calculation
- [ ] Add instance_group_mapping building
- [ ] Add lab_requirements extraction
- [ ] Add core_lab_mapping loading
- [ ] Return ExtendedDataContainer

**Expected output**:
```python
extended_data = {
    # From basic data_loader
    'courses': [...],
    'teachers': [...],
    'departments': [...],
    'rooms': {...},
    
    # New from preprocessing
    'groups': {...},
    'group_requirements': {...},
    'instance_group_mapping': {...},
    'lab_requirements': {...},
    'core_lab_mapping': {...},
}
```

---

### Phase 2: Constraint Infrastructure (Week 1-2)

#### Step 2.1: Create `src/constraints/base.py`
**Time**: 1 hour
**Code template**:
```python
from abc import ABC, abstractmethod
from typing import Dict, Any
import logging

class Constraint(ABC):
    """Base class for all constraints."""
    
    def __init__(self, name: str, data: Dict[str, Any]):
        self.name = name
        self.data = data
        self.logger = logging.getLogger(f"constraint.{name}")
    
    @abstractmethod
    def apply(self, model, variables) -> None:
        """Apply constraint to the model."""
        pass
    
    def get_metadata(self) -> Dict[str, Any]:
        """Return metadata about this constraint."""
        return {
            'name': self.name,
            'type': 'unknown',
            'priority': 5,
            'is_hard': True,
        }
```

#### Step 2.2: Update `src/constraints/__init__.py`
**Time**: 30 minutes
**Code**:
```python
from .base import Constraint

# Import all constraint categories
from .lab import *
from .theory import *
from .cross_system import *
from .utility import *

__all__ = [
    'Constraint',
    # Lab constraints
    'CourseLabRequirementsConstraint',
    'LabRoomAllocationConstraint',
    # ... etc
]
```

---

### Phase 3: Lab Constraints (Week 2)

#### Step 3.1: Create `src/constraints/lab/requirements.py`
**Time**: 2-3 hours
**Source**: combined_scheduler.py lines 2680-2956
**Algorithm**: For each course instance, sum assignments ≥ sessions_needed
```python
class CourseLabRequirementsConstraint(Constraint):
    def apply(self, model, variables):
        for teacher_id in variables['lab_vars']:
            for course_id, course_vars in variables['lab_vars'][teacher_id].items():
                assignments = []
                for day_idx in course_vars:
                    for session in course_vars[day_idx]:
                        for room in course_vars[day_idx][session]:
                            assignments.append(course_vars[day_idx][session][room])
                
                needed = self.data['lab_requirements'][teacher_id][course_id]['sessions_needed']
                model.Add(sum(assignments) >= needed)
                self.logger.info(f"Course {course_id}: ≥{needed} sessions")
```

#### Step 3.2: Create `src/constraints/lab/room_allocation.py`
**Time**: 2-3 hours
**Source**: combined_scheduler.py lines 3074-3317
**Algorithm**: Each session → exactly one room; prefer blocks

#### Step 3.3: Create `src/constraints/lab/capacity_analysis.py`
**Time**: 2-3 hours
**Source**: combined_scheduler.py lines 3320-3422
**Algorithm**: 35-cap vs 140-cap strategies

#### Step 3.4: Create `src/constraints/lab/shift_based.py`
**Time**: 2-3 hours
**Source**: combined_scheduler.py lines 8765-8930
**Algorithm**: Enforce shift patterns per department

#### Step 3.5: Create `src/constraints/lab/core_lab.py`
**Time**: 2-3 hours
**Source**: combined_scheduler.py lines 2981-3071, 3540-3657
**Algorithm**: Core labs → core groups; core groups → core labs

---

### Phase 4: Theory Constraints (Week 2-3)

#### Step 4.1: Create `src/constraints/theory/group_scheduling.py`
**Time**: 2-3 hours
**Source**: combined_scheduler.py lines 3427-3537
**Algorithm**: Distribute instances within group timeslots

#### Step 4.2: Create `src/constraints/theory/room_capacity.py`
**Time**: 2-3 hours
**Source**: combined_scheduler.py lines 4194-4728
**Algorithm**: Match rooms to group capacity

#### Step 4.3: Create `src/constraints/theory/teacher_presence.py`
**Time**: 1-2 hours
**Source**: combined_scheduler.py lines 4731-4846
**Algorithm**: Teacher availability enforcement

#### Step 4.4: Create `src/constraints/theory/daily_limits.py`
**Time**: 1-2 hours
**Source**: combined_scheduler.py lines 4849-4951
**Algorithm**: Limit slots per day

#### Step 4.5: Create `src/constraints/theory/consecutive_slots.py`
**Time**: 1 hour
**Source**: combined_scheduler.py lines 4087-4191
**Algorithm**: No 3+ consecutive slots

---

### Phase 5: Cross-System Constraints (Week 3)

#### Step 5.1: Create `src/constraints/cross_system/teacher_clash.py`
**Time**: 2-3 hours
**Source**: combined_scheduler.py lines 5220-5418
**Algorithm**: Teacher can't have lab+theory same time

#### Step 5.2: Create `src/constraints/cross_system/department_conflicts.py`
**Time**: 1-2 hours
**Source**: combined_scheduler.py lines 5098-5217
**Algorithm**: Dept-semester can't have conflicts

#### Step 5.3: Create `src/constraints/cross_system/time_mapping.py`
**Time**: 1 hour
**Source**: combined_scheduler.py lines 1544-1610
**Algorithm**: Map lab times to theory times

---

### Phase 6: Utility Constraints (Week 3)

#### Step 6.1: Create `src/constraints/utility/lunch_break.py`
**Time**: 1-2 hours
**Source**: combined_scheduler.py lines 8284-8521
**Algorithm**: Fixed & flexible lunch enforcement

#### Step 6.2: Create `src/constraints/utility/teacher_preferences.py`
**Time**: 1 hour
**Source**: combined_scheduler.py lines 4954-5078
**Algorithm**: Load from pop.csv, apply as soft constraints

#### Step 6.3: Create `src/constraints/utility/five_pm.py`
**Time**: 1 hour
**Source**: combined_scheduler.py lines 5630-5785
**Algorithm**: Hard/soft 5:30 PM limits

---

### Phase 7: Core Modules (Week 4)

#### Step 7.1: Create `src/model_builder.py`
**Time**: 3-4 hours
**Key logic**:
```python
class ModelBuilder:
    def __init__(self, data, config):
        self.data = data
        self.config = config
        self.model = cp_model.CpModel()
        self.variables = {}
        self.constraints = []
    
    def build_model(self):
        """Orchestrate full model creation."""
        # 1. Create variables
        var_creator = VariableCreator(self.data)
        self.variables['lab'] = var_creator.create_lab_variables(self.model)
        self.variables['theory'] = var_creator.create_theory_variables(self.model)
        
        # 2. Apply constraints in order
        self._apply_all_constraints()
        
        # 3. Set objectives
        self._setup_objectives()
        
        return {
            'model': self.model,
            'variables': self.variables,
            'constraint_info': self._get_constraint_info()
        }
    
    def _apply_all_constraints(self):
        """Apply all constraints in priority order."""
        # Load constraint registry
        for category in ['lab', 'theory', 'cross_system', 'utility']:
            for constraint_name, constraint_config in CONSTRAINT_REGISTRY[category].items():
                constraint_class = constraint_config['class']
                constraint = constraint_class(constraint_name, self.data)
                constraint.apply(self.model, self.variables)
                self.constraints.append(constraint)
                self.logger.info(f"Applied {constraint_name}")
```

#### Step 7.2: Create `src/solver.py`
**Time**: 2 hours
**Key logic**:
```python
class Solver:
    def __init__(self, config):
        self.config = config
        self.solver = cp_model.CpSolver()
        self._configure_solver()
    
    def solve(self, model):
        """Execute solver."""
        status = self.solver.Solve(model)
        
        return {
            'status': str(status),
            'solver': self.solver,
            'optimal': status == cp_model.OPTIMAL,
            'statistics': self._get_stats()
        }
    
    def _configure_solver(self):
        """Set solver parameters from config."""
        self.solver.parameters.log_search_progress = self.config.get('log', True)
        self.solver.parameters.max_time_in_seconds = self.config.get('max_time', 600)
```

#### Step 7.3: Create `src/extractor.py`
**Time**: 3-4 hours
**Key logic**:
```python
class ScheduleExtractor:
    def extract_schedules(self, solver, variables, data):
        """Extract lab and theory schedules."""
        lab_schedule = self._extract_lab(solver, variables)
        theory_schedule = self._extract_theory(solver, variables, data)
        
        return {
            'lab': lab_schedule,
            'theory': theory_schedule,
            'combined': self._combine(lab_schedule, theory_schedule)
        }
```

#### Step 7.4: Create `src/validator.py`
**Time**: 2-3 hours
**Purpose**: Validate output schedules
```python
class ScheduleValidator:
    def validate(self, schedule):
        """Check all constraints satisfied."""
        # Check room conflicts
        # Check teacher conflicts
        # Check capacity constraints
        # Return validation report
```

#### Step 7.5: Create `src/metrics.py`
**Time**: 2 hours
**Purpose**: Compute schedule statistics
```python
class ScheduleMetrics:
    def compute(self, schedule):
        """Compute utilization, balance, etc."""
```

#### Step 7.6: Update `src/orchestrator.py`
**Time**: 2 hours
**Key logic**:
```python
class Scheduler:
    def run(self):
        """Main entry point."""
        # 1. Load data
        loader = DataLoader()
        data = loader.load_all_data()
        
        # 2. Build model
        builder = ModelBuilder(data, self.config)
        constraint_model = builder.build_model()
        
        # 3. Solve
        solver = Solver(self.config)
        result = solver.solve(constraint_model['model'])
        
        # 4. Extract
        extractor = ScheduleExtractor()
        schedules = extractor.extract_schedules(
            result['solver'], 
            constraint_model['variables'],
            data
        )
        
        # 5. Validate
        validator = ScheduleValidator()
        validation = validator.validate(schedules)
        
        # 6. Save
        self.save_schedules(schedules)
        
        return schedules
```

---

## 5. Code Dependencies Graph

```
data_loader.py
    ├── utils/data_utils.py (DataNormalizer, DataValidator, etc.)
    ├── utils/room_utils.py (RoomParser, RoomRegistry, etc.)
    ├── utils/time_utils.py (TimeParser, TimeConfiguration, etc.)
    └── utils/dept_utils.py (DepartmentParser, etc.)

models/variables.py
    ├── data_loader.py
    └── utils/time_utils.py (TimeSlotCalculator)

constraints/base.py
    └── (no dependencies)

constraints/lab/*.py
    ├── constraints/base.py
    ├── data_loader.py
    ├── utils/room_utils.py
    └── utils/time_utils.py

constraints/theory/*.py
    ├── constraints/base.py
    ├── data_loader.py
    ├── utils/time_utils.py
    └── utils/room_utils.py

constraints/cross_system/*.py
    ├── constraints/base.py
    ├── data_loader.py
    ├── utils/time_utils.py
    └── constraints/lab/*.py + constraints/theory/*.py

constraints/utility/*.py
    ├── constraints/base.py
    ├── data_loader.py
    └── utils/dept_utils.py (for preferences)

model_builder.py
    ├── models/variables.py
    ├── constraints/*.py (ALL)
    ├── data_loader.py
    ├── config/*.yaml

solver.py
    ├── config/solver_params.yaml
    └── model_builder.py (result)

extractor.py
    ├── data_loader.py
    ├── utils/time_utils.py
    ├── utils/room_utils.py
    └── solver.py (result)

validator.py
    ├── data_loader.py
    ├── extractor.py (result)

metrics.py
    ├── extractor.py (result)

orchestrator.py
    ├── data_loader.py
    ├── model_builder.py
    ├── solver.py
    ├── extractor.py
    ├── validator.py
    ├── metrics.py
    └── config/*.yaml

cli.py
    └── orchestrator.py
```

---

## 6. Configuration Files

### File: `config/constraint.yaml`
**Purpose**: Enable/disable constraints and set priorities
```yaml
constraints:
  lab:
    requirements:
      enabled: true
      priority: 10
      type: hard
    room_allocation:
      enabled: true
      priority: 9
      type: hard
  theory:
    group_scheduling:
      enabled: true
      priority: 10
      type: hard
  # ... more constraints
```

### File: `config/solver_params.yaml`
**Purpose**: Solver configuration
```yaml
solver:
  log_search_progress: true
  max_time_seconds: 600
  num_workers: 4
  log_level: INFO
```

---

## 7. Testing Strategy

### Unit Tests
```
tests/unit/
├── test_variables.py (Test variable creation)
├── test_constraints_lab.py (Test lab constraints)
├── test_constraints_theory.py (Test theory constraints)
├── test_constraints_cross.py (Test cross constraints)
└── test_solver.py (Test solver integration)
```

### Integration Tests
```
tests/integration/
├── test_scheduler_pipeline.py (End-to-end test)
└── test_data_to_schedule.py (Full workflow)
```

---

## 8. Timeline & Resource Estimate

| Phase | Duration | Effort | Key Files |
|-------|----------|--------|-----------|
| P1: Variables | 3-5 hrs | Medium | models/variables.py |
| P2: Base Infrastructure | 1.5 hrs | Low | constraints/base.py, __init__.py |
| P3: Lab Constraints | 12-15 hrs | High | constraints/lab/*.py |
| P4: Theory Constraints | 10-12 hrs | High | constraints/theory/*.py |
| P5: Cross Constraints | 4-5 hrs | Medium | constraints/cross_system/*.py |
| P6: Utility Constraints | 3-4 hrs | Medium | constraints/utility/*.py |
| P7: Core Modules | 14-16 hrs | High | model_builder.py, solver.py, extractor.py, etc. |
| **TOTAL** | **47-56 hrs** | **High** | **Complete modular stack** |

**Estimated Timeline**: 1-2 weeks with focused effort

---

## 9. Version Control Strategy

```bash
# Phase commits
git commit -m "feat: Add VariableCreator in models/variables.py"
git commit -m "feat: Create base Constraint class"
git commit -m "feat: Implement lab constraints (requirements, room_allocation, etc.)"
git commit -m "feat: Implement theory constraints (group_scheduling, room_capacity, etc.)"
git commit -m "feat: Implement cross-system constraints"
git commit -m "feat: Implement utility constraints"
git commit -m "feat: Create ModelBuilder orchestrator"
git commit -m "feat: Create Solver wrapper"
git commit -m "feat: Create ScheduleExtractor"
git commit -m "feat: Integrate all modules in orchestrator.py"
```

---

## 10. Quality Checkpoints

### ✅ Checkpoint 1: Variables Created
- [ ] VariableCreator class complete
- [ ] Unit tests passing
- [ ] Variables correctly shaped for constraints

### ✅ Checkpoint 2: Constraint Infrastructure
- [ ] Base Constraint class works
- [ ] All constraint imports working
- [ ] Registry populated

### ✅ Checkpoint 3: Lab Constraints (50% Complete)
- [ ] 5 lab constraint modules implemented
- [ ] Unit tests for each module
- [ ] Can build model with lab constraints only

### ✅ Checkpoint 4: Theory Constraints (50% Complete)
- [ ] 5 theory constraint modules implemented
- [ ] Unit tests for each module
- [ ] Can build model with theory constraints only

### ✅ Checkpoint 5: Cross-System Integration
- [ ] All cross-system constraints working
- [ ] No conflicts between lab and theory
- [ ] Model builds successfully

### ✅ Checkpoint 6: End-to-End Pipeline
- [ ] data_loader → variables → constraints → solver → extractor
- [ ] Small test case solves successfully
- [ ] Results validated

---

## 11. Dos and Don'ts

### ✅ DO
- Keep constraints focused and single-responsibility
- Use utility classes (DataNormalizer, etc.) consistently
- Log constraint application with informative messages
- Test each constraint independently
- Document constraint logic clearly
- Use type hints (Dict[str, Any], etc.)
- Follow naming: `*Constraint` class names
- Return clean metadata from constraints

### ❌ DON'T
- Mix multiple constraint types in one file
- Duplicate code across constraints
- Hard-code values; use config files
- Skip logging and error handling
- Create variables in constraints (only variables.py)
- Ignore performance considerations
- Leave constraints without tests
- Create circular dependencies

---

## 12. Next Immediate Action

**→ START WITH STEP 1.1 & 1.2:**

1. **Extend `data_loader.py`** to create intermediate data structures:
   - course_groups, group_requirements, instance_group_mapping
   - lab_requirements, core_lab_mapping

2. **Create `src/models/variables.py`** with VariableCreator class:
   - create_lab_variables()
   - create_theory_variables()
   - create_group_timeslot_variables()

3. **Create `src/constraints/base.py`** for base Constraint class

Then proceed phase by phase through the constraint implementations.

