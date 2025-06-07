"""
Working Hours Constraint

This constraint ensures teachers don't exceed 21-hour weekly limit with minimal overhead.
OPTIMIZED: Streamlined calculation and constraint generation.
"""

import logging
from .constraint_base import ConstraintBase

logger = logging.getLogger(__name__)

class WorkingHoursConstraint(ConstraintBase):
    """Working hours constraint with minimal computational overhead."""
    
    def apply(self, teacher_theory_assignments, teacher_lab_assignments=None):
        """
        Apply working hours constraint with streamlined calculation.
        
        OPTIMIZATION: Direct calculation without redundant variable storage.
        """
        logger.info("Applying working hours constraint...")
        
        constraints_added = 0
        
        for teacher in self.teachers:
            teacher_instances = self.get_teacher_instances(teacher)
            if not teacher_instances:
                continue
            
            # OPTIMIZED: Direct variable collection in single pass
            weekly_hour_vars = []
            
            # Theory hours (1 hour per slot)
            for day_idx in range(self.num_days):
                for slot_idx in range(self.num_slots):
                    for room_id in self.classroom_ids:
                        weekly_hour_vars.append(
                            teacher_theory_assignments[teacher][day_idx][slot_idx][room_id]
                        )
            
            # Lab hours (2 hours per session) if enabled
            if teacher_lab_assignments is not None:
                for day_idx in range(self.num_days):
                    for session in self.lab_sessions:
                        for room_id in self.lab_ids:
                            lab_var = teacher_lab_assignments[teacher][day_idx][session][room_id]
                            # Each lab session = 2 hours
                            weekly_hour_vars.extend([lab_var, lab_var])
            
            # Apply 21-hour limit
            self.model.Add(sum(weekly_hour_vars) <= self.max_weekly_hours)
            constraints_added += 1
            
            # OPTIMIZED LOGGING: Calculate expected hours for verification
            expected_theory = sum(
                req['total_theory_hours'] 
                for req in [self.get_instance_requirements(inst['id']) for inst in teacher_instances]
            )
            expected_practical = sum(
                req['practical_hours'] 
                for req in [self.get_instance_requirements(inst['id']) for inst in teacher_instances]
            )
            
            logger.info(f"Teacher {teacher}: ≤{self.max_weekly_hours}h limit (expected: {expected_theory + expected_practical}h)")
        
        self.log_constraint_info("Working Hours Constraint", constraints_added)
        return True 