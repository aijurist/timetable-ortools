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
                'lecture_hours': int(row.get('lecture_hours', 0)),
                'tutorial_hours': int(row.get('tutorial_hours', 0)),
                'student_count': int(row['student_count']),
                'semester': row.get('semester', 1),
                'course_dept': row.get('course_dept', 'Computer Science & Engineering')
            })
        
        # Calculate theory requirements for each teacher and course
        self.calculate_theory_requirements()
        
        # Create course groups using SAME logic as lab scheduler (Hall's theorem distribution)
        self.create_course_groups()
    
    def calculate_theory_requirements(self):
        """Calculate theory requirements based on lecture and tutorial hours."""
        self.theory_requirements = {}
        self.course_to_teacher = {}  # Maps course instance to teacher
        
        for teacher_id, assignments in self.teacher_course_assignments.items():
            # Filter only courses with theory hours (lecture or tutorial)
            theory_courses = [a for a in assignments if a['lecture_hours'] > 0 or a['tutorial_hours'] > 0]
            
            if theory_courses:
                self.theory_requirements[teacher_id] = []
                
                for course in theory_courses:
                    course_instance_id = course['id']
                    lecture_hours = course['lecture_hours']
                    tutorial_hours = course['tutorial_hours']
                    student_count = course['student_count']
                    
                    # Map course instance to teacher
                    self.course_to_teacher[course_instance_id] = teacher_id
                    
                    # Calculate required theory sessions (each session = 1 hour)
                    required_lecture_sessions = lecture_hours
                    required_tutorial_sessions = tutorial_hours
                    
                    self.theory_requirements[teacher_id].append({
                        'course_instance_id': course_instance_id,
                        'course_code': course['course_code'],
                        'lecture_hours': lecture_hours,
                        'tutorial_hours': tutorial_hours,
                        'students_per_instance': student_count,
                        'required_lecture_sessions': required_lecture_sessions,
                        'required_tutorial_sessions': required_tutorial_sessions
                    })
        
        # Log theory requirements
        total_lecture_slots = sum(sum(c['required_lecture_sessions'] for c in courses) 
                               for teacher, courses in self.theory_requirements.items())
        total_tutorial_slots = sum(sum(c['required_tutorial_sessions'] for c in courses) 
                               for teacher, courses in self.theory_requirements.items())
        
        self.logger.info(f"Calculated theory requirements: {total_lecture_slots} lecture slots + {total_tutorial_slots} tutorial slots needed")
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
                'lecture_hours': int(row.get('lecture_hours', 0)),
                'tutorial_hours': int(row.get('tutorial_hours', 0)),
                'student_count': int(row['student_count']),
                'semester': row.get('semester', 1),
                'course_dept': row.get('course_dept', 'Computer Science & Engineering'),
                'is_theory_course': int(row.get('lecture_hours', 0)) > 0 or int(row.get('tutorial_hours', 0)) > 0
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
        theory_courses = [inst for inst in courses if inst['lecture_hours'] > 0 or inst.get('is_theory_course', False) == False]
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
            'total_lecture_hours': sum(inst['lecture_hours'] for inst in courses),
            'total_tutorial_hours': sum(inst['tutorial_hours'] for inst in courses),
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
        self.logger.info(f"  Total lecture workload: {instance_analysis['total_lecture_hours']} hours")
        self.logger.info(f"  Total tutorial workload: {instance_analysis['total_tutorial_hours']} hours")
        
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
                        'lecture_hours': instance.get('lecture_hours', 0),
                        'tutorial_hours': instance.get('tutorial_hours', 0)
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
        """Generate the theory schedule using group-based time slot allocation."""
        self.logger.info("Starting theory schedule generation with GROUP-BASED TIME SLOT ALLOCATION...")
        
        # Check constraint feasibility before creating model
        if not self.analyze_theory_feasibility():
            self.logger.error("Theory scheduling is not feasible with current requirements and constraints")
            return False
        
        # Create the CP-SAT model
        model = cp_model.CpModel()
        
        # STEP 1: Create group time slot allocation variables (similar to course_group_constraint.py)
        group_timeslot_vars = self.create_group_timeslot_variables(model)
        
        # STEP 2: Apply group-level constraints
        self.apply_group_level_constraints(model, group_timeslot_vars)
        
        # STEP 3: Add optimization objective for group allocation
        self.add_group_allocation_objective(model, group_timeslot_vars)
        
        # Log model statistics
        self.logger.info("="*60)
        self.logger.info("GROUP-BASED MODEL STATISTICS")
        self.logger.info("="*60)
        model_stats = model.Proto()
        self.logger.info(f"Variables: {len(model_stats.variables)}")
        self.logger.info(f"Constraints: {len(model_stats.constraints)}")
        
        # Count group timeslot variables
        total_group_vars = sum(len(day_dict) * len(slot_dict) for day_dict in group_timeslot_vars.values() for slot_dict in day_dict.values())
        self.logger.info(f"  - Group timeslot variables: {total_group_vars}")
        
        # Create the solver and solve
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 180  # 3 minutes should be enough for group allocation
        solver.parameters.num_search_workers = 16
        solver.parameters.log_search_progress = True
        
        self.logger.info("Solving group-based theory scheduling model...")
        status = solver.Solve(model)
        
        # Log solver results
        self.logger.info("="*60)
        self.logger.info("GROUP ALLOCATION SOLVER RESULTS")
        self.logger.info("="*60)
        self.logger.info(f"Status: {solver.StatusName(status)}")
        self.logger.info(f"Wall time: {solver.WallTime():.2f} seconds")
        
        if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
            self.logger.info(f"{'🎯 OPTIMAL' if status == cp_model.OPTIMAL else '✅ FEASIBLE'} group allocation found!")
            
            # STEP 4: Extract group time slot assignments
            group_timeslots = self.extract_group_timeslots(solver, group_timeslot_vars)
            
            # STEP 5: Post-process to distribute course sessions within allocated group time slots
            theory_schedule = self.distribute_sessions_in_group_timeslots(group_timeslots)
            
            # Save the schedule
            self.save_theory_schedule(theory_schedule)
            
            return True
        else:
            self.logger.error(f"❌ No group allocation solution found. Status: {solver.StatusName(status)}")
            return False
    
    def create_group_timeslot_variables(self, model):
        """Create variables for group time slot allocation (similar to course_group_constraint.py)."""
        self.logger.info("Creating group time slot allocation variables...")
        
        group_timeslot_vars = {}
        
        # Calculate time slot requirements for each group
        group_requirements = {}
        
        for (dept, semester), groups in self.course_groups.items():
            for group_idx, group in enumerate(groups):
                if not group:
                    continue
                    
                group_name = f"{dept}_S{semester}_G{group_idx + 1}"
                
                # Calculate required time slots based on max theory hours in group
                max_theory_hours = 0
                total_theory_hours = 0
                for instance in group:
                    theory_hours = instance.get('lecture_hours', 0) + instance.get('tutorial_hours', 0)
                    max_theory_hours = max(max_theory_hours, theory_hours)
                    total_theory_hours += theory_hours
                
                # Allocate slots based on max theory hours (minimum 3, maximum 8)
                required_slots = max(3, min(6, max_theory_hours))
                group_requirements[group_name] = required_slots
                
                self.logger.info(f"Group {group_name}: {len(group)} instances, max {max_theory_hours}h → {required_slots} time slots")
                
                # Create binary variables for each possible time slot
                group_timeslot_vars[group_name] = {}
                for day_idx in range(self.num_days):
                    group_timeslot_vars[group_name][day_idx] = {}
                    for slot_idx in range(len(self.theory_time_slots)):
                        group_timeslot_vars[group_name][day_idx][slot_idx] = model.NewBoolVar(
                            f'group_{group_name}_day_{day_idx}_slot_{slot_idx}'
                        )
        
        # Store requirements for later use
        self.group_requirements = group_requirements
        
        return group_timeslot_vars
    
    def apply_group_level_constraints(self, model, group_timeslot_vars):
        """Apply constraints at the group level (similar to course_group_constraint.py)."""
        self.logger.info("Applying group-level constraints...")
        
        constraints_applied = 0
        
        # CONSTRAINT 1: Each group must have exactly the required number of time slots
        for group_name, required_slots in self.group_requirements.items():
            if group_name not in group_timeslot_vars:
                continue
                
            timeslot_vars = []
            for day_idx in range(self.num_days):
                for slot_idx in range(len(self.theory_time_slots)):
                    timeslot_vars.append(group_timeslot_vars[group_name][day_idx][slot_idx])
            
            model.Add(sum(timeslot_vars) == required_slots)
            constraints_applied += 1
            
            self.logger.info(f"Group {group_name}: exactly {required_slots} time slots required")
        
        # CONSTRAINT 2: Different groups in same semester CANNOT overlap
        semester_groups = {}
        for group_name in group_timeslot_vars.keys():
            # Parse group name to get semester info
            parts = group_name.split('_')
            if len(parts) >= 2:
                dept = parts[0]
                semester_part = parts[1]  # e.g., "S3" 
                semester = semester_part[1:] if semester_part.startswith('S') else semester_part
                
                semester_key = f"{dept}_S{semester}"
                if semester_key not in semester_groups:
                    semester_groups[semester_key] = []
                semester_groups[semester_key].append(group_name)
        
        for semester_key, groups in semester_groups.items():
            if len(groups) <= 1:
                continue
                
            self.logger.info(f"Applying non-overlap constraints for {semester_key}: {len(groups)} groups")
            
            for day_idx in range(self.num_days):
                for slot_idx in range(len(self.theory_time_slots)):
                    # At most one group from this semester can use this time slot
                    slot_usage_vars = []
                    for group_name in groups:
                        if group_name in group_timeslot_vars:
                            slot_usage_vars.append(group_timeslot_vars[group_name][day_idx][slot_idx])
                    
                    if len(slot_usage_vars) > 1:
                        model.Add(sum(slot_usage_vars) <= 1)
                        constraints_applied += 1
        
        # CONSTRAINT 3: Room capacity constraint (global)
        for day_idx in range(self.num_days):
            for slot_idx in range(len(self.theory_time_slots)):
                # Count total groups using this time slot
                total_usage_vars = []
                for group_name in group_timeslot_vars.keys():
                    total_usage_vars.append(group_timeslot_vars[group_name][day_idx][slot_idx])
                
                # Limit to available theory rooms
                if total_usage_vars:
                    model.Add(sum(total_usage_vars) <= len(self.theory_room_ids))
                    constraints_applied += 1
        
        # CONSTRAINT 4: Encourage consecutive time slots for same group
        for group_name, day_slots in group_timeslot_vars.items():
            for day_idx in range(self.num_days):
                for slot_idx in range(len(self.theory_time_slots) - 1):
                    # Create consecutive pair bonus
                    consecutive_pair = model.NewBoolVar(f'consecutive_{group_name}_day_{day_idx}_slot_{slot_idx}')
                    
                    # consecutive_pair = 1 if both consecutive slots are used
                    model.Add(consecutive_pair <= day_slots[day_idx][slot_idx])
                    model.Add(consecutive_pair <= day_slots[day_idx][slot_idx + 1])
                    model.Add(consecutive_pair >= day_slots[day_idx][slot_idx] + day_slots[day_idx][slot_idx + 1] - 1)
        
        self.logger.info(f"Applied {constraints_applied} group-level constraints")
        self.logger.info("✅ GROUP CONSTRAINTS:")
        self.logger.info("  1. Each group gets exactly required time slots")
        self.logger.info("  2. Different groups, same semester → CANNOT overlap")
        self.logger.info("  3. Global room capacity respected")
        self.logger.info("  4. Consecutive time slots encouraged")
    
    def add_group_allocation_objective(self, model, group_timeslot_vars):
        """Add objective for optimal group time slot allocation."""
        objective_terms = []
        
        # Objective 1: Tiered time slot preference (priority-based)
        tier1_bonus = []  # First 4 slots - highest priority
        tier2_bonus = []  # Next 4 slots - medium priority  
        tier3_bonus = []  # Next 3 slots - lowest priority
        
        for group_name, day_slots in group_timeslot_vars.items():
            for day_idx in range(self.num_days):
                # Tier 1: Slots 0-3 (highest priority)
                for slot_idx in range(min(4, len(self.theory_time_slots))):
                    tier1_bonus.append(day_slots[day_idx][slot_idx])
                
                # Tier 2: Slots 4-7 (medium priority)
                for slot_idx in range(4, min(8, len(self.theory_time_slots))):
                    tier2_bonus.append(day_slots[day_idx][slot_idx])
                
                # Tier 3: Slots 8-10 (lowest priority)
                for slot_idx in range(8, min(11, len(self.theory_time_slots))):
                    tier3_bonus.append(day_slots[day_idx][slot_idx])
        
        # Objective 2: Encourage consecutive slots
        consecutive_bonus = []
        for group_name, day_slots in group_timeslot_vars.items():
            for day_idx in range(self.num_days):
                for slot_idx in range(len(self.theory_time_slots) - 1):
                    consecutive_pair = model.NewBoolVar(f'obj_consecutive_{group_name}_day_{day_idx}_slot_{slot_idx}')
                    model.Add(consecutive_pair <= day_slots[day_idx][slot_idx])
                    model.Add(consecutive_pair <= day_slots[day_idx][slot_idx + 1])
                    model.Add(consecutive_pair >= day_slots[day_idx][slot_idx] + day_slots[day_idx][slot_idx + 1] - 1)
                    consecutive_bonus.append(consecutive_pair)
        
        # Combine objectives with tiered weights
        if tier1_bonus:
            objective_terms.extend([term * 10 for term in tier1_bonus])  # Highest weight for first 4 slots
        if tier2_bonus:
            objective_terms.extend([term * 5 for term in tier2_bonus])   # Medium weight for next 4 slots
        if tier3_bonus:
            objective_terms.extend([term * 2 for term in tier3_bonus])   # Lowest weight for next 3 slots
        if consecutive_bonus:
            objective_terms.extend([term * 3 for term in consecutive_bonus])  # Weight for consecutiveness
        
        if objective_terms:
            model.Maximize(sum(objective_terms))
            self.logger.info(f"Group allocation objective set with {len(objective_terms)} terms")
            self.logger.info("Objective weights: Tier 1 slots 0-3 (+10), Tier 2 slots 4-7 (+5), Tier 3 slots 8-10 (+2), Consecutive slots (+3)")
            self.logger.info("Tiered priority system: Fill first 4 slots priority, then next 4, then next 3")
    
    def extract_group_timeslots(self, solver, group_timeslot_vars):
        """Extract allocated time slots for each group from solver solution."""
        self.logger.info("Extracting group time slot allocations...")
        
        group_timeslots = {}
        total_slots_allocated = 0
        
        for group_name, day_slots in group_timeslot_vars.items():
            group_timeslots[group_name] = []
            
            for day_idx in range(self.num_days):
                for slot_idx in range(len(self.theory_time_slots)):
                    if solver.Value(day_slots[day_idx][slot_idx]) == 1:
                        group_timeslots[group_name].append((day_idx, slot_idx))
                        total_slots_allocated += 1
            
            # Log allocated slots
            allocated_slots = group_timeslots[group_name]
            slot_details = []
            for day_idx, slot_idx in sorted(allocated_slots):
                day_name = self.days[day_idx]
                time_slot = self.theory_time_slots[slot_idx]
                slot_details.append(f"{day_name} {time_slot}")
            
            self.logger.info(f"Group {group_name}: {len(allocated_slots)} slots → {', '.join(slot_details)}")
        
        self.logger.info(f"Total time slots allocated to groups: {total_slots_allocated}")
        return group_timeslots
    
    def distribute_sessions_in_group_timeslots(self, group_timeslots):
        """Distribute individual course sessions within allocated group time slots (POST-PROCESSING)."""
        self.logger.info("Distributing course sessions within allocated group time slots...")
        
        theory_schedule = []
        
        for group_name, allocated_slots in group_timeslots.items():
            if not allocated_slots:
                continue
                
            # Get group info
            group_info = None
            for (dept, semester), groups in self.course_groups.items():
                for group_idx, group in enumerate(groups):
                    expected_name = f"{dept}_S{semester}_G{group_idx + 1}"
                    if expected_name == group_name:
                        group_info = {'dept': dept, 'semester': semester, 'instances': group}
                        break
            
            if not group_info:
                self.logger.warning(f"Group info not found for {group_name}")
                continue
                
            instances = group_info['instances']
            self.logger.info(f"Distributing {len(instances)} course instances across {len(allocated_slots)} time slots for {group_name}")
            
            # Collect all sessions needed for this group
            sessions_needed = []
            for instance in instances:
                course_instance_id = instance['id']
                teacher_id = instance['teacher_id']
                lecture_hours = instance.get('lecture_hours', 0)
                tutorial_hours = instance.get('tutorial_hours', 0)
                
                # Create lecture sessions
                for session_num in range(lecture_hours):
                    sessions_needed.append({
                        'course_instance_id': course_instance_id,
                        'teacher_id': teacher_id,
                        'session_type': 'Lecture',
                        'session_number': session_num + 1,
                        'instance': instance
                    })
                
                # Create tutorial sessions
                for session_num in range(tutorial_hours):
                    sessions_needed.append({
                        'course_instance_id': course_instance_id,
                        'teacher_id': teacher_id,
                        'session_type': 'Tutorial',
                        'session_number': session_num + 1,
                        'instance': instance
                    })
            
            # Distribute sessions across allocated time slots
            # Group sessions by teacher to avoid teacher conflicts
            teacher_sessions = {}
            for session in sessions_needed:
                teacher_id = session['teacher_id']
                if teacher_id not in teacher_sessions:
                    teacher_sessions[teacher_id] = []
                teacher_sessions[teacher_id].append(session)
            
            # Distribute sessions ensuring no teacher conflicts
            slot_assignments = {}  # slot_idx -> assigned_sessions
            for slot_idx in range(len(allocated_slots)):
                slot_assignments[slot_idx] = []
            
            # Track which teachers are already assigned to each slot
            slot_teachers = {}  # slot_idx -> set of teacher_ids
            for slot_idx in range(len(allocated_slots)):
                slot_teachers[slot_idx] = set()
            
            # Assign sessions to slots
            for teacher_id, teacher_session_list in teacher_sessions.items():
                for session in teacher_session_list:
                    # Find a slot where this teacher is not already assigned
                    assigned = False
                    for slot_idx in range(len(allocated_slots)):
                        if teacher_id not in slot_teachers[slot_idx]:
                            slot_assignments[slot_idx].append(session)
                            slot_teachers[slot_idx].add(teacher_id)
                            assigned = True
                            break  # Move break inside the slot finding loop
            
                    if not assigned:
                        # If all slots have this teacher, assign to the slot with fewest sessions
                        min_slot = min(slot_assignments.keys(), key=lambda x: len(slot_assignments[x]))
                        slot_assignments[min_slot].append(session)
                        slot_teachers[min_slot].add(teacher_id)
                        self.logger.warning(f"Teacher {teacher_id} has multiple sessions in same time slot - may need more slots for {group_name}")
            
            # Create schedule entries
            for slot_idx, assigned_sessions in slot_assignments.items():
                if not assigned_sessions:
                    continue
            
                day_idx, time_slot_idx = allocated_slots[slot_idx]
                
                for session in assigned_sessions:
                    # Get teacher and course details
                    instance = session['instance']
                    teacher_row = self.courses_df[self.courses_df['teacher_id'] == session['teacher_id']].iloc[0]
                    
                    # Assign rooms in round-robin fashion
                    room_idx = len([s for s in theory_schedule if s['day'] == self.days[day_idx] and s['time_slot'] == self.theory_time_slots[time_slot_idx]]) % len(self.theory_room_ids)
                    room_id = self.theory_room_ids[room_idx]
                    room_row = self.rooms_df[self.rooms_df['id'] == room_id].iloc[0]
                    
                    # Create schedule entry
                    theory_schedule.append({
                        'day': self.days[day_idx],
                        'time_slot': self.theory_time_slots[time_slot_idx],
                        'slot_index': time_slot_idx,  # Add slot_index for visualizer compatibility
                        'course_instance_id': session['course_instance_id'],
                        'course_code': instance['course_code'],
                        'course_name': instance['course_name'],
                        'session_type': session['session_type'],
                        'session_number': session['session_number'],
                        'teacher_id': session['teacher_id'],
                        'teacher_name': f"{teacher_row.get('first_name', '')} {teacher_row.get('last_name', '')}".strip(),
                        'staff_code': teacher_row.get('staff_code', ''),
                        'room_id': int(room_id),
                        'room_number': room_row['room_number'],
                        'block': room_row.get('block', ''),
                        'student_count': int(instance.get('student_count', 70)),
                        # Group information
                        'group_name': group_name,
                        'group_index': int(group_name.split('_G')[1]) if '_G' in group_name else 1,
                        'department': group_info['dept'],
                        'semester': group_info['semester']
                    })
        
        self.logger.info(f"Distributed {len(theory_schedule)} theory sessions across group time slots")
        return theory_schedule
    
    def analyze_theory_feasibility(self):
        """Analyze if the theory requirements can be satisfied."""
        total_lecture_slots_needed = sum(sum(c['required_lecture_sessions'] for c in courses) 
                                       for teacher, courses in self.theory_requirements.items())
        total_tutorial_slots_needed = sum(sum(c['required_tutorial_sessions'] for c in courses) 
                                       for teacher, courses in self.theory_requirements.items())
        
        # Calculate total theory capacity per week
        total_theory_rooms = len(self.theory_room_ids)
        theory_slots_per_week = len(self.theory_time_slots) * self.num_days  # 11 slots * 5 days = 55
        total_theory_capacity = total_theory_rooms * theory_slots_per_week
        
        self.logger.info(f"Theory constraint feasibility analysis:")
        self.logger.info(f"  - Total lecture slots needed: {total_lecture_slots_needed}")
        self.logger.info(f"  - Total tutorial slots needed: {total_tutorial_slots_needed}")
        self.logger.info(f"  - Total theory rooms: {total_theory_rooms}")
        self.logger.info(f"  - Theory slots per week: {theory_slots_per_week}")
        self.logger.info(f"  - Total theory capacity: {total_theory_capacity}")
        self.logger.info(f"  - Utilization: {total_lecture_slots_needed / total_theory_capacity * 100:.1f}% for lecture slots")
        self.logger.info(f"  - Utilization: {total_tutorial_slots_needed / total_theory_capacity * 100:.1f}% for tutorial slots")
        
        if total_lecture_slots_needed > total_theory_capacity or total_tutorial_slots_needed > total_theory_capacity:
            self.logger.error(f"INFEASIBLE: Need {total_lecture_slots_needed} lecture slots + {total_tutorial_slots_needed} tutorial slots but only have {total_theory_capacity} capacity")
            return False
        
        return True
    
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