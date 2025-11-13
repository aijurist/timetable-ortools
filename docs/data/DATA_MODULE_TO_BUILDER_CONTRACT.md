# Data Module to Model Builder Contract

## Overview: What Data Flows to the Model Builder

This document specifies the **complete data contract** between:
1. **Data Module** (data loading & preprocessing)
2. **Course Group Optimizer** (grouping & batch creation)
3. **Model Builder** (constraint-based variable creation)

---

## Architecture Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          COMBINED SCHEDULER PIPELINE                        │
└─────────────────────────────────────────────────────────────────────────────┘

INPUT FILES (CSV)
├─ courses.csv
├─ techlongue.csv (rooms)
├─ day_order.csv
├─ core_lab_mapping.csv
└─ pop.csv (teacher preferences)
         │
         ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│ PHASE 1: DATA MODULE (Load & Preprocess)                                   │
│ Location: __init__() lines 34-178                                          │
└─────────────────────────────────────────────────────────────────────────────┘
         │
         ├─→ self.courses_df (pd.DataFrame)
         ├─→ self.rooms_df (pd.DataFrame)
         ├─→ self.day_order_df (pd.DataFrame)
         ├─→ Time configurations (lab_sessions, theory_time_slots)
         ├─→ Room lists (lab_room_ids, theory_room_ids)
         └─→ Department configurations (day_patterns, lunch_slots, shifts)
         │
         ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│ PHASE 2: COURSE GROUP OPTIMIZER (Create Groups)                            │
│ Location: create_course_groups() lines 1901-1941                           │
└─────────────────────────────────────────────────────────────────────────────┘
         │
         ├─→ self.course_groups (dict)
         ├─→ self.instance_group_mapping (dict)
         ├─→ self.group_requirements (dict)
         ├─→ self.lab_requirements (dict)
         └─→ self.theory_requirements (dict)
         │
         ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│ PHASE 3: MODEL BUILDER (Create Variables & Apply Constraints)              │
│ Location: generate_combined_schedule() lines 2475-2509                     │
└─────────────────────────────────────────────────────────────────────────────┘
         │
         ├─→ lab_variables (CP-SAT BoolVars)
         ├─→ group_timeslot_vars (CP-SAT BoolVars)
         └─→ Constraints applied
         │
         ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│ PHASE 4: SOLVER & EXTRACTION                                               │
└─────────────────────────────────────────────────────────────────────────────┘
         │
         └─→ Lab Schedule + Theory Schedule
```

---

## PHASE 1: Data Module Outputs

### 1.1 Core DataFrames (Raw Data)

#### **courses_df** (pd.DataFrame)
```python
# Location: Line 43
self.courses_df = pd.read_csv(course_file)

# Structure:
{
    "id": int,                    # Course instance ID
    "course_code": str,           # e.g., "CSE101"
    "course_name": str,           # e.g., "Data Structures"
    "student_dept": str,          # e.g., "Computer Science & Engineering"
    "semester": int,              # e.g., 3
    "teacher_id": str,            # e.g., "T001"
    "teacher_name": str,          # e.g., "John Doe"
    "practical_hours": int,       # Lab hours (P in LTPC)
    "lecture_hours": int,         # Theory hours (L in LTPC)
    "tutorial_hours": int,        # Tutorial hours (T in LTPC)
    "student_count": int          # Number of students
}

# Used By:
├─ Course Group Optimizer (to create groups)
├─ Lab requirements extraction
└─ Theory requirements extraction

# Key Operations:
├─ Filtering by department/semester
├─ Teacher lookup
└─ Student count aggregation
```

#### **rooms_df** (pd.DataFrame)
```python
# Location: Line 45-67
self.rooms_df = pd.read_csv(techlongue_file)  # Primary source

# Structure:
{
    "id": str,                    # Room number e.g., "LAB201", "A101"
    "capacity": int,              # Student capacity
    "room_type": str,             # "Laboratory", "Classroom", "Lecture Hall"
    "is_lab": int,                # 1 for labs, 0 for theory rooms
    "floor": int,                 # Floor number
    "block": str                  # Building block (optional)
}

# Derived Lists:
├─ self.lab_room_ids = rooms_df[is_lab == 1]['id'].tolist()
│  └─ Used for: Lab variable creation, capacity checks
│
├─ self.theory_room_ids = rooms_df[is_lab == 0]['id'].tolist()
│  └─ Used for: Theory room assignment (post-processing)
│
└─ self.laboratory_room_ids = rooms_df[room_type == 'Laboratory']['id'].tolist()
   └─ Used for: Core lab restriction constraint

# Used By:
├─ Lab variable creation (line 2512-2556)
├─ Room capacity constraints
└─ Core lab mapping constraints
```

#### **day_order_df** (pd.DataFrame)
```python
# Location: Line 69 (_load_day_order())
self.day_order_df = self._load_day_order()

# Structure:
{
    "department": str,            # Department name
    "semester": int,              # Semester number (optional)
    "day_pattern": str,           # "M-F", "M-Th-F", "M-W-F", etc.
    "shift": str                  # "morning", "evening", "full" (optional)
}

# Used By:
└─ _setup_department_day_patterns() → department_day_patterns

# Example:
{
    "Computer Science & Engineering": ["monday", "tuesday", "wed", "thur", "fri"],
    "Mechanical Engineering": ["monday", "thur", "fri"]
}
```

---

### 1.2 Time System Configuration

#### **Lab Time System**
```python
# Location: Lines 86-136

# A. Lab Time Slots (12 slots of 50 minutes each)
self.lab_time_slots = [
    "8:00 - 8:50", "8:50 - 9:40", "9:50 - 10:40", "10:40 - 11:30",
    "11:40 - 12:30", "12:30 - 1:20", "1:50 - 2:40", "2:40 - 3:20", 
    "3:30 - 4:20", "4:20 - 5:10", "5:20 - 6:10", "5:10 - 7:00"
]
self.num_lab_slots = 12

# B. Lab Sessions (6 sessions of 2 hours each)
self.lab_sessions = {
    'L1': {'slots': [0, 1], 'time_range': '8:00 - 9:40'},
    'L2': {'slots': [2, 3], 'time_range': '9:50 - 11:30'},
    'L3': {'slots': [4, 5], 'time_range': '11:40 - 1:20'},
    'L4': {'slots': [6, 7], 'time_range': '1:50 - 3:20'},
    'L5': {'slots': [8, 9], 'time_range': '3:30 - 5:10'},
    'L6': {'slots': [10, 11], 'time_range': '5:20 - 7:00'}
}
self.num_lab_sessions = 6

# C. Lab Session Details (for constraint mapping)
self.lab_sessions_details = {
    'L1': {'slots': [0, 1]},
    'L2': {'slots': [2, 3]},
    ...
}

# Used By:
├─ Lab variable creation (iteration over sessions)
├─ Lab-to-theory time mapping
└─ Consecutive batch constraints
```

#### **Theory Time System**
```python
# Location: Lines 140-156

# Theory Time Slots (11 slots of 50 minutes each)
self.theory_time_slots = [
    "8:00 - 8:50", "8:55 - 9:45", "9:50 - 10:40", "10:45 - 11:35", 
    "11:40 - 12:30", "12:35 - 1:20", "1:50 - 2:40", "3:20 - 4:10", 
    "4:15 - 5:05", "5:10 - 6:00", "6:10 - 7:00"
]
self.num_theory_slots = 11

# Used By:
├─ Theory variable creation (iteration over slots)
├─ Lab-to-theory time mapping
└─ Lunch break constraints
```

#### **Lab-to-Theory Time Mapping**
```python
# Location: Line 158 (_build_time_mapping())
self._build_time_mapping()

# Creates:
self.lab_to_theory_slot_mapping = {
    'L1': [0, 1],      # L1 (8:00-9:40) overlaps theory slots 0-1
    'L2': [2, 3],      # L2 (9:50-11:30) overlaps theory slots 2-3
    'L3': [4, 5],      # L3 (11:40-1:20) overlaps theory slots 4-5
    'L4': [6, 7],      # L4 (1:50-3:20) overlaps theory slots 6-7
    'L5': [8, 9],      # L5 (3:30-5:10) overlaps theory slots 8-9
    'L6': [10, 11]     # L6 (5:20-7:00) overlaps theory slots 10-11 (approx)
}

# Also creates (reverse mapping):
self.theory_to_lab_mapping = {
    0: ['L1'],
    1: ['L1'],
    2: ['L2'],
    ...
}

# Used By:
├─ Unified teacher clash constraint (cross-system conflicts)
├─ Dept-semester group conflict constraint
└─ Lab lunch break constraint
```

---

### 1.3 Department Configurations

#### **Department Day Patterns**
```python
# Location: Line 71 (_setup_department_day_patterns())
self._setup_department_day_patterns()

# Creates:
self.department_day_patterns = {
    "Computer Science & Engineering": {
        "default": ["monday", "tuesday", "wed", "thur", "fri"],
        "semester_overrides": {}  # Can override per semester
    },
    "Mechanical Engineering": {
        "default": ["monday", "thur", "fri"],
        "semester_overrides": {
            5: ["monday", "tuesday", "thur", "fri"]  # S5 override
        }
    }
}

# Helper Methods:
├─ _get_days_for_department(dept_name, semester) → list
└─ _get_day_pattern_for_department(dept_name, semester) → str

# Used By:
├─ Lab variable creation (determines num_dept_days)
├─ Theory variable creation (determines num_dept_days)
└─ Shift-based constraints
```

#### **Lunch Break Slots**
```python
# Location: Line 74 (_setup_lunch_break_configuration())
self._setup_lunch_break_configuration()

# Creates:
self.lunch_break_slots = {
    "Computer Science & Engineering": 4,     # Theory slot index
    "Mechanical Engineering": 5,
    ...
}

# Also creates:
self.flexible_lunch_departments = [
    "Biotechnology",
    "Food Technology"
]

# Helper Methods:
├─ get_lunch_break_slot(dept, semester) → int
├─ is_lunch_break_slot(slot_idx, dept, semester) → bool
└─ is_flexible_lunch_department(dept, semester) → bool

# Used By:
├─ Theory lunch break constraint
├─ Lab lunch break constraint (via time mapping)
└─ Flexible lunch constraint (soft)
```

#### **Shift Configurations**
```python
# Location: Line 77 (_setup_shift_based_constraints())
self._setup_shift_based_constraints()

# Creates:
self.shift_departments = {
    "Computer Science & Engineering": {
        "shift_pattern": "morning",          # or "evening"
        "theory_slots": [0, 1, 2, 3, 4, 5],  # Allowed theory slots
        "lab_sessions": ["L1", "L2", "L3"],  # Allowed lab sessions
        "shift_pattern_by_day": {
            0: "morning",  # Monday
            1: "morning",  # Tuesday
            ...
        }
    }
}

# Helper Methods:
├─ is_shift_department(dept) → bool
├─ get_shift_theory_slots(shift_id) → list
├─ get_shift_lab_sessions(shift_id) → list
└─ get_department_shift_for_day(dept, day_idx) → str

# Used By:
├─ Shift-based lab constraint
├─ Shift-based theory constraint
└─ Unified weekly shift constraint
```

#### **5pm Constraints**
```python
# Location: Line 161 (_setup_5pm_constraints())
self._setup_5pm_constraints()

# Creates:
self.five_pm_constraints = {
    "Mechanical Engineering": {
        "type": "hard",           # or "soft"
        "last_slot": 8,           # Last allowed theory slot (5:30pm cutoff)
        "last_session": "L5"      # Last allowed lab session
    }
}

# Used By:
└─ _apply_5pm_constraints() (line 5630-5785)
```

#### **Teacher Day Preferences**
```python
# Location: Line 207 (_load_teacher_day_preferences())
self._load_teacher_day_preferences()

# Creates:
self.teacher_day_preferences = {
    "T001": {
        "preferred_days": ["monday", "wednesday", "friday"],
        "courses": ["CSE101", "CSE201"]
    }
}

# Used By:
└─ _apply_teacher_day_preference_constraints() (line 4954-5078)
```

---

### 1.4 Room-Related Data

#### **Core Lab Mapping**
```python
# Location: Line 175 (_load_core_lab_mapping())
self._load_core_lab_mapping()

# Creates:
self.core_lab_mapping = {
    "CSE_S3_G1": ["LAB201", "LAB202", "LAB203"],
    "CSE_S3_G2": ["LAB204", "LAB205"],
    "ME_S5_G1": ["LAB301", "LAB302"]
}

# Also creates:
self.course_to_room_mapping = {
    ("CSE101", "Data Structures"): ["LAB201", "LAB202"],
    ("ME201", "Mechanics Lab"): ["LAB301"]
}

# Used By:
└─ apply_core_lab_mapping_constraint() (line 3540-3657)
```

---

## PHASE 2: Course Group Optimizer Outputs

### 2.1 Course Groups (Primary Structure)

#### **course_groups** (dict)
```python
# Location: Line 1901-1941 (create_course_groups())
self.course_groups = {}

# Structure:
{
    ("Computer Science & Engineering", 3): [  # (dept, semester) key
        [  # Group 1 (G1)
            {
                "id": "CSE_S3_1001",              # Instance ID
                "course_code": "CSE101",
                "course_name": "Data Structures",
                "teacher_id": "T001",
                "teacher_name": "John Doe",
                "lecture_hours": 3,
                "practical_hours": 2,
                "tutorial_hours": 0,
                "student_count": 60,
                "has_lab": True,
                "has_theory": True
            },
            {
                "id": "CSE_S3_1002",
                "course_code": "CSE102",
                ...
            }
        ],
        [  # Group 2 (G2)
            {...},
            {...}
        ]
    ],
    ("Mechanical Engineering", 5): [...]
}

# Properties:
├─ Organized by (department, semester)
├─ Each group contains course instances
├─ Instances have complete course information
└─ Groups are optimized for:
   ├─ Minimal teacher overlap (Hall's Theorem)
   ├─ Balanced student counts
   └─ Maximum student choice

# Used By:
├─ instance_group_mapping creation
├─ group_requirements computation
├─ lab_requirements filtering
├─ Theory variable creation
└─ ALL group-based constraints
```

---

### 2.2 Instance-Group Mapping

#### **instance_group_mapping** (dict)
```python
# Location: Line 2272-2297 (_create_instance_group_mapping())
self.instance_group_mapping = {}

# Structure:
{
    "CSE_S3_1001": {
        "group_name": "Computer Science & Engineering_S3_G1",
        "group_index": 1,
        "department": "Computer Science & Engineering",
        "semester": 3,
        "teacher_id": "T001",
        "course_code": "CSE101",
        "has_lab": True,
        "has_theory": True,
        "practical_hours": 2,
        "lecture_hours": 3,
        "tutorial_hours": 0
    },
    "CSE_S3_1002": {...},
    ...
}

# Key Features:
├─ Maps EVERY instance to its group
├─ Includes complete metadata
└─ Fast lookup by instance_id

# Used By:
├─ Lab variable creation (to get dept/semester/group)
├─ Core lab mapping constraint (to map instance → group → allowed rooms)
├─ Dept-semester group conflict constraint
└─ Cross-department teacher constraints

# CRITICAL: This is the BRIDGE between:
├─ Lab scheduling (instance-based)
└─ Theory scheduling (group-based)
```

---

### 2.3 Group Requirements (Theory)

#### **group_requirements** (dict)
```python
# Location: Line 1513-1541 (_compute_group_requirements())
self.group_requirements = {}

# Structure:
{
    "Computer Science & Engineering_S3_G1": 8,  # Theory hours per week
    "Computer Science & Engineering_S3_G2": 7,
    "Mechanical Engineering_S5_G1": 6,
    ...
}

# Computation:
For each group in course_groups:
    total_theory_hours = sum(
        instance['lecture_hours'] + instance['tutorial_hours']
        for instance in group
    )
    group_requirements[group_name] = total_theory_hours

# Example:
Group CSE_S3_G1 contains:
├─ CSE_S3_1001 (3 lecture + 0 tutorial = 3h)
├─ CSE_S3_1002 (3 lecture + 0 tutorial = 3h)
└─ CSE_S3_1003 (2 lecture + 0 tutorial = 2h)
→ group_requirements["CSE_S3_G1"] = 8 hours

# Used By:
├─ Theory variable creation (knows how many slots to create)
└─ apply_group_based_scheduling_constraint() (line 3427-3537)
   └─ Ensures: sum(group_timeslot_vars[group]) == group_requirements[group]
```

---

### 2.4 Lab Requirements (Lab)

#### **lab_requirements** (dict)
```python
# Location: Line 1944-2016 (_update_lab_requirements_with_virtual_instances())
# Also: Line 2396-2445 (_filter_lab_requirements_by_groups())
self.lab_requirements = {}

# Structure:
{
    "T001": [  # Teacher ID
        {
            "course_instance_id": "CSE_S3_1001",
            "course_code": "CSE101",
            "course_name": "Data Structures",
            "lab_sessions_needed": 2,        # Number of 2-hour sessions
            "practical_hours": 4,
            "students_per_instance": 60,
            "department": "Computer Science & Engineering",
            "semester": 3
        },
        {
            "course_instance_id": "CSE_S5_2003",
            ...
        }
    ],
    "T002": [...]
}

# Computation:
For each course with practical_hours > 0:
    teacher_id = course['teacher_id']
    sessions_needed = practical_hours / 2  # Each session = 2 hours
    
    lab_requirements[teacher_id].append({
        "course_instance_id": instance_id,
        "lab_sessions_needed": sessions_needed,
        "practical_hours": practical_hours,
        ...
    })

# Filtering:
After group creation, filter to only include instances in groups:
    lab_requirements = {
        teacher: [
            req for req in reqs 
            if req['course_instance_id'] in instance_group_mapping
        ]
        for teacher, reqs in lab_requirements.items()
    }

# Used By:
├─ Lab variable creation (knows what to schedule)
├─ apply_course_lab_requirements_constraint() (line 2680-2956)
│  └─ Ensures: sum(lab_variables[teacher][instance]) == lab_sessions_needed
├─ Unified teacher clash constraint
└─ Consecutive batch scheduling constraint
```

---

### 2.5 Theory Requirements (Theory)

#### **theory_requirements** (dict)
```python
# Location: Derived from course_groups
self.theory_requirements = {}

# Structure:
{
    "T001": [  # Teacher ID
        {
            "group_name": "Computer Science & Engineering_S3_G1",
            "course_instance_id": "CSE_S3_1001",
            "course_code": "CSE101",
            "lecture_hours": 3,
            "tutorial_hours": 0,
            "department": "Computer Science & Engineering",
            "semester": 3
        }
    ]
}

# Used By:
├─ Teacher clash constraint (to know which groups each teacher teaches)
└─ Teacher daily presence constraint
```

---

## PHASE 3: Model Builder Inputs

### 3.1 What Model Builder Receives

The model builder (`generate_combined_schedule()`) has access to ALL data from Phases 1 and 2:

```python
def generate_combined_schedule(self):
    # AVAILABLE DATA:
    
    # FROM DATA MODULE:
    ├─ self.courses_df
    ├─ self.rooms_df
    ├─ self.lab_room_ids (list)
    ├─ self.theory_room_ids (list)
    ├─ self.laboratory_room_ids (list)
    ├─ self.lab_sessions (dict)
    ├─ self.theory_time_slots (list)
    ├─ self.num_lab_slots (int)
    ├─ self.num_theory_slots (int)
    ├─ self.lab_to_theory_slot_mapping (dict)
    ├─ self.theory_to_lab_mapping (dict)
    ├─ self.department_day_patterns (dict)
    ├─ self.lunch_break_slots (dict)
    ├─ self.shift_departments (dict)
    ├─ self.five_pm_constraints (dict)
    ├─ self.teacher_day_preferences (dict)
    └─ self.core_lab_mapping (dict)
    
    # FROM COURSE GROUP OPTIMIZER:
    ├─ self.course_groups (dict)
    ├─ self.instance_group_mapping (dict)
    ├─ self.group_requirements (dict)
    ├─ self.lab_requirements (dict)
    └─ self.theory_requirements (dict)
```

---

### 3.2 Variable Creation Process

#### **Lab Variables Creation**
```python
# Location: Line 2512-2556 (_create_lab_variables())

def _create_lab_variables(self, model):
    lab_assignments = {}
    
    # INPUTS USED:
    ├─ self.lab_requirements (iteration: teacher → courses)
    ├─ self.instance_group_mapping (lookup: instance → dept/semester)
    ├─ self.department_day_patterns (lookup: dept → num_days)
    ├─ self.lab_sessions (iteration: session names)
    └─ self.lab_room_ids (iteration: room IDs)
    
    # LOGIC:
    For each teacher in lab_requirements:
        For each course of that teacher:
            instance_id = course['course_instance_id']
            
            # Get department-specific days
            dept = instance_group_mapping[instance_id]['department']
            semester = instance_group_mapping[instance_id]['semester']
            num_dept_days = len(_get_days_for_department(dept, semester))
            
            # Create variables
            For day in range(num_dept_days):
                For session in lab_sessions:
                    For room in lab_room_ids:
                        var = model.NewBoolVar(
                            f'lab_{teacher}_{instance}_{day}_{session}_{room}'
                        )
                        lab_assignments[teacher][instance][day][session][room] = var
    
    # OUTPUT:
    return lab_assignments  # Structure: [teacher][instance][day][session][room] → BoolVar
```

#### **Theory Variables Creation**
```python
# Location: Line 2569-2605 (_create_group_timeslot_variables())

def _create_group_timeslot_variables(self, model):
    group_timeslot_vars = {}
    
    # INPUTS USED:
    ├─ self.group_requirements (iteration: group_name → required_slots)
    ├─ self.department_day_patterns (lookup: dept → num_days)
    └─ self.num_theory_slots (iteration bounds)
    
    # LOGIC:
    For each group_name in group_requirements:
        # Parse group name to get dept/semester
        dept = group_name.split('_S')[0]
        semester = extract_semester(group_name)
        
        # Get department-specific days
        num_dept_days = len(_get_days_for_department(dept, semester))
        
        # Create variables
        For day in range(num_dept_days):
            For slot in range(num_theory_slots):
                var = model.NewBoolVar(
                    f'group_{group_name}_day_{day}_slot_{slot}'
                )
                group_timeslot_vars[group_name][day][slot] = var
    
    # OUTPUT:
    return group_timeslot_vars  # Structure: [group_name][day][slot] → BoolVar
```

---

## Complete Data Contract Summary

### Data Module MUST Provide:

```python
# 1. RAW DATA (DataFrames)
├─ courses_df: pd.DataFrame
├─ rooms_df: pd.DataFrame
└─ day_order_df: pd.DataFrame

# 2. TIME SYSTEM
├─ lab_time_slots: List[str]
├─ lab_sessions: Dict[str, Dict]
├─ theory_time_slots: List[str]
├─ num_lab_slots: int
├─ num_theory_slots: int
├─ lab_to_theory_slot_mapping: Dict[str, List[int]]
└─ theory_to_lab_mapping: Dict[int, List[str]]

# 3. ROOM LISTS
├─ lab_room_ids: List[str]
├─ theory_room_ids: List[str]
└─ laboratory_room_ids: List[str]

# 4. DEPARTMENT CONFIGS
├─ department_day_patterns: Dict[str, Dict]
├─ lunch_break_slots: Dict[str, int]
├─ shift_departments: Dict[str, Dict]
├─ five_pm_constraints: Dict[str, Dict]
├─ teacher_day_preferences: Dict[str, Dict]
└─ core_lab_mapping: Dict[str, List[str]]
```

### Course Group Optimizer MUST Provide:

```python
# 1. GROUPING STRUCTURE
├─ course_groups: Dict[Tuple[str, int], List[List[Dict]]]
│   └─ Structure: {(dept, sem): [[instance1, instance2], [instance3, instance4]]}
│
├─ instance_group_mapping: Dict[str, Dict]
│   └─ Structure: {instance_id: {group_name, dept, semester, teacher, ...}}
│
└─ group_requirements: Dict[str, int]
    └─ Structure: {group_name: theory_hours_needed}

# 2. SCHEDULING REQUIREMENTS
├─ lab_requirements: Dict[str, List[Dict]]
│   └─ Structure: {teacher_id: [{instance, sessions_needed, ...}]}
│
└─ theory_requirements: Dict[str, List[Dict]]
    └─ Structure: {teacher_id: [{group_name, instance, hours, ...}]}
```

### Model Builder CONSUMES:

```python
# VARIABLE CREATION:
├─ lab_requirements → Lab variables
│   └─ Creates: lab_variables[teacher][instance][day][session][room]
│
└─ group_requirements → Theory variables
    └─ Creates: group_timeslot_vars[group_name][day][slot]

# CONSTRAINT APPLICATION:
├─ instance_group_mapping → Core lab mapping, dept-sem conflict
├─ lab_to_theory_slot_mapping → Cross-system constraints
├─ department_day_patterns → Day-specific constraints
├─ lunch_break_slots → Lunch break constraints
├─ shift_departments → Shift-based constraints
├─ teacher_day_preferences → Teacher preference constraints
└─ core_lab_mapping → Core lab restriction constraint
```

---

## Data Flow Diagram (Detailed)

```
┌───────────────────────────────────────────────────────────────────────────┐
│                        CSV FILES (Input)                                  │
└───────────────────────────────────────────────────────────────────────────┘
    │
    │ courses.csv → courses_df (327 courses)
    │ techlongue.csv → rooms_df (140 rooms)
    │ day_order.csv → day_order_df (dept schedules)
    │ core_lab_mapping.csv → core mappings
    │ pop.csv → teacher preferences
    │
    ↓
┌───────────────────────────────────────────────────────────────────────────┐
│                    DATA MODULE (Preprocessing)                            │
└───────────────────────────────────────────────────────────────────────────┘
    │
    ├─→ Time Systems
    │   ├─ lab_sessions (6 sessions: L1-L6)
    │   ├─ theory_time_slots (11 slots)
    │   └─ lab_to_theory_slot_mapping (overlap detection)
    │
    ├─→ Room Lists
    │   ├─ lab_room_ids (140 rooms)
    │   ├─ theory_room_ids (50 rooms)
    │   └─ laboratory_room_ids (core labs only)
    │
    └─→ Department Configs
        ├─ department_day_patterns (M-F, M-Th-F, etc.)
        ├─ lunch_break_slots (per dept)
        ├─ shift_departments (shift configs)
        └─ teacher_day_preferences (from pop.csv)
    │
    ↓
┌───────────────────────────────────────────────────────────────────────────┐
│               COURSE GROUP OPTIMIZER (Grouping)                           │
└───────────────────────────────────────────────────────────────────────────┘
    │
    ├─→ course_groups
    │   └─ {(dept, sem): [[inst1, inst2], [inst3, inst4]]}
    │       └─ Optimized for Hall's Theorem (minimal teacher overlap)
    │
    ├─→ instance_group_mapping
    │   └─ {instance_id: {group, dept, sem, teacher, ...}}
    │       └─ BRIDGE between instance-based (labs) and group-based (theory)
    │
    ├─→ group_requirements
    │   └─ {group_name: theory_hours_needed}
    │       └─ Drives theory variable creation
    │
    └─→ lab_requirements
        └─ {teacher_id: [{instance, sessions_needed, ...}]}
            └─ Drives lab variable creation
    │
    ↓
┌───────────────────────────────────────────────────────────────────────────┐
│                   MODEL BUILDER (Variable Creation)                       │
└───────────────────────────────────────────────────────────────────────────┘
    │
    ├─→ CREATE LAB VARIABLES
    │   │
    │   ├─ INPUT: lab_requirements (teacher → courses)
    │   ├─ INPUT: instance_group_mapping (instance → dept/sem)
    │   ├─ INPUT: department_day_patterns (dept → num_days)
    │   ├─ INPUT: lab_sessions (session names)
    │   └─ INPUT: lab_room_ids (room list)
    │   │
    │   └─→ OUTPUT: lab_variables[teacher][instance][day][session][room]
    │       └─ ~1.7M BoolVars (205 teachers × 4 instances × 5 days × 6 sessions × 140 rooms)
    │
    └─→ CREATE THEORY VARIABLES
        │
        ├─ INPUT: group_requirements (group → hours_needed)
        ├─ INPUT: department_day_patterns (dept → num_days)
        └─ INPUT: num_theory_slots (slot count)
        │
        └─→ OUTPUT: group_timeslot_vars[group][day][slot]
            └─ ~2,800 BoolVars (50 groups × 5 days × 11 slots)
    │
    ↓
┌───────────────────────────────────────────────────────────────────────────┐
│                    CONSTRAINT APPLICATION                                 │
└───────────────────────────────────────────────────────────────────────────┘
    │
    ├─→ LAB CONSTRAINTS
    │   ├─ Course lab requirements (lab_requirements)
    │   ├─ Room single assignment (lab_variables)
    │   ├─ Core lab mapping (core_lab_mapping + instance_group_mapping)
    │   ├─ Shift-based (shift_departments)
    │   └─ Lab lunch break (lunch_break_slots + lab_to_theory_slot_mapping)
    │
    ├─→ THEORY CONSTRAINTS
    │   ├─ Group requirements (group_requirements)
    │   ├─ Room capacity (group_requirements + rooms_df)
    │   ├─ Daily slot limit (group_timeslot_vars)
    │   ├─ Teacher presence (course_groups)
    │   ├─ Shift-based (shift_departments)
    │   └─ Theory lunch break (lunch_break_slots)
    │
    └─→ CROSS-SYSTEM CONSTRAINTS
        ├─ Unified teacher clash (lab_requirements + course_groups + lab_to_theory_slot_mapping)
        └─ Dept-sem group conflict (instance_group_mapping + lab_to_theory_slot_mapping)
    │
    ↓
┌───────────────────────────────────────────────────────────────────────────┐
│                       SOLVER & EXTRACTION                                 │
└───────────────────────────────────────────────────────────────────────────┘
    │
    └─→ Lab Schedule + Theory Schedule
```

---

## Key Insights for Modular Design

### 1. **Clear Module Boundaries**

```
DATA MODULE:
└─ Responsible for: Raw data loading, time systems, dept configs
└─ Output Format: DataFrames + configuration dicts

COURSE GROUP OPTIMIZER:
└─ Responsible for: Grouping, batch creation, requirement computation
└─ Output Format: Structured dicts (course_groups, mappings, requirements)

MODEL BUILDER:
└─ Responsible for: Variable creation, constraint application
└─ Input Format: All outputs from Data Module + Course Group Optimizer
```

### 2. **Critical Bridge: instance_group_mapping**

This is the **MOST IMPORTANT** data structure because it:
- Links instance-based lab scheduling to group-based theory scheduling
- Enables cross-system constraints (dept-sem group conflict)
- Provides metadata for constraints (dept, semester, teacher, group)

### 3. **Type Contracts**

```python
# Data Module Output Types
TimeSystem = Dict[str, Union[List[str], Dict[str, Dict[str, List[int]]]]]
RoomLists = Dict[str, List[str]]
DeptConfigs = Dict[str, Union[Dict, List, int]]

# Course Group Optimizer Output Types
CourseGroups = Dict[Tuple[str, int], List[List[Dict[str, Any]]]]
InstanceGroupMapping = Dict[str, Dict[str, Any]]
GroupRequirements = Dict[str, int]
LabRequirements = Dict[str, List[Dict[str, Any]]]

# Model Builder Input Types
All of the above
```

### 4. **Data Validation Points**

```python
# After Data Module:
assert len(lab_room_ids) > 0, "No lab rooms found"
assert len(theory_time_slots) == num_theory_slots
assert all(dept in department_day_patterns for dept in courses_df['student_dept'])

# After Course Group Optimizer:
assert len(course_groups) > 0, "No groups created"
assert all(instance in instance_group_mapping for group in course_groups.values() for subgroup in group for instance in subgroup)
assert sum(group_requirements.values()) > 0, "No theory hours to schedule"

# Before Model Builder:
assert len(lab_requirements) > 0, "No lab requirements"
assert len(group_requirements) > 0, "No group requirements"
```

---

## Recommended Modular Architecture

```python
# 1. DATA MODULE
class DataModule:
    def load_data(self) -> DataLoadResult:
        return DataLoadResult(
            courses_df=...,
            rooms_df=...,
            time_system=TimeSystemConfig(...),
            room_lists=RoomLists(...),
            dept_configs=DeptConfigs(...)
        )

# 2. COURSE GROUP OPTIMIZER
class CourseGroupOptimizer:
    def create_groups(self, data: DataLoadResult) -> GroupOptimizationResult:
        return GroupOptimizationResult(
            course_groups=...,
            instance_group_mapping=...,
            group_requirements=...,
            lab_requirements=...,
            theory_requirements=...
        )

# 3. MODEL BUILDER
class ModelBuilder:
    def build_model(
        self, 
        data: DataLoadResult, 
        groups: GroupOptimizationResult
    ) -> cp_model.CpModel:
        lab_vars = self._create_lab_variables(...)
        theory_vars = self._create_theory_variables(...)
        self._apply_constraints(...)
        return model
```

This contract ensures clean separation of concerns and clear data flow!
