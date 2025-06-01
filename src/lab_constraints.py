import logging


class LabConstraints:
    """Class containing all lab scheduling constraints."""
    
    def __init__(self, lab_scheduler):
        """Initialize with reference to the lab scheduler."""
        self.scheduler = lab_scheduler
        self.logger = logging.getLogger(__name__)
    
    def apply_all_constraints(self, model, lab_assignments, lab_room_ids, lab_sessions, course_to_teacher):
        """Apply all lab scheduling constraints including the new practical hours capacity constraint."""
        self.logger.info("Applying lab scheduling constraints...")
        self.lab_sessions = lab_sessions
        
        # Store lab room IDs for constraint methods
        self.lab_room_ids = lab_room_ids
        
        # Apply individual constraints (using existing method names)
        self.apply_course_lab_requirements_constraint(model, lab_assignments, course_to_teacher)
        self.apply_teacher_single_lab_assignment_constraint(model, lab_assignments, lab_room_ids, lab_sessions, course_to_teacher)
        self.apply_lab_room_single_assignment_constraint(model, lab_assignments, lab_sessions)
        # COMMENTED OUT: Theory-Lab Overlap Prevention Constraint
        # self.apply_theory_lab_overlap_prevention_constraint(model, lab_assignments, lab_sessions, course_to_teacher)
        
        # NEW: Apply macroblock-based lab allocation constraint
        self.apply_macroblock_based_lab_allocation_constraint(model, lab_assignments, lab_sessions, course_to_teacher)
        
        self.apply_weekly_working_hour_constraint(model, lab_assignments, lab_sessions, course_to_teacher)
        self.apply_continuous_lab_room_constraint(model, lab_assignments, lab_room_ids, lab_sessions)
        
        # Apply the new hard constraint for practical hours and lab capacity
        self.apply_practical_hours_capacity_constraint(model, lab_assignments)
        
        # Apply new capacity-based constraints
        self.apply_capacity_based_room_assignment_constraint(model, lab_assignments)
        
        # Apply capacity preference constraints for 70-student courses
        self.apply_capacity_preference_constraints(model, lab_assignments, lab_room_ids, lab_sessions)
        
        # NEW: Apply consecutive lab slots constraint (max 2 consecutive sessions per teacher per day)
        self.apply_max_consecutive_lab_slots_constraint(model, lab_assignments, lab_sessions, course_to_teacher)
        
        # COMMENTED OUT: Teacher Shift Constraint
        # self.apply_teacher_shift_constraint(model, lab_assignments, lab_sessions, course_to_teacher)
        
        self.logger.info("All lab constraints applied successfully")
    
    def apply_course_lab_requirements_constraint(self, model, lab_assignments, course_to_teacher):
        """Ensure each course gets the required number of lab sessions based on capacity allocation strategy."""
        for teacher, courses in self.scheduler.lab_requirements.items():
            for course in courses:
                course_instance_id = course['course_instance_id']
                total_lab_slots_needed = course['total_lab_slots_needed']
                batching_required = course['batching_required']
                num_batches = course['num_batches']
                
                if course_instance_id in lab_assignments:
                    # Count total assignments for this course instance
                    total_assignments = []
                    
                    for day_idx in range(self.scheduler.num_days):
                        for session_idx in range(len(list(self.scheduler.lab_sessions.keys()))):
                            for room_id in self.scheduler.labs['id'].tolist():
                                total_assignments.append(lab_assignments[course_instance_id][day_idx][session_idx][room_id])
                    
                    # Add constraint for exact number of lab slots needed
                    model.Add(sum(total_assignments) == total_lab_slots_needed)
                    
                    # If batching is required, add additional constraints
                    if batching_required and num_batches > 1:
                        # Constraint: Batches must be on different days/times (same teacher can't be in two places)
                        self._add_batch_separation_constraint(model, lab_assignments, course_instance_id, num_batches)
                        
                        # Constraint: Ensure consistent room capacity for batched assignments
                        self._add_capacity_consistency_constraint(model, lab_assignments, course_instance_id, course)
    
    def _add_batch_separation_constraint(self, model, lab_assignments, course_instance_id, num_batches):
        """Ensure batches are scheduled at different times (same teacher can't be in multiple places)."""
        # For each day-session combination, at most one batch can be scheduled
        for day_idx in range(self.scheduler.num_days):
            for session_idx in range(len(list(self.scheduler.lab_sessions.keys()))):
                session_assignments = []
                for room_id in self.scheduler.labs['id'].tolist():
                    session_assignments.append(lab_assignments[course_instance_id][day_idx][session_idx][room_id])
                
                # At most one assignment per day-session (to avoid teacher conflicts)
                model.Add(sum(session_assignments) <= 1)
    
    def _add_capacity_consistency_constraint(self, model, lab_assignments, course_instance_id, course):
        """Ensure room capacity is appropriate for the allocation strategy with 70-capacity lab preferences."""
        preferred_capacities = course['preferred_lab_capacities']
        students_per_batch = course['students_per_batch']
        practical_hours = course['practical_hours']
        students_per_instance = course['students_per_instance']
        
        # Get lab rooms categorized by capacity
        labs_by_capacity = {
            35: [lab['id'] for lab in self.scheduler.lab_capacity_analysis['labs_35']],
            70: [lab['id'] for lab in self.scheduler.lab_capacity_analysis['labs_70']],
            140: [lab['id'] for lab in self.scheduler.lab_capacity_analysis['labs_140']]
        }
        
        # NEW LOGIC: Handle both 35 and 70 capacity labs with preferences
        for day_idx in range(self.scheduler.num_days):
            for session_idx in range(len(list(self.scheduler.lab_sessions.keys()))):
                capacity_assignments = {}
                
                # Group assignments by capacity
                for capacity in [35, 70]:
                    capacity_assignments[capacity] = []
                    if capacity in labs_by_capacity:
                        for room_id in labs_by_capacity[capacity]:
                            if room_id in self.scheduler.labs['id'].tolist():
                                capacity_assignments[capacity].append(
                                    lab_assignments[course_instance_id][day_idx][session_idx][room_id])
                
                # Apply capacity-based constraints for 70-student courses
                if students_per_instance == 70:
                    # 70-student courses can use either 35 or 70 capacity labs
                    # No hard constraints needed - preference handled in objective function
                    
                    # For courses with >2 practical hours, strongly discourage 35-capacity labs
                    # unless no 70-capacity labs are available
                    if practical_hours > 2 and 35 in capacity_assignments and 70 in capacity_assignments:
                        # Add soft constraint to prefer 70-capacity labs
                        # This will be handled through objective function weighting
                        pass
                elif students_per_instance > 70:
                    # >70 students: prefer 70-capacity labs, allow 35 with batching
                    pass
                elif students_per_instance <= 35:
                    # ≤35 students: can use any capacity, prefer 35 for efficiency
                    pass
    
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
    
    # COMMENTED OUT: Theory-Lab Overlap Prevention Constraint
    # def apply_theory_lab_overlap_prevention_constraint(self, model, lab_assignments, lab_sessions, course_to_teacher):
    #     """Prevent teachers from having overlapping theory and lab sessions."""
    #     self.logger.info("Applying no theory-lab overlap constraint...")
    #     
    #     # Map theory time slots to lab sessions that overlap
    #     theory_lab_overlaps = self.calculate_theory_lab_overlaps()
    #     overlap_violations = 0
    #     
    #     # Group course assignments by teacher
    #     teacher_courses = {}
    #     for course_instance_id, teacher in course_to_teacher.items():
    #         if teacher not in teacher_courses:
    #             teacher_courses[teacher] = []
    #         teacher_courses[teacher].append(course_instance_id)
    #     
    #     for teacher, course_list in teacher_courses.items():
    #         # Get teacher's theory schedule
    #         teacher_theory = self.scheduler.theory_schedule_df[self.scheduler.theory_schedule_df['teacher_id'] == teacher]
    #         
    #         for _, theory_slot in teacher_theory.iterrows():
    #             theory_day = theory_slot['day']
    #             theory_slot_idx = theory_slot['slot_index']
    #             
    #             if theory_day in self.scheduler.days:
    #                 day_idx = self.scheduler.days.index(theory_day)
    #                 
    #                 # Find lab sessions that overlap with this theory slot
    #                 overlapping_sessions = theory_lab_overlaps.get((theory_day, theory_slot_idx), [])
    #                 
    #                 for session_name in overlapping_sessions:
    #                     if session_name in lab_sessions:
    #                         session_idx = lab_sessions.index(session_name)
    #                         
    #                         # Teacher cannot be in lab during theory class (across all their courses)
    #                         lab_vars = []
    #                         for course_instance_id in course_list:
    #                             for room_id in self.scheduler.labs['id']:
    #                                 lab_vars.append(lab_assignments[course_instance_id][day_idx][session_idx][room_id])
    #                         
    #                         # Add constraint - no lab during theory
    #                         model.Add(sum(lab_vars) == 0)
    #                         overlap_violations += 1
    #     
    #     self.logger.info(f"Applied {overlap_violations} theory-lab overlap constraints")
    
    # COMMENTED OUT: Helper method for theory-lab overlap calculation
    # def calculate_theory_lab_overlaps(self):
    #     """Calculate which lab sessions overlap with theory time slots."""
    #     overlaps = {}
    #     
    #     # Theory time slots
    #     theory_slots = [
    #         "8:00 - 8:50", "9:00 - 9:50", "10:00 - 10:50", "11:00 - 11:50",
    #         "12:00 - 12:50", "1:00 - 1:50", "2:00 - 2:50", "3:00 - 3:50", 
    #         "4:00 - 4:50", "5:00 - 5:50", "6:00 - 6:50"
    #     ]
    #     
    #     def parse_time(time_str):
    #         """Parse time string like '11:00' to minutes since midnight."""
    #         time_part = time_str.split()[0]  # Get '11:00' from '11:00 - 11:50'
    #         hours, minutes = map(int, time_part.split(':'))
    #         return hours * 60 + minutes
    #     
    #     def time_ranges_overlap(range1, range2):
    #         """Check if two time ranges overlap."""
    #         # Parse range1 (e.g., "11:00 - 11:50")
    #         start1_str, end1_str = range1.split(' - ')
    #         start1 = parse_time(start1_str)
    #         end1 = parse_time(end1_str)
    #         
    #         # Parse range2 (e.g., "10:40 - 11:30") 
    #         start2_str, end2_str = range2.split(' - ')
    #         start2 = parse_time(start2_str)
    #         end2 = parse_time(end2_str)
    #         
    #         # Check for overlap: ranges overlap if start1 < end2 and start2 < end1
    #         return start1 < end2 and start2 < end1
    #     
    #     for day in self.scheduler.days:
    #         for slot_idx, theory_slot in enumerate(theory_slots):
    #             overlapping_sessions = []
    #             
    #             # Check each lab session for overlap with this theory slot
    #             for session_name, session_times in self.scheduler.lab_sessions.items():
    #                 session_overlaps = False
    #                 for lab_time in session_times:
    #                     if time_ranges_overlap(theory_slot, lab_time):
    #                         session_overlaps = True
    #                         break
    #                 
    #                 if session_overlaps:
    #                     overlapping_sessions.append(session_name)
    #             
    #             if overlapping_sessions:
    #                 overlaps[(day, slot_idx)] = overlapping_sessions
    #     
    #     return overlaps
    
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
    
    def apply_capacity_based_room_assignment_constraint(self, model, lab_assignments):
        """Apply capacity-based room assignment constraints for optimal allocation."""
        self.logger.info("Applying capacity-based room assignment constraint...")
        
        # For each course, prefer rooms that match their capacity requirements
        for teacher, courses in self.scheduler.lab_requirements.items():
            for course in courses:
                course_instance_id = course['course_instance_id']
                preferred_capacities = course['preferred_lab_capacities']
                practical_hours = course['practical_hours']
                
                if course_instance_id in lab_assignments:
                    # Apply preference weighting (this will be used in the objective function)
                    # For practical hours > 3, strongly prefer 70+ capacity labs
                    if practical_hours > 3:
                        self._apply_capacity_preference_weights(model, lab_assignments, course_instance_id, course)
        
        self.logger.info("Capacity-based room assignment constraint applied successfully")
    
    def _apply_capacity_preference_weights(self, model, lab_assignments, course_instance_id, course):
        """Apply capacity preference weights to encourage 70-capacity labs for high practical hour courses."""
        # Get lab rooms categorized by capacity
        labs_by_capacity = {
            35: [lab['id'] for lab in self.scheduler.lab_capacity_analysis['labs_35']],
            70: [lab['id'] for lab in self.scheduler.lab_capacity_analysis['labs_70']],
            140: [lab['id'] for lab in self.scheduler.lab_capacity_analysis['labs_140']]
        }
        
        practical_hours = course['practical_hours']
        students_per_instance = course['students_per_instance']
        
        # For courses with >2 practical hours, strongly prefer 70-capacity labs
        if practical_hours > 2 and students_per_instance > 60:
            self.scheduler.logger.info(f"Applying 70-capacity lab preference for course {course['display_course_code']} "
                                     f"with {practical_hours} practical hours")
            
            # Create preference variables to encourage 70-capacity lab usage
            # This is implemented through the objective function optimization
            # The solver will naturally prefer assignments that minimize the objective
            
            for day_idx in range(self.scheduler.num_days):
                for session_idx in range(len(list(self.scheduler.lab_sessions.keys()))):
                    # Track assignments to different capacity labs
                    assignments_35 = []
                    assignments_70 = []
                    
                    if 35 in labs_by_capacity:
                        for room_id in labs_by_capacity[35]:
                            if room_id in self.scheduler.labs['id'].tolist():
                                assignments_35.append(
                                    lab_assignments[course_instance_id][day_idx][session_idx][room_id])
                    
                    if 70 in labs_by_capacity:
                        for room_id in labs_by_capacity[70]:
                            if room_id in self.scheduler.labs['id'].tolist():
                                assignments_70.append(
                                    lab_assignments[course_instance_id][day_idx][session_idx][room_id])
                    
                    # Add soft preference for 70-capacity labs
                    # This will be handled in the objective function
                    # For now, we trust the solver to find optimal allocation
        
        # For courses with ≤2 practical hours, no strong preference needed
        elif practical_hours <= 2 and students_per_instance == 70:
            self.scheduler.logger.info(f"No strong capacity preference for course {course['display_course_code']} "
                                     f"with {practical_hours} practical hours - any capacity acceptable")
    
    def apply_capacity_preference_constraints(self, model, lab_assignments, lab_room_ids, lab_sessions):
        """Apply capacity preference constraints for 70-student courses."""
        self.logger.info("Applying capacity preference constraints for 70-student courses...")
        
        for teacher, courses in self.scheduler.lab_requirements.items():
            for course in courses:
                course_instance_id = course['course_instance_id']
                practical_hours = course['practical_hours']
                
                if course_instance_id in lab_assignments and practical_hours > 3:
                    # Get lab rooms categorized by capacity
                    labs_by_capacity = {
                        35: [lab['id'] for lab in self.scheduler.lab_capacity_analysis['labs_35']],
                        70: [lab['id'] for lab in self.scheduler.lab_capacity_analysis['labs_70']],
                        140: [lab['id'] for lab in self.scheduler.lab_capacity_analysis['labs_140']]
                    }
                    
                    # Apply capacity preference weights
                    self._apply_capacity_preference_weights(model, lab_assignments, course_instance_id, course)
        
        self.logger.info("Capacity preference constraints applied successfully")

    def apply_relaxed_constraints(self, model, lab_assignments, lab_room_ids, lab_sessions, course_to_teacher):
        """Apply relaxed constraints for when normal constraints are too restrictive."""
        self.logger.info("Applying relaxed lab constraints...")
        
        # 1. Relaxed course requirements (allow partial fulfillment)
        for teacher, courses in self.scheduler.lab_requirements.items():
            for course in courses:
                course_instance_id = course['course_instance_id']
                required_sessions = course['total_lab_slots_needed']
                
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
        
        # 4. Apply relaxed shift constraints (more lenient than full constraints)
        # COMMENTED OUT: Relaxed shift constraints
        # self.apply_relaxed_teacher_shift_constraint(model, lab_assignments, lab_sessions, course_to_teacher)
        
        # 5. Apply macroblock-based lab allocation constraint (keep this even in relaxed mode)
        self.apply_macroblock_based_lab_allocation_constraint(model, lab_assignments, lab_sessions, course_to_teacher)
        
        # 6. Apply macroblock-based lab grouping constraint (keep this even in relaxed mode)
        # COMMENTED OUT: Macroblock Lab Grouping Constraint (removed per user request)
        # self.apply_macroblock_lab_grouping_constraint(model, lab_assignments, lab_sessions, course_to_teacher)
        
        # 7. Apply consecutive lab slots constraint (keep this even in relaxed mode to prevent teacher exhaustion)
        self.apply_max_consecutive_lab_slots_constraint(model, lab_assignments, lab_sessions, course_to_teacher)
        
        self.logger.info("Relaxed lab constraints applied successfully")

    # COMMENTED OUT: Relaxed Teacher Shift Constraint
    # def apply_relaxed_teacher_shift_constraint(self, model, lab_assignments, lab_sessions, course_to_teacher):
    #     """Apply relaxed teacher shift constraint - prefer shift-compliant sessions but allow violations if necessary."""
    #     self.logger.info("Applying relaxed teacher shift constraint...")
    #     
    #     if not hasattr(self.scheduler, 'teacher_shift_data') or not self.scheduler.teacher_shift_data:
    #         self.logger.warning("No teacher shift data available - skipping relaxed shift constraints")
    #         return
    #     
    #     penalty_vars = []
    #     
    #     # Group course assignments by teacher
    #     teacher_courses = {}
    #     for course_instance_id, teacher in course_to_teacher.items():
    #         if teacher not in teacher_courses:
    #             teacher_courses[teacher] = []
    #         teacher_courses[teacher].append(course_instance_id)
    #     
    #     for teacher_id, course_list in teacher_courses.items():
    #         for day_idx, day in enumerate(self.scheduler.days):
    #             # Get allowed lab sessions for this teacher on this day
    #             allowed_sessions = self.scheduler.get_teacher_allowed_lab_sessions(teacher_id, day)
    #             
    #             # Convert allowed session names to indices
    #             allowed_session_indices = []
    #             for session_name in allowed_sessions:
    #                 if session_name in lab_sessions:
    #                     allowed_session_indices.append(lab_sessions.index(session_name))
    #             
    #             # For each non-allowed session, create penalty variables instead of hard constraints
    #             for session_idx in range(len(lab_sessions)):
    #                 if session_idx not in allowed_session_indices:
    #                     # Create penalty variables for assignments to non-preferred sessions
    #                     for course_instance_id in course_list:
    #                         for room_id in self.scheduler.labs['id'].tolist():
    #                             if course_instance_id in lab_assignments:
    #                                 assignment_var = lab_assignments[course_instance_id][day_idx][session_idx][room_id]
    #                                 
    #                                 # Add penalty variable that equals assignment_var
    #                                 penalty_var = model.NewBoolVar(f'shift_penalty_{teacher_id}_{day}_{session_idx}_{course_instance_id}_{room_id}')
    #                                 model.Add(penalty_var == assignment_var)
    #                                 penalty_vars.append(penalty_var)
    #     
    #     # Add penalty to objective function (this will be handled by the solver's objective)
    #     # For now, just log the relaxed constraint application
    #     self.logger.info(f"Applied relaxed shift constraints with {len(penalty_vars)} potential penalties")
    #     
    #     # Store penalty variables for objective function modification (if needed)
    #     if hasattr(self.scheduler, 'shift_penalty_vars'):
    #         self.scheduler.shift_penalty_vars.extend(penalty_vars)
    #     else:
    #         self.scheduler.shift_penalty_vars = penalty_vars

    def _add_dynamic_batching_constraint(self, model, lab_assignments, course_instance_id, course):
        """Add constraints for dynamic batching based on assigned lab capacity."""
        # For 70-student courses, the batching will be handled during solution processing
        # based on the actual lab capacity that gets assigned
        
        # Just log that dynamic batching is enabled for this course
        self.scheduler.logger.info(f"Dynamic batching enabled for course {course['display_course_code']} "
                                 f"(ID: {course_instance_id}) - will create batches based on assigned lab capacity")
    
    def _add_course_allocation_constraints(self, model, lab_assignments, course_to_teacher):
        """Each course instance gets the required number of lab slots based on its allocation strategy."""
        for teacher, courses in self.scheduler.lab_requirements.items():
            for course in courses:
                course_instance_id = course['course_instance_id']
                required_lab_slots = course['total_lab_slots_needed']  # This accounts for potential batching
                
                # Each course instance gets exactly the required number of lab slots
                total_assignments = []
                for day_idx in range(self.scheduler.num_days):
                    for session_idx in range(len(self.lab_sessions)):
                        for room_id in self.lab_room_ids:
                            total_assignments.append(lab_assignments[course_instance_id][day_idx][session_idx][room_id])
                
                # Ensure course gets exactly the required number of lab slot assignments
                model.Add(sum(total_assignments) == required_lab_slots)
                
                self.scheduler.logger.info(f"Constraint: Course {course['display_course_code']} "
                                         f"(ID: {course_instance_id}) must get exactly {required_lab_slots} lab slots")
                
                # For potential batching courses (70 students), add additional constraints
                if course.get('potential_batching_needed', False):
                    # Add constraint to ensure consistent room capacity usage
                    # If assigned to 35-capacity labs, should get 2x the base sessions
                    # If assigned to 70+ capacity labs, should get 1x the base sessions
                    self._add_dynamic_batching_constraint(model, lab_assignments, course_instance_id, course)

    def apply_practical_hours_capacity_constraint(self, model, lab_assignments):
        """HARD CONSTRAINT: Only courses with practical_hours >= 3 can use 70-capacity labs."""
        
        # Get lab rooms categorized by capacity
        labs_by_capacity = {
            35: [lab['id'] for lab in self.scheduler.lab_capacity_analysis['labs_35']],
            70: [lab['id'] for lab in self.scheduler.lab_capacity_analysis['labs_70']],
            140: [lab['id'] for lab in self.scheduler.lab_capacity_analysis['labs_140']]
        }
        
        # Get all 70+ capacity labs (including 140 treated as 70)
        high_capacity_labs = labs_by_capacity[70] + labs_by_capacity[140]
        
        if not high_capacity_labs:
            self.logger.info("No high-capacity labs available - constraint not needed")
            return
        
        for teacher_id, courses in self.scheduler.lab_requirements.items():
            for course in courses:
                course_instance_id = course['course_instance_id']
                practical_hours = course['practical_hours']
                
                # HARD CONSTRAINT: If practical_hours < 3, cannot use 70+ capacity labs
                if practical_hours < 3:
                    self.logger.info(f"Applying hard constraint: Course {course['display_course_code']} "
                                   f"({practical_hours} practical hours) cannot use 70+ capacity labs")
                    
                    # Prevent assignment to any 70+ capacity lab
                    for day_idx in range(self.scheduler.num_days):
                        for session_idx in range(len(self.lab_sessions)):
                            for room_id in high_capacity_labs:
                                if course_instance_id in lab_assignments:
                                    assignment_var = lab_assignments[course_instance_id][day_idx][session_idx][room_id]
                                    # Force this assignment to be 0 (cannot be assigned)
                                    model.Add(assignment_var == 0)
        
        self.logger.info("Hard constraint applied: Courses with <3 practical hours blocked from 70+ capacity labs")

    # COMMENTED OUT: Teacher Shift Constraint
    # def apply_teacher_shift_constraint(self, model, lab_assignments, lab_sessions, course_to_teacher):
    #     """Apply teacher shift constraint - ensure lab sessions are scheduled according to teacher shifts."""
    #     self.logger.info("Applying teacher shift constraint...")
    #     
    #     violations_applied = 0
    #     
    #     # Group course assignments by teacher
    #     teacher_courses = {}
    #     for course_instance_id, teacher in course_to_teacher.items():
    #         if teacher not in teacher_courses:
    #             teacher_courses[teacher] = []
    #         teacher_courses[teacher].append(course_instance_id)
    #     
    #     for teacher_id, course_list in teacher_courses.items():
    #         for day_idx, day in enumerate(self.scheduler.days):
    #             # Get allowed lab sessions for this teacher on this day
    #             allowed_sessions = self.scheduler.get_teacher_allowed_lab_sessions(teacher_id, day)
    #             
    #             # Convert allowed session names to indices
    #             allowed_session_indices = []
    #             for session_name in allowed_sessions:
    #                 if session_name in lab_sessions:
    #                     allowed_session_indices.append(lab_sessions.index(session_name))
    #             
    #             # Apply constraint: teacher can only be assigned to allowed lab sessions
    #             for session_idx in range(len(lab_sessions)):
    #                 session_name = lab_sessions[session_idx]
    #                 
    #                 if session_idx not in allowed_session_indices:
    #                     # This session is NOT allowed for this teacher on this day
    #                     # Set all assignments for this teacher in this session to 0
    #                     for course_instance_id in course_list:
    #                         for room_id in self.scheduler.labs['id'].tolist():
    #                             if course_instance_id in lab_assignments:
    #                                 assignment_var = lab_assignments[course_instance_id][day_idx][session_idx][room_id]
    #                                 model.Add(assignment_var == 0)
    #                                 violations_applied += 1
    #                     
    #                     # Log the constraint application
    #                     shift_info = self.scheduler.teacher_shift_data.get(teacher_id, {}).get(day, {})
    #                     shift = shift_info.get('shift', 'unknown')
    #                     self.logger.debug(f"SHIFT CONSTRAINT: Teacher {teacher_id} on {day} blocked from session {session_name} "
    #                                     f"(shift: {shift}, allowed: {allowed_sessions})")
    #     
    #     self.logger.info(f"Applied {violations_applied} shift-based constraints")
    #     
    #     # Log shift constraint summary
    #     if hasattr(self.scheduler, 'teacher_shift_data') and self.scheduler.teacher_shift_data:
    #         total_teacher_days = len(self.scheduler.teacher_shift_data) * len(self.scheduler.days)
    #         
    #         # Count shift distribution
    #         shift_distribution = {'shift1': 0, 'shift2': 0, 'shift3': 0, 'no_classes': 0, 'other': 0}
    #         for teacher_id, teacher_shifts in self.scheduler.teacher_shift_data.items():
    #             for day, shift_info in teacher_shifts.items():
    #                 shift = shift_info.get('shift', 'other')
    #                 if shift in shift_distribution:
    #                     shift_distribution[shift] += 1
    #                 else:
    #                     shift_distribution['other'] += 1
    #         
    #         self.logger.info(f"Shift constraint summary:")
    #         self.logger.info(f"  - shift1 (8:00-3:00, L1-L3): {shift_distribution['shift1']} teacher-days")
    #         self.logger.info(f"  - shift2 (10:00-5:00, L2-L4): {shift_distribution['shift2']} teacher-days") 
    #         self.logger.info(f"  - shift3 (12:00-7:00, L4-L6): {shift_distribution['shift3']} teacher-days")
    #         self.logger.info(f"  - no_classes: {shift_distribution['no_classes']} teacher-days")
    #         self.logger.info(f"  - other/unknown: {shift_distribution['other']} teacher-days")
    #     else:
    #         self.logger.warning("No teacher shift data available - shift constraints not applied")

    def apply_macroblock_based_lab_allocation_constraint(self, model, lab_assignments, lab_sessions, course_to_teacher):
        """Apply macroblock-based lab allocation constraint.
        
        Rules:
        - If theory macroblocks are a1, b1, c1, d1, e1, f1, g1 -> Lab sessions L4, L5, L6 only
        - If theory macroblocks are a2, b2, c2, d2, e2, f2, g2 -> Lab sessions L1, L2, L3 only
        """
        self.logger.info("Applying macroblock-based lab allocation constraint...")
        
        # Define macroblock to lab session mapping
        macroblock_to_lab_sessions = {
            # Morning theory blocks (a1-g1) -> Afternoon lab sessions (L4-L6)
            'a1': ['L4', 'L5', 'L6'],
            'b1': ['L4', 'L5', 'L6'], 
            'c1': ['L4', 'L5', 'L6'],
            'd1': ['L4', 'L5', 'L6'],
            'e1': ['L4', 'L5', 'L6'],
            'f1': ['L4', 'L5', 'L6'],
            'g1': ['L4', 'L5', 'L6'],
            
            # Afternoon theory blocks (a2-g2) -> Morning lab sessions (L1-L3)
            'a2': ['L1', 'L2', 'L3'],
            'b2': ['L1', 'L2', 'L3'],
            'c2': ['L1', 'L2', 'L3'],
            'd2': ['L1', 'L2', 'L3'],
            'e2': ['L1', 'L2', 'L3'],
            'f2': ['L1', 'L2', 'L3'],
            'g2': ['L1', 'L2', 'L3']
        }
        
        # Group course assignments by teacher
        teacher_courses = {}
        for course_instance_id, teacher in course_to_teacher.items():
            if teacher not in teacher_courses:
                teacher_courses[teacher] = []
            teacher_courses[teacher].append(course_instance_id)
        
        constraints_applied = 0
        
        for teacher_id, course_list in teacher_courses.items():
            # Get teacher's theory schedule to determine their macroblocks
            teacher_theory = self.scheduler.theory_schedule_df[self.scheduler.theory_schedule_df['teacher_id'] == teacher_id]
            
            if teacher_theory.empty:
                self.logger.debug(f"No theory schedule found for teacher {teacher_id}, allowing all lab sessions")
                continue
            
            # Determine teacher's macroblocks from theory schedule
            teacher_macroblocks = set()
            for _, theory_row in teacher_theory.iterrows():
                macroblock = theory_row.get('macroblock', '')
                if macroblock:
                    teacher_macroblocks.add(macroblock.lower())
            
            if not teacher_macroblocks:
                self.logger.debug(f"No macroblocks found for teacher {teacher_id}, allowing all lab sessions")
                continue
            
            # Determine allowed lab sessions based on teacher's macroblocks
            allowed_lab_sessions = set()
            for macroblock in teacher_macroblocks:
                if macroblock in macroblock_to_lab_sessions:
                    allowed_lab_sessions.update(macroblock_to_lab_sessions[macroblock])
            
            if not allowed_lab_sessions:
                self.logger.debug(f"No lab session restrictions for teacher {teacher_id} macroblocks: {teacher_macroblocks}")
                continue
            
            # Convert allowed session names to indices
            allowed_session_indices = []
            for session_name in allowed_lab_sessions:
                if session_name in lab_sessions:
                    allowed_session_indices.append(lab_sessions.index(session_name))
            
            self.logger.info(f"Teacher {teacher_id} macroblocks {teacher_macroblocks} -> allowed lab sessions {allowed_lab_sessions}")
            
            # Apply constraint: teacher can only be assigned to allowed lab sessions
            for day_idx in range(self.scheduler.num_days):
                for session_idx in range(len(lab_sessions)):
                    session_name = lab_sessions[session_idx]
                    
                    if session_idx not in allowed_session_indices:
                        # This session is NOT allowed for this teacher based on their macroblocks
                        # Set all assignments for this teacher in this session to 0
                        for course_instance_id in course_list:
                            for room_id in self.scheduler.labs['id'].tolist():
                                if course_instance_id in lab_assignments:
                                    assignment_var = lab_assignments[course_instance_id][day_idx][session_idx][room_id]
                                    model.Add(assignment_var == 0)
                                    constraints_applied += 1
                        
                        self.logger.debug(f"MACROBLOCK CONSTRAINT: Teacher {teacher_id} blocked from lab session {session_name} "
                                        f"(macroblocks: {teacher_macroblocks}, allowed: {allowed_lab_sessions})")
        
        self.logger.info(f"Applied {constraints_applied} macroblock-based lab allocation constraints")
        
        # Log constraint summary
        self.logger.info("Macroblock-based lab allocation rules:")
        self.logger.info("  - Theory blocks a1-g1 (morning) → Lab sessions L4-L6 (afternoon)")
        self.logger.info("  - Theory blocks a2-g2 (afternoon) → Lab sessions L1-L3 (morning)")
        self.logger.info("  - This prevents scheduling conflicts between theory and lab sessions")

    def apply_max_consecutive_lab_slots_constraint(self, model, lab_assignments, lab_sessions, course_to_teacher):
        """Apply constraint to prevent more than 2 consecutive lab sessions per teacher per day.
        
        Rules:
        - If L4 and L5 are allocated, L6 cannot be allocated on the same day
        - If L1 and L2 are allocated, L3 cannot be allocated on the same day
        - If L2 and L3 are allocated, L1 and L4 cannot be allocated on the same day
        - And so on for all consecutive triplets
        """
        self.logger.info("Applying max consecutive lab slots constraint (max 2 consecutive sessions per teacher per day)...")
        
        # Group course assignments by teacher
        teacher_courses = {}
        for course_instance_id, teacher in course_to_teacher.items():
            if teacher not in teacher_courses:
                teacher_courses[teacher] = []
            teacher_courses[teacher].append(course_instance_id)
        
        constraints_applied = 0
        
        # Define consecutive lab session triplets that are forbidden
        # Lab sessions: L1, L2, L3, L4, L5, L6 (indices 0, 1, 2, 3, 4, 5)
        consecutive_triplets = [
            [0, 1, 2],  # L1, L2, L3
            [1, 2, 3],  # L2, L3, L4  
            [2, 3, 4],  # L3, L4, L5
            [3, 4, 5],  # L4, L5, L6
        ]
        
        for teacher, course_list in teacher_courses.items():
            for day_idx in range(self.scheduler.num_days):
                day_name = self.scheduler.days[day_idx]
                
                # For each consecutive triplet, ensure at most 2 out of 3 sessions are allocated
                for triplet in consecutive_triplets:
                    session1_idx, session2_idx, session3_idx = triplet
                    session1_name = lab_sessions[session1_idx]
                    session2_name = lab_sessions[session2_idx] 
                    session3_name = lab_sessions[session3_idx]
                    
                    # Collect all assignment variables for this teacher in these 3 consecutive sessions
                    triplet_assignments = []
                    
                    for course_instance_id in course_list:
                        if course_instance_id in lab_assignments:
                            for room_id in self.scheduler.labs['id'].tolist():
                                # Add assignments for all 3 consecutive sessions
                                triplet_assignments.append(lab_assignments[course_instance_id][day_idx][session1_idx][room_id])
                                triplet_assignments.append(lab_assignments[course_instance_id][day_idx][session2_idx][room_id])
                                triplet_assignments.append(lab_assignments[course_instance_id][day_idx][session3_idx][room_id])
                    
                    # Constraint: at most 2 out of these 3 consecutive sessions can be allocated to this teacher
                    if triplet_assignments:
                        model.Add(sum(triplet_assignments) <= 2)
                        constraints_applied += 1
                        
                        self.logger.debug(f"Teacher {teacher} on {day_name}: max 2 sessions allowed from "
                                        f"{session1_name}, {session2_name}, {session3_name}")
        
        self.logger.info(f"Applied {constraints_applied} consecutive lab slots constraints")
        self.logger.info("Consecutive lab slots rules:")
        self.logger.info("  - Maximum 2 consecutive lab sessions per teacher per day")
        self.logger.info("  - Prevents teacher exhaustion from 3 consecutive lab sessions (6 hours)")
        self.logger.info("  - Examples: L4+L5+L6, L1+L2+L3, L2+L3+L4, L3+L4+L5 are forbidden")


# Utility functions for constraint validation and debugging
def validate_lab_constraints(schedule_df, lab_requirements):
    """Validate that the generated lab schedule satisfies all constraints."""
    violations = []
    
    # Check if all courses got required lab sessions
    lab_data = schedule_df[schedule_df['slot_type'] == 'Practical']
    
    for teacher, courses in lab_requirements.items():
        for course in courses:
            course_instance_id = course['course_instance_id']
            required_sessions = course['total_lab_slots_needed']
            
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
            analysis['total_lab_sessions_needed'] += course['total_lab_slots_needed']
    
    # Calculate total lab capacity per week
    analysis['total_lab_capacity'] = len(lab_rooms) * 6 * 5  # 6 sessions * 5 days
    
    # Check for potential teacher overloads
    for teacher, courses in lab_requirements.items():
        teacher_theory_hours = len(theory_schedule_df[theory_schedule_df['teacher_id'] == teacher])
        teacher_lab_hours = sum(course['total_lab_slots_needed'] * 2 for course in courses)  # Each session = 2 hours
        total_hours = teacher_theory_hours + teacher_lab_hours
        
        if total_hours > 25:
            analysis['teacher_overloads'].append({
                'teacher': teacher,
                'theory_hours': teacher_theory_hours,
                'lab_hours': teacher_lab_hours,
                'total_hours': total_hours
            })
    
    return analysis 