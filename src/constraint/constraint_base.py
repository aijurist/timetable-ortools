"""
Constraint Base Class

This base class consolidates common data structures and variables used across all constraints
to reduce redundancy and improve performance.
"""

import logging

logger = logging.getLogger(__name__)

class ConstraintBase:
    """Base class for constraints with shared data structures."""
    
    def __init__(self, model, teachers, teacher_course_assignments, classrooms, labs):
        """Initialize shared constraint data structures."""
        self.model = model
        self.teachers = teachers
        self.teacher_course_assignments = teacher_course_assignments
        self.classrooms = classrooms
        self.labs = labs
        
        # Pre-computed efficient data structures (shared across all constraints)
        self._setup_shared_data_structures()
        
        # Create shared instance tracking (used by multiple constraints)
        self._setup_instance_tracking()
    
    def _setup_shared_data_structures(self):
        """Setup efficient shared data structures used by multiple constraints."""
        # Room ID lists (pre-computed once)
        self.classroom_ids = self.classrooms['id'].tolist()
        self.lab_ids = self.labs['id'].tolist()
        
        # Time structure constants
        self.days = ["tuesday", "wed", "thur", "fri", "sat"]
        self.num_days = len(self.days)
        self.num_slots = 11  # Theory slots per day
        
        # Lab sessions (simplified structure)
        self.lab_sessions = ['L1', 'L2', 'L3', 'L4', 'L5', 'L6']
        self.num_lab_sessions = len(self.lab_sessions)
        
        # Lab session time mappings (only when needed)
        self._lab_time_slots = {
            'L1': [0, 1], 'L2': [2, 3], 'L3': [4, 5],
            'L4': [6, 7], 'L5': [8, 9], 'L6': [10, 11]
        }
        
        # Working hours configuration
        self.max_weekly_hours = 21
        self.theory_slot_hours = 1
        self.lab_session_hours = 2
    
    def _setup_instance_tracking(self):
        """Setup efficient instance tracking structures."""
        # Create efficient instance lookup tables
        self.teacher_instances = {}
        self.instance_requirements = {}
        self.instance_to_teacher = {}
        
        for teacher, instances in self.teacher_course_assignments.items():
            self.teacher_instances[teacher] = instances
            
            for instance in instances:
                instance_id = instance['id']
                self.instance_to_teacher[instance_id] = teacher
                
                # Store instance requirements efficiently
                self.instance_requirements[instance_id] = {
                    'lecture_hours': instance['lecture_hours'],
                    'tutorial_hours': instance['tutorial_hours'],
                    'practical_hours': instance['practical_hours'],
                    'total_theory_hours': instance['lecture_hours'] + instance['tutorial_hours'],
                    'course_code': instance['course_code'],
                    'student_count': instance['student_count']
                }
    
    def get_teacher_instances(self, teacher):
        """Get all instances for a teacher efficiently."""
        return self.teacher_instances.get(teacher, [])
    
    def get_instance_requirements(self, instance_id):
        """Get requirements for a specific instance efficiently."""
        return self.instance_requirements.get(instance_id, {})
    
    def get_teacher_for_instance(self, instance_id):
        """Get teacher for a specific instance efficiently."""
        return self.instance_to_teacher.get(instance_id)
    
    def get_lab_time_slots(self, session):
        """Get time slots for a lab session."""
        return self._lab_time_slots.get(session, [])
    
    def log_constraint_info(self, constraint_name, constraints_added):
        """Standard logging for constraint application."""
        logger.info(f"{constraint_name} applied: {constraints_added} constraints added") 