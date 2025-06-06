"""
Teacher Assignment Constraint

This constraint ensures that a teacher cannot be assigned to multiple 
rooms or sessions at the same time, preventing double-booking.
"""

import logging

logger = logging.getLogger(__name__)

class TeacherAssignmentConstraint:
    def __init__(self, model, teachers, teacher_course_assignments, classrooms, labs):
        """Initialize the teacher assignment constraint."""
        self.model = model
        self.teachers = teachers
        self.teacher_course_assignments = teacher_course_assignments
        self.classrooms = classrooms
        self.labs = labs
        
        # Pre-compute room IDs for efficiency
        self.classroom_ids = self.classrooms['id'].tolist()
        self.lab_ids = self.labs['id'].tolist()
        
        # Time structure
        self.days = ["tuesday", "wed", "thur", "fri", "sat"]
        self.num_days = len(self.days)
        self.num_slots = 11  # Theory slots per day
        
        # Lab sessions
        self.lab_sessions = {
            'L1': {'slots': [0, 1], 'time_range': '8:00 - 9:40'},
            'L2': {'slots': [2, 3], 'time_range': '9:50 - 11:30'},
            'L3': {'slots': [4, 5], 'time_range': '11:50 - 1:30'},
            'L4': {'slots': [6, 7], 'time_range': '1:50 - 3:30'},
            'L5': {'slots': [8, 9], 'time_range': '3:50 - 5:30'},
            'L6': {'slots': [10, 11], 'time_range': '5:30 - 7:10'}
        }
    
    def apply(self, teacher_theory_assignments, teacher_lab_assignments=None):
        """
        Apply teacher assignment constraint to prevent double-booking.
        
        This constraint ensures that:
        1. A teacher cannot be in multiple classrooms in the same time slot
        2. A teacher cannot be in multiple labs in the same lab session
        3. A teacher cannot have overlapping theory and lab assignments
        """
        logger.info("Applying teacher assignment constraint...")
        
        # Constraint 1: Teacher cannot be in multiple classrooms at the same time
        for teacher in self.teachers:
            for day_idx in range(self.num_days):
                for slot_idx in range(self.num_slots):
                    # Theory constraint - at most one classroom per slot
                    theory_vars = [teacher_theory_assignments[teacher][day_idx][slot_idx][room_id] 
                                 for room_id in self.classroom_ids]
                    self.model.Add(sum(theory_vars) <= 1)
        
        # Constraint 2: Teacher cannot be in multiple labs at the same session (if lab assignments provided)
        if teacher_lab_assignments is not None:
            for teacher in self.teachers:
                for day_idx in range(self.num_days):
                    for session in self.lab_sessions.keys():
                        # Lab constraint - at most one lab per session
                        lab_vars = [teacher_lab_assignments[teacher][day_idx][session][room_id] 
                                   for room_id in self.lab_ids]
                        self.model.Add(sum(lab_vars) <= 1)
        
        # Constraint 3: Teacher cannot have overlapping theory and lab assignments
        if teacher_lab_assignments is not None:
            for teacher in self.teachers:
                for day_idx in range(self.num_days):
                    for session_name, session_info in self.lab_sessions.items():
                        lab_session_slots = session_info['slots']  # e.g., [0, 1] for L1
                        
                        # Get lab assignment variables for this session
                        lab_vars = [teacher_lab_assignments[teacher][day_idx][session_name][room_id] 
                                   for room_id in self.lab_ids]
                        lab_assigned = sum(lab_vars)
                        
                        # Get theory assignment variables for overlapping slots
                        theory_vars = []
                        for slot_idx in lab_session_slots:
                            if slot_idx < self.num_slots:  # Ensure slot is within theory time range
                                for room_id in self.classroom_ids:
                                    theory_vars.append(
                                        teacher_theory_assignments[teacher][day_idx][slot_idx][room_id]
                                    )
                        
                        # If teacher has lab assignment, cannot have overlapping theory assignments
                        if theory_vars:
                            theory_assigned = sum(theory_vars)
                            # Cannot have both lab and theory assignments in overlapping times
                            self.model.Add(lab_assigned + theory_assigned <= 1)
        
        logger.info("Teacher assignment constraint applied successfully")
        return True 