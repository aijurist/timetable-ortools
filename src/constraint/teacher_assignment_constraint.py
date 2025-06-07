"""
Teacher Assignment Constraint

This constraint prevents teacher double-booking with minimal redundant constraints.
OPTIMIZED: Streamlined constraint generation while maintaining full functionality.
"""

import logging
from .constraint_base import ConstraintBase

logger = logging.getLogger(__name__)

class TeacherAssignmentConstraint(ConstraintBase):
    """Teacher assignment constraint with minimal constraint overhead."""
    
    def apply(self, teacher_theory_assignments, teacher_lab_assignments=None):
        """
        Apply teacher assignment constraint to prevent double-booking.
        
        OPTIMIZATION: Streamlined constraint generation with improved efficiency.
        """
        logger.info("Applying teacher assignment constraint...")
        
        total_constraints_added = 0
        
        # OPTIMIZED: Single loop for all theory double-booking constraints
        for teacher in self.teachers:
            for day_idx in range(self.num_days):
                for slot_idx in range(self.num_slots):
                    # Theory constraint: at most one classroom per slot
                    theory_vars = [
                        teacher_theory_assignments[teacher][day_idx][slot_idx][room_id]
                        for room_id in self.classroom_ids
                    ]
                    self.model.Add(sum(theory_vars) <= 1)
                    total_constraints_added += 1
        
        # Lab constraints (if enabled)
        if teacher_lab_assignments is not None:
            for teacher in self.teachers:
                for day_idx in range(self.num_days):
                    for session in self.lab_sessions:
                        # Lab constraint: at most one lab per session
                        lab_vars = [
                            teacher_lab_assignments[teacher][day_idx][session][room_id]
                            for room_id in self.lab_ids
                        ]
                        self.model.Add(sum(lab_vars) <= 1)
                        total_constraints_added += 1
            
            # OPTIMIZED: Theory-lab overlap prevention (only for overlapping slots)
            overlap_constraints = 0
            for teacher in self.teachers:
                for day_idx in range(self.num_days):
                    for session in self.lab_sessions:
                        # Get theory slots that overlap with this lab session
                        overlap_slots = self.get_lab_time_slots(session)
                        
                        # Lab assignment for this session
                        lab_vars = [
                            teacher_lab_assignments[teacher][day_idx][session][room_id]
                            for room_id in self.lab_ids
                        ]
                        lab_assigned = sum(lab_vars)
                        
                        # Theory assignments in overlapping slots
                        for slot_idx in overlap_slots:
                            if slot_idx < self.num_slots:
                                theory_vars = [
                                    teacher_theory_assignments[teacher][day_idx][slot_idx][room_id]
                                    for room_id in self.classroom_ids
                                ]
                                theory_assigned = sum(theory_vars)
                                
                                # Prevent overlap: lab + theory <= 1
                                self.model.Add(lab_assigned + theory_assigned <= 1)
                                overlap_constraints += 1
                                total_constraints_added += 1
            
            logger.info(f"Added {overlap_constraints} theory-lab overlap prevention constraints")
        
        # OPTIMIZED LOGGING: Summary statistics
        multi_instance_teachers = sum(
            1 for teacher in self.teachers 
            if len(self.get_teacher_instances(teacher)) > 1
        )
        
        if multi_instance_teachers > 0:
            logger.info(f"Constraint protects {multi_instance_teachers} teachers with multiple instances")
        
        self.log_constraint_info("Teacher Assignment Constraint", total_constraints_added)
        return True 