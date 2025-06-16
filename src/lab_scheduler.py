import os
import pandas as pd
import numpy as np
import logging
import json
from datetime import datetime
from collections import defaultdict
from itertools import combinations
from ortools.sat.python import cp_model
import matplotlib.pyplot as plt
import seaborn as sns

class LabScheduler:
    """Schedules lab sessions based on practical hours requirements, following reference implementation approach."""
    
    def __init__(self, course_file, room_file, theory_schedule_data=None):
        """Initialize the lab scheduler with course and room data, and optional theory schedule data."""
        self.logger = logging.getLogger(__name__)
        
        # Load the data
        self.courses_df = pd.read_csv(course_file)
        self.rooms_df = pd.read_csv(room_file)
        
        # Store theory schedule data for conflict prevention
        self.theory_schedule_data = theory_schedule_data
        if theory_schedule_data:
            self.logger.info(f"Lab scheduler initialized with theory schedule data: {len(theory_schedule_data)} theory sessions")
            self._parse_theory_schedule()
        else:
            self.logger.info("Lab scheduler initialized without theory schedule data")
            self.theory_group_timeslots = {}
        
        # Load core mapping data for specific lab assignments
        self.core_mapping_df = None
        try:
            # The path to combined_lab_mapping.csv. This assumes it's in the same directory as the other data files.
            base_data_dir = os.path.dirname(course_file)
            # A more robust path might be:
            core_mapping_file_path = os.path.join(os.path.dirname(base_data_dir), 'combined_lab_mapping.csv')
            
            if not os.path.exists(core_mapping_file_path):
                 core_mapping_file_path = os.path.join(base_data_dir, 'combined_lab_mapping.csv')
            
            if not os.path.exists(core_mapping_file_path):
                 core_mapping_file_path = os.path.join(base_data_dir, '..', 'data', 'combined_lab_mapping.csv')

            if os.path.exists(core_mapping_file_path):
                self.core_mapping_df = pd.read_csv(core_mapping_file_path)
                self.logger.info(f"Successfully loaded core lab mapping from {core_mapping_file_path}")
            else:
                self.logger.warning(f"Core lab mapping file 'combined_lab_mapping.csv' not found.")

        except Exception as e:
            self.logger.error(f"Error loading combined_lab_mapping.csv: {e}")
            self.core_mapping_df = None
        
        # Setup time structure (matching reference implementation)
        self.days = ["tuesday", "wed", "thur", "fri", "sat"]  # Excluding Monday
        self.num_days = len(self.days)
        
        # Lab time slots (12 slots per day)
        self.lab_time_slots = [
            "8:00 - 8:50", "8:50 - 9:40", "9:50 - 10:40", "10:40 - 11:30",
            "11:50 - 12:40", "12:40 - 1:30", "1:50 - 2:40", "2:40 - 3:30", 
            "3:50 - 4:40", "4:40 - 5:30", "5:30 - 6:20", "6:20 - 7:10"
        ]
        
        # Group lab slots into 2-hour sessions (L1, L2, L3, etc.)
        self.lab_sessions = {
            'L1': ['8:00 - 8:50', '8:50 - 9:40'],      # 8:00 - 9:40
            'L2': ['9:50 - 10:40', '10:40 - 11:30'],   # 9:50 - 11:30  
            'L3': ['11:50 - 12:40', '12:40 - 1:30'],   # 11:50 - 1:30
            'L4': ['1:50 - 2:40', '2:40 - 3:30'],      # 1:50 - 3:30
            'L5': ['3:50 - 4:40', '4:40 - 5:30'],      # 3:50 - 5:30
            'L6': ['5:30 - 6:20', '6:20 - 7:10']       # 5:30 - 7:10
        }
        
        self.lab_rooms = self.rooms_df[self.rooms_df['is_lab'] == 1]
        self.lab_room_ids = self.lab_rooms['id'].tolist()
        
        self.laboratory_room_ids = self.lab_rooms[self.lab_rooms['room_type'] == 'Laboratory']['id'].tolist()
        self.logger.info(f"Found {len(self.laboratory_room_ids)} rooms of type 'Laboratory'.")
        
        self.course_to_room_mapping = {}
        if self.core_mapping_df is not None:
            # We need to map (course_code, course_name) -> list of room_ids
            self.rooms_df['block'] = self.rooms_df['block'].fillna('Unknown').astype(str).str.strip()
            self.rooms_df['room_number'] = self.rooms_df['room_number'].astype(str).str.strip()
            self.rooms_df['room_identifier'] = self.rooms_df['room_number'] + "_" + self.rooms_df['block']
            room_lookup = pd.Series(self.rooms_df.id.values, index=self.rooms_df.room_identifier).to_dict()

            # Clean data in core_mapping_df
            self.core_mapping_df['course_code'] = self.core_mapping_df['course_code'].astype(str).str.strip()
            self.core_mapping_df['course_name'] = self.core_mapping_df['course_name'].astype(str).str.strip()
            
            for _, row in self.core_mapping_df.iterrows():
                course_code = row['course_code']
                course_name = row['course_name']
                total_labs = int(row.get('total_labs', 1))
                
                mapped_rooms = []
                
                # Process each lab (lab_1, lab_2, lab_3, etc.)
                for lab_num in range(1, total_labs + 1):
                    room_col = f'lab_{lab_num}_room'
                    block_col = f'lab_{lab_num}_block'
                    
                    if room_col in row and block_col in row:
                        room_number = str(row[room_col]).strip()
                        block = str(row[block_col]).strip()
                        
                        # Skip if room_number is 'nan' or empty
                        if room_number.lower() in ['nan', ''] or pd.isna(row[room_col]):
                            continue
                            
                        room_identifier = room_number + "_" + block
                        
                        if room_identifier in room_lookup:
                            room_id = room_lookup[room_identifier]
                            mapped_rooms.append(room_id)
                            self.logger.info(f"Mapped course '{course_code}' - '{course_name}' to lab {lab_num}: '{room_number}' (ID: {room_id})")
                        else:
                            self.logger.warning(f"Room '{room_number}' in block '{block}' for course '{course_code}' lab {lab_num} not found in rooms file. Identifier: '{room_identifier}'")
                
                # Store the mapping with all available rooms for this course
                if mapped_rooms:
                    self.course_to_room_mapping[(course_code, course_name)] = mapped_rooms
                    self.logger.info(f"Course '{course_code}' mapped to {len(mapped_rooms)} lab(s): {mapped_rooms}")
                else:
                    self.logger.warning(f"No valid labs found for course '{course_code}' - '{course_name}'")

        
        # Identify all instance IDs that are considered "core labs"
        self.core_lab_instance_ids = set()
        if self.core_mapping_df is not None:
            # Create a lookup from (course_code, course_name) to a list of instance IDs from the main courses_df
            course_name_to_ids = defaultdict(list)
            for _, row in self.courses_df.iterrows():
                course_code = row['course_code']
                course_name = row['course_name']
                instance_id = str(row['id'])
                course_name_to_ids[(course_code, course_name)].append(instance_id)

            # Use the lookup to find all instance IDs corresponding to the core lab mapping
            for course_tuple in self.course_to_room_mapping.keys():
                if course_tuple in course_name_to_ids:
                    self.core_lab_instance_ids.update(course_name_to_ids[course_tuple])

            self.logger.info(f"Identified {len(self.core_lab_instance_ids)} core lab instances that will be exempt from the 18-slot weekly limit.")

        # Process teacher-course assignments for lab sessions
        self.process_teacher_courses()
        
        # Create output directory
        self.output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
                                      'output', 
                                      f'lab_schedule_{datetime.now().strftime("%Y%m%d_%H%M%S")}')
        os.makedirs(self.output_dir, exist_ok=True)
    
    def _parse_theory_schedule(self):
        """Parse theory schedule data to extract group-timeslot conflicts."""
        self.theory_group_timeslots = {}
        
        if not self.theory_schedule_data:
            return
        
        self.logger.info("Parsing theory schedule data for conflict prevention...")
        
        for session in self.theory_schedule_data:
            dept = session.get('department', 'Unknown')
            semester = session.get('semester', 0)
            group_index = session.get('group_index', 0)
            day = session.get('day', '')
            timeslot = session.get('time_slot', '')  # Fixed: use 'time_slot' not 'timeslot'
            
            # Create dept-semester-group key
            group_key = f"{dept}_S{semester}_G{group_index}"
            
            if group_key not in self.theory_group_timeslots:
                self.theory_group_timeslots[group_key] = set()
            
            # Add day-timeslot combination to this group's occupied slots
            if day and timeslot:
                day_timeslot = f"{day}_{timeslot}"
                self.theory_group_timeslots[group_key].add(day_timeslot)
        
        # Log theory group conflicts
        self.logger.info(f"Parsed theory schedule conflicts:")
        for group_key, timeslots in self.theory_group_timeslots.items():
            self.logger.info(f"  {group_key}: {len(timeslots)} occupied timeslots")
            if len(timeslots) <= 5:  # Show details for groups with few timeslots
                self.logger.info(f"    Occupied: {', '.join(sorted(timeslots))}")
        
        total_theory_conflicts = sum(len(slots) for slots in self.theory_group_timeslots.values())
        self.logger.info(f"Total theory timeslots to avoid: {total_theory_conflicts}")
    
    def _map_theory_timeslot_to_lab_session(self, theory_timeslot):
        """Map theory timeslot to corresponding lab session(s) that would conflict."""
        
        def parse_time_range(time_str):
            """Parse time range string to start and end times in minutes from midnight."""
            try:
                # Handle format like "8:00 - 8:50" or "10:00 - 10:50"
                start_str, end_str = time_str.split(' - ')
                
                def time_to_minutes(time_part):
                    # Handle both "8:00" and "8:00" format
                    hour, minute = map(int, time_part.split(':'))
                    return hour * 60 + minute
                
                start_minutes = time_to_minutes(start_str)
                end_minutes = time_to_minutes(end_str)
                
                return start_minutes, end_minutes
            except Exception as e:
                self.logger.warning(f"Could not parse time range '{time_str}': {e}")
                return None, None
        
        def time_ranges_overlap(start1, end1, start2, end2):
            """Check if two time ranges overlap (excluding adjacent endpoints)."""
            if start1 is None or end1 is None or start2 is None or end2 is None:
                return False
            
            # Two ranges overlap if: start1 < end2 AND start2 < end1
            # This excludes cases where one ends exactly when the other starts
            return start1 < end2 and start2 < end1
        
        # Parse theory timeslot
        theory_start, theory_end = parse_time_range(theory_timeslot)
        if theory_start is None or theory_end is None:
            return None
        
        # Check which lab sessions overlap with this theory timeslot
        conflicting_sessions = []
        
        for session_name, time_slots in self.lab_sessions.items():
            # Check if theory timeslot overlaps with any slot in this lab session
            session_has_conflict = False
            
            for lab_timeslot in time_slots:
                lab_start, lab_end = parse_time_range(lab_timeslot)
                if lab_start is None or lab_end is None:
                    continue
                
                if time_ranges_overlap(theory_start, theory_end, lab_start, lab_end):
                    session_has_conflict = True
                    self.logger.debug(f"Theory {theory_timeslot} overlaps with lab {lab_timeslot} in session {session_name}")
                    break
            
            if session_has_conflict:
                conflicting_sessions.append(session_name)
        
        # Return the first conflicting session (there should typically be at most one)
        if conflicting_sessions:
            if len(conflicting_sessions) > 1:
                self.logger.warning(f"Theory timeslot {theory_timeslot} conflicts with multiple lab sessions: {conflicting_sessions}")
            return conflicting_sessions[0]
        
        return None
    
    def process_teacher_courses(self):
        """Process the teacher-course assignments from the CSV data, focusing on courses with practical hours."""
        # Extract unique teachers
        self.teachers = self.courses_df['teacher_id'].unique()
        self.num_teachers = len(self.teachers)
        self.logger.info(f"Processing {self.num_teachers} teachers")
        
        # Create a mapping of teachers to their courses with required hours
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
                'practical_hours': int(row['practical_hours']),
                'student_count': int(row['student_count']),
                'semester': row.get('semester', 1),
                'student_dept': row.get('student_dept', 'Computer Science & Engineering')
            })
        
        # Calculate lab requirements for each teacher and course
        self.calculate_lab_requirements()
        
        # Create course groups for Hall's theorem distribution (semester/department based)
        self.create_course_groups()
    
    def calculate_lab_requirements(self):
        """Calculate lab requirements based on practical hours with proper capacity-based allocation strategy."""
        self.lab_requirements = {}
        self.course_to_teacher = {}  # Maps course instance to teacher
        
        for teacher_id, assignments in self.teacher_course_assignments.items():
            # Filter only courses with practical hours
            practical_courses = [a for a in assignments if a['practical_hours'] > 0]
            
            if practical_courses:
                self.lab_requirements[teacher_id] = []
                
                for course in practical_courses:
                    course_instance_id = course['id']
                    practical_hours = course['practical_hours']
                    student_count = course['student_count']
                    
                    # Map course instance to teacher
                    self.course_to_teacher[course_instance_id] = teacher_id
                    
                    # Calculate required lab sessions (each session = 2 practical hours)
                    # Match reference implementation logic
                    required_sessions = (practical_hours + 1) // 2  # Round up division
                    
                    # Exact mapping for clarity (corrected)
                    if practical_hours == 1:
                        required_sessions = 1  # 1 practical hour needs 1 lab session (2 hours)
                    elif practical_hours == 2:
                        required_sessions = 1  # 2 practical hours = exactly 1 lab session
                    elif practical_hours == 3:
                        required_sessions = 2  # 3 practical hours needs 2 lab sessions (4 hours)
                    elif practical_hours == 4:
                        required_sessions = 2  # 4 practical hours = exactly 2 lab sessions
                    elif practical_hours == 5:
                        required_sessions = 3  # 5 practical hours needs 3 lab sessions (6 hours)
                    elif practical_hours == 6:
                        required_sessions = 3  # 6 practical hours = exactly 3 lab sessions
                    else:
                        required_sessions = (practical_hours + 1) // 2  # General rule: round up
                    
                    # Determine lab capacity requirements and batching strategy
                    lab_allocation_strategy = self._determine_lab_allocation_strategy(practical_hours, student_count)
                    
                    self.lab_requirements[teacher_id].append({
                        'course_instance_id': course_instance_id,
                        'course_code': course['course_code'],
                        'display_course_code': course['course_code'],
                        'practical_hours': practical_hours,
                        'students_per_instance': student_count,
                        'base_sessions': lab_allocation_strategy['base_sessions'],
                        'preferred_lab_capacities': lab_allocation_strategy['preferred_lab_capacities']
                    })
        
        # Log lab requirements (using base sessions for now)
        total_lab_slots = sum(sum(c['base_sessions'] for c in courses) 
                             for teacher, courses in self.lab_requirements.items())
        self.logger.info(f"Calculated lab requirements: {total_lab_slots} total lab slots needed")
        self.logger.info(f"Teachers with practical courses: {len(self.lab_requirements)}")
    
    def create_course_groups(self):
        """Create course groups based on semester and department for Hall's theorem distribution."""
        self.logger.info("Creating course groups for Hall's theorem distribution...")
        
        # Create course groups by department and semester
        self.course_groups = self._create_course_groups_by_dept_semester()
        
        # Create instance-group mapping for CSV output
        self.instance_group_mapping = {}
        self._create_instance_group_mapping()
        
        # Generate course-to-group distribution heatmap BEFORE applying constraints
        self.generate_course_group_distribution_heatmap()
        
        self.logger.info("Course grouping completed successfully")
        self.logger.info("✅ TEACHER UNIQUENESS CONSTRAINT: Each teacher appears at most once per group per semester")
        self.logger.info("✅ HALL'S THEOREM COMPLIANCE: Optimized for maximum student choice while respecting teacher constraints")
    
    def _create_course_groups_by_dept_semester(self):
        """Group course instances by department and semester with Hall's theorem optimization.
        
        IMPORTANT: This grouping considers ALL courses (theory + lab) in a semester,
        not just courses with practical hours. This ensures proper Hall's distribution
        across all courses that students need to take in a semester.
        """
        # Collect ALL course instances by department and semester (theory + lab)
        dept_sem_courses = defaultdict(list)
        total_instances = 0
        
        # Gather ALL course instances from the original CSV data, not just practical courses
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
                'practical_hours': int(row['practical_hours']),
                'student_count': int(row['student_count']),
                'semester': row.get('semester', 1),
                'student_dept': row.get('student_dept', 'Computer Science & Engineering'),
                'is_lab_course': int(row['practical_hours']) > 0
            }
            all_instances.append(instance_with_teacher)
            total_instances += 1
        
        self.logger.info(f"Processing {total_instances} total course instances (theory + lab) across {len(self.teachers)} teachers")
        
        # Group by department and semester
        for instance in all_instances:
            dept = instance.get('student_dept', 'Computer Science & Engineering')
            semester = instance.get('semester', 3)  # Default to semester 3
            dept_sem_courses[(dept, semester)].append(instance)
        
        # Log department-semester distribution
        for (dept, semester), instances in dept_sem_courses.items():
            self.logger.info(f"Dept: {dept}, Semester: {semester}: {len(instances)} instances")
        
        # Create groups for each department and semester
        course_groups = {}
        for (dept, semester), courses in dept_sem_courses.items():
            if courses:  # Skip if there are no courses
                # Analyze teacher distribution challenges before grouping
                self._analyze_teacher_distribution_challenges(courses, dept, semester)
                
                course_groups[(dept, semester)] = self._distribute_course_instances(courses, dept, semester)
        
        return course_groups
    
    def _analyze_teacher_distribution_challenges(self, courses, dept, semester):
        """Analyze potential challenges in teacher distribution for Hall's theorem compliance."""
        self.logger.info(f"Analyzing teacher distribution challenges for {dept} Semester {semester}...")
        
        # Count courses per teacher
        teacher_course_count = {}
        teacher_instances = {}
        total_instances = len(courses)
        
        for instance in courses:
            teacher_id = instance['teacher_id']
            if teacher_id not in teacher_course_count:
                teacher_course_count[teacher_id] = 0
                teacher_instances[teacher_id] = []
            teacher_course_count[teacher_id] += 1
            teacher_instances[teacher_id].append(instance)
        
        # Identify potential conflicts
        unique_teachers = len(teacher_course_count)
        unique_courses = len(set(inst['course_code'] for inst in courses))
        max_courses_per_teacher = max(teacher_course_count.values()) if teacher_course_count else 0
        
        # Calculate optimal number of groups
        optimal_groups = unique_courses  # One group per unique course for maximum choice
        
        # Identify high-load teachers (multiple courses)
        high_load_teachers = [(t, count) for t, count in teacher_course_count.items() if count > 1]
        
        self.logger.info(f"Teacher distribution analysis:")
        self.logger.info(f"  Total instances: {total_instances}")
        self.logger.info(f"  Unique teachers: {unique_teachers}")
        self.logger.info(f"  Unique courses: {unique_courses}")
        self.logger.info(f"  Optimal groups: {optimal_groups}")
        self.logger.info(f"  Max courses per teacher: {max_courses_per_teacher}")
        self.logger.info(f"  High-load teachers: {len(high_load_teachers)}")
        
        if high_load_teachers:
            self.logger.info("  Teachers with multiple courses:")
            for teacher_id, course_count in sorted(high_load_teachers, key=lambda x: x[1], reverse=True):
                course_codes = [inst['course_code'] for inst in teacher_instances[teacher_id]]
                self.logger.info(f"    Teacher {teacher_id}: {course_count} courses ({', '.join(set(course_codes))})")
        
        # Check if distribution is theoretically possible
        if unique_teachers < optimal_groups:
            self.logger.warning(f"W Challenge: Only {unique_teachers} teachers for {optimal_groups} optimal groups")
            self.logger.warning(f"W Some groups will need to share teachers across different group instances")
        
        # Estimate minimum groups needed to satisfy teacher uniqueness
        if max_courses_per_teacher > optimal_groups:
            min_groups_needed = max_courses_per_teacher
            self.logger.warning(f"W Teacher uniqueness requires at least {min_groups_needed} groups")
            self.logger.warning(f"W This exceeds optimal groups ({optimal_groups}) - some compromise may be needed")
        
        return {
            'total_instances': total_instances,
            'unique_teachers': unique_teachers,
            'unique_courses': unique_courses,
            'optimal_groups': optimal_groups,
            'max_courses_per_teacher': max_courses_per_teacher,
            'high_load_teachers': high_load_teachers,
            'distribution_feasible': unique_teachers >= optimal_groups and max_courses_per_teacher <= optimal_groups
        }

    def _calculate_min_groups_for_halls_with_course_limit(self, courses, unique_course_codes):
        """Calculate minimum number of groups needed for Hall's theorem with course limit constraint."""
        # Build course-teacher mapping
        course_to_teachers = {}
        teacher_to_courses = {}
        
        for instance in courses:
            course_code = instance['course_code']
            teacher_id = instance['teacher_id']
            
            if course_code not in course_to_teachers:
                course_to_teachers[course_code] = set()
            course_to_teachers[course_code].add(teacher_id)
            
            if teacher_id not in teacher_to_courses:
                teacher_to_courses[teacher_id] = set()
            teacher_to_courses[teacher_id].add(course_code)
        
        # Calculate minimum groups needed for Hall's theorem
        # With course limit of 2 groups per course, we need to ensure:
        # For any subset S of courses, |N(S)| >= |S|
        # But each course can appear in at most 2 groups
        
        max_teachers_per_course = max(len(teachers) for teachers in course_to_teachers.values()) if course_to_teachers else 1
        min_groups_from_teachers = max_teachers_per_course
        
        # Consider worst-case Hall's theorem scenario
        # If we have courses with limited teacher availability
        courses_by_teacher_count = {}
        for course_code, teachers in course_to_teachers.items():
            teacher_count = len(teachers)
            if teacher_count not in courses_by_teacher_count:
                courses_by_teacher_count[teacher_count] = []
            courses_by_teacher_count[teacher_count].append(course_code)
        
        # Estimate minimum groups needed
        # Each course can be in 2 groups, so we need enough groups to satisfy Hall's condition
        min_groups_needed = max(1, (unique_course_codes + 1) // 2)  # Base minimum
        
        # Check if we need more groups due to teacher constraints
        unique_teachers = len(teacher_to_courses)
        if unique_teachers < unique_course_codes:
            # Not enough teachers for one-to-one mapping
            # Need more groups to distribute courses properly
            min_groups_needed = max(min_groups_needed, min_groups_from_teachers)
        
        self.logger.info(f"Hall's constraint analysis:")
        self.logger.info(f"  Unique courses: {unique_course_codes}")
        self.logger.info(f"  Unique teachers: {unique_teachers}")
        self.logger.info(f"  Max teachers per course: {max_teachers_per_course}")
        self.logger.info(f"  Calculated min groups: {min_groups_needed}")
        
        return min_groups_needed

    def _distribute_course_instances(self, courses, dept, semester):
        """Distribute course instances across groups with Hall's theorem optimization and course limit constraints."""
        total_instances = len(courses)
        
        if total_instances == 0:
            return []
        
        # Enhanced instance analysis for ALL courses (theory + lab)
        practical_courses = [inst for inst in courses if inst['practical_hours'] > 0]
        theory_courses = [inst for inst in courses if inst['practical_hours'] == 0]
        
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
            'practical_instances_count': len(practical_courses),
            'theory_instances_count': len(theory_courses),
            'unique_courses': len(set(inst['course_code'] for inst in courses)),
            'unique_practical_courses': len(set(inst['course_code'] for inst in practical_courses)),
            'unique_theory_courses': len(set(inst['course_code'] for inst in theory_courses)),
            'unique_teachers': len(set(inst['teacher_id'] for inst in courses)),
            'total_practical_hours': sum(inst['practical_hours'] for inst in courses),
            'avg_student_count': sum(inst.get('student_count', 70) for inst in courses) / total_instances if total_instances > 0 else 0,
            'max_instances_per_course': max_instances_per_course,
            'dynamic_student_capacity': dynamic_student_capacity,
            'course_instance_counts': course_instance_counts
        }
        
        self.logger.info(f"Hall-based analysis for {dept} Semester {semester}:")
        self.logger.info(f"  {instance_analysis['total_instances']} total instances")
        self.logger.info(f"  {instance_analysis['practical_instances_count']} practical instances, {instance_analysis['theory_instances_count']} theory instances")
        self.logger.info(f"  {instance_analysis['unique_courses']} unique courses ({instance_analysis['unique_practical_courses']} practical + {instance_analysis['unique_theory_courses']} theory)")
        self.logger.info(f"  {instance_analysis['unique_teachers']} unique teachers")
        self.logger.info(f"  Total practical workload: {instance_analysis['total_practical_hours']} hours")
        self.logger.info(f"  Max instances per course: {instance_analysis['max_instances_per_course']}")
        self.logger.info(f"  Dynamic student capacity: {instance_analysis['dynamic_student_capacity']} students")
        
        # CRITICAL: Number of groups = Number of unique courses in the semester
        # Each course can appear in at most 2 of these groups for optimal student choice
        unique_course_codes = instance_analysis['unique_courses']
        
        # Always create as many groups as there are unique courses
        num_groups = unique_course_codes
        
        self.logger.info(f"Creating {num_groups} groups (one per unique course: {unique_course_codes})")
        self.logger.info(f"📋 CONSTRAINT: Each course limited to maximum 2 of the {num_groups} groups for optimal choice balance")
        
        # Initialize groups
        groups = [[] for _ in range(num_groups)]
        
        # Track group metrics
        group_metrics = []
        for i in range(num_groups):
            group_metrics.append({
                'workload': 0,
                'practical_workload': 0,
                'student_count': 0,
                'instance_count': 0,
                'practical_instance_count': 0,
                'theory_instance_count': 0,
                'courses': set(),
                'teachers': set()
            })
        
        # Build course-teacher bipartite graph for Hall's theorem (ALL courses)
        course_to_teachers = {}
        teacher_to_courses = {}
        
        for instance in courses:  # Use ALL courses, not just practical
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
        for instance in courses:  # Use ALL courses, not just practical
            course_code = instance['course_code']
            if course_code not in course_instances:
                course_instances[course_code] = []
            course_instances[course_code].append(instance)
        
        # LAB-FIRST SORTING STRATEGY:
        # Prioritize courses with practical hours to fill initial groups with labs
        self.logger.info("🧪 Applying LAB-FIRST sorting strategy to prioritize practical courses in initial groups...")
        
        # 1. Separate lab and theory course codes
        lab_course_codes = {c for c, instances in course_instances.items() if any(i['practical_hours'] > 0 for i in instances)}
        theory_course_codes = {c for c in course_to_teachers if c not in lab_course_codes}
        
        self.logger.info(f"  - Found {len(lab_course_codes)} lab courses and {len(theory_course_codes)} theory-only courses.")

        # 2. Sort both lists independently by teacher availability (for Hall's theorem)
        sorted_lab_courses = sorted(list(lab_course_codes), key=lambda c: len(course_to_teachers.get(c, set())))
        sorted_theory_courses = sorted(list(theory_course_codes), key=lambda c: len(course_to_teachers.get(c, set())))

        # 3. Combine the lists, with lab courses first
        sorted_courses = sorted_lab_courses + sorted_theory_courses
        
        self.logger.info(f"  - Final sorted order: {len(sorted_courses)} total courses (labs first).")

        self.logger.info("Course-teacher availability analysis (Lab-First):")
        # Log first few lab courses
        self.logger.info("  Lab courses (up to 5):")
        for course_code in sorted_lab_courses[:5]:
            teacher_count = len(course_to_teachers.get(course_code, set()))
            self.logger.info(f"    - {course_code}: {teacher_count} teachers, {len(course_instances.get(course_code, []))} instances")
        
        # Log first few theory courses
        self.logger.info("  Theory courses (up to 5):")
        for course_code in sorted_theory_courses[:5]:
            teacher_count = len(course_to_teachers.get(course_code, set()))
            self.logger.info(f"    - {course_code}: {teacher_count} teachers, {len(course_instances.get(course_code, []))} instances")

        # SMARTER PRE-ALLOCATION LOGIC
        self.logger.info("Performing smarter course pre-allocation to groups to maximize choice...")
        pre_allocation = [set() for _ in range(num_groups)]
        course_group_assignments = {}

        # Create a balanced, chained allocation to ensure all groups are used meaningfully
        for i, course_code in enumerate(sorted_courses):
            # Each course should appear in up to 2 groups for choice, if possible and num_groups > 1
            num_placements = min(2, len(course_instances[course_code])) if num_groups > 1 else 1

            # Place course in a "chained" fashion: e.g., C1 in G1/G2, C2 in G2/G3, C3 in G3/G4...
            for j in range(num_placements):
                group_idx = (i + j) % num_groups
                pre_allocation[group_idx].add(course_code)
                
                if course_code not in course_group_assignments:
                    course_group_assignments[course_code] = []
                
                # Ensure we don't add the same group index twice
                if group_idx not in course_group_assignments[course_code]:
                    course_group_assignments[course_code].append(group_idx)
        
        # Log course-group pre-allocation
        self.logger.info("Course pre-allocation (max 2 groups per course, chained distribution):")
        for course_code, group_indices in sorted(course_group_assignments.items()):
            group_names = [f"G{i+1}" for i in sorted(group_indices)]
            self.logger.info(f"  {course_code}: assigned to groups {', '.join(group_names)}")
        
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
                        
                        # Update metrics
                        metrics = group_metrics[group_idx]
                        practical_hrs = instance['practical_hours']
                        
                        metrics['workload'] += practical_hrs
                        metrics['practical_workload'] += practical_hrs
                        metrics['student_count'] += instance.get('student_count', 70)
                        metrics['instance_count'] += 1
                        if practical_hrs > 0:
                            metrics['practical_instance_count'] += 1
                        else:
                            metrics['theory_instance_count'] = metrics.get('theory_instance_count', 0) + 1
                        metrics['courses'].add(instance['course_code'])
                        metrics['teachers'].add(instance['teacher_id'])
                        
                        self.logger.debug(f"  Pre-allocated: {course_code} (T{teacher_id}) → Group {group_idx + 1}")
                        break
                
                if not instance_assigned:
                    self.logger.debug(f"  Could not pre-allocate {course_code} to Group {group_idx + 1} - no teacher available that isn't already in this group")
        
        # --- START REVISED DISTRIBUTION LOGIC ---
        self.logger.info("Phase 1 distribution complete. Now starting Phase 2: Bottleneck Repair & Remainder Placement.")

        # Identify courses that are under-represented (in fewer than 2 groups) after the first pass
        course_placements = defaultdict(set)
        for i, g in enumerate(groups):
            for inst in g:
                course_placements[inst['course_code']].add(i)

        under_represented_courses = {
            c for c, placements in course_placements.items() if len(placements) < 2
        }
        if under_represented_courses:
            self.logger.warning(f"Found {len(under_represented_courses)} under-represented courses (in < 2 groups): {', '.join(sorted(list(under_represented_courses)))}")
            self.logger.info("Attempting to find a second group for them...")
        else:
            self.logger.info("All courses are in at least two groups after initial placement.")

        # Get all remaining instances that were not placed in the first pass
        all_assigned_instances = {inst['id'] for g in groups for inst in g}
        remaining_instances = [
            inst for inst_list in course_instances.values() for inst in inst_list 
            if inst['id'] not in all_assigned_instances
        ]

        # Prioritize placing instances from under-represented courses first
        instances_to_assign = sorted(
            remaining_instances,
            key=lambda x: (x['course_code'] not in under_represented_courses, x['course_code'])
        )
        self.logger.info(f"Distributing {len(instances_to_assign)} remaining instances (prioritizing under-represented ones).")

        failed_assignments = []
        for instance in instances_to_assign:
            teacher_id = instance['teacher_id']
            course_code = instance['course_code']

            # Find the best valid group for this instance
            best_group_idx = -1
            best_score = -1
            
            # Re-check current placements for the course inside the loop
            current_placements = {i for i, g in enumerate(groups) for inst in g if inst['course_code'] == course_code}

            for group_idx in range(num_groups):
                # --- Constraint Checks ---
                # 1. Teacher Uniqueness: Teacher cannot already be in this group.
                group_teachers = {inst['teacher_id'] for inst in groups[group_idx]}
                if pd.notna(instance.get('assistant_teacher_id')):
                    group_teachers.add(instance['assistant_teacher_id'])
                if teacher_id in group_teachers:
                    continue

                # 2. Max 2 Groups per Course: Prevent a course from being in more than two distinct groups.
                #    A course can be added to a new group only if it's currently in less than 2 groups.
                #    It can always be added to a group it's already in (if teacher is unique).
                if group_idx not in current_placements and len(current_placements) >= 2:
                    continue
                
                # --- Scoring ---
                # Base score prefers smaller groups.
                score = 1000 - len(groups[group_idx])
                
                if score > best_score:
                    best_score = score
                    best_group_idx = group_idx
            
            # Place the instance in the best found group
            if best_group_idx != -1:
                groups[best_group_idx].append(instance)
                self.logger.info(f"✅ Placed instance {instance['id']} ({course_code}) in Group {best_group_idx + 1} to improve student choice.")
                # Update metrics for the newly added instance
                metrics = group_metrics[best_group_idx]
                practical_hrs = instance['practical_hours']
                
                metrics['workload'] += practical_hrs
                metrics['practical_workload'] += practical_hrs
                metrics['student_count'] += instance.get('student_count', 70)
                metrics['instance_count'] += 1
                if practical_hrs > 0:
                    metrics['practical_instance_count'] += 1
                else:
                    metrics['theory_instance_count'] = metrics.get('theory_instance_count', 0) + 1
                metrics['courses'].add(instance['course_code'])
                metrics['teachers'].add(instance['teacher_id'])
            else:
                failed_assignments.append(instance)
        
        # --- END REVISED DISTRIBUTION LOGIC ---

        # Log assignment results
        if failed_assignments:
            self.logger.error(f"Failed to assign: {len(failed_assignments)} instances after both phases.")
            for failure in failed_assignments[:5]: # Log first 5
                self.logger.error(f"  - Instance {failure['id']} (Teacher {failure['teacher_id']}, Course {failure['course_code']}) could not be placed.")
        
        # Log final unassigned instances
        final_assigned_ids = {inst['id'] for g in groups for inst in g}
        final_unassigned_instances = [
            inst for inst_list in course_instances.values() for inst in inst_list
            if inst['id'] not in final_assigned_ids
        ]
        
        if final_unassigned_instances:
            self.logger.error(f"TOTAL UNASSIGNED INSTANCES: {len(final_unassigned_instances)}")
            for unassigned in final_unassigned_instances[:5]:
                 self.logger.error(f"  - Unassigned: {unassigned['id']} ({unassigned['course_code']})")
        
        # Validate and log final group distribution
        self._validate_teacher_uniqueness_constraint(groups, dept, semester)
        self._validate_halls_theorem(groups, dept, semester)
        
        # Analyze student choice feasibility for 420 students
        self.analyze_student_choice_feasibility(groups, dept, semester, target_students=420)
        
        # Log final group distribution with course limit analysis
        self.logger.info(f"Final group distribution for {dept} Semester {semester} (Course Limit: 2 groups max):")
        
        # Track course distribution across groups
        course_distribution_summary = {}
        
        for i, group in enumerate(groups):
            if group:  # Only show non-empty groups
                metrics = group_metrics[i]
                teacher_list = sorted(set(str(instance['teacher_id']) for instance in group))
                course_list = sorted(set(instance['course_code'] for instance in group))
                practical_courses = [inst['course_code'] for inst in group if inst['practical_hours'] > 0]
                theory_courses = [inst['course_code'] for inst in group if inst['practical_hours'] == 0]
                
                # Track course distribution
                for course_code in course_list:
                    if course_code not in course_distribution_summary:
                        course_distribution_summary[course_code] = []
                    course_distribution_summary[course_code].append(i + 1)
                
                self.logger.info(f"  Group {i+1}: {metrics['instance_count']} instances")
                self.logger.info(f"    Practical: {metrics['practical_instance_count']} instances, Theory: {metrics.get('theory_instance_count', 0)} instances")
                self.logger.info(f"    Teachers: [{', '.join(teacher_list)}]")
                self.logger.info(f"    Courses: [{', '.join(course_list)}]")
                if practical_courses:
                    self.logger.info(f"    Practical courses: [{', '.join(set(practical_courses))}]")
                if theory_courses:
                    self.logger.info(f"    Theory courses: [{', '.join(set(theory_courses))}]")
                self.logger.info(f"    Total practical hours: {metrics['practical_workload']}")
        
        # Log course distribution summary
        self.logger.info(f"\nCourse distribution summary (max 2 groups per course):")
        for course_code, group_list in sorted(course_distribution_summary.items()):
            group_names = [f"G{g}" for g in group_list]
            constraint_status = "✅" if len(group_list) <= 2 else "❌"
            self.logger.info(f"  {course_code}: {', '.join(group_names)} ({len(group_list)} groups) {constraint_status}")
        
        # Calculate student choice metrics
        total_courses = len(course_distribution_summary)
        courses_with_choice = len([course for course, groups in course_distribution_summary.items() if len(groups) > 1])
        choice_percentage = (courses_with_choice / total_courses * 100) if total_courses > 0 else 0
        
        self.logger.info(f"\nStudent choice analysis:")
        self.logger.info(f"  Total courses: {total_courses}")
        self.logger.info(f"  Courses with multiple group options: {courses_with_choice}")
        self.logger.info(f"  Student choice percentage: {choice_percentage:.1f}%")
        self.logger.info(f"  Dynamic student capacity: {instance_analysis['dynamic_student_capacity']} students")
        
        # Remove empty groups
        non_empty_groups = [group for group in groups if group]
        return non_empty_groups
    
    def _validate_teacher_uniqueness_constraint(self, groups, dept, semester):
        """Validate that no teacher appears multiple times in the same group."""
        constraint_violations = 0
        violation_details = []
        
        for group_idx, group in enumerate(groups):
            if not group:
                continue
                
            teacher_occurrences = {}
            for instance in group:
                teacher_id = instance['teacher_id']
                if teacher_id not in teacher_occurrences:
                    teacher_occurrences[teacher_id] = []
                teacher_occurrences[teacher_id].append({
                    'course_code': instance['course_code'],
                    'instance_id': instance['id'],
                    'practical_hours': instance.get('practical_hours', 0)
                })
            
            # Check for violations
            for teacher_id, course_details in teacher_occurrences.items():
                if len(course_details) > 1:
                    constraint_violations += 1
                    violation_info = {
                        'teacher_id': teacher_id,
                        'group_idx': group_idx + 1,
                        'occurrences': len(course_details),
                        'courses': [detail['course_code'] for detail in course_details],
                        'instance_ids': [detail['instance_id'] for detail in course_details]
                    }
                    violation_details.append(violation_info)
                    
                    course_list = ', '.join(violation_info['courses'])
                    self.logger.error(f"CONSTRAINT VIOLATION: Teacher {teacher_id} appears {len(course_details)} times in Group {group_idx + 1}")
                    self.logger.error(f"  Courses: {course_list}")
                    self.logger.error(f"  Instance IDs: {violation_info['instance_ids']}")
        
        if constraint_violations == 0:
            self.logger.info(f"V Teacher uniqueness constraint SATISFIED for {dept} Semester {semester}")
            
            # Log teacher distribution summary for validation
            total_teachers = set()
            group_teacher_counts = []
            for group_idx, group in enumerate(groups):
                if group:
                    group_teachers = set(instance['teacher_id'] for instance in group)
                    total_teachers.update(group_teachers)
                    group_teacher_counts.append(len(group_teachers))
                    self.logger.info(f"  Group {group_idx + 1}: {len(group_teachers)} unique teachers")
            
            self.logger.info(f"  Total unique teachers across all groups: {len(total_teachers)}")
            if group_teacher_counts:
                self.logger.info(f"  Average teachers per group: {sum(group_teacher_counts) / len(group_teacher_counts):.1f}")
        else:
            self.logger.error(f"X Teacher uniqueness constraint VIOLATED: {constraint_violations} violations")
            self.logger.error(f"X Total violation details: {len(violation_details)} cases")
            
        return constraint_violations == 0

    def _analyze_last_student_probability(self, course_group_mapping, course_group_capacities, target_students):
        """Analyze probability that the last student will have valid choices after random selections."""
        
        # Get all possible course-group combinations (32 total for 5 courses, 2 groups each)
        from itertools import product
        
        all_courses = sorted(course_group_mapping.keys())
        course_group_choices = [course_group_mapping[course] for course in all_courses]
        all_combinations = list(product(*course_group_choices))
        
        total_combinations = len(all_combinations)
        
        # For each combination, calculate if it can survive 419 random selections
        viable_combinations = 0
        combination_analysis = []
        
        for combination in all_combinations:
            # Calculate total capacity for this specific combination
            combination_capacity = float('inf')
            combination_details = []
            
            for i, (course, group_idx) in enumerate(zip(all_courses, combination)):
                capacity = course_group_capacities[(course, group_idx)]
                combination_capacity = min(combination_capacity, capacity)
                combination_details.append(f"{course}:G{group_idx+1}({capacity})")
            
            # This combination is viable if it can handle at least target_students
            is_viable = combination_capacity >= target_students
            if is_viable:
                viable_combinations += 1
            
            combination_analysis.append({
                'combination': combination_details,
                'bottleneck_capacity': combination_capacity,
                'viable': is_viable
            })
        
        # Calculate success probability
        success_probability = (viable_combinations / total_combinations) * 100
        
        # Determine guarantee level
        if viable_combinations == total_combinations:
            # ALL combinations can handle 420 students
            return {
                'guaranteed_success': True,
                'high_probability': True,
                'success_probability': 100.0,
                'viable_combinations': viable_combinations,
                'total_combinations': total_combinations,
                'reason': f"ALL {total_combinations} combinations have sufficient capacity"
            }
        elif success_probability >= 90:
            # Very high probability
            return {
                'guaranteed_success': False,
                'high_probability': True,
                'success_probability': success_probability,
                'viable_combinations': viable_combinations,
                'total_combinations': total_combinations,
                'reason': f"{viable_combinations}/{total_combinations} combinations are viable"
            }
        else:
            # Lower probability - may need attention
            # Find bottleneck combinations
            bottleneck_combinations = [
                combo for combo in combination_analysis 
                if not combo['viable']
            ][:3]  # Show first 3 problematic combinations
            
            bottleneck_details = []
            for combo in bottleneck_combinations:
                combo_str = ' + '.join(combo['combination'])
                bottleneck_details.append(f"[{combo_str}] → {combo['bottleneck_capacity']} capacity")
            
            return {
                'guaranteed_success': False,
                'high_probability': False,
                'success_probability': success_probability,
                'viable_combinations': viable_combinations,
                'total_combinations': total_combinations,
                'reason': f"Only {viable_combinations}/{total_combinations} combinations viable. Bottlenecks: {'; '.join(bottleneck_details)}"
            }
    
    def _validate_halls_theorem(self, groups, dept, semester):
        """Validate that groups satisfy Hall's theorem for optimal student choice with course limit constraints."""
        total_violations = 0
        
        # Global validation: Check Hall's theorem across all groups with 2-group-per-course constraint
        all_courses = set()
        global_course_teacher_matrix = {}
        course_group_participation = {}
        
        # Build global course-teacher mapping and track course participation
        for group_idx, group in enumerate(groups):
            if not group:
                continue
                
            for instance in group:
                course_code = instance['course_code']
                teacher_id = instance['teacher_id']
                
                all_courses.add(course_code)
                
                if course_code not in global_course_teacher_matrix:
                    global_course_teacher_matrix[course_code] = set()
                global_course_teacher_matrix[course_code].add(teacher_id)
                
                if course_code not in course_group_participation:
                    course_group_participation[course_code] = set()
                course_group_participation[course_code].add(group_idx)
        
        # Validate 2-group-per-course constraint
        course_limit_violations = 0
        for course_code, participating_groups in course_group_participation.items():
            if len(participating_groups) > 2:
                course_limit_violations += 1
                group_names = [f"G{i+1}" for i in participating_groups]
                self.logger.error(f"COURSE LIMIT VIOLATION: {course_code} appears in {len(participating_groups)} groups: {', '.join(group_names)}")
        
        if course_limit_violations == 0:
            self.logger.info(f"V Course limit constraint SATISFIED (max 2 groups per course)")
        else:
            self.logger.error(f"X Course limit constraint VIOLATED: {course_limit_violations} violations")
        
        # Global Hall's theorem validation with course choices consideration
        self.logger.info(f"Global Hall's theorem validation with course choices:")
        
        # For student choice validation: Each course appears in at most 2 groups
        # Students need to be able to select all courses for their semester
        course_choice_validation = []
        
        for course_code in all_courses:
            available_groups = course_group_participation.get(course_code, set())
            available_teachers = global_course_teacher_matrix.get(course_code, set())
            
            course_choice_validation.append({
                'course': course_code,
                'groups': len(available_groups),
                'teachers': len(available_teachers),
                'choice_ratio': len(available_groups) / max(1, len(available_teachers))
            })
        
        # Log course choice availability
        self.logger.info("Course choice availability analysis:")
        for choice_info in sorted(course_choice_validation, key=lambda x: x['choice_ratio']):
            course = choice_info['course']
            groups = choice_info['groups']
            teachers = choice_info['teachers']
            self.logger.info(f"  {course}: {groups} groups, {teachers} teachers (ratio: {choice_info['choice_ratio']:.2f})")
        
        # Check global Hall's condition for student choice
        global_violations = []
        
        for r in range(1, min(len(all_courses) + 1, 6)):  # Limit to prevent exponential explosion
            for course_subset in combinations(all_courses, r):
                # Calculate total choice combinations available for this subset
                total_group_choices = 1
                neighbor_teachers = set()
                
                for course in course_subset:
                    course_groups = len(course_group_participation.get(course, set()))
                    total_group_choices *= max(1, course_groups)
                    neighbor_teachers.update(global_course_teacher_matrix.get(course, set()))
                
                # Modified Hall's condition: Students need enough choices to select all courses
                # At minimum, need 1 valid combination (each course available in at least 1 group)
                if len(neighbor_teachers) < len(course_subset):
                    global_violations.append({
                        'subset': list(course_subset),
                        'subset_size': len(course_subset),
                        'teacher_count': len(neighbor_teachers),
                        'group_choices': total_group_choices
                    })
        
        if global_violations:
            total_violations += len(global_violations)
            self.logger.warning(f"W Global Hall's theorem VIOLATED: {len(global_violations)} violations")
            for violation in global_violations[:3]:  # Show first 3 violations
                courses_str = ', '.join(violation['subset'])
                self.logger.warning(f"  Subset [{courses_str}]: {violation['teacher_count']} teachers < {violation['subset_size']} courses")
        else:
            self.logger.info(f"V Global Hall's theorem SATISFIED with course limit constraints")
        
        return total_violations == 0 and course_limit_violations == 0
    
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
                        'is_lab_course': instance.get('is_lab_course', False),
                        'practical_hours': instance.get('practical_hours', 0)
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
    
    def _determine_lab_allocation_strategy(self, practical_hours, students_per_instance):
        """Determine the optimal lab allocation strategy - simplified logic."""
        # Calculate base lab sessions needed (2 practical hours = 1 lab session)
        base_sessions = (practical_hours + 1) // 2
        
        strategy = {
            'practical_hours': practical_hours,
            'students_per_instance': students_per_instance,
            'base_sessions': base_sessions,
            'total_lab_slots_needed': base_sessions,  # Default: no batching
            'preferred_lab_capacities': [],
            'force_35_capacity': False,
            'force_70_plus_capacity': False,
            'prefer_70_plus_with_batching_fallback': False
        }
        
        # Simple capacity rules based on practical hours
        if practical_hours <= 2:
            # Rule 3: practical_hours <= 2 should always use 35-capacity labs (with batching if needed)
            strategy['force_35_capacity'] = True
            strategy['preferred_lab_capacities'] = [35]
        elif practical_hours == 6:
            # Rule NEW: practical_hours == 6 PREFERS 70+ capacity labs but allows batching fallback
            strategy['prefer_70_plus_with_batching_fallback'] = True
            strategy['preferred_lab_capacities'] = [70, 140, 35]  # 70+ preferred, 35 as fallback
        elif practical_hours >= 5:
            # Rule 2: practical_hours >= 5 (but not 6) PREFERS 70+ capacity labs but allows batching fallback
            strategy['prefer_70_plus_with_batching_fallback'] = True
            strategy['preferred_lab_capacities'] = [70, 140, 35]  # 70+ preferred, 35 as fallback
        elif practical_hours == 4:
            # Rule NEW: practical_hours == 4 PREFERS 70+ capacity labs but allows batching fallback
            strategy['prefer_70_plus_with_batching_fallback'] = True
            strategy['preferred_lab_capacities'] = [70, 140, 35]  # 70+ preferred, 35 as fallback
        else:
            # Rule 4: practical_hours 3 or less can use either strategy (solver decides)
            strategy['preferred_lab_capacities'] = [35, 70, 140]
        
        return strategy
    
    def analyze_lab_capacity(self):
        """Analyze lab capacity distribution."""
        # Categorize labs by capacity
        labs_35 = []
        labs_70 = []
        labs_140 = []
        
        for _, lab in self.lab_rooms.iterrows():
            capacity = lab['room_max_cap']
            lab_info = {
                'id': lab['id'],
                'room_number': lab['room_number'],
                'capacity': capacity,
                'block': lab.get('block', ''),
                'description': lab.get('description', '')
            }
            
            if capacity <= 35:
                labs_35.append(lab_info)
            elif capacity <= 70:
                labs_70.append(lab_info)
            else:
                labs_140.append(lab_info)
        
        # Store the analysis
        self.lab_capacity_analysis = {
            'labs_35': labs_35,
            'labs_70': labs_70,
            'labs_140': labs_140,
            'total_35': len(labs_35),
            'total_70': len(labs_70),
            'total_140': len(labs_140),
            'total_labs': len(self.lab_rooms)
        }
        
        # Log capacity analysis
        self.logger.info(f"Lab capacity analysis:")
        self.logger.info(f"  - 35 capacity labs: {len(labs_35)}")
        self.logger.info(f"  - 70 capacity labs: {len(labs_70)}")
        self.logger.info(f"  - 140 capacity labs: {len(labs_140)}")
    
    def analyze_constraint_feasibility(self):
        """Analyze if the lab requirements can be satisfied with available resources."""
        total_lab_slots_needed = sum(sum(c['base_sessions'] for c in courses) 
                                   for teacher, courses in self.lab_requirements.items())
        
        # Calculate total lab capacity per week
        total_labs = len(self.lab_room_ids)
        lab_sessions_per_week = len(self.lab_sessions) * self.num_days  # 6 sessions * 5 days = 30
        total_lab_capacity = total_labs * lab_sessions_per_week
        
        self.logger.info(f"Constraint feasibility analysis:")
        self.logger.info(f"  - Total lab slots needed: {total_lab_slots_needed}")
        self.logger.info(f"  - Total lab rooms: {total_labs}")
        self.logger.info(f"  - Lab sessions per week: {lab_sessions_per_week}")
        self.logger.info(f"  - Total lab capacity: {total_lab_capacity}")
        self.logger.info(f"  - Utilization: {total_lab_slots_needed / total_lab_capacity * 100:.1f}%")
        
        if total_lab_slots_needed > total_lab_capacity:
            self.logger.error(f"INFEASIBLE: Need {total_lab_slots_needed} slots but only have {total_lab_capacity} capacity")
            return False
        
        return True
    
    def generate_lab_schedule(self):
        """Generate the lab schedule using OR-Tools CP-SAT solver."""
        self.logger.info("Starting lab schedule generation...")
        
        # Analyze lab capacity
        self.analyze_lab_capacity()
        
        # Check constraint feasibility before creating model
        if not self.analyze_constraint_feasibility():
            self.logger.error("Lab scheduling is not feasible with current requirements and constraints")
            return False
        
        # Create the CP-SAT model
        model = cp_model.CpModel()
        
        # Define assignment variables (following reference implementation structure)
        # lab_assignments[course_instance_id][day][session][room_id] = 1 if this course is assigned to room in session on day
        lab_assignments = {}
        lab_sessions = list(self.lab_sessions.keys())  # ['L1', 'L2', 'L3', 'L4', 'L5', 'L6']
        
        # Create variables for each course that needs lab time
        for teacher_id, courses in self.lab_requirements.items():
            for course in courses:
                course_instance_id = course['course_instance_id']
                
                if course_instance_id not in lab_assignments:
                    lab_assignments[course_instance_id] = {}
                    
                    for day_idx in range(self.num_days):
                        lab_assignments[course_instance_id][day_idx] = {}
                        
                        for session_idx in range(len(lab_sessions)):
                            session_name = lab_sessions[session_idx]
                            lab_assignments[course_instance_id][day_idx][session_idx] = {}
                            
                            for room_id in self.lab_room_ids:
                                lab_assignments[course_instance_id][day_idx][session_idx][room_id] = model.NewBoolVar(
                                    f'course_{course_instance_id}_day_{day_idx}_session_{session_idx}_lab_{room_id}')
        
        # Log that course-group distribution heatmap was already generated during initialization
        self.logger.info("📊 Course-group distribution heatmap was generated during initialization (before constraints)")
        self.logger.info("🔧 Now applying CP-SAT constraints to find optimal time slot assignments...")
        
        # Apply constraints (with group-based scheduling logic)
        self.apply_lab_constraints(model, lab_assignments, lab_sessions)
        
        # Add efficiency optimization objective
        self.add_efficiency_objective(model, lab_assignments, lab_sessions)
        
        # Log model statistics before solving
        self.logger.info("="*60)
        self.logger.info("MODEL STATISTICS")
        self.logger.info("="*60)
        model_stats = model.Proto()
        self.logger.info(f"Variables: {len(model_stats.variables)}")
        self.logger.info(f"Constraints: {len(model_stats.constraints)}")
        
        # Count different types of variables
        bool_vars = sum(1 for var in model_stats.variables if var.domain == [0, 1])
        int_vars = len(model_stats.variables) - bool_vars
        self.logger.info(f"  - Boolean variables: {bool_vars}")
        self.logger.info(f"  - Integer variables: {int_vars}")
        
        # Count course instances and rooms
        total_course_instances = len(lab_assignments)
        total_rooms = len(self.lab_room_ids)
        total_time_slots = self.num_days * len(self.lab_sessions)
        
        self.logger.info(f"Problem dimensions:")
        self.logger.info(f"  - Course instances: {total_course_instances}")
        self.logger.info(f"  - Lab rooms: {total_rooms}")
        self.logger.info(f"  - Time slots: {total_time_slots} ({self.num_days} days × {len(self.lab_sessions)} sessions)")
        self.logger.info(f"  - Total assignment possibilities: {total_course_instances * total_rooms * total_time_slots:,}")
        
        # Create the solver and solve the model
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 1200  # 10 minutes time limit for better solutions
        solver.parameters.num_search_workers = 16  # Use 16 threads for parallel solving
        solver.parameters.log_search_progress = True  # Enable search progress logging
        solver.parameters.cp_model_presolve = True  # Enable presolving
        solver.parameters.cp_model_probing_level = 2  # Enhanced probing
        
        self.logger.info("Solving the lab scheduling model...")
        self.logger.info(f"Solver configuration:")
        self.logger.info(f"  - Time limit: {solver.parameters.max_time_in_seconds} seconds")
        self.logger.info(f"  - Threads: {solver.parameters.num_search_workers}")
        self.logger.info(f"  - Progress logging: {solver.parameters.log_search_progress}")
        self.logger.info(f"  - Presolving: {solver.parameters.cp_model_presolve}")
        self.logger.info(f"  - Probing level: {solver.parameters.cp_model_probing_level}")
        
        # Create a callback to log progress
        class SolutionCallback(cp_model.CpSolverSolutionCallback):
            def __init__(self, logger):
                cp_model.CpSolverSolutionCallback.__init__(self)
                self.logger = logger
                self.solution_count = 0
                self.start_time = datetime.now()
                
            def on_solution_callback(self):
                self.solution_count += 1
                current_time = datetime.now()
                elapsed = (current_time - self.start_time).total_seconds()
                
                self.logger.info(f"Solution #{self.solution_count} found at {elapsed:.1f}s")
                self.logger.info(f"  - Objective value: {self.ObjectiveValue()}")
                self.logger.info(f"  - Wall time: {elapsed:.2f}s")
                
                # Stop after finding first feasible solution for now
                # Remove this if you want to find optimal solution
                self.StopSearch() # Removed to allow searching for optimal solution
        
        solution_callback = SolutionCallback(self.logger)
        
        self.logger.info("Starting OR-Tools CP-SAT solver...")
        status = solver.Solve(model, solution_callback)
        
        # Log detailed solver statistics
        self.logger.info("="*60)
        self.logger.info("SOLVER STATISTICS")
        self.logger.info("="*60)
        self.logger.info(f"Status: {solver.StatusName(status)}")
        self.logger.info(f"Wall time: {solver.WallTime():.2f} seconds")
        self.logger.info(f"User time: {solver.UserTime():.2f} seconds")
        self.logger.info(f"Branches: {solver.NumBranches()}")
        self.logger.info(f"Conflicts: {solver.NumConflicts()}")
        self.logger.info(f"Response summary: {'Available' if solver.ResponseStats else 'Not available'}")
        
        if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
            if status == cp_model.OPTIMAL:
                self.logger.info("V Optimal solution found!")
            else:
                self.logger.info("V Feasible solution found!")
            
            # Extract and save the schedule
            lab_schedule = self.extract_lab_schedule(solver, lab_assignments, lab_sessions)
            
            # Save the schedule
            self.save_lab_schedule(lab_schedule)
            return True
        else:
            self.logger.error(f"X No solution found. Status: {solver.StatusName(status)}")
            self.logger.error("The problem is INFEASIBLE - constraints are conflicting")
            self.logger.error("Suggestions:")
            self.logger.error("  1. Check if teacher assignments are realistic")
            self.logger.error("  2. Verify room capacity constraints")
            self.logger.error("  3. Review group-based scheduling rules")
            self.logger.error("  4. Consider increasing time limit or relaxing constraints")
            
            return False
    
    def apply_lab_constraints(self, model, lab_assignments, lab_sessions):
        """Applies all the necessary constraints for lab scheduling."""
        self.logger.info("Applying all lab scheduling constraints...")
        
        # Core constraints
        self.apply_course_lab_requirements_constraint(model, lab_assignments)
        self.apply_lab_room_single_assignment_constraint(model, lab_assignments, lab_sessions)
        self.apply_teacher_clash_constraint(model, lab_assignments, lab_sessions)
        self.apply_capacity_constraint(model, lab_assignments)
        self.apply_group_based_scheduling_constraint(model, lab_assignments)
        
        # Conflict constraints
        self.apply_theory_lab_group_conflict_constraint(model, lab_assignments, lab_sessions)
        
        # Semester-level constraints
        self.apply_semester_lab_slot_limit_constraint(model, lab_assignments)

        # Final mapping constraints
        self.apply_core_lab_mapping_constraint(model, lab_assignments)
        
        self.logger.info("All lab constraints applied successfully.")

    def apply_course_lab_requirements_constraint(self, model, lab_assignments):
        """CONSTRAINT: Each course must be scheduled for its required number of lab sessions."""
        self.logger.info("Applying course lab requirements constraint...")
        
        for teacher, courses in self.lab_requirements.items():
            for course in courses:
                course_instance_id = course['course_instance_id']
                base_sessions = course['base_sessions']  # Base sessions needed (without batching)
                
                if course_instance_id in lab_assignments:
                    # Count total assignments for this course instance
                    total_assignments = []
                    
                    for day_idx in range(self.num_days):
                        for session_idx in range(len(self.lab_sessions)):
                            for room_id in self.lab_room_ids:
                                total_assignments.append(lab_assignments[course_instance_id][day_idx][session_idx][room_id])
                    
                    # Get lab capacity categories
                    labs_35 = [lab['id'] for lab in self.lab_capacity_analysis['labs_35']]
                    
                    # Calculate expected sessions based on potential batching
                    student_count = course['students_per_instance']
                    
                    # If course might be assigned to 35-cap labs and has >35 students, plan for batching
                    assignments_in_35_cap = []
                    assignments_in_70_plus_cap = []
                    
                    for day_idx in range(self.num_days):
                        for session_idx in range(len(self.lab_sessions)):
                            for room_id in self.lab_room_ids:
                                assignment_var = lab_assignments[course_instance_id][day_idx][session_idx][room_id]
                                if room_id in labs_35:
                                    assignments_in_35_cap.append(assignment_var)
                                else:
                                    assignments_in_70_plus_cap.append(assignment_var)
                    
                    # Create conditional constraint based on lab capacity assignment
                    if student_count > 35:
                        # CRITICAL: Either ALL sessions in 35-cap (with batching) OR ALL sessions in 70+ cap (no batching)
                        # NOT BOTH strategies for the same course
                        total_35_assignments = sum(assignments_in_35_cap)
                        total_70_plus_assignments = sum(assignments_in_70_plus_cap)
                        
                        # Calculate sessions needed for batching in 35-cap labs
                        num_batches_35 = (student_count + 34) // 35
                        sessions_with_batching = base_sessions * num_batches_35
                        
                        # APPLY SLOT RESTRICTIONS BASED ON PRACTICAL HOURS
                        practical_hours = course['practical_hours']
                        
                        # Restrict batched sessions based on practical hours
                        if practical_hours >= 6:
                            # 6+ practical hours: Allow up to 6 slots if batched, max 3 if not batched
                            max_batched_sessions = min(sessions_with_batching, 6)
                            max_unbatched_sessions = min(base_sessions, 3)
                        elif practical_hours >= 4:
                            # 4+ practical hours: Allow up to 4 slots if batched, max 2 if not batched (70+ lab)
                            max_batched_sessions = min(sessions_with_batching, 4)
                            max_unbatched_sessions = min(base_sessions, 2)  # 4h course in 70+ lab -> 2 sessions
                        else:
                            # 2 practical hours: Maximum 2 slots if batched, 1 if not batched
                            max_batched_sessions = min(sessions_with_batching, 2)
                            max_unbatched_sessions = min(base_sessions, 1)  # 2h course in 70+ lab -> 1 session
                        
                        # Boolean variable to choose strategy: True = use 35-cap labs, False = use 70+ cap labs
                        use_35_cap_strategy = model.NewBoolVar(f'course_{course_instance_id}_use_35_cap_strategy')
                        
                        # Constraint 1: If using 35-cap strategy, ALL sessions must be in 35-cap labs
                        model.Add(total_35_assignments == sum(total_assignments)).OnlyEnforceIf(use_35_cap_strategy)
                        model.Add(total_70_plus_assignments == 0).OnlyEnforceIf(use_35_cap_strategy)
                        
                        # Constraint 2: If using 70+ cap strategy, ALL sessions must be in 70+ cap labs  
                        model.Add(total_70_plus_assignments == sum(total_assignments)).OnlyEnforceIf(use_35_cap_strategy.Not())
                        model.Add(total_35_assignments == 0).OnlyEnforceIf(use_35_cap_strategy.Not())
                        
                        # Constraint 3: Session count depends on chosen strategy WITH SLOT RESTRICTIONS
                        model.Add(sum(total_assignments) == max_batched_sessions).OnlyEnforceIf(use_35_cap_strategy)
                        model.Add(sum(total_assignments) == max_unbatched_sessions).OnlyEnforceIf(use_35_cap_strategy.Not())
                        
                        # ENFORCE MAXIMUM SLOT CONSTRAINTS BASED ON PRACTICAL HOURS
                        if practical_hours >= 6:
                            # For 6+ practical hours: max 6 if batched, max 3 if not batched
                            model.Add(sum(total_assignments) <= 6).OnlyEnforceIf(use_35_cap_strategy)
                            model.Add(sum(total_assignments) <= 3).OnlyEnforceIf(use_35_cap_strategy.Not())
                        elif practical_hours >= 4:
                            # For 4+ practical hours: max 4 if batched, max 2 if not batched
                            model.Add(sum(total_assignments) <= 4).OnlyEnforceIf(use_35_cap_strategy)
                            model.Add(sum(total_assignments) <= 2).OnlyEnforceIf(use_35_cap_strategy.Not())
                        else:
                            # For 2 practical hours: max 2 if batched, max 1 if not batched
                            model.Add(sum(total_assignments) <= 2).OnlyEnforceIf(use_35_cap_strategy)
                            model.Add(sum(total_assignments) <= 1).OnlyEnforceIf(use_35_cap_strategy.Not())
                        
                        self.logger.info(f"Course {course['course_code']} ({practical_hours}h): EITHER {max_batched_sessions} sessions (35-cap batched) OR {max_unbatched_sessions} sessions (70+ cap unbatched)")
                    else:
                        # Small courses: always base sessions, but enforce max 4 slots
                        max_sessions = min(base_sessions, 4)
                        model.Add(sum(total_assignments) == max_sessions)
                        self.logger.info(f"Course {course['course_code']}: exactly {max_sessions} sessions (max 4 slots enforced)")
    
    def apply_lab_room_single_assignment_constraint(self, model, lab_assignments, lab_sessions):
        """Prevent lab room double-booking."""
        self.logger.info("Applying lab room single assignment constraint...")
        
        for room_id in self.lab_room_ids:
            for day_idx in range(self.num_days):
                for session_idx in range(len(lab_sessions)):
                    # Each lab room can have at most one course per session
                    room_vars = []
                    for course_instance_id in lab_assignments.keys():
                        room_vars.append(lab_assignments[course_instance_id][day_idx][session_idx][room_id])
                    model.Add(sum(room_vars) <= 1)
    
    def apply_teacher_clash_constraint(self, model, lab_assignments, lab_sessions):
        """Ensure a teacher is not assigned to more than one lab at the same time."""
        self.logger.info("Applying teacher clash constraint (global)...")
        
        # Group course instances by teacher
        teacher_assignments = defaultdict(list)
        for course_instance_id, teacher_id in self.course_to_teacher.items():
            if course_instance_id in lab_assignments:
                teacher_assignments[teacher_id].append(course_instance_id)

        # Get all teacher IDs that have lab assignments
        all_teacher_ids = list(teacher_assignments.keys())
        
        constraints_applied = 0
        for teacher_id in all_teacher_ids:
            if teacher_id in teacher_assignments:
                courses = teacher_assignments[teacher_id]
                for day_idx in range(self.num_days):
                    for session_idx in range(len(lab_sessions)):
                        teacher_session_assignments = []
                        for course_instance_id in courses:
                            if course_instance_id in lab_assignments:
                                for room_id in self.lab_room_ids:
                                    teacher_session_assignments.append(
                                        lab_assignments[course_instance_id][day_idx][session_idx][room_id]
                                    )
                        
                        if teacher_session_assignments:
                            model.Add(sum(teacher_session_assignments) <= 1)
                            constraints_applied += 1
                            
        self.logger.info(f"Applied {constraints_applied} global teacher clash constraints for {len(all_teacher_ids)} teachers (main and assistants)")
    
    def apply_capacity_constraint(self, model, lab_assignments):
        """Apply capacity-based assignment constraints."""
        self.logger.info("Applying capacity-based assignment constraint...")
        
        # Get lab rooms categorized by capacity
        labs_35 = [lab['id'] for lab in self.lab_capacity_analysis['labs_35']]
        labs_70_plus = [lab['id'] for lab in self.lab_capacity_analysis['labs_70']] + [lab['id'] for lab in self.lab_capacity_analysis['labs_140']]
        
        for teacher, courses in self.lab_requirements.items():
            for course in courses:
                course_instance_id = course['course_instance_id']
                practical_hours = course['practical_hours']
                force_35_capacity = course.get('force_35_capacity', False)
                force_70_plus_capacity = course.get('force_70_plus_capacity', False)
                prefer_70_plus_with_batching_fallback = course.get('prefer_70_plus_with_batching_fallback', False)
                
                if force_35_capacity or practical_hours <= 3:
                    # Courses with 3 or fewer practical hours must use 35-capacity labs only
                    for day_idx in range(self.num_days):
                        for session_idx in range(len(self.lab_sessions)):
                            for room_id in labs_70_plus:
                                model.Add(lab_assignments[course_instance_id][day_idx][session_idx][room_id] == 0)
                    
                    self.logger.info(f"Course {course['course_code']} (practical_hours={practical_hours}) restricted to 35-capacity labs")
                elif prefer_70_plus_with_batching_fallback:
                    # Courses with 6 practical hours prefer 70+ but can use 35 with batching
                    # Create a preference variable to encourage 70+ labs
                    prefer_70_plus = model.NewBoolVar(f'course_{course_instance_id}_prefer_70_plus')
                    
                    # Count assignments in 70+ capacity labs
                    assignments_70_plus = []
                    assignments_35 = []
                    
                    for day_idx in range(self.num_days):
                        for session_idx in range(len(self.lab_sessions)):
                            for room_id in labs_70_plus:
                                assignments_70_plus.append(lab_assignments[course_instance_id][day_idx][session_idx][room_id])
                            for room_id in labs_35:
                                assignments_35.append(lab_assignments[course_instance_id][day_idx][session_idx][room_id])
                    
                    # If prefer_70_plus is true, then all assignments should be in 70+ labs
                    if assignments_70_plus and assignments_35:
                        total_assignments = assignments_70_plus + assignments_35
                        
                        # Preference constraint: if prefer_70_plus = 1, then use only 70+ labs
                        model.Add(sum(assignments_35) == 0).OnlyEnforceIf(prefer_70_plus)
                        model.Add(sum(assignments_70_plus) == sum(total_assignments)).OnlyEnforceIf(prefer_70_plus)
                        
                        # If prefer_70_plus = 0, then we can use 35-cap labs (batching allowed)
                        # No restriction when prefer_70_plus = 0
                        
                        # Store preference for objective (encourage 70+ usage)
                        if not hasattr(self, 'capacity_preferences'):
                            self.capacity_preferences = []
                        self.capacity_preferences.append(prefer_70_plus * 10)  # Bonus for using 70+ labs
                    
                    self.logger.info(f"Course {course['course_code']} (practical_hours={practical_hours}) PREFERS 70+ capacity labs, allows 35-capacity fallback with batching")
                elif force_70_plus_capacity:
                    # Courses with force_70_plus_capacity flag must use 70+ capacity labs only
                    for day_idx in range(self.num_days):
                        for session_idx in range(len(self.lab_sessions)):
                            for room_id in labs_35:
                                model.Add(lab_assignments[course_instance_id][day_idx][session_idx][room_id] == 0)
                    
                    self.logger.info(f"Course {course['course_code']} (practical_hours={practical_hours}) restricted to 70+ capacity labs")
                else:
                    # Courses with 4 practical hours can use any lab
                    self.logger.info(f"Course {course['course_code']} (practical_hours={practical_hours}) can use any capacity lab")
    
    def apply_group_based_scheduling_constraint(self, model, lab_assignments):
        """Apply group-based scheduling constraints to enforce scheduling by groups."""
        self.logger.info("Applying group-based scheduling constraints...")
        
        # Group course instances by department, semester, and group
        semester_groups = defaultdict(lambda: defaultdict(list))
        unassigned_instances = []
        
        for course_instance_id in lab_assignments.keys():
            group_info = self.get_group_info_for_course_instance(course_instance_id)
            dept = group_info['department']
            semester = group_info['semester']
            group_index = group_info['group_index']
            
            if group_index > 0:  # Valid group
                semester_groups[(dept, semester)][group_index].append(course_instance_id)
            else:  # Unassigned/invalid group
                unassigned_instances.append(course_instance_id)
        
        # Create default groups for unassigned instances
        if unassigned_instances:
            self.logger.info(f"Creating default groups for {len(unassigned_instances)} unassigned instances")
            
            # Group instances by course code to keep related courses together
            course_code_groups = defaultdict(list)
            for instance_id in unassigned_instances:
                course_code = None
                for teacher, courses in self.lab_requirements.items():
                    for course in courses:
                        if course['course_instance_id'] == instance_id:
                            course_code = course['course_code']
                            break
                    if course_code:
                        break
                
                if course_code:
                    course_code_groups[course_code].append(instance_id)
                else:
                    # Fallback if course code not found
                    course_code_groups['unknown'].append(instance_id)
            
            # Create more balanced default groups
            default_dept = "Default"
            default_groups = []
            
            # First, sort course groups by size (descending)
            sorted_course_groups = sorted(course_code_groups.items(), key=lambda x: len(x[1]), reverse=True)
            
            # Group instances with a maximum of 4 instances per group to ensure 4-slot limit
            current_group = []
            current_size = 0
            max_group_size = 4  # Maximum instances per default group
            
            for course_code, instances in sorted_course_groups:
                if current_size + len(instances) <= max_group_size:
                    # This course can fit in the current group
                    current_group.extend(instances)
                    current_size += len(instances)
                else:
                    # This course would exceed the max size, start a new group
                    if current_group:
                        default_groups.append(current_group)
                    
                    # Handle the case where a single course has more than max instances
                    if len(instances) > max_group_size:
                        # Split this course into multiple groups
                        for i in range(0, len(instances), max_group_size):
                            chunk = instances[i:i+max_group_size]
                            default_groups.append(chunk)
                    else:
                        current_group = instances.copy()
                        current_size = len(instances)
            
            # Add the last group if not empty
            if current_group:
                default_groups.append(current_group)
            
            # Add the default groups to semester_groups
            for i, group in enumerate(default_groups):
                group_index = i + 1
                semester_id = (i // 5) + 1  # Create different semesters to avoid conflicts
                semester_groups[(default_dept, semester_id)][group_index] = group
                self.logger.info(f"Default group {group_index} (semester {semester_id}): {len(group)} instances")
        
        constraints_applied = 0
        
        # CONSTRAINT 1: Same-semester group non-overlap
        for (dept, semester), groups in semester_groups.items():
            self.logger.info(f"Applying group constraints for {dept} Semester {semester}: {len(groups)} groups")
            
            # For each time slot, ensure at most one group from this semester is active
            for day_idx in range(self.num_days):
                for session_idx in range(len(self.lab_sessions)):
                    # For each time slot, collect usage variables for each group
                    group_usages = {}
                    
                    for group_idx, course_instances in groups.items():
                        group_usage_vars = []
                        
                        for course_instance_id in course_instances:
                            for room_id in self.lab_room_ids:
                                group_usage_vars.append(lab_assignments[course_instance_id][day_idx][session_idx][room_id])
                    
                        if group_usage_vars:
                            # Create a variable indicating if this group uses this time slot
                            group_usage = model.NewBoolVar(f'group_usage_{dept}_S{semester}_G{group_idx}_day{day_idx}_session{session_idx}')
                    
                            # Link usage to the assignment variables
                            model.Add(group_usage <= sum(group_usage_vars))
                            # Any assignment makes the group usage 1
                            model.Add(sum(group_usage_vars) <= len(self.lab_room_ids) * group_usage)
                            
                            group_usages[group_idx] = group_usage
                    
                    # At most one group can use this time slot
                    if len(group_usages) > 1:
                        model.Add(sum(group_usages.values()) <= 1)
                        constraints_applied += 1
            
            # CONSTRAINT 2: Course instance uniqueness
        for course_instance_id in lab_assignments.keys():
            for day_idx in range(self.num_days):
                for session_idx in range(len(self.lab_sessions)):
                    session_assignments = []
                    for room_id in self.lab_room_ids:
                        session_assignments.append(lab_assignments[course_instance_id][day_idx][session_idx][room_id])
                    
                    if len(session_assignments) > 1:
                        model.Add(sum(session_assignments) <= 1)
                        constraints_applied += 1
        
        # CONSTRAINT 3: Dynamic group slot limit based on maximum practical hours and teacher availability
        for (dept, semester), groups in semester_groups.items():
            for group_idx, course_instances in groups.items():
                # Calculate maximum practical hours and analyze teacher distribution
                max_practical_hours = 0
                unique_teachers = set()
                total_courses = len(course_instances)
                core_lab_courses = 0  # Count courses that are in core mapping
                
                for course_instance_id in course_instances:
                    for teacher, courses in self.lab_requirements.items():
                        for course in courses:
                            if course['course_instance_id'] == course_instance_id:
                                max_practical_hours = max(max_practical_hours, course['practical_hours'])
                                unique_teachers.add(teacher)
                                
                                # Check if this course is in core mapping
                                course_code = course['course_code']
                                # Get course name from the original courses data
                                course_row = self.courses_df[self.courses_df['id'] == int(course_instance_id)]
                                if not course_row.empty:
                                    course_name = course_row.iloc[0]['course_name']
                                    if (course_code, course_name) in self.course_to_room_mapping:
                                        core_lab_courses += 1
                                break
                
                # SMART RULE: Apply slot limits based on practical hours and batching requirements
                # EXCEPTION: If group contains core lab courses, don't limit slots
                if core_lab_courses > 0:
                    slot_limit = None  # No slot limit for groups with core lab courses
                    strategy_note = f"NO SLOT LIMIT for group with {core_lab_courses} core lab courses"
                elif max_practical_hours <= 2:
                    # For 2-hour practical courses, always limit to 2 slots
                    slot_limit = 2  # Always 2 lab slots for 2-hour courses - forces parallelization
                elif max_practical_hours == 4:
                    # 4-hour courses prefer 70+ capacity labs but allow batching fallback
                    # Check if any course in this group might need batching (>35 students and limited 70+ labs)
                    needs_batching_fallback = False
                    
                    for course_instance_id in course_instances:
                        for teacher, courses in self.lab_requirements.items():
                            for course in courses:
                                if course['course_instance_id'] == course_instance_id:
                                    practical_hours = course.get('practical_hours', 0)
                                    student_count = course.get('student_count', 70)
                                    
                                    # If course has >35 students, it might need batching fallback
                                    if practical_hours == 4 and student_count > 35:
                                        needs_batching_fallback = True
                                    break
                    
                    if needs_batching_fallback:
                        # Allow more slots for potential batching, but prefer 2 slots
                        slot_limit = 4  # Allow up to 4 slots for 4-hour courses with batching fallback
                        strategy_note = "2-4 slots for 4-hour courses (prefers 70+ labs, batching fallback available)"
                    else:
                        # Courses with ≤35 students will use 70+ capacity labs (2 slots)
                        slot_limit = 2  # Standard limit for 4-hour courses in 70+ capacity labs
                        strategy_note = "2 slots for 4-hour courses using 70+ capacity labs"
                elif max_practical_hours >= 6:
                    # 6+ hour courses prefer 70+ capacity labs but allow batching fallback
                    # Check if any course in this group might need batching (>35 students and limited 70+ labs)
                    needs_batching_fallback = False
                    
                    for course_instance_id in course_instances:
                        for teacher, courses in self.lab_requirements.items():
                            for course in courses:
                                if course['course_instance_id'] == course_instance_id:
                                    practical_hours = course.get('practical_hours', 0)
                                    student_count = course.get('student_count', 70)
                                    
                                    # If course has >35 students, it might need batching fallback
                                    if practical_hours >= 6 and student_count > 35:
                                        needs_batching_fallback = True
                                    break
                    
                    if needs_batching_fallback:
                        # Allow more slots for potential batching, but prefer 3 slots
                        slot_limit = 6  # Allow up to 6 slots for 6+ hour courses with batching fallback
                        strategy_note = "3-6 slots for 6+ hour courses (prefers 70+ labs, batching fallback available)"
                    else:
                        # Courses with ≤35 students will use 70+ capacity labs (3 slots)
                        slot_limit = 3  # Standard limit for 6+ hour courses in 70+ capacity labs
                        strategy_note = "3 slots for 6+ hour courses using 70+ capacity labs"
                else:
                    slot_limit = 4  # Default 4 lab slots for groups with 3-5 practical hours
                
                # Track all used time slots for this group
                group_slot_usage = []
                
                for day_idx in range(self.num_days):
                    for session_idx in range(len(self.lab_sessions)):
                        # Create a variable indicating if this group uses this time slot
                        group_slot_var = model.NewBoolVar(f'group_slot_{dept}_S{semester}_G{group_idx}_day{day_idx}_session{session_idx}')
                        
                        # Collect all assignment variables for this group at this time slot
                        slot_assignments = []
                        for course_instance_id in course_instances:
                            for room_id in self.lab_room_ids:
                                slot_assignments.append(lab_assignments[course_instance_id][day_idx][session_idx][room_id])
                        
                        if slot_assignments:
                            # group_slot_var = 1 if any course in this group uses this slot
                            model.Add(group_slot_var <= sum(slot_assignments))
                            model.Add(sum(slot_assignments) <= len(slot_assignments) * group_slot_var)
                            
                            # Add to the list of all used slots for this group
                            group_slot_usage.append(group_slot_var)
                
                # Constraint: Dynamic slot limit based on max practical hours (skip if slot_limit is None)
                if group_slot_usage and slot_limit is not None:
                    model.Add(sum(group_slot_usage) <= slot_limit)
                    constraints_applied += 1
                
                # Ensure all course instances in this group are assigned (always apply this)
                required_instances = 0
                for course_instance_id in course_instances:
                    for teacher, courses in self.lab_requirements.items():
                        for course in courses:
                            if course['course_instance_id'] == course_instance_id:
                                required_instances += 1
                
                # Calculate assignments across all slots for this group
                group_assignments = []
                for day_idx in range(self.num_days):
                    for session_idx in range(len(self.lab_sessions)):
                        for course_instance_id in course_instances:
                            for room_id in self.lab_room_ids:
                                group_assignments.append(lab_assignments[course_instance_id][day_idx][session_idx][room_id])
                
                # Ensure all required instances are assigned
                if group_assignments:
                    model.Add(sum(group_assignments) >= required_instances)
                    constraints_applied += 1
                        
                    group_type = "Default" if dept == "Default" else "Regular"
                    
                    # Determine scheduling strategy note if not already set
                    if slot_limit is not None and 'strategy_note' not in locals():
                        if max_practical_hours <= 2:
                            strategy_note = "STRICT 2-SLOT LIMIT (forces parallelization)"
                        elif max_practical_hours >= 6:
                            # strategy_note already set above in the elif block
                            pass
                        else:
                            strategy_note = "allows flexible scheduling for 3-5 hour courses"
                    
                    if slot_limit is not None:
                        self.logger.info(f"{group_type} Group {dept}_S{semester}_G{group_idx}: limited to {slot_limit} slots for {total_courses} courses (max practical hours: {max_practical_hours}, teachers: {len(unique_teachers)}) - {strategy_note}")
                    else:
                        self.logger.info(f"{group_type} Group {dept}_S{semester}_G{group_idx}: NO SLOT LIMIT for {total_courses} courses (max practical hours: {max_practical_hours}, teachers: {len(unique_teachers)}) - {strategy_note}")
        
        # CONSTRAINT 4: Encourage same-group courses to run in parallel
        self.apply_same_group_parallelization_preference(model, lab_assignments, semester_groups)
        
        self.logger.info(f"Group-based scheduling constraints applied successfully: {constraints_applied} constraints")
        self.logger.info("✅ ENHANCED CONSTRAINT RULES:")
        self.logger.info("  1. Same group courses ENCOURAGED to overlap/run parallel (students take different courses)")
        self.logger.info("  2. Different groups in same semester CANNOT overlap (strict enforcement)")
        self.logger.info("  3. Different semesters CAN overlap (different student populations)")
        self.logger.info("  4. Teachers cannot teach multiple labs simultaneously (global constraint)")
        self.logger.info("  5. At most ONE group per semester can be active in any time slot")
        self.logger.info("  6. Same-group parallelization preference added to objective")
        self.logger.info("  7. SMART group slot limits: NO LIMIT for core lab courses, 2 slots if <=2 hours (strict), 2-4 slots if 4 hours (prefers 70+ labs, batching fallback), 3-6 slots if 6+ hours (prefers 70+ labs, batching fallback), else 4 slots")
        self.logger.info("  8. IMPROVED: Unassigned courses are now grouped by course code with balanced groups")
    
    def apply_same_group_parallelization_preference(self, model, lab_assignments, semester_groups):
        """Apply a preference for scheduling courses from the same group in parallel."""
        self.logger.info("Adding same-group parallelization preference to objective...")
        
        # This will store all of our parallelization bonus variables
        self.group_parallelization_vars = []
        self.graduated_parallelization_vars = {}
        
        # For each semester and group, encourage scheduling in parallel
        for (dept, semester), groups in semester_groups.items():
            for group_idx, course_instances in groups.items():
                if len(course_instances) <= 1:
                    continue  # Skip groups with only one course
                
                # For each time slot, check if multiple courses from this group are scheduled
                for day_idx in range(self.num_days):
                    for session_idx in range(len(self.lab_sessions)):
                        # Collect all assignment variables for this group at this time slot
                        course_assignments = []
                        
                        for course_instance_id in course_instances:
                            # Create a variable indicating if this course is scheduled at this time
                            course_scheduled = model.NewBoolVar(
                                f'course_{course_instance_id}_scheduled_day{day_idx}_session{session_idx}'
                            )
                            
                            # Collect room assignments for this course at this time
                            room_assignments = []
                            for room_id in self.lab_room_ids:
                                room_assignments.append(lab_assignments[course_instance_id][day_idx][session_idx][room_id])
                        
                            # Link course_scheduled to room assignments
                            if room_assignments:
                                model.Add(course_scheduled <= sum(room_assignments))
                                model.Add(sum(room_assignments) <= len(room_assignments) * course_scheduled)
                                
                                # Add to the list of courses that might be scheduled at this time
                                course_assignments.append(course_scheduled)
                        
                        # If we have multiple potential courses for this time slot
                        if len(course_assignments) >= 2:
                            # Create graduated bonus variables for different levels of parallelization
                            # We'll give higher bonuses for scheduling more courses in parallel
                            
                            # Base case: Bonus for scheduling at least 2 courses in parallel
                            parallel_bonus_2 = model.NewBoolVar(
                                f'parallel_bonus_2_{dept}_S{semester}_G{group_idx}_day{day_idx}_session{session_idx}'
                            )
                            
                            # This is true if at least 2 courses are scheduled
                            model.Add(sum(course_assignments) >= 2).OnlyEnforceIf(parallel_bonus_2)
                            model.Add(sum(course_assignments) < 2).OnlyEnforceIf(parallel_bonus_2.Not())
                            
                            # Add to our list of objective terms with higher weight (+8)
                            self.group_parallelization_vars.append(parallel_bonus_2 * 8)
                            
                            # If we have 3+ potential courses, add graduated bonuses
                            if len(course_assignments) >= 3:
                                # Bonus for scheduling at least 3 courses in parallel
                                parallel_bonus_3 = model.NewBoolVar(
                                    f'parallel_bonus_3_{dept}_S{semester}_G{group_idx}_day{day_idx}_session{session_idx}'
                                )
                                
                                model.Add(sum(course_assignments) >= 3).OnlyEnforceIf(parallel_bonus_3)
                                model.Add(sum(course_assignments) < 3).OnlyEnforceIf(parallel_bonus_3.Not())
                            
                                # Even higher weight for 3+ courses (+12)
                                self.group_parallelization_vars.append(parallel_bonus_3 * 12)
                                
                                # If we have 4+ potential courses, add more graduated bonuses
                                if len(course_assignments) >= 4:
                                    # Bonus for scheduling at least 4 courses in parallel
                                    parallel_bonus_4 = model.NewBoolVar(
                                        f'parallel_bonus_4_{dept}_S{semester}_G{group_idx}_day{day_idx}_session{session_idx}'
                                    )
                                    
                                    model.Add(sum(course_assignments) >= 4).OnlyEnforceIf(parallel_bonus_4)
                                    model.Add(sum(course_assignments) < 4).OnlyEnforceIf(parallel_bonus_4.Not())
                                    
                                    # Even higher weight for 4+ courses (+16)
                                    self.group_parallelization_vars.append(parallel_bonus_4 * 16)
                                    
                                    # If we have 5+ potential courses, add more graduated bonuses
                                    if len(course_assignments) >= 5:
                                        # Bonus for scheduling at least 5 courses in parallel
                                        parallel_bonus_5 = model.NewBoolVar(
                                            f'parallel_bonus_5_{dept}_S{semester}_G{group_idx}_day{day_idx}_session{session_idx}'
                                        )
                                        
                                        model.Add(sum(course_assignments) >= 5).OnlyEnforceIf(parallel_bonus_5)
                                        model.Add(sum(course_assignments) < 5).OnlyEnforceIf(parallel_bonus_5.Not())
                                        
                                        # Highest weight for 5+ courses (+20)
                                        self.group_parallelization_vars.append(parallel_bonus_5 * 20)
        
        self.logger.info(f"Added {len(self.group_parallelization_vars)} parallelization bonus variables to objective")
        self.logger.info("📊 Graduated parallelization bonus weights:")
        self.logger.info("  • 2 courses in parallel: +8 (was +4)")
        self.logger.info("  • 3 courses in parallel: +12 (was +6)")
        self.logger.info("  • 4 courses in parallel: +16 (new!)")
        self.logger.info("  • 5+ courses in parallel: +20 (new!)")
        self.logger.info("This combined with the 4-slot limit will strongly encourage parallel scheduling")
    
    def apply_max_consecutive_lab_slots_constraint(self, model, lab_assignments, lab_sessions):
        """Creates penalty variables for teachers having more than 2 consecutive lab sessions."""
        self.logger.info("Creating penalties for more than 2 consecutive lab slots (teacher exhaustion)...")

        self.teacher_exhaustion_penalties = []

        teacher_courses = {}
        for course_instance_id, teacher_id in self.course_to_teacher.items():
            if teacher_id not in teacher_courses:
                teacher_courses[teacher_id] = []
            teacher_courses[teacher_id].append(course_instance_id)

        consecutive_triplets = [
            [0, 1, 2],  # L1, L2, L3
            [1, 2, 3],  # L2, L3, L4
            [2, 3, 4],  # L3, L4, L5
            [3, 4, 5],  # L4, L5, L6
        ]

        for teacher_id, course_list in teacher_courses.items():
            for day_idx in range(self.num_days):
                # For each session, determine if the teacher is active
                teacher_session_active = []
                for session_idx in range(len(lab_sessions)):
                    is_active = model.NewBoolVar(f'teacher{teacher_id}_day{day_idx}_session{session_idx}_active')
                    assignments_in_session = []
                    if course_list:
                        for course_instance_id in course_list:
                            if course_instance_id in lab_assignments:
                                for room_id in self.lab_room_ids:
                                    assignments_in_session.append(
                                        lab_assignments[course_instance_id][day_idx][session_idx][room_id])

                    if assignments_in_session:
                        model.Add(sum(assignments_in_session) > 0).OnlyEnforceIf(is_active)
                        model.Add(sum(assignments_in_session) == 0).OnlyEnforceIf(is_active.Not())
                    else:
                        model.Add(is_active == 0)
                    teacher_session_active.append(is_active)

                # Check for 3 consecutive active sessions
                for triplet in consecutive_triplets:
                    session1_active = teacher_session_active[triplet[0]]
                    session2_active = teacher_session_active[triplet[1]]
                    session3_active = teacher_session_active[triplet[2]]

                    # A penalty is incurred if all three sessions in the triplet are active
                    is_exhausting_triplet = model.NewBoolVar(
                        f'teacher{teacher_id}_day{day_idx}_triplet{triplet[0]}_exhausting')
                    model.AddBoolAnd([session1_active, session2_active, session3_active]).OnlyEnforceIf(
                        is_exhausting_triplet)
                    model.AddImplication(is_exhausting_triplet, session1_active)
                    model.AddImplication(is_exhausting_triplet, session2_active)
                    model.AddImplication(is_exhausting_triplet, session3_active)

                    self.teacher_exhaustion_penalties.append(is_exhausting_triplet)

        self.logger.info(f"Created {len(self.teacher_exhaustion_penalties)} penalty variables for consecutive labs.")
    
    def apply_theory_lab_group_conflict_constraint(self, model, lab_assignments, lab_sessions):
        """Prevents lab groups from being scheduled at the same time as theory groups from the same dept/semester."""
        self.logger.info("Applying theory-lab group conflict constraint...")
        
        if not self.theory_group_timeslots:
            self.logger.info("No theory schedule data provided, skipping theory-lab conflict constraint.")
            return
            
        constraints_applied = 0
        
        # Get lab group info
        lab_groups = defaultdict(list)
        for instance_id in lab_assignments.keys():
            group_info = self.get_group_info_for_course_instance(instance_id)
            if group_info['department'] != 'Unknown':
                dept = group_info['department']
                semester = group_info['semester']
                group_index = group_info['group_index']
                
                group_key = f"{dept}_S{semester}_G{group_index}"
                lab_groups[group_key].append(instance_id)
                
        # Apply constraints
        for group_key, instance_ids in lab_groups.items():
            if group_key in self.theory_group_timeslots:
                occupied_theory_slots = self.theory_group_timeslots[group_key]
                
                for day_timeslot in occupied_theory_slots:
                    day, timeslot = day_timeslot.split('_', 1)
                    
                    # Map theory timeslot to conflicting lab session
                    conflicting_lab_session = self._map_theory_timeslot_to_lab_session(timeslot)
                    
                    if conflicting_lab_session:
                        day_idx = self.days.index(day)
                        session_idx = list(self.lab_sessions.keys()).index(conflicting_lab_session)
                        
                        # This lab group cannot be scheduled in this conflicting slot
                        for instance_id in instance_ids:
                            for room_id in self.lab_room_ids:
                                model.Add(lab_assignments[instance_id][day_idx][session_idx][room_id] == 0)
                                constraints_applied += 1
                                
                        self.logger.info(f"Group {group_key} is blocked from lab session {conflicting_lab_session} on {day} due to theory conflict.")

        self.logger.info(f"Applied {constraints_applied} theory-lab conflict constraints")

    def apply_semester_lab_slot_limit_constraint(self, model, lab_assignments):
        """CONSTRAINT: Limit the total number of lab slots used by any single semester/department to 18."""
        self.logger.info("Applying semester lab slot limit constraint (max 18 slots per sem/dept)...")
        
        # Group course instances by department and semester
        semester_courses = defaultdict(list)
        for instance_id in lab_assignments.keys():
            group_info = self.get_group_info_for_course_instance(instance_id)
            if group_info and group_info['department'] != 'Unknown':
                dept = group_info['department']
                semester = group_info['semester']
                semester_courses[(dept, semester)].append(instance_id)

        # Apply constraint for each semester/department
        for (dept, semester), instance_ids in semester_courses.items():
            # Exclude core lab instances from this constraint
            non_core_instance_ids = [
                inst_id for inst_id in instance_ids 
                if inst_id not in self.core_lab_instance_ids
            ]

            if not non_core_instance_ids:
                self.logger.info(f"  - Skipping 18-slot limit for {dept} S{semester}: all its labs are core labs and thus exempt.")
                continue

            # Create boolean variables for each time slot to check if it's used by this semester/dept's non-core labs
            slot_used_vars = {}
            for day_idx in range(self.num_days):
                for session_idx in range(len(self.lab_sessions)):
                    slot_used_vars[(day_idx, session_idx)] = model.NewBoolVar(
                        f'slot_used_{dept}_S{semester}_d{day_idx}_s{session_idx}'
                    )

            # Link these variables to the main assignment variables
            for day_idx in range(self.num_days):
                for session_idx in range(len(self.lab_sessions)):
                    # Slot is used if ANY non-core lab from this semester/dept is scheduled in it
                    
                    # Get all assignment variables for this slot for this semester/dept
                    slot_assignments = []
                    for instance_id in non_core_instance_ids:
                        slot_assignments.extend(
                            lab_assignments[instance_id][day_idx][session_idx].values()
                        )
                    
                    if slot_assignments:
                        # Reification: slot_used_vars[(day_idx, session_idx)] is true iff sum(slot_assignments) > 0
                        model.Add(sum(slot_assignments) >= 1).OnlyEnforceIf(slot_used_vars[(day_idx, session_idx)])
                        model.Add(sum(slot_assignments) == 0).OnlyEnforceIf(slot_used_vars[(day_idx, session_idx)].Not())

            # The sum of used slots for this semester/dept's non-core labs must be <= 18
            total_slots_used = sum(slot_used_vars.values())
            model.Add(total_slots_used <= 18)
            
            self.logger.info(f"  - Constraint for {dept} Semester {semester}: total used non-core lab slots <= 18")

    def apply_lab_efficiency_constraints(self, model, lab_assignments, lab_sessions):
        """Applies various constraints to improve the efficiency and quality of the lab schedule."""
        self.logger.info("Applying lab efficiency constraints for a higher quality schedule...")
        
        self._apply_room_utilization_maximization(model, lab_assignments, lab_sessions)
        self._apply_minimize_gaps_constraint(model, lab_assignments, lab_sessions)
        # self._apply_consecutive_session_preference(model, lab_assignments, lab_sessions) # Disabled for now
        self._apply_peak_time_balancing(model, lab_assignments, lab_sessions)
        self._apply_room_capacity_optimization(model, lab_assignments)
        self._apply_teacher_schedule_compactness(model, lab_assignments, lab_sessions)

    def _apply_room_utilization_maximization(self, model, lab_assignments, lab_sessions):
        """Helper to maximize room utilization."""
        pass  # Placeholder for now, can be implemented later
    
    def _apply_minimize_gaps_constraint(self, model, lab_assignments, lab_sessions):
        """Minimize gaps between sessions in the same room on the same day."""
        constraints_applied = 0
        
        # SOFT CONSTRAINT: Handle gap minimization in objective only
        # This avoids over-constraining the problem
        
        self.logger.info(f"Applied gap minimization: {constraints_applied} constraints (objective-based)") 
        return constraints_applied
    
    def _apply_consecutive_session_preference(self, model, lab_assignments, lab_sessions):
        """Prefer scheduling multiple sessions of the same course in consecutive slots."""
        constraints_applied = 0
        
        # SOFT CONSTRAINT: Handle in objective only to avoid over-constraining
        # We'll track this in the objective function instead
        
        self.logger.info(f"Applied consecutive session preference: {constraints_applied} constraints (objective-based)")
        return constraints_applied
    
    def _apply_peak_time_balancing(self, model, lab_assignments, lab_sessions):
        """Balance load across time slots to avoid overcrowding popular times."""
        constraints_applied = 0
        
        # RELAXED CONSTRAINT: Only limit extreme overcrowding, allow more flexibility
        for session_idx in range(len(lab_sessions)):
            session_assignments_across_days = []
            
            for day_idx in range(self.num_days):
                for course_instance_id in lab_assignments.keys():
                    for room_id in self.lab_room_ids:
                        session_assignments_across_days.append(
                            lab_assignments[course_instance_id][day_idx][session_idx][room_id]
                        )
            
            if session_assignments_across_days:
                # Much more relaxed constraint: allow up to 80% of labs per time slot
                max_sessions_per_slot = int(len(self.lab_room_ids) * 0.8)  # Use at most 80% of labs per time slot
                model.Add(sum(session_assignments_across_days) <= max_sessions_per_slot)
                constraints_applied += 1
        
        self.logger.info(f"Applied peak time balancing: {constraints_applied} constraints (relaxed)")
        return constraints_applied
    
    def _apply_room_capacity_optimization(self, model, lab_assignments):
        """Match room capacity more closely to course requirements."""
        constraints_applied = 0
        
        # SOFT CONSTRAINT: Handle room capacity matching in objective only
        # This avoids conflicts with the existing capacity constraints
        
        self.logger.info(f"Applied room capacity optimization: {constraints_applied} constraints (objective-based)")
        return constraints_applied
    
    def _apply_teacher_schedule_compactness(self, model, lab_assignments, lab_sessions):
        """Group teacher's sessions to minimize travel time and gaps in their schedule."""
        constraints_applied = 0
        
        # SOFT CONSTRAINT: Handle teacher compactness in objective only
        # This avoids complex constraint interactions that can cause infeasibility
        
        self.logger.info(f"Applied teacher schedule compactness: {constraints_applied} constraints (objective-based)")
        return constraints_applied
    
    def add_efficiency_objective(self, model, lab_assignments, lab_sessions):
        """Add an objective function to maximize scheduling efficiency."""
        self.logger.info("Adding efficiency objective function...")
        
        objective_terms = []
        
        # PRIORITY 1: Schedule all required lab sessions (HIGH WEIGHT)
        required_sessions = 0
        for teacher, courses in self.lab_requirements.items():
            for course in courses:
                # Fix the key name - using the correct key from lab_scheduler
                required_sessions += course.get('base_sessions', 0)
        
        self.logger.info(f"REQUIREMENT: Schedule {required_sessions} lab sessions across {len(self.lab_requirements)} teachers")
        
        # PRIORITY 2: Use parallelization bonuses to encourage same-group courses to run simultaneously
        if hasattr(self, 'group_parallelization_vars') and self.group_parallelization_vars:
            # These are already weighted in the apply_same_group_parallelization_preference method
            objective_terms.extend(self.group_parallelization_vars)
            self.logger.info(f"BONUS: Parallelization - {len(self.group_parallelization_vars)} bonus variables with graduated weights")
            self.logger.info("  • Strongly encourages same-group courses to run in parallel")
            self.logger.info("  • Higher bonuses for higher degrees of parallelization")
        
        # PRIORITY 3: Minimize "orphaned" sessions on days (encourage compact scheduling)
        orphaned_session_penalties = []
        self._add_orphaned_session_penalties(model, lab_assignments, lab_sessions, orphaned_session_penalties)
        
        # Add penalties with weight (negative in objective function)
        if orphaned_session_penalties:
            for penalty in orphaned_session_penalties:
                objective_terms.append(penalty * -5)  # Weight of -5 per orphaned session
            self.logger.info(f"PENALTY: Orphaned Sessions - {len(orphaned_session_penalties)} penalty variables")
        
        # PRIORITY 4: Balance room utilization
        room_utilization_vars = []
        self._add_room_utilization_balance(model, lab_assignments, room_utilization_vars)
        
        if room_utilization_vars:
            objective_terms.extend(room_utilization_vars)
            self.logger.info(f"BONUS: Room Utilization - {len(room_utilization_vars)} bonus variables")
        
        # PRIORITY 5: Teacher schedule compactness
        teacher_compactness_vars = []
        self._add_teacher_schedule_compactness(model, lab_assignments, teacher_compactness_vars)
        
        if teacher_compactness_vars:
            objective_terms.extend(teacher_compactness_vars)
            self.logger.info(f"BONUS: Teacher Compactness - {len(teacher_compactness_vars)} bonus variables")
        
        # PRIORITY 6: Capacity preferences (for 6 practical hour courses)
        if hasattr(self, 'capacity_preferences') and self.capacity_preferences:
            objective_terms.extend(self.capacity_preferences)
            self.logger.info(f"BONUS: Capacity Preferences - {len(self.capacity_preferences)} bonus variables for 6-hour courses preferring 70+ labs")
        
        # NEW PRIORITY: Penalize teacher exhaustion (3 consecutive labs)
        if hasattr(self, 'teacher_exhaustion_penalties') and self.teacher_exhaustion_penalties:
            for penalty_var in self.teacher_exhaustion_penalties:
                objective_terms.append(penalty_var * -100)  # Heavy penalty
            self.logger.info(
                f"PENALTY: Teacher Exhaustion - {len(self.teacher_exhaustion_penalties)} penalty variables with high weight")
        
        # Create the final objective function
        if objective_terms:
            model.Maximize(sum(objective_terms))
            self.logger.info(f"Efficiency objective created with {len(objective_terms)} terms")
            self.logger.info("📊 OBJECTIVE PRIORITIES:")
            self.logger.info("  1. Satisfy all required lab sessions (HARD CONSTRAINT)")
            self.logger.info("  2. GROUP PARALLELIZATION: Schedule same-group courses in parallel (STRONG PREFERENCE)")
            self.logger.info("     - Graduated weights from +8 to +20 based on parallelization level")
            self.logger.info("  3. Avoid orphaned sessions (-5 per orphaned session)")
            self.logger.info("  4. Balance room utilization (LOW WEIGHT)")
            self.logger.info("  5. Teacher schedule compactness (LOW WEIGHT)")
            self.logger.info("  6. CAPACITY PREFERENCE: 6-hour courses prefer 70+ labs (+10 bonus)")
        else:
            self.logger.warning("No objective terms were added - using solver defaults")
    
    def _add_orphaned_session_penalties(self, model, lab_assignments, lab_sessions, penalties):
        """Add penalties for orphaned lab sessions (used sessions with no adjacent sessions)."""
        # For each day, track which sessions are used and penalize orphaned ones
        for day_idx in range(self.num_days):
            day_usage = []
            
            # Create variables for each session: is it used or not?
            for session_idx in range(len(lab_sessions)):
                session_used = model.NewBoolVar(f'day{day_idx}_session{session_idx}_used')
                
                # Collect all assignments in this session
                session_assignments = []
                for course_instance_id in lab_assignments.keys():
                    for room_id in self.lab_room_ids:
                        session_assignments.append(lab_assignments[course_instance_id][day_idx][session_idx][room_id])
                    
                # Link session_used to assignments
                if session_assignments:
                    model.Add(session_used <= sum(session_assignments))
                    model.Add(sum(session_assignments) <= len(session_assignments) * session_used)
                else:
                    model.Add(session_used == 0)
                
                day_usage.append(session_used)
        
            # Create orphaned session penalties
            for session_idx in range(1, len(lab_sessions) - 1):
                # A session is orphaned if it's used but both adjacent sessions are not
                orphaned = model.NewBoolVar(f'day{day_idx}_session{session_idx}_orphaned')
                
                # orphaned = 1 iff session_used[session_idx] = 1 AND 
                #                session_used[session_idx-1] = 0 AND 
                #                session_used[session_idx+1] = 0
                
                # This requires 3 implications:
                # 1. If orphaned = 1 then session_used[session_idx] = 1
                model.Add(day_usage[session_idx] >= orphaned)
                
                # 2. If orphaned = 1 then session_used[session_idx-1] = 0
                model.Add(day_usage[session_idx-1] <= 1 - orphaned)
                
                # 3. If orphaned = 1 then session_used[session_idx+1] = 0
                model.Add(day_usage[session_idx+1] <= 1 - orphaned)
                        
                # 4. If all three conditions are true, then orphaned = 1
                # (session_used[i] = 1 AND session_used[i-1] = 0 AND session_used[i+1] = 0) -> orphaned = 1
                # Equivalent to: orphaned >= session_used[i] + (1-session_used[i-1]) + (1-session_used[i+1]) - 2
                model.Add(orphaned >= day_usage[session_idx] + (1 - day_usage[session_idx-1]) + 
                         (1 - day_usage[session_idx+1]) - 2)
                
                # Add penalty to the list
                penalties.append(orphaned)

    def _add_room_utilization_balance(self, model, lab_assignments, utilization_vars):
        """Add variables to encourage balanced room utilization."""
        for room_id in self.lab_room_ids:
            room_usage = []
                            
            for day_idx in range(self.num_days):
                for session_idx in range(len(self.lab_sessions)):
                    # Count assignments to this room
                    room_session_assignments = []
                    for course_instance_id in lab_assignments.keys():
                        room_session_assignments.append(lab_assignments[course_instance_id][day_idx][session_idx][room_id])
                    
                    # Create a variable for whether this room-session is used
                    room_session_used = model.NewBoolVar(f'room{room_id}_day{day_idx}_session{session_idx}_used')
                    
                    if room_session_assignments:
                        model.Add(room_session_used <= sum(room_session_assignments))
                        model.Add(sum(room_session_assignments) <= len(room_session_assignments) * room_session_used)
                    else:
                        model.Add(room_session_used == 0)
                    
                    room_usage.append(room_session_used)
            
            # Add this room's usage to the list of variables
            utilization_vars.append(sum(room_usage))

    def _add_teacher_schedule_compactness(self, model, lab_assignments, compactness_vars):
        """Add variables to encourage compact teacher schedules."""
        # Get unique teachers from lab_requirements
        unique_teachers = set()
        for teacher_id, courses in self.lab_requirements.items():
            unique_teachers.add(teacher_id)
            
        for teacher_id in unique_teachers:
            # For each day, compute consecutive sessions
            for day_idx in range(self.num_days):
                # Create a variable for each session: is this teacher teaching in this session?
                teacher_day_sessions = []
                
                for session_idx in range(len(self.lab_sessions)):
                    teacher_session = model.NewBoolVar(f'teacher{teacher_id}_day{day_idx}_session{session_idx}')
                    
                    # Collect all assignments for this teacher in this session
                    teacher_session_assignments = []
                        
                    # Get all course instances taught by this teacher
                    for course_instance_id in lab_assignments.keys():
                        # Check if this teacher teaches this course instance
                        teaches_course = False
                        for t_id, courses in self.lab_requirements.items():
                            if t_id == teacher_id:
                                for course in courses:
                                    if course['course_instance_id'] == course_instance_id:
                                        teaches_course = True
                                        break
                        
                        if teaches_course:
                            for room_id in self.lab_room_ids:
                                teacher_session_assignments.append(lab_assignments[course_instance_id][day_idx][session_idx][room_id])
                    
                    # Link teacher_session to assignments
                    if teacher_session_assignments:
                        model.Add(teacher_session <= sum(teacher_session_assignments))
                        model.Add(sum(teacher_session_assignments) <= len(teacher_session_assignments) * teacher_session)
                    else:
                        model.Add(teacher_session == 0)
                            
                    teacher_day_sessions.append(teacher_session)
        
                # Create bonuses for consecutive sessions
                for session_idx in range(len(self.lab_sessions) - 1):
                    consecutive_bonus = model.NewBoolVar(f'teacher{teacher_id}_day{day_idx}_consecutive_{session_idx}')
        
                    # Bonus if both this session and the next are used
                    model.Add(consecutive_bonus <= teacher_day_sessions[session_idx])
                    model.Add(consecutive_bonus <= teacher_day_sessions[session_idx + 1])
                    model.Add(consecutive_bonus >= teacher_day_sessions[session_idx] + teacher_day_sessions[session_idx + 1] - 1)
                    
                    # Add to compactness vars
                    compactness_vars.append(consecutive_bonus)
    
    def extract_lab_schedule(self, solver, lab_assignments, lab_sessions):
        """Extract the lab schedule from the solver solution with proper batching logic."""
        self.logger.info("Extracting lab schedule from solution...")
        
        lab_schedule = []
        
        for course_instance_id in lab_assignments.keys():
            teacher_id = self.course_to_teacher[course_instance_id]
            
            # Find the course details
            course_details = None
            for course in self.lab_requirements[teacher_id]:
                if course['course_instance_id'] == course_instance_id:
                    course_details = course
                    break
            
            if not course_details:
                continue
            
            for day_idx in range(self.num_days):
                for session_idx in range(len(lab_sessions)):
                    for room_id in self.lab_room_ids:
                        if solver.Value(lab_assignments[course_instance_id][day_idx][session_idx][room_id]) == 1:
                            # Get room details
                            room_row = self.lab_rooms[self.lab_rooms['id'] == room_id].iloc[0]
                            room_capacity = room_row['room_max_cap']
                            
                            # Get teacher details
                            teacher_row = self.courses_df[self.courses_df['teacher_id'] == teacher_id].iloc[0]
                            
                            # Rule 1: Simple batching rule - batch if using 35-capacity lab and have more students
                            student_count = course_details['students_per_instance']
                            
                            if student_count > room_capacity:
                                # Need batching: split students into batches that fit the lab capacity
                                batching_required = True
                                num_batches = (student_count + room_capacity - 1) // room_capacity
                                students_per_batch = (student_count + num_batches - 1) // num_batches
                            else:
                                # No batching needed: students fit in the lab
                                batching_required = False
                                num_batches = 1
                                students_per_batch = student_count
                            
                            session_name = lab_sessions[session_idx]
                            session_time_slots = self.lab_sessions[session_name]
                            
                            if batching_required and num_batches > 1:
                                # For batched courses, distribute sessions across batches
                                # Count total assignments for this course so far
                                existing_assignments = [item for item in lab_schedule 
                                                      if item['course_instance_id'] == course_instance_id]
                                
                                # Calculate how many sessions each batch should get
                                base_sessions = course_details['base_sessions']
                                
                                # Group existing assignments by batch
                                batch_session_counts = {}
                                for existing in existing_assignments:
                                    if existing.get('is_batched'):
                                        batch_num = existing.get('batch_info', '').replace('Batch ', '')
                                        if batch_num.isdigit():
                                            batch_session_counts[int(batch_num)] = batch_session_counts.get(int(batch_num), 0) + 1
                                
                                # Find which batch this assignment should go to
                                current_batch = 1
                                for batch_num in range(1, num_batches + 1):
                                    if batch_session_counts.get(batch_num, 0) < base_sessions:
                                        current_batch = batch_num
                                        break
                                
                                course_code_display = f"{course_details['course_code']} Batch {current_batch}"
                                batch_info = f"Batch {current_batch}"
                                
                                # Get group information for this course instance
                                group_info = self.get_group_info_for_course_instance(course_instance_id)
                                
                                # Add this session to the current batch
                                full_time_interval = f"{session_time_slots[0]} - {session_time_slots[1].split(' - ')[1]}"
                                lab_schedule.append({
                                    'day': self.days[day_idx],
                                    'session_name': session_name,
                                    'time_interval': full_time_interval,
                                    'course_instance_id': course_instance_id,
                                    'course_code': course_details['course_code'],
                                    'course_code_display': course_code_display,
                                    'practical_hours': int(course_details['practical_hours']),
                                    'teacher_id': teacher_id,
                                    'teacher_name': f"{teacher_row.get('first_name', '')} {teacher_row.get('last_name', '')}".strip(),
                                    'staff_code': teacher_row.get('staff_code', ''),
                                    'room_id': int(room_id),
                                    'room_number': room_row['room_number'],
                                    'block': room_row['block'],
                                    'capacity': int(room_capacity),
                                    'student_count': int(students_per_batch),
                                    'total_students': int(student_count),
                                    'is_batched': bool(True),
                                    'batch_info': batch_info,
                                    # Group information for Hall's theorem distribution
                                    'group_name': group_info['group_name'],
                                    'group_index': group_info['group_index'],
                                    'department': group_info['department'],
                                    'semester': group_info['semester']
                                })
                                
                                # Log assignment
                                self.logger.info(f"Lab assignment: Course {course_details['course_code']} Batch {current_batch} -> "
                                               f"{session_name} on {self.days[day_idx]} in "
                                               f"Lab {room_row['room_number']} ({students_per_batch} students)")
                            else:
                                # Single assignment, no batching (grouped as single entry)
                                course_code_display = course_details['course_code']
                                full_time_interval = f"{session_time_slots[0]} - {session_time_slots[1].split(' - ')[1]}"
                                
                                # Get group information for this course instance
                                group_info = self.get_group_info_for_course_instance(course_instance_id)
                                
                                lab_schedule.append({
                                    'day': self.days[day_idx],
                                    'session_name': session_name,
                                    'time_interval': full_time_interval,
                                    'course_instance_id': course_instance_id,
                                    'course_code': course_details['course_code'],
                                    'course_code_display': course_code_display,
                                    'practical_hours': int(course_details['practical_hours']),
                                    'teacher_id': teacher_id,
                                    'teacher_name': f"{teacher_row.get('first_name', '')} {teacher_row.get('last_name', '')}".strip(),
                                    'staff_code': teacher_row.get('staff_code', ''),
                                    'room_id': int(room_id),
                                    'room_number': room_row['room_number'],
                                    'block': room_row['block'],
                                    'capacity': int(room_capacity),
                                    'student_count': int(student_count),
                                    'total_students': int(student_count),
                                    'is_batched': bool(False),
                                    'batch_info': "",
                                    # Group information for Hall's theorem distribution
                                    'group_name': group_info['group_name'],
                                    'group_index': group_info['group_index'],
                                    'department': group_info['department'],
                                    'semester': group_info['semester']
                                })
                                
                                # Log assignment
                                self.logger.info(f"Lab assignment: Course {course_code_display} -> "
                                               f"{session_name} on {self.days[day_idx]} in "
                                               f"Lab {room_row['room_number']} (capacity: {room_capacity})")
        
        return lab_schedule
    
    def save_lab_schedule(self, lab_schedule):
        """Save the lab schedule to files."""
        self.logger.info("Saving lab schedule...")
        
        # Convert to DataFrame
        lab_df = pd.DataFrame(lab_schedule)
        
        # Save as CSV
        csv_path = os.path.join(self.output_dir, 'lab_schedule.csv')
        lab_df.to_csv(csv_path, index=False)
        self.logger.info(f"Lab schedule saved to {csv_path}")
        
        # Save as JSON
        json_path = os.path.join(self.output_dir, 'lab_schedule.json')
        with open(json_path, 'w') as f:
            json.dump(lab_schedule, f, indent=2)
        self.logger.info(f"Lab schedule saved to {json_path}")
        
        # Generate summary
        self.generate_summary(lab_schedule)
        
        # Generate efficiency analysis
        self.generate_efficiency_analysis(lab_schedule)
    
    def generate_summary(self, lab_schedule):
        """Generate a summary of the lab schedule."""
        summary_path = os.path.join(self.output_dir, 'lab_schedule_summary.txt')
        
        with open(summary_path, 'w') as f:
            f.write("Lab Schedule Summary\n")
            f.write("===================\n\n")
            
            # Total scheduled lab sessions
            f.write(f"Total scheduled lab sessions: {len(lab_schedule)}\n")
            
            # Sessions by day
            day_counts = {}
            for item in lab_schedule:
                day = item['day']
                day_counts[day] = day_counts.get(day, 0) + 1
            
            f.write("\nLab sessions by day:\n")
            for day in self.days:
                f.write(f"  {day.capitalize()}: {day_counts.get(day, 0)}\n")
            
            # Sessions by time slot
            session_counts = {}
            for item in lab_schedule:
                session = item['session_name']
                session_counts[session] = session_counts.get(session, 0) + 1
            
            f.write("\nLab sessions by time slot:\n")
            for session in self.lab_sessions.keys():
                time_range = f"{self.lab_sessions[session][0]} to {self.lab_sessions[session][1]}"
                f.write(f"  {session} ({time_range}): {session_counts.get(session, 0)}\n")
            
            # Teachers with lab assignments
            teacher_sessions = {}
            for item in lab_schedule:
                teacher = item['teacher_id']
                teacher_sessions[teacher] = teacher_sessions.get(teacher, 0) + 1
            
            f.write(f"\nTeachers with lab assignments: {len(teacher_sessions)}\n")
            
            # Courses with lab assignments
            course_assignments = {}
            for item in lab_schedule:
                course = item['course_code_display']
                course_assignments[course] = course_assignments.get(course, 0) + 1
            
            f.write(f"\nCourses with lab assignments:\n")
            for course, count in sorted(course_assignments.items()):
                f.write(f"  {course}: {count} sessions\n")
            
            # Rooms used
            room_usage = {}
            for item in lab_schedule:
                room = item['room_number']
                room_usage[room] = room_usage.get(room, 0) + 1
            
            f.write(f"\nLab rooms used: {len(room_usage)} out of {len(self.lab_rooms)}\n")
            
            # Room utilization
            f.write("\nRoom utilization:\n")
            for room, count in sorted(room_usage.items(), key=lambda x: x[1], reverse=True):
                f.write(f"  {room}: {count} sessions\n")
            
            # Batching information
            batched_courses = [item for item in lab_schedule if item.get('is_batched', False)]
            if batched_courses:
                f.write(f"\nBatched courses: {len(set(item['course_instance_id'] for item in batched_courses))}\n")
                batch_info = {}
                for item in batched_courses:
                    course_display = item['course_code_display']
                    batch_info[course_display] = batch_info.get(course_display, 0) + 1
                
                f.write("Batching details:\n")
                for course, count in sorted(batch_info.items()):
                    f.write(f"  {course}: {count} sessions\n")
            else:
                f.write(f"\nNo course batching required (all courses fit in assigned lab capacities)\n")
        
        self.logger.info(f"Summary saved to {summary_path}")
    
    def generate_efficiency_analysis(self, lab_schedule):
        """Generate detailed efficiency analysis of the lab schedule."""
        efficiency_path = os.path.join(self.output_dir, 'lab_efficiency_analysis.txt')
        
        # Calculate efficiency metrics
        efficiency_metrics = self._calculate_efficiency_metrics(lab_schedule)
        
        with open(efficiency_path, 'w') as f:
            f.write("Lab Schedule Efficiency Analysis\n")
            f.write("================================\n\n")
            
            # Room Utilization Analysis
            f.write("ROOM UTILIZATION ANALYSIS\n")
            f.write("-------------------------\n")
            f.write(f"Total lab rooms available: {len(self.lab_room_ids)}\n")
            f.write(f"Rooms actually used: {efficiency_metrics['rooms_used']}\n")
            f.write(f"Room utilization rate: {efficiency_metrics['room_utilization_rate']:.1f}%\n")
            f.write(f"Average sessions per used room: {efficiency_metrics['avg_sessions_per_room']:.1f}\n\n")
            
            # Time Slot Distribution
            f.write("TIME SLOT DISTRIBUTION\n")
            f.write("----------------------\n")
            for session, count in efficiency_metrics['session_distribution'].items():
                f.write(f"{session}: {count} sessions\n")
            f.write(f"Most popular time slot: {efficiency_metrics['peak_session']} ({efficiency_metrics['peak_count']} sessions)\n")
            f.write(f"Least used time slot: {efficiency_metrics['low_session']} ({efficiency_metrics['low_count']} sessions)\n")
            f.write(f"Load balance ratio: {efficiency_metrics['load_balance_ratio']:.2f}\n\n")
            
            # Gap Analysis
            f.write("GAP ANALYSIS\n")
            f.write("------------\n")
            f.write(f"Rooms with scheduling gaps: {efficiency_metrics['rooms_with_gaps']}\n")
            f.write(f"Total gap penalty score: {efficiency_metrics['gap_penalty_score']}\n")
            f.write(f"Gap efficiency: {efficiency_metrics['gap_efficiency']:.1f}%\n\n")
            
            # Teacher Schedule Compactness
            f.write("TEACHER SCHEDULE COMPACTNESS\n")
            f.write("----------------------------\n")
            f.write(f"Teachers with compact schedules: {efficiency_metrics['compact_teachers']}\n")
            f.write(f"Teachers with fragmented schedules: {efficiency_metrics['fragmented_teachers']}\n")
            f.write(f"Average teacher schedule compactness: {efficiency_metrics['avg_compactness']:.1f}%\n\n")
            
            # Course Grouping Efficiency
            f.write("COURSE GROUPING EFFICIENCY\n")
            f.write("--------------------------\n")
            f.write(f"Courses with consecutive sessions: {efficiency_metrics['consecutive_courses']}\n")
            f.write(f"Course grouping efficiency: {efficiency_metrics['course_grouping_efficiency']:.1f}%\n\n")
            
            # Overall Efficiency Score
            f.write("OVERALL EFFICIENCY SCORE\n")
            f.write("------------------------\n")
            f.write(f"Combined efficiency score: {efficiency_metrics['overall_efficiency']:.1f}/100\n")
            f.write(f"Efficiency grade: {efficiency_metrics['efficiency_grade']}\n\n")
            
            # Recommendations
            f.write("EFFICIENCY RECOMMENDATIONS\n")
            f.write("--------------------------\n")
            for recommendation in efficiency_metrics['recommendations']:
                f.write(f"• {recommendation}\n")
        
        self.logger.info(f"Efficiency analysis saved to {efficiency_path}")
        self.logger.info(f"Overall efficiency score: {efficiency_metrics['overall_efficiency']:.1f}/100 ({efficiency_metrics['efficiency_grade']})")
    
    def _calculate_efficiency_metrics(self, lab_schedule):
        """Calculate comprehensive efficiency metrics for the lab schedule."""
        metrics = {}
        
        if not lab_schedule:
            return {'overall_efficiency': 0, 'efficiency_grade': 'F', 'recommendations': ['No schedule data available']}
        
        # Room utilization metrics
        used_rooms = set(item['room_id'] for item in lab_schedule)
        metrics['rooms_used'] = len(used_rooms)
        metrics['room_utilization_rate'] = (len(used_rooms) / len(self.lab_room_ids)) * 100
        metrics['avg_sessions_per_room'] = len(lab_schedule) / len(used_rooms) if used_rooms else 0
        
        # Time slot distribution
        session_counts = {}
        for item in lab_schedule:
            session = item['session_name']
            session_counts[session] = session_counts.get(session, 0) + 1
        
        metrics['session_distribution'] = session_counts
        if session_counts:
            metrics['peak_session'] = max(session_counts, key=session_counts.get)
            metrics['peak_count'] = session_counts[metrics['peak_session']]
            metrics['low_session'] = min(session_counts, key=session_counts.get)
            metrics['low_count'] = session_counts[metrics['low_session']]
            metrics['load_balance_ratio'] = metrics['low_count'] / metrics['peak_count'] if metrics['peak_count'] > 0 else 0
        else:
            metrics.update({'peak_session': 'N/A', 'peak_count': 0, 'low_session': 'N/A', 'low_count': 0, 'load_balance_ratio': 0})
        
        # Gap analysis - calculate scheduling gaps in each room
        room_schedules = {}
        for item in lab_schedule:
            room_id = item['room_id']
            day = item['day']
            session = item['session_name']
            
            if room_id not in room_schedules:
                room_schedules[room_id] = {}
            if day not in room_schedules[room_id]:
                room_schedules[room_id][day] = []
            
            room_schedules[room_id][day].append(session)
        
        rooms_with_gaps = 0
        gap_penalty_score = 0
        
        for room_id, days in room_schedules.items():
            for day, sessions in days.items():
                if len(sessions) >= 3:
                    # Sort sessions by time order
                    session_order = ['L1', 'L2', 'L3', 'L4', 'L5', 'L6']
                    sorted_sessions = sorted(sessions, key=lambda x: session_order.index(x))
                    
                    # Check for gaps
                    session_indices = [session_order.index(s) for s in sorted_sessions]
                    for i in range(len(session_indices) - 2):
                        if session_indices[i+2] - session_indices[i] == 2 and session_indices[i+1] not in session_indices:
                            gap_penalty_score += 1
                            rooms_with_gaps += 1
                            break
        
        metrics['rooms_with_gaps'] = rooms_with_gaps
        metrics['gap_penalty_score'] = gap_penalty_score
        metrics['gap_efficiency'] = max(0, (1 - gap_penalty_score / len(used_rooms)) * 100) if used_rooms else 100
        
        # Teacher schedule compactness
        teacher_schedules = {}
        for item in lab_schedule:
            teacher_id = item['teacher_id']
            day = item['day']
            session = item['session_name']
            
            if teacher_id not in teacher_schedules:
                teacher_schedules[teacher_id] = {}
            if day not in teacher_schedules[teacher_id]:
                teacher_schedules[teacher_id][day] = []
            
            teacher_schedules[teacher_id][day].append(session)
        
        compact_teachers = 0
        fragmented_teachers = 0
        compactness_scores = []
        
        for teacher_id, days in teacher_schedules.items():
            teacher_compactness = 0
            teacher_days = 0
            
            for day, sessions in days.items():
                if len(sessions) > 1:
                    teacher_days += 1
                    session_order = ['L1', 'L2', 'L3', 'L4', 'L5', 'L6']
                    session_indices = sorted([session_order.index(s) for s in sessions])
                    
                    # Calculate compactness as ratio of actual span to minimum possible span
                    actual_span = session_indices[-1] - session_indices[0] + 1
                    minimum_span = len(session_indices)
                    day_compactness = minimum_span / actual_span if actual_span > 0 else 1
                    teacher_compactness += day_compactness
            
            if teacher_days > 0:
                avg_teacher_compactness = teacher_compactness / teacher_days
                compactness_scores.append(avg_teacher_compactness)
                
                if avg_teacher_compactness >= 0.8:
                    compact_teachers += 1
                else:
                    fragmented_teachers += 1
        
        metrics['compact_teachers'] = compact_teachers
        metrics['fragmented_teachers'] = fragmented_teachers
        metrics['avg_compactness'] = (sum(compactness_scores) / len(compactness_scores) * 100) if compactness_scores else 100
        
        # Course grouping efficiency
        course_sessions = {}
        for item in lab_schedule:
            course = item['course_code']
            day = item['day']
            session = item['session_name']
            
            if course not in course_sessions:
                course_sessions[course] = {}
            if day not in course_sessions[course]:
                course_sessions[course][day] = []
            
            course_sessions[course][day].append(session)
        
        consecutive_courses = 0
        total_course_instances = len(course_sessions)
        
        for course, days in course_sessions.items():
            for day, sessions in days.items():
                if len(sessions) > 1:
                    session_order = ['L1', 'L2', 'L3', 'L4', 'L5', 'L6']
                    session_indices = sorted([session_order.index(s) for s in sessions])
                    
                    # Check if sessions are consecutive
                    is_consecutive = all(session_indices[i+1] - session_indices[i] == 1 for i in range(len(session_indices)-1))
                    if is_consecutive:
                        consecutive_courses += 1
                        break
        
        metrics['consecutive_courses'] = consecutive_courses
        metrics['course_grouping_efficiency'] = (consecutive_courses / total_course_instances * 100) if total_course_instances > 0 else 100
        
        # Calculate overall efficiency score
        efficiency_components = [
            ('room_utilization_rate', 0.2),
            ('load_balance_ratio', 0.15),
            ('gap_efficiency', 0.25),
            ('avg_compactness', 0.2),
            ('course_grouping_efficiency', 0.2)
        ]
        
        total_score = 0
        for component, weight in efficiency_components:
            if component == 'load_balance_ratio':
                # Convert ratio to percentage
                score = min(metrics[component] * 100, 100)
            else:
                score = metrics[component]
            total_score += score * weight
        
        metrics['overall_efficiency'] = total_score
        
        # Assign efficiency grade
        if total_score >= 90:
            metrics['efficiency_grade'] = 'A+'
        elif total_score >= 85:
            metrics['efficiency_grade'] = 'A'
        elif total_score >= 80:
            metrics['efficiency_grade'] = 'B+'
        elif total_score >= 75:
            metrics['efficiency_grade'] = 'B'
        elif total_score >= 70:
            metrics['efficiency_grade'] = 'C+'
        elif total_score >= 65:
            metrics['efficiency_grade'] = 'C'
        elif total_score >= 60:
            metrics['efficiency_grade'] = 'D'
        else:
            metrics['efficiency_grade'] = 'F'
        
        # Generate recommendations
        recommendations = []
        if metrics['room_utilization_rate'] < 60:
            recommendations.append("Consider consolidating sessions to use fewer rooms more intensively")
        if metrics['gap_efficiency'] < 80:
            recommendations.append("Minimize scheduling gaps by grouping sessions consecutively")
        if metrics['avg_compactness'] < 75:
            recommendations.append("Improve teacher schedule compactness to reduce travel time")
        if metrics['course_grouping_efficiency'] < 70:
            recommendations.append("Group related course sessions together for better learning continuity")
        if metrics['load_balance_ratio'] < 0.5:
            recommendations.append("Better distribute sessions across time slots to avoid peak congestion")
        
        if not recommendations:
            recommendations.append("Schedule efficiency is excellent! No major improvements needed.")
        
        metrics['recommendations'] = recommendations
        
        return metrics

    def analyze_student_choice_feasibility(self, groups, dept, semester, target_students=420):
        """Analyze if target number of students can select all required courses for their semester."""
        self.logger.info(f"\n" + "="*80)
        self.logger.info(f"STUDENT CHOICE FEASIBILITY ANALYSIS for {dept} Semester {semester}")
        self.logger.info(f"Target Students: {target_students}")
        self.logger.info(f"="*80)
        
        if not groups:
            self.logger.error("No groups available for analysis")
            return False
        
        # Extract all courses and their group distribution
        all_courses = set()
        course_group_mapping = {}  # course -> list of group indices where it appears
        
        for group_idx, group in enumerate(groups):
            if not group:
                continue
                
            group_courses = set(instance['course_code'] for instance in group)
            all_courses.update(group_courses)
            
            for course_code in group_courses:
                if course_code not in course_group_mapping:
                    course_group_mapping[course_code] = []
                course_group_mapping[course_code].append(group_idx)
        
        total_courses = len(all_courses)
        total_groups = len([g for g in groups if g])
        
        self.logger.info(f"📊 DISTRIBUTION OVERVIEW:")
        self.logger.info(f"   Total Courses: {total_courses}")
        self.logger.info(f"   Total Groups: {total_groups}")
        self.logger.info(f"   Target Students: {target_students}")
        
        # Show course distribution across groups
        self.logger.info(f"\n📋 COURSE-GROUP DISTRIBUTION:")
        for course_code in sorted(all_courses):
            group_indices = course_group_mapping[course_code]
            group_names = [f"G{i+1}" for i in group_indices]
            self.logger.info(f"   {course_code}: {', '.join(group_names)} ({len(group_indices)} groups)")
        
        # CRITICAL ANALYSIS: Can students select all courses?
        # For this, we need to check if there's a perfect matching from courses to groups
        
        # Build bipartite graph: courses -> available groups
        from itertools import combinations
        
        # Check Hall's Marriage Theorem for perfect matching
        self.logger.info(f"\n🔍 HALL'S MARRIAGE THEOREM ANALYSIS:")
        
        # For every subset of courses, check if they have enough group choices
        hall_violations = []
        
        for r in range(1, min(total_courses + 1, 6)):  # Check subsets up to size 5
            for course_subset in combinations(all_courses, r):
                # Find all groups that serve at least one course in this subset
                available_groups = set()
                for course in course_subset:
                    available_groups.update(course_group_mapping.get(course, []))
                
                # Hall's condition: |available_groups| >= |course_subset|
                if len(available_groups) < len(course_subset):
                    hall_violations.append({
                        'courses': list(course_subset),
                        'required_groups': len(course_subset),
                        'available_groups': len(available_groups),
                        'deficit': len(course_subset) - len(available_groups)
                    })
        
        if hall_violations:
            self.logger.error(f"❌ HALL'S THEOREM VIOLATED: {len(hall_violations)} violations")
            self.logger.error(f"   Students CANNOT select all {total_courses} courses!")
            
            for violation in hall_violations[:3]:  # Show first 3 violations
                courses_str = ', '.join(violation['courses'])
                self.logger.error(f"   Subset [{courses_str}]: needs {violation['required_groups']} groups, only {violation['available_groups']} available")
            
            return False
        else:
            self.logger.info(f"V HALL'S THEOREM SATISFIED")
            self.logger.info(f"   Perfect matching EXISTS - students CAN select all {total_courses} courses!")
        
        # Find and display valid course-group assignments
        self.logger.info(f"\n🎯 VALID COURSE-GROUP ASSIGNMENTS:")
        
        # Try to find a valid assignment using greedy approach
        valid_assignment = self._find_perfect_matching(course_group_mapping, total_groups)
        
        if valid_assignment:
            self.logger.info(f"   Example valid assignment for students:")
            for course, group_idx in valid_assignment.items():
                self.logger.info(f"     {course} → Group {group_idx + 1}")
            
            # Calculate student capacity for this assignment
            self.logger.info(f"\n👥 STUDENT CAPACITY ANALYSIS:")
            
            # Each course appears in 2 groups, so students have some flexibility
            choice_combinations = 1
            for course in all_courses:
                available_groups = len(course_group_mapping[course])
                choice_combinations *= available_groups
                self.logger.info(f"     {course}: {available_groups} group choices")
            
            self.logger.info(f"   Total choice combinations: {choice_combinations}")
            
            # Estimate capacity based on dynamic student calculation
            max_instances_per_course = 0
            for group in groups:
                if group:
                    course_counts = {}
                    for instance in group:
                        course_code = instance['course_code']
                        course_counts[course_code] = course_counts.get(course_code, 0) + 1
                    if course_counts:
                        max_instances_per_course = max(max_instances_per_course, max(course_counts.values()))
            
            dynamic_capacity = max_instances_per_course * 70
            
            self.logger.info(f"   Estimated capacity per choice combination: {dynamic_capacity} students")
            self.logger.info(f"   Total theoretical capacity: {choice_combinations * dynamic_capacity} students")
            
            # CRITICAL ANALYSIS: Will the 420th student still have choices after random selections?
            self.logger.info(f"\n🎲 RANDOM SELECTION ROBUSTNESS ANALYSIS:")
            self.logger.info(f"   Analyzing worst-case: Will student #{target_students} have choices after {target_students-1} random selections?")
            
            # Calculate capacity per course-group combination
            course_group_capacities = {}
            for course in all_courses:
                for group_idx in course_group_mapping[course]:
                    # Count instances of this course in this group
                    course_instances_in_group = len([
                        inst for inst in groups[group_idx] 
                        if inst['course_code'] == course
                    ])
                    capacity = course_instances_in_group * 70  # Each instance can handle 70 students
                    course_group_capacities[(course, group_idx)] = capacity
                    
                    self.logger.info(f"     {course} in Group {group_idx + 1}: {capacity} students ({course_instances_in_group} instances)")
            
            # Calculate minimum guaranteed capacity using bottleneck analysis
            min_capacity_per_course = {}
            for course in all_courses:
                available_groups = course_group_mapping[course]
                capacities = [course_group_capacities[(course, g)] for g in available_groups]
                min_capacity_per_course[course] = min(capacities)
                total_capacity_for_course = sum(capacities)
                
                self.logger.info(f"     {course}: Min capacity = {min_capacity_per_course[course]}, Total capacity = {total_capacity_for_course}")
            
            # Bottleneck analysis: Find the most constrained course
            bottleneck_course = min(all_courses, key=lambda c: min_capacity_per_course[c])
            bottleneck_capacity = min_capacity_per_course[bottleneck_course]
            
            self.logger.info(f"\n🚨 BOTTLENECK ANALYSIS:")
            self.logger.info(f"   Most constrained course: {bottleneck_course}")
            self.logger.info(f"   Minimum capacity for {bottleneck_course}: {bottleneck_capacity} students")
            
            # Worst-case scenario: Can the last student still get all courses?
            # This happens when the bottleneck course-group combinations are nearly full
            
            # Calculate probability that last student has choices
            worst_case_analysis = self._analyze_last_student_probability(
                course_group_mapping, course_group_capacities, target_students
            )
            
            if worst_case_analysis['guaranteed_success']:
                self.logger.info(f"V LAST STUDENT GUARANTEED SUCCESS!")
                self.logger.info(f"   Even after {target_students-1} random selections, student #{target_students} will have valid choices")
                self.logger.info(f"   Reason: {worst_case_analysis['reason']}")
                final_result = True
            elif worst_case_analysis['high_probability']:
                self.logger.info(f"V LAST STUDENT HIGH SUCCESS PROBABILITY!")
                self.logger.info(f"   Student #{target_students} has {worst_case_analysis['success_probability']:.1f}% chance of valid choices")
                self.logger.info(f"   Reason: {worst_case_analysis['reason']}")
                final_result = True
            else:
                self.logger.warning(f"W LAST STUDENT MAY FACE DIFFICULTIES!")
                self.logger.warning(f"   Student #{target_students} has only {worst_case_analysis['success_probability']:.1f}% chance of valid choices")
                self.logger.warning(f"   Reason: {worst_case_analysis['reason']}")
                final_result = False
            
            return final_result
        else:
            self.logger.error(f"X NO VALID ASSIGNMENT FOUND")
            self.logger.error(f"   Students CANNOT select all {total_courses} courses!")
            return False
    
    def _find_perfect_matching(self, course_group_mapping, total_groups):
        """Find a perfect matching from courses to groups using greedy algorithm."""
        assignment = {}
        used_groups = set()
        
        # Sort courses by number of available groups (ascending) - handle constrained courses first
        sorted_courses = sorted(course_group_mapping.keys(), key=lambda c: len(course_group_mapping[c]))
        
        for course in sorted_courses:
            available_groups = course_group_mapping[course]
            
            # Find an unused group for this course
            assigned = False
            for group_idx in available_groups:
                if group_idx not in used_groups:
                    assignment[course] = group_idx
                    used_groups.add(group_idx)
                    assigned = True
                    break
            
            if not assigned:
                # Backtrack or return None if no assignment possible
                return None
        
        return assignment 

    def apply_core_lab_mapping_constraint(self, model, lab_assignments):
        """Applies constraint that courses in core_mapping must be assigned to their specified lab(s)."""
        if not self.course_to_room_mapping:
            self.logger.info("No core lab mapping found, skipping this constraint.")
            return

        self.logger.info("Applying core lab mapping constraint...")
        constraints_applied = 0
        
        for teacher_id, courses in self.lab_requirements.items():
            for course in courses:
                course_code = course['course_code']
                course_instance_id = course['course_instance_id']
                
                # Get course name from the original courses data
                course_row = self.courses_df[self.courses_df['id'] == int(course_instance_id)]
                if course_row.empty:
                    self.logger.warning(f"Course instance {course_instance_id} not found in courses data")
                    continue
                    
                course_name = course_row.iloc[0]['course_name']
                
                if (course_code, course_name) in self.course_to_room_mapping:
                    required_room_ids = self.course_to_room_mapping[(course_code, course_name)]
                    
                    # Ensure all required rooms are valid lab rooms
                    valid_required_rooms = [room_id for room_id in required_room_ids if room_id in self.lab_room_ids]
                    
                    if not valid_required_rooms:
                        self.logger.warning(f"No valid lab rooms found for course {course_code}. Skipping constraint for this course.")
                        continue
                        
                    # This course must be assigned ONLY to one of its specified rooms
                    # Constrain it to NOT use any other rooms
                    forbidden_rooms = set(self.lab_room_ids) - set(valid_required_rooms)
                    
                    for day_idx in range(self.num_days):
                        for session_idx in range(len(self.lab_sessions)):
                            for room_id in forbidden_rooms:
                                # This lab session cannot be assigned to forbidden rooms
                                if course_instance_id in lab_assignments:
                                    model.Add(lab_assignments[course_instance_id][day_idx][session_idx][room_id] == 0)
                                    constraints_applied += 1
                    
                    self.logger.info(f"Constraining course '{course_code}' - '{course_name}' to {len(valid_required_rooms)} specific room(s): {valid_required_rooms}")
                else:
                    # This course is NOT in the core mapping.
                    # Constrain it to rooms of type 'Laboratory'.
                    self.logger.info(f"Course '{course_code}' not in core mapping. Constraining to 'Laboratory' type rooms.")
                    non_laboratory_rooms = set(self.lab_room_ids) - set(self.laboratory_room_ids)
                    for day_idx in range(self.num_days):
                        for session_idx in range(len(self.lab_sessions)):
                            for room_id in non_laboratory_rooms:
                                if course_instance_id in lab_assignments:
                                    model.Add(lab_assignments[course_instance_id][day_idx][session_idx][room_id] == 0)
                                    constraints_applied += 1

        self.logger.info(f"Applied {constraints_applied} core lab mapping constraints.")

    def generate_course_group_distribution_heatmap(self):
        """Generate heatmap visualization of course-to-group distribution before applying constraints."""
        self.logger.info("🎨 Generating course-to-group distribution heatmap...")
        
        try:
            # Create output directory for visualizations
            viz_output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
                                         'output', 
                                         f'lab_grouping_viz_{datetime.now().strftime("%Y%m%d_%H%M%S")}')
            os.makedirs(viz_output_dir, exist_ok=True)
            
            # Process each department-semester combination
            total_dept_sem = len(self.course_groups)
            processed_count = 0
            
            self.logger.info(f"📊 Processing {total_dept_sem} department-semester combinations for heatmaps...")
            
            for (dept, semester), groups in self.course_groups.items():
                processed_count += 1
                
                if not groups:
                    self.logger.warning(f"⚠️ Skipping {dept} S{semester} - no groups")
                    continue
                    
                self.logger.info(f"🎨 Creating heatmap {processed_count}/{total_dept_sem}: {dept} Semester {semester}...")
                
                try:
                    # Collect course-group data
                    course_group_matrix = {}
                    all_courses = set()
                    group_names = []
                    
                    for group_idx, group in enumerate(groups):
                        if not group:
                            continue
                            
                        group_name = f"G{group_idx + 1}"
                        group_names.append(group_name)
                        
                        # Count teacher assignments per course per group
                        course_teacher_counts = {}
                        for instance in group:
                            course_code = instance['course_code']
                            teacher_id = instance['teacher_id']
                            all_courses.add(course_code)
                            
                            if course_code not in course_teacher_counts:
                                course_teacher_counts[course_code] = set()
                            course_teacher_counts[course_code].add(teacher_id)
                        
                        # Store teacher assignment counts
                        for course_code, teachers in course_teacher_counts.items():
                            if course_code not in course_group_matrix:
                                course_group_matrix[course_code] = {}
                            course_group_matrix[course_code][group_name] = len(teachers)
                    
                    if not all_courses or not group_names:
                        self.logger.warning(f"No data to visualize for {dept} Semester {semester}")
                        continue
                    
                    # Create matrix for heatmap
                    courses_list = sorted(list(all_courses))
                    matrix_data = []
                    
                    for course in courses_list:
                        row = []
                        for group_name in group_names:
                            count = course_group_matrix.get(course, {}).get(group_name, 0)
                            row.append(count)
                        matrix_data.append(row)
                    
                    # Create the heatmap
                    plt.figure(figsize=(max(8, len(group_names) * 1.2), max(6, len(courses_list) * 0.4)))
                    
                    # Convert to numpy array for better handling
                    matrix_array = np.array(matrix_data)
                    
                    # Create heatmap with custom colormap
                    ax = sns.heatmap(matrix_array, 
                                   xticklabels=group_names,
                                   yticklabels=courses_list,
                                   annot=True, 
                                   fmt='d',
                                   cmap='YlOrRd',
                                   cbar_kws={'label': 'Number of Teacher Assignments'},
                                   linewidths=0.5)
                    
                    # Customize the plot
                    plt.title(f'Course-Group Distribution Heatmap\n{dept} - Semester {semester}\n(Number shows teacher assignments per course per group)', 
                             fontsize=14, fontweight='bold', pad=20)
                    plt.xlabel('Groups', fontsize=12, fontweight='bold')
                    plt.ylabel('Courses', fontsize=12, fontweight='bold')
                    
                    # Rotate labels for better readability
                    plt.xticks(rotation=0, ha='center')
                    plt.yticks(rotation=0)
                    
                    # Add grid for better readability
                    ax.set_facecolor('white')
                    
                    # Add summary statistics as text
                    total_assignments = np.sum(matrix_array)
                    max_assignments = np.max(matrix_array) if matrix_array.size > 0 else 0
                    
                    # Calculate course distribution stats
                    courses_with_choice = sum(1 for course in courses_list 
                                            if sum(course_group_matrix.get(course, {}).values()) > 1)
                    choice_percentage = (courses_with_choice / len(courses_list) * 100) if courses_list else 0
                    
                    stats_text = f'Stats: {len(courses_list)} courses, {len(group_names)} groups\n'
                    stats_text += f'Total assignments: {total_assignments}, Max per cell: {max_assignments}\n'
                    stats_text += f'Courses with multiple groups: {courses_with_choice} ({choice_percentage:.1f}%)'
                    
                    plt.figtext(0.02, 0.02, stats_text, fontsize=9, 
                               bbox=dict(boxstyle="round,pad=0.3", facecolor="lightgray", alpha=0.8))
                    
                    plt.tight_layout()
                    
                    # Save the heatmap - handle special characters in filename
                    safe_dept_name = dept.replace(" ", "_").replace("&", "and").replace("(", "").replace(")", "")
                    filename = f'course_group_heatmap_{safe_dept_name}_S{semester}.png'
                    filepath = os.path.join(viz_output_dir, filename)
                    plt.savefig(filepath, dpi=300, bbox_inches='tight')
                    plt.close()
                    
                    self.logger.info(f"✅ Heatmap saved: {filepath}")
                    
                    # Also create a detailed text summary
                    summary_filename = f'course_group_summary_{safe_dept_name}_S{semester}.txt'
                    summary_filepath = os.path.join(viz_output_dir, summary_filename)
                    
                    with open(summary_filepath, 'w', encoding='utf-8') as f:
                        f.write(f"Course-Group Distribution Summary\n")
                        f.write(f"Department: {dept}\n")
                        f.write(f"Semester: {semester}\n")
                        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                        f.write(f"="*60 + "\n\n")
                        
                        f.write(f"OVERVIEW:\n")
                        f.write(f"- Total Courses: {len(courses_list)}\n")
                        f.write(f"- Total Groups: {len(group_names)}\n")
                        f.write(f"- Total Teacher Assignments: {total_assignments}\n")
                        f.write(f"- Courses with Multiple Group Options: {courses_with_choice} ({choice_percentage:.1f}%)\n\n")
                        
                        f.write(f"COURSE DISTRIBUTION:\n")
                        for course in courses_list:
                            course_data = course_group_matrix.get(course, {})
                            groups_with_course = [g for g, count in course_data.items() if count > 0]
                            total_teachers = sum(course_data.values())
                            f.write(f"- {course}: {len(groups_with_course)} groups, {total_teachers} teacher assignments\n")
                            for group_name in groups_with_course:
                                f.write(f"  └─ {group_name}: {course_data[group_name]} teachers\n")
                        
                        f.write(f"\nGROUP COMPOSITION:\n")
                        for group_idx, group in enumerate(groups):
                            if not group:
                                continue
                            group_name = f"G{group_idx + 1}"
                            courses_in_group = set(inst['course_code'] for inst in group)
                            teachers_in_group = set(inst['teacher_id'] for inst in group)
                            f.write(f"- {group_name}: {len(courses_in_group)} courses, {len(teachers_in_group)} teachers\n")
                            for course in sorted(courses_in_group):
                                course_teachers = set(inst['teacher_id'] for inst in group if inst['course_code'] == course)
                                f.write(f"  └─ {course}: {len(course_teachers)} teachers\n")
                    
                    self.logger.info(f"✅ Summary saved: {summary_filepath}")
                    
                except Exception as dept_error:
                    self.logger.error(f"❌ Error processing {dept} S{semester}: {str(dept_error)}")
                    import traceback
                    self.logger.error(f"Traceback: {traceback.format_exc()}")
                    # Continue with next department instead of stopping
                    continue

                    # Create a combined overview heatmap if multiple department-semesters exist
            if len(self.course_groups) > 1:
                self._create_combined_overview_heatmap(viz_output_dir)
            
            self.logger.info(f"🎨 All course-group distribution visualizations saved to: {viz_output_dir}")
            
        except Exception as e:
            self.logger.error(f"❌ Error generating course-group heatmap: {str(e)}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")

    def _create_combined_overview_heatmap(self, viz_output_dir):
        """Create a combined overview heatmap showing all department-semester combinations."""
        self.logger.info("Creating combined overview heatmap...")
        
        try:
            # Collect data from all department-semester combinations
            all_data = []
            dept_sem_labels = []
            
            for (dept, semester), groups in self.course_groups.items():
                if not groups:
                    continue
                    
                dept_sem_key = f"{dept} S{semester}"
                dept_sem_labels.append(dept_sem_key)
                
                # Count courses and groups
                all_courses = set()
                total_assignments = 0
                
                for group in groups:
                    if group:
                        group_courses = set(inst['course_code'] for inst in group)
                        all_courses.update(group_courses)
                        total_assignments += len(group)
                
                courses_with_choice = 0
                course_group_counts = {}
                
                # Count how many groups each course appears in
                for course in all_courses:
                    groups_with_course = 0
                    for group in groups:
                        if group and any(inst['course_code'] == course for inst in group):
                            groups_with_course += 1
                    course_group_counts[course] = groups_with_course
                    if groups_with_course > 1:
                        courses_with_choice += 1
                
                choice_percentage = (courses_with_choice / len(all_courses) * 100) if all_courses else 0
                
                all_data.append({
                    'dept_sem': dept_sem_key,
                    'total_courses': len(all_courses),
                    'total_groups': len([g for g in groups if g]),
                    'total_assignments': total_assignments,
                    'courses_with_choice': courses_with_choice,
                    'choice_percentage': choice_percentage,
                    'avg_groups_per_course': sum(course_group_counts.values()) / len(all_courses) if all_courses else 0
                })
            
            if not all_data:
                return
            
            # Create overview visualization
            fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(16, 12))
            fig.suptitle('Lab Scheduler: Course-Group Distribution Overview\n(Before Constraint Application)', 
                        fontsize=16, fontweight='bold')
            
            # Chart 1: Courses and Groups per Department-Semester
            dept_sems = [d['dept_sem'] for d in all_data]
            courses_counts = [d['total_courses'] for d in all_data]
            groups_counts = [d['total_groups'] for d in all_data]
            
            x = np.arange(len(dept_sems))
            width = 0.35
            
            ax1.bar(x - width/2, courses_counts, width, label='Courses', color='skyblue', alpha=0.8)
            ax1.bar(x + width/2, groups_counts, width, label='Groups', color='lightcoral', alpha=0.8)
            ax1.set_xlabel('Department-Semester')
            ax1.set_ylabel('Count')
            ax1.set_title('Courses vs Groups Distribution')
            ax1.set_xticks(x)
            ax1.set_xticklabels(dept_sems, rotation=45, ha='right')
            ax1.legend()
            ax1.grid(True, alpha=0.3)
            
            # Chart 2: Student Choice Percentage
            choice_percentages = [d['choice_percentage'] for d in all_data]
            bars = ax2.bar(dept_sems, choice_percentages, color='lightgreen', alpha=0.8)
            ax2.set_xlabel('Department-Semester')
            ax2.set_ylabel('Percentage (%)')
            ax2.set_title('Student Choice Availability\n(% of courses with multiple group options)')
            ax2.set_xticklabels(dept_sems, rotation=45, ha='right')
            ax2.grid(True, alpha=0.3)
            
            # Add percentage labels on bars
            for bar, pct in zip(bars, choice_percentages):
                height = bar.get_height()
                ax2.text(bar.get_x() + bar.get_width()/2., height + 1,
                        f'{pct:.1f}%', ha='center', va='bottom', fontweight='bold')
            
            # Chart 3: Total Assignments
            assignments = [d['total_assignments'] for d in all_data]
            ax3.bar(dept_sems, assignments, color='gold', alpha=0.8)
            ax3.set_xlabel('Department-Semester')
            ax3.set_ylabel('Total Assignments')
            ax3.set_title('Total Teacher-Course Assignments')
            ax3.set_xticklabels(dept_sems, rotation=45, ha='right')
            ax3.grid(True, alpha=0.3)
            
            # Chart 4: Average Groups per Course
            avg_groups = [d['avg_groups_per_course'] for d in all_data]
            ax4.bar(dept_sems, avg_groups, color='mediumpurple', alpha=0.8)
            ax4.set_xlabel('Department-Semester')
            ax4.set_ylabel('Average Groups per Course')
            ax4.set_title('Course Distribution Efficiency')
            ax4.set_xticklabels(dept_sems, rotation=45, ha='right')
            ax4.grid(True, alpha=0.3)
            ax4.axhline(y=2.0, color='red', linestyle='--', alpha=0.7, label='Max Limit (2)')
            ax4.legend()
            
            plt.tight_layout()
            
            # Save combined overview
            overview_filepath = os.path.join(viz_output_dir, 'combined_overview_heatmap.png')
            plt.savefig(overview_filepath, dpi=300, bbox_inches='tight')
            plt.close()
            
            self.logger.info(f"✅ Combined overview saved: {overview_filepath}")
            
        except Exception as e:
            self.logger.error(f"❌ Error creating combined overview: {str(e)}")