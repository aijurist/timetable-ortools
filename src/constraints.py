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
        self.time_slots = [
            "8:00 - 8:50", "9:00 - 9:50", "10:00 - 10:50", "11:00 - 11:50",
            "12:00 - 12:50", "1:00 - 1:50", "2:00 - 2:50", "3:00 - 3:50", 
            "4:00 - 4:50", "5:00 - 5:50", "6:00 - 6:50", "7:00 - 7:50"
        ]
        self.num_slots = len(self.time_slots)
        
        # Lab time slots (L slots - different timing structure for 50-minute periods)
        self.lab_time_slots = [
            "8:00 - 8:50", "8:50 - 9:40", "9:50 - 10:40", "10:40 - 11:30",
            "11:50 - 12:40", "12:40 - 1:30", "1:50 - 2:40", "2:40 - 3:30", 
            "3:50 - 4:40", "4:40 - 5:30", "5:30 - 6:20", "6:20 - 7:10"
        ]
        self.num_lab_slots = len(self.lab_time_slots)
        
        # Lab slot groupings - each group represents 2 practical hours (100 minutes)
        # l1 = 8:00-9:40, l2 = 9:50-11:30, l3 = 11:50-1:30, l4 = 1:50-3:30, l5 = 3:50-5:30, l6 = 5:30-7:10
        self.lab_slot_groups = {
            'l1': [0, 1],    # 8:00-8:50, 8:50-9:40
            'l2': [2, 3],    # 9:50-10:40, 10:40-11:30
            'l3': [4, 5],    # 11:50-12:40, 12:40-1:30
            'l4': [6, 7],    # 1:50-2:40, 2:40-3:30
            'l5': [8, 9],    # 3:50-4:40, 4:40-5:30
            'l6': [10, 11]   # 5:30-6:20, 6:20-7:10
        }
        self.num_lab_groups = len(self.lab_slot_groups)
        
        # Simplified macroblock structure - no separate macro shifts or teacher shifts
        # All blocks are available to all teachers
        self.daily_schedule_structure = {
            "tuesday": ["a1/L1", "b1/L2", "c1/L3", "d1/L4", "e1/L5", "f1/L6", 
                       "g1/L7", "a2/L8", "b2/L9", "c2/L10", "L11", 'L12'],
            "wed": ["d2/L12", "e2/L14", "f2/L15", "g2/L16", "ta1/L17", "tb1/L18", 
                   "tc1/L19", "td1/L20", "te1/L21", "tf1/L22", "L23", "L24"],
            "thur": ["tg1/L25", "taa2/L26", "tbb2/L27", "tcc2/L28", "v1/L29", "v2/L30", 
                    "a1/L31", "b1/L32", "c1/L33", "d1/L34", "L35", "L36"],
            "fri": ["e1/L37", "f1/L38", "g1/L39", "ta2/L40", "tb2/L41", "tc2/L42", 
                   "td2/L43", "te2/L44", "tf2/L45", "tg2/L46", "L47", "L48"],
            "sat": ["a2/L49", "b2/L50", "c2/L51", "taa1/L52", "tbb1/L53", "tcc1/L54", 
                   "d2/L55", "e2/L56", "f2/L57", "g2/L58", "L59", "L60"]
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
        
        # Map lab slots from daily schedule to lab slot groups
        self.daily_lab_mappings = self._map_daily_labs_to_groups()
    
    def _map_daily_labs_to_groups(self):
        """Map lab slots from daily schedule structure to lab slot groups."""
        daily_lab_mappings = {}
        
        for day, schedule in self.daily_schedule_structure.items():
            daily_lab_mappings[day] = {}
            for slot_idx, content in enumerate(schedule):
                # Extract lab slots from content
                parts = content.split('/')
                for part in parts:
                    if part.startswith('L'):
                        lab_number = int(part[1:])  # Extract number from L1, L2, etc.
                        
                        # Map lab numbers to lab slot groups
                        # Each group of 2 consecutive lab numbers maps to a lab group
                        # L1,L2 -> l1, L3,L4 -> l2, etc.
                        group_index = (lab_number - 1) // 2
                        if group_index < self.num_lab_groups:
                            group_name = list(self.lab_slot_groups.keys())[group_index]
                            daily_lab_mappings[day][slot_idx] = {
                                'lab_number': lab_number,
                                'group_name': group_name,
                                'group_slot_index': (lab_number - 1) % 2  # 0 or 1 within the group
                            }
        
        return daily_lab_mappings
    
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
        Constraint 1: Course Hours Constraint (EXTENDED FOR LAB SUPPORT)
        Assigns base macroblocks (a1, b1, c1, etc.) to course instances for theory.
        Assigns lab slot groups (l1, l2, etc.) to course instances for practicals.
        Detailed lecture/tutorial mapping will be done in post-processing.
        """
        logger.info("Applying course hours constraint with lab support...")
        
        # Create simplified macroblock assignment variables - ONLY for base blocks
        self.macroblock_assignments = {}
        # Create lab assignment variables for practical courses
        self.lab_assignments = {}
        
        for teacher in self.teachers:
            if teacher not in self.teacher_course_assignments:
                continue
                
            self.macroblock_assignments[teacher] = {}
            self.lab_assignments[teacher] = {}
            course_instances = self.teacher_course_assignments[teacher]
            
            # Group instances by course code to apply separation constraints
            course_code_instances = {}
            for instance in course_instances:
                course_code = instance['course_code']
                if course_code not in course_code_instances:
                    course_code_instances[course_code] = []
                course_code_instances[course_code].append(instance)
                
            for instance in course_instances:
                instance_id = instance['id']
                lecture_hours = instance['lecture_hours']
                tutorial_hours = instance['tutorial_hours'] 
                practical_hours = instance['practical_hours']
                        
                self.macroblock_assignments[teacher][instance_id] = {}
                self.lab_assignments[teacher][instance_id] = {}
                
                # Theory/Tutorial assignment (if course has theory hours)
                if lecture_hours > 0 or tutorial_hours > 0:
                    # Create macroblock choice variables for base blocks only (a1, a2, b1, b2, etc.)
                    for block in self.theory_blocks:
                        self.macroblock_assignments[teacher][instance_id][f'{block}_chosen'] = (
                            self.model.NewBoolVar(f'teacher_{teacher}_instance_{instance_id}_{block}_chosen'))
                    
                    # Apply simple constraint: 3L+1T courses can only use blocks with extended tutorial support
                    if lecture_hours == 3 and tutorial_hours == 1:
                        # Only allow assignment to blocks that have extended tutorial support (a1, a2, b1, b2, c1, c2)
                        blocks_with_extended_tutorials = ['a1', 'a2', 'b1', 'b2', 'c1', 'c2']
                        blocks_without_extended_tutorials = [block for block in self.theory_blocks 
                                                           if block not in blocks_with_extended_tutorials]
                        
                        # Prohibit assignment to blocks without extended tutorial support
                        for block in blocks_without_extended_tutorials:
                            self.model.Add(
                                self.macroblock_assignments[teacher][instance_id][f'{block}_chosen'] == 0)
                        
                        logger.info(f"3L+1T course {instance_id} restricted to blocks with extended tutorial support: {blocks_with_extended_tutorials}")
                    
                    # Ensure exactly one block is chosen per course instance with theory hours
                    block_choices = []
                    for block in self.theory_blocks:
                        block_choices.append(
                            self.macroblock_assignments[teacher][instance_id][f'{block}_chosen'])
                    
                    # Must assign exactly one macroblock for courses with theory hours
                    self.model.Add(sum(block_choices) == 1)  # Exactly one block
                    
                    logger.info(f"Course instance {instance_id} (Teacher {teacher}, {lecture_hours}L+{tutorial_hours}T) - macroblock assignment")
                
                # Lab assignment (if course has practical hours)
                if practical_hours > 0:
                    # Create lab slot group choice variables
                    for group_name in self.lab_slot_groups.keys():
                        self.lab_assignments[teacher][instance_id][f'{group_name}_chosen'] = (
                            self.model.NewBoolVar(f'teacher_{teacher}_instance_{instance_id}_{group_name}_chosen'))
                    
                    # Calculate required number of lab slot groups based on practical hours
                    # Each lab slot group = 2 practical hours
                    required_lab_groups = (practical_hours + 1) // 2  # Round up
                    
                    # Ensure correct number of lab groups are chosen
                    lab_group_choices = []
                    for group_name in self.lab_slot_groups.keys():
                        lab_group_choices.append(
                            self.lab_assignments[teacher][instance_id][f'{group_name}_chosen'])
                    
                    # Must assign exactly the required number of lab groups
                    self.model.Add(sum(lab_group_choices) == required_lab_groups)
                    
                    logger.info(f"Course instance {instance_id} (Teacher {teacher}, {practical_hours}P) - requires {required_lab_groups} lab groups")
            
            # Apply course instance separation constraint for lab groups
            self._apply_course_instance_lab_separation(teacher, course_code_instances)
        
        # Apply lab group distribution constraints to prevent clustering
        self._apply_lab_group_distribution_constraints()
        
        # Apply semester and department grouping constraints (simplified)
        self._apply_semester_grouping_constraints()
        
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
    
    def _apply_course_instance_lab_separation(self, teacher, course_code_instances):
        """
        Apply constraints to ensure different instances of the same course
        get assigned to different lab groups to avoid scheduling conflicts.
        """
        for course_code, instances in course_code_instances.items():
            if len(instances) <= 1:
                continue  # Skip if only one instance
            
            # For each lab group, ensure at most one instance of the same course is assigned
            for group_name in self.lab_slot_groups.keys():
                instances_with_labs = [inst for inst in instances if inst['practical_hours'] > 0]
                
                if len(instances_with_labs) <= 1:
                    continue
                
                # Collect lab group assignment variables for all instances of this course
                lab_group_vars = []
                for instance in instances_with_labs:
                    instance_id = instance['id']
                    if instance_id in self.lab_assignments[teacher]:
                        lab_var = self.lab_assignments[teacher][instance_id].get(f'{group_name}_chosen')
                        if lab_var is not None:
                            lab_group_vars.append(lab_var)
                
                # Constraint: At most one instance of the same course can use the same lab group
                if len(lab_group_vars) > 1:
                    self.model.Add(sum(lab_group_vars) <= 1)
                    logger.info(f"Applied lab group separation for course {course_code}: max 1 instance per lab group {group_name}")
    
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
            
            # For each macroblock, apply diversity constraints
            for block in self.theory_blocks:
                
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
                
                # Constraint: Promote diversity by limiting same course code repetition
                course_code_vars = {}
                for teacher, instance_id, block_var, course_code in block_assignments:
                    if course_code not in course_code_vars:
                        course_code_vars[course_code] = []
                    course_code_vars[course_code].append(block_var)
                
                # Allow at most one instance per course code per block
                for course_code, course_vars in course_code_vars.items():
                    if len(course_vars) > 1:
                        self.model.Add(sum(course_vars) <= 1)
    
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
        Applies to both theory and lab assignments.
        """
        logger.info("Applying teacher single assignment constraint (theory and lab)...")
        
        for teacher in self.teachers:
            for day_idx in range(self.num_days):
                for slot_idx in range(self.num_slots):
                    # For theory slots - sum of all classroom assignments must be at most 1
                    theory_vars = [teacher_theory_assignments[teacher][day_idx][slot_idx][room_id] 
                                 for room_id in self.classroom_ids]
                    self.model.Add(sum(theory_vars) <= 1)
                
                # For lab slots - check lab time slots
                if teacher_lab_assignments is not None:
                    for lab_slot_idx in range(self.num_lab_slots):
                        # For lab slots - sum of all lab assignments must be at most 1
                        lab_vars = [teacher_lab_assignments[teacher][day_idx][lab_slot_idx][room_id] 
                                   for room_id in self.lab_ids]
                        self.model.Add(sum(lab_vars) <= 1)
        
        return True
    
    def apply_no_overlapping_slots_constraint(self, teacher_theory_assignments, teacher_lab_assignments=None):
        """
        Constraint 3: No Overlapping Slots Constraint
        Prevents teachers from being assigned to overlapping time slots.
        Checks both theory and lab slot overlaps, including theory block family overlaps.
        """
        logger.info("Applying no overlapping slots constraint...")
        
        if teacher_lab_assignments is None:
            logger.info("No lab assignments provided - skipping lab overlap checks")
            return True
        
        for teacher in self.teachers:
            for day_idx in range(self.num_days):
                # Direct overlap prevention: Check every theory slot against every lab slot
                for theory_slot_idx in range(self.num_slots):
                    theory_time = self.time_slots[theory_slot_idx]
                    
                    # Get all theory assignments for this teacher in this slot
                    theory_assignments = [teacher_theory_assignments[teacher][day_idx][theory_slot_idx][room_id] 
                                        for room_id in self.classroom_ids]
                    
                    # Check for overlapping lab slots
                    for lab_slot_idx in range(self.num_lab_slots):
                        lab_time = self.lab_time_slots[lab_slot_idx]
                        
                        # Check if theory and lab slots overlap
                        if self._times_overlap(theory_time, lab_time):
                            # Get all lab assignments for this teacher in this lab slot
                            lab_assignments = [teacher_lab_assignments[teacher][day_idx][lab_slot_idx][room_id] 
                                             for room_id in self.lab_ids]
                            
                            # STRICT CONSTRAINT: Teacher cannot have both theory and lab at overlapping times
                            # This is a hard constraint - no exceptions
                            theory_total = sum(theory_assignments)
                            lab_total = sum(lab_assignments) 
                            self.model.Add(theory_total + lab_total <= 1)
                            
                            # Additional individual constraints for extra safety
                            for theory_assign in theory_assignments:
                                for lab_assign in lab_assignments:
                                    self.model.Add(theory_assign + lab_assign <= 1)
                
                # Enhanced check: Prevent lab overlap with theory block families
                # This adds additional constraints beyond direct time overlap
                self._apply_comprehensive_theory_lab_constraints(teacher, day_idx, teacher_theory_assignments, teacher_lab_assignments)
                
                # Prevent overlaps within lab slot groups (ensure coherent usage)
                for group_name, slot_indices in self.lab_slot_groups.items():
                    if len(slot_indices) > 1:
                        # Ensure teacher can't be in multiple different labs within the same group simultaneously
                        for i, slot_idx_1 in enumerate(slot_indices):
                            for slot_idx_2 in slot_indices[i+1:]:
                                # For different rooms, prevent simultaneous assignment
                                for room_id_1 in self.lab_ids:
                                    for room_id_2 in self.lab_ids:
                                        if room_id_1 != room_id_2:  # Different rooms
                                            lab_assign_1 = teacher_lab_assignments[teacher][day_idx][slot_idx_1][room_id_1]
                                            lab_assign_2 = teacher_lab_assignments[teacher][day_idx][slot_idx_2][room_id_2]
                                            self.model.Add(lab_assign_1 + lab_assign_2 <= 1)
        
        return True
    
    def _apply_comprehensive_theory_lab_constraints(self, teacher, day_idx, teacher_theory_assignments, teacher_lab_assignments):
        """
        Apply comprehensive constraints to prevent lab assignments from overlapping 
        with theory block families and ensure proper scheduling separation.
        """
        day = self.days[day_idx]
        day_schedule = self.daily_schedule_structure[day]
        
        # Get all theory assignments for this teacher on this day
        for slot_idx, slot_content in enumerate(day_schedule):
            # Parse theory blocks in this slot
            theory_blocks_in_slot = []
            parts = slot_content.split('/')
            for part in parts:
                if part in self.theory_blocks + self.tutorial_blocks:
                    theory_blocks_in_slot.append(part)
            
            if not theory_blocks_in_slot:
                continue
            
            # For each theory block, find its family and prevent lab conflicts
            for theory_block in theory_blocks_in_slot:
                block_family = self._get_theory_block_family(theory_block)
                
                # Find all slots where this block family appears
                family_slots = []
                for check_slot_idx, check_slot_content in enumerate(day_schedule):
                    check_parts = check_slot_content.split('/')
                    for check_part in check_parts:
                        if check_part in block_family:
                            family_slots.append(check_slot_idx)
                            break
                
                # Get theory assignments for this teacher in current slot
                theory_assignments_in_slot = [teacher_theory_assignments[teacher][day_idx][slot_idx][room_id] 
                                            for room_id in self.classroom_ids]
                
                # For each family slot, prevent ALL lab overlaps
                for family_slot_idx in family_slots:
                    if family_slot_idx < len(self.time_slots):
                        family_time = self.time_slots[family_slot_idx]
                        
                        # Check ALL lab slots for overlap with this family slot
                        for lab_slot_idx in range(self.num_lab_slots):
                            lab_time = self.lab_time_slots[lab_slot_idx]
                            
                            # If times overlap, prevent assignment
                            if self._times_overlap(family_time, lab_time):
                                lab_assignments = [teacher_lab_assignments[teacher][day_idx][lab_slot_idx][room_id] 
                                                 for room_id in self.lab_ids]
                                
                                # Comprehensive prevention: if ANY theory assignment exists, NO lab assignment allowed
                                theory_total = sum(theory_assignments_in_slot)
                                lab_total = sum(lab_assignments)
                                self.model.Add(theory_total + lab_total <= 1)
                                
                                # Individual constraints for extra security
                                for theory_assign in theory_assignments_in_slot:
                                    for lab_assign in lab_assignments:
                                        self.model.Add(theory_assign + lab_assign <= 1)
    
    def _get_theory_block_family(self, theory_block):
        """
        Get the family of theory blocks (main block + related tutorial blocks).
        For example, b1 family includes: b1, tb1, tbb1
        """
        if len(theory_block) < 2:
            return [theory_block]
        
        # Extract base letter and number
        if theory_block.startswith('taa'):
            base_letter = 'a'
            base_number = theory_block[3:]
        elif theory_block.startswith('tbb'):
            base_letter = 'b'
            base_number = theory_block[3:]
        elif theory_block.startswith('tcc'):
            base_letter = 'c'
            base_number = theory_block[3:]
        elif theory_block.startswith('t') and len(theory_block) >= 3:
            base_letter = theory_block[1]
            base_number = theory_block[2:]
        else:
            base_letter = theory_block[0]
            base_number = theory_block[1:]
        
        # Build family
        family = []
        base_block = f"{base_letter}{base_number}"
        tutorial_block = f"t{base_letter}{base_number}"
        extended_tutorial_block = f"t{base_letter}{base_letter}{base_number}"
        
        # Add blocks that exist
        if base_block in self.theory_blocks:
            family.append(base_block)
        if tutorial_block in self.tutorial_blocks:
            family.append(tutorial_block)
        if extended_tutorial_block in self.tutorial_blocks:
            family.append(extended_tutorial_block)
        
        # Add special cases
        if base_letter in ['a', 'b', 'c'] and base_number in ['1', '2']:
            # v1, v2 are special tutorial blocks
            if f"v{base_number}" in self.tutorial_blocks:
                family.append(f"v{base_number}")
        
        return family if family else [theory_block]
    
    def _get_teacher_theory_schedule(self, teacher, day_idx):
        """
        Get the theory schedule for a teacher on a specific day.
        This is a placeholder method for future comprehensive schedule analysis.
        """
        # This method can be expanded later for more sophisticated scheduling analysis
        return {}
    
    def _times_overlap(self, time1, time2):
        """Check if two time intervals overlap."""
        def parse_time(time_str):
            # Parse "8:00 - 8:50" format
            start_str, end_str = time_str.split(' - ')
            start_hour, start_min = map(int, start_str.split(':'))
            end_hour, end_min = map(int, end_str.split(':'))
            return start_hour * 60 + start_min, end_hour * 60 + end_min
        
        start1, end1 = parse_time(time1)
        start2, end2 = parse_time(time2)
        
        # Check for overlap: intervals overlap if start1 < end2 and start2 < end1
        return start1 < end2 and start2 < end1
    
    def apply_room_single_assignment_constraint(self, teacher_theory_assignments, teacher_lab_assignments=None):
        """
        Constraint 4: Room Single Assignment Constraint
        A room cannot be assigned to multiple teachers in the same time slot.
        Applies to both classrooms and labs.
        """
        logger.info("Applying room single assignment constraint (classrooms and labs)...")
        
        # For classrooms (theory assignments)
        for room_id in self.classroom_ids:
            for day_idx in range(self.num_days):
                for slot_idx in range(self.num_slots):
                    room_vars = [teacher_theory_assignments[teacher][day_idx][slot_idx][room_id] 
                               for teacher in self.teachers]
                    self.model.Add(sum(room_vars) <= 1)
        
        # For labs (lab assignments)
        if teacher_lab_assignments is not None:
            for room_id in self.lab_ids:
                for day_idx in range(self.num_days):
                    for lab_slot_idx in range(self.num_lab_slots):
                        room_vars = [teacher_lab_assignments[teacher][day_idx][lab_slot_idx][room_id] 
                                   for teacher in self.teachers]
                        self.model.Add(sum(room_vars) <= 1)
        
        return True
    
    def apply_all_constraints(self, teacher_theory_assignments, teacher_lab_assignments=None):
        """Apply all timetable constraints including lab constraints."""
        if teacher_lab_assignments is not None:
            logger.info("Applying all macroblock timetable constraints (theory and lab)...")
        else:
            logger.info("Applying all macroblock timetable constraints (theory only)...")
        
        constraints_applied = [
            self.apply_course_hours_constraint(teacher_theory_assignments, teacher_lab_assignments),
            self.apply_teacher_single_assignment_constraint(teacher_theory_assignments, teacher_lab_assignments),
            self.apply_no_overlapping_slots_constraint(teacher_theory_assignments, teacher_lab_assignments),
            self.apply_room_single_assignment_constraint(teacher_theory_assignments, teacher_lab_assignments),
            self.apply_weekly_working_hour_constraint(teacher_theory_assignments, teacher_lab_assignments),
        ]
        
        # Apply additional lab-specific constraints
        if teacher_lab_assignments is not None:
            constraints_applied.extend([
                self.apply_lab_group_coherence_constraint(teacher_lab_assignments),
                self.apply_same_teacher_same_slot_constraint(teacher_theory_assignments, teacher_lab_assignments),
            ])
        
        return all(constraints_applied)

    def apply_weekly_working_hour_constraint(self, teacher_theory_assignments, teacher_lab_assignments=None):
        """
        Constraint: Weekly Working Hour Constraint
        Limits teacher workload to 21 hours per week.
        
        Hour Calculation:
        - Theory slots: 1 hour each (50 minutes ≈ 1 hour)
        - Lab slots: Each lab slot group = 2 hours (100 minutes ≈ 2 hours)
        
        Formula: theory_hours + 2 × lab_slot_groups ≤ 21
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
            
            # Collect all lab assignment variables for this teacher
            lab_slot_group_vars = []
            if teacher_lab_assignments is not None:
                for day_idx in range(self.num_days):
                    for lab_slot_idx in range(self.num_lab_slots):
                        for room_id in self.lab_ids:
                            lab_assignment = teacher_lab_assignments[teacher][day_idx][lab_slot_idx][room_id]
                            lab_slot_group_vars.append(lab_assignment)
            
            # Apply the weekly hour constraint
            # Theory: 1 hour per slot
            # Lab: Each lab slot = 1 hour, but lab slot groups count as 2 hours
            # We count individual lab slots, so each counts as 1 hour, but we need to account for grouping
            total_theory_hours = sum(theory_hour_vars)
            total_lab_hours = sum(lab_slot_group_vars)  # Each lab slot = 1 hour
            
            # Weekly limit: 21 hours
            self.model.Add(total_theory_hours + total_lab_hours <= 21)
            
            logger.info(f"Applied 21-hour weekly limit for Teacher {teacher}")
        
        return True

    def apply_lab_group_coherence_constraint(self, teacher_lab_assignments):
        """
        Lab-Specific Constraint: Lab Group Coherence
        Ensures that when a lab slot group (e.g., l1) is assigned to multiple course instances,
        all instances use the same lab room for that group.
        Also ensures all slots within a group are used together.
        """
        logger.info("Applying lab group coherence constraint...")
        
        # First pass: Ensure coherence within each course instance
        for teacher in self.teachers:
            if teacher not in self.lab_assignments:
                continue
                
            for instance_id, lab_vars in self.lab_assignments[teacher].items():
                for group_name, slot_indices in self.lab_slot_groups.items():
                    group_chosen_var = lab_vars.get(f'{group_name}_chosen')
                    if group_chosen_var is None:
                        continue
                    
                    for day_idx in range(self.num_days):
                        # If the group is chosen for this instance, ensure coherent assignment
                        for room_id in self.lab_ids:
                            # Collect assignment variables for all slots in this group
                            group_slot_vars = []
                            for slot_idx in slot_indices:
                                if slot_idx < self.num_lab_slots:
                                    slot_var = teacher_lab_assignments[teacher][day_idx][slot_idx][room_id]
                                    group_slot_vars.append(slot_var)
                            
                            if len(group_slot_vars) == len(slot_indices):
                                # If group is chosen, either all slots in group are assigned to same room, or none
                                for i in range(1, len(group_slot_vars)):
                                    # All slots in group must have same assignment state
                                    self.model.Add(group_slot_vars[0] == group_slot_vars[i])
        
        # Second pass: Ensure that different course instances assigned to same lab group use same room
        for group_name, slot_indices in self.lab_slot_groups.items():
            for day_idx in range(self.num_days):
                for slot_idx in slot_indices:
                    if slot_idx < self.num_lab_slots:
                        # Collect all teacher-instance pairs that could be assigned to this lab group
                        group_assignment_vars = []
                        
                        for teacher in self.teachers:
                            if teacher in self.lab_assignments:
                                for instance_id, lab_vars in self.lab_assignments[teacher].items():
                                    group_chosen_var = lab_vars.get(f'{group_name}_chosen')
                                    if group_chosen_var is not None:
                                        # For each room, collect variables for this slot
                                        for room_id in self.lab_ids:
                                            slot_var = teacher_lab_assignments[teacher][day_idx][slot_idx][room_id]
                                            # Create implication: if lab group is chosen for this instance, 
                                            # then this slot assignment must be consistent with room choice
                                            group_assignment_vars.append((teacher, instance_id, room_id, slot_var, group_chosen_var))
                        
                        # For each lab group on each day, ensure at most one room is used
                        for room_id in self.lab_ids:
                            room_assignments = []
                            for teacher, instance_id, r_id, slot_var, group_var in group_assignment_vars:
                                if r_id == room_id:
                                    room_assignments.append(slot_var)
                            
                            # If any instance uses this room for this lab group slot, 
                            # then all instances assigned to this lab group should use this room
                            if len(room_assignments) > 1:
                                # All assignments to this room for this lab group slot should be equal
                                for i in range(1, len(room_assignments)):
                                    # If one instance uses this room, all should use it (or none should)
                                    # This will be enforced by the room single assignment constraint
                                    pass
                        
                        # Ensure that for each lab group slot, at most one room is used across all instances
                        room_usage_vars = []
                        for room_id in self.lab_ids:
                            room_slot_assignments = []
                            for teacher, instance_id, r_id, slot_var, group_var in group_assignment_vars:
                                if r_id == room_id:
                                    room_slot_assignments.append(slot_var)
                            
                            if room_slot_assignments:
                                # Create a variable indicating if this room is used for this lab group slot
                                room_used = self.model.NewBoolVar(f'room_{room_id}_used_for_{group_name}_slot_{slot_idx}_day_{day_idx}')
                                
                                # If any assignment to this room is made, then room_used = 1
                                self.model.Add(sum(room_slot_assignments) <= len(room_slot_assignments) * room_used)
                                self.model.Add(sum(room_slot_assignments) >= room_used)
                                
                                room_usage_vars.append(room_used)
                        
                        # At most one room can be used for each lab group slot
                        if len(room_usage_vars) > 1:
                            self.model.Add(sum(room_usage_vars) <= 1)
        
        return True
    
    def apply_same_teacher_same_slot_constraint(self, teacher_theory_assignments, teacher_lab_assignments):
        """
        Additional Constraint: Same Teacher Same Slot Prevention
        Prevents the same teacher from being assigned to multiple courses in the same time slot
        on the same day (addressing point 3 from requirements).
        """
        logger.info("Applying same teacher same slot constraint...")
        
        for teacher in self.teachers:
            for day_idx in range(self.num_days):
                # Theory slots
                for slot_idx in range(self.num_slots):
                    # Sum of all theory assignments for this teacher in this slot must be <= 1
                    theory_assignments = [teacher_theory_assignments[teacher][day_idx][slot_idx][room_id] 
                                        for room_id in self.classroom_ids]
                    self.model.Add(sum(theory_assignments) <= 1)
                
                # Lab slots  
                for lab_slot_idx in range(self.num_lab_slots):
                    # Sum of all lab assignments for this teacher in this lab slot must be <= 1
                    lab_assignments = [teacher_lab_assignments[teacher][day_idx][lab_slot_idx][room_id] 
                                     for room_id in self.lab_ids]
                    self.model.Add(sum(lab_assignments) <= 1)
        
        return True

    def _apply_lab_group_distribution_constraints(self):
        """
        Apply constraints to distribute lab groups more evenly across teachers and course instances.
        Prevents all assignments from clustering on l1.
        """
        logger.info("Applying lab group distribution constraints...")
        
        # Collect all lab group assignment variables across all teachers
        all_lab_group_assignments = {}
        for group_name in self.lab_slot_groups.keys():
            all_lab_group_assignments[group_name] = []
        
        for teacher in self.teachers:
            if teacher in self.lab_assignments:
                for instance_id, lab_vars in self.lab_assignments[teacher].items():
                    for group_name in self.lab_slot_groups.keys():
                        group_var = lab_vars.get(f'{group_name}_chosen')
                        if group_var is not None:
                            all_lab_group_assignments[group_name].append(group_var)
        
        # Calculate total number of lab assignments
        total_lab_assignments = sum(len(vars_list) for vars_list in all_lab_group_assignments.values())
        
        if total_lab_assignments == 0:
            return  # No lab assignments to distribute
        
        # Apply distribution constraints to prevent clustering
        group_names = list(self.lab_slot_groups.keys())
        num_groups = len(group_names)
        
        if num_groups > 1 and total_lab_assignments > num_groups:
            # Calculate expected assignments per group (rough distribution)
            avg_assignments_per_group = total_lab_assignments // num_groups
            max_assignments_per_group = avg_assignments_per_group + 2  # Allow some flexibility
            
            # Prevent any single lab group from being overloaded
            for group_name, group_vars in all_lab_group_assignments.items():
                if len(group_vars) > 0:
                    # Limit assignments to prevent clustering
                    self.model.Add(sum(group_vars) <= max_assignments_per_group)
                    logger.info(f"Limited lab group {group_name} to max {max_assignments_per_group} assignments")
            
            # Encourage use of multiple lab groups
            # At least 2 different lab groups should be used if we have enough assignments
            if total_lab_assignments >= 2:
                group_used_vars = []
                for group_name, group_vars in all_lab_group_assignments.items():
                    if len(group_vars) > 0:
                        # Create indicator variable for whether this group is used
                        group_used = self.model.NewBoolVar(f'lab_group_{group_name}_used')
                        
                        # If any assignment to this group, then group_used = 1
                        self.model.Add(sum(group_vars) <= len(group_vars) * group_used)
                        self.model.Add(sum(group_vars) >= group_used)
                        
                        group_used_vars.append(group_used)
                
                # Require at least 2 different lab groups to be used if possible
                min_groups_to_use = min(2, len(group_used_vars))
                if len(group_used_vars) >= min_groups_to_use:
                    self.model.Add(sum(group_used_vars) >= min_groups_to_use)
                    logger.info(f"Required at least {min_groups_to_use} different lab groups to be used")
        
        # Additional constraint: spread assignments for same teacher across different groups
        for teacher in self.teachers:
            if teacher in self.lab_assignments:
                teacher_instances = list(self.lab_assignments[teacher].keys())
                if len(teacher_instances) > 1:
                    # If teacher has multiple instances with labs, try to use different groups
                    for group_name in self.lab_slot_groups.keys():
                        group_assignments_for_teacher = []
                        for instance_id in teacher_instances:
                            group_var = self.lab_assignments[teacher][instance_id].get(f'{group_name}_chosen')
                            if group_var is not None:
                                group_assignments_for_teacher.append(group_var)
                        
                        # Limit same teacher from using same group for multiple instances
                        if len(group_assignments_for_teacher) > 1:
                            # Allow at most 1 instance per teacher per group (this was already added above but reinforcing)
                            self.model.Add(sum(group_assignments_for_teacher) <= 1)
                            logger.info(f"Limited teacher {teacher} to max 1 instance in lab group {group_name}")
