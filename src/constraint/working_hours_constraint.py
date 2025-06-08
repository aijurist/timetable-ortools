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
        Apply working hours constraint with HIGHLY OPTIMIZED calculation.
        
        PERFORMANCE OPTIMIZATIONS:
        1. Process teachers in batches for better cache locality
        2. Pre-filter teachers that need constraints
        3. Use direct variable collection without intermediates
        4. Optimize memory access patterns
        5. Cache expected workload for validation
        """
        logger.info("Applying HIGHLY OPTIMIZED working hours constraint...")
        
        constraints_added = 0
        
        # OPTIMIZATION: Pre-filter teachers with assignments to reduce iterations
        teachers_with_assignments = []
        expected_hours = {}
        
        for teacher in self.teachers:
            teacher_instances = self.get_teacher_instances(teacher)
            if not teacher_instances:
                continue
            
            # OPTIMIZATION: Pre-calculate expected hours for each teacher
            theory_hours = sum(inst.get('lecture_hours', 0) + inst.get('tutorial_hours', 0) for inst in teacher_instances)
            practical_hours = sum(inst.get('practical_hours', 0) for inst in teacher_instances)
            total_expected = theory_hours + practical_hours
            
            if total_expected > 0:
                teachers_with_assignments.append(teacher)
                expected_hours[teacher] = {
                    'theory': theory_hours,
                    'practical': practical_hours,
                    'total': total_expected
                }
        
        # OPTIMIZATION: Process teachers in batches for better cache efficiency
        batch_size = 25  # Adjust based on teacher count
        for batch_start in range(0, len(teachers_with_assignments), batch_size):
            batch_end = min(batch_start + batch_size, len(teachers_with_assignments))
            teacher_batch = teachers_with_assignments[batch_start:batch_end]
            
            for teacher in teacher_batch:
                # OPTIMIZATION: Direct variable collection in single pass
                weekly_hour_vars = []
                
                # OPTIMIZATION: Collect theory hour variables by day for better cache locality
                for day_idx in range(self.num_days):
                    # Get day assignments once to improve cache hits
                    day_assignments = teacher_theory_assignments[teacher][day_idx]
                    
                    for slot_idx in range(self.num_slots):
                        # Get slot assignments once to improve cache hits
                        slot_assignments = day_assignments[slot_idx]
                        
                        # Add all room assignments for this slot
                        weekly_hour_vars.extend(slot_assignments.values())
                
                # Lab hours (2 hours per session) if enabled
                if teacher_lab_assignments is not None:
                    for day_idx in range(self.num_days):
                        # Get day lab assignments once to improve cache hits
                        day_lab_assignments = teacher_lab_assignments[teacher][day_idx]
                        
                        for session_name, session_info in self.lab_sessions.items():
                            # Get session assignments once to improve cache hits
                            if session_name in day_lab_assignments:
                                session_assignments = day_lab_assignments[session_name]
                                
                                # Add all lab assignments for this session
                                for lab_var in session_assignments.values():
                                    # Each lab session = 2 hours
                                    weekly_hour_vars.extend([lab_var, lab_var])
                
                # Apply 21-hour limit - only if there are variables to constrain
                if weekly_hour_vars:
                    self.model.Add(sum(weekly_hour_vars) <= self.max_weekly_hours)
                    constraints_added += 1
                    
                    # OPTIMIZED LOGGING: Log expected vs max workload
                    expected = expected_hours[teacher]
                    if expected['total'] > self.max_weekly_hours:
                        logger.warning(f"Teacher {teacher}: Expected {expected['total']}h ({expected['theory']}T+{expected['practical']}P) exceeds {self.max_weekly_hours}h limit!")
                    else:
                        logger.info(f"Teacher {teacher}: Expected {expected['total']}h ({expected['theory']}T+{expected['practical']}P) within {self.max_weekly_hours}h limit")
        
        logger.info(f"HIGHLY OPTIMIZED Working Hours Constraint: Added {constraints_added} constraints for {len(teachers_with_assignments)} teachers")
        
        return True 