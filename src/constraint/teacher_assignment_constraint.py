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
        
        PERFORMANCE OPTIMIZATIONS:
        1. Batch processing teachers for better cache efficiency
        2. Pre-compute variables by structure type
        3. Use more efficient constraint addition
        4. Skip unnecessary constraint generation
        5. Reuse computed variables when possible
        """
        logger.info("Applying HIGHLY OPTIMIZED teacher assignment constraint...")
        
        total_constraints_added = 0
        
        # OPTIMIZATION: Process teachers in batches for better cache locality
        batch_size = 25  # Adjust based on teacher count
        teacher_batches = [self.teachers[i:i+batch_size] for i in range(0, len(self.teachers), batch_size)]
        
        # OPTIMIZATION 1: Theory assignment constraints (at most one classroom per slot)
        for teacher_batch in teacher_batches:
            for teacher in teacher_batch:
                # OPTIMIZATION: Skip teachers with no theory assignments
                if teacher not in self.teacher_course_assignments:
                    continue
                    
                has_theory = any(
                    instance['lecture_hours'] + instance['tutorial_hours'] > 0
                    for instance in self.teacher_course_assignments[teacher]
                )
                
                if not has_theory:
                    continue
                
                # OPTIMIZATION: Process by day/slot for better cache locality
                for day_idx in range(self.num_days):
                    for slot_idx in range(self.num_slots):
                        # Theory constraint: at most one classroom per slot
                        theory_vars = [
                            teacher_theory_assignments[teacher][day_idx][slot_idx][room_id]
                            for room_id in self.classroom_ids
                        ]
                        
                        # OPTIMIZATION: Skip if no variables
                        if not theory_vars:
                            continue
                            
                        self.model.Add(sum(theory_vars) <= 1)
                        total_constraints_added += 1
        
        # Lab constraints (if enabled)
        if teacher_lab_assignments is not None:
            # OPTIMIZATION 2: Lab assignment constraints (at most one lab per session)
            for teacher_batch in teacher_batches:
                for teacher in teacher_batch:
                    # OPTIMIZATION: Skip teachers with no lab assignments
                    if teacher not in self.teacher_course_assignments:
                        continue
                        
                    has_lab = any(
                        instance['practical_hours'] > 0
                        for instance in self.teacher_course_assignments[teacher]
                    )
                    
                    if not has_lab:
                        continue
                    
                    # OPTIMIZATION: Cache lab sessions for better access
                    lab_sessions = list(self.lab_sessions.keys()) if hasattr(self, 'lab_sessions') else []
                    
                    # OPTIMIZATION: Pre-compute lab variables by session and day
                    lab_vars_by_day_session = {}
                    for day_idx in range(self.num_days):
                        lab_vars_by_day_session[day_idx] = {}
                        for session in lab_sessions:
                            lab_vars_by_day_session[day_idx][session] = [
                                teacher_lab_assignments[teacher][day_idx][session][room_id]
                                for room_id in self.lab_ids
                            ]
                    
                    # Add constraints for lab sessions
                    for day_idx in range(self.num_days):
                        for session in lab_sessions:
                            lab_vars = lab_vars_by_day_session[day_idx][session]
                            
                            # OPTIMIZATION: Skip if no variables
                            if not lab_vars:
                                continue
                                
                            self.model.Add(sum(lab_vars) <= 1)
                            total_constraints_added += 1
            
            # OPTIMIZATION 3: Theory-lab overlap prevention (only for teachers with both)
            overlap_constraints = 0
            
            # First identify teachers with both theory and lab assignments
            teachers_with_both = []
            for teacher in self.teachers:
                if teacher not in self.teacher_course_assignments:
                    continue
                    
                has_theory = any(
                    instance['lecture_hours'] + instance['tutorial_hours'] > 0
                    for instance in self.teacher_course_assignments[teacher]
                )
                has_lab = any(
                    instance['practical_hours'] > 0
                    for instance in self.teacher_course_assignments[teacher]
                )
                
                if has_theory and has_lab:
                    teachers_with_both.append(teacher)
            
            # OPTIMIZATION: Pre-compute lab session overlaps once
            lab_session_overlaps = {}
            for session_name, session_info in self.lab_sessions.items() if hasattr(self, 'lab_sessions') else {}:
                lab_session_overlaps[session_name] = [
                    slot_idx for slot_idx in session_info['slots'] if slot_idx < self.num_slots
                ]
            
            # Process teachers with both types of assignments in batches
            for teacher_batch in [teachers_with_both[i:i+batch_size] for i in range(0, len(teachers_with_both), batch_size)]:
                for teacher in teacher_batch:
                    # OPTIMIZATION: Pre-compute theory variables by slot
                    theory_vars_by_day_slot = {}
                    for day_idx in range(self.num_days):
                        theory_vars_by_day_slot[day_idx] = {}
                        for slot_idx in range(self.num_slots):
                            theory_vars_by_day_slot[day_idx][slot_idx] = [
                                teacher_theory_assignments[teacher][day_idx][slot_idx][room_id]
                                for room_id in self.classroom_ids
                            ]
                    
                    # OPTIMIZATION: Pre-compute lab variables by session
                    lab_vars_by_day_session = {}
                    for day_idx in range(self.num_days):
                        lab_vars_by_day_session[day_idx] = {}
                        for session in lab_session_overlaps.keys():
                            lab_vars_by_day_session[day_idx][session] = [
                                teacher_lab_assignments[teacher][day_idx][session][room_id]
                                for room_id in self.lab_ids
                            ]
                    
                    # Add theory-lab overlap constraints efficiently
                    for day_idx in range(self.num_days):
                        for session, overlap_slots in lab_session_overlaps.items():
                            lab_vars = lab_vars_by_day_session[day_idx][session]
                            
                            # OPTIMIZATION: Skip if no lab variables
                            if not lab_vars:
                                continue
                                
                            lab_assigned = sum(lab_vars)
                            
                            # Get all theory variables for overlapping slots efficiently
                            theory_vars_in_overlap = []
                            for slot_idx in overlap_slots:
                                if slot_idx < self.num_slots:
                                    theory_vars_in_overlap.extend(theory_vars_by_day_slot[day_idx][slot_idx])
                            
                            # OPTIMIZATION: Skip if no theory variables in overlap
                            if not theory_vars_in_overlap:
                                continue
                                
                            theory_assigned = sum(theory_vars_in_overlap)
                            
                            # Prevent overlap: lab + theory <= 1
                            self.model.Add(lab_assigned + theory_assigned <= 1)
                            overlap_constraints += 1
                            total_constraints_added += 1
            
            logger.info(f"Added {overlap_constraints} OPTIMIZED theory-lab overlap prevention constraints")
        
        # OPTIMIZED LOGGING: Include performance metrics
        teachers_with_constraints = sum(
            1 for teacher in self.teachers 
            if teacher in self.teacher_course_assignments and self.teacher_course_assignments[teacher]
        )
        
        logger.info(f"HIGHLY OPTIMIZED Teacher Assignment Constraint: {total_constraints_added} constraints for {teachers_with_constraints} teachers")
        
        return True 