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
                    theory_vars = []
                    for _, room_row in self.classrooms.iterrows():
                        room_id = room_row['id']
                        theory_vars.append(teacher_theory_assignments[teacher][d][s][room_id])
                    self.model.Add(sum(theory_vars) <= 1)
                
                # For each lab slot
                for s in range(self.num_lab_slots):
                    # Sum of all room assignments for this teacher in this lab slot must be at most 1
                    lab_vars = []
                    for _, room_row in self.labs.iterrows():
                        room_id = room_row['id']
                        lab_vars.append(teacher_lab_assignments[teacher][d][s][room_id])
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
                        lab_vars = []
                        for _, lab_row in self.labs.iterrows():
                            lab_id = lab_row['id']
                            lab_vars.append(teacher_lab_assignments[teacher][d][lab_slot][lab_id])
                        
                        # Get all variables for this teacher's theory assignments in the overlapping theory slots
                        first_theory_vars = []
                        second_theory_vars = []
                        for _, room_row in self.classrooms.iterrows():
                            room_id = room_row['id']
                            first_theory_vars.append(teacher_theory_assignments[teacher][d][first_theory_slot][room_id])
                            second_theory_vars.append(teacher_theory_assignments[teacher][d][second_theory_slot][room_id])
                        
                        # If the teacher is assigned to a lab in this lab slot, they cannot be assigned to
                        # either of the overlapping theory slots
                        for lab_var in lab_vars:
                            for theory_var in first_theory_vars + second_theory_vars:
                                self.model.AddBoolOr([lab_var.Not(), theory_var.Not()])
        
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
                        theory_slot_vars = []
                        for _, room_row in self.classrooms.iterrows():
                            room_id = room_row['id']
                            theory_slot_vars.append(teacher_theory_assignments[teacher][d][s][room_id])
                        
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
                        lab_slot_vars = []
                        for _, room_row in self.labs.iterrows():
                            room_id = room_row['id']
                            lab_slot_vars.append(teacher_lab_assignments[teacher][d][s][room_id])
                        
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
                    
                    # Calculate required lab slots based on practical hours and student count
                    required_lab_slots = (practical_hours + 1) // 2  # Ceiling division for base lab slots
                    
                    # For large classes (>35 students), we need multiple batches
                    if instance['student_count'] > 35:
                        num_batches = (instance['student_count'] + 34) // 35
                        required_lab_slots *= num_batches
                    
                    # Ensure the required number of lab slots
                    if practical_hours > 0:
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
                    room_vars = []
                    for teacher in self.teachers:
                        room_vars.append(teacher_theory_assignments[teacher][d][s][room_id])
                    self.model.Add(sum(room_vars) <= 1)
        
        # For labs
        for _, room_row in self.labs.iterrows():
            room_id = room_row['id']
            for d in range(self.num_days):
                for s in range(self.num_lab_slots):
                    room_vars = []
                    for teacher in self.teachers:
                        room_vars.append(teacher_lab_assignments[teacher][d][s][room_id])
                    self.model.Add(sum(room_vars) <= 1)
        
        return True
    
    def apply_all_constraints(self, teacher_theory_assignments, teacher_lab_assignments):
        """Apply all timetable constraints."""
        logger.info("Applying all timetable constraints...")
        
        constraints_applied = [
            self.apply_teacher_single_assignment_constraint(teacher_theory_assignments, teacher_lab_assignments),
            self.apply_no_overlapping_slots_constraint(teacher_theory_assignments, teacher_lab_assignments),
            self.apply_course_hours_constraint(teacher_theory_assignments, teacher_lab_assignments),
            self.apply_room_single_assignment_constraint(teacher_theory_assignments, teacher_lab_assignments)
            # Lab batch constraint logic is now incorporated into the course hours constraint
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
            }
        }
        
        return summary 