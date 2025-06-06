"""
Constraint package for timetable scheduling.

This package contains individual constraint files for better organization and maintainability.
Each constraint type is implemented in its own file for easy understanding and modification.
"""

from .course_hours_constraint import CourseHoursConstraint
from .teacher_assignment_constraint import TeacherAssignmentConstraint
from .room_assignment_constraint import RoomAssignmentConstraint
from .working_hours_constraint import WorkingHoursConstraint
from .lab_assignment_constraint import LabAssignmentConstraint
from .conflict_prevention_constraint import ConflictPreventionConstraint

__all__ = [
    'CourseHoursConstraint',
    'TeacherAssignmentConstraint', 
    'RoomAssignmentConstraint',
    'WorkingHoursConstraint',
    'LabAssignmentConstraint',
    'ConflictPreventionConstraint'
] 