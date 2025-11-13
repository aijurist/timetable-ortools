# CourseGroupOptimizer - Complete Analysis
## Purpose, Architecture, Constraints & Optimization Logic

---

## 🎯 **MAIN PURPOSE**

The `CourseGroupOptimizer` is an **OR-Tools based mathematical optimizer** that solves the **Course Instance Distribution Problem**:

**Problem Statement:**
> Given a set of course instances (with teacher IDs, practical hours, lecture hours, student counts) for a specific department and semester, **optimally distribute them into groups such that:**
> - No teacher appears twice in the same group
> - Each course appears in at most 2 groups
> - All groups have equal size
> - Lab courses occupy initial groups first (priority)
> - Special constraints for specific departments

**Output:** Optimized groups ready for unified theory + lab scheduling

---

## 📐 **ARCHITECTURE OVERVIEW**

```
INPUT DATA
    ↓
[Course Instances: List of {id, teacher_id, course_code, has_lab, has_theory, ...}]
    ↓
┌─────────────────────────────────────────────────┐
│  CourseGroupOptimizer.__init__()                │
│  - Preprocess large courses (140+ students)    │
│  - Load & separate PE courses                   │
│  - Filter by instance count                     │
│  - Analyze lab/theory split                     │
└─────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────┐
│  optimize_distribution()                        │
│  1. Create CP-SAT model                         │
│  2. Create binary decision variables            │
│  3. Apply 5 types of constraints               │
│  4. Set optimization objectives                │
│  5. Solve with CP-SAT solver                   │
└─────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────┐
│  _extract_solution()                            │
│  - Parse solver results                         │
│  - Reconstruct groups from assignments         │
│  - Handle co-scheduled virtual instances       │
└─────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────┐
│  validate_solution()                            │
│  - Check all constraints are satisfied         │
│  - Verify solution completeness                │
└─────────────────────────────────────────────────┘
    ↓
OUTPUT DATA
    ↓
[Optimized Groups: List of {group1[], group2[], ...}]
```

---

## 🔧 **INITIALIZATION PHASE**

### Constructor: `__init__(courses, dept, semester, logger, pe_course_map_file, flexible_grouping_depts)`

#### **Step 1: Store Parameters**
```python
self.courses = courses                    # Original course instances
self.dept = dept                          # Department name
self.semester = semester                  # Semester number
self.logger = logger                      # Logging object
self.pe_course_map_file = pe_course_map_file
self.flexible_grouping_depts = flexible_grouping_depts or [default_list]
```

#### **Step 2: Preprocess Large Courses (140+ students)**
```python
self.courses = self._preprocess_large_courses(self.courses)
```

**What Happens:**
- Identifies courses with 140+ students
- Splits each into TWO virtual instances:
  - `instance_id-A` (70 students)
  - `instance_id-B` (70 students)
- Marks them with metadata:
  - `'is_large_course_split': True`
  - `'original_student_count': 140`
  - `'co_scheduled_id'`: Link between -A and -B
- **Purpose:** Allows large courses to be distributed across groups while keeping lab sessions manageable (70 students per lab max)
- **Later Merge:** These virtual instances get merged back in `combined_scheduler.py` for 140-capacity lab scheduling

**Example:**
```
Original: Course CS301 (140 students, teacher T001)
        ↓ Split
Virtual-A: CS301-A (70 students, teacher T001, co_scheduled_id="CS301-B")
Virtual-B: CS301-B (70 students, teacher T001, co_scheduled_id="CS301-A")
```

#### **Step 3: Load PE Course Mapping**
```python
self._load_pe_course_mapping()
```

**What Happens:**
- Reads `pe_course_map.csv` (if provided)
- Identifies Professional Elective courses
- Stores course codes in `self.pe_course_codes`

#### **Step 4: Separate PE Courses**
```python
self.courses, self.pe_courses = self._separate_pe_courses(self.courses)
```

**What Happens:**
- PE courses are removed from main `self.courses`
- Kept separately in `self.pe_courses`
- **Purpose:** PE courses follow different grouping rules (not part of standard groups)

#### **Step 5: Filter Courses by Instance Count**
```python
self.courses = self._filter_courses_by_instance_count(self.courses)
```

**What Happens:**
1. Count instances per course code
   ```
   CS301: 2 instances
   CS302: 2 instances
   MATH201: 3 instances  ← Extra instance
   PHYS301: 1 instance   ← Fewer instances
   ```

2. Find most common count
   ```
   Frequency: count 1 → 1 course
              count 2 → 2 courses
              count 3 → 1 course
   Most common: count 2 (appears in 2 courses)
   ```

3. Filter courses:
   - **Keep:** Courses with exactly 2 instances
   - **Trim:** Courses with 3+ instances → trim down to 2 (random selection)
   - **Remove:** Courses with 1 instance ← Stored in `self.removed_courses`

4. **Why?** Ensures all remaining courses can be distributed equally across 2 groups minimum

**Output:**
```python
self.removed_courses = [PHYS301 instance info]
self.trimmed_courses = {
    'MATH201': {
        'original_count': 3,
        'kept_count': 2,
        'removed_instances': [...]
    }
}
self.filtering_summary = {detailed statistics}
```

#### **Step 6: Analyze Courses**
```python
self.lab_courses = [instances with has_lab=True]
self.theory_courses = [instances with has_theory=True]
self.unique_courses = list(set(inst['course_code']))
self.unique_teachers = list(set(inst['teacher_id']))
self.num_groups = len(self.unique_courses)  # KEY: # groups = # unique courses
```

**Important:** Number of groups = Number of unique course codes

**Example:**
```
After filtering: 4 unique courses (CS301, CS302, MATH201, CS101)
                 → 4 groups will be created
                 
Each group will have the same size:
    Group size = total_instances ÷ num_groups = 8 ÷ 4 = 2 instances per group
```

---

## 🧠 **OPTIMIZATION PHASE: `optimize_distribution()`**

### **Overview: 5-Step Optimization Process**

```
STEP 1: Check Feasibility
    ↓
STEP 2: Create CP-SAT Model & Variables
    ↓
STEP 3: Apply 5 Constraint Types
    ↓
STEP 4: Set Optimization Objectives
    ↓
STEP 5: Solve & Extract Solution
```

---

### **STEP 1: Feasibility Check**

```python
def _check_feasibility(self):
```

**Checks:**
1. ✅ Do we have groups? `num_groups > 0`
2. ✅ Can instances be evenly distributed?
   ```python
   total_instances % num_groups == 0
   
   Example:
   - Total instances: 8
   - Num groups: 4
   - Group size: 8 ÷ 4 = 2 ✓
   
   OR
   - Total instances: 9
   - Num groups: 4
   - Group size: 9 ÷ 4 = 2.25 ✗ (Not divisible)
   ```

3. ✅ Single vs multi-instance courses valid?
   ```python
   Single-instance courses: Can be in 1 group
   Multi-instance courses: Must be in exactly 2 groups (or 1-2 if flexible)
   ```

---

### **STEP 2: Create Binary Decision Variables**

```python
def _create_assignment_variables(self, model):
```

**Variable Type:** Binary (0 or 1)

**Variable Indexing:**
```python
assignment_vars[(instance_idx, group_idx)] = BoolVar

Example:
assignment_vars[(0, 0)] = True  → Instance 0 goes to Group 0
assignment_vars[(0, 1)] = False → Instance 0 does NOT go to Group 1
```

**Total Variables Created:**
```python
Total = num_instances × num_groups
Example: 8 instances × 4 groups = 32 binary variables
```

---

### **STEP 3: Apply 5 Constraint Types**

#### **Constraint Type 1: Basic Assignment Constraints**
```python
def _apply_assignment_constraints(model, assignment_vars):
```

**Rule:** Each instance must be assigned to EXACTLY one group

```python
for each instance i:
    sum(assignment_vars[(i, g)] for g in all_groups) == 1
    
Meaning: Sum across all groups must equal exactly 1
Example: Instance 0 must be in exactly one of {G0, G1, G2, G3}
```

**Special Handling for Virtual Instances:**
- If instance has `co_scheduled_id`, link it to same group as its twin
```python
if instance has co_scheduled_id:
    assignment_vars[(instance_idx, group)] == assignment_vars[(twin_idx, group)]
    
Example:
    If CS301-A goes to Group 1, then CS301-B MUST go to Group 1
    (They represent one 140-student course split into 2 parts)
```

---

#### **Constraint Type 2: Teacher Uniqueness Constraints**
```python
def _apply_teacher_uniqueness_constraints(model, assignment_vars):
```

**Rule:** No teacher can appear MORE THAN ONCE in the same group

```python
for each group g:
    for each teacher t:
        sum(assignment_vars[(i, g)] for i in instances_by_teacher_t) <= 1
        
Example Group 0:
    sum(CS301_instances_by_T001) <= 1  → At most 1 instance of T001's CS301
    sum(CS302_instances_by_T002) <= 1  → At most 1 instance of T002's CS302
```

**Exception:** Virtual instances with same `co_scheduled_id` are allowed together
```python
If T001 teaches CS301-A and CS301-B (same course split):
    They can both be in Group 1 (treated as single unit)
```

---

#### **Constraint Type 3: Course Limit Constraints**
```python
def _apply_course_limit_constraints(model, assignment_vars):
```

**Two Cases:**

**Case A: Single-Instance Courses**
```python
if course has only 1 instance:
    # Allow in only 1 group (trivial case)
    sum(assignment_vars[(i, g)] for g in groups) == 1
```

**Case B: Multi-Instance Courses**

**Standard Departments:**
```python
if course has 2+ instances AND dept NOT in flexible_grouping_depts:
    # Must be in EXACTLY 2 groups
    sum(BoolVar for each group where course appears) == 2
    
Example: CS301 with 2 instances
    CS301_inst1 in G0, CS301_inst2 in G2
    → CS301 appears in groups {0, 2} = 2 groups ✓
```

**Flexible Departments:**
```python
if course has 2+ instances AND dept in flexible_grouping_depts:
    # Can be in 1 OR 2 groups (flexible)
    1 <= sum(BoolVar for each group where course appears) <= 2
    
Allows consolidation if solver finds it optimal
```

---

#### **Constraint Type 4: Group Size Constraints**
```python
def _apply_group_size_constraints(model, assignment_vars):
```

**Rule:** Each group must have EXACTLY the same number of instances

```python
target_group_size = total_instances ÷ num_groups

for each group g:
    sum(assignment_vars[(i, g)] for i in all_instances) == target_group_size

Example:
    8 instances ÷ 4 groups = 2 per group
    Group 0: must have exactly 2 instances
    Group 1: must have exactly 2 instances
    Group 2: must have exactly 2 instances
    Group 3: must have exactly 2 instances
```

---

#### **Constraint Type 5: Lab Priority Constraints**
```python
def _apply_lab_priority_constraints(model, assignment_vars):
```

**Rule:** Lab courses occupy FIRST groups; theory-only courses occupy REMAINING groups

**Skip Condition:** If only 1 lab course OR only 1 theory-only course, skip (trivial)

**Setup:**
```python
lab_courses = {courses with has_lab=True}
theory_only_courses = {courses with has_theory=True AND has_lab=False}

num_lab_groups = len(lab_courses)
num_theory_groups = len(theory_only_courses)
```

**Constraint:**
```python
# Lab instances ONLY in first num_lab_groups groups
for each lab instance i:
    for group g in remaining_groups:
        assignment_vars[(i, g)] == 0  # Not allowed

# Theory-only instances NOT in first num_lab_groups groups
for each theory_only instance i:
    for group g in first_num_lab_groups_groups:
        assignment_vars[(i, g)] == 0  # Not allowed
```

**Example:**
```
3 lab courses, 2 theory-only courses
→ 5 groups total
→ Groups 0,1,2 for lab courses only
→ Groups 3,4 for theory-only courses only
```

---

### **STEP 4: Special Department Constraints**

```python
def _apply_special_department_constraints(model, assignment_vars):
```

**Currently Implemented for:**

1. **Electronics & Communication Engineering, Semester 7**
   - Even distribution of lab instances across initial groups
   - Balance lab load between groups

2. **Electronics & Communication Engineering, Semester 5**
   - Similar even distribution logic

**Purpose:** Specific departments have additional requirements for workload balancing

---

### **STEP 5: Set Optimization Objectives**

```python
def _set_optimization_objectives(model, assignment_vars):
```

**Multi-Objective Optimization:**

**Objective 1: Minimize Course Fragmentation** (Primary)
```python
Weight: High priority
Goal: Minimize number of groups per course
Logic: Prefer courses to be in fewer groups if possible
```

**Objective 2: Balance Group Sizes** (Secondary)
```python
Weight: Medium priority
Goal: Keep group sizes as equal as possible
Logic: Avoid uneven distribution
```

**Objective 3: Prefer Theory Consolidation** (Tertiary)
```python
Weight: Low priority
Goal: If possible, consolidate theory-only courses
```

---

### **STEP 6: Solve the Model**

```python
def _solve_model(model, assignment_vars):
```

**Solver:** CP-SAT solver with time limit (typically 30-60 seconds)

**Status Codes:**
- `OPTIMAL` (0): Best solution found
- `FEASIBLE` (1): Good solution found (not optimal)
- `INFEASIBLE` (2): No valid solution exists
- `MODEL_INVALID` (3): Problem setup is invalid

**Return:** `True` if solution found, `False` otherwise

---

## 🔍 **SOLUTION EXTRACTION**

```python
def _extract_solution(solver, assignment_vars):
```

**Process:**

1. **Read Solver Values:**
   ```python
   for instance_idx, group_idx in assignment_vars:
       if solver.Value(assignment_vars[(instance_idx, group_idx)]) == 1:
           # Instance is in this group
   ```

2. **Reconstruct Groups:**
   ```python
   groups[group_idx] = [list of instances in this group]
   ```

3. **Handle Co-Scheduled Instances:**
   ```python
   # If instance has co_scheduled_id, ensure both twins are together
   if instance A has co_scheduled_id = B:
       # Verify both A and B are in same group
   ```

4. **Store Results:**
   ```python
   self.groups = reconstructed_groups
   self.solution_found = True
   self.objective_value = solver.ObjectiveValue()
   ```

---

## ✅ **SOLUTION VALIDATION**

```python
def validate_solution(self):
```

**5 Validation Checks:**

### **Check 1: Teacher Uniqueness**
```python
def _validate_teacher_uniqueness(self):
    for each group:
        for each teacher:
            count = number of instances by this teacher
            if count > 1:  # Violation!
                log error
```

### **Check 2: Course Limits**
```python
def _validate_course_limits(self):
    for each course:
        num_groups = number of groups containing this course
        if single_instance_course AND num_groups != 1:
            log error
        if multi_instance_course AND num_groups not in [1, 2]:
            log error
```

### **Check 3: Assignment Completeness**
```python
def _validate_assignment_completeness(self):
    for each instance:
        if not assigned to any group:
            log error
        if assigned to multiple groups:
            log error
```

### **Check 4: Group Sizes**
```python
def _validate_group_sizes(self):
    for each group:
        if size != target_group_size:
            log error
```

### **Check 5: Lab Priority**
```python
def _validate_lab_priority(self):
    for first N groups (lab groups):
        if contains theory-only instance:
            log error
    for remaining groups (theory groups):
        if contains lab instance:
            log error
```

**Returns:** `True` if all checks pass, `False` otherwise

---

## 📊 **KEY DATA STRUCTURES**

### **Input: Course Instance**
```python
{
    'id': '123',                      # Instance ID
    'course_code': 'CS301',           # Course code
    'course_name': 'Algorithms',      # Full name
    'teacher_id': 'T001',             # Teacher ID
    'has_lab': True,                  # Has practical hours
    'has_theory': True,               # Has lecture hours
    'practical_hours': 3,             # Lab hours
    'lecture_hours': 2,               # Lecture hours
    'tutorial_hours': 1,              # Tutorial hours
    'student_count': 70,              # Student count
    'semester': 5,                    # Semester
    'course_dept': 'CSE',             # Course department
    'student_dept': 'CSE',            # Student department
    # Virtual instance fields (optional):
    'virtual_id': '123-A',            # If split from 140+ student course
    'is_large_course_split': True,    # If virtual instance
    'original_student_count': 140,    # If virtual instance
    'co_scheduled_id': '123-B'        # If virtual instance (twin ID)
}
```

### **Output: Optimized Groups**
```python
self.groups = [
    # Group 1
    [
        {instance1_with_all_fields},
        {instance2_with_all_fields},
        ...
    ],
    # Group 2
    [
        {instance3_with_all_fields},
        ...
    ],
    # ... more groups
]
```

### **Tracking Data**
```python
self.removed_courses = [
    {course info removed during filtering}
]

self.trimmed_courses = {
    'MATH201': {
        'original_count': 3,
        'kept_count': 2,
        'removed_instances': [...]
    }
}

self.filtering_summary = {
    'original_total_instances': 10,
    'filtered_total_instances': 8,
    'most_common_instance_count': 2,
    'courses_removed_count': 1,
    'courses_trimmed_count': 1,
    'total_instances_removed': 2
}
```

---

## 🔄 **WORKFLOW INTEGRATION WITH COMBINED_SCHEDULER**

### **How CourseGroupOptimizer Fits In:**

```
combined_scheduler.py (Line ~2080-2112)
    ↓
_distribute_course_instances_optimized()
    ↓
CourseGroupOptimizer.__init__()
    ↓
optimizer.optimize_distribution()
    ↓
Returns: self.groups (optimized groups)
    ↓
combined_scheduler.py continues:
    ↓
_create_instance_group_mapping()
    (Maps each instance ID → group name and metadata)
    ↓
_update_lab_requirements_with_virtual_instances()
    (Replace original large courses with virtual instances)
    ↓
_update_lab_requirements_for_virtual_instances()
    (Merge virtual instances back to unified 140-capacity courses)
    ↓
_filter_lab_requirements_by_groups()
    (Keep only instances in groups)
    ↓
_identify_core_lab_groups()
    (Mark groups with specialized labs)
```

---

## 🎯 **KEY ADVANTAGES OF THIS APPROACH**

1. **Mathematical Optimization:** Uses OR-Tools CP-SAT solver instead of heuristics
2. **Constraint Satisfaction:** Guarantees all constraints are met if solution exists
3. **Flexible Grouping:** Different departments can have different grouping rules
4. **Large Course Handling:** Properly splits 140+ student courses for lab scheduling
5. **PE Course Support:** Handles Professional Elective courses separately
6. **Validation:** Comprehensive validation ensures solution quality
7. **Reporting:** Detailed filtering and trimming reports for transparency

---

## ⚡ **EXAMPLE: COMPLETE OPTIMIZATION FLOW**

### **Input:**
```python
courses = [
    # CS301: 2 instances (lab)
    {'id': '1', 'course_code': 'CS301', 'teacher_id': 'T1', 'has_lab': True, 'student_count': 140},
    {'id': '2', 'course_code': 'CS301', 'teacher_id': 'T2', 'has_lab': True, 'student_count': 65},
    
    # CS302: 2 instances (lab)
    {'id': '3', 'course_code': 'CS302', 'teacher_id': 'T3', 'has_lab': True, 'student_count': 70},
    {'id': '4', 'course_code': 'CS302', 'teacher_id': 'T4', 'has_lab': True, 'student_count': 70},
    
    # MATH201: 3 instances (theory only)
    {'id': '5', 'course_code': 'MATH201', 'teacher_id': 'T5', 'has_lab': False, 'student_count': 120},
    {'id': '6', 'course_code': 'MATH201', 'teacher_id': 'T6', 'has_lab': False, 'student_count': 115},
    {'id': '7', 'course_code': 'MATH201', 'teacher_id': 'T7', 'has_lab': False, 'student_count': 110},
    
    # CS101: 2 instances (theory only)
    {'id': '8', 'course_code': 'CS101', 'teacher_id': 'T8', 'has_lab': False, 'student_count': 100},
    {'id': '9', 'course_code': 'CS101', 'teacher_id': 'T9', 'has_lab': False, 'student_count': 95},
]

dept = "Computer Science & Engineering"
semester = 5
```

### **Preprocessing:**

**1. Large Course Splitting:**
```
Instance 1 (CS301, 140 students) splits into:
    - 1-A (70 students, co_scheduled_id='1-B')
    - 1-B (70 students, co_scheduled_id='1-A')
```

**2. Separation:**
- All remain (no PE courses in this example)

**3. Filtering:**
```
Instance counts:
- CS301: 2 instances ✓
- CS302: 2 instances ✓
- MATH201: 3 instances ⚠ (trim to 2, remove 1)
- CS101: 2 instances ✓

Result:
- Keep: CS301 (2), CS302 (2), MATH201 (2), CS101 (2) = 8 instances total
- Remove: MATH201 instance (1 removed)
- Unique courses: 4 → 4 groups needed
- Group size: 8 ÷ 4 = 2 instances per group
```

### **Optimization:**

**Decision Variables Created:**
```
32 binary variables: (instance_id, group_id) pairs
8 instances × 4 groups = 32 variables
```

**Constraints Applied:**
```
1. Assignment: Each instance in exactly 1 group
2. Teacher Uniqueness: No teacher appears twice in same group
3. Course Limit: Each course in exactly 2 groups
4. Group Size: Each group has exactly 2 instances
5. Lab Priority: Lab instances in Groups 0-1, Theory in Groups 2-3
```

**Optimization Objectives:**
```
1. Minimize fragmentation
2. Balance group sizes
3. Prefer theory consolidation
```

### **Solution (Possible):**

```
Group 0 (Lab group):
  - Instance 1-A (CS301, T1, 70 students)
  - Instance 3 (CS302, T3, 70 students)

Group 1 (Lab group):
  - Instance 1-B (CS301, T2, 65 students) - co-scheduled with 1-A
  - Instance 4 (CS302, T4, 70 students)

Group 2 (Theory group):
  - Instance 5 (MATH201, T5, 120 students)
  - Instance 8 (CS101, T8, 100 students)

Group 3 (Theory group):
  - Instance 6 (MATH201, T6, 115 students)
  - Instance 9 (CS101, T9, 95 students)

Verification:
✓ Each instance in exactly 1 group
✓ No teacher appears twice in same group
✓ CS301 in groups {0, 1} = 2 groups
✓ CS302 in groups {0, 1} = 2 groups
✓ MATH201 in groups {2, 3} = 2 groups
✓ CS101 in groups {2, 3} = 2 groups
✓ Each group has 2 instances
✓ Lab instances (0, 1, 3, 4) in Groups 0-1 ✓
✓ Theory instances (5, 6, 8, 9) in Groups 2-3 ✓
✓ Co-scheduled 1-A and 1-B in same group ✓
```

### **Output:**

```python
optimizer.groups = [
    # Group 0
    [instance_1_A, instance_3],
    # Group 1
    [instance_1_B, instance_4],
    # Group 2
    [instance_5, instance_8],
    # Group 3
    [instance_6, instance_9]
]

optimizer.solution_found = True
optimizer.objective_value = 0.95  # High quality solution
```

### **Post-Processing in combined_scheduler:**

```python
# Map instances to groups
instance_group_mapping['1-A'] = {group_name: 'CSE_S5_G1', ...}
instance_group_mapping['1-B'] = {group_name: 'CSE_S5_G2', ...}
# ... etc

# Later: Merge virtual instances
# 1-A + 1-B → Instance 1 (140-capacity lab course)
```

---

## 📝 **SUMMARY**

| Aspect | Detail |
|--------|--------|
| **Purpose** | Mathematically optimize course instance distribution into groups |
| **Input** | Course instances with teacher, hours, student count |
| **Algorithm** | OR-Tools CP-SAT constraint satisfaction solver |
| **Key Constraints** | Teacher uniqueness, course limit (2 max), equal group size, lab priority |
| **Output** | Optimized groups ready for timetabling |
| **Special Features** | Handles 140+ student splits, PE courses, flexible grouping |
| **Validation** | 5-check validation ensures solution quality |
| **Role in System** | Part of combined_scheduler initialization pipeline |

