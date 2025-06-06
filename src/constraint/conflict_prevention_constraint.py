"""
Conflict Prevention Constraint

This constraint prevents scheduling conflicts between different types of 
assignments and ensures proper resource allocation.
"""

import logging

logger = logging.getLogger(__name__)

class ConflictPreventionConstraint:
    def __init__(self, model, teachers, teacher_course_assignments, classrooms, labs):
        """Initialize the conflict prevention constraint."""
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
        Apply conflict prevention constraints.
        
        This constraint ensures that:
        1. No time conflicts between theory and lab assignments
        2. Course instance integrity is maintained
        3. Room type matching (theory courses in classrooms, practicals in labs)
        """
        logger.info("Applying conflict prevention constraint...")
        
        # Constraint 1: Prevent time conflicts between theory and lab assignments
        if teacher_lab_assignments is not None:
            self._prevent_theory_lab_time_conflicts(teacher_theory_assignments, teacher_lab_assignments)
        
        # Constraint 2: Ensure course instance integrity
        self._ensure_course_instance_integrity(teacher_theory_assignments, teacher_lab_assignments)
        
        # Constraint 3: Room type matching
        self._ensure_room_type_matching(teacher_theory_assignments, teacher_lab_assignments)
        
        logger.info("Conflict prevention constraint applied successfully")
        return True
    
    def _prevent_theory_lab_time_conflicts(self, teacher_theory_assignments, teacher_lab_assignments):
        """Prevent time conflicts between theory and lab assignments."""
        logger.info("Preventing theory-lab time conflicts...")
        
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
        
        logger.info("Theory-lab time conflicts prevented")
    
    def _ensure_course_instance_integrity(self, teacher_theory_assignments, teacher_lab_assignments):
        """Ensure that course instances maintain integrity across assignments."""
        logger.info("Ensuring course instance integrity...")
        
        # This constraint can be enhanced to ensure that:
        # - A course instance's theory and practical components are properly linked
        # - The same course instance doesn't get split inappropriately
        # - Course dependencies are respected
        
        # For now, we implement basic integrity checks
        for teacher in self.teachers:
            if teacher not in self.teacher_course_assignments:
                continue
            
            # Ensure that teachers with multiple course instances get appropriate distribution
            course_instances = self.teacher_course_assignments[teacher]
            if len(course_instances) > 1:
                # Add soft constraints to encourage balanced distribution
                # This prevents one course from dominating all time slots
                
                # Calculate theory requirements per course instance
                for instance in course_instances:
                    required_theory_hours = instance['lecture_hours'] + instance['tutorial_hours']
                    required_practical_hours = instance['practical_hours']
                    
                    if required_theory_hours > 0:
                        # Theory assignments should be somewhat distributed across days
                        daily_theory_assignments = []
                        for day_idx in range(self.num_days):
                            day_assignments = []
                            for slot_idx in range(self.num_slots):
                                for room_id in self.classroom_ids:
                                    day_assignments.append(
                                        teacher_theory_assignments[teacher][day_idx][slot_idx][room_id]
                                    )
                            daily_theory_assignments.append(sum(day_assignments))
                        
                        # Soft constraint: try to distribute across multiple days
                        # At least 2 days should have assignments if teacher has >= 4 theory hours
                        if required_theory_hours >= 4:
                            # Create binary variables for days with assignments
                            day_has_assignment = []
                            for day_idx in range(self.num_days):
                                day_var = self.model.NewBoolVar(f'teacher_{teacher}_day_{day_idx}_has_theory')
                                # day_var = 1 if teacher has any assignment on this day
                                self.model.Add(daily_theory_assignments[day_idx] >= day_var)
                                self.model.Add(daily_theory_assignments[day_idx] <= 
                                             self.num_slots * len(self.classroom_ids) * day_var)
                                day_has_assignment.append(day_var)
                            
                            # Encourage assignments on at least 2 days
                            self.model.Add(sum(day_has_assignment) >= min(2, required_theory_hours))
        
        logger.info("Course instance integrity ensured")
    
    def _ensure_room_type_matching(self, teacher_theory_assignments, teacher_lab_assignments):
        """Ensure that course types are matched with appropriate room types."""
        logger.info("Ensuring room type matching...")
        
        # This constraint ensures that:
        # - Theory courses (lectures, tutorials) are assigned to classrooms
        # - Practical courses are assigned to labs
        # - Room capacity is appropriate for course size
        
        # Since we're already structuring assignments by room type in the scheduler,
        # this constraint is mostly about validation and capacity checking
        
        # Constraint: Theory assignments should only use classrooms
        # (This is implicitly enforced by the assignment variable structure)
        
        # Constraint: Lab assignments should only use lab rooms  
        # (This is implicitly enforced by the assignment variable structure)
        
        # Constraint: Room capacity should accommodate course size
        self._check_room_capacity_constraints(teacher_theory_assignments, teacher_lab_assignments)
        
        logger.info("Room type matching ensured")
    
    def _check_room_capacity_constraints(self, teacher_theory_assignments, teacher_lab_assignments):
        """Check that room capacity can accommodate course requirements."""
        logger.info("Checking room capacity constraints...")
        
        # For each teacher assignment, ensure room capacity is sufficient
        for teacher in self.teachers:
            if teacher not in self.teacher_course_assignments:
                continue
            
            # Get maximum student count for this teacher's courses
            max_student_count = 0
            for instance in self.teacher_course_assignments[teacher]:
                student_count = instance.get('student_count', 0)
                max_student_count = max(max_student_count, student_count)
            
            if max_student_count > 0:
                # Add some flexibility - allow 10% capacity margin for smaller classes
                capacity_margin = max(5, int(max_student_count * 0.1))
                effective_requirement = max_student_count - capacity_margin
                
                # Theory assignments - check classroom capacity with flexibility
                for day_idx in range(self.num_days):
                    for slot_idx in range(self.num_slots):
                        for room_id in self.classroom_ids:
                            assignment_var = teacher_theory_assignments[teacher][day_idx][slot_idx][room_id]
                            
                            # Get room capacity
                            room_data = self.classrooms[self.classrooms['id'] == room_id]
                            if not room_data.empty:
                                room_capacity = room_data['room_max_cap'].iloc[0]
                                
                                # Only prevent assignment if room is significantly too small
                                if room_capacity < effective_requirement:
                                    self.model.Add(assignment_var == 0)
                
                # Lab assignments - check lab capacity with flexibility (if lab assignments provided)
                if teacher_lab_assignments is not None:
                    for day_idx in range(self.num_days):
                        for session in self.lab_sessions.keys():
                            for room_id in self.lab_ids:
                                assignment_var = teacher_lab_assignments[teacher][day_idx][session][room_id]
                                
                                # Get lab capacity
                                lab_data = self.labs[self.labs['id'] == room_id]
                                if not lab_data.empty:
                                    lab_capacity = lab_data['room_max_cap'].iloc[0]
                                    
                                    # Only prevent assignment if lab is significantly too small
                                    if lab_capacity < effective_requirement:
                                        self.model.Add(assignment_var == 0)
        
        logger.info("Room capacity constraints checked") 