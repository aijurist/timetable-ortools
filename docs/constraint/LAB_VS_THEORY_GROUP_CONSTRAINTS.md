# Lab Groups vs Theory Groups: Constraint Handling

## Executive Summary

The timetable scheduler handles **Lab Groups** and **Theory Groups** completely differently with distinct constraints, variables, and scheduling strategies:

| Aspect | Lab Groups | Theory Groups |
|--------|-----------|---------------|
| **Variable Type** | Binary variables per (teacher, course, day, session, **room**) | Binary variables per (group, day, **timeslot**) |
| **Variables Structure** | `lab_assignments[T][C][D][S][R]` | `group_timeslot_vars[G][D][S]` |
| **Room Assignment** | Explicit in search space | Not modeled (post-processed) |
| **Constraint Focus** | Room conflicts, capacity, specialization | Timeslot allocation, group non-overlap |
| **Key Constraint** | Group-based scheduling (same-semester groups don't overlap) | Theory group non-overlap per timeslot |
| **Daily Sessions** | Max 6 sessions per day (L1-L6) | Max 11 slots per day (11 theory timeslots) |
| **Primary Constraints** | 15 lab-specific | 11 theory-specific |

---

## Part 1: Lab Groups - Constraint Details

### What are Lab Groups?

Lab groups are **collections of students taking the same course in a lab session** at the same time. A course might be split into multiple lab sessions (L1, L2, ..., L6) if it has high demand.

```
Example: Data Structures Lab (DSA Lab)
├─ Lab Session L1: 35 students → Group 1
├─ Lab Session L2: 35 students → Group 2
├─ Lab Session L3: 30 students → Group 3
└─ Lab Session L4: 25 students → Group 4

All 4 groups belong to same course but different students
Need separate rooms and teacher assignments
```

### Key Lab Group Constraint: `apply_group_based_scheduling_constraint()` (Lines 3426-3560)

**Purpose**: Ensure same-semester groups from same department don't conflict on the same day-session

```python
def apply_group_based_scheduling_constraint(self, model, lab_variables):
    """
    CONSTRAINT 1: Same-semester group non-overlap
    CONSTRAINT 2: Course instance uniqueness
    """
    
    # Group course instances by department, semester, and group
    semester_groups = defaultdict(lambda: defaultdict(list))
    
    for teacher_id in lab_variables:
        for course_instance_id in lab_variables[teacher_id]:
            # Get group info for this course instance
            group_mapping = self.instance_group_mapping[course_instance_id]
            dept = group_mapping['department']
            semester = group_mapping['semester']
            group_index = group_mapping['group_index']
            
            if group_index > 0:  # Valid group
                semester_groups[(dept, semester)][group_index].append(course_instance_id)
```

### CONSTRAINT 1: Same-Semester Group Non-Overlap (Lines 3445-3485)

```python
# For each time slot (day, session), ensure at most ONE group 
# from same department-semester is active

FOR (dept, semester), groups IN semester_groups:
    FOR day_idx IN range(num_dept_days):
        FOR session_name IN lab_sessions:
            group_usages = {}  # Track if each group uses this slot
            
            FOR group_idx, course_instances IN groups:
                group_usage_vars = []
                
                FOR course_instance_id IN course_instances:
                    FOR room_id IN lab_room_ids:
                        group_usage_vars.append(
                            lab_assignments[T][course_id][day_idx][session][room]
                        )
                
                # Create boolean: "Does this group use this time slot?"
                group_usage = NewBoolVar()
                group_usages[group_idx] = group_usage
            
            # HARD CONSTRAINT: At most 1 group per time slot
            IF len(group_usages) > 1:
                ADD_CONSTRAINT: sum(group_usages.values()) <= 1
```

**Example Enforcement**:
```
Monday L1 Session:
├─ CSE Dept, Semester 3
│  ├─ Group 1: Can use this slot
│  ├─ Group 2: CANNOT use this slot (same time as Group 1)
│  └─ Group 3: CANNOT use this slot (same time as Group 1)
└─ Result: Only 1 of the 3 groups scheduled at this time

Tuesday L1 Session:
├─ CSE Dept, Semester 3
│  ├─ Group 1: Still scheduled Monday, available here
│  ├─ Group 2: Can use this slot (different from Group 1's Tuesday schedule)
│  └─ Group 3: CANNOT use (Group 2 already using)
```

### CONSTRAINT 2: Course Instance Uniqueness (Lines 3488-3535)

```python
# For EACH course instance, max 1 room per session

FOR teacher_id IN lab_variables:
    FOR course_instance_id IN lab_variables[teacher_id]:
        FOR day_idx IN range(num_dept_days):
            FOR session_name IN lab_sessions:
                session_assignments = []
                
                FOR room_id IN lab_room_ids:
                    session_assignments.append(
                        lab_assignments[T][C][day][session][room]
                    )
                
                # Cannot be assigned to multiple rooms same session
                IF len(session_assignments) > 1:
                    ADD_CONSTRAINT: sum(session_assignments) <= 1
                    # At most 1 room per session
```

**Why Both Constraints?**

1. **Constraint 1** (Group Non-Overlap): Prevents **two different courses from same group** using same slot
   - Example: DSA Group 1 and Database Group 1 can't both use Monday L1
   
2. **Constraint 2** (Instance Uniqueness): Prevents **same course** from using multiple rooms same session
   - Example: DSA Group 1 can't use both Room 5 and Room 10 on Monday L1

---

## Part 2: Theory Groups - Constraint Details

### What are Theory Groups?

Theory groups are **collections of students taking lecture/tutorial together** (not split by room). All students in a theory group attend same lectures/tutorials at same times.

```
Example: Data Structures Theory (DSA Theory)
Department: Computer Science & Engineering
Semester: 3

Groups by size:
├─ Group 1: 140 students
│   ├─ Lecture: 3 hours per week
│   └─ Tutorial: 1 hour per week
│       Total: 4 timeslots needed per week

├─ Group 2: 135 students  
│   ├─ Lecture: 3 hours per week
│   └─ Tutorial: 1 hour per week
│       Total: 4 timeslots needed per week

├─ Group 3: 130 students
│   ├─ Lecture: 3 hours per week
│   └─ Tutorial: 1 hour per week
│       Total: 4 timeslots needed per week

All 3 groups share same content but scheduled SEPARATELY
Each group gets 4 timeslots (not rooms) during the week
```

### Key Theory Group Constraint: Theory Group Non-Overlap per Timeslot (Lines 4000-4045)

**File Location**: Lines 4000-4050 in `_apply_theory_constraints()`

```python
def _apply_theory_constraints(self, model, group_timeslot_vars):
    """
    Orchestrates 11 theory-specific constraints
    """
    constraints_applied = 0
    
    # CONSTRAINT 2: Theory group non-overlap per timeslot
    # Group courses by department and semester
    
    for (dept, semester), groups IN self.course_groups:
        # For EACH time slot in theory schedule
        FOR day_idx IN range(num_dept_days):
            FOR slot_idx IN range(num_theory_slots):  # 11 slots (9AM-5:30PM)
                slot_usage_vars = []
                
                FOR group_name IN groups:
                    IF (group_name in group_timeslot_vars AND
                        day_idx in group_timeslot_vars[group_name] AND
                        slot_idx in group_timeslot_vars[group_name][day_idx]):
                        
                        slot_usage_vars.append(
                            group_timeslot_vars[group_name][day_idx][slot_idx]
                        )
                
                # At most 1 group per timeslot
                IF len(slot_usage_vars) > 1:
                    ADD_CONSTRAINT: sum(slot_usage_vars) <= 1
                    constraints_applied += 1
```

**What This Means**:
```
Monday 9:00 AM - 9:50 AM (Slot 0):
├─ Theory Group CSE S3 G1: Can use this slot
├─ Theory Group CSE S3 G2: CANNOT use (Group 1 already using)
└─ Theory Group CSE S3 G3: CANNOT use (Group 1 already using)

Tuesday 9:00 AM - 9:50 AM (Slot 0):
├─ Theory Group CSE S3 G1: Already used Mon slot 0, available here
├─ Theory Group CSE S3 G2: Can use (different from Monday)
└─ Theory Group CSE S3 G3: CANNOT use (Group 2 using this slot)
```

### Critical Difference: MULTIPLE CONSTRAINTS INVOLVED

Unlike Lab Groups which use ONE main constraint, Theory Groups use **MULTIPLE** coordinated constraints:

```
Theory Group Constraints (Lines 3990-5290):

1. ✅ CONSTRAINT 2: Theory group non-overlap per timeslot (Lines 4000-4045)
   Purpose: Different groups don't use same timeslot
   Example: Group 1 & Group 2 can't both use Monday 9AM

2. ✅ CONSTRAINT 3: Proper theory room capacity (Lines 4322-4600)
   Purpose: Enough rooms available for concurrent groups
   Example: If 2 groups need timeslot, need ≥2 theory rooms

3. ✅ CONSTRAINT 4: No 3 consecutive slots (Lines 4103-4150)
   Purpose: Groups don't get 3 consecutive hours same day
   Example: Can't schedule Group 1 at 9AM, 9:50AM, 10:40AM

4. ✅ CONSTRAINT 5: Lunch break (Lines 4153-4200)
   Purpose: Respect lunch breaks
   Example: CSE doesn't schedule theory during 12:30-1:30PM

5. ✅ CONSTRAINT 6: Shift constraints (Lines 4203-4250)
   Purpose: Respect shift times (morning vs evening)
   Example: Evening depts can't schedule before 10AM

6. ✅ CONSTRAINT 7: Early scheduling (Lines 4113-4170)
   Purpose: Prefer scheduling before 3:00 PM
   Example: Late slots get penalty in objective

7. ✅ CONSTRAINT 8: 140-capacity room reservation (Lines 4217-4280)
   Purpose: Reserve 140-cap rooms for 140-student groups
   Example: Group with 140 students blocked from small slots

8. ✅ CONSTRAINT 9: Daily session limit (Lines 4283-4450)
   Purpose: Max 2 sessions per course per day (pop.csv teachers get 4)
   Example: DSA can't have 3 lectures same day

9. ✅ CONSTRAINT 10: Teacher daily presence (Lines 4453-4550)
   Purpose: Prevent 11+ hour violation days
   Example: Teacher can't teach 9AM and then 5PM same day

10. ✅ CONSTRAINT 11: Daily slot limit (Lines 5153-5290)
    Purpose: Max 5-6 slots per day (core vs non-core depts)
    Example: Core depts get 6 slots max, others get 5

Total: 10+ coordinated constraints for theory groups
```

---

## Part 3: Key Differences Summary

### Lab Groups
```
VARIABLES:
  lab_assignments[teacher][course][day][session][ROOM]
  ↑ Room explicitly in search space
  
CONSTRAINT LOGIC:
  IF lab_assignments[T1][C1][Monday][L1][Room5] = 1
  THEN lab_assignments[T2][C2][Monday][L1][Room5] = 0 (same room blocked)
  AND other_groups_at_monday_L1 must be 0 (unless co-scheduled)
  
ROOMS ASSIGNED:
  ✅ DIRECTLY in constraint satisfaction
  ✅ Room conflicts immediately detected
  ✅ Capacity checked during solving
  
RESULT:
  ✅ Final schedule includes specific room assignments
  ✅ No room conflicts possible
  ✅ Rooms optimized for capacity match
```

### Theory Groups
```
VARIABLES:
  group_timeslot_vars[group][day][SLOT]
  ↑ Only timeslot, NOT room
  
CONSTRAINT LOGIC:
  IF group_timeslot_vars[CSE_S3_G1][Monday][Slot0] = 1
  THEN group_timeslot_vars[CSE_S3_G2][Monday][Slot0] = 0 (same slot blocked)
  AND must have sufficient theory_rooms available
  
ROOMS ASSIGNED:
  ⏳ POST-SOLVED (not in search space)
  ⏳ Assigned after solution found
  ⏳ Simpler room capacity calculation
  
RESULT:
  ⏳ Final schedule includes timeslots + groups
  ⏳ Rooms assigned post-hoc (avoiding complex search)
  ⏳ Simpler optimization problem
```

### Constraint Type Comparison

| Constraint Type | Lab Groups | Theory Groups |
|-----------------|-----------|---------------|
| **Room Conflicts** | HARD constraint in solver | Post-processing only |
| **Group Non-Overlap** | Via `group_usage_vars` | Via `group_timeslot_vars` |
| **Capacity Matching** | Automatic during solving | Approximate pre-calculation |
| **Specialization** | 4 types (core, K/J, Techlounge, 140-cap) | Not applicable (all general) |
| **Co-Scheduling** | Explicit (same room for 70+70=140) | N/A |
| **Soft Objectives** | Capacity preference weights | Early scheduling preference |
| **Complexity** | ~15 constraints × 2 per time | ~10 constraints × 1 per timeslot |

---

## Part 4: Implementation Architecture

### Lab Groups Search Space

```
                         FOR EACH...
                              ↓
Lab Assignment Variables (ROOM DECISIONS)
                              ↓
        lab_assignments[teacher_id]
                |
        [course_instance_id]
                |
        [day_idx] (Mon=0, Tue=1, ..., Fri=4)
                |
        [session_name] (L1, L2, ..., L6)
                |
        [room_id] (1, 2, ..., 140)
                |
            BoolVar (0 or 1)
        
Total Variables: ~5000 courses × 5 days × 6 sessions × 140 rooms
                = 210 million → optimized to ~50 million

Constraints Applied:
1. Group-based scheduling (same-semester groups don't overlap)
2. Room single assignment (each room-session max 1 course)
3. Capacity matching (students ≤ room capacity)
4. Specialization rules (core-only, K/J priority, etc.)
5. + 11 other lab-specific constraints
```

### Theory Groups Search Space

```
                         FOR EACH...
                              ↓
Theory Group Timeslot Variables (SLOT DECISIONS ONLY)
                              ↓
        group_timeslot_vars[group_name]
                |
        [day_idx] (Mon=0, Tue=1, ..., Fri=4)
                |
        [slot_idx] (0=9AM, 1=9:50AM, ..., 10=5:00PM)
                |
            BoolVar (0 or 1)
        
Total Variables: ~100 groups × 5 days × 11 slots
                = 5,500 variables (much simpler!)

Rooms Assigned Later (Post-Hoc):
- For each group needing theory room
- Pick from available theory_room_ids
- Based on group size and capacity needs

Constraints Applied:
1. Theory group non-overlap per timeslot
2. Proper room capacity calculation
3. No 3 consecutive slots
4. Lunch break respect
5. + 7 other theory-specific constraints
```

---

## Part 5: Real-World Scheduling Example

### Scenario
Monday morning, 9:00 AM - 9:50 AM slot (Lab L1 and Theory Slot 0)

### Lab Groups Competing

```
COURSE 1: Data Structures Lab (5 lab sessions)
  ├─ DSA-L1 Group (35 students)
  │  ├─ Lab assignment vars created for Monday-L1
  │  └─ Needs: 1 room from {room_5, room_10, room_15, ...}
  │
  └─ DSA-L2 Group (35 students)
     ├─ Lab assignment vars created for Monday-L1
     └─ Needs: 1 room from {room_5, room_10, room_15, ...}

COURSE 2: Algorithms Lab (3 lab sessions)
  ├─ ALG-L1 Group (30 students)
  │  ├─ Lab assignment vars created for Monday-L1
  │  └─ Needs: 1 room from {room_20, room_25, ...}
  │
  └─ ALG-L2 Group (32 students)
     ├─ Lab assignment vars created for Monday-L1
     └─ Needs: 1 room from {room_20, room_25, ...}

CONSTRAINT: apply_group_based_scheduling_constraint()
  ├─ DSA-L1 uses room_5 Monday-L1 → DSA-L2 CANNOT use room_5 (room conflict)
  ├─ But DSA-L2 can use room_10, room_15, etc (different rooms)
  ├─ ALG-L1 and ALG-L2 similarly constrained
  └─ Result: All groups CAN be scheduled Monday-L1 (in different rooms)
```

### Theory Groups Competing

```
COURSE: Data Structures Theory (3 groups)
  ├─ CSE_S3_G1 (140 students)
  │  ├─ 3 lectures + 1 tutorial = 4 timeslots/week needed
  │  └─ Theory group timeslot vars created
  │
  ├─ CSE_S3_G2 (135 students)
  │  ├─ 3 lectures + 1 tutorial = 4 timeslots/week needed
  │  └─ Theory group timeslot vars created
  │
  └─ CSE_S3_G3 (130 students)
     ├─ 3 lectures + 1 tutorial = 4 timeslots/week needed
     └─ Theory group timeslot vars created

CONSTRAINT: Theory group non-overlap per timeslot
  ├─ Monday 9AM slot: ONLY 1 group can use it
  │  ├─ Option A: CSE_S3_G1 gets Monday 9AM
  │  ├─ Then CSE_S3_G2 MUST use different day/time
  │  └─ And CSE_S3_G3 MUST use different day/time
  │
  ├─ Tuesday 9AM slot: Available for whichever group didn't get Monday
  │  ├─ If CSE_S3_G1 took Monday, G2 or G3 takes Tuesday
  │  └─ Others use Wed/Thu/Fri slots
  │
  └─ Result: All 3 groups get 4 slots, none conflict

POST-HOC ROOM ASSIGNMENT:
  ├─ CSE_S3_G1 (140 students) → Auditorium (capacity 150)
  ├─ CSE_S3_G2 (135 students) → Auditorium OR Large Hall (capacity 140)
  └─ CSE_S3_G3 (130 students) → Auditorium OR Large Hall
```

---

## Part 6: Why Different Approaches?

### Why Lab Groups use Explicit Room Variables

✅ **Pros**:
- Room conflicts immediately detected during optimization
- Capacity matching automatic in solver
- Specialization rules easily enforced
- Can use soft penalties for room preferences

❌ **Cons**:
- Millions of variables → expensive computation
- 140 rooms × all combinations = explosive growth
- But necessary for correctness (no conflicts allowed)

### Why Theory Groups use Post-Hoc Room Assignment

✅ **Pros**:
- Much simpler search space (5,500 vs 210M variables)
- Optimization 10x faster
- Room assignment trivial post-solve

❌ **Cons**:
- Theory rooms not optimized in search
- Approximate capacity calculation
- Some theory conflicts possible (handled in post-processing)

---

## Part 7: Constraint Hierarchy

### Lab Group Constraints (Priority Order)

```
PRIORITY 1: FEASIBILITY
  ├─ Room single assignment (no double-booking)
  └─ Group non-overlap (same-semester groups don't conflict)

PRIORITY 2: RESOURCE CONSTRAINTS
  ├─ Capacity matching (students ≤ room)
  ├─ Co-scheduling (140+140 forced to same room)
  └─ Specialization (core-only, 140-cap forced)

PRIORITY 3: PREFERENCE CONSTRAINTS
  ├─ K/J block priority (+400 weight)
  ├─ Capacity strategy preference (CS/IT prefer 70-cap)
  └─ Core lab group slot limits (prefer ≤8 slots)

PRIORITY 4: OPTIMIZATION
  ├─ Soft penalties minimized
  └─ Objective function balanced
```

### Theory Group Constraints (Priority Order)

```
PRIORITY 1: FEASIBILITY
  ├─ Theory group non-overlap (max 1 group per timeslot)
  └─ Room capacity approximation (groups ≤ available rooms)

PRIORITY 2: DISTRIBUTION
  ├─ No 3 consecutive slots (spread throughout day)
  ├─ Max 2 sessions per day (avoid concentration)
  └─ Daily slot limits (5-6 per day by dept)

PRIORITY 3: RESPECT CONSTRAINTS
  ├─ Lunch breaks (respect lunch times)
  ├─ Shift times (morning vs evening depts)
  └─ 140-capacity room reservation (if needed)

PRIORITY 4: OPTIMIZATION
  ├─ Early scheduling preference (before 3PM)
  └─ Teacher daily presence (avoid extreme hours)
```

---

## Summary: When Is Each Constraint Used?

### `apply_group_based_scheduling_constraint()` is used for LAB GROUPS:
- **When**: Lab courses with multiple sessions (L1, L2, ..., L6)
- **What**: Prevents same department-semester groups from conflicting
- **Where**: Lines 3426-3560 in combined_scheduler.py
- **Result**: Each group gets unique room + timeslot in lab sessions

### Theory Group Non-Overlap is used for THEORY GROUPS:
- **When**: Theory courses with lectures and tutorials
- **What**: Prevents different groups of same course from same timeslot
- **Where**: Lines 4000-4045 in combined_scheduler.py (within `_apply_theory_constraints()`)
- **Result**: Each group gets unique timeslot(s) in theory schedule

### Key Takeaway:
**Lab groups = room-based scheduling** (explicit room variables in solver)
**Theory groups = time-based scheduling** (timeslot variables, rooms post-hoc)

Both use "group non-overlap" concept but apply to different search dimensions!
