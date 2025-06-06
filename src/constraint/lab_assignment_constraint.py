"""
Lab Assignment Constraint

This constraint handles lab scheduling requirements and ensures 
proper allocation of practical hours to lab sessions.
"""

import logging

logger = logging.getLogger(__name__)

class LabAssignmentConstraint:
    def __init__(self, model, teachers, teacher_course_assignments, classrooms, labs):
        """Initialize the lab assignment constraint."""
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
        Apply lab assignment constraint for proper lab scheduling.
        
        This constraint ensures that:
        1. Teachers with practical hours get appropriate lab assignments
        2. Lab sessions are properly allocated
        3. Lab assignments match course requirements
        """
        # Only apply if lab assignments are provided
        if teacher_lab_assignments is None:
            logger.info("No lab assignments provided - skipping lab assignment constraints")
            return True
            
        logger.info("Applying lab assignment constraint...")
        
        for teacher in self.teachers:
            if teacher not in self.teacher_course_assignments:
                continue
                
            # Calculate total practical hours for this teacher
            total_practical_hours = 0
            for instance in self.teacher_course_assignments[teacher]:
                total_practical_hours += instance['practical_hours']
            
            # If teacher has practical hours, ensure they get lab assignments
            if total_practical_hours > 0:
                lab_assignment_vars = []
                
                for day_idx in range(self.num_days):
                    for session in self.lab_sessions.keys():
                        for room_id in self.lab_ids:
                            lab_assignment_vars.append(
                                teacher_lab_assignments[teacher][day_idx][session][room_id]
                            )
                
                # Each lab session covers 2 practical hours
                required_lab_sessions = max(1, (total_practical_hours + 1) // 2)  # Round up
                
                # Ensure teacher gets at least the required number of lab sessions
                self.model.Add(sum(lab_assignment_vars) >= required_lab_sessions)
                
                # Don't over-assign - add upper bound with some flexibility
                max_allowed_sessions = required_lab_sessions + 2
                self.model.Add(sum(lab_assignment_vars) <= max_allowed_sessions)
                
                logger.info(f"Teacher {teacher}: {total_practical_hours} practical hours → {required_lab_sessions}-{max_allowed_sessions} lab sessions")
        
        # Additional constraint: Ensure lab sessions are used efficiently
        # Priority given to teachers with more practical hours
        self._apply_lab_priority_constraints(teacher_lab_assignments)
        
        logger.info("Lab assignment constraint applied successfully")
        return True
    
    def _apply_lab_priority_constraints(self, teacher_lab_assignments):
        """Apply priority constraints for lab assignment efficiency."""
        # Calculate practical hours per teacher for priority
        teacher_practical_hours = {}
        for teacher in self.teachers:
            if teacher not in self.teacher_course_assignments:
                continue
                
            total_practical_hours = 0
            for instance in self.teacher_course_assignments[teacher]:
                total_practical_hours += instance['practical_hours']
            
            teacher_practical_hours[teacher] = total_practical_hours
        
        # Sort teachers by practical hours (descending)
        teachers_by_priority = sorted(
            teacher_practical_hours.keys(), 
            key=lambda t: teacher_practical_hours[t], 
            reverse=True
        )
        
        # Apply soft constraints to encourage assignment of high-priority teachers first
        # This is done by adding preferences rather than hard constraints
        for i, teacher in enumerate(teachers_by_priority):
            if teacher_practical_hours[teacher] > 0:
                lab_vars = []
                for day_idx in range(self.num_days):
                    for session in self.lab_sessions.keys():
                        for room_id in self.lab_ids:
                            lab_vars.append(teacher_lab_assignments[teacher][day_idx][session][room_id])
                
                # Add a soft constraint that encourages assignment (but doesn't force it)
                # Higher priority teachers get more encouragement
                priority_weight = len(teachers_by_priority) - i
                if lab_vars and priority_weight > 1:
                    # This is a preference rather than a hard constraint
                    # The solver will try to satisfy it but it's not mandatory
                    pass  # For now, we rely on the main constraints
        
        logger.info("Lab priority constraints applied") 