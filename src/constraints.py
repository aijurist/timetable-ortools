import logging
from ortools.sat.python import cp_model
import random

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
        
        # Time slots based on update.txt structure
        self.time_slots = [
            "8:00 - 8:50", "8:50 - 9:40", "9:50 - 10:40", "10:40 - 11:30",
            "11:50 - 12:40", "12:40 - 1:30", "1:50 - 2:40", "2:40 - 3:30", 
            "3:50 - 4:40", "4:40 - 5:30", "5:30 - 6:20", "6:20 - 7:10"
        ]
        self.num_slots = len(self.time_slots)
        
        # Teacher shift definitions (when teachers are available to work)
        self.teacher_shifts = {
            'teacher_shift1': {
                'name': 'Teacher Shift 1',
                'time_range': '8:00 - 15:00',
                'start_hour': 8,
                'end_hour': 15,
                'time_slots': ["8:00 - 8:50", "8:50 - 9:40", "9:50 - 10:40", "10:40 - 11:30",
                              "11:50 - 12:40", "12:40 - 1:30", "1:50 - 2:40"]  # 8:00-14:50
            },
            'teacher_shift2': {
                'name': 'Teacher Shift 2', 
                'time_range': '10:00 - 17:00',
                'start_hour': 10,
                'end_hour': 17,
                'time_slots': ["9:50 - 10:40", "10:40 - 11:30", "11:50 - 12:40", "12:40 - 1:30",
                              "1:50 - 2:40", "2:40 - 3:30", "3:50 - 4:40"]  # 10:00-16:50
            },
            'teacher_shift3': {
                'name': 'Teacher Shift 3',
                'time_range': '12:00 - 19:00',
                'start_hour': 12,
                'end_hour': 19,
                'time_slots': ["11:50 - 12:40", "12:40 - 1:30", "1:50 - 2:40", "2:40 - 3:30", 
                              "3:50 - 4:40", "4:40 - 5:30", "5:30 - 6:20"]  # 12:00-18:50
            }
        }
        
        # Macroblock shift definitions (scheduling slot groups)
        self.macroblock_shifts = {
            'macro_shift1': {
                'name': 'Macroblock Shift 1',
                'time_range': '8:00 - 12:50',  # Until 12:50, not 13:00
                'time_slots': ["8:00 - 8:50", "8:50 - 9:40", "9:50 - 10:40", "10:40 - 11:30",
                              "11:50 - 12:40"]  # 8:00-12:40 (5 slots)
            },
            'macro_shift2': {
                'name': 'Macroblock Shift 2',
                'time_range': '10:00 - 16:50',
                'time_slots': ["9:50 - 10:40", "10:40 - 11:30", "11:50 - 12:40", "12:40 - 1:30",
                              "1:50 - 2:40", "2:40 - 3:30", "3:50 - 4:40"]  # 10:00-16:50 (7 slots)
            },
            'macro_shift3': {
                'name': 'Macroblock Shift 3',
                'time_range': '12:00 - 18:50',
                'time_slots': ["11:50 - 12:40", "12:40 - 1:30", "1:50 - 2:40", "2:40 - 3:30", 
                              "3:50 - 4:40", "4:40 - 5:30", "5:30 - 6:20"]  # 12:00-18:50 (7 slots)
            }
        }
        
        # Teacher-to-Macroblock compatibility mapping
        # This defines which macroblock shifts a teacher can access based on their teacher shift
        self.teacher_macroblock_compatibility = {
            'teacher_shift1': {
                'macro_shift1': True,   # Full access (5 slots available)
                'macro_shift2': True,   # Partial access (overlapping slots until 14:50)
                'macro_shift3': False   # No access (starts at 12:00, teacher ends at 15:00, minimal overlap)
            },
            'teacher_shift2': {
                'macro_shift1': True,   # Partial access (overlapping slots from 10:00)
                'macro_shift2': True,   # Full access (7 slots available)
                'macro_shift3': True    # Full access (7 slots available)
            },
            'teacher_shift3': {
                'macro_shift1': False,  # No access (ends at 12:50, teacher starts at 12:00, minimal overlap)
                'macro_shift2': True,   # Partial access (overlapping slots from 12:00)
                'macro_shift3': True    # Full access (7 slots available)
            }
        }
        
        # Macroblock structure from update.txt
        self.daily_schedule_structure = {
            "tuesday": ["a1/L1", "f1/L2", "d1/L3", "b1/a2/L4", "g1/f2/L5", "d2/L6", 
                       "b2/a3/L7", "g2/f3/L8", "d3/L9", "b3/L10", "g3/L11", "L12"],
            "wed": ["b1/L12", "g1/L14", "e1/L15", "c1/b2/L24", "ta1/g2/L17", "e1/L18", 
                   "c2/b3/L19", "ta2/g3/L20", "e3/L21", "c3/L22", "ta3/L23", "L24"],
            "thur": ["c1/L25", "a1/L26", "f1/L27", "d1/c2/L28", "tb1/a2/L29", "f2/L30", 
                    "d2/c3/L31", "tb2/a3/L32", "f3/L33", "d3/L34", "tb3/L35", "L36"],
            "fri": ["d1/L37", "b1/L38", "g1/L39", "e1/d2/L40", "tc1/b2/L41", "g2/L42", 
                   "e2/d3/L43", "tc2/b4/L44", "g3/L45", "e3/L46", "tc3/L47", "L46"],
            "sat": ["e1/L49", "c1/L50", "a1/L51", "f1/e2/L52", "td1/c2/L53", "a2/L54", 
                   "f2/e3/L55", "td2/c3/L56", "a3/L57", "f3/L58", "td3/L59", "L60"]
        }
        
        # Define macroblock groups with MACROBLOCK shift assignments (not teacher shifts)
        self.theory_blocks = {
            'macro_shift1': ['a1', 'b1', 'c1', 'd1', 'e1', 'f1', 'g1'],
            'macro_shift2': ['a2', 'b2', 'c2', 'd2', 'e2', 'f2', 'g2'],
            'macro_shift3': ['a3', 'b3', 'c3', 'd3', 'e3', 'f3', 'g3']
        }
        
        self.tutorial_blocks = {
            'macro_shift1': ['ta1', 'tb1', 'tc1', 'td1'],
            'macro_shift2': ['ta2', 'tb2', 'tc2', 'td2'],
            'macro_shift3': ['ta3', 'tb3', 'tc3', 'td3']
        }
        
        # Parse slot assignments for each day to identify theory and lab slots
        self.slot_assignments = self._parse_slot_assignments()
        
        # Pre-compute room IDs for efficiency
        self.classroom_ids = self.classrooms['id'].tolist()
        self.lab_ids = self.labs['id'].tolist()
    
        # Group courses by semester and department for better allocation
        self.semester_course_groups = self._group_courses_by_semester_dept()
        
        # Assign teachers to shifts
        self.teacher_shift_assignments = self._assign_teachers_to_shifts()
    
    def _assign_teachers_to_shifts(self):
        """Assign teachers to shifts based on 33% distribution per department."""
        logger.info("Assigning teachers to shifts (33% per department)...")
        
        # Group teachers by department
        dept_teachers = {}
        for teacher in self.teachers:
            if teacher in self.teacher_course_assignments:
                # Get department from first course assignment
                first_instance = self.teacher_course_assignments[teacher][0]
                dept = first_instance.get('course_dept', 'Computer Science & Engineering')
                
                if dept not in dept_teachers:
                    dept_teachers[dept] = []
                dept_teachers[dept].append(teacher)
        
        teacher_shifts = {}
        
        # Assign teachers to shifts for each department
        for dept, teachers_list in dept_teachers.items():
            # Shuffle for random distribution
            shuffled_teachers = teachers_list.copy()
            random.shuffle(shuffled_teachers)
            
            # Calculate distribution (33% each, remainder to shift1)
            total_teachers = len(teachers_list)
            shift1_count = total_teachers // 3
            shift2_count = total_teachers // 3
            shift3_count = total_teachers - shift1_count - shift2_count  # Remainder goes to shift3
            
            # Assign teachers
            shift_assignments = (
                ['teacher_shift1'] * shift1_count + 
                ['teacher_shift2'] * shift2_count + 
                ['teacher_shift3'] * shift3_count
            )
            
            for teacher, shift in zip(shuffled_teachers, shift_assignments):
                teacher_shifts[teacher] = shift
                logger.info(f"Assigned Teacher {teacher} to {shift} (Department: {dept})")
        
        return teacher_shifts
    
    def _parse_slot_assignments(self):
        """Parse the daily schedule structure to identify theory and lab slots with macroblock shift information."""
        slot_assignments = {}
        
        for day, schedule in self.daily_schedule_structure.items():
            slot_assignments[day] = []
            for slot_idx, content in enumerate(schedule):
                theory_blocks = []
                lab_slots = []
                macroblock_shift_blocks = {'macro_shift1': [], 'macro_shift2': [], 'macro_shift3': []}
                
                # Split content by '/'
                parts = content.split('/')
                for part in parts:
                    if part.startswith('L'):
                        lab_slots.append(part)
                    elif part in ['a1', 'b1', 'c1', 'd1', 'e1', 'f1', 'g1', 
                                 'ta1', 'tb1', 'tc1', 'td1']:
                        theory_blocks.append(part)
                        macroblock_shift_blocks['macro_shift1'].append(part)
                    elif part in ['a2', 'b2', 'c2', 'd2', 'e2', 'f2', 'g2',
                                 'ta2', 'tb2', 'tc2', 'td2']:
                        theory_blocks.append(part)
                        macroblock_shift_blocks['macro_shift2'].append(part)
                    elif part in ['a3', 'b3', 'c3', 'd3', 'e3', 'f3', 'g3',
                                 'ta3', 'tb3', 'tc3', 'td3']:
                        theory_blocks.append(part)
                        macroblock_shift_blocks['macro_shift3'].append(part)
                
                # Determine if this is an overlapping slot (multiple macroblock shifts active)
                active_macro_shifts = [shift for shift, blocks in macroblock_shift_blocks.items() if blocks]
                is_overlapping = len(active_macro_shifts) > 1
                
                slot_assignments[day].append({
                    'slot_index': slot_idx,
                    'time_interval': self.time_slots[slot_idx],
                    'theory_blocks': theory_blocks,
                    'lab_slots': lab_slots,
                    'macroblock_shift_blocks': macroblock_shift_blocks,
                    'active_macro_shifts': active_macro_shifts,
                    'is_overlapping': is_overlapping
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
        Lab assignments are skipped for now as requested.
        """
        logger.info("Applying course hours constraint with macroblock structure (skipping labs)...")
        
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
                
                # Create macroblock choice variables based on teacher-macroblock compatibility
                teacher_shift = self.teacher_shift_assignments.get(teacher, 'teacher_shift1')
                
                for macro_shift in ['macro_shift1', 'macro_shift2', 'macro_shift3']:
                    # Check if teacher can access this macroblock shift
                    if self.teacher_macroblock_compatibility[teacher_shift][macro_shift]:
                        for block in self.theory_blocks[macro_shift]:
                            self.macroblock_assignments[teacher][instance_id][f'{block}_chosen'] = (
                                self.model.NewBoolVar(f'teacher_{teacher}_instance_{instance_id}_{block}_chosen'))
                
                # Determine if tutorials should be allocated:
                # If tutorial_hours > 0 OR lecture_hours == 4 (original working logic)
                should_allocate_tutorials = tutorial_hours > 0 or lecture_hours == 4
                
                # Ensure exactly one block is chosen per course instance (if it has theory hours)
                if lecture_hours > 0 or should_allocate_tutorials:
                    block_choices = []
                    teacher_shift = self.teacher_shift_assignments.get(teacher, 'teacher_shift1')
                    
                    for macro_shift in ['macro_shift1', 'macro_shift2', 'macro_shift3']:
                        # Only include blocks from accessible macroblock shifts
                        if self.teacher_macroblock_compatibility[teacher_shift][macro_shift]:
                            for block in self.theory_blocks[macro_shift]:
                                if f'{block}_chosen' in self.macroblock_assignments[teacher][instance_id]:
                                    block_choices.append(
                                        self.macroblock_assignments[teacher][instance_id][f'{block}_chosen'])
                    
                    # CRITICAL: Every course instance MUST be assigned to exactly one block
                    if block_choices:  # Only add constraint if there are valid choices
                        self.model.Add(sum(block_choices) == 1)
                    
                    # Add a high-priority constraint to ensure this instance gets scheduled
                    logger.info(f"Ensuring course instance {instance_id} (Teacher {teacher}, {lecture_hours}L+{tutorial_hours}T) gets assigned")
                
                # Link macroblock assignments to actual slot assignments (skip labs)
                self._link_macroblock_to_slots(teacher, instance, teacher_theory_assignments, None)
        
        # Apply semester and department grouping constraints
        self._apply_semester_grouping_constraints()
        
        # Apply teacher shift constraints
        self._apply_teacher_shift_constraints(teacher_theory_assignments)
        
        return True
    
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
            for macro_shift in ['macro_shift1', 'macro_shift2', 'macro_shift3']:
                for block in self.theory_blocks[macro_shift]:
                    
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
                    # but allow same course instance to use multiple slots in the same block
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
    
    def _apply_teacher_shift_constraints(self, teacher_theory_assignments):
        """Apply teacher shift constraints to ensure teachers only work in their assigned shifts."""
        logger.info("Applying teacher shift constraints...")
        
        for teacher in self.teachers:
            if teacher not in self.teacher_shift_assignments:
                continue
                
            teacher_shift = self.teacher_shift_assignments[teacher]
            allowed_time_slots = self.teacher_shifts[teacher_shift]['time_slots']
            
            # For each day and slot, check if teacher should be allowed to work
            for day_idx, day in enumerate(self.days):
                for slot_idx in range(self.num_slots):
                    current_time_slot = self.time_slots[slot_idx]
                    
                    # If this time slot is not in teacher's allowed shift, prevent assignment
                    if current_time_slot not in allowed_time_slots:
                        # Teacher cannot be assigned to any room in this slot
                        for room_id in self.classroom_ids:
                            assignment_var = teacher_theory_assignments[teacher][day_idx][slot_idx][room_id]
                            self.model.Add(assignment_var == 0)
                    else:
                        # Teacher can work in this slot, but check for overlapping shift conflicts
                        self._apply_overlapping_slot_constraints(
                            teacher, day_idx, slot_idx, teacher_shift, teacher_theory_assignments)
    
    def _apply_overlapping_slot_constraints(self, teacher, day_idx, slot_idx, teacher_shift, teacher_theory_assignments):
        """Apply constraints for overlapping slots to prevent conflicts between macroblock shifts."""
        day = self.days[day_idx]
        slot_info = self.slot_assignments[day][slot_idx]
        
        if not slot_info['is_overlapping']:
            return  # No overlap, no additional constraints needed
        
        # For overlapping slots, ensure teacher only uses blocks from accessible macroblock shifts
        accessible_blocks = []
        inaccessible_blocks = []
        
        for macro_shift in ['macro_shift1', 'macro_shift2', 'macro_shift3']:
            shift_blocks = slot_info['macroblock_shift_blocks'].get(macro_shift, [])
            if self.teacher_macroblock_compatibility[teacher_shift][macro_shift]:
                accessible_blocks.extend(shift_blocks)
            else:
                inaccessible_blocks.extend(shift_blocks)
        
        # If teacher has course assignments, ensure they only use accessible blocks
        if teacher in self.teacher_course_assignments:
            for instance in self.teacher_course_assignments[teacher]:
                instance_id = instance['id']
                
                if teacher in self.macroblock_assignments and instance_id in self.macroblock_assignments[teacher]:
                    # Prevent assignment to inaccessible macroblock shift blocks in this overlapping slot
                    for inaccessible_block in inaccessible_blocks:
                        if f'{inaccessible_block}_chosen' in self.macroblock_assignments[teacher][instance_id]:
                            inaccessible_block_var = self.macroblock_assignments[teacher][instance_id][f'{inaccessible_block}_chosen']
                            
                            # If inaccessible block is chosen, teacher cannot be in this slot
                            for room_id in self.classroom_ids:
                                room_var = teacher_theory_assignments[teacher][day_idx][slot_idx][room_id]
                                # Prevent both being true simultaneously
                                self.model.Add(inaccessible_block_var + room_var <= 1)
    
    def _link_macroblock_to_slots(self, teacher, instance, teacher_theory_assignments, teacher_lab_assignments):
        """Link macroblock assignments to actual time slot assignments. Skip lab linking."""
        instance_id = instance['id']
        lecture_hours = instance['lecture_hours']
        tutorial_hours = instance['tutorial_hours']
        practical_hours = instance['practical_hours']  # Not used for now
        
        # Determine if tutorials should be allocated
        should_allocate_tutorials = tutorial_hours > 0 or lecture_hours == 4
        
        # Get teacher's assigned shift
        teacher_shift = self.teacher_shift_assignments.get(teacher, 'teacher_shift1')
        
        # For each day and slot, link to macroblock assignments
        for day_idx, day in enumerate(self.days):
            for slot_info in self.slot_assignments[day]:
                slot_idx = slot_info['slot_index']
                theory_blocks = slot_info['theory_blocks']
                macroblock_shift_blocks = slot_info['macroblock_shift_blocks']
                is_overlapping = slot_info['is_overlapping']
                # Skip lab_slots as requested
                
                # Determine which blocks teacher can access based on compatibility
                allowed_blocks = []
                for macro_shift in ['macro_shift1', 'macro_shift2', 'macro_shift3']:
                    if self.teacher_macroblock_compatibility[teacher_shift][macro_shift]:
                        # Teacher can access this macroblock shift
                        allowed_blocks.extend(macroblock_shift_blocks.get(macro_shift, []))
                
                # Handle theory assignments
                for block in allowed_blocks:
                    if block in ['a1', 'a2', 'a3', 'b1', 'b2', 'b3', 'c1', 'c2', 'c3', 
                               'd1', 'd2', 'd3', 'e1', 'e2', 'e3', 'f1', 'f2', 'f3', 'g1', 'g2', 'g3']:
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
                    
                    elif block in ['ta1', 'ta2', 'ta3', 'tb1', 'tb2', 'tb3', 'tc1', 'tc2', 'tc3', 'td1', 'td2', 'td3'] and should_allocate_tutorials:
                        # Tutorial block - determine parent block
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
        self._enforce_exact_hours(teacher, instance, teacher_theory_assignments, None)
    
    def _enforce_exact_hours(self, teacher, instance, teacher_theory_assignments, teacher_lab_assignments):
        """Enforce exact hour requirements for each course instance. Skip lab hours."""
        instance_id = instance['id']
        lecture_hours = instance['lecture_hours']
        tutorial_hours = instance['tutorial_hours']
        practical_hours = instance['practical_hours']  # Not enforced for now
        
        # Determine if tutorials should be allocated
        should_allocate_tutorials = tutorial_hours > 0 or lecture_hours == 4
        
        # Count total lecture hours assigned
        if lecture_hours > 0:
            lecture_vars = []
            teacher_shift = self.teacher_shift_assignments.get(teacher, 'teacher_shift1')
            
            for day_idx, day in enumerate(self.days):
                for slot_info in self.slot_assignments[day]:
                    slot_idx = slot_info['slot_index']
                    macroblock_shift_blocks = slot_info['macroblock_shift_blocks']
                    
                    # Only check blocks from accessible macroblock shifts
                    accessible_blocks = []
                    for macro_shift in ['macro_shift1', 'macro_shift2', 'macro_shift3']:
                        if self.teacher_macroblock_compatibility[teacher_shift][macro_shift]:
                            accessible_blocks.extend(macroblock_shift_blocks.get(macro_shift, []))
                    
                    for block in accessible_blocks:
                        if block in ['a1', 'a2', 'a3', 'b1', 'b2', 'b3', 'c1', 'c2', 'c3', 
                                   'd1', 'd2', 'd3', 'e1', 'e2', 'e3', 'f1', 'f2', 'f3', 'g1', 'g2', 'g3']:
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
            
            # Ensure at least the required lecture hours (allow flexibility for scheduling)
            self.model.Add(sum(lecture_vars) >= lecture_hours)
            # But don't allow too many extra hours (max 1 extra)
            self.model.Add(sum(lecture_vars) <= lecture_hours + 1)
        
        # Count total tutorial hours assigned (if tutorials should be allocated)
        if should_allocate_tutorials:
            tutorial_vars = []
            # Calculate expected tutorial hours based on allocation rules
            if tutorial_hours > 0:
                # Use the actual tutorial_hours from data
                expected_tutorial_hours = tutorial_hours
            elif lecture_hours == 4:
                # Add 1 tutorial hour for 4-hour lecture courses (original logic)
                expected_tutorial_hours = 1
            else:
                # Should not reach here due to should_allocate_tutorials condition
                expected_tutorial_hours = 0
            
            teacher_shift = self.teacher_shift_assignments.get(teacher, 'teacher_shift1')
            
            for day_idx, day in enumerate(self.days):
                for slot_info in self.slot_assignments[day]:
                    slot_idx = slot_info['slot_index']
                    macroblock_shift_blocks = slot_info['macroblock_shift_blocks']
                    
                    # Only check blocks from accessible macroblock shifts
                    accessible_blocks = []
                    for macro_shift in ['macro_shift1', 'macro_shift2', 'macro_shift3']:
                        if self.teacher_macroblock_compatibility[teacher_shift][macro_shift]:
                            accessible_blocks.extend(macroblock_shift_blocks.get(macro_shift, []))
                    
                    for block in accessible_blocks:
                        if block in ['ta1', 'ta2', 'ta3', 'tb1', 'tb2', 'tb3', 'tc1', 'tc2', 'tc3', 'td1', 'td2', 'td3']:
                            # Find parent block
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
            
            if expected_tutorial_hours > 0:
                # Allow flexibility in tutorial hours (at least required, max +1 extra)
                self.model.Add(sum(tutorial_vars) >= expected_tutorial_hours)
                self.model.Add(sum(tutorial_vars) <= expected_tutorial_hours + 1)
        
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
            self.apply_room_single_assignment_constraint(teacher_theory_assignments, None)
        ]
        
        return all(constraints_applied)