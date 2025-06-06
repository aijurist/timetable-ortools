"""
Main Constraints Module

This module coordinates all individual constraint classes to create
a comprehensive timetable scheduling constraint system.
"""

import logging
from src.constraint import (
    CourseHoursConstraint,
    TeacherAssignmentConstraint,
    RoomAssignmentConstraint,
    WorkingHoursConstraint,
    LabAssignmentConstraint,
    ConflictPreventionConstraint
)

logger = logging.getLogger(__name__)

class TimetableConstraints:
    def __init__(self, model, teachers, teacher_course_assignments, classrooms, labs):
        """Initialize the timetable constraints with model and necessary data."""
        self.model = model
        self.teachers = teachers
        self.teacher_course_assignments = teacher_course_assignments
        self.classrooms = classrooms
        self.labs = labs
        
        # Initialize individual constraint handlers
        self.course_hours_constraint = CourseHoursConstraint(
            model, teachers, teacher_course_assignments, classrooms, labs
        )
        self.teacher_assignment_constraint = TeacherAssignmentConstraint(
            model, teachers, teacher_course_assignments, classrooms, labs
        )
        self.room_assignment_constraint = RoomAssignmentConstraint(
            model, teachers, teacher_course_assignments, classrooms, labs
        )
        self.working_hours_constraint = WorkingHoursConstraint(
            model, teachers, teacher_course_assignments, classrooms, labs
        )
        self.lab_assignment_constraint = LabAssignmentConstraint(
            model, teachers, teacher_course_assignments, classrooms, labs
        )
        self.conflict_prevention_constraint = ConflictPreventionConstraint(
            model, teachers, teacher_course_assignments, classrooms, labs
        )
        
        logger.info("TimetableConstraints initialized with individual constraint handlers")
    
    def apply_all_constraints(self, teacher_theory_assignments, teacher_lab_assignments=None):
        """Apply all timetable constraints using individual constraint handlers."""
        logger.info("Applying all timetable constraints...")
        
        try:
            # Apply constraints in logical order
            constraints_applied = []
            
            # 1. Course Hours Constraint - ensures proper hour allocation
            constraints_applied.append(
                self.course_hours_constraint.apply(teacher_theory_assignments, teacher_lab_assignments)
            )
            
            # 2. Teacher Assignment Constraint - prevents teacher double-booking
            constraints_applied.append(
                self.teacher_assignment_constraint.apply(teacher_theory_assignments, teacher_lab_assignments)
            )
            
            # 3. Room Assignment Constraint - prevents room conflicts
            constraints_applied.append(
                self.room_assignment_constraint.apply(teacher_theory_assignments, teacher_lab_assignments)
            )
            
            # 4. Working Hours Constraint - limits teacher workload
            constraints_applied.append(
                self.working_hours_constraint.apply(teacher_theory_assignments, teacher_lab_assignments)
            )
            
            # 5. Lab Assignment Constraint - handles lab scheduling (if lab assignments provided)
            if teacher_lab_assignments is not None:
                constraints_applied.append(
                    self.lab_assignment_constraint.apply(teacher_theory_assignments, teacher_lab_assignments)
                )
            else:
                logger.info("No lab assignments provided - skipping lab assignment constraints")
                constraints_applied.append(True)
            
            # 6. Conflict Prevention Constraint - prevents various scheduling conflicts
            constraints_applied.append(
                self.conflict_prevention_constraint.apply(teacher_theory_assignments, teacher_lab_assignments)
            )
            
            # Check if all constraints were applied successfully
            success = all(constraints_applied)
            
            if success:
                logger.info("All timetable constraints applied successfully")
            else:
                logger.error("Some constraints failed to apply")
            
            return success
            
        except Exception as e:
            logger.error(f"Error applying constraints: {e}")
            logger.exception("Constraint application error details")
            return False

# Backward compatibility alias
MacroblockTimetableConstraints = TimetableConstraints
