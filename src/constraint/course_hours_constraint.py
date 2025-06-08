"""
Course Hours Constraint

This constraint ensures correct hour allocation per course instance with minimal variables.
OPTIMIZED: Eliminates redundant instance variables while maintaining instance-aware logic.
GROUP-BASED COMPATIBLE: Works with the new group-based scheduling approach.
"""

import logging
from .constraint_base import ConstraintBase

logger = logging.getLogger(__name__)

class CourseHoursConstraint(ConstraintBase):
    """Course hours constraint with minimal variable creation."""
    
    def apply(self, teacher_theory_assignments, teacher_lab_assignments=None):
        """
        Apply course hours constraint ensuring proper hour allocation.
        
        OPTIMIZATION: Uses existing teacher assignment variables instead of creating
        redundant instance variables, while maintaining instance-aware logic.
        
        GROUP-BASED COMPATIBLE: With group-based scheduling, this constraint only ensures
        that total required hours per teacher are available across all groups.
        Post-processing will handle the actual hour distribution.
        """
        logger.info("Applying course hours constraint...")
        
        total_constraints_added = 0
        lab_assignments_enabled = teacher_lab_assignments is not None
        
        if not lab_assignments_enabled:
            logger.info("Lab assignments disabled - theory hours only")
        
        # Process each teacher's instances efficiently
        for teacher in self.teachers:
            teacher_instances = self.get_teacher_instances(teacher)
            if not teacher_instances:
                continue
            
            # OPTIMIZATION: Calculate total required hours per teacher (sum of all instances)
            total_theory_hours_required = sum(
                self.get_instance_requirements(inst['id'])['total_theory_hours']
                for inst in teacher_instances
            )
            
            total_practical_hours_required = sum(
                self.get_instance_requirements(inst['id'])['practical_hours']
                for inst in teacher_instances
            )
            
            if total_theory_hours_required > 0:
                # OPTIMIZED CONSTRAINT: Teacher's total assignments = sum of instance requirements
                teacher_theory_vars = []
                for day_idx in range(self.num_days):
                    for slot_idx in range(self.num_slots):
                        for room_id in self.classroom_ids:
                            teacher_theory_vars.append(
                                teacher_theory_assignments[teacher][day_idx][slot_idx][room_id]
                            )
                
                # Single constraint instead of multiple instance variables
                self.model.Add(sum(teacher_theory_vars) == total_theory_hours_required)
                total_constraints_added += 1
                
                logger.info(f"Teacher {teacher}: EXACTLY {total_theory_hours_required} theory hours required")
            
            # Lab hours constraint (if enabled)
            if lab_assignments_enabled and total_practical_hours_required > 0:
                teacher_lab_vars = []
                for day_idx in range(self.num_days):
                    for session in self.lab_sessions:
                        for room_id in self.lab_ids:
                            teacher_lab_vars.append(
                                teacher_lab_assignments[teacher][day_idx][session][room_id]
                            )
                
                # Convert practical hours to lab sessions (each session = 2 hours)
                total_lab_sessions_required = sum(
                    max(1, (self.get_instance_requirements(inst['id'])['practical_hours'] + 1) // 2)
                    for inst in teacher_instances
                    if self.get_instance_requirements(inst['id'])['practical_hours'] > 0
                )
                
                self.model.Add(sum(teacher_lab_vars) == total_lab_sessions_required)
                total_constraints_added += 1
                
                logger.info(f"Teacher {teacher}: EXACTLY {total_lab_sessions_required} lab sessions required")
        
        self.log_constraint_info("Course Hours Constraint", total_constraints_added)
        return True 