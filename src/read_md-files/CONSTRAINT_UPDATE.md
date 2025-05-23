# New Constraint Added: No Continuous Lab Slots

## Overview
A new constraint has been added to prevent teachers from being assigned to continuous lab slots unless there's sufficient break time between them.

## Constraint Details

### Lab Slot Timing Analysis
The system has 6 lab slots per day with the following timings:
- **L1**: 8:00-9:40
- **L2**: 10:00-11:40 (20 min break from L1)
- **L3**: 11:40-1:20 (0 min break from L2 - continuous)  
- **L4**: 1:20-3:00 (0 min break from L3 - continuous)
- **L5**: 3:00-4:40 (0 min break from L4 - continuous)
- **L6**: 5:10-6:50 (30 min break from L5)

### Constraint Rules
- **ALLOWED consecutive assignments**: 
  - L1-L2 (20 minute break)
  - L5-L6 (30 minute break)
- **FORBIDDEN consecutive assignments**:
  - L2-L3 (0 minute break - continuous)
  - L3-L4 (0 minute break - continuous)
  - L4-L5 (0 minute break - continuous)

### Implementation
The constraint is implemented in `src/constraints.py` as:
```python
def apply_no_continuous_lab_slots_constraint(self, teacher_theory_assignments, teacher_lab_assignments)
```

### Benefits
1. **Teacher Well-being**: Prevents exhausting back-to-back lab sessions
2. **Quality Education**: Ensures teachers have adequate break time for preparation
3. **Flexible Scheduling**: Still allows consecutive assignments when sufficient break exists

### Integration
- Added to `apply_all_constraints()` method
- Included in constraint summary reporting
- Updated main.py highlights to inform users

The constraint ensures the timetable respects teacher workload while maintaining scheduling flexibility where appropriate breaks exist. 