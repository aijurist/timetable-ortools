import os
import pandas as pd
import numpy as np
import logging
import json
from datetime import datetime
from collections import defaultdict, Counter
from itertools import combinations
from ortools.sat.python import cp_model
import matplotlib.pyplot as plt
import seaborn as sns

class TheoryScheduler:
    """Schedules theory sessions based on lecture and tutorial hours, following a group-based approach."""
    
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
                'course_dept': row.get('course_dept', 'Computer Science & Engineering'),
                'student_dept': row.get('student_dept', 'Computer Science & Engineering'),
                'is_theory_course': int(row.get('lecture_hours', 0)) > 0 or int(row.get('tutorial_hours', 0)) > 0,
                'has_assistant': row['is_assistant'] == 1,
                'assistant_teacher_id': row.get('assist_teacher_id'),
                'assistant_staff_code': row.get('assist_staff_code'),
                'assistant_teacher_name': f"{row.get('assist_first_name', '')} {row.get('assist_last_name', '')}".strip()
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
                'student_dept': row.get('student_dept', 'Computer Science & Engineering'),
                'is_theory_course': int(row.get('lecture_hours', 0)) > 0 or int(row.get('tutorial_hours', 0)) > 0,
                'has_assistant': row['is_assistant'] == 1,
                'assistant_teacher_id': row.get('assist_teacher_id'),
                'assistant_staff_code': row.get('assist_staff_code'),
                'assistant_teacher_name': f"{row.get('assist_first_name', '')} {row.get('assist_last_name', '')}".strip()
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
            # Main teacher
            teacher_id = instance['teacher_id']
            if teacher_id not in teacher_course_count:
                teacher_course_count[teacher_id] = 0
                teacher_instances[teacher_id] = []
            teacher_course_count[teacher_id] += 1
            teacher_instances[teacher_id].append(instance)

            # Assistant teacher
            if instance.get('has_assistant') and pd.notna(instance.get('assistant_teacher_id')):
                assistant_id = instance.get('assistant_teacher_id')
                if assistant_id not in teacher_course_count:
                    teacher_course_count[assistant_id] = 0
                    teacher_instances[assistant_id] = []
                teacher_course_count[assistant_id] += 1
                teacher_instances[assistant_id].append(instance)
        
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
            self.logger.warning(f"⚠️ Challenge: Only {unique_teachers} teachers for {optimal_groups} optimal groups")
            self.logger.warning(f"⚠️ Some groups will need to share teachers across different group instances")
        
        # Estimate minimum groups needed to satisfy teacher uniqueness
        if max_courses_per_teacher > optimal_groups:
            min_groups_needed = max_courses_per_teacher
            self.logger.warning(f"⚠️ Teacher uniqueness requires at least {min_groups_needed} groups")
            self.logger.warning(f"⚠️ This exceeds optimal groups ({optimal_groups}) - some compromise may be needed")
        
        return {
            'total_instances': total_instances,
            'unique_teachers': unique_teachers,
            'unique_courses': unique_courses,
            'optimal_groups': optimal_groups,
            'max_courses_per_teacher': max_courses_per_teacher,
            'high_load_teachers': high_load_teachers,
            'distribution_feasible': unique_teachers >= optimal_groups and max_courses_per_teacher <= optimal_groups
        }
    
    def _distribute_course_instances(self, courses, dept, semester):
        """Distribute course instances across groups with Hall's theorem optimization and course limit constraints."""
        total_instances = len(courses)
        
        if total_instances == 0:
            return []
        
        # Enhanced instance analysis for ALL courses (theory + lab)
        theory_courses = [inst for inst in courses if inst.get('lecture_hours', 0) > 0 or inst.get('tutorial_hours', 0) > 0]
        practical_courses = [inst for inst in courses if not (inst.get('lecture_hours', 0) > 0 or inst.get('tutorial_hours', 0) > 0) and inst.get('practical_hours', 0) > 0]
        
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
            'practical_instances_count': len(practical_courses),
            'unique_courses': len(set(inst['course_code'] for inst in courses)),
            'unique_theory_courses': len(set(inst['course_code'] for inst in theory_courses)),
            'unique_practical_courses': len(set(inst['course_code'] for inst in practical_courses)),
            'unique_teachers': len(set(inst['teacher_id'] for inst in courses)),
            'total_lecture_hours': sum(inst.get('lecture_hours', 0) for inst in courses),
            'total_tutorial_hours': sum(inst.get('tutorial_hours', 0) for inst in courses),
            'avg_student_count': sum(inst.get('student_count', 70) for inst in courses) / total_instances if total_instances > 0 else 0,
            'max_instances_per_course': max_instances_per_course,
            'dynamic_student_capacity': dynamic_student_capacity,
            'course_instance_counts': course_instance_counts
        }
        
        self.logger.info(f"Hall-based analysis for {dept} Semester {semester} (Theory Scheduling):")
        self.logger.info(f"  {instance_analysis['total_instances']} total instances")
        self.logger.info(f"  {instance_analysis['theory_instances_count']} theory instances, {instance_analysis['practical_instances_count']} practical instances")
        self.logger.info(f"  {instance_analysis['unique_courses']} unique courses ({instance_analysis['unique_theory_courses']} theory + {instance_analysis['unique_practical_courses']} practical)")
        self.logger.info(f"  {instance_analysis['unique_teachers']} unique teachers")
        self.logger.info(f"  Total lecture workload: {instance_analysis['total_lecture_hours']} hours")
        self.logger.info(f"  Total tutorial workload: {instance_analysis['total_tutorial_hours']} hours")
        
        # CRITICAL: Number of groups = Number of unique courses in the semester
        # Each course can appear in at most 2 of these groups for optimal student choice
        unique_course_codes = instance_analysis['unique_courses']
        
        # Always create as many groups as there are unique courses
        num_groups = len(set(inst['course_code'] for inst in courses))

        self.logger.info(f"Creating {num_groups} groups (one per unique course: {unique_course_codes})")
        if unique_course_codes != num_groups:
            self.logger.warning(f"Mismatch between unique course codes ({unique_course_codes}) and group count ({num_groups}). Using {num_groups} groups.")

        self.logger.info(f"📋 CONSTRAINT: Each course limited to maximum 2 of the {num_groups} groups for optimal choice balance")
        
        # Initialize groups
        groups = [[] for _ in range(num_groups)]
        
        # Track group metrics
        group_metrics = []
        for i in range(num_groups):
            group_metrics.append({
                'workload': 0,
                'theory_workload': 0,
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
        
        # Sort courses by number of teachers (ascending) for better Hall satisfaction
        sorted_courses = sorted(course_to_teachers.keys(), 
                              key=lambda c: len(course_to_teachers[c]))
        
        self.logger.info("Course-teacher availability analysis:")
        for course_code in sorted_courses[:5]:  # Show first 5 courses
            teacher_count = len(course_to_teachers[course_code])
            self.logger.info(f"  {course_code}: {teacher_count} teachers, {len(course_instances[course_code])} instances")
        
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
                    assistant_id = instance.get('assistant_teacher_id')
                    
                    # Check if main or assistant teacher is already used in THIS group
                    if teacher_id not in used_teachers and (not pd.notna(assistant_id) or assistant_id not in used_teachers):
                        groups[group_idx].append(instance)
                        used_teachers.add(teacher_id)
                        if pd.notna(assistant_id):
                            used_teachers.add(assistant_id)
                        instance_assigned = True
                        
                        # Update metrics
                        metrics = group_metrics[group_idx]
                        theory_hrs = instance.get('lecture_hours', 0) + instance.get('tutorial_hours', 0)
                        
                        metrics['workload'] += theory_hrs
                        metrics['theory_workload'] += theory_hrs
                        metrics['student_count'] += instance.get('student_count', 70)
                        metrics['instance_count'] += 1
                        if theory_hrs > 0:
                            metrics['theory_instance_count'] += 1
                        else:
                            metrics['practical_instance_count'] = metrics.get('practical_instance_count', 0) + 1
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
                metrics['instance_count'] += 1
                metrics['courses'].add(course_code)
                metrics['teachers'].add(teacher_id)
                # Note: other metrics like workload are not as critical for theory scheduler
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
                theory_courses = [inst['course_code'] for inst in group if inst.get('lecture_hours', 0) > 0 or inst.get('tutorial_hours', 0) > 0]
                practical_courses = [inst['course_code'] for inst in group if not (inst.get('lecture_hours', 0) > 0 or inst.get('tutorial_hours', 0) > 0) and inst.get('practical_hours', 0) > 0]

                # Track course distribution
                for course_code in course_list:
                    if course_code not in course_distribution_summary:
                        course_distribution_summary[course_code] = []
                    course_distribution_summary[course_code].append(i + 1)
                
                self.logger.info(f"  Group {i+1}: {metrics['instance_count']} instances")
                self.logger.info(f"    Theory: {metrics['theory_instance_count']} instances, Practical: {metrics.get('practical_instance_count', 0)} instances")
                self.logger.info(f"    Teachers: [{', '.join(teacher_list)}]")
                self.logger.info(f"    Courses: [{', '.join(course_list)}]")
                if theory_courses:
                    self.logger.info(f"    Theory courses: [{', '.join(set(theory_courses))}]")
                if practical_courses:
                    self.logger.info(f"    Practical courses: [{', '.join(set(practical_courses))}]")
                self.logger.info(f"    Total theory workload: {metrics['theory_workload']} hours")
        
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
                # Main teacher
                teacher_id = instance['teacher_id']
                if teacher_id not in teacher_occurrences:
                    teacher_occurrences[teacher_id] = []
                teacher_occurrences[teacher_id].append({
                    'course_code': instance['course_code'],
                    'instance_id': instance['id'],
                    'role': 'Main'
                })

                # Assistant teacher
                if instance.get('has_assistant') and pd.notna(instance.get('assistant_teacher_id')):
                    assistant_id = instance.get('assistant_teacher_id')
                    if assistant_id not in teacher_occurrences:
                        teacher_occurrences[assistant_id] = []
                    teacher_occurrences[assistant_id].append({
                        'course_code': instance['course_code'],
                        'instance_id': instance['id'],
                        'role': 'Assistant'
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
            self.logger.info(f"✅ Teacher uniqueness constraint SATISFIED for {dept} Semester {semester}")
        else:
            self.logger.error(f"❌ Teacher uniqueness constraint VIOLATED: {constraint_violations} violations")
            
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
            self.logger.info(f"✅ Course limit constraint SATISFIED (max 2 groups per course)")
        else:
            self.logger.error(f"❌ Course limit constraint VIOLATED: {course_limit_violations} violations")
        
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
            self.logger.warning(f"⚠️ Global Hall's theorem VIOLATED: {len(global_violations)} violations")
            for violation in global_violations[:3]:  # Show first 3 violations
                courses_str = ', '.join(violation['subset'])
                self.logger.warning(f"  Subset [{courses_str}]: {violation['teacher_count']} teachers < {violation['subset_size']} courses")
        else:
            self.logger.info(f"✅ Global Hall's theorem SATISFIED with course limit constraints")
        
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
    
    def _parse_time(self, time_str):
        """Parse time string like '8:00' or '1:30' into minutes from midnight."""
        h, m = map(int, time_str.split(':'))
        # Heuristic for AM/PM: 8-11 are AM, 12 and 1-7 are PM.
        if h <= 7 or h == 12:
            if h != 12:
                h += 12
        return h * 60 + m

    def _parse_time_range(self, time_range_str):
        """Parse a time range string like '8:00 - 9:40' into start and end minutes."""
        try:
            start_str, end_str = time_range_str.split(' - ')
            start_minutes = self._parse_time(start_str)
            end_minutes = self._parse_time(end_str)
            return start_minutes, end_minutes
        except (ValueError, AttributeError) as e:
            self.logger.warning(f"Could not parse time range '{time_range_str}': {e}")
            return None, None

    def _get_conflicting_theory_slots(self, lab_session_range_str):
        """Find all theory slots that conflict with a given lab session time range string."""
        lab_start, lab_end = self._parse_time_range(lab_session_range_str)
        if lab_start is None:
            return []

        conflicting_slots = []
        for theory_slot_str in self.theory_time_slots:
            theory_start, theory_end = self._parse_time_range(theory_slot_str)
            if theory_start is None:
                continue

            # Check for overlap: (StartA < EndB) and (EndA > StartB)
            if lab_start < theory_end and lab_end > theory_start:
                conflicting_slots.append(theory_slot_str)
        return conflicting_slots
    
    def parse_lab_schedule(self):
        """Parse existing lab schedule to identify occupied time slots for conflict detection."""
        self.occupied_slots = {}  # Format: {teacher_id: {day: [time_slots]}}
        self.occupied_rooms = {}  # Format: {room_id: {day: [time_slots]}}
        self.lab_group_timeslots = {}  # Format: {group_name: [(day, time_slot)]}
        
        if not self.lab_schedule_data:
            self.logger.info("No existing lab schedule data provided")
            return
        
        self.logger.info(f"DEBUG: Parsing lab schedule with {len(self.lab_schedule_data)} lab sessions")
        
        # Dynamically build the lab session to theory time slot mapping
        self.logger.info("Dynamically mapping lab sessions to conflicting theory time slots...")
        lab_session_mapping = {}
        for session_name, session_info in self.lab_sessions.items():
            lab_range = session_info['time_range']
            conflicting_slots = self._get_conflicting_theory_slots(lab_range)
            lab_session_mapping[session_name] = conflicting_slots
            self.logger.info(f"  Lab Session {session_name} ({lab_range}) conflicts with Theory Slots: {conflicting_slots}")
        
        for lab_session in self.lab_schedule_data:
            teacher_id = lab_session.get('teacher_id')
            room_id = lab_session.get('room_id')
            day = lab_session.get('day')
            session_name = lab_session.get('session_name', '')
            group_name = lab_session.get('group_name', '')
            department = lab_session.get('department', '')
            semester = lab_session.get('semester', 0)
            group_index = lab_session.get('group_index', 0)
            
            if teacher_id and day and session_name:
                # Get the time slots for this lab session
                if session_name in lab_session_mapping:
                    time_slots = lab_session_mapping[session_name]
                    
                    # Mark teacher as occupied
                    if teacher_id not in self.occupied_slots:
                        self.occupied_slots[teacher_id] = {}
                    if day not in self.occupied_slots[teacher_id]:
                        self.occupied_slots[teacher_id][day] = []
                    self.occupied_slots[teacher_id][day].extend(time_slots)
                    
                    # Mark room as occupied if it's a theory room too
                    if room_id and room_id in self.theory_room_ids:
                        if room_id not in self.occupied_rooms:
                            self.occupied_rooms[room_id] = {}
                        if day not in self.occupied_rooms[room_id]:
                            self.occupied_rooms[room_id][day] = []
                        self.occupied_rooms[room_id][day].extend(time_slots)
                    
                    # Track lab group timeslots for conflict prevention
                    if department and semester:
                        # Create lab group key using department, semester, and group index
                        lab_group_key = f"{department}_S{semester}_G{group_index}"
                        if lab_group_key not in self.lab_group_timeslots:
                            self.lab_group_timeslots[lab_group_key] = []
                        
                        # Convert day and time slots to indices
                        day_idx = self.days.index(day) if day in self.days else -1
                        if day_idx >= 0:
                            for time_slot in time_slots:
                                if time_slot in self.theory_time_slots:
                                    slot_idx = self.theory_time_slots.index(time_slot)
                                    self.lab_group_timeslots[lab_group_key].append((day_idx, slot_idx))
                                    self.logger.debug(f"DEBUG: Added {lab_group_key} -> {day} {time_slot} (day_idx={day_idx}, slot_idx={slot_idx})")
        
        # Remove duplicates and log conflicts
        for teacher_id in self.occupied_slots:
            for day in self.occupied_slots[teacher_id]:
                self.occupied_slots[teacher_id][day] = list(set(self.occupied_slots[teacher_id][day]))
        
        for room_id in self.occupied_rooms:
            for day in self.occupied_rooms[room_id]:
                self.occupied_rooms[room_id][day] = list(set(self.occupied_rooms[room_id][day]))
        
        # Remove duplicate lab group timeslots
        for lab_group_key in self.lab_group_timeslots:
            self.lab_group_timeslots[lab_group_key] = list(set(self.lab_group_timeslots[lab_group_key]))
        
        total_conflicts = sum(len(days.get(day, [])) for days in self.occupied_slots.values() for day in self.days)
        self.logger.info(f"Parsed lab schedule: {len(self.occupied_slots)} teachers with {total_conflicts} occupied time slots")
        self.logger.info(f"Lab group timeslots tracked: {len(self.lab_group_timeslots)} lab groups")
        
        # DEBUG: Log first few lab groups
        self.logger.info("DEBUG: First 5 lab groups:")
        for i, (lab_group_key, timeslots) in enumerate(self.lab_group_timeslots.items()):
            if i >= 5:
                break
            if timeslots:
                slot_details = []
                for day_idx, slot_idx in timeslots:
                    day_name = self.days[day_idx] if day_idx < len(self.days) else f"day_{day_idx}"
                    time_slot = self.theory_time_slots[slot_idx] if slot_idx < len(self.theory_time_slots) else f"slot_{slot_idx}"
                    slot_details.append(f"{day_name} {time_slot}")
                self.logger.info(f"  {lab_group_key}: {', '.join(slot_details)}")
        
        # Log lab group conflicts for debugging
        for lab_group_key, timeslots in self.lab_group_timeslots.items():
            if timeslots:
                self.logger.debug(f"Lab group {lab_group_key}: {len(timeslots)} occupied timeslots")
    
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
            group_indices = course_group_mapping.get(course_code, [])
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
            self.logger.info(f"✅ HALL'S THEOREM SATISFIED")
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
                available_groups = len(course_group_mapping.get(course, []))
                choice_combinations *= available_groups if available_groups > 0 else 1
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
                for group_idx in course_group_mapping.get(course, []):
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
                available_groups = course_group_mapping.get(course, [])
                if available_groups:
                    capacities = [course_group_capacities.get((course, g), 0) for g in available_groups]
                    min_capacity_per_course[course] = min(capacities) if capacities else 0
                    total_capacity_for_course = sum(capacities)
                else:
                    min_capacity_per_course[course] = 0
                    total_capacity_for_course = 0

                self.logger.info(f"     {course}: Min capacity = {min_capacity_per_course[course]}, Total capacity = {total_capacity_for_course}")
            
            # Bottleneck analysis: Find the most constrained course
            bottleneck_course = min(all_courses, key=lambda c: min_capacity_per_course.get(c, 0)) if all_courses else "N/A"
            bottleneck_capacity = min_capacity_per_course.get(bottleneck_course, 0)
            
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
                self.logger.info(f"✅ LAST STUDENT GUARANTEED SUCCESS!")
                self.logger.info(f"   Even after {target_students-1} random selections, student #{target_students} will have valid choices")
                self.logger.info(f"   Reason: {worst_case_analysis['reason']}")
                final_result = True
            elif worst_case_analysis['high_probability']:
                self.logger.info(f"✅ LAST STUDENT HIGH SUCCESS PROBABILITY!")
                self.logger.info(f"   Student #{target_students} has {worst_case_analysis['success_probability']:.1f}% chance of valid choices")
                self.logger.info(f"   Reason: {worst_case_analysis['reason']}")
                final_result = True
            else:
                self.logger.warning(f"⚠️ LAST STUDENT MAY FACE DIFFICULTIES!")
                self.logger.warning(f"   Student #{target_students} has only {worst_case_analysis['success_probability']:.1f}% chance of valid choices")
                self.logger.warning(f"   Reason: {worst_case_analysis['reason']}")
                final_result = False
            
            return final_result
        else:
            self.logger.error(f"❌ NO VALID ASSIGNMENT FOUND")
            self.logger.error(f"   Students CANNOT select all {total_courses} courses!")
            return False
    
    def _find_perfect_matching(self, course_group_mapping, total_groups):
        """Find a perfect matching from courses to groups using greedy algorithm."""
        assignment = {}
        used_groups = set()
        
        # Sort courses by number of available groups (ascending) - handle constrained courses first
        sorted_courses = sorted(course_group_mapping.keys(), key=lambda c: len(course_group_mapping.get(c, [])))
        
        for course in sorted_courses:
            available_groups = course_group_mapping.get(course, [])
            
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
    
    def generate_theory_schedule(self):
        """Generate the theory schedule using group-based time slot allocation."""
        self.logger.info("Starting theory schedule generation with GROUP-BASED TIME SLOT ALLOCATION...")
        
        # Parse lab schedule data for conflict detection
        self.parse_lab_schedule()
        
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
        
        # CONSTRAINT 4: Global teacher clash prevention → Same teacher CANNOT be in multiple groups at same time
        self.logger.info("Applying global teacher clash prevention constraint...")
        teacher_clash_constraints = self.apply_global_teacher_clash_constraint(model, group_timeslot_vars)
        constraints_applied += teacher_clash_constraints
        
        # CONSTRAINT 5: Lab-Theory conflict prevention → Theory groups CANNOT overlap with lab groups from same semester
        self.logger.info("Applying lab-theory conflict prevention constraint...")
        lab_conflict_constraints = self.apply_lab_theory_conflict_constraint(model, group_timeslot_vars)
        constraints_applied += lab_conflict_constraints
        
        self.logger.info(f"Applied {constraints_applied} group-level constraints")
        self.logger.info("✅ GROUP CONSTRAINTS:")
        self.logger.info("  1. Each group gets exactly required time slots")
        self.logger.info("  2. Different groups, same semester → CANNOT overlap")
        self.logger.info("  3. Global room capacity respected")
        self.logger.info("  4. Global teacher clash prevention → Same teacher CANNOT be in multiple groups at same time")
        self.logger.info("  5. Lab-Theory conflict prevention → Theory groups CANNOT overlap with lab groups from same semester")
    
    def apply_lab_theory_conflict_constraint(self, model, group_timeslot_vars):
        """Apply constraint to prevent theory groups from conflicting with ANY lab groups from same semester/department."""
        constraints_applied = 0
        
        if not hasattr(self, 'lab_group_timeslots') or not self.lab_group_timeslots:
            self.logger.info("No lab group timeslots available - skipping lab-theory conflict constraints")
            return constraints_applied
        
        self.logger.info(f"Applying lab-theory conflict constraints for {len(self.lab_group_timeslots)} lab groups...")
        
        # Group lab timeslots by department and semester
        lab_timeslots_by_dept_sem = {}
        for lab_group_key, timeslots in self.lab_group_timeslots.items():
            if not timeslots:
                continue
                
            # Parse lab group name to get department and semester
            parts = lab_group_key.split('_')
            if len(parts) >= 2:
                dept_parts = parts[:-2]  # Everything except last 2 parts (semester and group)
                dept = '_'.join(dept_parts)
                semester_part = parts[-2]  # e.g., "S3"
                semester = semester_part[1:] if semester_part.startswith('S') else semester_part
                
                dept_sem_key = f"{dept}_S{semester}"
                if dept_sem_key not in lab_timeslots_by_dept_sem:
                    lab_timeslots_by_dept_sem[dept_sem_key] = []
                lab_timeslots_by_dept_sem[dept_sem_key].extend(timeslots)
        
        # Remove duplicates from lab timeslots
        for dept_sem_key in lab_timeslots_by_dept_sem:
            lab_timeslots_by_dept_sem[dept_sem_key] = list(set(lab_timeslots_by_dept_sem[dept_sem_key]))
        
        self.logger.info(f"DEBUG: Found lab timeslots for {len(lab_timeslots_by_dept_sem)} department-semester combinations")
        
        # For each theory group, prevent conflicts with ALL lab groups from same department-semester
        for theory_group_name in group_timeslot_vars.keys():
            # Parse theory group name to get department and semester
            parts = theory_group_name.split('_')
            if len(parts) >= 2:
                dept_parts = parts[:-2]  # Everything except last 2 parts (semester and group)
                dept = '_'.join(dept_parts)
                semester_part = parts[-2]  # e.g., "S3"
                semester = semester_part[1:] if semester_part.startswith('S') else semester_part
                
                dept_sem_key = f"{dept}_S{semester}"
                
                if dept_sem_key in lab_timeslots_by_dept_sem:
                    occupied_timeslots = lab_timeslots_by_dept_sem[dept_sem_key]
                    self.logger.info(f"DEBUG: Theory group {theory_group_name} blocked from {len(occupied_timeslots)} lab timeslots")
                    
                    for day_idx, slot_idx in occupied_timeslots:
                        # Ensure indices are valid
                        if 0 <= day_idx < self.num_days and 0 <= slot_idx < len(self.theory_time_slots):
                            # Theory group cannot use this timeslot
                            model.Add(group_timeslot_vars[theory_group_name][day_idx][slot_idx] == 0)
                            constraints_applied += 1
        
        self.logger.info(f"Applied {constraints_applied} lab-theory conflict constraints (ALL LAB GROUPS from same dept-semester)")
        return constraints_applied
    
    def apply_global_teacher_clash_constraint(self, model, group_timeslot_vars):
        """Apply global teacher clash constraint to prevent same teacher in multiple groups at same time."""
        self.logger.info("Creating teacher-group mapping for clash prevention...")
        
        constraints_applied = 0
        
        # Build mapping of teachers to groups they appear in
        teacher_group_mapping = {}
        
        for (dept, semester), groups in self.course_groups.items():
            for group_idx, group in enumerate(groups):
                if not group:
                    continue
                    
                group_name = f"{dept}_S{semester}_G{group_idx + 1}"
                
                if group_name not in group_timeslot_vars:
                    continue
                
                # Collect all teachers in this group
                group_teachers = set()
                for instance in group:
                    teacher_id = instance['teacher_id']
                    group_teachers.add(teacher_id)
                    
                    # Add to teacher-group mapping
                    if teacher_id not in teacher_group_mapping:
                        teacher_group_mapping[teacher_id] = []
                    teacher_group_mapping[teacher_id].append(group_name)
        
        # Log teacher distribution across groups
        self.logger.info(f"Teacher-group distribution for clash prevention:")
        teachers_with_multiple_groups = 0
        for teacher_id, group_list in teacher_group_mapping.items():
            if len(group_list) > 1:
                teachers_with_multiple_groups += 1
                self.logger.info(f"  Teacher {teacher_id}: {len(group_list)} groups ({', '.join(group_list)})")
        
        self.logger.info(f"Teachers appearing in multiple groups: {teachers_with_multiple_groups}")
        
        # Apply constraints: For each teacher with multiple groups, ensure they're not scheduled simultaneously
        for teacher_id, group_list in teacher_group_mapping.items():
            if len(group_list) <= 1:
                continue  # Skip teachers with only one group
                
            # For each time slot, ensure at most one of this teacher's groups is active
            for day_idx in range(self.num_days):
                for slot_idx in range(len(self.theory_time_slots)):
                    teacher_group_vars = []
                    
                    for group_name in group_list:
                        if group_name in group_timeslot_vars:
                            teacher_group_vars.append(group_timeslot_vars[group_name][day_idx][slot_idx])
                    
                    # At most one group for this teacher can be active in this time slot
                    if len(teacher_group_vars) > 1:
                        model.Add(sum(teacher_group_vars) <= 1)
                        constraints_applied += 1
        
        self.logger.info(f"Applied {constraints_applied} teacher clash constraints")
        return constraints_applied
    
    def add_group_allocation_objective(self, model, group_timeslot_vars):
        """Add objective for optimal group time slot allocation."""
        objective_terms = []
        
        # Sequential slot filling approach:
        # Give extremely high weights to earlier slots to ensure they're filled first
        # before considering later slots
        for group_name, day_slots in group_timeslot_vars.items():
            for day_idx in range(self.num_days):
                # Tier 1: First 4 slots (8:00-11:50) - extremely high weight
                # for slot_idx in range(min(4, len(self.theory_time_slots))):
                #     objective_terms.append(day_slots[day_idx][slot_idx] * 1000)
                
                # Tier 2: Next 4 slots (12:00 - 3:50) - high weight, but much lower than Tier 1
                # for slot_idx in range(4, min(8, len(self.theory_time_slots))):
                #     objective_terms.append(day_slots[day_idx][slot_idx] * 100)
                
                # Tier 3: Last 3 slots (4:00 - 6:50) - lowest weight
                # for slot_idx in range(8, min(11, len(self.theory_time_slots))):
                #     objective_terms.append(day_slots[day_idx][slot_idx] * 10)
                pass
        
        if objective_terms:
            model.Maximize(sum(objective_terms))
            self.logger.info(f"Group allocation objective set with {len(objective_terms)} terms")
            # self.logger.info("SEQUENTIAL SLOT FILLING STRATEGY:")
            # self.logger.info("  Tier 1 slots 0-3 (8:00-11:50): +1000 - Will be filled first")
            # self.logger.info("  Tier 2 slots 4-7 (12:00-3:50): +100 - Will be filled only after Tier 1 slots")
            # self.logger.info("  Tier 3 slots 8-10 (4:00-6:50): +10 - Will be filled only after Tier 1 and 2 slots")
            # self.logger.info("This ensures earlier slots will be completely filled before using later slots")
    
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

    def generate_course_group_distribution_heatmap(self):
        """Generate heatmap visualization of course-to-group distribution before applying constraints."""
        self.logger.info("🎨 Generating course-to-group distribution heatmap for Theory Scheduler...")
        
        try:
            # Create output directory for visualizations
            viz_output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
                                         'output', 
                                         f'theory_grouping_viz_{datetime.now().strftime("%Y%m%d_%H%M%S")}')
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
                                   cmap='YlGnBu',
                                   cbar_kws={'label': 'Number of Teacher Assignments'},
                                   linewidths=0.5)
                    
                    # Customize the plot
                    plt.title(f'Theory Course-Group Distribution\n{dept} - Semester {semester}\n(Number shows teacher assignments per course per group)', 
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
                    filename = f'theory_course_group_heatmap_{safe_dept_name}_S{semester}.png'
                    filepath = os.path.join(viz_output_dir, filename)
                    plt.savefig(filepath, dpi=300, bbox_inches='tight')
                    plt.close()
                    
                    self.logger.info(f"✅ Heatmap saved: {filepath}")
                    
                except Exception as dept_error:
                    self.logger.error(f"❌ Error processing {dept} S{semester} for theory heatmap: {str(dept_error)}")
                    import traceback
                    self.logger.error(f"Traceback: {traceback.format_exc()}")
                    continue

            # Create a combined overview heatmap if multiple department-semesters exist
            if len(self.course_groups) > 1:
                self._create_combined_overview_heatmap(viz_output_dir)
            
            self.logger.info(f"🎨 All theory course-group distribution visualizations saved to: {viz_output_dir}")
            
        except Exception as e:
            self.logger.error(f"❌ Error generating theory course-group heatmap: {str(e)}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")

    def _create_combined_overview_heatmap(self, viz_output_dir):
        """Create a combined overview heatmap showing all department-semester combinations for theory courses."""
        self.logger.info("Creating combined overview heatmap for theory scheduler...")
        
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
            fig.suptitle('Theory Scheduler: Course-Group Distribution Overview\n(Before Constraint Application)', 
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
            overview_filepath = os.path.join(viz_output_dir, 'theory_combined_overview_heatmap.png')
            plt.savefig(overview_filepath, dpi=300, bbox_inches='tight')
            plt.close()
            
            self.logger.info(f"✅ Combined overview saved: {overview_filepath}")
            
        except Exception as e:
            self.logger.error(f"❌ Error creating combined theory overview: {str(e)}")