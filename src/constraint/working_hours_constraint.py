"""
Working Hours Constraint

This constraint ensures that teachers don't exceed the maximum 
weekly working hours limit (21 hours per week).
"""

import logging

logger = logging.getLogger(__name__)

class WorkingHoursConstraint:
    def __init__(self, model, teachers, teacher_course_assignments, classrooms, labs):
        """Initialize the working hours constraint."""
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
        
        # Working hours configuration
        self.max_weekly_hours = 21
        self.theory_slot_hours = 1  # Each theory slot = 1 hour
        self.lab_session_hours = 2  # Each lab session = 2 hours
    
    def apply(self, teacher_theory_assignments, teacher_lab_assignments=None):
        """
        Apply working hours constraint to limit teacher workload.
        
        This constraint ensures that:
        1. Total weekly hours per teacher ≤ 21 hours
        2. Theory slots count as 1 hour each
        3. Lab sessions count as 2 hours each
        """
        logger.info("Applying working hours constraint...")
        
        for teacher in self.teachers:
            weekly_hour_vars = []
            
            # Count theory hours (1 hour per slot)
            for day_idx in range(self.num_days):
                for slot_idx in range(self.num_slots):
                    for room_id in self.classroom_ids:
                        theory_assignment = teacher_theory_assignments[teacher][day_idx][slot_idx][room_id]
                        # Each theory assignment = 1 hour
                        weekly_hour_vars.append(theory_assignment)
            
            # Count lab hours (2 hours per session) if lab assignments are provided
            if teacher_lab_assignments is not None:
                for day_idx in range(self.num_days):
                    for session in self.lab_sessions.keys():
                        for room_id in self.lab_ids:
                            lab_assignment = teacher_lab_assignments[teacher][day_idx][session][room_id]
                            # Each lab session = 2 hours, so add the assignment twice
                            weekly_hour_vars.extend([lab_assignment, lab_assignment])
            
            # Apply 21-hour weekly limit
            total_hours = sum(weekly_hour_vars)
            self.model.Add(total_hours <= self.max_weekly_hours)
            
            logger.info(f"Applied {self.max_weekly_hours}-hour weekly limit for Teacher {teacher}")
        
        logger.info("Working hours constraint applied successfully")
        return True 