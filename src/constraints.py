import logging

logger = logging.getLogger(__name__)

class TimetableConstraints:
    def __init__(self, model, teachers, days, theory_slots, lab_slots, classrooms, labs, teacher_course_assignments):
        """Initialize the timetable constraints with model and necessary data."""
        self.model = model
        self.teachers = teachers
        self.days = days
        self.theory_slots = theory_slots
        self.lab_slots = lab_slots
        self.num_days = len(days)
        self.num_theory_slots = len(theory_slots)
        self.num_lab_slots = len(lab_slots)
        self.classrooms = classrooms
        self.labs = labs
        self.teacher_course_assignments = teacher_course_assignments
        
        # Pre-compute room IDs for efficiency
        self.classroom_ids = self.classrooms['id'].tolist()
        self.lab_ids = self.labs['id'].tolist()
    
    def _get_teacher_theory_slot_vars(self, teacher, day, slot, teacher_theory_assignments):
        """Helper method to get all theory slot variables for a teacher in a specific slot."""
        return [teacher_theory_assignments[teacher][day][slot][room_id] 
                for room_id in self.classroom_ids]
    
    def _get_teacher_lab_slot_vars(self, teacher, day, slot, teacher_lab_assignments):
        """Helper method to get all lab slot variables for a teacher in a specific slot."""
        return [teacher_lab_assignments[teacher][day][slot][room_id] 
                for room_id in self.lab_ids]
    
    def _get_room_theory_slot_vars(self, room_id, day, slot, teacher_theory_assignments):
        """Helper method to get all teacher variables for a specific theory slot in a room."""
        return [teacher_theory_assignments[teacher][day][slot][room_id] 
                for teacher in self.teachers]
    
    def _get_room_lab_slot_vars(self, room_id, day, slot, teacher_lab_assignments):
        """Helper method to get all teacher variables for a specific lab slot in a room."""
        return [teacher_lab_assignments[teacher][day][slot][room_id] 
                for teacher in self.teachers]
    
    def apply_teacher_single_assignment_constraint(self, teacher_theory_assignments, teacher_lab_assignments):
        """
        Constraint 1: A teacher cannot be assigned to multiple rooms in the same time slot.
        This ensures teachers aren't double-booked.
        """
        logger.info("Applying teacher single assignment constraint...")
        
        for teacher in self.teachers:
            for d in range(self.num_days):
                # For each theory slot
                for s in range(self.num_theory_slots):
                    # Sum of all room assignments for this teacher in this theory slot must be at most 1
                    theory_vars = self._get_teacher_theory_slot_vars(teacher, d, s, teacher_theory_assignments)
                    self.model.Add(sum(theory_vars) <= 1)
                
                # For each lab slot
                for s in range(self.num_lab_slots):
                    # Sum of all room assignments for this teacher in this lab slot must be at most 1
                    lab_vars = self._get_teacher_lab_slot_vars(teacher, d, s, teacher_lab_assignments)
                    self.model.Add(sum(lab_vars) <= 1)
        
        return True
    
    def apply_no_overlapping_slots_constraint(self, teacher_theory_assignments, teacher_lab_assignments):
        """
        Constraint 2: No overlapping theory and lab slots for teachers.
        Lab slots overlap with theory slots, so teachers can't be scheduled for both.
        """
        logger.info("Applying no overlapping slots constraint...")
        
        for teacher in self.teachers:
            for d in range(self.num_days):
                for lab_slot in range(self.num_lab_slots):
                    # Each lab slot overlaps with 2 theory slots
                    first_theory_slot = lab_slot * 2
                    second_theory_slot = first_theory_slot + 1
                    
                    if first_theory_slot < self.num_theory_slots and second_theory_slot < self.num_theory_slots:
                        # Get all variables for this teacher's lab assignments in this lab slot
                        lab_vars = self._get_teacher_lab_slot_vars(teacher, d, lab_slot, teacher_lab_assignments)
                        
                        # Get all variables for this teacher's theory assignments in the overlapping theory slots
                        first_theory_vars = self._get_teacher_theory_slot_vars(teacher, d, first_theory_slot, teacher_theory_assignments)
                        second_theory_vars = self._get_teacher_theory_slot_vars(teacher, d, second_theory_slot, teacher_theory_assignments)
                        
                        # If the teacher is assigned to a lab in this lab slot, they cannot be assigned to
                        # either of the overlapping theory slots
                        for lab_var in lab_vars:
                            for theory_var in first_theory_vars + second_theory_vars:
                                self.model.AddBoolOr([lab_var.Not(), theory_var.Not()])
        
        return True
    
    def apply_intelligent_lab_capacity_constraint(self, teacher_theory_assignments, teacher_lab_assignments):
        """
        Constraint 7: Intelligent lab capacity allocation.
        For courses with >60 students:
        - 70-capacity labs: No batching needed (all students in one batch)
        - 140-capacity labs: No batching needed if students ≤ 140
        This reduces total lab slots needed compared to always using 35-capacity labs.
        """
        logger.info("Applying intelligent lab capacity constraint...")
        
        # Categorize labs by capacity
        labs_35 = self.labs[self.labs['room_max_cap'] <= 35]
        labs_70 = self.labs[(self.labs['room_max_cap'] >= 70) & (self.labs['room_max_cap'] < 140)]
        labs_140 = self.labs[self.labs['room_max_cap'] >= 140]
        
        # Create decision variables for lab capacity choice per course instance
        self.lab_capacity_choices = {}
        
        for teacher in self.teachers:
            if teacher in self.teacher_course_assignments:
                course_instances = self.teacher_course_assignments[teacher]
                
                for instance in course_instances:
                    if instance['practical_hours'] <= 0:
                        continue  # Skip courses without lab requirements
                    
                    instance_id = instance['id']
                    student_count = instance['student_count']
                    practical_hours = instance['practical_hours']
                    
                    # Only apply intelligent allocation for courses with >60 students
                    if student_count > 60:
                        key = f"{teacher}_{instance_id}"
                        self.lab_capacity_choices[key] = {}
                        
                        # Create choice variables for different lab capacities
                        if len(labs_35) > 0:
                            self.lab_capacity_choices[key]['uses_35'] = self.model.NewBoolVar(
                                f'instance_{key}_uses_35_cap_labs')
                        
                        if len(labs_70) > 0:
                            self.lab_capacity_choices[key]['uses_70'] = self.model.NewBoolVar(
                                f'instance_{key}_uses_70_cap_labs')
                        
                        if len(labs_140) > 0:
                            self.lab_capacity_choices[key]['uses_140'] = self.model.NewBoolVar(
                                f'instance_{key}_uses_140_cap_labs')
                        
                        # Exactly one capacity type must be chosen
                        choice_vars = list(self.lab_capacity_choices[key].values())
                        if len(choice_vars) > 1:
                            self.model.Add(sum(choice_vars) == 1)
                        
                        # Link lab assignments to capacity choices
                        for d in range(self.num_days):
                            for s in range(self.num_lab_slots):
                                
                                # 35-capacity lab assignments
                                if 'uses_35' in self.lab_capacity_choices[key]:
                                    lab_35_assignments = []
                                    for _, room_row in labs_35.iterrows():
                                        room_id = room_row['id']
                                        lab_35_assignments.append(teacher_lab_assignments[teacher][d][s][room_id])
                                    
                                    # If using 35-cap labs, can only assign to 35-cap labs in this slot
                                    if lab_35_assignments:
                                        uses_35 = self.lab_capacity_choices[key]['uses_35']
                                        # If not using 35-cap labs, cannot assign to any 35-cap lab
                                        for var in lab_35_assignments:
                                            self.model.Add(var == 0).OnlyEnforceIf(uses_35.Not())
                                
                                # 70-capacity lab assignments  
                                if 'uses_70' in self.lab_capacity_choices[key]:
                                    lab_70_assignments = []
                                    for _, room_row in labs_70.iterrows():
                                        room_id = room_row['id']
                                        lab_70_assignments.append(teacher_lab_assignments[teacher][d][s][room_id])
                                    
                                    if lab_70_assignments:
                                        uses_70 = self.lab_capacity_choices[key]['uses_70']
                                        for var in lab_70_assignments:
                                            self.model.Add(var == 0).OnlyEnforceIf(uses_70.Not())
                                
                                # 140-capacity lab assignments
                                if 'uses_140' in self.lab_capacity_choices[key]:
                                    lab_140_assignments = []
                                    for _, room_row in labs_140.iterrows():
                                        room_id = room_row['id']
                                        lab_140_assignments.append(teacher_lab_assignments[teacher][d][s][room_id])
                                    
                                    if lab_140_assignments:
                                        uses_140 = self.lab_capacity_choices[key]['uses_140']
                                        for var in lab_140_assignments:
                                            self.model.Add(var == 0).OnlyEnforceIf(uses_140.Not())
        
        return True
    
    def apply_course_hours_constraint(self, teacher_theory_assignments, teacher_lab_assignments):
        """
        Constraint 3: Allocate the correct number of hours for each course instance.
        Ensures that each course instance gets allocated the required lecture and practical hours.
        When a teacher has multiple instances of the same course, each instance must receive its 
        FULL allocation of hours (no sharing of hours between instances).
        """
        logger.info("Applying course hours constraint...")
        
        # Create variables to track which course instance each time slot is assigned to
        # We need these to ensure each instance gets its own allocation without sharing
        course_instance_vars = {}
        
        for teacher in self.teachers:
            if teacher in self.teacher_course_assignments:
                # Get all course instances for this teacher
                course_instances = self.teacher_course_assignments[teacher]
                
                # Skip if teacher has no courses
                if not course_instances:
                    continue
                
                # Create decision variables for each course instance and time slot combination
                course_instance_vars[teacher] = {}
                
                # Theory slots assignment variables
                for d in range(self.num_days):
                    for s in range(self.num_theory_slots):
                        slot_key = (d, s, 'theory')
                        course_instance_vars[teacher][slot_key] = {}
                        for instance in course_instances:
                            instance_id = instance['id']
                            if instance['lecture_hours'] > 0:  # Only create vars for courses with theory hours
                                course_instance_vars[teacher][slot_key][instance_id] = self.model.NewBoolVar(
                                    f'teacher_{teacher}_day_{d}_theory_{s}_instance_{instance_id}')
                
                # Lab slots assignment variables
                for d in range(self.num_days):
                    for s in range(self.num_lab_slots):
                        slot_key = (d, s, 'lab')
                        course_instance_vars[teacher][slot_key] = {}
                        for instance in course_instances:
                            instance_id = instance['id']
                            if instance['practical_hours'] > 0:  # Only create vars for courses with lab hours
                                course_instance_vars[teacher][slot_key][instance_id] = self.model.NewBoolVar(
                                    f'teacher_{teacher}_day_{d}_lab_{s}_instance_{instance_id}')
                
                # Link course instance vars to teacher assignment vars for theory slots
                for d in range(self.num_days):
                    for s in range(self.num_theory_slots):
                        slot_key = (d, s, 'theory')
                        
                        # Sum of all room assignments for this teacher in this theory slot
                        theory_slot_vars = self._get_teacher_theory_slot_vars(teacher, d, s, teacher_theory_assignments)
                        
                        # If any room is assigned to this teacher for this slot, exactly one course instance must be assigned
                        is_slot_assigned = self.model.NewBoolVar(f'teacher_{teacher}_assigned_theory_{d}_{s}')
                        self.model.Add(sum(theory_slot_vars) > 0).OnlyEnforceIf(is_slot_assigned)
                        self.model.Add(sum(theory_slot_vars) == 0).OnlyEnforceIf(is_slot_assigned.Not())
                        
                        # Sum of all course instance assignments for this slot
                        instance_vars = list(course_instance_vars[teacher][slot_key].values())
                        
                        # If slot is assigned, exactly one course instance must be assigned
                        if instance_vars:
                            self.model.Add(sum(instance_vars) == 1).OnlyEnforceIf(is_slot_assigned)
                            self.model.Add(sum(instance_vars) == 0).OnlyEnforceIf(is_slot_assigned.Not())
                
                # Link course instance vars to teacher assignment vars for lab slots
                for d in range(self.num_days):
                    for s in range(self.num_lab_slots):
                        slot_key = (d, s, 'lab')
                        
                        # Sum of all room assignments for this teacher in this lab slot
                        lab_slot_vars = self._get_teacher_lab_slot_vars(teacher, d, s, teacher_lab_assignments)
                        
                        # If any room is assigned to this teacher for this slot, exactly one course instance must be assigned
                        is_slot_assigned = self.model.NewBoolVar(f'teacher_{teacher}_assigned_lab_{d}_{s}')
                        self.model.Add(sum(lab_slot_vars) > 0).OnlyEnforceIf(is_slot_assigned)
                        self.model.Add(sum(lab_slot_vars) == 0).OnlyEnforceIf(is_slot_assigned.Not())
                        
                        # Sum of all course instance assignments for this slot
                        instance_vars = list(course_instance_vars[teacher][slot_key].values())
                        
                        # If slot is assigned, exactly one course instance must be assigned
                        if instance_vars:
                            self.model.Add(sum(instance_vars) == 1).OnlyEnforceIf(is_slot_assigned)
                            self.model.Add(sum(instance_vars) == 0).OnlyEnforceIf(is_slot_assigned.Not())
                
                # Ensure each course instance gets its required number of hours
                for instance in course_instances:
                    instance_id = instance['id']
                    lecture_hours = instance['lecture_hours']
                    practical_hours = instance['practical_hours']
                    
                    # Get all theory slot assignments for this instance
                    theory_instance_vars = []
                    for d in range(self.num_days):
                        for s in range(self.num_theory_slots):
                            slot_key = (d, s, 'theory')
                            if instance_id in course_instance_vars[teacher][slot_key]:
                                theory_instance_vars.append(course_instance_vars[teacher][slot_key][instance_id])
                    
                    # Ensure the required number of theory slots
                    if lecture_hours > 0:
                        self.model.Add(sum(theory_instance_vars) == lecture_hours)
                    
                    # Get all lab slot assignments for this instance
                    lab_instance_vars = []
                    for d in range(self.num_days):
                        for s in range(self.num_lab_slots):
                            slot_key = (d, s, 'lab')
                            if instance_id in course_instance_vars[teacher][slot_key]:
                                lab_instance_vars.append(course_instance_vars[teacher][slot_key][instance_id])
                    
                    # Calculate required lab slots based on practical hours and lab capacity choice
                    if practical_hours > 0:
                        base_lab_slots = (practical_hours + 1) // 2  # Ceiling division
                        
                        # Check if this instance uses intelligent lab capacity allocation
                        key = f"{teacher}_{instance_id}"
                        
                        if (instance['student_count'] > 60 and 
                            hasattr(self, 'lab_capacity_choices') and 
                            key in self.lab_capacity_choices):
                            
                            # For courses >60 students with intelligent allocation
                            choices = self.lab_capacity_choices[key]
                            
                            if 'uses_35' in choices:
                                # Using 35-capacity labs: need batching (2 batches for 70 students)
                                num_batches_35 = (instance['student_count'] + 34) // 35
                                required_slots_35 = base_lab_slots * num_batches_35
                                self.model.Add(sum(lab_instance_vars) == required_slots_35).OnlyEnforceIf(choices['uses_35'])
                            
                            if 'uses_70' in choices:
                                # Using 70-capacity labs: no batching needed (1 batch)
                                # But still need enough slots to cover all practical hours
                                required_slots_70 = base_lab_slots  # Respect practical hours!
                                self.model.Add(sum(lab_instance_vars) == required_slots_70).OnlyEnforceIf(choices['uses_70'])
                            
                            if 'uses_140' in choices:
                                # Using 140-capacity labs: no batching needed if ≤140 students
                                # But still need enough slots to cover all practical hours
                                if instance['student_count'] <= 140:
                                    required_slots_140 = base_lab_slots  # Respect practical hours!
                                else:
                                    num_batches_140 = (instance['student_count'] + 139) // 140
                                    required_slots_140 = base_lab_slots * num_batches_140
                                self.model.Add(sum(lab_instance_vars) == required_slots_140).OnlyEnforceIf(choices['uses_140'])
                        
                        else:
                            # Standard allocation for courses ≤60 students or without intelligent allocation
                            required_lab_slots = base_lab_slots
                            
                            # For large classes (>35 students), use standard batching
                            if instance['student_count'] > 35:
                                num_batches = (instance['student_count'] + 34) // 35
                                required_lab_slots *= num_batches
                            
                            self.model.Add(sum(lab_instance_vars) == required_lab_slots)
        
        return True
    
    def apply_room_single_assignment_constraint(self, teacher_theory_assignments, teacher_lab_assignments):
        """
        Constraint 4: A room cannot be assigned to multiple teachers in the same time slot.
        Ensures rooms aren't double-booked.
        """
        logger.info("Applying room single assignment constraint...")
        
        # For classrooms
        for _, room_row in self.classrooms.iterrows():
            room_id = room_row['id']
            for d in range(self.num_days):
                for s in range(self.num_theory_slots):
                    room_vars = self._get_room_theory_slot_vars(room_id, d, s, teacher_theory_assignments)
                    self.model.Add(sum(room_vars) <= 1)
        
        # For labs
        for _, room_row in self.labs.iterrows():
            room_id = room_row['id']
            for d in range(self.num_days):
                for s in range(self.num_lab_slots):
                    room_vars = self._get_room_lab_slot_vars(room_id, d, s, teacher_lab_assignments)
                    self.model.Add(sum(room_vars) <= 1)
        
        return True
    
    def apply_weekly_working_hour_constraint(self, teacher_theory_assignments, teacher_lab_assignments):
        """
        Constraint 5: Weekly working hour limit (21 hours per teacher).
        Ensures no teacher exceeds 21 hours of teaching per week.
        Theory slots count as 1 hour each, lab slots count as 2 hours each.
        """
        logger.info("Applying weekly working hour constraint...")
        
        for teacher in self.teachers:
            # Collect all theory slot assignments for this teacher (1 hour each)
            theory_vars = []
            for d in range(self.num_days):
                for s in range(self.num_theory_slots):
                    theory_vars.extend(self._get_teacher_theory_slot_vars(teacher, d, s, teacher_theory_assignments))
            
            # Collect all lab slot assignments for this teacher (2 hours each)
            lab_vars = []
            for d in range(self.num_days):
                for s in range(self.num_lab_slots):
                    lab_vars.extend(self._get_teacher_lab_slot_vars(teacher, d, s, teacher_lab_assignments))
            
            # Weekly working hour constraint: theory_hours + 2*lab_hours <= 21
            # Theory slots are 50 minutes (~1 hour), lab slots are 100 minutes (~2 hours)
            total_weekly_hours = sum(theory_vars) + 2 * sum(lab_vars)
            self.model.Add(total_weekly_hours <= 21)
        
        return True
    
    def apply_no_continuous_lab_slots_constraint(self, teacher_theory_assignments, teacher_lab_assignments):
        """
        Constraint 8: Teachers should not be assigned to continuous lab slots unless there's sufficient break.
        Lab slots timing:
        - L1: 8:00-9:40
        - L2: 10:00-11:40 (20 min break from L1) - ALLOWED consecutive assignment
        - L3: 11:40-1:20 (0 min break from L2) - FORBIDDEN consecutive assignment
        - L4: 1:20-3:00 (0 min break from L3) - FORBIDDEN consecutive assignment
        - L5: 3:00-4:40 (0 min break from L4) - FORBIDDEN consecutive assignment
        - L6: 5:10-6:50 (30 min break from L5) - ALLOWED consecutive assignment
        
        Only consecutive lab slot pairs with 20+ minute breaks are allowed:
        - L1-L2 (20 min break) and L5-L6 (30 min break) are ALLOWED
        - L2-L3, L3-L4, L4-L5 are FORBIDDEN (continuous)
        """
        logger.info("Applying no continuous lab slots constraint...")
        
        # Define which consecutive lab slot pairs are forbidden (0 break time)
        # Lab slots: L1(0), L2(1), L3(2), L4(3), L5(4), L6(5)
        forbidden_consecutive_pairs = [
            (1, 2),  # L2-L3: 11:40 to 11:40 (continuous - 0 min break)
            (2, 3),  # L3-L4: 1:20 to 1:20 (continuous - 0 min break)  
            (3, 4),  # L4-L5: 3:00 to 3:00 (continuous - 0 min break)
        ]
        
        for teacher in self.teachers:
            for d in range(self.num_days):
                for first_slot, second_slot in forbidden_consecutive_pairs:
                    # Get all lab assignments for the teacher in the first slot
                    first_slot_vars = self._get_teacher_lab_slot_vars(teacher, d, first_slot, teacher_lab_assignments)
                    
                    # Get all lab assignments for the teacher in the second slot
                    second_slot_vars = self._get_teacher_lab_slot_vars(teacher, d, second_slot, teacher_lab_assignments)
                    
                    # Add constraint: teacher cannot be assigned to both consecutive slots
                    # For each pair of assignments (one in first slot, one in second slot),
                    # at least one must be false (using Boolean OR with negation)
                    for first_var in first_slot_vars:
                        for second_var in second_slot_vars:
                            # If teacher is assigned to first slot, they cannot be assigned to second slot
                            self.model.AddBoolOr([first_var.Not(), second_var.Not()])
        
        return True
    
    def apply_monday_or_saturday_constraint(self, teacher_theory_assignments, teacher_lab_assignments):
        """
        Constraint 9: Teachers should work either on Monday OR Saturday, but not both days.
        This ensures better work-life balance by preventing teachers from working both 
        the beginning and end of the week.
        
        Implementation:
        - Monday is day 0, Saturday is day 5 in the days array
        - For each teacher, create boolean variables indicating if they work on each day
        - Add constraint: if teacher works Monday, they cannot work Saturday (and vice versa)
        """
        logger.info("Applying Monday or Saturday constraint...")
        
        # Days array: ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
        monday_index = 0      # Monday is day 0
        saturday_index = 5    # Saturday is day 5
        
        for teacher in self.teachers:
            # Create boolean variables to track if teacher works on Monday or Saturday
            works_monday = self.model.NewBoolVar(f'teacher_{teacher}_works_monday')
            works_saturday = self.model.NewBoolVar(f'teacher_{teacher}_works_saturday')
            
            # Collect all Monday assignments (theory and lab)
            monday_theory_vars = []
            for s in range(self.num_theory_slots):
                monday_theory_vars.extend(self._get_teacher_theory_slot_vars(teacher, monday_index, s, teacher_theory_assignments))
            
            monday_lab_vars = []
            for s in range(self.num_lab_slots):
                monday_lab_vars.extend(self._get_teacher_lab_slot_vars(teacher, monday_index, s, teacher_lab_assignments))
            
            monday_all_vars = monday_theory_vars + monday_lab_vars
            
            # Collect all Saturday assignments (theory and lab)
            saturday_theory_vars = []
            for s in range(self.num_theory_slots):
                saturday_theory_vars.extend(self._get_teacher_theory_slot_vars(teacher, saturday_index, s, teacher_theory_assignments))
            
            saturday_lab_vars = []
            for s in range(self.num_lab_slots):
                saturday_lab_vars.extend(self._get_teacher_lab_slot_vars(teacher, saturday_index, s, teacher_lab_assignments))
            
            saturday_all_vars = saturday_theory_vars + saturday_lab_vars
            
            # Link boolean variables to actual assignments
            # If any Monday slot is assigned, works_monday must be true
            if monday_all_vars:
                for var in monday_all_vars:
                    self.model.Add(works_monday >= var)
                # If works_monday is true, at least one Monday assignment must exist
                self.model.Add(sum(monday_all_vars) >= works_monday)
            
            # If any Saturday slot is assigned, works_saturday must be true
            if saturday_all_vars:
                for var in saturday_all_vars:
                    self.model.Add(works_saturday >= var)
                # If works_saturday is true, at least one Saturday assignment must exist
                self.model.Add(sum(saturday_all_vars) >= works_saturday)
            
            # Main constraint: teacher cannot work both Monday and Saturday
            # Either works_monday OR works_saturday, but not both
            self.model.Add(works_monday + works_saturday <= 1)
        
        return True
    
    def apply_shift_based_constraint(self, teacher_theory_assignments, teacher_lab_assignments):
        """
        Constraint 10: Shift-based system with 3 shifts and balanced distribution.
        
        Shift Definitions:
        - Shift 1: 8:00-15:00 (covers theory slots 0-6, lab slots L1-L3)
        - Shift 2: 10:00-17:00 (covers theory slots 2-8, lab slots L2-L5) 
        - Shift 3: 12:00-19:00 (covers theory slots 4-10, lab slots L3-L6)
        
        Requirements:
        1. Each teacher is assigned to exactly one shift per working day
        2. Teachers can only teach during slots within their assigned shift
        3. Each teacher follows one of three weekly patterns: (1-2-2), (2-2-1), (2-1-2)
           representing days spent in (shift1-shift2-shift3)
        4. Department-level distribution: 33%-33%-33% across shifts
        5. Teachers are randomly distributed across the three patterns
        """
        logger.info("Applying shift-based constraint...")
        
        # Define shift coverage for theory slots (0-indexed)
        shift1_theory_slots = list(range(0, 7))   # 8:00-14:50 (slots 0-6)
        shift2_theory_slots = list(range(2, 9))   # 10:00-16:50 (slots 2-8)  
        shift3_theory_slots = list(range(4, 11))  # 12:00-18:50 (slots 4-10)
        
        # Define shift coverage for lab slots (0-indexed)
        shift1_lab_slots = [0, 1, 2]  # L1, L2, L3 (8:00-13:20)
        shift2_lab_slots = [1, 2, 3, 4]  # L2, L3, L4, L5 (10:00-16:40)
        shift3_lab_slots = [2, 3, 4, 5]  # L3, L4, L5, L6 (11:40-18:50)
        
        # Create shift assignment variables for each teacher and day
        teacher_shift_assignments = {}
        for teacher in self.teachers:
            teacher_shift_assignments[teacher] = {}
            for d in range(self.num_days):
                teacher_shift_assignments[teacher][d] = {
                    'shift1': self.model.NewBoolVar(f'teacher_{teacher}_day_{d}_shift1'),
                    'shift2': self.model.NewBoolVar(f'teacher_{teacher}_day_{d}_shift2'),
                    'shift3': self.model.NewBoolVar(f'teacher_{teacher}_day_{d}_shift3'),
                    'no_shift': self.model.NewBoolVar(f'teacher_{teacher}_day_{d}_no_shift')
                }
                
                # Exactly one shift assignment per day (including no shift for non-working days)
                shift_vars = [
                    teacher_shift_assignments[teacher][d]['shift1'],
                    teacher_shift_assignments[teacher][d]['shift2'], 
                    teacher_shift_assignments[teacher][d]['shift3'],
                    teacher_shift_assignments[teacher][d]['no_shift']
                ]
                self.model.Add(sum(shift_vars) == 1)
        
        # Store shift assignments for later access
        self.teacher_shift_assignments = teacher_shift_assignments
        
        # Link shift assignments to actual teaching assignments
        for teacher in self.teachers:
            for d in range(self.num_days):
                # Collect all teaching assignments for this teacher on this day
                day_theory_vars = []
                day_lab_vars = []
                
                for s in range(self.num_theory_slots):
                    day_theory_vars.extend(self._get_teacher_theory_slot_vars(teacher, d, s, teacher_theory_assignments))
                
                for s in range(self.num_lab_slots):
                    day_lab_vars.extend(self._get_teacher_lab_slot_vars(teacher, d, s, teacher_lab_assignments))
                
                all_day_vars = day_theory_vars + day_lab_vars
                
                # If teacher has any assignments on this day, they must be assigned to a shift
                has_assignments = self.model.NewBoolVar(f'teacher_{teacher}_day_{d}_has_assignments')
                if all_day_vars:
                    self.model.Add(sum(all_day_vars) > 0).OnlyEnforceIf(has_assignments)
                    self.model.Add(sum(all_day_vars) == 0).OnlyEnforceIf(has_assignments.Not())
                    
                    # If has assignments, cannot be in no_shift
                    self.model.Add(teacher_shift_assignments[teacher][d]['no_shift'] == 0).OnlyEnforceIf(has_assignments)
                    
                    # If no assignments, must be in no_shift
                    shift_working_vars = [
                        teacher_shift_assignments[teacher][d]['shift1'],
                        teacher_shift_assignments[teacher][d]['shift2'],
                        teacher_shift_assignments[teacher][d]['shift3']
                    ]
                    self.model.Add(sum(shift_working_vars) == 0).OnlyEnforceIf(has_assignments.Not())
                
                # Constraint: can only teach in slots covered by assigned shift
                # Shift 1 constraints
                shift1_var = teacher_shift_assignments[teacher][d]['shift1']
                
                # Theory slots outside shift1 cannot be used if assigned to shift1
                for s in range(self.num_theory_slots):
                    if s not in shift1_theory_slots:
                        theory_vars_outside_shift1 = self._get_teacher_theory_slot_vars(teacher, d, s, teacher_theory_assignments)
                        for var in theory_vars_outside_shift1:
                            self.model.Add(var == 0).OnlyEnforceIf(shift1_var)
                
                # Lab slots outside shift1 cannot be used if assigned to shift1
                for s in range(self.num_lab_slots):
                    if s not in shift1_lab_slots:
                        lab_vars_outside_shift1 = self._get_teacher_lab_slot_vars(teacher, d, s, teacher_lab_assignments)
                        for var in lab_vars_outside_shift1:
                            self.model.Add(var == 0).OnlyEnforceIf(shift1_var)
                
                # Shift 2 constraints  
                shift2_var = teacher_shift_assignments[teacher][d]['shift2']
                
                for s in range(self.num_theory_slots):
                    if s not in shift2_theory_slots:
                        theory_vars_outside_shift2 = self._get_teacher_theory_slot_vars(teacher, d, s, teacher_theory_assignments)
                        for var in theory_vars_outside_shift2:
                            self.model.Add(var == 0).OnlyEnforceIf(shift2_var)
                
                for s in range(self.num_lab_slots):
                    if s not in shift2_lab_slots:
                        lab_vars_outside_shift2 = self._get_teacher_lab_slot_vars(teacher, d, s, teacher_lab_assignments)
                        for var in lab_vars_outside_shift2:
                            self.model.Add(var == 0).OnlyEnforceIf(shift2_var)
                
                # Shift 3 constraints
                shift3_var = teacher_shift_assignments[teacher][d]['shift3']
                
                for s in range(self.num_theory_slots):
                    if s not in shift3_theory_slots:
                        theory_vars_outside_shift3 = self._get_teacher_theory_slot_vars(teacher, d, s, teacher_theory_assignments)
                        for var in theory_vars_outside_shift3:
                            self.model.Add(var == 0).OnlyEnforceIf(shift3_var)
                
                for s in range(self.num_lab_slots):
                    if s not in shift3_lab_slots:
                        lab_vars_outside_shift3 = self._get_teacher_lab_slot_vars(teacher, d, s, teacher_lab_assignments)
                        for var in lab_vars_outside_shift3:
                            self.model.Add(var == 0).OnlyEnforceIf(shift3_var)
        
        # Apply weekly shift patterns for each teacher
        self._apply_weekly_shift_patterns(teacher_shift_assignments)
        
        # Apply department-level shift distribution (33%-33%-33%)
        self._apply_department_shift_distribution(teacher_shift_assignments)
        
        return True
    
    def _apply_weekly_shift_patterns(self, teacher_shift_assignments):
        """Apply weekly shift patterns: each teacher follows one of (1-2-2), (2-2-1), (2-1-2)."""
        
        for teacher in self.teachers:
            # Create pattern selection variables
            pattern_122 = self.model.NewBoolVar(f'teacher_{teacher}_pattern_122')  # 1 shift1, 2 shift2, 2 shift3
            pattern_221 = self.model.NewBoolVar(f'teacher_{teacher}_pattern_221')  # 2 shift1, 2 shift2, 1 shift3
            pattern_212 = self.model.NewBoolVar(f'teacher_{teacher}_pattern_212')  # 2 shift1, 1 shift2, 2 shift3
            
            # Each teacher must follow exactly one pattern
            self.model.Add(pattern_122 + pattern_221 + pattern_212 == 1)
            
            # Count shift days for each teacher across the week
            shift1_days = []
            shift2_days = []
            shift3_days = []
            
            for d in range(self.num_days):
                shift1_days.append(teacher_shift_assignments[teacher][d]['shift1'])
                shift2_days.append(teacher_shift_assignments[teacher][d]['shift2'])
                shift3_days.append(teacher_shift_assignments[teacher][d]['shift3'])
            
            # Pattern 1-2-2: 1 day shift1, 2 days shift2, 2 days shift3
            self.model.Add(sum(shift1_days) == 1).OnlyEnforceIf(pattern_122)
            self.model.Add(sum(shift2_days) == 2).OnlyEnforceIf(pattern_122)
            self.model.Add(sum(shift3_days) == 2).OnlyEnforceIf(pattern_122)
            
            # Pattern 2-2-1: 2 days shift1, 2 days shift2, 1 day shift3
            self.model.Add(sum(shift1_days) == 2).OnlyEnforceIf(pattern_221)
            self.model.Add(sum(shift2_days) == 2).OnlyEnforceIf(pattern_221)
            self.model.Add(sum(shift3_days) == 1).OnlyEnforceIf(pattern_221)
            
            # Pattern 2-1-2: 2 days shift1, 1 day shift2, 2 days shift3
            self.model.Add(sum(shift1_days) == 2).OnlyEnforceIf(pattern_212)
            self.model.Add(sum(shift2_days) == 1).OnlyEnforceIf(pattern_212)
            self.model.Add(sum(shift3_days) == 2).OnlyEnforceIf(pattern_212)
    
    def _apply_department_shift_distribution(self, teacher_shift_assignments):
        """Apply department-level shift distribution (33%-33%-33%)."""
        
        # For simplicity, assume all teachers are in the same department
        # In a real implementation, you would group by department
        num_teachers = len(self.teachers)
        target_per_shift = num_teachers // 3
        
        # Count teachers primarily assigned to each shift (based on their weekly pattern)
        shift1_primary_teachers = []
        shift2_primary_teachers = []
        shift3_primary_teachers = []
        
        for teacher in self.teachers:
            # A teacher is "primarily" assigned to the shift they work most days
            shift1_total = self.model.NewIntVar(0, self.num_days, f'teacher_{teacher}_shift1_total')
            shift2_total = self.model.NewIntVar(0, self.num_days, f'teacher_{teacher}_shift2_total')
            shift3_total = self.model.NewIntVar(0, self.num_days, f'teacher_{teacher}_shift3_total')
            
            shift1_days = [teacher_shift_assignments[teacher][d]['shift1'] for d in range(self.num_days)]
            shift2_days = [teacher_shift_assignments[teacher][d]['shift2'] for d in range(self.num_days)]
            shift3_days = [teacher_shift_assignments[teacher][d]['shift3'] for d in range(self.num_days)]
            
            self.model.Add(shift1_total == sum(shift1_days))
            self.model.Add(shift2_total == sum(shift2_days))
            self.model.Add(shift3_total == sum(shift3_days))
            
            # Determine primary shift assignment
            primary_shift1 = self.model.NewBoolVar(f'teacher_{teacher}_primary_shift1')
            primary_shift2 = self.model.NewBoolVar(f'teacher_{teacher}_primary_shift2')
            primary_shift3 = self.model.NewBoolVar(f'teacher_{teacher}_primary_shift3')
            
            # Each teacher has exactly one primary shift
            self.model.Add(primary_shift1 + primary_shift2 + primary_shift3 == 1)
            
            # Link primary shift to actual shift counts (simplified logic)
            # This could be made more sophisticated with additional constraints
            shift1_primary_teachers.append(primary_shift1)
            shift2_primary_teachers.append(primary_shift2)
            shift3_primary_teachers.append(primary_shift3)
        
        # Balance distribution across shifts (allow some flexibility)
        tolerance = max(1, num_teachers // 10)  # 10% tolerance
        
        self.model.Add(sum(shift1_primary_teachers) >= target_per_shift - tolerance)
        self.model.Add(sum(shift1_primary_teachers) <= target_per_shift + tolerance)
        self.model.Add(sum(shift2_primary_teachers) >= target_per_shift - tolerance)
        self.model.Add(sum(shift2_primary_teachers) <= target_per_shift + tolerance)
        self.model.Add(sum(shift3_primary_teachers) >= target_per_shift - tolerance)
        self.model.Add(sum(shift3_primary_teachers) <= target_per_shift + tolerance)
    
    def apply_all_constraints(self, teacher_theory_assignments, teacher_lab_assignments):
        """Apply all timetable constraints."""
        logger.info("Applying all timetable constraints...")
        
        constraints_applied = [
            self.apply_teacher_single_assignment_constraint(teacher_theory_assignments, teacher_lab_assignments),
            self.apply_no_overlapping_slots_constraint(teacher_theory_assignments, teacher_lab_assignments),
            self.apply_intelligent_lab_capacity_constraint(teacher_theory_assignments, teacher_lab_assignments),
            self.apply_course_hours_constraint(teacher_theory_assignments, teacher_lab_assignments),
            self.apply_room_single_assignment_constraint(teacher_theory_assignments, teacher_lab_assignments),
            self.apply_weekly_working_hour_constraint(teacher_theory_assignments, teacher_lab_assignments),
            self.apply_no_continuous_lab_slots_constraint(teacher_theory_assignments, teacher_lab_assignments),
            self.apply_monday_or_saturday_constraint(teacher_theory_assignments, teacher_lab_assignments),
            self.apply_shift_based_constraint(teacher_theory_assignments, teacher_lab_assignments)
        ]
        
        return all(constraints_applied)
    
    def generate_constraint_summary(self):
        """Generate a summary of the impact of each constraint."""
        summary = {
            "teacher_single_assignment": {
                "name": "Teacher Single Assignment Constraint",
                "description": "Prevents teachers from being assigned to multiple rooms in the same time slot",
                "impact": "Ensures teachers aren't double-booked, which is critical for a valid timetable",
                "complexity": {
                    "formula": "O(T × D × (S_theory × R_classroom + S_lab × R_lab))",
                    "explanation": "T = teachers, D = days, S = slots, R = rooms",
                    "level": "High",
                    "notes": "Scales linearly with number of teachers, days, slots, and rooms"
                }
            },
            "no_overlapping_slots": {
                "name": "No Overlapping Slots Constraint",
                "description": "Prevents teachers from being assigned to lab and theory slots that overlap in time",
                "impact": "Ensures teachers can't physically be in two places at once when lab slots overlap with theory slots",
                "complexity": {
                    "formula": "O(T × D × S_lab × (R_lab × R_classroom))",
                    "explanation": "Each lab slot overlaps with two theory slots",
                    "level": "High",
                    "notes": "Complex constraint as it must check all possible combinations of lab and theory slots"
                }
            },
            "course_hours": {
                "name": "Course Hours Constraint",
                "description": "Ensures each course gets allocated the required lecture and practical hours",
                "impact": "Critical for educational outcomes - ensures students receive the proper instructional time",
                "complexity": {
                    "formula": "O(T × C × (D × S_theory × R_classroom + D × S_lab × R_lab))",
                    "explanation": "C = courses per teacher",
                    "level": "Very High",
                    "notes": "Most complex constraint as it requires tracking hours across all possible assignments"
                }
            },
            "room_single_assignment": {
                "name": "Room Single Assignment Constraint",
                "description": "Prevents rooms from being assigned to multiple teachers in the same time slot",
                "impact": "Ensures rooms aren't double-booked, preventing scheduling conflicts",
                "complexity": {
                    "formula": "O((R_classroom × D × S_theory + R_lab × D × S_lab) × T)",
                    "explanation": "Physical constraint - a room can only host one class at a time",
                    "level": "Medium",
                    "notes": "Must be checked for every room, time slot, and teacher combination"
                }
            },
            "lab_batch": {
                "name": "Lab Batch Constraint",
                "description": "Handles lab capacity limitations by creating multiple batches for large classes",
                "impact": "Ensures all students get proper lab time despite lab capacity limits (35 students per lab)",
                "complexity": {
                    "formula": "O(T × C × D × S_lab × R_lab)",
                    "explanation": "Requires calculating batches based on student count and scheduling accordingly",
                    "level": "High",
                    "notes": "Classes with 70 students require two separate lab batches, doubling the needed lab slots"
                },
                "example": "For a course with 2 practical hours and 70 students:\n- Batch 1 (35 students): 2hrs = 1 lab slot\n- Batch 2 (35 students): 2hrs = 1 lab slot\n- Total: 4hrs = 2 lab slots needed"
            },
            "weekly_working_hour": {
                "name": "Weekly Working Hour Constraint",
                "description": "Ensures no teacher exceeds 21 hours of teaching per week",
                "impact": "Critical for teacher well-being and teaching quality",
                "complexity": {
                    "formula": "O(T × D × (S_theory + 2 × S_lab))",
                    "explanation": "T = teachers, D = days, S = slots",
                    "level": "Medium",
                    "notes": "Ensures teachers don't work excessive hours"
                }
            },
            "intelligent_lab_capacity": {
                "name": "Intelligent Lab Capacity Constraint",
                "description": "Handles different lab capacities (35, 70, 140) to optimize lab usage",
                "impact": "Ensures proper lab time allocation based on student count and lab capacity",
                "complexity": {
                    "formula": "O(T × C × D × S_lab × R_lab)",
                    "explanation": "T = teachers, C = courses per teacher, D = days, S = slots, R = rooms",
                    "level": "High",
                    "notes": "Complex constraint as it requires handling multiple lab capacity scenarios"
                }
            },
            "no_continuous_lab_slots": {
                "name": "No Continuous Lab Slots Constraint", 
                "description": "Prevents teachers from being assigned to continuous lab slots unless there's sufficient break time (20+ minutes)",
                "impact": "Ensures teacher well-being by preventing back-to-back lab sessions without adequate break, while allowing consecutive assignments when sufficient break time exists",
                "complexity": {
                    "formula": "O(T × D × 3 × R_lab²)",
                    "explanation": "T = teachers, D = days, 3 = forbidden consecutive pairs, R_lab = lab rooms",
                    "level": "Medium",
                    "notes": "Checks 3 specific consecutive lab slot pairs (L2-L3, L3-L4, L4-L5) for each teacher and day"
                },
                "example": "Lab slot timings:\n- L1-L2: 20 min break (ALLOWED)\n- L2-L3: 0 min break (FORBIDDEN)\n- L3-L4: 0 min break (FORBIDDEN)\n- L4-L5: 0 min break (FORBIDDEN)\n- L5-L6: 30 min break (ALLOWED)"
            },
            "monday_or_saturday": {
                "name": "Monday or Saturday Constraint",
                "description": "Ensures teachers work either on Monday OR Saturday, but not both days",
                "impact": "Promotes better work-life balance by preventing teachers from working both the beginning and end of the week, while ensuring weekend and week-start coverage",
                "complexity": {
                    "formula": "O(T × (S_theory + S_lab) × 2)",
                    "explanation": "T = teachers, S = slots per day, 2 = Monday and Saturday",
                    "level": "Medium",
                    "notes": "Creates boolean variables to track Monday/Saturday work and enforces mutual exclusion"
                },
                "example": "Teacher scheduling scenarios:\n- Teacher A: Works Monday (theory + lab) -> Cannot work Saturday\n- Teacher B: Works Saturday (theory + lab) -> Cannot work Monday\n- Teacher C: Works Tuesday-Friday -> Can work either Monday OR Saturday\n- Teacher D: No Monday/Saturday assignments -> Constraint satisfied"
            },
            "shift_based": {
                "name": "Shift-Based System Constraint",
                "description": "Implements a 3-shift system with balanced teacher distribution and weekly patterns",
                "impact": "Ensures organized shift coverage, balanced teacher workload across time periods, and departmental equity in shift distribution",
                "complexity": {
                    "formula": "O(T × D × (S_theory + S_lab) × 3)",
                    "explanation": "T = teachers, D = days, S = slots per type, 3 = number of shifts",
                    "level": "Very High",
                    "notes": "Most complex constraint involving shift assignments, pattern matching, and distribution balancing"
                },
                "example": "Shift System:\n- Shift 1 (8:00-15:00): Early shift covering morning slots\n- Shift 2 (10:00-17:00): Day shift with overlap coverage\n- Shift 3 (12:00-19:00): Late shift covering afternoon/evening\n\nWeekly Patterns:\n- Pattern A (1-2-2): 1 day shift1, 2 days shift2, 2 days shift3\n- Pattern B (2-2-1): 2 days shift1, 2 days shift2, 1 day shift3\n- Pattern C (2-1-2): 2 days shift1, 1 day shift2, 2 days shift3\n\nDepartment Distribution: 33%-33%-33% across all shifts"
            }
        }
        
        return summary 