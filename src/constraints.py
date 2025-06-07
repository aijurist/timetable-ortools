"""
Main Constraints Module

This module coordinates all individual constraint classes to create
a comprehensive timetable scheduling constraint system.

OPTIMIZED: Now uses streamlined constraint implementations for better performance.
"""

import logging
from src.constraint import (
    CourseHoursConstraint,
    TeacherAssignmentConstraint,
    RoomAssignmentConstraint,
    WorkingHoursConstraint,
    LabAssignmentConstraint,
    ConflictPreventionConstraint,
    CourseGroupConstraint
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
        
        # Initialize individual constraint handlers (now using optimized implementations)
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
        self.course_group_constraint = CourseGroupConstraint(
            model, teachers, teacher_course_assignments, classrooms, labs
        )
        
        logger.info("TimetableConstraints initialized with optimized constraint handlers")
    
    def apply_all_constraints(self, teacher_theory_assignments, teacher_lab_assignments=None):
        """Apply all timetable constraints using optimized constraint handlers."""
        logger.info("Applying all timetable constraints with optimized implementations...")
        
        try:
            # Apply constraints in logical order
            constraints_applied = []
            
            # 1. Course Hours Constraint - ensures proper hour allocation (OPTIMIZED)
            constraints_applied.append(
                self.course_hours_constraint.apply(teacher_theory_assignments, teacher_lab_assignments)
            )
            
            # 2. Teacher Assignment Constraint - prevents teacher double-booking (OPTIMIZED)
            constraints_applied.append(
                self.teacher_assignment_constraint.apply(teacher_theory_assignments, teacher_lab_assignments)
            )
            
            # 3. Room Assignment Constraint - prevents room conflicts
            constraints_applied.append(
                self.room_assignment_constraint.apply(teacher_theory_assignments, teacher_lab_assignments)
            )
            
            # 4. Working Hours Constraint - limits teacher workload (OPTIMIZED)
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
            
            # 7. Course Group Constraint - groups courses by semester and department
            constraints_applied.append(
                self.course_group_constraint.apply(teacher_theory_assignments, teacher_lab_assignments)
            )
            
            # Check if all constraints were applied successfully
            success = all(constraints_applied)
            
            if success:
                logger.info("All optimized timetable constraints applied successfully")
                self._log_optimization_summary()
            else:
                logger.error("Some constraints failed to apply")
            
            return success
            
        except Exception as e:
            logger.error(f"Error applying constraints: {e}")
            logger.exception("Constraint application error details")
            return False
    
    def _log_optimization_summary(self):
        """Log optimization summary for the constraint system."""
        logger.info("=== OPTIMIZATION SUMMARY ===")
        logger.info("✅ Course Hours Constraint: Optimized - eliminates redundant variables")
        logger.info("✅ Teacher Assignment Constraint: Optimized - streamlined constraint generation")
        logger.info("✅ Working Hours Constraint: Optimized - direct calculation, minimal overhead")
        logger.info("✅ Room Assignment Constraint: Standard implementation (already efficient)")
        logger.info("✅ Lab Assignment Constraint: Standard implementation (already efficient)")
        logger.info("✅ Conflict Prevention Constraint: Standard implementation (already efficient)")
        logger.info("✅ Course Group Constraint: Standard implementation (already efficient)")
        logger.info("📊 Performance Impact: Reduced variable count, faster constraint generation")
        logger.info("============================")

# Backward compatibility alias
MacroblockTimetableConstraints = TimetableConstraints
