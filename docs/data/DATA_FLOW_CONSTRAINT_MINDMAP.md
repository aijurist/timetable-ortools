# Data Flow Through Constraints - Complete Mindmap

## Overview: Data Journey from CSVs to Constraints

```
CSV Files → Data Processing → Group Formation → Variable Creation → Constraint Application → Solver
```

---

## 1. INPUT DATA SOURCES (Raw CSVs)

```
┌─────────────────────────────────────────────────────────────────┐
│                     RAW DATA FILES                              │
└─────────────────────────────────────────────────────────────────┘
         │
         ├─→ courses.csv (Computer-Depts-LTPC.csv)
         │   ├─ course_code
         │   ├─ course_name
         │   ├─ department
         │   ├─ semester
         │   ├─ teacher_id
         │   ├─ teacher_name
         │   ├─ practical_hours (P)
         │   ├─ lecture_hours (L)
         │   ├─ tutorial_hours (T)
         │   └─ student_count
         │
         ├─→ techlongue.csv (Room data)
         │   ├─ id (room number)
         │   ├─ capacity
         │   ├─ room_type (Lab/Theory)
         │   ├─ is_lab (0/1)
         │   ├─ floor
         │   └─ block
         │
         ├─→ day_order.csv (Department schedules)
         │   ├─ department
         │   ├─ semester
         │   ├─ day_pattern (M-F, M-Th-F, etc.)
         │   └─ shift (morning/evening)
         │
         ├─→ core_lab_mapping.csv (Lab restrictions)
         │   ├─ group_id
         │   └─ allowed_rooms
         │
         └─→ pop.csv (Teacher preferences)
             ├─ teacher_id
             └─ preferred_days
```

---

## 2. DATA PROCESSING LAYER

### Phase 1: Load and Parse (lines 1729-1816)

```
process_courses()
    ├─→ Read courses.csv
    ├─→ Normalize department names
    ├─→ Extract teacher info
    ├─→ Calculate total hours per course
    └─→ Store in self.courses_df

OUTPUTS:
    ├─ self.courses_df: Full course data
    ├─ self.teachers_df: Unique teacher list
    └─ self.departments: Unique department set
```

### Phase 2: Time System Setup (lines 83-166)

```
Time Configuration
    ├─→ LAB TIME SLOTS (12 slots)
    │   ├─ self.lab_time_slots = ["8:00-8:50", "8:50-9:40", ...]
    │   ├─ self.lab_sessions = {
    │   │   "L1": {"slots": [0,1], "time_range": "8:00-9:40"},
    │   │   "L2": {"slots": [2,3], "time_range": "9:50-11:30"},
    │   │   ...
    │   │   "L6": {"slots": [10,11], "time_range": "5:20-7:00"}
    │   └─ }
    │
    ├─→ THEORY TIME SLOTS (11 slots)
    │   ├─ self.theory_time_slots = ["8:00-8:50", "8:55-9:45", ...]
    │   └─ One slot = 50 minutes
    │
    └─→ TIME MAPPING (line 1544-1610)
        └─ _build_time_mapping()
            ├─ Maps lab sessions to theory slot ranges
            ├─ self.lab_to_theory_slot_mapping = {
            │   "L1": [0, 1],      # L1 overlaps theory slots 0-1
            │   "L2": [2, 3],      # L2 overlaps theory slots 2-3
            │   ...
            └─ }
            └─ Used for cross-system conflict detection
```

### Phase 3: Room Processing (lines 169-178)

```
Room Registry
    ├─→ self.lab_rooms = rooms where is_lab == 1
    │   ├─ Used for: Lab variable creation, capacity checks
    │   └─ self.lab_room_ids = ["LAB201", "LAB202", ...]
    │
    ├─→ self.theory_rooms = rooms where is_lab == 0
    │   ├─ Used for: Theory variable creation, capacity checks
    │   └─ self.theory_room_ids = ["A101", "A102", ...]
    │
    └─→ self.laboratory_room_ids = rooms where room_type == "Laboratory"
        ├─ Subset of lab_rooms
        └─ Used for: Core lab restriction constraint
```

### Phase 4: Department Configuration (lines 575-839)

```
Department-Specific Configs
    ├─→ _setup_department_day_patterns() (line 575-640)
    │   ├─ self.department_day_patterns = {
    │   │   "Computer Science & Engineering": {
    │   │       "default": ["monday", "tuesday", "wed", "thur", "fri"],
    │   │       "semester_overrides": {}
    │   │   },
    │   │   "Mechanical Engineering": {
    │   │       "default": ["monday", "thur", "fri"],
    │   │       ...
    │   │   }
    │   └─ }
    │
    ├─→ _setup_lunch_break_configuration() (line 701-839)
    │   ├─ self.lunch_break_slots = {
    │   │   "Computer Science & Engineering": 4,  # Slot index
    │   │   "Mechanical Engineering": 5,
    │   │   ...
    │   └─ }
    │
    ├─→ _setup_shift_based_constraints() (line 914-1034)
    │   ├─ self.shift_departments = {
    │   │   "Computer Science & Engineering": {
    │   │       "shift_pattern": "morning",
    │   │       "theory_slots": [0,1,2,3,4,5],
    │   │       "lab_sessions": ["L1", "L2", "L3"]
    │   │   }
    │   └─ }
    │
    └─→ _setup_5pm_constraints() (line 1037-1132)
        └─ self.five_pm_constraints = {
            "Mechanical Engineering": {"type": "hard", "last_slot": 8}
        }
```

---

## 3. GROUP FORMATION (Core Transformation)

### Phase 1: Create Course Groups (line 1901-1941)

```
create_course_groups()
    ↓
_create_course_groups_by_dept_semester() (line 2019-2070)
    ↓
For each (department, semester):
    ├─→ Collect all course instances
    ├─→ _distribute_course_instances_optimized() (line 2073-2118)
    │   ├─ Apply CourseGroupOptimizer
    │   ├─ Minimize teacher overlap
    │   └─ Balance student counts
    │
    └─→ Create groups structure:
        {
            "Computer Science & Engineering": {
                "semester_3": [
                    {
                        "group_id": "CSE_S3_G1",
                        "instances": ["CSE_S3_1001", "CSE_S3_1002", "CSE_S3_1003"],
                        "students": 45,
                        "teachers": ["T001", "T002", "T003"],
                        "courses": [<course_obj_1>, <course_obj_2>, ...]
                    },
                    {"group_id": "CSE_S3_G2", ...},
                    {"group_id": "CSE_S3_G3", ...}
                ],
                "semester_5": [...]
            },
            "Mechanical Engineering": {...}
        }

STORED IN: self.groups
```

### Phase 2: Create Mappings (line 2272-2297)

```
_create_instance_group_mapping()
    ↓
For each group:
    For each instance in group:
        instance_group_mapping[instance_id] = {
            "group": group_id,
            "dept": department,
            "semester": semester,
            "students": student_count,
            "teachers": teacher_list
        }

EXAMPLE:
    instance_group_mapping["CSE_S3_1001"] = {
        "group": "CSE_S3_G1",
        "dept": "Computer Science & Engineering",
        "semester": 3,
        "students": 45
    }

STORED IN: self.instance_group_mapping
USED BY:
    ├─ Theory constraints (to know which instances move together)
    ├─ Cross-system constraints (group-based conflicts)
    └─ Validation (checking group integrity)
```

### Phase 3: Compute Requirements (line 1513-1541)

```
_compute_group_requirements()
    ↓
For each group:
    total_theory_hours = sum(course.lecture_hours for course in group)
    group_requirements[group_id] = total_theory_hours

EXAMPLE:
    Group CSE_S3_G1 has:
        - DS (3 theory hours)
        - OS (3 theory hours)
        - DBMS (2 theory hours)
        → group_requirements["CSE_S3_G1"] = 8 hours/week

STORED IN: self.group_requirements
USED BY:
    └─ Theory requirement constraint (ensures 8 slots scheduled)
```

### Phase 4: Extract Lab Requirements (line 1944-2016)

```
_update_lab_requirements_with_virtual_instances()
    ↓
For each course with practical_hours > 0:
    teacher_id = course.teacher_id
    sessions_needed = practical_hours / 2  # Each session = 2 hours
    
    lab_requirements[teacher_id].append({
        "course": course_instance_id,
        "sessions": sessions_needed,
        "practical_hours": practical_hours,
        "students": student_count,
        "dept": department,
        "semester": semester
    })

EXAMPLE:
    lab_requirements["T001"] = [
        {
            "course": "CSE_S3_1001",  # Data Structures
            "sessions": 2,             # Needs 2 lab sessions
            "practical_hours": 4,
            "students": 60,
            "dept": "CSE",
            "semester": 3
        },
        {
            "course": "CSE_S5_2003",  # ML lab
            "sessions": 2,
            ...
        }
    ]

STORED IN: self.lab_requirements
USED BY:
    ├─ Lab variable creation (knows what to schedule)
    ├─ Lab requirement constraint
    └─ Teacher clash constraint
```

### Phase 5: Core Lab Mapping (line 1302-1510)

```
_load_core_lab_mapping()
    ↓
Read core_lab_mapping.csv
    ↓
For each mapping:
    core_lab_mapping[group_id] = [allowed_room_ids]

EXAMPLE:
    core_lab_mapping = {
        "CSE_S3_G1": ["LAB201", "LAB202", "LAB203"],
        "CSE_S3_G2": ["LAB204", "LAB205"],
        "ME_S5_G1": ["LAB301", "LAB302"]
    }

STORED IN: self.core_lab_mapping
USED BY:
    └─ Core lab mapping constraint (restricts room choices)
```

---

## 4. VARIABLE CREATION (Decision Space)

### Lab Variables (line 2512-2556)

```
_create_lab_variables(model)
    ↓
STRUCTURE: lab_variables[teacher_id][course_instance][day][session_name][room_id]

For each teacher in lab_requirements:
    For each requirement (course_instance) of that teacher:
        For each day (0 to 4):
            For each lab_session ("L1" to "L6"):
                For each lab_room:
                    var_name = f"lab_{teacher}_{instance}_{day}_{session}_{room}"
                    lab_variables[teacher][instance][day][session][room] = model.NewBoolVar(var_name)

EXAMPLE VARIABLE:
    lab_variables["T001"]["CSE_S3_1001"][0]["L1"]["LAB201"] = BoolVar_12345
    Meaning: "Teacher T001 teaches CSE_S3_1001 on Monday in session L1 in LAB201"

TOTAL VARIABLES: ~1.7M BoolVars
    (205 teachers × 4 instances × 5 days × 6 sessions × 140 rooms)

DATA DEPENDENCIES:
    ├─ self.lab_requirements: Knows which teacher-instance pairs exist
    ├─ self.num_days: Iteration bounds
    ├─ self.lab_sessions: Available sessions
    └─ self.lab_room_ids: Available rooms
```

### Theory Variables (line 2569-2605)

```
_create_group_timeslot_variables(model)
    ↓
STRUCTURE: group_timeslot_vars[group_id][day][slot]

For each group in self.groups:
    For each day (0 to 4):
        For each theory_slot (0 to 10):
            var_name = f"group_{group_id}_{day}_{slot}"
            group_timeslot_vars[group_id][day][slot] = model.NewBoolVar(var_name)

EXAMPLE VARIABLE:
    group_timeslot_vars["CSE_S3_G1"][0][2] = BoolVar_56789
    Meaning: "Group CSE_S3_G1 has a class on Monday at theory slot 2"

TOTAL VARIABLES: ~2,800 BoolVars
    (50 groups × 5 days × 11 slots)

DATA DEPENDENCIES:
    ├─ self.groups: All group IDs
    ├─ self.num_days: Iteration bounds
    └─ self.num_theory_slots: Available slots
```

---

## 5. CONSTRAINT APPLICATION (Rules Layer)

### LAB CONSTRAINTS (Uses lab_variables)

#### 5.1 Course Lab Requirements (line 2680-2956) - PRIORITY 10

```
apply_course_lab_requirements_constraint(model, lab_variables)

DATA USED:
    ├─ self.lab_requirements[teacher_id]
    │   └─ For each instance: required sessions count
    ├─ lab_variables[teacher][instance][day][session][room]
    └─ self.lab_sessions (session names)

LOGIC:
    For each teacher:
        For each course_instance:
            required_sessions = requirement['sessions']
            
            # Sum all variables for this instance across all dimensions
            total_scheduled = sum(
                lab_variables[teacher][instance][day][session][room]
                for day in days
                for session in lab_sessions
                for room in lab_rooms
            )
            
            # HARD CONSTRAINT: Must equal required sessions
            model.Add(total_scheduled == required_sessions)

EXAMPLE:
    CSE_S3_1001 needs 2 sessions
    → Must schedule exactly 2 times across week
    → sum(all lab_variables for CSE_S3_1001) == 2

DATA FLOW:
    lab_requirements["T001"] → "sessions": 2 → Constraint: sum(...) == 2
```

#### 5.2 Lab Room Single Assignment (line 3074-3192) - PRIORITY 9

```
apply_lab_room_single_assignment_constraint(model, lab_variables)

DATA USED:
    ├─ lab_variables[teacher][instance][day][session][room]
    ├─ self.lab_requirements (to iterate teachers/instances)
    ├─ self.num_days
    └─ self.lab_sessions

LOGIC:
    For each (day, session, room):
        # Only ONE teacher-instance can use this room at this time
        occupants = [
            lab_variables[teacher][instance][day][session][room]
            for teacher in teachers
            for instance in teacher_instances
            if variable exists
        ]
        
        model.Add(sum(occupants) <= 1)

EXAMPLE:
    LAB201 on Monday session L1:
    → Only one of [T001's CSE_S3_1001, T002's ME_S3_2001, ...] can be true

DATA FLOW:
    lab_variables → Filter by (day, session, room) → Sum ≤ 1
```

#### 5.3 Core Lab Mapping (line 3540-3657) - PRIORITY 9

```
apply_core_lab_mapping_constraint(model, lab_variables)

DATA USED:
    ├─ self.core_lab_mapping[group_id] = [allowed_rooms]
    ├─ self.instance_group_mapping[instance_id]["group"]
    ├─ lab_variables[teacher][instance][day][session][room]
    └─ self.laboratory_room_ids (core lab rooms)

LOGIC:
    For each instance:
        group_id = instance_group_mapping[instance]["group"]
        
        # If this group has core lab restrictions:
        if group_id in core_lab_mapping:
            allowed_rooms = core_lab_mapping[group_id]
            
            For each (day, session):
                For each room NOT in allowed_rooms:
                    # Force this variable to be FALSE
                    model.Add(lab_variables[teacher][instance][day][session][room] == 0)

EXAMPLE:
    CSE_S3_G1 can only use LAB201, LAB202
    → All lab_variables for CSE_S3_G1 instances in other rooms = 0
    → lab_variables["T001"]["CSE_S3_1001"][any_day][any_session]["LAB301"] = 0

DATA FLOW:
    instance_id → instance_group_mapping → group_id → core_lab_mapping → allowed_rooms → Filter variables
```

#### 5.4 Shift-Based Lab Constraint (line 8765-8930) - PRIORITY 7

```
apply_shift_based_lab_constraint(model, lab_variables)

DATA USED:
    ├─ self.shift_departments[dept]["lab_sessions"] = ["L1", "L2", "L3"]
    ├─ self.lab_requirements[teacher][instance]["dept"]
    ├─ self.department_day_patterns[dept]["shift_pattern_by_day"][day_idx]
    └─ lab_variables[teacher][instance][day][session][room]

LOGIC:
    For departments with shifts (8am-3pm or 10am-5pm):
        For each instance in that department:
            For each day:
                shift = get_department_shift_for_day(dept, day)
                allowed_sessions = get_shift_lab_sessions(shift)
                
                For each session NOT in allowed_sessions:
                    # Force all variables for this session to 0
                    model.Add(sum(
                        lab_variables[teacher][instance][day][session][room]
                        for room in lab_rooms
                    ) == 0)

EXAMPLE:
    CSE has morning shift (8am-3pm) on Monday
    → Allowed sessions: L1, L2, L3
    → All CSE labs on Monday must use L1/L2/L3
    → L4, L5, L6 forced to 0

DATA FLOW:
    dept → shift_departments → allowed_sessions → Filter sessions → Force variables = 0
```

#### 5.5 Lab Lunch Break (line 8524-8611) - PRIORITY 6

```
_apply_lab_lunch_break_constraint(model, lab_variables)

DATA USED:
    ├─ self.lunch_break_slots[dept] = slot_index (e.g., 4)
    ├─ self.lab_to_theory_slot_mapping[session] = [slot_range]
    ├─ self.instance_group_mapping[instance]["dept"]
    └─ lab_variables[teacher][instance][day][session][room]

LOGIC:
    For each department with fixed lunch:
        lunch_slot = lunch_break_slots[dept]
        
        For each lab session:
            theory_slots_covered = lab_to_theory_slot_mapping[session]
            
            # If this lab session overlaps lunch slot:
            if lunch_slot in theory_slots_covered:
                For each instance in that department:
                    # Forbid scheduling during lunch-overlapping sessions
                    model.Add(sum(
                        lab_variables[teacher][instance][day][session][room]
                        for day, room in day_room_combos
                    ) == 0)

EXAMPLE:
    CSE lunch = theory slot 4 (11:40-12:30)
    Lab session L3 = slots [4,5] → Overlaps lunch
    → All CSE labs cannot use L3
    → lab_variables[any_teacher][CSE_instance][any_day]["L3"][any_room] = 0

DATA FLOW:
    dept → lunch_break_slots → slot_index → lab_to_theory_slot_mapping → overlapping_sessions → Filter variables
```

---

### THEORY CONSTRAINTS (Uses group_timeslot_vars)

#### 5.6 Group-Based Scheduling (line 3427-3537) - PRIORITY 10

```
apply_group_based_scheduling_constraint(model, lab_variables)

DATA USED:
    ├─ self.groups[dept][semester] = [group_list]
    ├─ self.group_requirements[group_id] = theory_hours_needed
    └─ group_timeslot_vars[group_id][day][slot]

LOGIC:
    For each group:
        required_hours = group_requirements[group_id]
        
        # Sum all scheduled slots for this group
        total_scheduled = sum(
            group_timeslot_vars[group_id][day][slot]
            for day in days
            for slot in theory_slots
        )
        
        # HARD CONSTRAINT: Must equal required hours
        model.Add(total_scheduled == required_hours)

EXAMPLE:
    CSE_S3_G1 needs 8 theory hours
    → Must schedule exactly 8 slots across week
    → sum(group_timeslot_vars["CSE_S3_G1"][all days][all slots]) == 8

DATA FLOW:
    group_id → group_requirements → required_hours → Constraint: sum(...) == required_hours
```

#### 5.7 Proper Theory Room Capacity (line 4462-4728) - PRIORITY 9

```
_apply_proper_theory_room_capacity_constraint(model, group_timeslot_vars)

DATA USED:
    ├─ self.groups[dept][semester][group]["students"]
    ├─ self.theory_rooms (with capacity info)
    ├─ group_timeslot_vars[group_id][day][slot]
    └─ self.theory_room_ids

LOGIC:
    For each group:
        student_count = groups[...][group]["students"]
        
        For each (day, slot):
            For each room:
                # If group is scheduled at (day, slot):
                # Then room capacity must be sufficient
                
                if room.capacity < student_count:
                    # This room cannot be used
                    # (Implemented via room selection in extraction phase)
                    pass
                else:
                    # Room is eligible
                    pass

EXAMPLE:
    CSE_S3_G1 has 75 students
    → Can only use theory rooms with capacity ≥ 75
    → Filters room choices during schedule extraction

DATA FLOW:
    group → student_count → theory_rooms → filter by capacity → eligible rooms
```

#### 5.8 Daily Theory Slot Limit (line 4849-4951) - PRIORITY 6

```
_apply_daily_theory_slot_limit_constraint(model, group_timeslot_vars)

DATA USED:
    ├─ group_timeslot_vars[group_id][day][slot]
    ├─ self.groups (to iterate groups)
    └─ max_slots_per_day = 3 (hardcoded limit)

LOGIC:
    For each group:
        For each day:
            daily_slots = sum(
                group_timeslot_vars[group_id][day][slot]
                for slot in theory_slots
            )
            
            # Limit slots per day
            model.Add(daily_slots <= max_slots_per_day)

EXAMPLE:
    CSE_S3_G1 on Monday:
    → Can have maximum 3 theory slots on Monday
    → sum(group_timeslot_vars["CSE_S3_G1"][0][all slots]) ≤ 3

DATA FLOW:
    group_id → Filter by day → Sum slots → Limit ≤ 3
```

#### 5.9 No Three Consecutive Slots (line 4087-4133) - PRIORITY 5

```
_apply_no_three_consecutive_slots_constraint(model, group_timeslot_vars)

DATA USED:
    ├─ group_timeslot_vars[group_id][day][slot]
    └─ self.num_theory_slots (to iterate consecutive triples)

LOGIC:
    For each group:
        For each day:
            For each consecutive triple (slot, slot+1, slot+2):
                # At most 2 of 3 can be scheduled
                model.Add(
                    group_timeslot_vars[group_id][day][slot] +
                    group_timeslot_vars[group_id][day][slot+1] +
                    group_timeslot_vars[group_id][day][slot+2]
                    <= 2
                )

EXAMPLE:
    CSE_S3_G1 on Monday, slots 2-3-4:
    → Can schedule 2 out of 3 (e.g., slots 2 and 4)
    → Cannot schedule all 3 consecutive slots

DATA FLOW:
    group_id, day → Sliding window of 3 slots → Sum ≤ 2
```

#### 5.10 Teacher Daily Presence (line 4731-4846) - PRIORITY 7

```
apply_teacher_daily_presence_constraint(model, group_timeslot_vars)

DATA USED:
    ├─ self.groups[dept][semester][group]["teachers"]
    ├─ group_timeslot_vars[group_id][day][slot]
    └─ teacher_group_mapping (reverse lookup: teacher → groups)

LOGIC:
    For each teacher:
        groups_taught = [groups where teacher teaches]
        
        For each day:
            # If teacher teaches on this day, must teach ≥2 slots
            teacher_present = model.NewBoolVar(f"teacher_{teacher}_present_{day}")
            
            total_slots = sum(
                group_timeslot_vars[group_id][day][slot]
                for group_id in groups_taught
                for slot in theory_slots
            )
            
            # If present, at least 2 slots
            model.Add(total_slots >= 2).OnlyEnforceIf(teacher_present)
            model.Add(total_slots == 0).OnlyEnforceIf(teacher_present.Not())

EXAMPLE:
    Teacher T001 teaches CSE_S3_G1 and CSE_S3_G2
    If T001 comes on Monday → Must teach ≥2 slots total
    Otherwise → Don't schedule T001 on Monday at all

DATA FLOW:
    teacher → groups_taught → Sum slots per day → Presence indicator → Constraint ≥ 2
```

#### 5.11 Shift-Based Theory (line 9059-9161) - PRIORITY 7

```
apply_shift_based_theory_constraint(model, group_timeslot_vars)

DATA USED:
    ├─ self.shift_departments[dept]["theory_slots"] = [0,1,2,3,4,5]
    ├─ self.groups[dept][semester]
    ├─ self.department_day_patterns[dept]["shift_pattern_by_day"][day_idx]
    └─ group_timeslot_vars[group_id][day][slot]

LOGIC:
    For departments with shifts:
        For each group in that department:
            For each day:
                shift = get_department_shift_for_day(dept, day)
                allowed_slots = get_shift_theory_slots(shift)
                
                For each slot NOT in allowed_slots:
                    # Force this slot to 0
                    model.Add(group_timeslot_vars[group_id][day][slot] == 0)

EXAMPLE:
    CSE has morning shift (8am-3pm) on Monday
    → Allowed theory slots: 0-5
    → Slots 6-10 forced to 0 for CSE groups

DATA FLOW:
    dept → shift_departments → allowed_slots → Filter slots → Force variables = 0
```

#### 5.12 Theory Lunch Break (line 8284-8336) - PRIORITY 6

```
_apply_lunch_break_constraint(model, group_timeslot_vars)

DATA USED:
    ├─ self.lunch_break_slots[dept] = slot_index
    ├─ self.groups[dept][semester]
    └─ group_timeslot_vars[group_id][day][slot]

LOGIC:
    For departments with fixed lunch:
        lunch_slot = lunch_break_slots[dept]
        
        For each group in that department:
            For each day:
                # Forbid scheduling during lunch
                model.Add(group_timeslot_vars[group_id][day][lunch_slot] == 0)

EXAMPLE:
    CSE lunch = slot 4
    → All CSE groups cannot have theory at slot 4
    → group_timeslot_vars["CSE_S3_G1"][any_day][4] = 0

DATA FLOW:
    dept → lunch_break_slots → slot_index → Force variable = 0
```

---

### CROSS-SYSTEM CONSTRAINTS (Uses BOTH lab_variables AND group_timeslot_vars)

#### 5.13 Unified Teacher Clash (line 5220-5418) - PRIORITY 10

```
_apply_unified_teacher_clash_constraint(model, lab_variables, group_timeslot_vars)

DATA USED:
    ├─ self.lab_requirements[teacher_id] (lab teaching)
    ├─ self.groups[dept][semester][group]["teachers"] (theory teaching)
    ├─ self.lab_to_theory_slot_mapping[session] = [slot_range]
    ├─ lab_variables[teacher][instance][day][session][room]
    └─ group_timeslot_vars[group_id][day][slot]

LOGIC:
    For each teacher:
        For each day:
            For each time unit (theory slot or lab session):
                
                # THEORY CONTRIBUTION
                theory_classes = sum(
                    group_timeslot_vars[group_id][day][slot]
                    for group_id in groups_taught_by_teacher
                )
                
                # LAB CONTRIBUTION (mapped to same time)
                lab_classes = sum(
                    lab_variables[teacher][instance][day][session][room]
                    for instance in teacher_lab_instances
                    for session in sessions_overlapping_this_slot
                    for room in lab_rooms
                )
                
                # COMBINED CONSTRAINT: At most 1 at this time
                model.Add(theory_classes + lab_classes <= 1)

EXAMPLE:
    Teacher T001 on Monday at theory slot 2:
    
    Theory: T001 teaches CSE_S3_G1
    → theory_term = group_timeslot_vars["CSE_S3_G1"][0][2]
    
    Lab: T001's lab session L2 overlaps slot 2
    → lab_term = sum(lab_variables["T001"][any_instance][0]["L2"][any_room])
    
    Constraint: theory_term + lab_term ≤ 1
    (T001 cannot do both theory and lab at same time)

DATA FLOW:
    teacher → groups_taught + lab_instances → Map time → Sum both → ≤ 1
```

#### 5.14 Department-Semester Group Conflict (line 5098-5217) - PRIORITY 9

```
_apply_dept_semester_group_conflict_constraint(model, lab_variables, group_timeslot_vars)

DATA USED:
    ├─ self.groups[dept][semester] = [group_list]
    ├─ self.instance_group_mapping[instance]["dept"], ["semester"]
    ├─ self.lab_to_theory_slot_mapping[session] = [slot_range]
    ├─ lab_variables[teacher][instance][day][session][room]
    └─ group_timeslot_vars[group_id][day][slot]

LOGIC:
    For each (department, semester) pair:
        groups = groups[dept][semester]
        
        For each day:
            For each theory slot:
                # THEORY: Only 1 group can be scheduled
                theory_scheduled = sum(
                    group_timeslot_vars[group_id][day][slot]
                    for group_id in groups
                )
                model.Add(theory_scheduled <= 1)
                
                # LAB: Any lab for this dept/sem at overlapping time
                # also counts as occupying this slot
                lab_scheduled = sum(
                    lab_variables[teacher][instance][day][session][room]
                    for instance in dept_sem_instances
                    for session in sessions_overlapping_this_slot
                    for teacher, room in valid_combos
                )
                
                # COMBINED: Theory + Lab ≤ 1 for this cohort
                model.Add(theory_scheduled + lab_scheduled <= 1)

EXAMPLE:
    CSE Semester 3 on Monday slot 2:
    
    Theory: CSE_S3_G1 at slot 2
    → theory_term = group_timeslot_vars["CSE_S3_G1"][0][2]
    
    Lab: CSE_S3 lab session overlapping slot 2
    → lab_term = sum(lab_variables for CSE S3 instances at matching time)
    
    Constraint: theory_term + lab_term ≤ 1
    (CSE S3 students cannot have both theory and lab at same time)

DATA FLOW:
    (dept, sem) → groups + instances → Map time → Sum theory + lab → ≤ 1
```

---

## 6. DATA FLOW SUMMARY BY CONSTRAINT

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          CONSTRAINT DATA DEPENDENCY MAP                         │
└─────────────────────────────────────────────────────────────────────────────────┘

LAB CONSTRAINTS:
├─ Course Lab Requirements
│  └─ Uses: lab_requirements[teacher] → sessions
│
├─ Lab Room Single Assignment
│  └─ Uses: lab_variables → (day, session, room) index
│
├─ Core Lab Mapping
│  └─ Uses: core_lab_mapping[group] + instance_group_mapping → allowed rooms
│
├─ Shift-Based Lab
│  └─ Uses: shift_departments → lab_sessions + department_day_patterns
│
└─ Lab Lunch Break
   └─ Uses: lunch_break_slots + lab_to_theory_slot_mapping → overlapping sessions

THEORY CONSTRAINTS:
├─ Group-Based Scheduling
│  └─ Uses: group_requirements[group] → theory_hours
│
├─ Proper Theory Room Capacity
│  └─ Uses: groups[dept][sem][group]["students"] + theory_rooms → capacity match
│
├─ Daily Theory Slot Limit
│  └─ Uses: group_timeslot_vars → (group, day) aggregation
│
├─ No Three Consecutive
│  └─ Uses: group_timeslot_vars → sliding window of slots
│
├─ Teacher Daily Presence
│  └─ Uses: groups[...]["teachers"] → reverse mapping to groups
│
├─ Shift-Based Theory
│  └─ Uses: shift_departments → theory_slots + department_day_patterns
│
└─ Theory Lunch Break
   └─ Uses: lunch_break_slots[dept] → slot_index

CROSS-SYSTEM CONSTRAINTS:
├─ Unified Teacher Clash
│  └─ Uses: lab_requirements + groups["teachers"] + lab_to_theory_slot_mapping
│
└─ Dept-Sem Group Conflict
   └─ Uses: groups[dept][sem] + instance_group_mapping + lab_to_theory_slot_mapping
```

---

## 7. COMPLETE DATA FLOW DIAGRAM

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           DATA FLOW FROM CSV TO CONSTRAINTS                     │
└─────────────────────────────────────────────────────────────────────────────────┘

courses.csv ────────┐
techlongue.csv ─────┤
day_order.csv ──────┼──→ LOAD & PARSE ──→ DataFrames (self.courses_df, self.rooms_df)
core_lab_map.csv ───┤                         │
pop.csv ────────────┘                         │
                                              ↓
                                    PROCESS & CONFIGURE
                                    ├─ Department day patterns
                                    ├─ Lunch break slots
                                    ├─ Shift configurations
                                    ├─ Time system setup
                                    └─ 5pm constraints
                                              │
                                              ↓
                        ┌─────────────────────────────────────────┐
                        │         CREATE COURSE GROUPS             │
                        │  (The Core Transformation)               │
                        └─────────────────────────────────────────┘
                                              │
                ┌─────────────────────────────┴─────────────────────────────┐
                │                                                           │
                ↓                                                           ↓
        THEORY-CENTRIC                                            LAB-CENTRIC
    (Group-based scheduling)                               (Instance-based scheduling)
                │                                                           │
                ├─ groups[dept][semester]                                   ├─ lab_requirements[teacher]
                ├─ group_requirements[group_id]                             ├─ instance_group_mapping
                └─ instance_group_mapping                                   └─ core_lab_mapping
                │                                                           │
                ↓                                                           ↓
    CREATE THEORY VARIABLES                                  CREATE LAB VARIABLES
    group_timeslot_vars[group][day][slot]        lab_variables[teacher][instance][day][session][room]
                │                                                           │
                ↓                                                           ↓
        THEORY CONSTRAINTS                                          LAB CONSTRAINTS
        ├─ Group requirements              ←─────┐                 ├─ Session requirements
        ├─ Room capacity                        │                  ├─ Room single assignment
        ├─ Daily limits                         │                  ├─ Core lab mapping
        ├─ No 3 consecutive                     │                  ├─ Shift-based
        ├─ Teacher presence                     │                  └─ Lab lunch break
        ├─ Shift-based                          │
        └─ Theory lunch break                   │
                │                               │
                └───────────────┬───────────────┘
                                │
                                ↓
                    CROSS-SYSTEM CONSTRAINTS
                    ├─ Unified teacher clash
                    │  (Uses: lab_to_theory_slot_mapping)
                    └─ Dept-sem group conflict
                       (Uses: lab_to_theory_slot_mapping)
                                │
                                ↓
                        SOLVER (CP-SAT)
                                │
                                ↓
                        EXTRACT SCHEDULES
                        ├─ Lab schedule
                        ├─ Theory schedule
                        └─ Combined schedule
```

---

## 8. KEY DATA STRUCTURES - QUICK REFERENCE

```
PRIMARY DATA STRUCTURES (in order of creation):

1. courses_df (Loaded from CSV)
   └─ Raw course data

2. rooms_df (Loaded from CSV)
   └─ Raw room data with capacity, type, location

3. groups (Created by CourseGroupOptimizer)
   └─ groups[dept][semester] = [group_list]
   └─ Each group contains: group_id, instances, students, teachers

4. instance_group_mapping (Derived from groups)
   └─ instance_group_mapping[instance_id] = {group, dept, sem, students}

5. group_requirements (Computed from groups)
   └─ group_requirements[group_id] = theory_hours_needed

6. lab_requirements (Extracted from courses)
   └─ lab_requirements[teacher_id] = [{course, sessions, hours, students}]

7. core_lab_mapping (Loaded from CSV)
   └─ core_lab_mapping[group_id] = [allowed_room_ids]

8. department_day_patterns (Configured from day_order.csv)
   └─ department_day_patterns[dept] = {default: [days], overrides: {...}}

9. lunch_break_slots (Configured)
   └─ lunch_break_slots[dept] = slot_index

10. shift_departments (Configured)
    └─ shift_departments[dept] = {theory_slots, lab_sessions, pattern}

11. lab_to_theory_slot_mapping (Computed)
    └─ lab_to_theory_slot_mapping[session] = [overlapping_slot_indices]

12. lab_variables (Created from lab_requirements)
    └─ lab_variables[teacher][instance][day][session][room] = BoolVar

13. group_timeslot_vars (Created from groups)
    └─ group_timeslot_vars[group][day][slot] = BoolVar
```

---

## 9. CONSTRAINT PRIORITY LAYERS

```
PRIORITY 10 (MUST SATISFY - Hard Requirements):
├─ Course Lab Requirements: Uses lab_requirements
├─ Group-Based Scheduling: Uses group_requirements
└─ Unified Teacher Clash: Uses lab_requirements + groups["teachers"] + mapping

PRIORITY 9 (CRITICAL - Resource Allocation):
├─ Lab Room Single Assignment: Uses lab_variables indexing
├─ Core Lab Mapping: Uses core_lab_mapping + instance_group_mapping
├─ Proper Theory Room Capacity: Uses groups["students"] + theory_rooms
└─ Dept-Sem Group Conflict: Uses groups + instance_group_mapping + mapping

PRIORITY 7 (IMPORTANT - Structural Constraints):
├─ Shift-Based Lab: Uses shift_departments + department_day_patterns
├─ Shift-Based Theory: Uses shift_departments + department_day_patterns
└─ Teacher Daily Presence: Uses groups["teachers"]

PRIORITY 6 (COMFORT - Quality Improvements):
├─ Daily Theory Slot Limit: Uses group_timeslot_vars aggregation
├─ Lab Lunch Break: Uses lunch_break_slots + mapping
└─ Theory Lunch Break: Uses lunch_break_slots

PRIORITY 5 (PREFERENCE - Nice-to-have):
└─ No Three Consecutive: Uses group_timeslot_vars sliding window
```

---

## 10. VISUAL CONSTRAINT DEPENDENCY GRAPH

```
                    ┌──────────────┐
                    │  COURSES.CSV │
                    └──────┬───────┘
                           │
        ┌──────────────────┴────────────────────┐
        │                                       │
        ↓                                       ↓
┌─────────────────┐                    ┌─────────────────┐
│  CREATE GROUPS  │                    │ EXTRACT LAB REQ │
│                 │                    │                 │
│ (dept/sem based)│                    │ (teacher-based) │
└────────┬────────┘                    └────────┬────────┘
         │                                      │
         ├─→ groups                             ├─→ lab_requirements
         ├─→ group_requirements                 │
         └─→ instance_group_mapping             │
         │                                      │
         └──────────────┬───────────────────────┘
                        │
        ┌───────────────┴────────────────┐
        │                                │
        ↓                                ↓
┌─────────────────┐            ┌─────────────────┐
│ THEORY VARS     │            │  LAB VARS       │
│                 │            │                 │
│ [group][d][s]   │            │ [t][i][d][s][r] │
└────────┬────────┘            └────────┬────────┘
         │                               │
         │    ┌──────────────────────────┤
         │    │                          │
         ↓    ↓                          ↓
    ┌────────────┐              ┌───────────────┐
    │  THEORY    │              │  LAB          │
    │ CONSTRAINTS│              │  CONSTRAINTS  │
    └────────┬───┘              └───────┬───────┘
             │                          │
             │   ┌──────────────────────┘
             │   │
             ↓   ↓
        ┌──────────────┐
        │ CROSS-SYSTEM │
        │ CONSTRAINTS  │
        │              │
        │ Uses mapping │
        │ between      │
        │ lab & theory │
        └──────┬───────┘
               │
               ↓
        ┌─────────────┐
        │   SOLVER    │
        └─────────────┘
```

This mindmap shows the complete data journey from CSV files through group formation to constraint application, with explicit data dependencies for each constraint!
