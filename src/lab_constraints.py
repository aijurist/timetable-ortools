import logging


class LabConstraints:
    """Class containing all lab scheduling constraints."""
    
    def __init__(self, lab_scheduler):
        """Initialize with reference to the lab scheduler."""
        self.scheduler = lab_scheduler
        self.logger = logging.getLogger(__name__)
    
    def apply_all_constraints(self, model, lab_assignments, lab_room_ids, lab_sessions, course_to_teacher):
        """Apply all lab scheduling constraints."""
        self.logger.info("Applying all lab scheduling constraints...")
        
        # Apply individual constraints
        self.apply_course_lab_requirements_constraint(model, lab_assignments, lab_sessions)
        self.apply_teacher_single_lab_assignment_constraint(model, lab_assignments, lab_room_ids, lab_sessions, course_to_teacher)
        self.apply_lab_room_single_assignment_constraint(model, lab_assignments, lab_sessions)
        self.apply_no_theory_lab_overlap_constraint(model, lab_assignments, lab_sessions, course_to_teacher)
        self.apply_weekly_working_hour_constraint(model, lab_assignments, lab_sessions, course_to_teacher)
        self.apply_continuous_lab_room_constraint(model, lab_assignments, lab_room_ids, lab_sessions)
        
        self.logger.info("All lab constraints applied successfully")
    
    def apply_course_lab_requirements_constraint(self, model, lab_assignments, lab_sessions):
        """Ensure each course gets the required number of lab sessions."""
        self.logger.info("Applying course lab requirements constraint (COURSE LEVEL)...")
        
        for teacher, courses in self.scheduler.lab_requirements.items():
            for course in courses:
                course_instance_id = course['course_instance_id']
                required_sessions = course['total_sessions_needed']
                
                # Collect all possible lab session assignments for this specific course
                course_lab_vars = []
                for day_idx in range(self.scheduler.num_days):
                    for session_idx in range(len(lab_sessions)):
                        for room_id in self.scheduler.labs['id']:
                            course_lab_vars.append(lab_assignments[course_instance_id][day_idx][session_idx][room_id])
                
                # Ensure course gets exactly the required number of lab sessions
                model.Add(sum(course_lab_vars) == required_sessions)
                
                self.logger.info(f"Course {course['display_course_code']} (ID: {course['course_instance_id']}, Teacher {teacher}): {course['practical_hours']} practical hours -> {required_sessions} lab sessions required")
    
    def apply_teacher_single_lab_assignment_constraint(self, model, lab_assignments, lab_room_ids, lab_sessions, course_to_teacher):
        """Prevent teacher from being in multiple labs at the same time."""
        self.logger.info("Applying teacher single lab assignment constraint...")
        
        # Group course assignments by teacher for overlap checking
        teacher_courses = {}
        for course_instance_id, teacher in course_to_teacher.items():
            if teacher not in teacher_courses:
                teacher_courses[teacher] = []
            teacher_courses[teacher].append(course_instance_id)
        
        for teacher, course_list in teacher_courses.items():
            for day_idx in range(self.scheduler.num_days):
                for session_idx in range(len(lab_sessions)):
                    # Teacher can be in at most one lab per session (across all their courses)
                    teacher_lab_vars = []
                    for course_instance_id in course_list:
                        for room_id in lab_room_ids:
                            teacher_lab_vars.append(lab_assignments[course_instance_id][day_idx][session_idx][room_id])
                    model.Add(sum(teacher_lab_vars) <= 1)
    
    def apply_lab_room_single_assignment_constraint(self, model, lab_assignments, lab_sessions):
        """Prevent lab room double-booking."""
        self.logger.info("Applying lab room single assignment constraint...")
        
        for room_id in self.scheduler.labs['id']:
            for day_idx in range(self.scheduler.num_days):
                for session_idx in range(len(lab_sessions)):
                    # Each lab room can have at most one course per session
                    room_vars = []
                    for course_instance_id in lab_assignments.keys():
                        room_vars.append(lab_assignments[course_instance_id][day_idx][session_idx][room_id])
                    model.Add(sum(room_vars) <= 1)
    
    def apply_no_theory_lab_overlap_constraint(self, model, lab_assignments, lab_sessions, course_to_teacher):
        """Prevent teachers from having overlapping theory and lab sessions."""
        self.logger.info("Applying no theory-lab overlap constraint...")
        
        # Map theory time slots to lab sessions that overlap
        theory_lab_overlaps = self.calculate_theory_lab_overlaps()
        overlap_violations = 0
        
        # Group course assignments by teacher
        teacher_courses = {}
        for course_instance_id, teacher in course_to_teacher.items():
            if teacher not in teacher_courses:
                teacher_courses[teacher] = []
            teacher_courses[teacher].append(course_instance_id)
        
        for teacher, course_list in teacher_courses.items():
            # Get teacher's theory schedule
            teacher_theory = self.scheduler.theory_schedule_df[self.scheduler.theory_schedule_df['teacher_id'] == teacher]
            
            for _, theory_slot in teacher_theory.iterrows():
                theory_day = theory_slot['day']
                theory_slot_idx = theory_slot['slot_index']
                
                if theory_day in self.scheduler.days:
                    day_idx = self.scheduler.days.index(theory_day)
                    
                    # Find lab sessions that overlap with this theory slot
                    overlapping_sessions = theory_lab_overlaps.get((theory_day, theory_slot_idx), [])
                    
                    for session_name in overlapping_sessions:
                        if session_name in lab_sessions:
                            session_idx = lab_sessions.index(session_name)
                            
                            # Teacher cannot be in lab during theory class (across all their courses)
                            lab_vars = []
                            for course_instance_id in course_list:
                                for room_id in self.scheduler.labs['id']:
                                    lab_vars.append(lab_assignments[course_instance_id][day_idx][session_idx][room_id])
                            
                            # Add constraint - no lab during theory
                            model.Add(sum(lab_vars) == 0)
                            overlap_violations += 1
        
        self.logger.info(f"Applied {overlap_violations} theory-lab overlap constraints")
    
    def calculate_theory_lab_overlaps(self):
        """Calculate which lab sessions overlap with theory time slots."""
        overlaps = {}
        
        # Theory time slots
        theory_slots = [
            "8:00 - 8:50", "9:00 - 9:50", "10:00 - 10:50", "11:00 - 11:50",
            "12:00 - 12:50", "1:00 - 1:50", "2:00 - 2:50", "3:00 - 3:50", 
            "4:00 - 4:50", "5:00 - 5:50", "6:00 - 6:50"
        ]
        
        def parse_time(time_str):
            """Parse time string like '11:00' to minutes since midnight."""
            time_part = time_str.split()[0]  # Get '11:00' from '11:00 - 11:50'
            hours, minutes = map(int, time_part.split(':'))
            return hours * 60 + minutes
        
        def time_ranges_overlap(range1, range2):
            """Check if two time ranges overlap."""
            # Parse range1 (e.g., "11:00 - 11:50")
            start1_str, end1_str = range1.split(' - ')
            start1 = parse_time(start1_str)
            end1 = parse_time(end1_str)
            
            # Parse range2 (e.g., "10:40 - 11:30") 
            start2_str, end2_str = range2.split(' - ')
            start2 = parse_time(start2_str)
            end2 = parse_time(end2_str)
            
            # Check for overlap: ranges overlap if start1 < end2 and start2 < end1
            return start1 < end2 and start2 < end1
        
        for day in self.scheduler.days:
            for slot_idx, theory_slot in enumerate(theory_slots):
                overlapping_sessions = []
                
                # Check each lab session for overlap with this theory slot
                for session_name, session_times in self.scheduler.lab_sessions.items():
                    session_overlaps = False
                    for lab_time in session_times:
                        if time_ranges_overlap(theory_slot, lab_time):
                            session_overlaps = True
                            break
                    
                    if session_overlaps:
                        overlapping_sessions.append(session_name)
                
                if overlapping_sessions:
                    overlaps[(day, slot_idx)] = overlapping_sessions
        
        return overlaps
    
    def apply_weekly_working_hour_constraint(self, model, lab_assignments, lab_sessions, course_to_teacher):
        """Apply weekly working hour constraint including both theory and lab hours."""
        self.logger.info("Applying weekly working hour constraint (25 hours max including labs)...")
        
        # Group course assignments by teacher
        teacher_courses = {}
        for course_instance_id, teacher in course_to_teacher.items():
            if teacher not in teacher_courses:
                teacher_courses[teacher] = []
            teacher_courses[teacher].append(course_instance_id)
        
        for teacher, course_list in teacher_courses.items():
            # Count theory hours from existing schedule
            teacher_theory = self.scheduler.theory_schedule_df[self.scheduler.theory_schedule_df['teacher_id'] == teacher]
            theory_hours = len(teacher_theory)  # Each theory slot = 1 hour
            
            # Count lab hours (each lab session = 2 hours) across all teacher's courses
            lab_hour_vars = []
            for course_instance_id in course_list:
                for day_idx in range(self.scheduler.num_days):
                    for session_idx in range(len(lab_sessions)):
                        for room_id in self.scheduler.labs['id']:
                            lab_hour_vars.append(lab_assignments[course_instance_id][day_idx][session_idx][room_id])
            
            total_lab_hours = sum(lab_hour_vars) * 2  # Each lab session = 2 hours
            
            # Constraint: theory_hours + lab_hours <= 25
            model.Add(theory_hours + total_lab_hours <= 25)
            
            self.logger.info(f"Teacher {teacher}: {theory_hours} theory hours + labs <= 25 total hours")
    
    def apply_continuous_lab_room_constraint(self, model, lab_assignments, lab_room_ids, lab_sessions):
        """Ensure that multi-slot lab sessions use the same room continuously."""
        self.logger.info("Applying continuous lab room constraint for lab sessions...")
        
        # Since each lab session (L1, L2, etc.) already consists of 2 consecutive time slots,
        # and we're assigning at the session level, we need to ensure the session assignment
        # is consistent. The actual continuous room usage is handled implicitly since
        # each L1, L2, etc. represents a continuous 2-hour block.
        
        self.logger.info("Continuous lab room constraint: Handled by session-level assignment structure")
    
    def apply_relaxed_constraints(self, model, lab_assignments, lab_room_ids, lab_sessions, course_to_teacher):
        """Apply relaxed constraints for when normal constraints are too restrictive."""
        self.logger.info("Applying relaxed lab constraints...")
        
        # 1. Relaxed course requirements (allow partial fulfillment)
        for teacher, courses in self.scheduler.lab_requirements.items():
            for course in courses:
                course_instance_id = course['course_instance_id']
                required_sessions = course['total_sessions_needed']
                
                # Collect all possible lab session assignments for this specific course
                course_lab_vars = []
                for day_idx in range(self.scheduler.num_days):
                    for session_idx in range(len(lab_sessions)):
                        for room_id in self.scheduler.labs['id']:
                            course_lab_vars.append(lab_assignments[course_instance_id][day_idx][session_idx][room_id])
                
                # More relaxed: allow at least 1 session, but try for full requirement
                model.Add(sum(course_lab_vars) >= min(1, required_sessions))
                model.Add(sum(course_lab_vars) <= required_sessions)
                
                self.logger.info(f"Relaxed constraint: Course {course['display_course_code']} needs 1-{required_sessions} lab sessions")
        
        # 2. Teacher single assignment constraint (still apply this for safety)
        teacher_courses = {}
        for course_instance_id, teacher in course_to_teacher.items():
            if teacher not in teacher_courses:
                teacher_courses[teacher] = []
            teacher_courses[teacher].append(course_instance_id)
        
        for teacher, course_list in teacher_courses.items():
            for day_idx in range(self.scheduler.num_days):
                for session_idx in range(len(lab_sessions)):
                    # Teacher can be in at most one lab per session (across all their courses)
                    teacher_lab_vars = []
                    for course_instance_id in course_list:
                        for room_id in lab_room_ids:
                            teacher_lab_vars.append(lab_assignments[course_instance_id][day_idx][session_idx][room_id])
                    model.Add(sum(teacher_lab_vars) <= 1)
        
        # 3. Lab room single assignment constraint (still apply this for safety)
        for room_id in self.scheduler.labs['id']:
            for day_idx in range(self.scheduler.num_days):
                for session_idx in range(len(lab_sessions)):
                    room_vars = []
                    for course_instance_id in lab_assignments.keys():
                        room_vars.append(lab_assignments[course_instance_id][day_idx][session_idx][room_id])
                    model.Add(sum(room_vars) <= 1)
        
        self.logger.info("Relaxed lab constraints applied successfully")


# Utility functions for constraint validation and debugging
def validate_lab_constraints(schedule_df, lab_requirements):
    """Validate that the generated lab schedule satisfies all constraints."""
    violations = []
    
    # Check if all courses got required lab sessions
    lab_data = schedule_df[schedule_df['slot_type'] == 'Practical']
    
    for teacher, courses in lab_requirements.items():
        for course in courses:
            course_instance_id = course['course_instance_id']
            required_sessions = course['total_sessions_needed']
            
            # Count actual lab sessions for this course
            course_labs = lab_data[lab_data['course_instance_id'] == course_instance_id]
            actual_sessions = len(course_labs) // 2  # Each session = 2 time slots
            
            if actual_sessions != required_sessions:
                violations.append(f"Course {course['display_course_code']} (ID: {course_instance_id}): "
                                f"Required {required_sessions} sessions, got {actual_sessions}")
    
    # Check for theory-lab time overlaps
    def parse_time(time_str):
        """Parse time string like '11:00' to minutes since midnight."""
        time_part = time_str.split()[0]  # Get '11:00' from '11:00 - 11:50'
        hours, minutes = map(int, time_part.split(':'))
        return hours * 60 + minutes
    
    def time_ranges_overlap(range1, range2):
        """Check if two time ranges overlap."""
        # Parse range1 (e.g., "11:00 - 11:50")
        start1_str, end1_str = range1.split(' - ')
        start1 = parse_time(start1_str)
        end1 = parse_time(end1_str)
        
        # Parse range2 (e.g., "10:40 - 11:30") 
        start2_str, end2_str = range2.split(' - ')
        start2 = parse_time(start2_str)
        end2 = parse_time(end2_str)
        
        # Check for overlap: ranges overlap if start1 < end2 and start2 < end1
        return start1 < end2 and start2 < end1
    
    # Check for teacher time conflicts (theory vs lab)
    theory_data = schedule_df[schedule_df['slot_type'].isin(['Lecture', 'Tutorial'])]
    
    for teacher_id in schedule_df['teacher_id'].unique():
        teacher_theory = theory_data[theory_data['teacher_id'] == teacher_id]
        teacher_labs = lab_data[lab_data['teacher_id'] == teacher_id]
        
        for _, theory_row in teacher_theory.iterrows():
            theory_day = theory_row['day']
            theory_time = theory_row['time_interval']
            
            for _, lab_row in teacher_labs.iterrows():
                lab_day = lab_row['day']
                lab_time = lab_row['time_interval']
                
                # Check if same day and time overlap
                if theory_day == lab_day and time_ranges_overlap(theory_time, lab_time):
                    violations.append(f"Teacher {teacher_id} time conflict on {theory_day}: "
                                    f"Theory class {theory_time} overlaps with lab {lab_time}")
    
    return violations


def analyze_constraint_conflicts(lab_requirements, theory_schedule_df, lab_rooms):
    """Analyze potential constraint conflicts before scheduling."""
    analysis = {
        'total_lab_sessions_needed': 0,
        'total_lab_capacity': 0,
        'theory_lab_conflicts': 0,
        'teacher_overloads': []
    }
    
    # Calculate total lab sessions needed
    for courses in lab_requirements.values():
        for course in courses:
            analysis['total_lab_sessions_needed'] += course['total_sessions_needed']
    
    # Calculate total lab capacity per week
    analysis['total_lab_capacity'] = len(lab_rooms) * 6 * 5  # 6 sessions * 5 days
    
    # Check for potential teacher overloads
    for teacher, courses in lab_requirements.items():
        teacher_theory_hours = len(theory_schedule_df[theory_schedule_df['teacher_id'] == teacher])
        teacher_lab_hours = sum(course['total_sessions_needed'] * 2 for course in courses)  # Each session = 2 hours
        total_hours = teacher_theory_hours + teacher_lab_hours
        
        if total_hours > 25:
            analysis['teacher_overloads'].append({
                'teacher': teacher,
                'theory_hours': teacher_theory_hours,
                'lab_hours': teacher_lab_hours,
                'total_hours': total_hours
            })
    
    return analysis 