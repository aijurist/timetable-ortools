import os
import pandas as pd
import numpy as np
import logging
import json
from datetime import datetime
from collections import defaultdict
from itertools import combinations
from ortools.sat.python import cp_model

class TheoryScheduler:
    """Schedules theory sessions after lab sessions, avoiding conflicts with existing lab schedule."""
    
    def __init__(self, course_file, room_file, lab_schedule_data=None):
        """Initialize the theory scheduler with course and room data."""
        self.logger = logging.getLogger(__name__)
        
        # Load the data
        self.courses_df = pd.read_csv(course_file)
        self.rooms_df = pd.read_csv(room_file)
        
        # Store existing lab schedule to avoid conflicts
        self.lab_schedule_data = lab_schedule_data or []
        
        # Setup time structure (matching reference implementation)
        self.days = ["tuesday", "wed", "thur", "fri", "sat"]  # Excluding Monday
        self.num_days = len(self.days)
        
        # Theory time slots (11 slots per day - 1 hour each)
        self.theory_time_slots = [
            "8:00 - 8:50", "9:00 - 9:50", "10:00 - 10:50", "11:00 - 11:50",
            "12:00 - 12:50", "1:00 - 1:50", "2:00 - 2:50", "3:00 - 3:50", 
            "4:00 - 4:50", "5:00 - 5:50", "6:00 - 6:50"
        ]
        
        # Lab sessions mapping for conflict detection
        self.lab_sessions = {
            'L1': {'slots': [0, 1], 'time_range': '8:00 - 9:40'},
            'L2': {'slots': [2, 3], 'time_range': '9:50 - 11:30'},
            'L3': {'slots': [4, 5], 'time_range': '11:50 - 1:30'},
            'L4': {'slots': [6, 7], 'time_range': '1:50 - 3:30'},
            'L5': {'slots': [8, 9], 'time_range': '3:50 - 5:30'},
            'L6': {'slots': [10, 11], 'time_range': '5:30 - 7:10'}
        }
        
        # Process theory classrooms (excluding labs)
        self.theory_rooms = self.rooms_df[self.rooms_df['is_lab'] == 0]
        self.theory_room_ids = self.theory_rooms['id'].tolist()
        
        # Process teacher-course assignments for theory
        self.process_theory_courses()
        
        # Parse existing lab schedule for conflict detection
        self.parse_lab_schedule()
        
        # Create output directory
        self.output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
                                      'output', 
                                      f'theory_schedule_{datetime.now().strftime("%Y%m%d_%H%M%S")}')
        os.makedirs(self.output_dir, exist_ok=True)
    
    def process_theory_courses(self):
        """Process the teacher-course assignments from the CSV data, focusing on courses with theory hours."""
        # Extract unique teachers
        self.teachers = self.courses_df['teacher_id'].unique()
        self.num_teachers = len(self.teachers)
        self.logger.info(f"Processing {self.num_teachers} teachers for theory scheduling")
        
        # Create a mapping of teachers to their theory courses
        self.teacher_course_assignments = {}
        for _, row in self.courses_df.iterrows():
            teacher_id = row['teacher_id']
            course_id = row['course_id']
            
            if teacher_id not in self.teacher_course_assignments:
                self.teacher_course_assignments[teacher_id] = []
            
            # Create a unique identifier for each course instance
            course_instance_id = str(row['id'])
            
            self.teacher_course_assignments[teacher_id].append({
                'id': course_instance_id,
                'course_id': course_id,
                'course_code': row['course_code'],
                'course_name': row['course_name'],
                'course_type': row['course_type'],
                'theory_hours': int(row.get('lecture_hours', 0)),
                'student_count': int(row['student_count']),
                'semester': row.get('semester', 1),
                'course_dept': row.get('course_dept', 'Computer Science & Engineering')
            })
        
        # Calculate theory requirements for each teacher and course
        self.calculate_theory_requirements()
        
        # Create course groups using SAME logic as lab scheduler (Hall's theorem distribution)
        self.create_course_groups()
    
    def calculate_theory_requirements(self):
        """Calculate theory requirements based on theory hours."""
        self.theory_requirements = {}
        self.course_to_teacher = {}  # Maps course instance to teacher
        
        for teacher_id, assignments in self.teacher_course_assignments.items():
            # Filter only courses with theory hours
            theory_courses = [a for a in assignments if a['theory_hours'] > 0]
            
            if theory_courses:
                self.theory_requirements[teacher_id] = []
                
                for course in theory_courses:
                    course_instance_id = course['id']
                    theory_hours = course['theory_hours']
                    student_count = course['student_count']
                    
                    # Map course instance to teacher
                    self.course_to_teacher[course_instance_id] = teacher_id
                    
                    # Calculate required theory sessions (each session = 1 theory hour)
                    required_sessions = theory_hours
                    
                    self.theory_requirements[teacher_id].append({
                        'course_instance_id': course_instance_id,
                        'course_code': course['course_code'],
                        'theory_hours': theory_hours,
                        'students_per_instance': student_count,
                        'required_sessions': required_sessions
                    })
        
        # Log theory requirements
        total_theory_slots = sum(sum(c['required_sessions'] for c in courses) 
                               for teacher, courses in self.theory_requirements.items())
        self.logger.info(f"Calculated theory requirements: {total_theory_slots} total theory slots needed")
        self.logger.info(f"Teachers with theory courses: {len(self.theory_requirements)}")
    
    def create_course_groups(self):
        """Create course groups based on semester and department for Hall's theorem distribution (SAME as lab scheduler)."""
        self.logger.info("Creating course groups for Hall's theorem distribution (theory scheduling)...")
        
        # Create course groups by department and semester
        self.course_groups = self._create_course_groups_by_dept_semester()
        
        # Create instance-group mapping for CSV output
        self.instance_group_mapping = {}
        self._create_instance_group_mapping()
        
        self.logger.info("Course grouping completed successfully for theory scheduling")
        self.logger.info("✅ TEACHER UNIQUENESS CONSTRAINT: Each teacher appears at most once per group per semester")
        self.logger.info("✅ HALL'S THEOREM COMPLIANCE: Optimized for maximum student choice while respecting teacher constraints")
    
    def _create_course_groups_by_dept_semester(self):
        """Group course instances by department and semester with Hall's theorem optimization (SAME as lab scheduler)."""
        # Collect ALL course instances by department and semester (theory + lab)
        dept_sem_courses = defaultdict(list)
        total_instances = 0
        
        # Gather ALL course instances from the original CSV data, not just theory courses
        all_instances = []
        for _, row in self.courses_df.iterrows():
            teacher_id = row['teacher_id']
            course_instance_id = str(row['id'])
            
            instance_with_teacher = {
                'id': course_instance_id,
                'teacher_id': teacher_id,
                'course_id': row['course_id'],
                'course_code': row['course_code'],
                'course_name': row['course_name'],
                'course_type': row['course_type'],
                'theory_hours': int(row.get('lecture_hours', 0)),
                'student_count': int(row['student_count']),
                'semester': row.get('semester', 1),
                'course_dept': row.get('course_dept', 'Computer Science & Engineering'),
                'is_theory_course': int(row.get('lecture_hours', 0)) > 0
            }
            all_instances.append(instance_with_teacher)
            total_instances += 1
        
        self.logger.info(f"Processing {total_instances} total course instances (theory + lab) across {len(self.teachers)} teachers")
        
        # Group by department and semester
        for instance in all_instances:
            dept = instance.get('course_dept', 'Computer Science & Engineering')
            semester = instance.get('semester', 3)  # Default to semester 3
            dept_sem_courses[(dept, semester)].append(instance)
        
        # Log department-semester distribution
        for (dept, semester), instances in dept_sem_courses.items():
            self.logger.info(f"Dept: {dept}, Semester: {semester}: {len(instances)} instances")
        
        # Create groups for each department and semester
        course_groups = {}
        for (dept, semester), courses in dept_sem_courses.items():
            if courses:  # Skip if there are no courses
                course_groups[(dept, semester)] = self._distribute_course_instances(courses, dept, semester)
        
        return course_groups
    
    def _distribute_course_instances(self, courses, dept, semester):
        """Distribute course instances across groups with Hall's theorem optimization (SAME as lab scheduler)."""
        total_instances = len(courses)
        
        if total_instances == 0:
            return []
        
        # Enhanced instance analysis for ALL courses (theory + lab)
        theory_courses = [inst for inst in courses if inst['theory_hours'] > 0]
        lab_courses = [inst for inst in courses if inst.get('is_theory_course', False) == False]
        
        # Calculate dynamic student capacity
        course_instance_counts = {}
        for inst in courses:
            course_code = inst['course_code']
            if course_code not in course_instance_counts:
                course_instance_counts[course_code] = 0
            course_instance_counts[course_code] += 1
        
        max_instances_per_course = max(course_instance_counts.values()) if course_instance_counts else 1
        dynamic_student_capacity = max_instances_per_course * 70
        
        instance_analysis = {
            'total_instances': total_instances,
            'theory_instances_count': len(theory_courses),
            'lab_instances_count': len(lab_courses),
            'unique_courses': len(set(inst['course_code'] for inst in courses)),
            'unique_theory_courses': len(set(inst['course_code'] for inst in theory_courses)),
            'unique_lab_courses': len(set(inst['course_code'] for inst in lab_courses)),
            'unique_teachers': len(set(inst['teacher_id'] for inst in courses)),
            'total_theory_hours': sum(inst['theory_hours'] for inst in courses),
            'avg_student_count': sum(inst.get('student_count', 70) for inst in courses) / total_instances if total_instances > 0 else 0,
            'max_instances_per_course': max_instances_per_course,
            'dynamic_student_capacity': dynamic_student_capacity,
            'course_instance_counts': course_instance_counts
        }
        
        self.logger.info(f"Hall-based analysis for {dept} Semester {semester} (Theory Scheduling):")
        self.logger.info(f"  {instance_analysis['total_instances']} total instances")
        self.logger.info(f"  {instance_analysis['theory_instances_count']} theory instances, {instance_analysis['lab_instances_count']} lab instances")
        self.logger.info(f"  {instance_analysis['unique_courses']} unique courses ({instance_analysis['unique_theory_courses']} theory + {instance_analysis['unique_lab_courses']} lab)")
        self.logger.info(f"  {instance_analysis['unique_teachers']} unique teachers")
        self.logger.info(f"  Total theory workload: {instance_analysis['total_theory_hours']} hours")
        
        # CRITICAL: Number of groups = Number of unique courses in the semester
        unique_course_codes = instance_analysis['unique_courses']
        num_groups = unique_course_codes
        
        self.logger.info(f"Creating {num_groups} groups (one per unique course: {unique_course_codes}) for theory scheduling")
        self.logger.info(f"📋 CONSTRAINT: Each course limited to maximum 2 of the {num_groups} groups for optimal choice balance")
        
        # Initialize groups
        groups = [[] for _ in range(num_groups)]
        
        # Build course-teacher bipartite graph for Hall's theorem (ALL courses)
        course_to_teachers = {}
        teacher_to_courses = {}
        
        for instance in courses:  # Use ALL courses, not just theory
            course_code = instance['course_code']
            teacher_id = instance['teacher_id']
            
            if course_code not in course_to_teachers:
                course_to_teachers[course_code] = set()
            course_to_teachers[course_code].add(teacher_id)
            
            if teacher_id not in teacher_to_courses:
                teacher_to_courses[teacher_id] = set()
            teacher_to_courses[teacher_id].add(course_code)
        
        # Group instances by course code (ALL courses)
        course_instances = {}
        for instance in courses:  # Use ALL courses, not just theory
            course_code = instance['course_code']
            if course_code not in course_instances:
                course_instances[course_code] = []
            course_instances[course_code].append(instance)
        
        # Sort courses by number of teachers (ascending) for better Hall satisfaction
        sorted_courses = sorted(course_to_teachers.keys(), 
                              key=lambda c: len(course_to_teachers[c]))
        
        # Pre-allocate courses to groups with 2-group-per-course limit
        pre_allocation = [set() for _ in range(num_groups)]
        course_group_assignments = {}  # Track which groups each course is assigned to
        next_group = 0
        
        for course_code in sorted_courses:
            instances = course_instances[course_code].copy()
            # CONSTRAINT: Each course can appear in at most 2 groups
            max_groups_per_course = min(2, len(instances), num_groups)
            
            course_group_assignments[course_code] = []
            
            for _ in range(max_groups_per_course):
                pre_allocation[next_group].add(course_code)
                course_group_assignments[course_code].append(next_group)
                next_group = (next_group + 1) % num_groups
        
        # Execute the distribution with strict teacher uniqueness
        for group_idx, target_courses in enumerate(pre_allocation):
            used_teachers = set()
            
            # First, fulfill the pre-allocation plan with teacher uniqueness enforcement
            for course_code in target_courses:
                instances = [inst for inst in course_instances[course_code] if inst not in [i for g in groups for i in g]]
                
                if not instances:
                    continue
                
                # Find an instance with a teacher not yet used in ANY group (global uniqueness)
                instance_assigned = False
                for instance in instances:
                    teacher_id = instance['teacher_id']
                    
                    # Check if teacher is already used in THIS group
                    if teacher_id not in used_teachers:
                        groups[group_idx].append(instance)
                        used_teachers.add(teacher_id)
                        instance_assigned = True
                        break
                
                if not instance_assigned:
                    self.logger.debug(f"Could not pre-allocate {course_code} to Group {group_idx + 1} - no teacher available that isn't already in this group")
        
        # Distribute remaining instances
        remaining_instances = []
        for course_code, instances in course_instances.items():
            for instance in instances:
                if instance not in [i for g in groups for i in g]:
                    remaining_instances.append(instance)
        
        self.logger.info(f"Distributing {len(remaining_instances)} remaining instances...")
        
        # Track teacher assignments to ensure uniqueness constraint
        teacher_group_assignments = {}
        for group_idx, group in enumerate(groups):
            for instance in group:
                teacher_id = instance['teacher_id']
                if teacher_id not in teacher_group_assignments:
                    teacher_group_assignments[teacher_id] = set()
                teacher_group_assignments[teacher_id].add(group_idx)
        
        successfully_assigned = 0
        
        for instance in remaining_instances:
            teacher_id = instance['teacher_id']
            course_code = instance['course_code']
            
            # Find valid groups for this teacher and course
            valid_groups = []
            
            # Get groups where this course is already assigned (from pre-allocation)
            course_assigned_groups = course_group_assignments.get(course_code, [])
            
            for group_idx in range(num_groups):
                # CONSTRAINT 1: Teacher cannot be in this group already
                teacher_conflict = teacher_id in {inst['teacher_id'] for inst in groups[group_idx]}
                
                # CONSTRAINT 2: Course can only be in groups where it was pre-allocated (max 2 groups)
                course_allowed = group_idx in course_assigned_groups
                
                if not teacher_conflict and course_allowed:
                    valid_groups.append(group_idx)
            
            if valid_groups:
                # Find the best valid group for this instance
                best_group = min(valid_groups, key=lambda g: len(groups[g]))
                groups[best_group].append(instance)
                successfully_assigned += 1
                
                # Update teacher assignments tracking
                if teacher_id not in teacher_group_assignments:
                    teacher_group_assignments[teacher_id] = set()
                teacher_group_assignments[teacher_id].add(best_group)
        
        self.logger.info(f"Successfully assigned: {successfully_assigned} instances")
        
        # Remove empty groups
        non_empty_groups = [group for group in groups if group]
        return non_empty_groups
    
    def _create_instance_group_mapping(self):
        """Create mapping from course instances to their groups."""
        total_mapped_instances = 0
        
        for (dept, semester), groups in self.course_groups.items():
            for group_idx, group in enumerate(groups):
                for instance in group:
                    instance_id = instance['id']
                    teacher_id = instance['teacher_id']
                    course_code = instance['course_code']
                    
                    self.instance_group_mapping[instance_id] = {
                        'group_name': f"{dept}_S{semester}_G{group_idx + 1}",
                        'group_index': group_idx + 1,
                        'department': dept,
                        'semester': semester,
                        'teacher_id': teacher_id,
                        'course_code': course_code,
                        'is_theory_course': instance.get('is_theory_course', False),
                        'theory_hours': instance.get('theory_hours', 0)
                    }
                    total_mapped_instances += 1
        
        self.logger.info(f"Instance-group mapping created: {total_mapped_instances} instances mapped to groups (theory + lab)")
    
    def get_group_info_for_course_instance(self, course_instance_id):
        """Get group information for a specific course instance."""
        if course_instance_id in self.instance_group_mapping:
            return self.instance_group_mapping[course_instance_id]
        else:
            # Fallback for instances not found in mapping
            self.logger.warning(f"Instance {course_instance_id} not found in group mapping")
            return {
                'group_name': 'Unassigned',
                'group_index': 0,
                'department': 'Unknown',
                'semester': 0,
                'teacher_id': 'Unknown',
                'course_code': 'Unknown'
            }
    
    def parse_lab_schedule(self):
        """Parse existing lab schedule to identify occupied time slots for conflict detection."""
        self.occupied_slots = {}  # Format: {teacher_id: {day: [time_slots]}}
        self.occupied_rooms = {}  # Format: {room_id: {day: [time_slots]}}
        
        if not self.lab_schedule_data:
            self.logger.info("No existing lab schedule data provided")
            return
        
        for lab_session in self.lab_schedule_data:
            teacher_id = lab_session.get('teacher_id')
            room_id = lab_session.get('room_id')
            day = lab_session.get('day')
            session_name = lab_session.get('session_name', '')
            
            if teacher_id and day and session_name:
                # Get the time slots for this lab session
                if session_name in self.lab_sessions:
                    time_slots = self.lab_sessions[session_name]['slots']
                    
                    # Mark teacher as occupied
                    if teacher_id not in self.occupied_slots:
                        self.occupied_slots[teacher_id] = {}
                    if day not in self.occupied_slots[teacher_id]:
                        self.occupied_slots[teacher_id][day] = []
                    self.occupied_slots[teacher_id][day].extend(time_slots)
                    
                    # Mark room as occupied if it's a theory room too
                    if room_id in self.theory_room_ids:
                        if room_id not in self.occupied_rooms:
                            self.occupied_rooms[room_id] = {}
                        if day not in self.occupied_rooms[room_id]:
                            self.occupied_rooms[room_id][day] = []
                        self.occupied_rooms[room_id][day].extend(time_slots)
        
        # Remove duplicates and log conflicts
        for teacher_id in self.occupied_slots:
            for day in self.occupied_slots[teacher_id]:
                self.occupied_slots[teacher_id][day] = list(set(self.occupied_slots[teacher_id][day]))
        
        for room_id in self.occupied_rooms:
            for day in self.occupied_rooms[room_id]:
                self.occupied_rooms[room_id][day] = list(set(self.occupied_rooms[room_id][day]))
        
        total_conflicts = sum(len(days.get(day, [])) for days in self.occupied_slots.values() for day in self.days)
        self.logger.info(f"Parsed lab schedule: {len(self.occupied_slots)} teachers with {total_conflicts} occupied time slots")
    
    def generate_theory_schedule(self):
        """Generate the theory schedule using OR-Tools CP-SAT solver."""
        self.logger.info("Starting theory schedule generation...")
        
        if not self.theory_requirements:
            self.logger.warning("No theory requirements found. All courses may be lab-only.")
            return False
        
        # Check constraint feasibility
        if not self.analyze_theory_feasibility():
            self.logger.error("Theory scheduling is not feasible with current requirements and constraints")
            return False
        
        # Create the CP-SAT model
        model = cp_model.CpModel()
        
        # Define assignment variables
        # theory_assignments[course_instance_id][day][time_slot][room_id] = 1 if assigned
        theory_assignments = {}
        
        # Create variables for each course that needs theory time
        for teacher_id, courses in self.theory_requirements.items():
            for course in courses:
                course_instance_id = course['course_instance_id']
                
                if course_instance_id not in theory_assignments:
                    theory_assignments[course_instance_id] = {}
                    
                    for day_idx in range(self.num_days):
                        theory_assignments[course_instance_id][day_idx] = {}
                        
                        for slot_idx in range(len(self.theory_time_slots)):
                            theory_assignments[course_instance_id][day_idx][slot_idx] = {}
                            
                            for room_id in self.theory_room_ids:
                                theory_assignments[course_instance_id][day_idx][slot_idx][room_id] = model.NewBoolVar(
                                    f'theory_{course_instance_id}_day_{day_idx}_slot_{slot_idx}_room_{room_id}')
        
        # Apply constraints
        self.apply_theory_constraints(model, theory_assignments)
        
        # Add optimization objective
        self.add_theory_objective(model, theory_assignments)
        
        # Create the solver and solve the model
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 300  # 5 minutes time limit
        solver.parameters.num_search_workers = 8  # Use 8 threads for theory scheduling
        solver.parameters.log_search_progress = True
        
        self.logger.info("Solving the theory scheduling model...")
        status = solver.Solve(model)
        
        if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
            self.logger.info(f"{'🎯 OPTIMAL' if status == cp_model.OPTIMAL else '✅ FEASIBLE'} theory solution found!")
            
            # Extract the theory schedule
            theory_schedule = self.extract_theory_schedule(solver, theory_assignments)
            
            # Save the schedule
            self.save_theory_schedule(theory_schedule)
            
            return True
        else:
            self.logger.error(f"❌ No theory solution found. Status: {solver.StatusName(status)}")
            return False
    
    def analyze_theory_feasibility(self):
        """Analyze if the theory requirements can be satisfied."""
        total_theory_slots_needed = sum(sum(c['required_sessions'] for c in courses) 
                                       for teacher, courses in self.theory_requirements.items())
        
        # Calculate total theory capacity per week
        total_theory_rooms = len(self.theory_room_ids)
        theory_slots_per_week = len(self.theory_time_slots) * self.num_days  # 11 slots * 5 days = 55
        total_theory_capacity = total_theory_rooms * theory_slots_per_week
        
        self.logger.info(f"Theory constraint feasibility analysis:")
        self.logger.info(f"  - Total theory slots needed: {total_theory_slots_needed}")
        self.logger.info(f"  - Total theory rooms: {total_theory_rooms}")
        self.logger.info(f"  - Theory slots per week: {theory_slots_per_week}")
        self.logger.info(f"  - Total theory capacity: {total_theory_capacity}")
        self.logger.info(f"  - Utilization: {total_theory_slots_needed / total_theory_capacity * 100:.1f}%")
        
        if total_theory_slots_needed > total_theory_capacity:
            self.logger.error(f"INFEASIBLE: Need {total_theory_slots_needed} slots but only have {total_theory_capacity} capacity")
            return False
        
        return True
    
    def apply_theory_constraints(self, model, theory_assignments):
        """Apply theory scheduling constraints."""
        self.logger.info("Applying theory scheduling constraints...")
        
        # Constraint 1: Each course gets required number of theory sessions
        self.apply_theory_requirements_constraint(model, theory_assignments)
        
        # Constraint 2: Room can only have one course at a time
        self.apply_room_single_assignment_constraint(model, theory_assignments)
        
        # Constraint 3: Teacher cannot be in multiple places at once
        self.apply_teacher_conflict_constraint(model, theory_assignments)
        
        # Constraint 4: Avoid conflicts with existing lab schedule
        self.apply_lab_conflict_constraint(model, theory_assignments)
        
        # Constraint 5: Group-based scheduling constraints (SAME as lab scheduler)
        self.apply_group_based_scheduling_constraint(model, theory_assignments)
        
        self.logger.info("Theory constraints applied successfully with group-based logic")
    
    def apply_theory_requirements_constraint(self, model, theory_assignments):
        """Ensure each course gets the required number of theory sessions."""
        for teacher, courses in self.theory_requirements.items():
            for course in courses:
                course_instance_id = course['course_instance_id']
                required_sessions = course['required_sessions']
                
                if course_instance_id in theory_assignments:
                    # Count total assignments for this course instance
                    total_assignments = []
                    
                    for day_idx in range(self.num_days):
                        for slot_idx in range(len(self.theory_time_slots)):
                            for room_id in self.theory_room_ids:
                                total_assignments.append(theory_assignments[course_instance_id][day_idx][slot_idx][room_id])
                    
                    # Constraint: exactly required number of sessions
                    model.Add(sum(total_assignments) == required_sessions)
    
    def apply_room_single_assignment_constraint(self, model, theory_assignments):
        """Prevent theory room double-booking."""
        for room_id in self.theory_room_ids:
            for day_idx in range(self.num_days):
                for slot_idx in range(len(self.theory_time_slots)):
                    # Each theory room can have at most one course per slot
                    room_vars = []
                    for course_instance_id in theory_assignments.keys():
                        room_vars.append(theory_assignments[course_instance_id][day_idx][slot_idx][room_id])
                    model.Add(sum(room_vars) <= 1)
    
    def apply_teacher_conflict_constraint(self, model, theory_assignments):
        """Prevent teacher from being in multiple theory classes simultaneously."""
        for teacher_id in self.teachers:
            for day_idx in range(self.num_days):
                for slot_idx in range(len(self.theory_time_slots)):
                    teacher_assignments = []
                    
                    for course_instance_id in theory_assignments.keys():
                        if course_instance_id in self.course_to_teacher and self.course_to_teacher[course_instance_id] == teacher_id:
                            for room_id in self.theory_room_ids:
                                teacher_assignments.append(theory_assignments[course_instance_id][day_idx][slot_idx][room_id])
                    
                    if len(teacher_assignments) > 1:
                        model.Add(sum(teacher_assignments) <= 1)
    
    def apply_lab_conflict_constraint(self, model, theory_assignments):
        """Prevent conflicts with existing lab schedule."""
        conflicts_applied = 0
        
        # Teacher conflicts: teachers with lab sessions cannot have theory at the same time
        for teacher_id, occupied_days in self.occupied_slots.items():
            for day in occupied_days:
                if day in self.days:
                    day_idx = self.days.index(day)
                    occupied_slots = occupied_days[day]
                    
                    for slot_idx in occupied_slots:
                        if slot_idx < len(self.theory_time_slots):
                            # Teacher cannot have theory session at this time slot
                            teacher_assignments = []
                            
                            for course_instance_id in theory_assignments.keys():
                                if course_instance_id in self.course_to_teacher and self.course_to_teacher[course_instance_id] == teacher_id:
                                    for room_id in self.theory_room_ids:
                                        teacher_assignments.append(theory_assignments[course_instance_id][day_idx][slot_idx][room_id])
                            
                            if teacher_assignments:
                                model.Add(sum(teacher_assignments) == 0)
                                conflicts_applied += 1
        
        self.logger.info(f"Applied {conflicts_applied} lab-theory conflict constraints")
    
    def apply_group_based_scheduling_constraint(self, model, theory_assignments):
        """Apply group-based scheduling constraints with teacher conflict prevention and same-group parallelization (SAME as lab scheduler)."""
        self.logger.info("Applying group-based teacher time conflict constraint with same-group parallelization (theory scheduling)...")
        
        # Get group information for all course instances
        course_group_info = {}
        for course_instance_id in theory_assignments.keys():
            group_info = self.get_group_info_for_course_instance(course_instance_id)
            course_group_info[course_instance_id] = {
                'semester': group_info['semester'],
                'group_index': group_info['group_index'],
                'department': group_info['department'],
                'teacher_id': self.course_to_teacher.get(course_instance_id)
            }
        
        # Group course instances by semester and department
        semester_groups = {}
        for course_instance_id, info in course_group_info.items():
            dept_sem_key = (info['department'], info['semester'])
            if dept_sem_key not in semester_groups:
                semester_groups[dept_sem_key] = {}
            
            group_idx = info['group_index']
            if group_idx not in semester_groups[dept_sem_key]:
                semester_groups[dept_sem_key][group_idx] = []
            
            semester_groups[dept_sem_key][group_idx].append(course_instance_id)
        
        constraints_applied = 0
        
        # CONSTRAINT 1: Teacher can teach at most ONE theory session at any time (global constraint)
        for teacher_id in self.teachers:
            for day_idx in range(self.num_days):
                for slot_idx in range(len(self.theory_time_slots)):
                    teacher_assignments = []
                    
                    for course_instance_id in theory_assignments.keys():
                        if course_group_info[course_instance_id]['teacher_id'] == teacher_id:
                            for room_id in self.theory_room_ids:
                                teacher_assignments.append(theory_assignments[course_instance_id][day_idx][slot_idx][room_id])
                    
                    if len(teacher_assignments) > 1:
                        model.Add(sum(teacher_assignments) <= 1)
                        constraints_applied += 1
        
        # CONSTRAINT 2: Same semester, different groups CANNOT overlap (ENHANCED)
        for (dept, semester), groups in semester_groups.items():
            group_indices = list(groups.keys())
            
            # Filter out invalid groups (group_index 0 means unassigned/invalid)
            valid_group_indices = [g for g in group_indices if g > 0]
            
            if len(valid_group_indices) <= 1:
                continue  # Skip if only one or no valid groups
            
            # For each time slot, ensure at most ONE group from this semester can be scheduled
            for day_idx in range(self.num_days):
                for slot_idx in range(len(self.theory_time_slots)):
                    # Collect all assignments for this semester at this time slot
                    group_assignments_by_group = {}
                    
                    for group_idx in valid_group_indices:
                        group_assignments_by_group[group_idx] = []
                        course_instances = groups[group_idx]
                        
                        for course_instance_id in course_instances:
                            for room_id in self.theory_room_ids:
                                group_assignments_by_group[group_idx].append(
                                    theory_assignments[course_instance_id][day_idx][slot_idx][room_id]
                                )
                    
                    # Create binary variables for each group being active in this time slot
                    group_active_vars = {}
                    for group_idx in valid_group_indices:
                        group_active_vars[group_idx] = model.NewBoolVar(
                            f'theory_group_active_{dept}_S{semester}_G{group_idx}_day{day_idx}_slot{slot_idx}'
                        )
                    
                    # Constraint: At most one group can be active in this time slot
                    if len(group_active_vars) > 1:
                        model.Add(sum(group_active_vars.values()) <= 1)
                        constraints_applied += 1
                    
                    # Link group activity to actual assignments
                    for group_idx in valid_group_indices:
                        group_assignments = group_assignments_by_group[group_idx]
                        if group_assignments:
                            # If any assignment in this group is made, the group is active
                            for assignment in group_assignments:
                                model.AddImplication(assignment, group_active_vars[group_idx])
                            
                            # If the group is not active, no assignments can be made
                            model.Add(sum(group_assignments) <= len(group_assignments) * group_active_vars[group_idx])
            
            self.logger.info(f"Applied strict non-overlap constraints for {dept} Semester {semester}: {len(valid_group_indices)} valid groups (theory)")
        
        # CONSTRAINT 3: Each course instance can only be assigned to one room per time slot
        for course_instance_id in theory_assignments.keys():
            for day_idx in range(self.num_days):
                for slot_idx in range(len(self.theory_time_slots)):
                    slot_assignments = []
                    for room_id in self.theory_room_ids:
                        slot_assignments.append(theory_assignments[course_instance_id][day_idx][slot_idx][room_id])
                    
                    if len(slot_assignments) > 1:
                        model.Add(sum(slot_assignments) <= 1)
                        constraints_applied += 1
        
        # NEW CONSTRAINT 4: Encourage same-group courses to run in parallel (SAME as lab scheduler)
        self.apply_same_group_parallelization_preference(model, theory_assignments, semester_groups)
        
        self.logger.info(f"Group-based theory scheduling constraints applied successfully: {constraints_applied} constraints")
        self.logger.info("✅ ENHANCED THEORY CONSTRAINT RULES:")
        self.logger.info("  1. Same group courses ENCOURAGED to overlap/run parallel (students take different courses)")
        self.logger.info("  2. Different groups in same semester CANNOT overlap (strict enforcement)")
        self.logger.info("  3. Different semesters CAN overlap (different student populations)")
        self.logger.info("  4. Teachers cannot teach multiple theory sessions simultaneously (global constraint)")
        self.logger.info("  5. At most ONE group per semester can be active in any time slot")
        self.logger.info("  6. Same-group parallelization preference added to theory objective")
    
    def apply_same_group_parallelization_preference(self, model, theory_assignments, semester_groups):
        """Apply preferences to encourage same-group courses to run in parallel (theory scheduling)."""
        self.logger.info("Applying same-group parallelization preferences for theory scheduling...")
        
        parallelization_bonuses = []
        
        for (dept, semester), groups in semester_groups.items():
            for group_idx, course_instances in groups.items():
                if group_idx <= 0 or len(course_instances) <= 1:
                    continue  # Skip invalid groups or groups with only one course
                
                # For each time slot, encourage multiple courses from the same group to run together
                for day_idx in range(self.num_days):
                    for slot_idx in range(len(self.theory_time_slots)):
                        # Collect assignments for all courses in this group at this time slot
                        group_course_assignments = []
                        
                        for course_instance_id in course_instances:
                            for room_id in self.theory_room_ids:
                                group_course_assignments.append(
                                    theory_assignments[course_instance_id][day_idx][slot_idx][room_id]
                                )
                        
                        if len(group_course_assignments) >= 2:
                            # Create a bonus variable for having multiple courses from same group running together
                            parallel_bonus = model.NewBoolVar(
                                f'theory_parallel_bonus_{dept}_S{semester}_G{group_idx}_day{day_idx}_slot{slot_idx}'
                            )
                            
                            # Bonus activates when 2 or more courses from same group run in parallel
                            model.Add(sum(group_course_assignments) >= 2).OnlyEnforceIf(parallel_bonus)
                            model.Add(sum(group_course_assignments) <= 1).OnlyEnforceIf(parallel_bonus.Not())
                            
                            parallelization_bonuses.append(parallel_bonus)
        
        # Store parallelization bonuses for use in objective function
        if not hasattr(self, 'parallelization_bonuses'):
            self.parallelization_bonuses = []
        self.parallelization_bonuses.extend(parallelization_bonuses)
        
        self.logger.info(f"Applied {len(parallelization_bonuses)} same-group parallelization preferences for theory")
        self.logger.info("Same-group theory courses are now encouraged to run simultaneously when possible")
    
    def add_theory_objective(self, model, theory_assignments):
        """Add optimization objective for theory scheduling with same-group parallelization."""
        objective_terms = []
        
        # Objective 1: Prefer earlier time slots (morning preference)
        morning_bonus = []
        for course_instance_id in theory_assignments.keys():
            for day_idx in range(self.num_days):
                for slot_idx in range(min(6, len(self.theory_time_slots))):  # First 6 slots (morning)
                    for room_id in self.theory_room_ids:
                        morning_bonus.append(theory_assignments[course_instance_id][day_idx][slot_idx][room_id])
        
        # Objective 2: Same-group parallelization bonuses (high weight)
        if hasattr(self, 'parallelization_bonuses') and self.parallelization_bonuses:
            objective_terms.extend([term * 4 for term in self.parallelization_bonuses])  # High weight for same-group parallelization
        
        # Objective 3: Morning preference (lower weight)
        if morning_bonus:
            objective_terms.extend([term * 1 for term in morning_bonus])  # Lower weight for morning preference
        
        # Set the combined objective
        if objective_terms:
            model.Maximize(sum(objective_terms))
            self.logger.info(f"Theory objective set with {len(objective_terms)} terms")
            weight_info = "Theory objective weights: Morning preference (+1)"
            if hasattr(self, 'parallelization_bonuses') and self.parallelization_bonuses:
                weight_info += f", Same-group parallelization (+4, {len(self.parallelization_bonuses)} terms)"
            self.logger.info(weight_info)
        else:
            self.logger.warning("No theory objective terms found")
    
    def extract_theory_schedule(self, solver, theory_assignments):
        """Extract the theory schedule from the solver solution."""
        theory_schedule = []
        
        for course_instance_id in theory_assignments.keys():
            teacher_id = self.course_to_teacher[course_instance_id]
            
            # Find the course details
            course_details = None
            for course in self.theory_requirements[teacher_id]:
                if course['course_instance_id'] == course_instance_id:
                    course_details = course
                    break
            
            if not course_details:
                continue
            
            for day_idx in range(self.num_days):
                for slot_idx in range(len(self.theory_time_slots)):
                    for room_id in self.theory_room_ids:
                        if solver.Value(theory_assignments[course_instance_id][day_idx][slot_idx][room_id]) == 1:
                            # Get room details
                            room_row = self.theory_rooms[self.theory_rooms['id'] == room_id].iloc[0]
                            
                            # Get teacher details
                            teacher_row = self.courses_df[self.courses_df['teacher_id'] == teacher_id].iloc[0]
                            
                            time_slot = self.theory_time_slots[slot_idx]
                            
                            # Get group information for this course instance (SAME as lab scheduler)
                            group_info = self.get_group_info_for_course_instance(course_instance_id)
                            
                            theory_schedule.append({
                                'day': self.days[day_idx],
                                'time_slot': time_slot,
                                'slot_index': slot_idx,
                                'course_instance_id': course_instance_id,
                                'course_code': course_details['course_code'],
                                'theory_hours': int(course_details['theory_hours']),
                                'teacher_id': teacher_id,
                                'teacher_name': f"{teacher_row.get('first_name', '')} {teacher_row.get('last_name', '')}".strip(),
                                'staff_code': teacher_row.get('staff_code', ''),
                                'room_id': int(room_id),
                                'room_number': room_row['room_number'],
                                'block': room_row.get('block', 'Unknown'),
                                'capacity': int(room_row['room_max_cap']),
                                'student_count': int(course_details['students_per_instance']),
                                'course_type': 'Theory',
                                'semester': teacher_row.get('semester', 1),
                                'department': teacher_row.get('course_dept', 'Computer Science & Engineering'),
                                # Group information for Hall's theorem distribution (SAME as lab scheduler)
                                'group_name': group_info['group_name'],
                                'group_index': group_info['group_index'],
                                'group_department': group_info['department'],
                                'group_semester': group_info['semester']
                            })
        
        return theory_schedule
    
    def save_theory_schedule(self, theory_schedule):
        """Save the theory schedule to files."""
        # Convert to DataFrame
        theory_df = pd.DataFrame(theory_schedule)
        
        # Save as CSV
        csv_path = os.path.join(self.output_dir, 'theory_schedule.csv')
        theory_df.to_csv(csv_path, index=False)
        self.logger.info(f"Theory schedule saved to {csv_path}")
        
        # Save as JSON (with proper type conversion for numpy types)
        json_path = os.path.join(self.output_dir, 'theory_schedule.json')
        with open(json_path, 'w') as f:
            # Convert numpy types to native Python types for JSON serialization
            def convert_numpy_types(obj):
                if isinstance(obj, np.integer):
                    return int(obj)
                elif isinstance(obj, np.floating):
                    return float(obj)
                elif isinstance(obj, np.ndarray):
                    return obj.tolist()
                elif isinstance(obj, dict):
                    return {k: convert_numpy_types(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [convert_numpy_types(item) for item in obj]
                return obj
            
            theory_schedule_serializable = convert_numpy_types(theory_schedule)
            json.dump(theory_schedule_serializable, f, indent=2)
        self.logger.info(f"Theory schedule saved to {json_path}")
        
        # Generate summary
        self.generate_theory_summary(theory_schedule)
    
    def generate_theory_summary(self, theory_schedule):
        """Generate a summary of the theory schedule."""
        summary_path = os.path.join(self.output_dir, 'theory_schedule_summary.txt')
        
        with open(summary_path, 'w') as f:
            f.write("Theory Schedule Summary\n")
            f.write("======================\n\n")
            
            f.write(f"Total scheduled theory sessions: {len(theory_schedule)}\n")
            
            # Sessions by day
            day_counts = {}
            for item in theory_schedule:
                day = item['day']
                day_counts[day] = day_counts.get(day, 0) + 1
            
            f.write("\nTheory sessions by day:\n")
            for day in self.days:
                f.write(f"  {day.capitalize()}: {day_counts.get(day, 0)}\n")
            
            # Teachers with theory assignments
            teacher_sessions = {}
            for item in theory_schedule:
                teacher = item['teacher_id']
                teacher_sessions[teacher] = teacher_sessions.get(teacher, 0) + 1
            
            f.write(f"\nTeachers with theory assignments: {len(teacher_sessions)}\n")
            
            # Courses with theory assignments
            course_assignments = {}
            for item in theory_schedule:
                course = item['course_code']
                course_assignments[course] = course_assignments.get(course, 0) + 1
            
            f.write(f"\nCourses with theory assignments:\n")
            for course, count in sorted(course_assignments.items()):
                f.write(f"  {course}: {count} sessions\n")
        
        self.logger.info(f"Theory summary saved to {summary_path}") 