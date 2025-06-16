#!/usr/bin/env python3
"""
Combined Timetable Scheduler

Unified scheduler that handles both lab and theory sessions with their respective time structures.
"""

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

class CombinedScheduler:
    """
    Unified scheduler that handles both lab and theory sessions with separate time structures.
    
    Key Features:
    - Theory sessions use 11-slot theory time structure (1 hour each)
    - Lab sessions use 12-slot lab time structure (grouped into 6 sessions of 2 hours each)
    - Cross-system conflict detection and resolution
    - Unified group creation and constraint management
    """
    
    def __init__(self, course_file, room_file):
        """Initialize the combined scheduler for unified lab and theory scheduling."""
        self.logger = logging.getLogger('src.combined_scheduler')
        self.logger.info("Initializing Combined Scheduler...")
        
        # Store input files
        self.course_file = course_file
        self.room_file = room_file
        
        # Load and process data
        self.courses_df = pd.read_csv(course_file)
        self.rooms_df = pd.read_csv(room_file)
        
        # Set up time configurations - MATCHING ORIGINAL SCHEDULERS
        # Using the EXACT same configuration as lab_scheduler.py and theory_scheduler.py
        self.days = ["tuesday", "wed", "thur", "fri", "sat"]  # Excluding Monday - EXACTLY as in original
        self.num_days = len(self.days)
        
        # LAB TIME CONFIGURATION - EXACTLY as in lab_scheduler.py
        self.lab_time_slots = [
            "8:00 - 8:50", "8:50 - 9:40", "9:50 - 10:40", "10:40 - 11:30",
            "11:50 - 12:40", "12:40 - 1:30", "1:50 - 2:40", "2:40 - 3:30", 
            "3:50 - 4:40", "4:40 - 5:30", "5:30 - 6:20", "6:20 - 7:10"
        ]
        self.num_lab_slots = len(self.lab_time_slots)
        
        # Group lab slots into 2-hour sessions (L1, L2, L3, etc.) - EXACTLY as in lab_scheduler.py
        self.lab_sessions = {
            'L1': ['8:00 - 8:50', '8:50 - 9:40'],      # 8:00 - 9:40
            'L2': ['9:50 - 10:40', '10:40 - 11:30'],   # 9:50 - 11:30  
            'L3': ['11:50 - 12:40', '12:40 - 1:30'],   # 11:50 - 1:30
            'L4': ['1:50 - 2:40', '2:40 - 3:30'],      # 1:50 - 3:30
            'L5': ['3:50 - 4:40', '4:40 - 5:30'],      # 3:50 - 5:30
            'L6': ['5:30 - 6:20', '6:20 - 7:10']       # 5:30 - 7:10
        }
        
        # THEORY TIME CONFIGURATION - EXACTLY as in theory_scheduler.py
        self.theory_time_slots = [
            "8:00 - 8:50", "9:00 - 9:50", "10:00 - 10:50", "11:00 - 11:50",
            "12:00 - 12:50", "1:00 - 1:50", "2:00 - 2:50", "3:00 - 3:50", 
            "4:00 - 4:50", "5:00 - 5:50", "6:00 - 6:50"
        ]
        self.num_theory_slots = len(self.theory_time_slots)
        
        # Build time slot mapping between lab and theory
        self._build_time_mapping()
        
        # ROOM PROCESSING
        self.lab_rooms = self.rooms_df[self.rooms_df['is_lab'] == 1]
        self.theory_rooms = self.rooms_df[self.rooms_df['is_lab'] == 0]
        self.lab_room_ids = self.lab_rooms['id'].tolist()
        self.theory_room_ids = self.theory_rooms['id'].tolist()
        self.laboratory_room_ids = self.lab_rooms[self.lab_rooms['room_type'] == 'Laboratory']['id'].tolist()
        self.logger.info(f"Found {len(self.laboratory_room_ids)} rooms of type 'Laboratory'.")
        
        # COURSE PROCESSING
        self.process_courses()
        
        # CREATE COURSE GROUPS (unified for lab and theory)
        self.create_course_groups()
        
        # COMPUTE GROUP REQUIREMENTS EARLY
        self._compute_group_requirements()
        
        # VALIDATE GROUP STRUCTURE
        self.logger.info("[OK] UNIFIED CONSTRAINTS: Both lab and theory respect same group structure")
        self.logger.info("[OK] HALL'S THEOREM COMPLIANCE: Optimized for maximum student choice")
        
        # Get teacher list for cross-system constraints
        self.teachers = set()
        for teacher_group in [self.lab_requirements.keys(), self.theory_requirements.keys()]:
            self.teachers.update(teacher_group)
        self.teachers = list(self.teachers)
        
        # Create output directory
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_dir = f"output/combined_schedule_{timestamp}"
        os.makedirs(self.output_dir, exist_ok=True)
        
        self.logger.info("Combined Scheduler initialized successfully")
        self.logger.info(f"Theory time slots: {self.num_theory_slots}")
        self.logger.info(f"Lab time slots: {self.num_lab_slots}")
        self.logger.info(f"Lab rooms: {len(self.lab_room_ids)}")
        self.logger.info(f"Theory rooms: {len(self.theory_room_ids)}")
    
    def _compute_group_requirements(self):
        """Compute theory time slot requirements for each group."""
        self.logger.info("Computing group time slot requirements...")
        
        # Calculate time slot requirements for each group
        self.group_requirements = {}
        
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
                
                # Allocate slots based on max theory hours (minimum 3, maximum 6)
                required_slots = max(3, min(6, max_theory_hours))
                self.group_requirements[group_name] = required_slots
                
                self.logger.info(f"Group {group_name}: {len(group)} instances, max {max_theory_hours}h -> {required_slots} time slots")
        
        self.logger.info(f"Group requirements computed for {len(self.group_requirements)} groups")
        return self.group_requirements
    
    def _build_time_mapping(self):
        """Build mapping between theory and lab time systems for conflict detection."""
        self.logger.info("Building cross-system time mapping...")
        
        # Theory slot to lab slot mapping (for conflict detection)
        self.theory_to_lab_mapping = {}
        self.lab_to_theory_mapping = {}
        
        # Helper function to parse time string to minutes
        def time_to_minutes(time_str):
            h, m = map(int, time_str.split(':'))
            # Handle AM/PM conversion for 12-hour format with 1-hour based times
            # 1:00 -> 13:00 (1 PM), 8:00 stays 8:00 (8 AM)
            if h <= 7 and h >= 1:  # 1 PM to 7 PM
                h += 12
            return h * 60 + m
        
        # Helper function to parse time range
        def parse_time_range(time_range_str):
            try:
                # Handle format like "8:00 - 8:50" or "1:00 - 1:50"
                start_str, end_str = time_range_str.split(' - ')
                start_minutes = time_to_minutes(start_str.strip())
                end_minutes = time_to_minutes(end_str.strip())
                return start_minutes, end_minutes
            except Exception as e:
                self.logger.warning(f"Failed to parse time range '{time_range_str}': {e}")
                return None, None
        
        # Map each theory slot to overlapping lab slots
        for theory_idx, theory_slot in enumerate(self.theory_time_slots):
            theory_start, theory_end = parse_time_range(theory_slot)
            if theory_start is None:
                continue
                
            overlapping_lab_slots = []
            for lab_idx, lab_slot in enumerate(self.lab_time_slots):
                lab_start, lab_end = parse_time_range(lab_slot)
                if lab_start is None:
                    continue
                
                # Check for overlap: (StartA < EndB) and (EndA > StartB)
                if theory_start < lab_end and theory_end > lab_start:
                    overlapping_lab_slots.append(lab_idx)
            
            self.theory_to_lab_mapping[theory_idx] = overlapping_lab_slots
            self.logger.debug(f"Theory slot {theory_idx} ({theory_slot}) overlaps with lab slots: {overlapping_lab_slots}")
        
        # Map each lab slot to overlapping theory slots
        for lab_idx, lab_slot in enumerate(self.lab_time_slots):
            lab_start, lab_end = parse_time_range(lab_slot)
            if lab_start is None:
                continue
                
            overlapping_theory_slots = []
            for theory_idx, theory_slot in enumerate(self.theory_time_slots):
                theory_start, theory_end = parse_time_range(theory_slot)
                if theory_start is None:
                    continue
                
                # Check for overlap
                if lab_start < theory_end and lab_end > theory_start:
                    overlapping_theory_slots.append(theory_idx)
            
            self.lab_to_theory_mapping[lab_idx] = overlapping_theory_slots
            self.logger.debug(f"Lab slot {lab_idx} ({lab_slot}) overlaps with theory slots: {overlapping_theory_slots}")
        
        self.logger.info("Cross-system time mapping completed")
    
    def process_courses(self):
        """Process courses and separate them into lab and theory requirements."""
        self.logger.info("Processing courses for combined scheduling...")
        
        # Extract unique teachers
        self.teachers = self.courses_df['teacher_id'].unique()
        self.num_teachers = len(self.teachers)
        
        # Create unified teacher-course assignments
        self.teacher_course_assignments = {}
        self.lab_requirements = {}
        self.theory_requirements = {}
        self.course_to_teacher = {}
        
        for _, row in self.courses_df.iterrows():
            teacher_id = row['teacher_id']
            course_id = row['course_id']
            course_instance_id = str(row['id'])
            
            if teacher_id not in self.teacher_course_assignments:
                self.teacher_course_assignments[teacher_id] = []
            
            # Create unified course instance record
            course_instance = {
                'id': course_instance_id,
                'course_id': course_id,
                'course_code': row['course_code'],
                'course_name': row['course_name'],
                'course_type': row['course_type'],
                'lecture_hours': int(row.get('lecture_hours', 0)),
                'tutorial_hours': int(row.get('tutorial_hours', 0)),
                'practical_hours': int(row.get('practical_hours', 0)),
                'student_count': int(row['student_count']),
                'semester': row.get('semester', 1),
                'course_dept': row.get('course_dept', 'Computer Science & Engineering'),
                'student_dept': row.get('student_dept', 'Computer Science & Engineering'),
                'has_assistant': row['is_assistant'] == 1,
                'assistant_teacher_id': row.get('assist_teacher_id'),
                'assistant_staff_code': row.get('assist_staff_code'),
                'assistant_teacher_name': f"{row.get('assist_first_name', '')} {row.get('assist_last_name', '')}".strip()
            }
            
            self.teacher_course_assignments[teacher_id].append(course_instance)
            self.course_to_teacher[course_instance_id] = teacher_id
            
            # Categorize into lab or theory requirements
            has_practical = course_instance['practical_hours'] > 0
            has_theory = course_instance['lecture_hours'] > 0 or course_instance['tutorial_hours'] > 0
            
            if has_practical:
                if teacher_id not in self.lab_requirements:
                    self.lab_requirements[teacher_id] = []
                
                # Calculate lab sessions needed (each lab session = 2 practical hours)
                practical_hours = course_instance['practical_hours']
                base_sessions = (practical_hours + 1) // 2  # Ceiling division for proper calculation
                
                self.lab_requirements[teacher_id].append({
                    'course_instance_id': course_instance_id,
                    'course_code': course_instance['course_code'],
                    'practical_hours': practical_hours,
                    'base_sessions': base_sessions,
                    'lab_sessions_needed': base_sessions,
                    'total_lab_slots_needed': base_sessions,  # Default: no batching
                    'students_per_instance': course_instance['student_count']
                })
            
            if has_theory:
                if teacher_id not in self.theory_requirements:
                    self.theory_requirements[teacher_id] = []
                
                self.theory_requirements[teacher_id].append({
                    'course_instance_id': course_instance_id,
                    'course_code': course_instance['course_code'],
                    'lecture_hours': course_instance['lecture_hours'],
                    'tutorial_hours': course_instance['tutorial_hours'],
                    'required_lecture_sessions': course_instance['lecture_hours'],
                    'required_tutorial_sessions': course_instance['tutorial_hours'],
                    'students_per_instance': course_instance['student_count']
                })
        
        # Log processing results
        total_lab_sessions = sum(sum(c['lab_sessions_needed'] for c in courses) 
                               for teacher, courses in self.lab_requirements.items())
        total_theory_sessions = sum(sum(c['required_lecture_sessions'] + c['required_tutorial_sessions'] for c in courses) 
                                  for teacher, courses in self.theory_requirements.items())
        
        self.logger.info(f"Course processing completed:")
        self.logger.info(f"  Teachers: {self.num_teachers}")
        self.logger.info(f"  Teachers with lab requirements: {len(self.lab_requirements)}")
        self.logger.info(f"  Teachers with theory requirements: {len(self.theory_requirements)}")
        self.logger.info(f"  Total lab sessions needed: {total_lab_sessions}")
        self.logger.info(f"  Total theory sessions needed: {total_theory_sessions}")
    
    def create_course_groups(self):
        """Create unified course groups for both lab and theory using Hall's theorem distribution."""
        self.logger.info("Creating unified course groups for combined scheduling...")
        
        # Use the same group creation logic as the individual schedulers
        # This ensures consistency and optimal student choice
        self.course_groups = self._create_course_groups_by_dept_semester()
        
        # Create instance-group mapping for both lab and theory
        self.instance_group_mapping = {}
        self._create_instance_group_mapping()
        
        self.logger.info("Unified course grouping completed successfully")
        self.logger.info("[OK] UNIFIED CONSTRAINTS: Both lab and theory respect same group structure")
        self.logger.info("[OK] HALL'S THEOREM COMPLIANCE: Optimized for maximum student choice")
    
    def _create_course_groups_by_dept_semester(self):
        """Group course instances by department and semester with Hall's theorem optimization (unified for lab and theory)."""
        # This uses the SAME logic as both individual schedulers to ensure consistency
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
                'practical_hours': int(row.get('practical_hours', 0)),
                'student_count': int(row['student_count']),
                'semester': row.get('semester', 1),
                'course_dept': row.get('course_dept', 'Computer Science & Engineering'),
                'student_dept': row.get('student_dept', 'Computer Science & Engineering'),
                'has_lab': int(row.get('practical_hours', 0)) > 0,
                'has_theory': int(row.get('lecture_hours', 0)) > 0 or int(row.get('tutorial_hours', 0)) > 0,
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
            lab_instances = [i for i in instances if i['has_lab']]
            theory_instances = [i for i in instances if i['has_theory']]
            self.logger.info(f"Dept: {dept}, Semester: {semester}: {len(instances)} instances ({len(lab_instances)} lab, {len(theory_instances)} theory)")
        
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
            self.logger.warning(f"[WARNING] Challenge: Only {unique_teachers} teachers for {optimal_groups} optimal groups")
            self.logger.warning(f"[WARNING] Some groups will need to share teachers across different group instances")
        
        # Estimate minimum groups needed to satisfy teacher uniqueness
        if max_courses_per_teacher > optimal_groups:
            min_groups_needed = max_courses_per_teacher
            self.logger.warning(f"[WARNING] Teacher uniqueness requires at least {min_groups_needed} groups")
            self.logger.warning(f"[WARNING] This exceeds optimal groups ({optimal_groups}) - some compromise may be needed")
        
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
        """Distribute course instances across groups with Hall's theorem optimization and course limit constraints (unified for lab and theory)."""
        total_instances = len(courses)
        
        if total_instances == 0:
            return []
        
        # Enhanced instance analysis for ALL courses (theory + lab)
        lab_courses = [inst for inst in courses if inst['has_lab']]
        theory_courses = [inst for inst in courses if inst['has_theory']]
        
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
            'lab_instances_count': len(lab_courses),
            'theory_instances_count': len(theory_courses),
            'unique_courses': len(set(inst['course_code'] for inst in courses)),
            'unique_lab_courses': len(set(inst['course_code'] for inst in lab_courses)),
            'unique_theory_courses': len(set(inst['course_code'] for inst in theory_courses)),
            'unique_teachers': len(set(inst['teacher_id'] for inst in courses)),
            'total_practical_hours': sum(inst.get('practical_hours', 0) for inst in courses),
            'total_lecture_hours': sum(inst.get('lecture_hours', 0) for inst in courses),
            'total_tutorial_hours': sum(inst.get('tutorial_hours', 0) for inst in courses),
            'avg_student_count': sum(inst.get('student_count', 70) for inst in courses) / total_instances if total_instances > 0 else 0,
            'max_instances_per_course': max_instances_per_course,
            'dynamic_student_capacity': dynamic_student_capacity,
            'course_instance_counts': course_instance_counts
        }
        
        self.logger.info(f"Hall-based analysis for {dept} Semester {semester} (Combined Scheduling):")
        self.logger.info(f"  {instance_analysis['total_instances']} total instances")
        self.logger.info(f"  {instance_analysis['lab_instances_count']} lab instances, {instance_analysis['theory_instances_count']} theory instances")
        self.logger.info(f"  {instance_analysis['unique_courses']} unique courses ({instance_analysis['unique_lab_courses']} lab + {instance_analysis['unique_theory_courses']} theory)")
        self.logger.info(f"  {instance_analysis['unique_teachers']} unique teachers")
        self.logger.info(f"  Total practical workload: {instance_analysis['total_practical_hours']} hours")
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

        self.logger.info(f"[CONSTRAINT] Each course limited to maximum 2 of the {num_groups} groups for optimal choice balance")
        
        # Initialize groups
        groups = [[] for _ in range(num_groups)]
        
        # Track group metrics
        group_metrics = []
        for i in range(num_groups):
            group_metrics.append({
                'workload': 0,
                'lab_workload': 0,
                'theory_workload': 0,
                'student_count': 0,
                'instance_count': 0,
                'lab_instance_count': 0,
                'theory_instance_count': 0,
                'courses': set(),
                'teachers': set()
            })
        
        # Build course-teacher bipartite graph for Hall's theorem (ALL courses)
        course_to_teachers = {}
        teacher_to_courses = {}
        
        for instance in courses:  # Use ALL courses, not just lab or theory
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
        for instance in courses:  # Use ALL courses
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
                
                # Find an instance with a teacher not yet used in THIS group
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
                        practical_hrs = instance.get('practical_hours', 0)
                        theory_hrs = instance.get('lecture_hours', 0) + instance.get('tutorial_hours', 0)
                        
                        metrics['workload'] += practical_hrs + theory_hrs
                        metrics['lab_workload'] += practical_hrs
                        metrics['theory_workload'] += theory_hrs
                        metrics['student_count'] += instance.get('student_count', 70)
                        metrics['instance_count'] += 1
                        if practical_hrs > 0:
                            metrics['lab_instance_count'] += 1
                        if theory_hrs > 0:
                            metrics['theory_instance_count'] += 1
                        metrics['courses'].add(instance['course_code'])
                        metrics['teachers'].add(instance['teacher_id'])
                        
                        self.logger.debug(f"  Pre-allocated: {course_code} (T{teacher_id}) → Group {group_idx + 1}")
                        break
                
                if not instance_assigned:
                    self.logger.debug(f"  Could not pre-allocate {course_code} to Group {group_idx + 1} - no teacher available that isn't already in this group")
        
        # Phase 2: Remainder placement (similar to theory scheduler)
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
                self.logger.debug(f"[OK] Placed instance {instance['id']} ({course_code}) in Group {best_group_idx + 1} to improve student choice.")
                # Update metrics
                metrics = group_metrics[best_group_idx]
                metrics['instance_count'] += 1
                metrics['courses'].add(course_code)
                metrics['teachers'].add(teacher_id)
            else:
                failed_assignments.append(instance)
        
        # Log assignment results
        if failed_assignments:
            self.logger.error(f"Failed to assign: {len(failed_assignments)} instances after both phases.")
            for failure in failed_assignments[:5]: # Log first 5
                self.logger.error(f"  - Instance {failure['id']} (Teacher {failure['teacher_id']}, Course {failure['course_code']}) could not be placed.")

        # Validate and log final group distribution
        self._validate_teacher_uniqueness_constraint(groups, dept, semester)
        self._validate_halls_theorem(groups, dept, semester)
        
        # Log final group distribution
        self.logger.info(f"Final unified group distribution for {dept} Semester {semester}:")
        
        # Track course distribution across groups
        course_distribution_summary = {}
        
        for i, group in enumerate(groups):
            if group:  # Only show non-empty groups
                metrics = group_metrics[i]
                teacher_list = sorted(set(str(instance['teacher_id']) for instance in group))
                course_list = sorted(set(instance['course_code'] for instance in group))
                lab_courses = [inst['course_code'] for inst in group if inst['has_lab']]
                theory_courses = [inst['course_code'] for inst in group if inst['has_theory']]

                # Track course distribution
                for course_code in course_list:
                    if course_code not in course_distribution_summary:
                        course_distribution_summary[course_code] = []
                    course_distribution_summary[course_code].append(i + 1)
                
                self.logger.info(f"  Group {i+1}: {metrics['instance_count']} instances")
                self.logger.info(f"    Lab: {metrics['lab_instance_count']} instances, Theory: {metrics['theory_instance_count']} instances")
                self.logger.info(f"    Teachers: [{', '.join(teacher_list)}]")
                self.logger.info(f"    Courses: [{', '.join(course_list)}]")
                if lab_courses:
                    self.logger.info(f"    Lab courses: [{', '.join(set(lab_courses))}]")
                if theory_courses:
                    self.logger.info(f"    Theory courses: [{', '.join(set(theory_courses))}]")
                self.logger.info(f"    Total workload: {metrics['workload']} hours ({metrics['lab_workload']} lab + {metrics['theory_workload']} theory)")
        
        # Log course distribution summary
        self.logger.info(f"\nCourse distribution summary (max 2 groups per course):")
        for course_code, group_list in sorted(course_distribution_summary.items()):
            group_names = [f"G{g}" for g in group_list]
            constraint_status = "[OK]" if len(group_list) <= 2 else "[ERROR]"
            self.logger.info(f"  {course_code}: {', '.join(group_names)} ({len(group_list)} groups) {constraint_status}")
        
        # Calculate student choice metrics
        total_courses = len(course_distribution_summary)
        courses_with_choice = len([course for course, groups_list in course_distribution_summary.items() if len(groups_list) > 1])
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
            self.logger.info(f"[OK] Teacher uniqueness constraint SATISFIED for {dept} Semester {semester}")
        else:
            self.logger.error(f"[ERROR] Teacher uniqueness constraint VIOLATED: {constraint_violations} violations")
            
        return constraint_violations == 0

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
            self.logger.info(f"[OK] Course limit constraint SATISFIED (max 2 groups per course)")
        else:
            self.logger.error(f"[ERROR] Course limit constraint VIOLATED: {course_limit_violations} violations")
        
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
            groups_count = choice_info['groups']
            teachers = choice_info['teachers']
            self.logger.info(f"  {course}: {groups_count} groups, {teachers} teachers (ratio: {choice_info['choice_ratio']:.2f})")
        
        # Check global Hall's condition for student choice
        global_violations = []
        
        from itertools import combinations
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
            self.logger.warning(f"[WARNING] Global Hall's theorem VIOLATED: {len(global_violations)} violations")
            for violation in global_violations[:3]:  # Show first 3 violations
                courses_str = ', '.join(violation['subset'])
                self.logger.warning(f"  Subset [{courses_str}]: {violation['teacher_count']} teachers < {violation['subset_size']} courses")
        else:
            self.logger.info(f"[OK] Global Hall's theorem SATISFIED with course limit constraints")
        
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
                        'has_lab': instance.get('has_lab', False),
                        'has_theory': instance.get('has_theory', False),
                        'practical_hours': instance.get('practical_hours', 0),
                        'lecture_hours': instance.get('lecture_hours', 0),
                        'tutorial_hours': instance.get('tutorial_hours', 0)
                    }
                    total_mapped_instances += 1
        
        self.logger.info(f"Instance-group mapping created: {total_mapped_instances} instances mapped")
    
    def generate_combined_schedule(self):
        """Generate the combined schedule for both lab and theory sessions."""
        self.logger.info("="*80)
        self.logger.info("STARTING COMBINED SCHEDULE GENERATION")
        self.logger.info("="*80)
        
        # Run feasibility analyses first
        if not self.analyze_theory_feasibility():
            self.logger.error("Combined scheduling is not feasible with current theory requirements and constraints")
            return False
        
        # Create the unified CP-SAT model
        model = cp_model.CpModel()
        
        # STEP 1: Create variables for both lab and theory
        self.logger.info("Creating variables for combined scheduling...")
        lab_variables = self._create_lab_variables(model)
        theory_variables = self._create_theory_variables(model)
        
        # STEP 2: Apply unified constraints
        self.logger.info("Applying unified constraints...")
        self._apply_unified_constraints(model, lab_variables, theory_variables)
        
        # STEP 3: Add group allocation objective for theory
        self.logger.info("Setting up group allocation objective...")
        self.add_group_allocation_objective(model, theory_variables)
        
        # STEP 4: Add optimization objectives
        self.logger.info("Setting up optimization objectives...")
        self._add_combined_objectives(model, lab_variables, theory_variables)
        
        # STEP 5: Solve the unified model
        self.logger.info("Solving combined scheduling model...")
        success = self._solve_combined_model(model, lab_variables, theory_variables)
        
        return success
    
    def _create_lab_variables(self, model):
        """Create CP-SAT variables for lab scheduling."""
        self.logger.info("Creating lab scheduling variables...")
        
        # Lab assignment variables: lab_assignments[teacher][course][day][session][room]
        lab_assignments = {}
        
        for teacher_id, lab_courses in self.lab_requirements.items():
            lab_assignments[teacher_id] = {}
            
            for course_req in lab_courses:
                course_instance_id = course_req['course_instance_id']
                lab_sessions_needed = course_req['lab_sessions_needed']
                
                lab_assignments[teacher_id][course_instance_id] = {}
                
                for day_idx in range(self.num_days):
                    lab_assignments[teacher_id][course_instance_id][day_idx] = {}
                    
                    for session_name in self.lab_sessions.keys():
                        lab_assignments[teacher_id][course_instance_id][day_idx][session_name] = {}
                        
                        for room_id in self.lab_room_ids:
                            var_name = f'lab_{teacher_id}_{course_instance_id}_{day_idx}_{session_name}_{room_id}'
                            lab_assignments[teacher_id][course_instance_id][day_idx][session_name][room_id] = \
                                model.NewBoolVar(var_name)
        
        self.logger.info("Lab variables created successfully")
        return lab_assignments
    
    def _create_theory_variables(self, model):
        """Create CP-SAT variables for theory scheduling using two-phase approach."""
        self.logger.info("Creating theory scheduling variables using two-phase approach...")
        
        # PHASE 1: Group timeslot allocation variables
        group_timeslot_vars = self._create_group_timeslot_variables(model)
        
        self.logger.info("Theory group timeslot variables created successfully")
        return group_timeslot_vars
    
    def _create_group_timeslot_variables(self, model):
        """Create variables for group time slot allocation (Phase 1 of two-phase approach)."""
        self.logger.info("Creating group time slot allocation variables...")
        
        group_timeslot_vars = {}
        
        # Use pre-computed group requirements
        for group_name, required_slots in self.group_requirements.items():
            self.logger.info(f"Creating variables for {group_name}: {required_slots} time slots required")
            
            # Create binary variables for each possible time slot
            group_timeslot_vars[group_name] = {}
            for day_idx in range(self.num_days):
                group_timeslot_vars[group_name][day_idx] = {}
                for slot_idx in range(self.num_theory_slots):
                    group_timeslot_vars[group_name][day_idx][slot_idx] = model.NewBoolVar(
                        f'group_{group_name}_day_{day_idx}_slot_{slot_idx}'
                    )
        
        self.logger.info(f"Created group timeslot variables for {len(group_timeslot_vars)} groups")
        return group_timeslot_vars
    
    def _apply_unified_constraints(self, model, lab_variables, theory_variables):
        """Apply unified constraints for both lab and theory scheduling."""
        constraints_applied = 0
        
        # 1. Lab-specific constraints
        constraints_applied += self._apply_lab_constraints(model, lab_variables)
        
        # 2. Theory-specific constraints (group-based)
        constraints_applied += self._apply_theory_constraints(model, theory_variables)
        
        # 3. Cross-system constraints (lab-theory conflicts)
        constraints_applied += self._apply_cross_system_constraints(model, lab_variables, theory_variables)
        
        self.logger.info(f"Applied {constraints_applied} unified constraints")
    
    def _apply_lab_constraints(self, model, lab_variables):
        """Apply lab-specific constraints."""
        self.logger.info("Applying lab-specific constraints...")
        constraints_applied = 0
        
        # Run lab capacity analysis first
        self.analyze_lab_capacity()
        
        # Apply CORE lab constraints (optimized - removed redundancies)
        constraints_applied += self.apply_course_lab_requirements_constraint(model, lab_variables)
        constraints_applied += self.apply_lab_room_single_assignment_constraint(model, lab_variables)
        constraints_applied += self.apply_teacher_clash_constraint(model, lab_variables)
        # REMOVED: apply_capacity_constraint - redundant with course_lab_requirements_constraint
        constraints_applied += self.apply_group_based_scheduling_constraint(model, lab_variables)
        # REMOVED: apply_theory_lab_group_conflict_constraint - redundant with cross-system constraints
        constraints_applied += self.apply_semester_lab_slot_limit_constraint(model, lab_variables)
        # REMOVED: apply_lab_efficiency_constraints - too restrictive and redundant with other constraints
        
        self.logger.info(f"Applied {constraints_applied} lab-specific constraints (optimized)")
        return constraints_applied

    def apply_course_lab_requirements_constraint(self, model, lab_variables):
        """CONSTRAINT: Each course must be scheduled for its required number of lab sessions."""
        self.logger.info("Applying course lab requirements constraint...")
        constraints_applied = 0
        
        for teacher_id, lab_courses in self.lab_requirements.items():
            for course_req in lab_courses:
                course_instance_id = course_req['course_instance_id']
                base_sessions = course_req['base_sessions']
                practical_hours = course_req['practical_hours']
                students_per_instance = course_req['students_per_instance']
                
                if teacher_id in lab_variables and course_instance_id in lab_variables[teacher_id]:
                    # Collect all assignment variables for this course
                    total_assignments = []
                    for day_idx in range(self.num_days):
                        for session_name in self.lab_sessions.keys():
                            for room_id in self.lab_room_ids:
                                total_assignments.append(
                                    lab_variables[teacher_id][course_instance_id][day_idx][session_name][room_id]
                                )
                    
                    # Get lab capacity categories
                    labs_35 = [lab['id'] for lab in self.lab_capacity_analysis['labs_35']]
                    labs_70_plus = [lab['id'] for lab in self.lab_capacity_analysis['labs_70']] + [lab['id'] for lab in self.lab_capacity_analysis['labs_140']]
                    
                    # Calculate expected sessions based on potential batching
                    student_count = students_per_instance
                    
                    # If course might be assigned to 35-cap labs and has >35 students, plan for batching
                    assignments_in_35_cap = []
                    assignments_in_70_plus_cap = []
                    
                    for day_idx in range(self.num_days):
                        for session_name in self.lab_sessions.keys():
                            for room_id in self.lab_room_ids:
                                assignment_var = lab_variables[teacher_id][course_instance_id][day_idx][session_name][room_id]
                                if room_id in labs_35:
                                    assignments_in_35_cap.append(assignment_var)
                                else:
                                    assignments_in_70_plus_cap.append(assignment_var)
                    
                    # Create conditional constraint based on lab capacity assignment
                    if student_count > 35:
                        # CRITICAL: Either ALL sessions in 35-cap (with batching) OR ALL sessions in 70+ cap (no batching)
                        total_35_assignments = sum(assignments_in_35_cap)
                        total_70_plus_assignments = sum(assignments_in_70_plus_cap)
                        
                        # Calculate sessions needed for batching in 35-cap labs
                        num_batches_35 = (student_count + 34) // 35
                        sessions_with_batching = base_sessions * num_batches_35
                        
                        # APPLY SLOT RESTRICTIONS BASED ON PRACTICAL HOURS
                        if practical_hours >= 6:
                            # 6+ practical hours: Allow up to 6 slots if batched, max 3 if not batched
                            max_batched_sessions = min(sessions_with_batching, 6)
                            max_unbatched_sessions = min(base_sessions, 3)
                        elif practical_hours >= 4:
                            # 4+ practical hours: Allow up to 4 slots if batched, max 2 if not batched
                            max_batched_sessions = min(sessions_with_batching, 4)
                            max_unbatched_sessions = min(base_sessions, 2)
                        else:
                            # 2 practical hours: Maximum 2 slots if batched, 1 if not batched
                            max_batched_sessions = min(sessions_with_batching, 2)
                            max_unbatched_sessions = min(base_sessions, 1)
                        
                        # Boolean variable to choose strategy: True = use 35-cap labs, False = use 70+ cap labs
                        use_35_cap_strategy = model.NewBoolVar(f'course_{course_instance_id}_use_35_cap_strategy')
                        
                        # Constraint 1: If using 35-cap strategy, ALL sessions must be in 35-cap labs
                        if assignments_in_35_cap and assignments_in_70_plus_cap:
                            model.Add(total_35_assignments == sum(total_assignments)).OnlyEnforceIf(use_35_cap_strategy)
                            model.Add(total_70_plus_assignments == 0).OnlyEnforceIf(use_35_cap_strategy)
                            
                            # Constraint 2: If using 70+ cap strategy, ALL sessions must be in 70+ cap labs  
                            model.Add(total_70_plus_assignments == sum(total_assignments)).OnlyEnforceIf(use_35_cap_strategy.Not())
                            model.Add(total_35_assignments == 0).OnlyEnforceIf(use_35_cap_strategy.Not())
                            
                            # Constraint 3: Session count depends on chosen strategy WITH SLOT RESTRICTIONS
                            model.Add(sum(total_assignments) == max_batched_sessions).OnlyEnforceIf(use_35_cap_strategy)
                            model.Add(sum(total_assignments) == max_unbatched_sessions).OnlyEnforceIf(use_35_cap_strategy.Not())
                            
                            constraints_applied += 6
                        else:
                            # Fallback to simple assignment if capacity separation not possible
                            required_sessions = min(max_batched_sessions, len(total_assignments))
                            model.Add(sum(total_assignments) == required_sessions)
                            constraints_applied += 1
                            
                        self.logger.info(f"Course {course_req['course_code']} ({practical_hours}h): EITHER {max_batched_sessions} sessions (35-cap batched) OR {max_unbatched_sessions} sessions (70+ cap unbatched)")
                    else:
                        # Small courses: always base sessions, but enforce max 4 slots
                        max_sessions = min(base_sessions, 4)
                        model.Add(sum(total_assignments) == max_sessions)
                        constraints_applied += 1
                        self.logger.info(f"Course {course_req['course_code']}: exactly {max_sessions} sessions (max 4 slots enforced)")
        
        self.logger.info(f"Applied {constraints_applied} course lab requirements constraints")
        return constraints_applied

    def apply_lab_room_single_assignment_constraint(self, model, lab_variables):
        """Prevent lab room double-booking."""
        self.logger.info("Applying lab room single assignment constraint...")
        constraints_applied = 0
        
        for day_idx in range(self.num_days):
            for session_name in self.lab_sessions.keys():
                for room_id in self.lab_room_ids:
                    room_usage_vars = []
                    
                    for teacher_id in lab_variables:
                        for course_instance_id in lab_variables[teacher_id]:
                            room_usage_vars.append(
                                lab_variables[teacher_id][course_instance_id][day_idx][session_name][room_id]
                            )
                    
                    if room_usage_vars:
                        model.Add(sum(room_usage_vars) <= 1)
                        constraints_applied += 1
        
        self.logger.info(f"Applied {constraints_applied} lab room single assignment constraints")
        return constraints_applied

    def apply_teacher_clash_constraint(self, model, lab_variables):
        """Ensure a teacher is not assigned to more than one lab at the same time."""
        self.logger.info("Applying teacher clash constraint (global)...")
        constraints_applied = 0
        
        for teacher_id in lab_variables:
            courses = list(lab_variables[teacher_id].keys())
            
            for day_idx in range(self.num_days):
                for session_name in self.lab_sessions.keys():
                    teacher_session_assignments = []
                    for course_instance_id in courses:
                        for room_id in self.lab_room_ids:
                            teacher_session_assignments.append(
                                lab_variables[teacher_id][course_instance_id][day_idx][session_name][room_id]
                            )
                    
                    if teacher_session_assignments:
                        model.Add(sum(teacher_session_assignments) <= 1)
                        constraints_applied += 1
                        
        self.logger.info(f"Applied {constraints_applied} global teacher clash constraints for {len(lab_variables)} teachers")
        return constraints_applied


    
    def apply_group_based_scheduling_constraint(self, model, lab_variables):
        """Apply group-based scheduling constraints to enforce scheduling by groups."""
        self.logger.info("Applying group-based scheduling constraints...")
        constraints_applied = 0
        
        # Group course instances by department, semester, and group
        semester_groups = defaultdict(lambda: defaultdict(list))
        
        for teacher_id in lab_variables:
            for course_instance_id in lab_variables[teacher_id]:
                # Get group info for this course instance
                if hasattr(self, 'instance_group_mapping') and course_instance_id in self.instance_group_mapping:
                    group_mapping = self.instance_group_mapping[course_instance_id]
                    dept = group_mapping['department']
                    semester = group_mapping['semester']
                    group_index = group_mapping['group_index']
                    
                    if group_index > 0:  # Valid group
                        semester_groups[(dept, semester)][group_index].append(course_instance_id)
        
        # CONSTRAINT 1: Same-semester group non-overlap
        for (dept, semester), groups in semester_groups.items():
            self.logger.info(f"Applying group constraints for {dept} Semester {semester}: {len(groups)} groups")
            
            # For each time slot, ensure at most one group from this semester is active
            for day_idx in range(self.num_days):
                for session_name in self.lab_sessions.keys():
                    # For each time slot, collect usage variables for each group
                    group_usages = {}
                    
                    for group_idx, course_instances in groups.items():
                        group_usage_vars = []
                        
                        for course_instance_id in course_instances:
                            # Find the teacher for this course instance
                            teacher_id = None
                            for tid in lab_variables:
                                if course_instance_id in lab_variables[tid]:
                                    teacher_id = tid
                                    break
                            
                            if teacher_id:
                                for room_id in self.lab_room_ids:
                                    group_usage_vars.append(lab_variables[teacher_id][course_instance_id][day_idx][session_name][room_id])
                        
                        if group_usage_vars:
                            # Create a variable indicating if this group uses this time slot
                            group_usage = model.NewBoolVar(f'group_usage_{dept}_S{semester}_G{group_idx}_day{day_idx}_session{session_name}')
                            
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
        for teacher_id in lab_variables:
            for course_instance_id in lab_variables[teacher_id]:
                for day_idx in range(self.num_days):
                    for session_name in self.lab_sessions.keys():
                        session_assignments = []
                        for room_id in self.lab_room_ids:
                            session_assignments.append(lab_variables[teacher_id][course_instance_id][day_idx][session_name][room_id])
                        
                        if len(session_assignments) > 1:
                            model.Add(sum(session_assignments) <= 1)
                            constraints_applied += 1
        
        self.logger.info(f"Applied {constraints_applied} group-based scheduling constraints")
        return constraints_applied
    
    # REMOVED: apply_theory_lab_group_conflict_constraint method - was redundant with cross-system constraints
    
    def apply_semester_lab_slot_limit_constraint(self, model, lab_variables):
        """CONSTRAINT: Limit the total number of lab slots used by any single semester/department."""
        self.logger.info("Applying semester lab slot limit constraint...")
        constraints_applied = 0
        
        # Group course instances by department and semester
        semester_courses = defaultdict(list)
        for teacher_id in lab_variables:
            for course_instance_id in lab_variables[teacher_id]:
                if hasattr(self, 'instance_group_mapping') and course_instance_id in self.instance_group_mapping:
                    group_mapping = self.instance_group_mapping[course_instance_id]
                    dept = group_mapping['department']
                    semester = group_mapping['semester']
                    semester_courses[(dept, semester)].append((teacher_id, course_instance_id))
        
        # Apply constraint for each semester/department
        for (dept, semester), instance_info in semester_courses.items():
            if len(instance_info) == 0:
                continue
            
            # Create boolean variables for each time slot to check if it's used by this semester/dept
            slot_used_vars = {}
            for day_idx in range(self.num_days):
                for session_name in self.lab_sessions.keys():
                    slot_used_vars[(day_idx, session_name)] = model.NewBoolVar(
                        f'slot_used_{dept}_S{semester}_d{day_idx}_s{session_name}'
                    )
            
            # Link these variables to the main assignment variables
            for day_idx in range(self.num_days):
                for session_name in self.lab_sessions.keys():
                    # Slot is used if ANY lab from this semester/dept is scheduled in it
                    slot_assignments = []
                    for teacher_id, course_instance_id in instance_info:
                        for room_id in self.lab_room_ids:
                            slot_assignments.append(lab_variables[teacher_id][course_instance_id][day_idx][session_name][room_id])
                    
                    if slot_assignments:
                        # Reification: slot_used_vars is true iff sum(slot_assignments) > 0
                        model.Add(sum(slot_assignments) >= 1).OnlyEnforceIf(slot_used_vars[(day_idx, session_name)])
                        model.Add(sum(slot_assignments) == 0).OnlyEnforceIf(slot_used_vars[(day_idx, session_name)].Not())
                        constraints_applied += 2
            
            # The sum of used slots for this semester/dept must be <= 18
            total_slots_used = sum(slot_used_vars.values())
            model.Add(total_slots_used <= 18)
            constraints_applied += 1
        
            self.logger.info(f"Constraint for {dept} Semester {semester}: lab slots <= 18 ({len(instance_info)} lab courses)")
        
        self.logger.info(f"Applied {constraints_applied} semester lab slot limit constraints")
        return constraints_applied
    
    # REMOVED: apply_lab_efficiency_constraints and _apply_peak_time_balancing methods - were over-constraining
    
    def _apply_theory_constraints(self, model, group_timeslot_vars):
        """Apply theory-specific constraints using group-based approach."""
        self.logger.info("Applying group-based theory constraints...")
        constraints_applied = 0
        
        # CONSTRAINT 1: Each group must have exactly the required number of time slots
        for group_name, required_slots in self.group_requirements.items():
            if group_name not in group_timeslot_vars:
                continue
                
            timeslot_vars = []
        for day_idx in range(self.num_days):
            for slot_idx in range(self.num_theory_slots):
                    timeslot_vars.append(group_timeslot_vars[group_name][day_idx][slot_idx])
            
            model.Add(sum(timeslot_vars) == required_slots)
            constraints_applied += 1
            self.logger.debug(f"Group {group_name}: exactly {required_slots} time slots required")
        
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
                
            self.logger.debug(f"Applying non-overlap constraints for {semester_key}: {len(groups)} groups")
            
        for day_idx in range(self.num_days):
            for slot_idx in range(self.num_theory_slots):
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
            for slot_idx in range(self.num_theory_slots):
                # Count total groups using this time slot
                total_usage_vars = []
                for group_name in group_timeslot_vars.keys():
                    total_usage_vars.append(group_timeslot_vars[group_name][day_idx][slot_idx])
                
                if total_usage_vars:
                    # Cannot exceed total theory room capacity
                    model.Add(sum(total_usage_vars) <= len(self.theory_room_ids))
                    constraints_applied += 1
        
        # REMOVED: _apply_global_teacher_clash_constraint - redundant with cross-system teacher constraints
        # REMOVED: _apply_lab_theory_conflict_constraint - redundant with cross-system group constraints
        
        self.logger.info(f"Applied {constraints_applied} theory-specific constraints (optimized)")
        return constraints_applied
    
    def _apply_cross_system_constraints(self, model, lab_variables, group_timeslot_vars):
        """Apply constraints that prevent conflicts between lab and theory systems."""
        self.logger.info("Applying cross-system conflict prevention constraints...")
        constraints_applied = 0
        
        # CONSTRAINT 1: Department/Semester Group Conflict Prevention
        # Lab groups and theory groups from the same dept/semester CANNOT overlap in time
        # RE-ENABLED WITH OPTIMIZED VERSION
        constraints_applied += self._apply_dept_semester_group_conflict_constraint(model, lab_variables, group_timeslot_vars)
        
        # CONSTRAINT 2: Teacher clash prevention (same teacher cannot be in lab and theory at overlapping times)
        # TEMPORARILY DISABLED FOR PERFORMANCE TESTING  
        # constraints_applied += self._apply_teacher_cross_system_conflict_constraint(model, lab_variables, group_timeslot_vars)
        
        self.logger.info(f"Applied {constraints_applied} cross-system constraints")
        return constraints_applied
    
    def _apply_dept_semester_group_conflict_constraint(self, model, lab_variables, group_timeslot_vars):
        """Prevent lab groups and theory groups from SAME dept/semester/group from overlapping in time.
        
        This optimized constraint ONLY applies to exact same groups (e.g., CS_S3_G1 lab vs CS_S3_G1 theory).
        Different departments, semesters, or group numbers CAN overlap.
        """
        self.logger.info("Applying optimized same-group conflict prevention...")
        constraints_applied = 0
        
        # Build mapping: dept_semester_group -> (lab_instances, theory_group_name)
        group_mappings = {}
        
        # Collect lab instances by exact group (dept_semester_group)
        for teacher_id in lab_variables:
            for course_instance_id in lab_variables[teacher_id]:
                if hasattr(self, 'instance_group_mapping') and course_instance_id in self.instance_group_mapping:
                    group_mapping = self.instance_group_mapping[course_instance_id]
                    dept = group_mapping['department']
                    semester = group_mapping['semester']
                    group_index = group_mapping['group_index']
                    
                    # Create exact group key: "dept_semester_group"
                    group_key = f"{dept}_S{semester}_G{group_index}"
                    
                    if group_key not in group_mappings:
                        group_mappings[group_key] = {'lab_instances': [], 'theory_group': None}
                    
                    group_mappings[group_key]['lab_instances'].append((teacher_id, course_instance_id))
        
        # Collect theory groups by exact group name
        for theory_group_name in group_timeslot_vars.keys():
            # theory_group_name format: "Computer Science & Engineering_S3_G1"
            # We need to extract dept_semester_group part
            parts = theory_group_name.split('_')
            if len(parts) >= 3:
                # Reconstruct the group key to match lab format
                dept_parts = parts[:-2]  # Everything except last 2 parts (semester and group)
                semester_part = parts[-2]  # e.g., "S3"
                group_part = parts[-1]    # e.g., "G1"
                
                dept = '_'.join(dept_parts)
                group_key = f"{dept}_{semester_part}_{group_part}"
                
                if group_key not in group_mappings:
                    group_mappings[group_key] = {'lab_instances': [], 'theory_group': None}
                
                group_mappings[group_key]['theory_group'] = theory_group_name
        
        # Apply constraints only for groups that have BOTH lab and theory instances
        for group_key, mapping in group_mappings.items():
            lab_instances = mapping['lab_instances']
            theory_group_name = mapping['theory_group']
            
            if not lab_instances or not theory_group_name:
                continue  # No conflict if only one type exists
            
            if theory_group_name not in group_timeslot_vars:
                continue  # Theory group not in variables
            
            self.logger.debug(f"Applying same-group conflict constraints for {group_key} ({len(lab_instances)} lab instances)")
            
            # For each time conflict: theory slot vs overlapping lab sessions
            for day_idx in range(self.num_days):
                for theory_slot_idx in range(self.num_theory_slots):
                    theory_var = group_timeslot_vars[theory_group_name][day_idx][theory_slot_idx]
                    
                    # Find lab sessions that overlap with this theory time slot
                    overlapping_lab_sessions = set()
                    if theory_slot_idx in self.theory_to_lab_mapping:
                        for lab_slot_idx in self.theory_to_lab_mapping[theory_slot_idx]:
                            # Find which lab session contains this lab slot
                            for session_name, session_time_slots in self.lab_sessions.items():
                                if lab_slot_idx < len(self.lab_time_slots):
                                    lab_time_slot = self.lab_time_slots[lab_slot_idx]
                                    if lab_time_slot in session_time_slots:
                                        overlapping_lab_sessions.add(session_name)
                    
                    # For each overlapping lab session, collect lab variables for this exact group
                    for lab_session_name in overlapping_lab_sessions:
                        lab_vars_for_group = []
                        
                        for teacher_id, course_instance_id in lab_instances:
                            if (teacher_id in lab_variables and 
                                course_instance_id in lab_variables[teacher_id] and
                                day_idx < len(lab_variables[teacher_id][course_instance_id]) and
                                lab_session_name in lab_variables[teacher_id][course_instance_id][day_idx]):
                                
                                # Collect all room assignments for this lab session
                                for room_id in self.lab_room_ids:
                                    if room_id in lab_variables[teacher_id][course_instance_id][day_idx][lab_session_name]:
                                        lab_vars_for_group.append(
                                            lab_variables[teacher_id][course_instance_id][day_idx][lab_session_name][room_id]
                                        )
                        
                        # Apply constraint: this specific group cannot have both theory and lab at overlapping times
                        if lab_vars_for_group:
                            # Either theory is active OR lab is active (for this exact group), but not both
                            model.Add(theory_var + sum(lab_vars_for_group) <= 1)
                            constraints_applied += 1
        
        self.logger.info(f"Applied {constraints_applied} optimized same-group conflict constraints")
        return constraints_applied
    
    def _apply_teacher_cross_system_conflict_constraint(self, model, lab_variables, group_timeslot_vars):
        """Prevent same teacher from being in lab and theory at overlapping times."""
        self.logger.info("Applying teacher-level cross-system conflict prevention...")
        constraints_applied = 0
        
        # Build teacher-group mapping for theory
        teacher_theory_groups = {}
        for (dept, semester), groups in self.course_groups.items():
            for group_idx, group in enumerate(groups):
                if not group:
                    continue
                    
                group_name = f"{dept}_S{semester}_G{group_idx + 1}"
                
                for instance in group:
                        teacher_id = instance['teacher_id']
                        if teacher_id not in teacher_theory_groups:
                            teacher_theory_groups[teacher_id] = []
                        if group_name not in teacher_theory_groups[teacher_id]:
                            teacher_theory_groups[teacher_id].append(group_name)
        
        # Apply teacher-level cross-system constraints
        for teacher_id in self.teachers:
            teacher_has_lab = teacher_id in lab_variables
            teacher_has_theory = teacher_id in teacher_theory_groups
            
            if teacher_has_lab and teacher_has_theory:
                for day_idx in range(self.num_days):
                    # Check each lab session against overlapping theory slots
                    for session_name, session_time_slots in self.lab_sessions.items():
                        # Convert session time slots to indices
                        lab_slot_indices = []
                        for time_slot in session_time_slots:
                            if time_slot in self.lab_time_slots:
                                lab_slot_indices.append(self.lab_time_slots.index(time_slot))
                        
                        # Find theory slots that overlap with this lab session
                        overlapping_theory_slots = set()
                        for lab_slot_idx in lab_slot_indices:
                            if lab_slot_idx in self.lab_to_theory_mapping:
                                overlapping_theory_slots.update(self.lab_to_theory_mapping[lab_slot_idx])
                        
                        # Constraint: teacher cannot be in lab session and overlapping theory group slots simultaneously
                        for theory_slot_idx in overlapping_theory_slots:
                            lab_vars = []
                            theory_vars = []
                            
                            # Collect all lab assignments for this teacher in this session
                            if teacher_id in lab_variables:
                                for course_instance_id in lab_variables[teacher_id]:
                                    for room_id in self.lab_room_ids:
                                        lab_vars.append(
                                        lab_variables[teacher_id][course_instance_id][day_idx][session_name][room_id]
                                        )
                            
                            # Collect all theory group assignments for this teacher in overlapping slot
                            for group_name in teacher_theory_groups[teacher_id]:
                                if group_name in group_timeslot_vars:
                                    theory_vars.append(
                                        group_timeslot_vars[group_name][day_idx][theory_slot_idx]
                                    )
                            
                            # Add constraint: at most one of lab or theory can be active
                            if lab_vars and theory_vars:
                                model.Add(sum(lab_vars) + sum(theory_vars) <= 1)
                                constraints_applied += 1
        
        self.logger.info(f"Applied {constraints_applied} teacher-level cross-system constraints")
        return constraints_applied
    
    def _add_combined_objectives(self, model, lab_variables, group_timeslot_vars):
        """Add optimization objectives for the combined model."""
        self.logger.info("Setting up combined optimization objectives...")
        
        objective_terms = []
        
        # Lab objective: maximize successful lab assignments
        for teacher_id in lab_variables:
            for course_instance_id in lab_variables[teacher_id]:
                for day_idx in range(self.num_days):
                    for session_name in self.lab_sessions.keys():
                        for room_id in self.lab_room_ids:
                            objective_terms.append(lab_variables[teacher_id][course_instance_id][day_idx][session_name][room_id])
        
        # Theory objective: maximize group timeslot allocations with preference for earlier slots
        for group_name, day_slots in group_timeslot_vars.items():
                for day_idx in range(self.num_days):
                    # Give higher weight to earlier slots to encourage compact scheduling
                    for slot_idx in range(self.num_theory_slots):
                        # Weight decreases as slot gets later (earlier slots preferred)
                        weight = self.num_theory_slots - slot_idx
                        objective_terms.append(day_slots[day_idx][slot_idx] * weight)
        
        # Add capacity preferences for lab room assignments
        if hasattr(self, 'capacity_preferences') and self.capacity_preferences:
            objective_terms.extend(self.capacity_preferences)
            self.logger.info(f"Added {len(self.capacity_preferences)} capacity preference terms to objective")
            self.logger.info("  • Encourages 70+ capacity labs for courses with 4-6 practical hours")
            self.logger.info("  • Allows 35-capacity labs with batching as fallback")
        
        if objective_terms:
            model.Maximize(sum(objective_terms))
            self.logger.info(f"Combined objective set with {len(objective_terms)} terms")
            self.logger.info("Objective strategy:")
            self.logger.info("  1. Lab assignments (base priority)")
            self.logger.info("  2. Group timeslots (prefer earlier slots)")
            self.logger.info("  3. Room capacity optimization (prefer appropriate room sizes)")
    
    def _solve_combined_model(self, model, lab_variables, group_timeslot_vars):
        """Solve the combined scheduling model using two-phase approach."""
        # Create the solver
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 300  # 5 minutes for testing
        solver.parameters.num_search_workers = 8  # Reduce workers to avoid contention
        solver.parameters.log_search_progress = True
        solver.parameters.stop_after_first_solution = True
        
        self.logger.info("Solving combined scheduling model (Phase 1: Group allocation)...")
        status = solver.Solve(model)
        
        # Log solver results
        self.logger.info("="*60)
        self.logger.info("COMBINED SOLVER RESULTS (PHASE 1)")
        self.logger.info("="*60)
        self.logger.info(f"Status: {solver.StatusName(status)}")
        self.logger.info(f"Wall time: {solver.WallTime():.2f} seconds")
        
        if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
            self.logger.info(f"{'[OPTIMAL]' if status == cp_model.OPTIMAL else '[FEASIBLE]'} group allocation found!")
            
            # PHASE 1: Extract lab schedule and group timeslots
            lab_schedule = self._extract_lab_schedule(solver, lab_variables)
            group_timeslots = self._extract_group_timeslots(solver, group_timeslot_vars)
            
            # PHASE 2: Distribute theory sessions within allocated group timeslots
            theory_schedule = self._distribute_theory_sessions_in_groups(group_timeslots)
            
            # Save schedules
            self._save_combined_schedules(lab_schedule, theory_schedule)
            
            return True
        else:
            self.logger.error(f"[ERROR] No combined solution found. Status: {solver.StatusName(status)}")
            return False
    
    def _extract_group_timeslots(self, solver, group_timeslot_vars):
        """Extract allocated time slots for each group from solver solution."""
        self.logger.info("Extracting group time slot allocations...")
        
        group_timeslots = {}
        total_slots_allocated = 0
        
        for group_name, day_slots in group_timeslot_vars.items():
            group_timeslots[group_name] = []
            
            for day_idx in range(self.num_days):
                for slot_idx in range(self.num_theory_slots):
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
    
    def _distribute_theory_sessions_in_groups(self, group_timeslots):
        """Distribute individual theory sessions within allocated group time slots (Phase 2)."""
        self.logger.info("Phase 2: Distributing theory sessions within allocated group time slots...")
        
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
                
            instances = [inst for inst in group_info['instances'] if inst.get('has_theory', False)]
            self.logger.info(f"Distributing {len(instances)} theory course instances across {len(allocated_slots)} time slots for {group_name}")
            
            # Collect all theory sessions needed for this group
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
            
            # Distribute sessions across allocated time slots ensuring no teacher conflicts
            slot_assignments = {}  # slot_idx -> assigned_sessions
            slot_teachers = {}  # slot_idx -> set of teacher_ids
            
            for slot_idx in range(len(allocated_slots)):
                slot_assignments[slot_idx] = []
                slot_teachers[slot_idx] = set()
            
            # Group sessions by teacher to avoid conflicts
            teacher_sessions = {}
            for session in sessions_needed:
                teacher_id = session['teacher_id']
                if teacher_id not in teacher_sessions:
                    teacher_sessions[teacher_id] = []
                teacher_sessions[teacher_id].append(session)
            
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
                            break
            
                    if not assigned:
                        # If all slots have this teacher, assign to the slot with fewest sessions
                        min_slot = min(slot_assignments.keys(), key=lambda x: len(slot_assignments[x]))
                        slot_assignments[min_slot].append(session)
                        slot_teachers[min_slot].add(teacher_id)
                        self.logger.warning(f"Teacher {teacher_id} has multiple sessions in same time slot for {group_name}")
            
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
                        'slot_index': time_slot_idx,
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
                        'lecture_hours': int(instance.get('lecture_hours', 0)),
                        'tutorial_hours': int(instance.get('tutorial_hours', 0)),
                        'schedule_type': 'theory',
                        # Group information
                        'group_name': group_name,
                        'group_index': int(group_name.split('_G')[1]) if '_G' in group_name else 1,
                        'department': group_info['dept'],
                        'semester': group_info['semester']
                    })
        
        self.logger.info(f"Phase 2 complete: Distributed {len(theory_schedule)} theory sessions across group time slots")
        return theory_schedule
    
    def _extract_lab_schedule(self, solver, lab_variables):
        """Extract lab schedule from solver solution with proper batching logic."""
        self.logger.info("Extracting lab schedule from solution...")
        lab_schedule = []
        
        for teacher_id in lab_variables:
            for course_instance_id in lab_variables[teacher_id]:
                # Find the course details
                course_details = None
                for course_req in self.lab_requirements.get(teacher_id, []):
                    if course_req['course_instance_id'] == course_instance_id:
                        course_details = course_req
                        break
                
                if not course_details:
                    continue
                
                for day_idx in range(self.num_days):
                    for session_name in self.lab_sessions.keys():
                        for room_id in self.lab_room_ids:
                            if solver.Value(lab_variables[teacher_id][course_instance_id][day_idx][session_name][room_id]) == 1:
                                # Get room details
                                room_row = self.rooms_df[self.rooms_df['id'] == room_id].iloc[0]
                                room_capacity = int(room_row['room_max_cap'])
                                
                                # Get teacher details
                                teacher_row = self.courses_df[self.courses_df['teacher_id'] == teacher_id].iloc[0]
                                course_row = self.courses_df[self.courses_df['id'] == int(course_instance_id)].iloc[0]
                                
                                # Rule 1: Simple batching rule - batch if using 35-capacity lab and have more students
                                student_count = int(course_row['student_count'])
                                
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
                                
                                if batching_required and num_batches > 1:
                                    # For batched courses, distribute sessions across batches
                                    # Count total assignments for this course so far
                                    existing_assignments = [item for item in lab_schedule 
                                                          if item['course_instance_id'] == course_instance_id]
                                    
                                    # Calculate how many sessions each batch should get
                                    base_sessions = course_details['lab_sessions_needed']
                                    
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
                                    group_name = ""
                                    group_index = 0
                                    department = ""
                                    semester = ""
                                    if hasattr(self, 'instance_group_mapping') and course_instance_id in self.instance_group_mapping:
                                        group_mapping = self.instance_group_mapping[course_instance_id]
                                        group_name = group_mapping['group_name']
                                        group_index = group_mapping['group_index']
                                        department = group_mapping['department']
                                        semester = group_mapping['semester']
                                    
                                    # Add this session to the current batch
                                    lab_schedule.append({
                                    'day': self.days[day_idx],
                                    'session_name': session_name,
                                    'time_range': f"{self.lab_sessions[session_name][0]} to {self.lab_sessions[session_name][-1]}",
                                    'course_instance_id': course_instance_id,
                                        'course_code': course_details['course_code'],
                                        'course_code_display': course_code_display,
                                    'course_name': course_row['course_name'],
                                        'practical_hours': int(course_row.get('practical_hours', 0)),
                                    'teacher_id': teacher_id,
                                    'teacher_name': f"{teacher_row.get('first_name', '')} {teacher_row.get('last_name', '')}".strip(),
                                    'staff_code': teacher_row.get('staff_code', ''),
                                    'room_id': int(room_id),
                                    'room_number': room_row['room_number'],
                                    'block': room_row.get('block', ''),
                                        'capacity': int(room_capacity),
                                        'student_count': int(students_per_batch),
                                        'total_students': int(student_count),
                                        'is_batched': True,
                                        'batch_info': batch_info,
                                        'num_batches': num_batches,
                                        'schedule_type': 'lab',
                                        # Group information
                                        'group_name': group_name,
                                        'group_index': group_index,
                                        'department': department,
                                        'semester': semester
                                    })
                                    
                                    # Log assignment
                                    self.logger.info(f"Lab assignment: Course {course_details['course_code']} Batch {current_batch} → "
                                                   f"{session_name} on {self.days[day_idx]} in "
                                                   f"Lab {room_row['room_number']} ({students_per_batch} students)")
                                else:
                                    # Single assignment, no batching
                                    course_code_display = course_details['course_code']
                                    
                                    # Get group information for this course instance
                                    group_name = ""
                                    group_index = 0
                                    department = ""
                                    semester = ""
                                    if hasattr(self, 'instance_group_mapping') and course_instance_id in self.instance_group_mapping:
                                        group_mapping = self.instance_group_mapping[course_instance_id]
                                        group_name = group_mapping['group_name']
                                        group_index = group_mapping['group_index']
                                        department = group_mapping['department']
                                        semester = group_mapping['semester']
                                    
                                    lab_schedule.append({
                                        'day': self.days[day_idx],
                                        'session_name': session_name,
                                        'time_range': f"{self.lab_sessions[session_name][0]} to {self.lab_sessions[session_name][-1]}",
                                        'course_instance_id': course_instance_id,
                                        'course_code': course_details['course_code'],
                                        'course_code_display': course_code_display,
                                        'course_name': course_row['course_name'],
                                        'practical_hours': int(course_row.get('practical_hours', 0)),
                                        'teacher_id': teacher_id,
                                        'teacher_name': f"{teacher_row.get('first_name', '')} {teacher_row.get('last_name', '')}".strip(),
                                        'staff_code': teacher_row.get('staff_code', ''),
                                        'room_id': int(room_id),
                                        'room_number': room_row['room_number'],
                                        'block': room_row.get('block', ''),
                                        'capacity': int(room_capacity),
                                        'student_count': int(student_count),
                                        'total_students': int(student_count),
                                        'is_batched': False,
                                        'batch_info': "",
                                        'num_batches': 1,
                                        'schedule_type': 'lab',
                                        # Group information
                                        'group_name': group_name,
                                        'group_index': group_index,
                                        'department': department,
                                        'semester': semester
                                    })
                                    
                                    # Log assignment
                                    self.logger.info(f"Lab assignment: Course {course_code_display} → "
                                                   f"{session_name} on {self.days[day_idx]} in "
                                                   f"Lab {room_row['room_number']} (capacity: {room_capacity})")
        
        self.logger.info(f"Extracted {len(lab_schedule)} lab sessions with proper batching")
        return lab_schedule
    
    def _save_combined_schedules(self, lab_schedule, theory_schedule):
        """Save both lab and theory schedules."""
        # Save lab schedule
        lab_df = pd.DataFrame(lab_schedule)
        lab_csv_path = os.path.join(self.output_dir, 'combined_lab_schedule.csv')
        lab_json_path = os.path.join(self.output_dir, 'combined_lab_schedule.json')
        
        lab_df.to_csv(lab_csv_path, index=False)
        with open(lab_json_path, 'w') as f:
            json.dump(lab_schedule, f, indent=2)
        
        # Save theory schedule
        theory_df = pd.DataFrame(theory_schedule)
        theory_csv_path = os.path.join(self.output_dir, 'combined_theory_schedule.csv')
        theory_json_path = os.path.join(self.output_dir, 'combined_theory_schedule.json')
        
        theory_df.to_csv(theory_csv_path, index=False)
        with open(theory_json_path, 'w') as f:
            json.dump(theory_schedule, f, indent=2)
        
        # Save combined schedule
        combined_schedule = lab_schedule + theory_schedule
        combined_df = pd.DataFrame(combined_schedule)
        combined_csv_path = os.path.join(self.output_dir, 'combined_full_schedule.csv')
        combined_json_path = os.path.join(self.output_dir, 'combined_full_schedule.json')
        
        combined_df.to_csv(combined_csv_path, index=False)
        with open(combined_json_path, 'w') as f:
            json.dump(combined_schedule, f, indent=2)
        
        self.logger.info(f"Lab schedule saved: {lab_csv_path}")
        self.logger.info(f"Theory schedule saved: {theory_csv_path}")
        self.logger.info(f"Combined schedule saved: {combined_csv_path}")
        
        # Generate summary
        self._generate_combined_summary(lab_schedule, theory_schedule, combined_schedule)
    
    def _generate_combined_summary(self, lab_schedule, theory_schedule, combined_schedule):
        """Generate a summary of the combined schedule."""
        summary_path = os.path.join(self.output_dir, 'combined_schedule_summary.txt')
        
        with open(summary_path, 'w') as f:
            f.write("COMBINED SCHEDULE SUMMARY\n")
            f.write("========================\n\n")
            
            f.write(f"Total scheduled sessions: {len(combined_schedule)}\n")
            f.write(f"  Lab sessions: {len(lab_schedule)}\n")
            f.write(f"  Theory sessions: {len(theory_schedule)}\n\n")
            
            # Batch analysis for lab sessions
            if lab_schedule:
                batched_sessions = [item for item in lab_schedule if item.get('is_batched', False)]
                non_batched_sessions = [item for item in lab_schedule if not item.get('is_batched', False)]
                
                f.write("Lab Session Batching Analysis:\n")
                f.write(f"  Batched sessions: {len(batched_sessions)}\n")
                f.write(f"  Non-batched sessions: {len(non_batched_sessions)}\n")
                
                if batched_sessions:
                    # Count courses that required batching
                    batched_courses = set()
                    batch_details = {}
                    
                    for session in batched_sessions:
                        course_code = session['course_code']
                        batched_courses.add(course_code)
                        
                        if course_code not in batch_details:
                            batch_details[course_code] = {
                                'num_batches': session.get('num_batches', 1),
                                'total_students': session.get('total_students', 0),
                                'students_per_batch': session.get('student_count', 0),
                                'capacity': session.get('capacity', 0)
                            }
                    
                    f.write(f"  Courses requiring batching: {len(batched_courses)}\n")
                    f.write("  Batch details:\n")
                    
                    for course_code, details in batch_details.items():
                        f.write(f"    {course_code}: {details['num_batches']} batches, "
                               f"{details['total_students']} total students, "
                               f"~{details['students_per_batch']} per batch "
                               f"(room capacity: {details['capacity']})\n")
                
                f.write("\n")
            
            # Sessions by day
            day_counts = {'lab': {}, 'theory': {}}
            for item in lab_schedule:
                day = item['day']
                day_counts['lab'][day] = day_counts['lab'].get(day, 0) + 1
            
            for item in theory_schedule:
                day = item['day']
                day_counts['theory'][day] = day_counts['theory'].get(day, 0) + 1
            
            f.write("Sessions by day:\n")
            for day in self.days:
                lab_count = day_counts['lab'].get(day, 0)
                theory_count = day_counts['theory'].get(day, 0)
                f.write(f"  {day.capitalize()}: {lab_count + theory_count} total ({lab_count} lab, {theory_count} theory)\n")
            
            # Teachers with assignments
            lab_teachers = set(item['teacher_id'] for item in lab_schedule)
            theory_teachers = set(item['teacher_id'] for item in theory_schedule)
            all_teachers = lab_teachers | theory_teachers
            
            f.write(f"\nTeachers with assignments: {len(all_teachers)}\n")
            f.write(f"  Lab only: {len(lab_teachers - theory_teachers)}\n")
            f.write(f"  Theory only: {len(theory_teachers - lab_teachers)}\n")
            f.write(f"  Both lab and theory: {len(lab_teachers & theory_teachers)}\n")
            
            # Room utilization
            lab_rooms = set(item['room_id'] for item in lab_schedule)
            theory_rooms = set(item['room_id'] for item in theory_schedule)
            
            f.write(f"\nRoom utilization:\n")
            f.write(f"  Lab rooms used: {len(lab_rooms)}\n")
            f.write(f"  Theory rooms used: {len(theory_rooms)}\n")
            
            # Capacity utilization analysis
            if lab_schedule:
                f.write(f"\nLab capacity utilization:\n")
                capacity_35_sessions = [item for item in lab_schedule if item.get('capacity', 0) <= 35]
                capacity_70_sessions = [item for item in lab_schedule if 35 < item.get('capacity', 0) <= 70]
                capacity_140_sessions = [item for item in lab_schedule if item.get('capacity', 0) > 70]
                
                f.write(f"  35-capacity labs: {len(capacity_35_sessions)} sessions\n")
                f.write(f"  70-capacity labs: {len(capacity_70_sessions)} sessions\n")
                f.write(f"  140+ capacity labs: {len(capacity_140_sessions)} sessions\n")
        
        self.logger.info(f"Combined summary saved to {summary_path}") 
    
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
    
    def _determine_lab_allocation_strategy(self, practical_hours, students_per_instance):
        """Determine the optimal lab allocation strategy based on practical hours and student count."""
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
            # Rule: practical_hours <= 2 should always use 35-capacity labs (with batching if needed)
            strategy['force_35_capacity'] = True
            strategy['preferred_lab_capacities'] = [35]
        elif practical_hours == 6:
            # Rule: practical_hours == 6 PREFERS 70+ capacity labs but allows batching fallback
            strategy['prefer_70_plus_with_batching_fallback'] = True
            strategy['preferred_lab_capacities'] = [70, 140, 35]  # 70+ preferred, 35 as fallback
        elif practical_hours >= 5:
            # Rule: practical_hours >= 5 (but not 6) PREFERS 70+ capacity labs but allows batching fallback
            strategy['prefer_70_plus_with_batching_fallback'] = True
            strategy['preferred_lab_capacities'] = [70, 140, 35]  # 70+ preferred, 35 as fallback
        elif practical_hours == 4:
            # Rule: practical_hours == 4 PREFERS 70+ capacity labs but allows batching fallback
            strategy['prefer_70_plus_with_batching_fallback'] = True
            strategy['preferred_lab_capacities'] = [70, 140, 35]  # 70+ preferred, 35 as fallback
        else:
            # Rule: practical_hours 3 or less can use either strategy (solver decides)
            strategy['preferred_lab_capacities'] = [35, 70, 140]
        
        return strategy
    
    def apply_capacity_constraint(self, model, lab_variables):
        """Apply capacity-based assignment constraints for lab scheduling."""
        self.logger.info("Applying capacity-based assignment constraint...")
        constraints_applied = 0
        
        # Run capacity analysis if not already done
        if not hasattr(self, 'lab_capacity_analysis'):
            self.analyze_lab_capacity()
        
        # Get lab rooms categorized by capacity
        labs_35 = [lab['id'] for lab in self.lab_capacity_analysis['labs_35']]
        labs_70_plus = [lab['id'] for lab in self.lab_capacity_analysis['labs_70']] + [lab['id'] for lab in self.lab_capacity_analysis['labs_140']]
        
        # Initialize capacity preferences list
        self.capacity_preferences = []
        
        for teacher_id, courses in self.lab_requirements.items():
            for course in courses:
                course_instance_id = course['course_instance_id']
                practical_hours = course['practical_hours']
                students_per_instance = course['students_per_instance']
                
                # Determine allocation strategy using the same logic as lab scheduler
                strategy = self._determine_lab_allocation_strategy(practical_hours, students_per_instance)
                force_35_capacity = strategy['force_35_capacity']
                force_70_plus_capacity = strategy.get('force_70_plus_capacity', False)
                prefer_70_plus_with_batching_fallback = strategy.get('prefer_70_plus_with_batching_fallback', False)
                
                if force_35_capacity or practical_hours <= 3:
                    # Courses with 3 or fewer practical hours must use 35-capacity labs only
                    for day_idx in range(self.num_days):
                        for session_name in self.lab_sessions.keys():
                            for room_id in labs_70_plus:
                                if teacher_id in lab_variables and course_instance_id in lab_variables[teacher_id]:
                                    model.Add(lab_variables[teacher_id][course_instance_id][day_idx][session_name][room_id] == 0)
                                    constraints_applied += 1
                    
                    self.logger.info(f"Course {course['course_code']} (practical_hours={practical_hours}) restricted to 35-capacity labs")
                    
                elif prefer_70_plus_with_batching_fallback:
                    # Courses with 4-6 practical hours prefer 70+ but can use 35 with batching
                    # Create a preference variable to encourage 70+ labs
                    prefer_70_plus = model.NewBoolVar(f'course_{course_instance_id}_prefer_70_plus')
                    
                    # Count assignments in 70+ capacity labs
                    assignments_70_plus = []
                    assignments_35 = []
                    
                    if teacher_id in lab_variables and course_instance_id in lab_variables[teacher_id]:
                        for day_idx in range(self.num_days):
                            for session_name in self.lab_sessions.keys():
                                for room_id in labs_70_plus:
                                    assignments_70_plus.append(lab_variables[teacher_id][course_instance_id][day_idx][session_name][room_id])
                                for room_id in labs_35:
                                    assignments_35.append(lab_variables[teacher_id][course_instance_id][day_idx][session_name][room_id])
                    
                    # If prefer_70_plus is true, then all assignments should be in 70+ labs
                    if assignments_70_plus and assignments_35:
                        total_assignments = assignments_70_plus + assignments_35
                        
                        # Preference constraint: if prefer_70_plus = 1, then use only 70+ labs
                        model.Add(sum(assignments_35) == 0).OnlyEnforceIf(prefer_70_plus)
                        model.Add(sum(assignments_70_plus) == sum(total_assignments)).OnlyEnforceIf(prefer_70_plus)
                        constraints_applied += 2
                        
                        # Store preference for objective (encourage 70+ usage)
                        self.capacity_preferences.append(prefer_70_plus * 10)  # Bonus for using 70+ labs
                    
                    self.logger.info(f"Course {course['course_code']} (practical_hours={practical_hours}) PREFERS 70+ capacity labs, allows 35-capacity fallback with batching")
                    
                elif force_70_plus_capacity:
                    # Courses with force_70_plus_capacity flag must use 70+ capacity labs only
                    for day_idx in range(self.num_days):
                        for session_name in self.lab_sessions.keys():
                            for room_id in labs_35:
                                if teacher_id in lab_variables and course_instance_id in lab_variables[teacher_id]:
                                    model.Add(lab_variables[teacher_id][course_instance_id][day_idx][session_name][room_id] == 0)
                                    constraints_applied += 1
                    
                    self.logger.info(f"Course {course['course_code']} (practical_hours={practical_hours}) restricted to 70+ capacity labs")
                else:
                    # Courses with other practical hours can use any lab
                    self.logger.info(f"Course {course['course_code']} (practical_hours={practical_hours}) can use any capacity lab")
        
        self.logger.info(f"Applied {constraints_applied} capacity-based constraints")
        return constraints_applied

    def analyze_theory_feasibility(self):
        """Analyze if theory scheduling is feasible with current constraints."""
        self.logger.info("Analyzing theory scheduling feasibility...")
        
        # Basic feasibility checks
        total_groups = sum(len(groups) for groups in self.course_groups.values())
        total_theory_slots = self.num_days * self.num_theory_slots
        total_room_capacity = len(self.theory_room_ids) * total_theory_slots
        
        # Calculate required slots
        total_required_slots = sum(self.group_requirements.values())
        
        self.logger.info(f"Theory feasibility analysis:")
        self.logger.info(f"  - Total groups: {total_groups}")
        self.logger.info(f"  - Total required slots: {total_required_slots}")
        self.logger.info(f"  - Total available time slots: {total_theory_slots}")
        self.logger.info(f"  - Total room capacity: {total_room_capacity}")
        
        if total_required_slots > total_room_capacity:
            self.logger.error(f"INFEASIBLE: Required slots ({total_required_slots}) exceed room capacity ({total_room_capacity})")
            return False
        
        # Check semester-level feasibility
        semester_feasible = True
        for (dept, semester), groups in self.course_groups.items():
            semester_key = f"{dept}_S{semester}"
            semester_required = 0
            
            for group_idx, group in enumerate(groups):
                if group:
                    group_name = f"{dept}_S{semester}_G{group_idx + 1}"
                    if group_name in self.group_requirements:
                        semester_required += self.group_requirements[group_name]
            
            if semester_required > total_theory_slots:
                self.logger.error(f"INFEASIBLE: {semester_key} requires {semester_required} slots but only {total_theory_slots} available")
                semester_feasible = False
        
        if semester_feasible:
            self.logger.info("✅ Theory scheduling appears feasible")
        
        return semester_feasible

    def add_group_allocation_objective(self, model, group_timeslot_vars):
        """Add objective for optimal group time slot allocation."""
        self.logger.info("Setting up group allocation objective...")
        objective_terms = []
        
        # Strategy: Prefer earlier time slots to create compact schedules
        for group_name, day_slots in group_timeslot_vars.items():
            for day_idx in range(self.num_days):
                for slot_idx in range(self.num_theory_slots):
                    # Give higher weight to earlier slots (morning preferred over evening)
                    weight = self.num_theory_slots - slot_idx
                    objective_terms.append(day_slots[day_idx][slot_idx] * weight)
        
        if objective_terms:
            model.Maximize(sum(objective_terms))
            self.logger.info(f"Group allocation objective set with {len(objective_terms)} terms")
            self.logger.info("Objective strategy: Prefer earlier time slots for compact scheduling")
        else:
            self.logger.warning("No objective terms created for group allocation")