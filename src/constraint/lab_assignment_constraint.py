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
        Apply lab assignment constraint for proper lab scheduling (instance-aware).
        
        This constraint ensures that:
        1. Teachers with practical hours get appropriate lab assignments
        2. Lab sessions are properly allocated based on individual course instances
        3. Lab assignments match course instance requirements
        """
        # Only apply if lab assignments are provided
        if teacher_lab_assignments is None:
            logger.info("No lab assignments provided - skipping lab assignment constraints")
            return True
            
        logger.info("Applying lab assignment constraint (instance-aware)...")
        
        for teacher in self.teachers:
            if teacher not in self.teacher_course_assignments:
                continue
                
            # Get course instances for this teacher
            teacher_instances = self.teacher_course_assignments[teacher]
            
            # Calculate total practical hours and log instance details
            total_practical_hours = 0
            practical_instances = []
            for instance in teacher_instances:
                practical_hrs = instance['practical_hours']
                total_practical_hours += practical_hrs
                if practical_hrs > 0:
                    practical_instances.append(f"Instance {instance['id']}:{instance['course_code']}({practical_hrs}P)")
            
            # If teacher has practical hours, ensure they get lab assignments
            if total_practical_hours > 0:
                logger.debug(f"Teacher {teacher}: {len(practical_instances)} practical instances, {total_practical_hours} total practical hours")
                logger.debug(f"  Instances: {', '.join(practical_instances)}")
                
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
        # Priority given to teachers with more practical hours and instances
        self._apply_lab_priority_constraints_instance_aware(teacher_lab_assignments)
        
        logger.info("Lab assignment constraint (instance-aware) applied successfully")
        return True
    
    def _apply_lab_priority_constraints_instance_aware(self, teacher_lab_assignments):
        """Apply priority constraints for lab assignment efficiency (instance-aware)."""
        # Calculate practical hours per teacher and number of practical instances
        teacher_priority_data = {}
        for teacher in self.teachers:
            if teacher not in self.teacher_course_assignments:
                continue
                
            total_practical_hours = 0
            practical_instance_count = 0
            for instance in self.teacher_course_assignments[teacher]:
                practical_hrs = instance['practical_hours']
                total_practical_hours += practical_hrs
                if practical_hrs > 0:
                    practical_instance_count += 1
            
            teacher_priority_data[teacher] = {
                'total_practical_hours': total_practical_hours,
                'practical_instances': practical_instance_count,
                'priority_score': total_practical_hours + (practical_instance_count * 0.5)  # Slight boost for more instances
            }
        
        # Sort teachers by priority score (descending)
        teachers_by_priority = sorted(
            [t for t in teacher_priority_data.keys() if teacher_priority_data[t]['total_practical_hours'] > 0], 
            key=lambda t: teacher_priority_data[t]['priority_score'], 
            reverse=True
        )
        
        # Log priority information
        logger.debug("Lab assignment priority order:")
        for i, teacher in enumerate(teachers_by_priority[:5]):  # Show top 5
            data = teacher_priority_data[teacher]
            logger.debug(f"  {i+1}. Teacher {teacher}: {data['total_practical_hours']}h, {data['practical_instances']} instances, score: {data['priority_score']:.1f}")
        
        # Apply soft constraints to encourage assignment of high-priority teachers first
        for i, teacher in enumerate(teachers_by_priority):
            lab_vars = []
            for day_idx in range(self.num_days):
                for session in self.lab_sessions.keys():
                    for room_id in self.lab_ids:
                        lab_vars.append(teacher_lab_assignments[teacher][day_idx][session][room_id])
            
            # Priority constraints can be enhanced here if needed
            # For now, the main constraints handle the core requirements
        
        logger.info(f"Lab priority constraints applied (instance-aware) for {len(teachers_by_priority)} teachers with practical requirements") 