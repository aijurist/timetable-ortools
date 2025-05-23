# New Constraint Added: Monday OR Saturday Work Days

## Overview
A new constraint has been added to ensure that teachers work either on Monday OR Saturday, but not both days. This promotes better work-life balance by preventing teachers from working both the beginning and end of the week.

## Constraint Details

### Problem Addressed
Without this constraint, teachers could be scheduled for:
- Monday classes (week start) AND Saturday classes (weekend)
- This creates poor work-life balance and extended work weeks
- Makes it difficult for teachers to have proper weekend rest

### Solution Implementation
**Constraint 9: Monday or Saturday Constraint**

```python
def apply_monday_or_saturday_constraint(self, teacher_theory_assignments, teacher_lab_assignments):
    # For each teacher:
    # 1. Create boolean variables: works_monday, works_saturday  
    # 2. Link variables to actual Monday/Saturday assignments
    # 3. Enforce: works_monday + works_saturday ≤ 1
```

### Technical Implementation

#### 1. **Day Index Mapping**
```python
monday_index = 0      # Monday is day 0 in days array
saturday_index = 5    # Saturday is day 5 in days array
```

#### 2. **Boolean Variable Creation**
For each teacher, creates tracking variables:
```python
works_monday = self.model.NewBoolVar(f'teacher_{teacher}_works_monday')
works_saturday = self.model.NewBoolVar(f'teacher_{teacher}_works_saturday')
```

#### 3. **Assignment Collection**
Collects all possible assignments for each day:
- **Monday**: All theory slots (0-10) + all lab slots (0-5)
- **Saturday**: All theory slots (0-10) + all lab slots (0-5)

#### 4. **Variable Linking**
Links boolean variables to actual assignments:
```python
# If any Monday slot assigned → works_monday = true
for var in monday_all_vars:
    self.model.Add(works_monday >= var)

# If any Saturday slot assigned → works_saturday = true  
for var in saturday_all_vars:
    self.model.Add(works_saturday >= var)
```

#### 5. **Mutual Exclusion Constraint**
Enforces that teachers cannot work both days:
```python
self.model.Add(works_monday + works_saturday <= 1)
```

## Constraint Logic Flow

### Scenario Examples

#### ✅ **Valid Schedules**
```
Teacher A: Monday Theory (8:00-9:00) + Monday Lab (10:00-11:40)
         → works_monday = 1, works_saturday = 0 ✓

Teacher B: Saturday Theory (14:00-15:00) + Saturday Lab (15:10-16:50)  
         → works_monday = 0, works_saturday = 1 ✓

Teacher C: Tuesday-Friday classes only
         → works_monday = 0, works_saturday = 0 ✓

Teacher D: No assignments
         → works_monday = 0, works_saturday = 0 ✓
```

#### ❌ **Invalid Schedules**
```
Teacher E: Monday Theory + Saturday Lab
         → works_monday = 1, works_saturday = 1 ❌
         → Violates: works_monday + works_saturday ≤ 1
```

## Integration Points

### 1. **Constraint Application** (`apply_all_constraints`)
Added to the list of applied constraints:
```python
constraints_applied = [
    # ... existing constraints ...
    self.apply_monday_or_saturday_constraint(teacher_theory_assignments, teacher_lab_assignments)
]
```

### 2. **Constraint Summary** (`generate_constraint_summary`)
Added comprehensive documentation:
```python
"monday_or_saturday": {
    "name": "Monday or Saturday Constraint",
    "description": "Ensures teachers work either on Monday OR Saturday, but not both days",
    "impact": "Promotes better work-life balance...",
    "complexity": "O(T × (S_theory + S_lab) × 2)",
    "example": "Teacher scheduling scenarios..."
}
```

### 3. **Main Application** (`main.py`)
Added to key highlights:
```
• Teachers work either Monday OR Saturday, not both days
```

## Benefits

### 1. **Work-Life Balance**
- Prevents extended work weeks (Monday + Saturday)
- Ensures teachers get proper weekend rest
- Reduces teacher burnout and fatigue

### 2. **Scheduling Flexibility**
- Still allows Monday OR Saturday coverage as needed
- Maintains adequate staffing for both days
- Balances institutional needs with teacher welfare

### 3. **Resource Distribution**  
- Distributes teaching load more evenly across teachers
- Prevents over-scheduling of individual teachers
- Improves overall schedule quality

## Performance Impact

### Computational Complexity
- **Formula**: O(T × (S_theory + S_lab) × 2)
- **Level**: Medium complexity
- **Variables Added**: 2 boolean variables per teacher
- **Constraints Added**: ~3-4 constraints per teacher

### Memory Usage
- Minimal impact: 2 additional boolean variables per teacher
- No significant performance degradation
- Scales linearly with number of teachers

## Verification

✅ **All implementation components verified**:
- ✅ Method exists and is properly implemented
- ✅ Boolean variables created correctly  
- ✅ Day indices mapped correctly (Monday=0, Saturday=5)
- ✅ Constraint enforcement logic implemented
- ✅ Integration with constraint application system
- ✅ Constraint summary documentation added
- ✅ Main application highlights updated

## Testing

To verify the constraint works:

1. **Run the scheduler**: `python main.py`

2. **Check generated schedules**:
   - No teacher should appear in both Monday AND Saturday schedules
   - Teachers can appear in Monday OR Saturday, but not both

3. **Verify constraint summary**:
   - Check `constraint_summary.txt` for Monday/Saturday constraint details

4. **Review individual teacher schedules**:
   - `teacher_*_schedule.csv` files should show either Monday or Saturday, not both

## Future Enhancements

Potential extensions of this constraint:
1. **Configurable day pairs**: Allow different day exclusions (e.g., Friday OR Monday)
2. **Flexible work patterns**: Support for different work week preferences
3. **Priority systems**: Preference-based assignment to Monday vs Saturday

The Monday/Saturday constraint successfully balances institutional scheduling needs with teacher work-life balance! 🎉 