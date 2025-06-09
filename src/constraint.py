"""
Individual Constraint Classes

This module contains individual constraint classes for the timetable scheduler.
Each class implements a specific type of constraint.
"""

import logging

logger = logging.getLogger(__name__)

class BaseConstraint:
    """Base class for all constraints."""
    def __init__(self, model, teachers, teacher_course_assignments, classrooms, labs):
        self.model = model
        self.teachers = teachers
        self.teacher_course_assignments = teacher_course_assignments
        self.classrooms = classrooms
        self.labs = labs
        
    def apply(self, teacher_theory_assignments, teacher_lab_assignments=None):
        """Apply the constraint to the model."""
        raise NotImplementedError("Subclasses must implement this method")

class CourseHoursConstraint(BaseConstraint):
    """Ensures each course gets its required hours."""
    def apply(self, teacher_theory_assignments, teacher_lab_assignments=None):
        logger.info("Applying Course Hours Constraint")
        # TODO: Implement the constraint logic
        return True

class TeacherAssignmentConstraint(BaseConstraint):
    """Prevents teacher double-booking."""
    def apply(self, teacher_theory_assignments, teacher_lab_assignments=None):
        logger.info("Applying Teacher Assignment Constraint")
        # TODO: Implement the constraint logic
        return True

class RoomAssignmentConstraint(BaseConstraint):
    """Prevents room conflicts."""
    def apply(self, teacher_theory_assignments, teacher_lab_assignments=None):
        logger.info("Applying Room Assignment Constraint")
        # TODO: Implement the constraint logic
        return True

class WorkingHoursConstraint(BaseConstraint):
    """Limits teacher workload."""
    def apply(self, teacher_theory_assignments, teacher_lab_assignments=None):
        logger.info("Applying Working Hours Constraint")
        # TODO: Implement the constraint logic
        return True

class LabAssignmentConstraint(BaseConstraint):
    """Handles lab scheduling."""
    def apply(self, teacher_theory_assignments, teacher_lab_assignments=None):
        logger.info("Applying Lab Assignment Constraint")
        # TODO: Implement the constraint logic
        return True

class ConflictPreventionConstraint(BaseConstraint):
    """Prevents various scheduling conflicts."""
    def apply(self, teacher_theory_assignments, teacher_lab_assignments=None):
        logger.info("Applying Conflict Prevention Constraint")
        # TODO: Implement the constraint logic
        return True

class CourseGroupConstraint(BaseConstraint):
    """Groups courses by semester and department."""
    def apply(self, teacher_theory_assignments, teacher_lab_assignments=None):
        logger.info("Applying Course Group Constraint")
        # TODO: Implement the constraint logic
        return True
        
    def get_group_info_for_course_instance(self, teacher_id, instance_id):
        """Get group information for a course instance."""
        # Find the instance in the teacher's assignments
        if teacher_id not in self.teacher_course_assignments:
            return {'group_name': 'Unknown', 'group_index': 0}
            
        for instance in self.teacher_course_assignments[teacher_id]:
            if instance['id'] == instance_id:
                # Create group based on semester and department
                semester = instance.get('semester', 0)
                dept = instance.get('course_dept', 'Unknown')
                group_name = f"{dept}_{semester}"
                
                return {
                    'group_name': group_name,
                    'group_index': semester,
                    'department': dept,
                    'semester': semester
                }
                
        return {'group_name': 'Unknown', 'group_index': 0} 