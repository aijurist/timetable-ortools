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
        Constraint 3: Allocate the correct number of hours for each course.
        Ensures that each course gets allocated the required lecture and practical hours.
        """
        logger.info("Applying course hours constraint...")
        
        for teacher in self.teachers:
            if teacher in self.teacher_course_assignments:
                for course_info in self.teacher_course_assignments[teacher]:
                    lecture_hours = course_info['lecture_hours']
                    practical_hours = course_info['practical_hours']
                    
                    # Track lecture hours allocation (1 theory slot = 1 lecture hour)
                    theory_vars = []
                    for d in range(self.num_days):
                        for s in range(self.num_theory_slots):
                            for _, room_row in self.classrooms.iterrows():
                                room_id = room_row['id']
                                theory_vars.append(teacher_theory_assignments[teacher][d][s][room_id])
                    
                    # We need to ensure at least lecture_hours theory slots are assigned
                    if lecture_hours > 0:
                        self.model.Add(sum(theory_vars) >= lecture_hours)
                    
                    # Track practical hours allocation (1 lab slot = 2 practical hours)
                    lab_vars = []
                    for d in range(self.num_days):
                        for s in range(self.num_lab_slots):
                            for _, room_row in self.labs.iterrows():
                                room_id = room_row['id']
                                lab_vars.append(teacher_lab_assignments[teacher][d][s][room_id])
                    
                    # We need to ensure at least practical_hours/2 lab slots are assigned (rounded up)
                    required_lab_slots = (practical_hours + 1) // 2  # Ceiling division
                    if practical_hours > 0:
                        self.model.Add(sum(lab_vars) >= required_lab_slots)
        
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
    
    def apply_lab_batch_constraint(self, teacher_theory_assignments, teacher_lab_assignments):
        """
        Constraint 5: Labs have limited capacity (35 students), so classes with 70 students need two separate lab slots.
        This ensures proper lab sessions for all students in batches.
        """
        logger.info("Applying lab batch constraint...")
        
        for teacher in self.teachers:
            if teacher in self.teacher_course_assignments:
                for course_info in self.teacher_course_assignments[teacher]:
                    # Only apply this constraint to courses with practical hours and student count > 35
                    practical_hours = course_info['practical_hours']
                    student_count = course_info['student_count']
                    
                    if practical_hours > 0 and student_count > 35:
                        # Calculate the number of batches needed
                        num_batches = (student_count + 34) // 35  # Ceiling division by 35
                        
                        # For each batch, we need practical_hours/2 lab slots (rounded up)
                        required_lab_slots_per_batch = (practical_hours + 1) // 2
                        total_required_lab_slots = required_lab_slots_per_batch * num_batches
                        
                        # Collect all lab assignment variables for this teacher
                        lab_vars = []
                        for d in range(self.num_days):
                            for s in range(self.num_lab_slots):
                                for _, room_row in self.labs.iterrows():
                                    room_id = room_row['id']
                                    lab_vars.append(teacher_lab_assignments[teacher][d][s][room_id])
                        
                        # Ensure the teacher gets enough lab slots for all batches
                        self.model.Add(sum(lab_vars) >= total_required_lab_slots)
                        
                        # Try to schedule lab slots on different days for different batches
                        # This is a soft constraint, so we'll use a heuristic approach
                        if num_batches > 1:
                            for d1 in range(self.num_days):
                                # Count labs on this day
                                day1_lab_vars = []
                                for s in range(self.num_lab_slots):
                                    for _, room_row in self.labs.iterrows():
                                        room_id = room_row['id']
                                        day1_lab_vars.append(teacher_lab_assignments[teacher][d1][s][room_id])
                                
                                # Try to limit labs on a single day to one batch worth
                                # This is a soft constraint that helps spread batches across days
                                self.model.Add(sum(day1_lab_vars) <= required_lab_slots_per_batch)
        
        return True
    
    def apply_all_constraints(self, teacher_theory_assignments, teacher_lab_assignments):
        """Apply all timetable constraints."""
        logger.info("Applying all timetable constraints...")
        
        constraints_applied = [
            self.apply_teacher_single_assignment_constraint(teacher_theory_assignments, teacher_lab_assignments),
            self.apply_no_overlapping_slots_constraint(teacher_theory_assignments, teacher_lab_assignments),
            self.apply_course_hours_constraint(teacher_theory_assignments, teacher_lab_assignments),
            self.apply_room_single_assignment_constraint(teacher_theory_assignments, teacher_lab_assignments),
            self.apply_lab_batch_constraint(teacher_theory_assignments, teacher_lab_assignments)
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