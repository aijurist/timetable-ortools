import logging

logger = logging.getLogger(__name__)

class MacroblockTimetableConstraints:
    def __init__(self, model, teachers, teacher_course_assignments, classrooms, labs):
        """Initialize the macroblock timetable constraints with model and necessary data."""
        self.model = model
        self.teachers = teachers
        self.teacher_course_assignments = teacher_course_assignments
        self.classrooms = classrooms
        self.labs = labs
        
        # Days of the week (excluding Monday which is not in update.txt)
        self.days = ["tuesday", "wed", "thur", "fri", "sat"]
        self.num_days = len(self.days)
        
        # Time slots based on theory class structure (T slots - proper hourly timing)
        # Covers 8:00-19:00 as requested (11 slots: 8:00-8:50 to 18:00-18:50)
        self.time_slots = [
            "8:00 - 8:50", "9:00 - 9:50", "10:00 - 10:50", "11:00 - 11:50",
            "12:00 - 12:50", "1:00 - 1:50", "2:00 - 2:50", "3:00 - 3:50", 
            "4:00 - 4:50", "5:00 - 5:50", "6:00 - 6:50"
        ]
        self.num_slots = len(self.time_slots)
        
        # NEW: Teacher shift definitions
        # Shift 1: 8:00 - 3:00 PM (slots 0-6: 8:00-8:50 to 2:00-2:50)
        # Shift 2: 10:00 - 5:00 PM (slots 2-8: 10:00-10:50 to 4:00-4:50) 
        # Shift 3: 12:00 - 7:00 PM (slots 4-10: 12:00-12:50 to 6:00-6:50)
        self.teacher_shifts = {
            'shift1': {'name': 'Shift 1 (8:00-3:00)', 'start_slot': 0, 'end_slot': 6},   # slots 0-6
            'shift2': {'name': 'Shift 2 (10:00-5:00)', 'start_slot': 2, 'end_slot': 8},  # slots 2-8
            'shift3': {'name': 'Shift 3 (12:00-7:00)', 'start_slot': 4, 'end_slot': 10}  # slots 4-10
        }
        
        # Lab time slots (L slots - different timing structure)
        self.lab_time_slots = [
            "8:00 - 8:50", "8:50 - 9:40", "9:50 - 10:40", "10:40 - 11:30",
            "11:50 - 12:40", "12:40 - 1:30", "1:50 - 2:40", "2:40 - 3:30", 
            "3:50 - 4:40", "4:40 - 5:30", "5:30 - 6:20", "6:20 - 7:10"
        ]
        
        # Simplified macroblock structure - no separate macro shifts or teacher shifts
        # All blocks are available to all teachers (11 slots to match time_slots)
        self.daily_schedule_structure = {
            "tuesday": ["a1/L1", "b1/L2", "c1/L3", "d1/L4", "e1/L5", "f1/L6", 
                       "g1/L7", "a2/L8", "b2/L9", "c2/L10", "L11"],
            "wed": ["d2/L12", "e2/L14", "f2/L15", "g2/L16", "ta1/L17", "tb1/L18", 
                   "tc1/L19", "td1/L20", "te1/L21", "tf1/L22", "L23"],
            "thur": ["tg1/L25", "taa2/L26", "tbb2/L27", "tcc2/L28", "v1/L29", "v2/L30", 
                    "a1/L31", "b1/L32", "c1/L33", "d1/L34", "L35"],
            "fri": ["e1/L37", "f1/L38", "g1/L39", "ta2/L40", "tb2/L41", "tc2/L42", 
                   "td2/L43", "te2/L44", "tf2/L45", "tg2/L46", "L47"],
            "sat": ["a2/L49", "b2/L50", "c2/L51", "taa1/L52", "tbb1/L53", "tcc1/L54", 
                   "d2/L55", "e2/L56", "f2/L57", "g2/L58", "L59"]
        }
        
        # Define all available blocks (no shift separation)
        self.theory_blocks = ['a1', 'b1', 'c1', 'd1', 'e1', 'f1', 'g1', 'a2', 'b2', 'c2', 'd2', 'e2', 'f2', 'g2']
        
        # Tutorial blocks for 3rd hour of lecture courses
        self.tutorial_blocks = ['ta1', 'tb1', 'tc1', 'td1', 'te1', 'tf1', 'tg1', 
                               'ta2', 'tb2', 'tc2', 'td2', 'te2', 'tf2', 'tg2',
                               'taa1', 'taa2', 'tbb1', 'tbb2', 'tcc1', 'tcc2', 'v1', 'v2']
        
        # Parse slot assignments for each day to identify theory and lab slots
        self.slot_assignments = self._parse_slot_assignments()
        
        # Pre-compute room IDs for efficiency
        self.classroom_ids = self.classrooms['id'].tolist()
        self.lab_ids = self.labs['id'].tolist()
    
        # Group courses by semester and department for better allocation
        self.semester_course_groups = self._group_courses_by_semester_dept()
    
    def _parse_slot_assignments(self):
        """Parse the daily schedule structure to identify theory and lab slots."""
        slot_assignments = {}
        
        for day, schedule in self.daily_schedule_structure.items():
            slot_assignments[day] = []
            for slot_idx, content in enumerate(schedule):
                theory_blocks = []
                lab_slots = []
                
                # Split content by '/'
                parts = content.split('/')
                for part in parts:
                    if part.startswith('L'):
                        lab_slots.append(part)
                    elif part in self.theory_blocks + self.tutorial_blocks:
                        theory_blocks.append(part)
                
                slot_assignments[day].append({
                    'slot_index': slot_idx,
                    'time_interval': self.time_slots[slot_idx],
                    'theory_blocks': theory_blocks,
                    'lab_slots': lab_slots
                })
        
        return slot_assignments
    
    def _group_courses_by_semester_dept(self):
        """Group courses by semester and department for better macroblock allocation."""
        semester_groups = {}
        
        for teacher in self.teachers:
            if teacher not in self.teacher_course_assignments:
                continue
                
            for instance in self.teacher_course_assignments[teacher]:
                # Use actual semester and department info from the data
                semester = instance.get('semester', 3)  # Default to semester 3
                
                dept = instance.get('course_dept', 'Computer Science & Engineering')
                course_code = instance['course_code']
                
                key = (semester, dept)
                if key not in semester_groups:
                    semester_groups[key] = []
                print(key, semester, dept)
                semester_groups[key].append({
                    'teacher': teacher,
                    'instance': instance,
                    'course_code': course_code
                })
        
        return semester_groups
    
    def apply_course_hours_constraint(self, teacher_theory_assignments, teacher_lab_assignments=None):
        """
        Constraint 1: Course Hours Constraint (SIMPLIFIED APPROACH)
        Only assigns base macroblocks (a1, b1, c1, etc.) to course instances.
        Detailed lecture/tutorial mapping will be done in post-processing.
        This dramatically reduces model complexity from 1.6M+ variables to manageable size.
        """
        logger.info("Applying simplified course hours constraint (base macroblock assignment only)...")
        
        # Create simplified macroblock assignment variables - ONLY for base blocks
        self.macroblock_assignments = {}
        
        for teacher in self.teachers:
            if teacher not in self.teacher_course_assignments:
                continue
                
            self.macroblock_assignments[teacher] = {}
            course_instances = self.teacher_course_assignments[teacher]
                
            for instance in course_instances:
                instance_id = instance['id']
                lecture_hours = instance['lecture_hours']
                tutorial_hours = instance['tutorial_hours'] 
                practical_hours = instance['practical_hours']  # Not used for now
                        
                self.macroblock_assignments[teacher][instance_id] = {}
                
                # Create macroblock choice variables for base blocks only (a1, a2, b1, b2, etc.)
                # EXCLUDE v1 and v2 from assignments - they should not be assigned to any courses
                allowed_theory_blocks = [block for block in self.theory_blocks if block not in ['v1', 'v2']]
                
                for block in allowed_theory_blocks:
                    self.macroblock_assignments[teacher][instance_id][f'{block}_chosen'] = (
                        self.model.NewBoolVar(f'teacher_{teacher}_instance_{instance_id}_{block}_chosen'))
                
                # PRIORITY CONSTRAINT: Courses requiring extended tutorial support should get priority for a1-c2 blocks
                blocks_with_extended_tutorials = ['a1', 'a2', 'b1', 'b2', 'c1', 'c2']
                blocks_without_extended_tutorials = [block for block in allowed_theory_blocks 
                                                   if block not in blocks_with_extended_tutorials]
                
                # Priority cases that need extended tutorial support (taa1, taa2, tbb1, tbb2, tcc1, tcc2)
                if ((lecture_hours == 4) or 
                    (lecture_hours == 3 and tutorial_hours == 1) or 
                    (lecture_hours == 2 and tutorial_hours == 2)):
                    
                    # STRICT constraint: These courses can ONLY use blocks with extended tutorial support
                    for block in blocks_without_extended_tutorials:
                        self.model.Add(
                            self.macroblock_assignments[teacher][instance_id][f'{block}_chosen'] == 0)
                    
                    logger.info(f"Priority course {instance_id} ({lecture_hours}L+{tutorial_hours}T) restricted to blocks with extended tutorial support: {blocks_with_extended_tutorials}")
                
                # Secondary priority: Other courses with tutorial hours > 0 can use any block with basic tutorial support
                elif tutorial_hours > 0:
                    # These courses can use any block with at least basic tutorial support (all blocks have ta1/ta2 support)
                    logger.info(f"Course {instance_id} with {lecture_hours}L+{tutorial_hours}T can use any block with basic tutorial support")
                
                # Standard courses (lectures only) can use any available block
                else:
                    logger.info(f"Course {instance_id} with {lecture_hours}L+0T can use any available block")
                
                # Ensure exactly one block is chosen per course instance (if it has theory hours)
                if lecture_hours > 0 or tutorial_hours > 0:
                    block_choices = []
                    
                    # Collect all possible block choices (excluding v1, v2)
                    for block in allowed_theory_blocks:
                        block_choices.append(
                            self.macroblock_assignments[teacher][instance_id][f'{block}_chosen'])
                    
                    # Must assign exactly one macroblock for courses with theory hours
                    self.model.Add(sum(block_choices) == 1)  # Exactly one block
                    
                    logger.info(f"Course instance {instance_id} (Teacher {teacher}, {lecture_hours}L+{tutorial_hours}T) - simplified macroblock assignment")
        
        # Apply teacher course instance overlap constraint
        self._apply_teacher_course_instance_overlap_constraint()
        
        # Apply semester and department grouping constraints (simplified)
        self._apply_semester_grouping_constraints()
        
        # NEW: Apply teacher shift constraints to prevent cross-shift violations
        self._apply_teacher_shift_constraints()
        
        # Store assignment mapping for post-processing
        self.course_instance_mappings = {}
        for teacher in self.teachers:
            if teacher in self.teacher_course_assignments:
                for instance in self.teacher_course_assignments[teacher]:
                    instance_id = instance['id']
                    self.course_instance_mappings[instance_id] = {
                        'teacher': teacher,
                        'instance': instance
                    }
        
        return True
    
    def _apply_teacher_course_instance_overlap_constraint(self):
        """
        NEW Constraint: Teacher Course Instance Overlap Prevention
        Prevents the same teacher from having multiple different course instances 
        assigned to overlapping time slots within the same macroblock.
        """
        logger.info("Applying teacher course instance overlap constraint...")
        
        for teacher in self.teachers:
            if teacher not in self.teacher_course_assignments or len(self.teacher_course_assignments[teacher]) <= 1:
                continue  # Skip if teacher has 0 or 1 course instances
            
            course_instances = self.teacher_course_assignments[teacher]
            
            # For each pair of different course instances for the same teacher
            for i in range(len(course_instances)):
                for j in range(i + 1, len(course_instances)):
                    instance1 = course_instances[i]
                    instance2 = course_instances[j]
                    
                    instance1_id = instance1['id']
                    instance2_id = instance2['id']
                    
                    # Check if both instances have macroblock assignments
                    if (teacher in self.macroblock_assignments and 
                        instance1_id in self.macroblock_assignments[teacher] and 
                        instance2_id in self.macroblock_assignments[teacher]):
                        
                        # For each macroblock, ensure at most one of the two instances is assigned
                        allowed_theory_blocks = [block for block in self.theory_blocks if block not in ['v1', 'v2']]
                        
                        for block in allowed_theory_blocks:
                            instance1_block_var = self.macroblock_assignments[teacher][instance1_id].get(f'{block}_chosen')
                            instance2_block_var = self.macroblock_assignments[teacher][instance2_id].get(f'{block}_chosen')
                            
                            if instance1_block_var is not None and instance2_block_var is not None:
                                # At most one of the two instances can be assigned to this block
                                self.model.Add(instance1_block_var + instance2_block_var <= 1)
                        
                        logger.info(f"Applied overlap constraint for Teacher {teacher}: instances {instance1_id} and {instance2_id} cannot be in same macroblock")
        
        logger.info("Teacher course instance overlap constraint applied successfully")
    
    def _apply_macroblock_span_constraints(self, teacher, instance, teacher_theory_assignments):
        """SIMPLIFIED: No detailed span constraints - handled in post-processing."""
        # This function is now simplified - detailed allocation moved to post-processing
        pass
    
    def _allocate_macroblock_span(self, teacher, instance_id, chosen_block, block_chosen_var, 
                                lecture_hours, tutorial_hours, teacher_theory_assignments):
        """SIMPLIFIED: Detailed allocation logic moved to post-processing for efficiency."""
        # All detailed allocation logic has been moved to post-processing
        # This dramatically reduces CP-SAT model complexity
        pass
    
    # REMOVED: All detailed case allocation functions moved to post-processing
    
    def _apply_semester_grouping_constraints(self):
        """Apply constraints to group courses by semester and department with teacher diversity."""
        logger.info("Applying semester and department grouping constraints...")
        
        # Exclude v1 and v2 from semester grouping as well
        allowed_theory_blocks = [block for block in self.theory_blocks if block not in ['v1', 'v2']]
        
        for (semester, dept), course_group in self.semester_course_groups.items():
            if len(course_group) <= 1:
                continue  # Skip if only one course in the group
            
            # Group by unique course codes to avoid same course repetition
            course_code_groups = {}
            for item in course_group:
                course_code = item['course_code']
                if course_code not in course_code_groups:
                    course_code_groups[course_code] = []
                course_code_groups[course_code].append(item)
            
            # For each macroblock, apply diversity constraints (excluding v1, v2)
            for block in allowed_theory_blocks:
                
                # Collect all course instances that could be assigned to this block
                block_assignments = []
                teacher_assignments = {}
                
                for course_code, course_instances in course_code_groups.items():
                    for item in course_instances:
                        teacher = item['teacher']
                        instance_id = item['instance']['id']
                        
                        if teacher in self.macroblock_assignments and instance_id in self.macroblock_assignments[teacher]:
                            block_var = self.macroblock_assignments[teacher][instance_id].get(f'{block}_chosen')
                            if block_var is not None:
                                block_assignments.append((teacher, instance_id, block_var, course_code))
                                
                                # Track teacher assignments
                                if teacher not in teacher_assignments:
                                    teacher_assignments[teacher] = []
                                teacher_assignments[teacher].append(block_var)
                
                # Constraint: Prevent same teacher from having multiple DIFFERENT course instances in same block
                for teacher, teacher_vars in teacher_assignments.items():
                    if len(teacher_vars) > 1:
                        # Group by course instance ID to allow same instance, prevent different instances
                        teacher_instances = {}
                        for teacher_id, instance_id, block_var, course_code in block_assignments:
                            if teacher_id == teacher:
                                if instance_id not in teacher_instances:
                                    teacher_instances[instance_id] = []
                                teacher_instances[instance_id].append(block_var)
                        
                        # If teacher has multiple different instances, only one can be in this block
                        if len(teacher_instances) > 1:
                            instance_vars = [teacher_instances[inst][0] for inst in teacher_instances]  # One var per instance
                            self.model.Add(sum(instance_vars) <= 1)
                
                # Constraint: Allow up to 2 instances per course code per block (enabling same course with different teachers)
                course_code_vars = {}
                for teacher, instance_id, block_var, course_code in block_assignments:
                    if course_code not in course_code_vars:
                        course_code_vars[course_code] = []
                    course_code_vars[course_code].append(block_var)
                
                # MODIFIED: Allow at most 2 instances per course code per block (instead of 2)
                # This enables same course instance with different teachers to be grouped in same macroblock
                for course_code, course_vars in course_code_vars.items():
                    if len(course_vars) > 1:
                        self.model.Add(sum(course_vars) <= 2)  
                        logger.info(f"Course {course_code} in block {block}: allowing up to 3 instances (different teachers)")
    
    def _link_macroblock_to_slots(self, teacher, instance, teacher_theory_assignments, teacher_lab_assignments):
        """SIMPLIFIED: No detailed slot linking - handled in post-processing."""
        # All detailed slot linking moved to post-processing for efficiency
        pass
    
    def _enforce_flexible_hours(self, teacher, instance, teacher_theory_assignments, teacher_lab_assignments):
        """SIMPLIFIED: No detailed hour enforcement - handled in post-processing."""
        # All detailed hour validation moved to post-processing for efficiency
        pass
    
    def apply_teacher_single_assignment_constraint(self, teacher_theory_assignments, teacher_lab_assignments=None):
        """
        Constraint 2: Teacher Single Assignment Constraint
        A teacher cannot be assigned to multiple rooms in the same time slot.
        Skip lab constraints for now.
        """
        logger.info("Applying teacher single assignment constraint (theory only)...")
        
        for teacher in self.teachers:
            for day_idx in range(self.num_days):
                for slot_idx in range(self.num_slots):
                    # For theory slots - sum of all classroom assignments must be at most 1
                    theory_vars = [teacher_theory_assignments[teacher][day_idx][slot_idx][room_id] 
                                 for room_id in self.classroom_ids]
                    self.model.Add(sum(theory_vars) <= 1)
                    
                    # Skip lab constraints for now
        
        return True
    
    def apply_no_overlapping_slots_constraint(self, teacher_theory_assignments, teacher_lab_assignments=None):
        """
        Constraint 3: No Overlapping Slots Constraint
        Skip this constraint for now since we're not dealing with labs.
        """
        logger.info("Skipping overlapping slots constraint (labs not allocated)...")
        return True
    
    def apply_room_single_assignment_constraint(self, teacher_theory_assignments, teacher_lab_assignments=None):
        """
        Constraint 4: Room Single Assignment Constraint
        A room cannot be assigned to multiple teachers in the same time slot.
        Apply only to classrooms for now.
        """
        logger.info("Applying room single assignment constraint (classrooms only)...")
        
        # For classrooms
        for room_id in self.classroom_ids:
            for day_idx in range(self.num_days):
                for slot_idx in range(self.num_slots):
                    room_vars = [teacher_theory_assignments[teacher][day_idx][slot_idx][room_id] 
                               for teacher in self.teachers]
                    self.model.Add(sum(room_vars) <= 1)
        
        # Skip labs for now
        
        return True
    
    def apply_all_constraints(self, teacher_theory_assignments, teacher_lab_assignments=None):
        """Apply all timetable constraints. Skip lab-related constraints for now."""
        logger.info("Applying all macroblock timetable constraints (theory only)...")
        
        constraints_applied = [
            self.apply_course_hours_constraint(teacher_theory_assignments, None),
            self.apply_teacher_single_assignment_constraint(teacher_theory_assignments, None),
            self.apply_no_overlapping_slots_constraint(teacher_theory_assignments, None),
            self.apply_room_single_assignment_constraint(teacher_theory_assignments, None),
            self.apply_weekly_working_hour_constraint(teacher_theory_assignments, None),
        ]
        
        # Apply teacher shift constraints (this method doesn't return a boolean)
        self._apply_teacher_shift_constraints()
        
        return all(constraints_applied)

    def apply_weekly_working_hour_constraint(self, teacher_theory_assignments, teacher_lab_assignments=None):
        """
        Constraint: Weekly Working Hour Constraint
        Limits teacher workload to 21 hours per week.
        
        Hour Calculation:
        - Theory slots: 1 hour each (50 minutes ≈ 1 hour)
        - Lab slots: 2 hours each (100 minutes ≈ 2 hours)
        
        Formula: theory_hours + 2 × lab_hours ≤ 21
        """
        logger.info("Applying weekly working hour constraint (21 hours max per teacher)...")
        
        for teacher in self.teachers:
            # Collect all theory assignment variables for this teacher
            theory_hour_vars = []
            
            for day_idx in range(self.num_days):
                for slot_idx in range(self.num_slots):
                    for room_id in self.classroom_ids:
                        theory_assignment = teacher_theory_assignments[teacher][day_idx][slot_idx][room_id]
                        theory_hour_vars.append(theory_assignment)
            
            # Collect all lab assignment variables for this teacher (when labs are implemented)
            lab_hour_vars = []
            if teacher_lab_assignments is not None:
                for day_idx in range(self.num_days):
                    # Lab slots would be different from theory slots
                    # For now, skip lab hours since labs are not implemented
                    pass
            
            # Apply the weekly hour constraint
            # Theory: 1 hour per slot, Labs: 2 hours per slot
            total_theory_hours = sum(theory_hour_vars)
            total_lab_hours = sum(lab_hour_vars) * 2 if lab_hour_vars else 0
            
            # Weekly limit: 21 hours
            self.model.Add(total_theory_hours + total_lab_hours <= 21)
            
            logger.info(f"Applied 21-hour weekly limit for Teacher {teacher}")
        
        return True

    def _apply_teacher_shift_constraints(self):
        """
        ENHANCED Day-Aware Teacher Shift Constraints
        
        Ensures that when multiple macroblocks are assigned to the same teacher,
        they stay within the same shift on each day. This prevents cross-shift violations
        by analyzing day-specific shift requirements.
        
        Approach:
        1. For each teacher, determine the shift requirements for each day
        2. Create constraints that ensure all macroblocks assigned to a teacher 
           use compatible shifts on each day
        3. Use cumulative shift analysis to prevent conflicts
        """
        logger.info("Applying enhanced day-aware teacher shift constraints...")
        
        # First, analyze which time slots each base macroblock spans for each day
        macroblock_slot_mapping = self._analyze_macroblock_time_slots()
        
        # For each teacher, apply day-aware shift constraints
        for teacher in self.teachers:
            if teacher not in self.teacher_course_assignments:
                continue
            
            course_instances = self.teacher_course_assignments[teacher]
            if len(course_instances) <= 1:
                continue  # Skip if teacher has only one course (no conflicts possible)
            
            logger.info(f"Applying day-aware shift constraints for Teacher {teacher} with {len(course_instances)} courses")
            
            # Analyze shift requirements for each course on each day
            course_day_shift_requirements = self._analyze_course_day_shift_requirements(
                teacher, course_instances, macroblock_slot_mapping)
            
            # Apply cross-course shift consistency constraints
            self._apply_cross_course_shift_consistency(teacher, course_instances, course_day_shift_requirements)
        
        logger.info("Enhanced day-aware teacher shift constraints applied successfully")
    
    def _analyze_course_day_shift_requirements(self, teacher, course_instances, macroblock_slot_mapping):
        """
        Analyze shift requirements for each course on each day.
        Returns a mapping of which shifts each course would require on each day for each possible base macroblock.
        """
        course_day_shift_requirements = {}
        
        for instance in course_instances:
            instance_id = instance['id']
            lecture_hours = instance['lecture_hours']
            tutorial_hours = instance['tutorial_hours']
            
            if teacher not in self.macroblock_assignments or instance_id not in self.macroblock_assignments[teacher]:
                continue
            
            course_day_shift_requirements[instance_id] = {}
            
            # Analyze each possible base macroblock for this course
            allowed_theory_blocks = [block for block in self.theory_blocks if block not in ['v1', 'v2']]
            
            for base_block in allowed_theory_blocks:
                course_day_shift_requirements[instance_id][base_block] = {}
                
                # For each day, determine which shift this base block would require
                for day in self.days:
                    predicted_slots = self._predict_time_slots_for_assignment(
                        base_block, day, lecture_hours, tutorial_hours, macroblock_slot_mapping)
                    
                    if predicted_slots:
                        required_shift = self._determine_required_shift(predicted_slots)
                        course_day_shift_requirements[instance_id][base_block][day] = {
                            'slots': predicted_slots,
                            'shift': required_shift
                        }
                    else:
                        course_day_shift_requirements[instance_id][base_block][day] = {
                            'slots': [],
                            'shift': None
                        }
        
        return course_day_shift_requirements
    
    def _determine_required_shift(self, slot_indices):
        """
        Determine which shift is required for a given set of time slots.
        Returns the shift name if all slots fit within one shift, 'invalid' if they span multiple shifts.
        """
        if not slot_indices:
            return None
        
        min_slot = min(slot_indices)
        max_slot = max(slot_indices)
        
        # Check which shifts can accommodate all slots
        compatible_shifts = []
        for shift_name, shift_info in self.teacher_shifts.items():
            start_slot = shift_info['start_slot']
            end_slot = shift_info['end_slot']
            
            if min_slot >= start_slot and max_slot <= end_slot:
                compatible_shifts.append(shift_name)
        
        if len(compatible_shifts) == 1:
            return compatible_shifts[0]
        elif len(compatible_shifts) > 1:
            # If multiple shifts are compatible, prefer the most restrictive one
            shift_sizes = {shift: self.teacher_shifts[shift]['end_slot'] - self.teacher_shifts[shift]['start_slot'] 
                          for shift in compatible_shifts}
            return min(shift_sizes.keys(), key=lambda x: shift_sizes[x])
        else:
            return 'invalid'
    
    def _apply_cross_course_shift_consistency(self, teacher, course_instances, course_day_shift_requirements):
        """
        Apply constraints to ensure all courses assigned to a teacher use compatible shifts on each day.
        """
        # For each day, ensure shift consistency across all courses
        for day in self.days:
            # For each pair of courses, ensure they can be assigned to compatible shifts on this day
            for i in range(len(course_instances)):
                for j in range(i + 1, len(course_instances)):
                    instance1 = course_instances[i]
                    instance2 = course_instances[j]
                    instance1_id = instance1['id']
                    instance2_id = instance2['id']
                    
                    if (instance1_id not in course_day_shift_requirements or 
                        instance2_id not in course_day_shift_requirements):
                        continue
                    
                    # Create constraints for this day and pair of courses
                    self._create_day_shift_consistency_constraints(
                        teacher, day, instance1_id, instance2_id, course_day_shift_requirements)
    
    def _create_day_shift_consistency_constraints(self, teacher, day, instance1_id, instance2_id, 
                                                 course_day_shift_requirements):
        """
        Create specific constraints to ensure two courses use compatible shifts on a given day.
        """
        req1 = course_day_shift_requirements[instance1_id]
        req2 = course_day_shift_requirements[instance2_id]
        
        allowed_theory_blocks = [block for block in self.theory_blocks if block not in ['v1', 'v2']]
        
        # For each combination of base macroblocks for the two courses
        for block1 in allowed_theory_blocks:
            for block2 in allowed_theory_blocks:
                if (block1 not in req1 or block2 not in req2 or 
                    day not in req1[block1] or day not in req2[block2]):
                    continue
                
                shift1 = req1[block1][day]['shift']
                shift2 = req2[block2][day]['shift']
                
                # If either shift is invalid or they're incompatible, prevent this combination
                if (shift1 == 'invalid' or shift2 == 'invalid' or 
                    (shift1 is not None and shift2 is not None and shift1 != shift2)):
                    
                    # Get the boolean variables for these macroblock choices
                    if (teacher in self.macroblock_assignments and
                        instance1_id in self.macroblock_assignments[teacher] and
                        instance2_id in self.macroblock_assignments[teacher]):
                        
                        block1_var = self.macroblock_assignments[teacher][instance1_id].get(f'{block1}_chosen')
                        block2_var = self.macroblock_assignments[teacher][instance2_id].get(f'{block2}_chosen')
                        
                        if block1_var is not None and block2_var is not None:
                            # Constraint: Cannot have both blocks chosen simultaneously
                            self.model.Add(block1_var + block2_var <= 1)
                            
                            logger.info(f"SHIFT CONSTRAINT: Teacher {teacher} on {day}: "
                                      f"blocks {block1}(course {instance1_id}) and {block2}(course {instance2_id}) "
                                      f"incompatible - shifts {shift1} vs {shift2}")
        
        # Also apply individual block constraints for invalid shifts
        for instance_id in [instance1_id, instance2_id]:
            req = course_day_shift_requirements[instance_id]
            for block in allowed_theory_blocks:
                if block in req and day in req[block] and req[block][day]['shift'] == 'invalid':
                    if (teacher in self.macroblock_assignments and
                        instance_id in self.macroblock_assignments[teacher]):
                        
                        block_var = self.macroblock_assignments[teacher][instance_id].get(f'{block}_chosen')
                        if block_var is not None:
                            # Hard constraint: Cannot use this block due to invalid shift
                            self.model.Add(block_var == 0)
                            
                            logger.info(f"INVALID SHIFT: Teacher {teacher} course {instance_id} "
                                      f"cannot use block {block} on {day} - spans multiple shifts")
    
    def _analyze_macroblock_time_slots(self):
        """Analyze which time slots each macroblock appears in for each day."""
        macroblock_slot_mapping = {}
        
        for day, schedule in self.daily_schedule_structure.items():
            macroblock_slot_mapping[day] = {}
            
            for slot_idx, content in enumerate(schedule):
                # Parse content to find theory blocks
                parts = content.split('/')
                for part in parts:
                    if part in self.theory_blocks + self.tutorial_blocks:
                        if part not in macroblock_slot_mapping[day]:
                            macroblock_slot_mapping[day][part] = []
                        macroblock_slot_mapping[day][part].append(slot_idx)
        
        return macroblock_slot_mapping
    
    def _predict_time_slots_for_assignment(self, base_block, day, lecture_hours, tutorial_hours, macroblock_slot_mapping):
        """
        Predict which time slots will be used if a course instance is assigned to a base macroblock.
        This uses the same logic as the post-processing case logic.
        """
        predicted_slots = []
        
        # Get base slots for this block on this day
        base_slots = macroblock_slot_mapping[day].get(base_block, [])
        
        # Get tutorial slots
        block_letter = base_block[0]  # 'a', 'b', 'c', etc.
        block_number = base_block[1]  # '1' or '2'
        tutorial_block = f't{block_letter}{block_number}'
        tutorial_slots = macroblock_slot_mapping[day].get(tutorial_block, [])
        
        # Get extended tutorial slots
        extended_tutorial_block = f't{block_letter}{block_letter}{block_number}'
        extended_tutorial_slots = macroblock_slot_mapping[day].get(extended_tutorial_block, [])
        
        # Apply the same case logic as in post-processing
        if lecture_hours == 3 and tutorial_hours == 0:
            # Case 1: 3L+0T → base_slots[:2] + tutorial_slots[:1]
            predicted_slots.extend(base_slots[:2])
            predicted_slots.extend(tutorial_slots[:1])
            
        elif lecture_hours == 3 and tutorial_hours == 1:
            # Case 2: 3L+1T → base_slots[:2] + tutorial_slots[:1] + extended_tutorial_slots[:1]
            predicted_slots.extend(base_slots[:2])
            predicted_slots.extend(tutorial_slots[:1])
            predicted_slots.extend(extended_tutorial_slots[:1])
            
        elif lecture_hours == 2 and tutorial_hours == 1:
            # Case 3: 2L+1T → base_slots[:2] + tutorial_slots[:1]
            predicted_slots.extend(base_slots[:2])
            predicted_slots.extend(tutorial_slots[:1])
            
        elif lecture_hours == 1 and tutorial_hours == 1:
            # Case 4: 1L+1T → base_slots[:1] + tutorial_slots[:1]
            predicted_slots.extend(base_slots[:1])
            predicted_slots.extend(tutorial_slots[:1])
            
        elif lecture_hours == 2 and tutorial_hours == 0:
            # Case 5: 2L+0T → base_slots[:2]
            predicted_slots.extend(base_slots[:2])
            
        elif lecture_hours == 1 and tutorial_hours == 0:
            # Case 6: 1L+0T → base_slots[:1]
            predicted_slots.extend(base_slots[:1])
            
        elif lecture_hours == 4 and tutorial_hours >= 1:
            # Case 7: 4L+1T or 4L+2T → base_slots[:2] + tutorial_slots[:(lecture_hours-2)] + remaining tutorial slots
            predicted_slots.extend(base_slots[:2])
            tutorial_slots_for_lectures = lecture_hours - 2
            predicted_slots.extend(tutorial_slots[:tutorial_slots_for_lectures])
            remaining_tutorial_slots = tutorial_slots[tutorial_slots_for_lectures:] + extended_tutorial_slots
            predicted_slots.extend(remaining_tutorial_slots[:tutorial_hours])
            
        elif lecture_hours == 5 and tutorial_hours >= 1:
            # Case 8: 5L+1T or 5L+2T → all base slots + additional tutorial slots
            predicted_slots.extend(base_slots)
            tutorial_slots_for_lectures = lecture_hours - len(base_slots)
            predicted_slots.extend(tutorial_slots[:tutorial_slots_for_lectures])
            remaining_tutorial_slots = tutorial_slots[tutorial_slots_for_lectures:] + extended_tutorial_slots
            predicted_slots.extend(remaining_tutorial_slots[:tutorial_hours])
            
        elif lecture_hours == 2 and tutorial_hours == 2:
            # Case 9: 2L+2T → base_slots[:2] + tutorial_slots[:1] + extended_tutorial_slots[:1]
            predicted_slots.extend(base_slots[:2])
            predicted_slots.extend(tutorial_slots[:1])
            predicted_slots.extend(extended_tutorial_slots[:1])
            
        else:
            # General case
            predicted_slots.extend(base_slots[:lecture_hours])
            predicted_slots.extend(tutorial_slots[:tutorial_hours])
        
        # Remove duplicates and sort
        predicted_slots = sorted(list(set(predicted_slots)))
        return predicted_slots
