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
        
        # Lab time slots (L slots - different timing structure)
        self.lab_time_slots = [
            "8:00 - 8:50", "8:50 - 9:40", "9:50 - 10:40", "10:40 - 11:30",
            "11:50 - 12:40", "12:40 - 1:30", "1:50 - 2:40", "2:40 - 3:30", 
            "3:50 - 4:40", "4:40 - 5:30", "5:30 - 6:20", "6:20 - 7:10"
        ]
        
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
                
                semester_groups[key].append({
                    'teacher': teacher,
                    'instance': instance,
                    'course_code': course_code
                })
        
        return semester_groups
    
    def apply_course_hours_constraint(self, teacher_theory_assignments, teacher_lab_assignments=None):
        """
        Constraint 1: Course Hours Constraint
        Ensures each course instance receives exactly its required lecture and tutorial hours.
        Uses macroblock structure where courses must be assigned consistently within blocks.
        OPTIMIZATION: When a macroblock is chosen, allocate the entire span needed for that course.
        Lab assignments are skipped for now as requested.
        """
        logger.info("Applying course hours constraint with macroblock span optimization (skipping labs)...")
        
        # Create macroblock assignment variables
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
                for block in self.theory_blocks:
                    self.macroblock_assignments[teacher][instance_id][f'{block}_chosen'] = (
                        self.model.NewBoolVar(f'teacher_{teacher}_instance_{instance_id}_{block}_chosen'))
                
                # Determine if tutorials should be allocated:
                should_allocate_tutorials = tutorial_hours > 0 or lecture_hours == 4
                
                # Ensure exactly one block is chosen per course instance (if it has theory hours)
                if lecture_hours > 0 or should_allocate_tutorials:
                    block_choices = []
                    
                    # Collect all possible block choices
                    for block in self.theory_blocks:
                        if f'{block}_chosen' in self.macroblock_assignments[teacher][instance_id]:
                            block_choices.append(
                                self.macroblock_assignments[teacher][instance_id][f'{block}_chosen'])
                    
                    # Must assign exactly one macroblock for significant courses
                    if block_choices and (lecture_hours >= 2 or tutorial_hours >= 1):
                        self.model.Add(sum(block_choices) == 1)  # Exactly one block
                    elif block_choices:
                        self.model.Add(sum(block_choices) <= 1)  # At most one block for small courses
                    
                    # Apply macroblock span allocation constraints
                    self._apply_macroblock_span_constraints(teacher, instance, teacher_theory_assignments)
                    
                    logger.info(f"Course instance {instance_id} (Teacher {teacher}, {lecture_hours}L+{tutorial_hours}T) - macroblock span allocation")
                
                # Link macroblock assignments to actual slot assignments (skip labs)
                self._link_macroblock_to_slots(teacher, instance, teacher_theory_assignments, None)
        
        # Apply semester and department grouping constraints
        self._apply_semester_grouping_constraints()
        
        return True
    
    def _apply_macroblock_span_constraints(self, teacher, instance, teacher_theory_assignments):
        """Apply constraints to ensure that when a macroblock is chosen, the appropriate span is allocated."""
        instance_id = instance['id']
        lecture_hours = instance['lecture_hours']
        tutorial_hours = instance['tutorial_hours']
        
        # For each chosen macroblock, ensure proper span allocation
        for block in self.theory_blocks:
            if f'{block}_chosen' in self.macroblock_assignments[teacher][instance_id]:
                block_chosen = self.macroblock_assignments[teacher][instance_id][f'{block}_chosen']
                
                # When this block is chosen, allocate required hours within the span
                self._allocate_macroblock_span(teacher, instance_id, block, block_chosen, 
                                             lecture_hours, tutorial_hours, teacher_theory_assignments)
    
    def _allocate_macroblock_span(self, teacher, instance_id, chosen_block, block_chosen_var, 
                                lecture_hours, tutorial_hours, teacher_theory_assignments):
        """Allocate the required hours within a macroblock span when that block is chosen."""
        
        # Get all slots that belong to this macroblock across all days
        lecture_slots = []  # For main block (a1, b1, etc.)
        tutorial_slots = []  # For tutorial block (ta1, tb1, etc.)
        extended_tutorial_slots = []  # For extended tutorial (taa1, tbb1, etc.)
        
        block_letter = chosen_block[0]  # 'a', 'b', 'c', etc.
        block_number = chosen_block[1]  # '1' or '2'
        
        for day_idx, day in enumerate(self.days):
            for slot_info in self.slot_assignments[day]:
                slot_idx = slot_info['slot_index']
                theory_blocks = slot_info['theory_blocks']
                
                # Check if this slot contains our chosen block
                if chosen_block in theory_blocks:
                    lecture_slots.append((day_idx, slot_idx))
                
                # Check for tutorial blocks related to our chosen block
                tutorial_block = f't{block_letter}{block_number}'  # ta1, tb1, etc.
                if tutorial_block in theory_blocks:
                    tutorial_slots.append((day_idx, slot_idx))
                
                # Check for extended tutorial blocks
                extended_tutorial_block = f't{block_letter}{block_letter}{block_number}'  # taa1, tbb1, etc.
                if extended_tutorial_block in theory_blocks:
                    extended_tutorial_slots.append((day_idx, slot_idx))
        
        # For 3-lecture courses: allocate exactly 2 lecture slots + 1 tutorial slot
        if lecture_hours == 3:
            # Ensure we have enough slots available
            total_available_slots = len(lecture_slots) + len(tutorial_slots) + len(extended_tutorial_slots)
            if total_available_slots < 3:
                logger.warning(f"Not enough slots available for 3-hour course {instance_id} in block {chosen_block}")
                return
            
            # Allocate exactly 2 lecture slots
            lecture_assignments = []
            for i, (day_idx, slot_idx) in enumerate(lecture_slots[:2]):  # Take first 2 lecture slots
                for room_id in self.classroom_ids:
                    room_assignment = teacher_theory_assignments[teacher][day_idx][slot_idx][room_id]
                    lecture_assignment = self.model.NewBoolVar(
                        f'span_lecture_{teacher}_{instance_id}_{chosen_block}_{day_idx}_{slot_idx}_{room_id}')
                    
                    # If block is chosen and room is assigned, this is a lecture assignment
                    self.model.Add(lecture_assignment == 1).OnlyEnforceIf([block_chosen_var, room_assignment])
                    self.model.Add(lecture_assignment == 0).OnlyEnforceIf([block_chosen_var.Not()])
                    self.model.Add(lecture_assignment == 0).OnlyEnforceIf([room_assignment.Not()])
                    
                    lecture_assignments.append(lecture_assignment)
            
            # Allocate exactly 1 tutorial slot (for the 3rd hour)
            tutorial_assignments = []
            all_tutorial_slots = tutorial_slots + extended_tutorial_slots
            if all_tutorial_slots:
                # Take first tutorial slot available
                day_idx, slot_idx = all_tutorial_slots[0]
                for room_id in self.classroom_ids:
                    room_assignment = teacher_theory_assignments[teacher][day_idx][slot_idx][room_id]
                    tutorial_assignment = self.model.NewBoolVar(
                        f'span_tutorial_{teacher}_{instance_id}_{chosen_block}_{day_idx}_{slot_idx}_{room_id}')
                    
                    self.model.Add(tutorial_assignment == 1).OnlyEnforceIf([block_chosen_var, room_assignment])
                    self.model.Add(tutorial_assignment == 0).OnlyEnforceIf([block_chosen_var.Not()])
                    self.model.Add(tutorial_assignment == 0).OnlyEnforceIf([room_assignment.Not()])
                    
                    tutorial_assignments.append(tutorial_assignment)
            
            # Enforce exactly 2 lecture hours + 1 tutorial hour when block is chosen
            if lecture_assignments:
                total_lecture_hours = sum(lecture_assignments)
                self.model.Add(total_lecture_hours == 2).OnlyEnforceIf([block_chosen_var])  # Exactly 2 lectures
            
            if tutorial_assignments:
                total_tutorial_hours = sum(tutorial_assignments)
                self.model.Add(total_tutorial_hours == 1).OnlyEnforceIf([block_chosen_var])  # Exactly 1 tutorial
                
            logger.info(f"Configured 3-hour course {instance_id}: 2 lectures + 1 tutorial in block {chosen_block}")
            
        # For other lecture hour counts, use flexible allocation
        else:
            # Allocate lecture hours: when block is chosen, use required number of lecture slots
            if lecture_hours > 0 and lecture_slots:
                lecture_assignments = []
                for day_idx, slot_idx in lecture_slots:
                    for room_id in self.classroom_ids:
                        room_assignment = teacher_theory_assignments[teacher][day_idx][slot_idx][room_id]
                        lecture_assignment = self.model.NewBoolVar(
                            f'span_lecture_{teacher}_{instance_id}_{chosen_block}_{day_idx}_{slot_idx}_{room_id}')
                        
                        # If block is chosen and room is assigned, this is a lecture assignment
                        self.model.Add(lecture_assignment == 1).OnlyEnforceIf([block_chosen_var, room_assignment])
                        self.model.Add(lecture_assignment == 0).OnlyEnforceIf([block_chosen_var.Not()])
                        self.model.Add(lecture_assignment == 0).OnlyEnforceIf([room_assignment.Not()])
                        
                        lecture_assignments.append(lecture_assignment)
                
                # Ensure we allocate the right number of lecture hours when block is chosen
                if lecture_assignments:
                    # When block is chosen, must allocate at least the required lecture hours
                    total_lecture_hours = sum(lecture_assignments)
                    min_required = min(lecture_hours, len(lecture_slots))  # Can't exceed available slots
                    
                    # Conditional constraint: IF block is chosen, THEN allocate required hours
                    self.model.Add(total_lecture_hours >= min_required).OnlyEnforceIf([block_chosen_var])
                    self.model.Add(total_lecture_hours <= lecture_hours + 1).OnlyEnforceIf([block_chosen_var])  # Allow 1 extra
            
            # Allocate tutorial hours: use tutorial and extended tutorial slots as needed
            should_allocate_tutorials = tutorial_hours > 0 or lecture_hours == 4
            if should_allocate_tutorials:
                all_tutorial_assignments = []
                
                # Regular tutorial slots (ta1, tb1, etc.)
                for day_idx, slot_idx in tutorial_slots:
                    for room_id in self.classroom_ids:
                        room_assignment = teacher_theory_assignments[teacher][day_idx][slot_idx][room_id]
                        tutorial_assignment = self.model.NewBoolVar(
                            f'span_tutorial_{teacher}_{instance_id}_{chosen_block}_{day_idx}_{slot_idx}_{room_id}')
                        
                        self.model.Add(tutorial_assignment == 1).OnlyEnforceIf([block_chosen_var, room_assignment])
                        self.model.Add(tutorial_assignment == 0).OnlyEnforceIf([block_chosen_var.Not()])
                        self.model.Add(tutorial_assignment == 0).OnlyEnforceIf([room_assignment.Not()])
                        
                        all_tutorial_assignments.append(tutorial_assignment)
                
                # Extended tutorial slots (taa1, tbb1, etc.)
                for day_idx, slot_idx in extended_tutorial_slots:
                    for room_id in self.classroom_ids:
                        room_assignment = teacher_theory_assignments[teacher][day_idx][slot_idx][room_id]
                        ext_tutorial_assignment = self.model.NewBoolVar(
                            f'span_ext_tutorial_{teacher}_{instance_id}_{chosen_block}_{day_idx}_{slot_idx}_{room_id}')
                        
                        self.model.Add(ext_tutorial_assignment == 1).OnlyEnforceIf([block_chosen_var, room_assignment])
                        self.model.Add(ext_tutorial_assignment == 0).OnlyEnforceIf([block_chosen_var.Not()])
                        self.model.Add(ext_tutorial_assignment == 0).OnlyEnforceIf([room_assignment.Not()])
                        
                        all_tutorial_assignments.append(ext_tutorial_assignment)
                
                # Ensure appropriate tutorial allocation when block is chosen
                if all_tutorial_assignments and tutorial_hours > 0:
                    total_tutorial_hours = sum(all_tutorial_assignments)
                    min_tutorial_required = min(tutorial_hours, len(tutorial_slots) + len(extended_tutorial_slots))
                    
                    # Conditional constraint: IF block is chosen AND tutorials needed, THEN allocate
                    self.model.Add(total_tutorial_hours >= min_tutorial_required).OnlyEnforceIf([block_chosen_var])
                    self.model.Add(total_tutorial_hours <= tutorial_hours * 2).OnlyEnforceIf([block_chosen_var])  # Allow flexibility
    
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
        """Link macroblock assignments to actual time slot assignments. Skip lab linking."""
        instance_id = instance['id']
        lecture_hours = instance['lecture_hours']
        tutorial_hours = instance['tutorial_hours']
        practical_hours = instance['practical_hours']  # Not used for now
        
        # Determine if tutorials should be allocated
        should_allocate_tutorials = tutorial_hours > 0 or lecture_hours == 4
        
        # For each day and slot, link to macroblock assignments
        for day_idx, day in enumerate(self.days):
            for slot_info in self.slot_assignments[day]:
                slot_idx = slot_info['slot_index']
                theory_blocks = slot_info['theory_blocks']
                lab_slots = slot_info['lab_slots']
                
                # Handle theory assignments
                for block in theory_blocks:
                    if block in ['a1', 'a2', 'b1', 'b2', 'c1', 'c2', 'd1', 'd2', 'e1', 'e2', 'f1', 'f2', 'g1', 'g2']:
                        # Lecture block - only access if it was created for this teacher
                        if f'{block}_chosen' in self.macroblock_assignments[teacher][instance_id]:
                            block_chosen = self.macroblock_assignments[teacher][instance_id][f'{block}_chosen']
                            
                            # Link to classroom assignments
                            for room_id in self.classroom_ids:
                                room_assignment = teacher_theory_assignments[teacher][day_idx][slot_idx][room_id]
                                # If block is chosen and room is assigned, this counts as a lecture hour
                                is_lecture_assignment = self.model.NewBoolVar(
                                    f'teacher_{teacher}_instance_{instance_id}_day_{day_idx}_slot_{slot_idx}_room_{room_id}_lecture')
                                
                                self.model.Add(is_lecture_assignment == 1).OnlyEnforceIf([block_chosen, room_assignment])
                                self.model.Add(is_lecture_assignment == 0).OnlyEnforceIf([block_chosen.Not()])
                                self.model.Add(is_lecture_assignment == 0).OnlyEnforceIf([room_assignment.Not()])
                    
                    elif block in ['ta1', 'ta2', 'tb1', 'tb2', 'tc1', 'tc2', 'td1', 'td2', 'te1', 'te2', 'tf1', 'tf2', 'tg1', 'tg2', 'taa1', 'taa2', 'tbb1', 'tbb2', 'tcc1', 'tcc2', 'v1', 'v2']:
                        # Tutorial block - determine parent block
                        if block.startswith('taa'):
                            parent_block = 'aa' + block[3:]  # taa1 -> aa1
                        elif block.startswith('tbb'):
                            parent_block = 'bb' + block[3:]  # tbb1 -> bb1
                        elif block.startswith('tcc'):
                            parent_block = 'cc' + block[3:]  # tcc1 -> cc1
                        elif block.startswith('v'):
                            parent_block = block  # v1 -> v1 (standalone tutorial block)
                        else:
                            parent_block = block[1:]  # Remove 't' prefix: ta1 -> a1
                        
                        # Find corresponding parent block choice
                        if f'{parent_block}_chosen' in self.macroblock_assignments[teacher][instance_id]:
                            parent_chosen = self.macroblock_assignments[teacher][instance_id][f'{parent_block}_chosen']
                            
                            # Link to classroom assignments for tutorial
                            for room_id in self.classroom_ids:
                                room_assignment = teacher_theory_assignments[teacher][day_idx][slot_idx][room_id]
                                is_tutorial_assignment = self.model.NewBoolVar(
                                    f'teacher_{teacher}_instance_{instance_id}_day_{day_idx}_slot_{slot_idx}_room_{room_id}_tutorial')
                                
                                self.model.Add(is_tutorial_assignment == 1).OnlyEnforceIf([parent_chosen, room_assignment])
                                self.model.Add(is_tutorial_assignment == 0).OnlyEnforceIf([parent_chosen.Not()])
                                self.model.Add(is_tutorial_assignment == 0).OnlyEnforceIf([room_assignment.Not()])
        
        # Ensure exact hour requirements are met (skip labs)
        self._enforce_flexible_hours(teacher, instance, teacher_theory_assignments, None)
    
    def _enforce_flexible_hours(self, teacher, instance, teacher_theory_assignments, teacher_lab_assignments):
        """Enforce flexible hour requirements for each course instance. Skip lab hours."""
        instance_id = instance['id']
        lecture_hours = instance['lecture_hours']
        tutorial_hours = instance['tutorial_hours']
        practical_hours = instance['practical_hours']  # Not enforced for now
        
        # Determine if tutorials should be allocated
        should_allocate_tutorials = tutorial_hours > 0 or lecture_hours == 4
        
        # Count total lecture hours assigned - stricter for 3-lecture courses
        if lecture_hours > 0:
            lecture_vars = []
            
            for day_idx, day in enumerate(self.days):
                for slot_info in self.slot_assignments[day]:
                    slot_idx = slot_info['slot_index']
                    theory_blocks = slot_info['theory_blocks']
                    
                    # Only check blocks from accessible macroblock shifts
                    accessible_blocks = []
                    for block in self.theory_blocks:
                        if block in theory_blocks:
                            accessible_blocks.append(block)
                    
                    for block in accessible_blocks:
                        if block in ['a1', 'a2', 'b1', 'b2', 'c1', 'c2', 'd1', 'd2', 'e1', 'e2', 'f1', 'f2', 'g1', 'g2']:
                            # Only access blocks that were actually created for this teacher
                            if f'{block}_chosen' in self.macroblock_assignments[teacher][instance_id]:
                                block_chosen = self.macroblock_assignments[teacher][instance_id][f'{block}_chosen']
                                
                                for room_id in self.classroom_ids:
                                    room_assignment = teacher_theory_assignments[teacher][day_idx][slot_idx][room_id]
                                    lecture_hour = self.model.NewBoolVar(f'lecture_hour_{teacher}_{instance_id}_{day_idx}_{slot_idx}_{room_id}')
                                    
                                    self.model.Add(lecture_hour == 1).OnlyEnforceIf([block_chosen, room_assignment])
                                    self.model.Add(lecture_hour == 0).OnlyEnforceIf([block_chosen.Not()])
                                    self.model.Add(lecture_hour == 0).OnlyEnforceIf([room_assignment.Not()])
                                    
                                    lecture_vars.append(lecture_hour)
            
            # More flexible hour requirements for non-3-lecture courses, stricter for 3-lecture courses
            if lecture_vars:
                if lecture_hours == 3:
                    # For 3-lecture courses, enforce exactly 2 lecture hours (the 3rd is tutorial)
                    self.model.Add(sum(lecture_vars) == 2)
                    logger.info(f"Enforcing exactly 2 lecture hours for 3-lecture course {instance_id}")
                else:
                    # Allow 50% flexibility for other courses: can be 50% to 150% of required hours
                    min_hours = max(1, lecture_hours // 2)  # At least half, minimum 1
                    max_hours = lecture_hours * 2  # Up to double
                    self.model.Add(sum(lecture_vars) >= min_hours)
                    self.model.Add(sum(lecture_vars) <= max_hours)
        
        # Count total tutorial hours assigned - stricter for 3-lecture courses
        if should_allocate_tutorials or lecture_hours == 3:  # Include 3-lecture courses
            tutorial_vars = []
            # Calculate expected tutorial hours based on allocation rules
            if tutorial_hours > 0:
                expected_tutorial_hours = tutorial_hours
            elif lecture_hours == 4:
                expected_tutorial_hours = 1
            elif lecture_hours == 3:
                expected_tutorial_hours = 1  # 3rd hour for 3-lecture courses
            else:
                expected_tutorial_hours = 0
            
            for day_idx, day in enumerate(self.days):
                for slot_info in self.slot_assignments[day]:
                    slot_idx = slot_info['slot_index']
                    theory_blocks = slot_info['theory_blocks']
                    
                    # Only check blocks from accessible macroblock shifts
                    accessible_blocks = []
                    for block in self.theory_blocks:
                        if block in theory_blocks:
                            accessible_blocks.append(block)
                    
                    for block in accessible_blocks:
                        if block in ['ta1', 'ta2', 'tb1', 'tb2', 'tc1', 'tc2', 'td1', 'td2', 'te1', 'te2', 'tf1', 'tf2', 'tg1', 'tg2', 'taa1', 'taa2', 'tbb1', 'tbb2', 'tcc1', 'tcc2', 'v1', 'v2']:
                            # Find parent block
                            if block.startswith('taa'):
                                parent_block = 'aa' + block[3:]  # taa1 -> aa1
                            elif block.startswith('tbb'):
                                parent_block = 'bb' + block[3:]  # tbb1 -> bb1
                            elif block.startswith('tcc'):
                                parent_block = 'cc' + block[3:]  # tcc1 -> cc1
                            elif block.startswith('v'):
                                parent_block = block  # v1 -> v1 (standalone tutorial block)
                            else:
                                parent_block = block[1:]  # Remove 't' prefix: ta1 -> a1
                            
                            if f'{parent_block}_chosen' in self.macroblock_assignments[teacher][instance_id]:
                                parent_chosen = self.macroblock_assignments[teacher][instance_id][f'{parent_block}_chosen']
                                
                                for room_id in self.classroom_ids:
                                    room_assignment = teacher_theory_assignments[teacher][day_idx][slot_idx][room_id]
                                    tutorial_hour = self.model.NewBoolVar(f'tutorial_hour_{teacher}_{instance_id}_{day_idx}_{slot_idx}_{room_id}')
                                    
                                    self.model.Add(tutorial_hour == 1).OnlyEnforceIf([parent_chosen, room_assignment])
                                    self.model.Add(tutorial_hour == 0).OnlyEnforceIf([parent_chosen.Not()])
                                    self.model.Add(tutorial_hour == 0).OnlyEnforceIf([room_assignment.Not()])
                                    
                                    tutorial_vars.append(tutorial_hour)
            
            if expected_tutorial_hours > 0 and tutorial_vars:
                if lecture_hours == 3:
                    # For 3-lecture courses, enforce exactly 1 tutorial hour (the 3rd hour)
                    self.model.Add(sum(tutorial_vars) == 1)
                    logger.info(f"Enforcing exactly 1 tutorial hour for 3-lecture course {instance_id}")
                else:
                    # Very flexible tutorial requirements for other courses - can be 0 to 3x expected
                    max_tutorial_hours = max(3, expected_tutorial_hours * 3)
                    self.model.Add(sum(tutorial_vars) <= max_tutorial_hours)
                    # Don't enforce minimum tutorial hours for non-3-lecture courses - make it optional
        
        # Skip practical hours enforcement as requested
    
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
