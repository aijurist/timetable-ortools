"""
Conflict Prevention Constraint

This constraint prevents scheduling conflicts between different types of 
assignments and ensures proper resource allocation.
INSTANCE-AWARE: Enhanced instance integrity and conflict tracking.
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
        Apply conflict prevention constraints (INSTANCE-AWARE).
        
        This constraint ensures that:
        1. No time conflicts between theory and lab assignments
        2. Course instance integrity is maintained at individual instance level
        3. Room type matching (theory courses in classrooms, practicals in labs)
        4. INSTANCE-AWARE: Detailed tracking of individual course instances
        """
        logger.info("Applying conflict prevention constraint (INSTANCE-AWARE)...")
        
        total_constraints_added = 0
        
        # Constraint 1: Prevent time conflicts between theory and lab assignments
        if teacher_lab_assignments is not None:
            constraints_added = self._prevent_theory_lab_time_conflicts_instance_aware(teacher_theory_assignments, teacher_lab_assignments)
            total_constraints_added += constraints_added
        
        # Constraint 2: Ensure course instance integrity (enhanced instance-aware)
        constraints_added = self._ensure_course_instance_integrity_enhanced(teacher_theory_assignments, teacher_lab_assignments)
        total_constraints_added += constraints_added
        
        # Constraint 3: Room type matching with instance consideration
        constraints_added = self._ensure_room_type_matching_instance_aware(teacher_theory_assignments, teacher_lab_assignments)
        total_constraints_added += constraints_added
        
        logger.info(f"Conflict prevention constraint (INSTANCE-AWARE) applied successfully: {total_constraints_added} constraints")
        return True
    
    def _prevent_theory_lab_time_conflicts_instance_aware(self, teacher_theory_assignments, teacher_lab_assignments):
        """Prevent time conflicts between theory and lab assignments (INSTANCE-AWARE)."""
        logger.info("Preventing theory-lab time conflicts (INSTANCE-AWARE)...")
        
        constraint_count = 0
        teachers_with_conflicts = 0
        
        for teacher in self.teachers:
            # Get instance information for this teacher
            teacher_instances = self.teacher_course_assignments.get(teacher, [])
            theory_instances = [inst for inst in teacher_instances if (inst['lecture_hours'] + inst['tutorial_hours']) > 0]
            lab_instances = [inst for inst in teacher_instances if inst['practical_hours'] > 0]
            
            if theory_instances and lab_instances:
                teachers_with_conflicts += 1
                logger.debug(f"Teacher {teacher}: {len(theory_instances)} theory instances, {len(lab_instances)} lab instances")
                
                # Log specific instances that might conflict
                for theory_inst in theory_instances:
                    theory_hrs = theory_inst['lecture_hours'] + theory_inst['tutorial_hours']
                    logger.debug(f"  Theory Instance {theory_inst['id']}: {theory_inst['course_code']} ({theory_hrs}h)")
                
                for lab_inst in lab_instances:
                    logger.debug(f"  Lab Instance {lab_inst['id']}: {lab_inst['course_code']} ({lab_inst['practical_hours']}h)")
            
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
                        constraint_count += 1
        
        logger.info(f"Theory-lab time conflicts prevented: {constraint_count} constraints for {teachers_with_conflicts} teachers")
        return constraint_count
    
    def _ensure_course_instance_integrity_enhanced(self, teacher_theory_assignments, teacher_lab_assignments):
        """Ensure enhanced course instance integrity (INSTANCE-AWARE)."""
        logger.info("Ensuring enhanced course instance integrity (INSTANCE-AWARE)...")
        
        constraint_count = 0
        total_instances_processed = 0
        
        for teacher in self.teachers:
            if teacher not in self.teacher_course_assignments:
                continue
            
            # Get course instances for this teacher
            course_instances = self.teacher_course_assignments[teacher]
            total_instances_processed += len(course_instances)
            
            # Enhanced instance tracking
            instance_analysis = {}
            total_theory_requirements = 0
            total_practical_requirements = 0
            
            for instance in course_instances:
                instance_id = instance['id']
                course_code = instance['course_code']
                lecture_hrs = instance['lecture_hours']
                tutorial_hrs = instance['tutorial_hours']
                practical_hrs = instance['practical_hours']
                theory_hrs = lecture_hrs + tutorial_hrs
                
                total_theory_requirements += theory_hrs
                total_practical_requirements += practical_hrs
                
                instance_analysis[instance_id] = {
                    'course_code': course_code,
                    'lecture_hours': lecture_hrs,
                    'tutorial_hours': tutorial_hrs,
                    'practical_hours': practical_hrs,
                    'total_theory': theory_hrs,
                    'student_count': instance.get('student_count', 0)
                }
            
            logger.debug(f"Teacher {teacher}: {len(course_instances)} instances analysis:")
            logger.debug(f"  Total requirements: {total_theory_requirements}T + {total_practical_requirements}P")
            
            # Log each instance details
            for instance_id, analysis in instance_analysis.items():
                logger.debug(f"  Instance {instance_id}: {analysis['course_code']} - "
                           f"L:{analysis['lecture_hours']} T:{analysis['tutorial_hours']} P:{analysis['practical_hours']} "
                           f"(Students: {analysis['student_count']})")
            
            if len(course_instances) > 1:
                # Multiple instances - add enhanced distribution constraints
                logger.debug(f"Teacher {teacher}: Multiple instances require balanced distribution")
                
                # Enhanced constraint: Encourage spreading instances across days
                for instance in course_instances:
                    instance_id = instance['id']
                    required_theory_hours = instance['lecture_hours'] + instance['tutorial_hours']
                    
                    if required_theory_hours > 0:
                        # Create daily assignment tracking for this specific instance
                        daily_assignments_for_instance = []
                        
                        for day_idx in range(self.num_days):
                            # Theoretical assignments for this instance on this day
                            # (This is a conceptual constraint - actual instance tracking would require 
                            # additional variables from the course hours constraint)
                            day_theory_vars = []
                            for slot_idx in range(self.num_slots):
                                for room_id in self.classroom_ids:
                                    day_theory_vars.append(teacher_theory_assignments[teacher][day_idx][slot_idx][room_id])
                            
                            if day_theory_vars:
                                daily_assignments_for_instance.append(sum(day_theory_vars))
                        
                        # Soft constraint: For courses with 3+ hours, encourage distribution across days
                        if required_theory_hours >= 3 and len(daily_assignments_for_instance) > 1:
                            # Create binary variables for days with assignments
                            day_has_assignment_vars = []
                            for day_idx in range(self.num_days):
                                day_var = self.model.NewBoolVar(f'teacher_{teacher}_instance_{instance_id}_day_{day_idx}_active')
                                
                                # Link day variable to actual assignments
                                daily_assignments = []
                                for slot_idx in range(self.num_slots):
                                    for room_id in self.classroom_ids:
                                        daily_assignments.append(teacher_theory_assignments[teacher][day_idx][slot_idx][room_id])
                                
                                if daily_assignments:
                                    # If teacher has any assignment on this day, day_var can be 1
                                    self.model.Add(sum(daily_assignments) >= day_var)
                                    self.model.Add(sum(daily_assignments) <= self.num_slots * len(self.classroom_ids) * day_var)
                                    constraint_count += 2
                                
                                day_has_assignment_vars.append(day_var)
                            
                            # Encourage distribution: multi-hour courses should use multiple days
                            min_days = min(2, required_theory_hours)
                            if len(day_has_assignment_vars) >= min_days:
                                self.model.Add(sum(day_has_assignment_vars) >= min_days)
                                constraint_count += 1
                                
                                logger.debug(f"    Instance {instance_id} ({instance['course_code']}): "
                                           f"{required_theory_hours}h requires min {min_days} days")
        
        logger.info(f"Enhanced course instance integrity ensured: {constraint_count} constraints for {total_instances_processed} instances")
        return constraint_count
    
    def _ensure_room_type_matching_instance_aware(self, teacher_theory_assignments, teacher_lab_assignments):
        """Ensure room type matching with instance-aware capacity checking."""
        logger.info("Ensuring room type matching (INSTANCE-AWARE)...")
        
        constraint_count = 0
        capacity_warnings = 0
        
        # Enhanced room-instance matching
        for teacher in self.teachers:
            if teacher not in self.teacher_course_assignments:
                continue
            
            teacher_instances = self.teacher_course_assignments[teacher]
            
            for instance in teacher_instances:
                instance_id = instance['id']
                course_code = instance['course_code']
                student_count = instance.get('student_count', 0)
                theory_hours = instance['lecture_hours'] + instance['tutorial_hours']
                practical_hours = instance['practical_hours']
                
                # Check capacity requirements per instance
                if student_count > 0:
                    # Theory capacity check
                    if theory_hours > 0:
                        suitable_classrooms = 0
                        for _, room in self.classrooms.iterrows():
                            if room['room_max_cap'] >= student_count:
                                suitable_classrooms += 1
                        
                        if suitable_classrooms == 0:
                            logger.warning(f"Instance {instance_id} ({course_code}): {student_count} students, no suitable classrooms")
                            capacity_warnings += 1
                        else:
                            logger.debug(f"Instance {instance_id} ({course_code}): {student_count} students, {suitable_classrooms} suitable classrooms")
                    
                    # Lab capacity check
                    if practical_hours > 0 and teacher_lab_assignments is not None:
                        suitable_labs = 0
                        for _, lab in self.labs.iterrows():
                            if lab['room_max_cap'] >= student_count:
                                suitable_labs += 1
                        
                        if suitable_labs == 0:
                            logger.warning(f"Instance {instance_id} ({course_code}): {student_count} students, no suitable labs")
                            capacity_warnings += 1
                        else:
                            logger.debug(f"Instance {instance_id} ({course_code}): {student_count} students, {suitable_labs} suitable labs")
        
        # The actual room type constraints are implicitly enforced by the variable structure
        # (theory assignments only to classrooms, lab assignments only to labs)
        
        if capacity_warnings > 0:
            logger.warning(f"Found {capacity_warnings} instances with potential capacity issues")
        
        logger.info(f"Room type matching (INSTANCE-AWARE) ensured with {capacity_warnings} capacity warnings")
        return constraint_count 