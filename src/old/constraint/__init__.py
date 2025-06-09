"""
Constraint Module

This module contains all the constraint classes for the timetable scheduling system.
Each constraint handles a specific aspect of the scheduling problem, ensuring the 
generated timetable meets various requirements and restrictions.

INSTANCE-AWARE CONSTRAINTS:
All constraints in this module work at the teacher-course-instance level, ensuring 
that each individual course instance (represented by a unique record ID) gets 
proper treatment in the scheduling algorithm.

CONSTRAINT TYPES:
1. CourseHoursConstraint - Ensures each instance gets exact required hours (L+T+P) [OPTIMIZED]
2. TeacherAssignmentConstraint - Prevents teacher double-booking with instance tracking [OPTIMIZED]
3. RoomAssignmentConstraint - Instance-aware room allocation with capacity checking
4. WorkingHoursConstraint - 21-hour limit with instance-level hour calculation [OPTIMIZED]
5. LabAssignmentConstraint - Lab scheduling with instance prioritization
6. ConflictPreventionConstraint - Instance-level conflict detection and prevention
7. CourseGroupConstraint - Instance-aware course grouping with Hall's theorem compliance

OPTIMIZATION FEATURES:
- Reduced variable creation and constraint overhead
- Streamlined constraint generation algorithms
- Efficient data structure utilization
- Improved performance while maintaining full functionality
"""

# Import all constraint classes
from .course_hours_constraint import CourseHoursConstraint
from .teacher_assignment_constraint import TeacherAssignmentConstraint
from .room_assignment_constraint import RoomAssignmentConstraint
from .working_hours_constraint import WorkingHoursConstraint
from .lab_assignment_constraint import LabAssignmentConstraint
from .conflict_prevention_constraint import ConflictPreventionConstraint
from .course_group_constraint import CourseGroupConstraint

# Export all constraint classes
__all__ = [
    'CourseHoursConstraint',
    'TeacherAssignmentConstraint', 
    'RoomAssignmentConstraint',
    'WorkingHoursConstraint',
    'LabAssignmentConstraint',
    'ConflictPreventionConstraint',
    'CourseGroupConstraint'
] 