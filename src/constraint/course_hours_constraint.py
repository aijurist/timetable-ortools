"""
Course Hours Constraint

This constraint ensures that each course gets allocated the correct number of 
lecture, tutorial, and practical hours based on its course definition.
"""

import logging

logger = logging.getLogger(__name__)

class CourseHoursConstraint:
    def __init__(self, model, teachers, teacher_course_assignments, classrooms, labs):
        """Initialize the course hours constraint."""
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
        Apply course hours constraint to ensure proper hour allocation.
        
        This constraint ensures that:
        1. Teachers get assigned slots based on their course requirements
        2. Lecture hours are allocated in theory slots
        3. Practical hours are allocated in lab sessions
        4. Tutorial hours are allocated appropriately
        """
        logger.info("Applying course hours constraint...")
        
        for teacher in self.teachers:
            if teacher not in self.teacher_course_assignments:
                continue
                
            # Calculate total required hours for this teacher
            total_lecture_hours = 0
            total_tutorial_hours = 0
            total_practical_hours = 0
            
            for instance in self.teacher_course_assignments[teacher]:
                total_lecture_hours += instance['lecture_hours']
                total_tutorial_hours += instance['tutorial_hours']
                total_practical_hours += instance['practical_hours']
            
            # Constraint 1: Theory assignments should match lecture + tutorial hours
            theory_assignments = []
            for day_idx in range(self.num_days):
                for slot_idx in range(self.num_slots):
                    for room_id in self.classroom_ids:
                        theory_assignments.append(
                            teacher_theory_assignments[teacher][day_idx][slot_idx][room_id]
                        )
            
            # Ensure teacher gets assigned theory slots equal to lecture + tutorial hours
            required_theory_slots = total_lecture_hours + total_tutorial_hours
            if required_theory_slots > 0:
                self.model.Add(sum(theory_assignments) >= required_theory_slots)
                self.model.Add(sum(theory_assignments) <= required_theory_slots + 2)  # Allow some flexibility
                
                logger.info(f"Teacher {teacher}: Required {required_theory_slots} theory slots")
            
            # Constraint 2: Lab assignments should match practical hours (if lab assignments provided)
            if teacher_lab_assignments is not None and total_practical_hours > 0:
                lab_assignments = []
                for day_idx in range(self.num_days):
                    for session in self.lab_sessions.keys():
                        for room_id in self.lab_ids:
                            lab_assignments.append(
                                teacher_lab_assignments[teacher][day_idx][session][room_id]
                            )
                
                # Each lab session = 2 practical hours, so practical_hours/2 sessions needed
                required_lab_sessions = max(1, total_practical_hours // 2)
                self.model.Add(sum(lab_assignments) >= required_lab_sessions)
                self.model.Add(sum(lab_assignments) <= required_lab_sessions + 1)  # Allow some flexibility
                
                logger.info(f"Teacher {teacher}: Required {required_lab_sessions} lab sessions for {total_practical_hours} practical hours")
        
        logger.info("Course hours constraint applied successfully")
        return True 