#!/usr/bin/env python3
"""
Course Instance to Group Distribution Optimizer using OR-Tools

This module uses OR-Tools to optimally distribute course instances to groups
with the same constraints as the combined_scheduler.py, but using mathematical
optimization instead of greedy algorithms.
"""

import os
import pandas as pd
import numpy as np
import logging
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set
from collections import defaultdict, Counter
from ortools.sat.python import cp_model
import matplotlib.pyplot as plt
import seaborn as sns


class CourseGroupOptimizer:
    """
    OR-Tools based optimizer for distributing course instances to groups.
    
    Preprocessing:
    - Removes courses with fewer instances than the most common instance count
    - Keeps courses with exact match to most common count
    - Trims courses with extra instances down to the most common count (random selection)
    
    Implements the core constraints:
    1. Teacher uniqueness: No teacher appears multiple times in the same group
    2. Course limit: Each course can appear in at most 2 groups
    3. Group size equality: Each group has the same number of instances 
       (equal to the most common number of course instances per course)
    4. Lab priority: Courses with practical hours occupy initial groups first
       (skipped if only 1 lab course or only 1 theory-only course)
    
    Number of groups is always equal to the number of unique courses (after filtering).
    """
    
    def __init__(
        self,
        courses,
        dept,
        semester,
        logger=None,
        pe_course_map_file=None,
        flexible_grouping_depts=None,
        consolidation_objective_enabled=None,
    ):
        """
        Initialize the optimizer with course instances.
        
        Args:
            courses: List of course instances to distribute
            dept: Department name
            semester: Semester number
            logger: Logger instance (optional)
            pe_course_map_file: Path to PE course mapping CSV file (optional)
            flexible_grouping_depts: List of departments that can have minimum 1 group for multi-instance courses (optional)
        """
        self.courses = courses
        self.dept = dept
        self.semester = semester
        self.logger = logger or logging.getLogger(__name__)
        self.pe_course_map_file = pe_course_map_file
        
        # Departments that can have minimum 1 group for multi-instance courses
        # If not specified, use default list of flexible departments
        if flexible_grouping_depts is None:
            self.flexible_grouping_depts = {
                'Computer Science & Engineering',
                'Computer Science & Business Systems',
                'Computer Science & Design',
                'Artificial Intelligence & Data Science',
                'Artificial Intelligence & Machine Learning',
                'Information Technology',
                "Computer Science & Engineering (Cyber Security)"
            }
        else:
            self.flexible_grouping_depts = set(flexible_grouping_depts)
        
        # Special-case flags
        self.is_cse_s2 = (self.dept == "Computer Science & Engineering" and self.semester == 2)

        # Semester-based heuristic is kept for backwards compatibility.
        # If *consolidation_objective_enabled* is provided, it becomes the source of truth.
        self.is_third_year = self.semester in (5, 6)
        if consolidation_objective_enabled is None:
            self.consolidation_objective_enabled = self.is_third_year
        else:
            self.consolidation_objective_enabled = bool(consolidation_objective_enabled)

        # Flexible grouping is required to allow consolidation into a single group.
        self.allows_flexible_grouping = self.consolidation_objective_enabled or (self.dept in self.flexible_grouping_depts)

        # Internal: course -> list[BoolVar] (presence of that course in each group)
        # populated in _apply_course_limit_constraints for objective construction.
        self._course_group_presence_vars = {}
        
        # Load PE course mapping if provided
        self.pe_course_codes = set()
        self.pe_courses = []
        if pe_course_map_file:
            self._load_pe_course_mapping()
        
        # Preprocess ALL courses to handle large instances FIRST (before separation)
        self.courses = self._preprocess_large_courses(self.courses)
        
        # Then separate PE courses from regular courses after preprocessing
        self.courses, self.pe_courses = self._separate_pe_courses(self.courses)
        
        # Processing results
        self.groups = []
        self.solution_found = False
        self.objective_value = 0
        
        # Track removed and modified courses for verification
        self.removed_courses = []  # Courses removed due to insufficient instances
        self.trimmed_courses = {}  # Courses trimmed down: {course_code: {'original_count': x, 'kept_count': y, 'removed_instances': []}}
        self.filtering_summary = {}  # Summary of filtering process
        
        # Filter courses based on instance count before analysis
        self.courses = self._filter_courses_by_instance_count(self.courses)
        
        # Course analysis (only on non-PE courses)
        self.lab_courses = [inst for inst in self.courses if inst.get('has_lab', False)]
        self.theory_courses = [inst for inst in self.courses if inst.get('has_theory', False)]
        self.unique_courses = list(set(inst['course_code'] for inst in self.courses))
        self.unique_teachers = list(set(inst['teacher_id'] for inst in self.courses))
        
        # Number of groups equals number of unique courses (as requested by user)
        self.num_groups = len(self.unique_courses)
        
        self.logger.info(f"Initializing Course Group Optimizer for {dept} Semester {semester}")
        self.logger.info(f"  Total instances (excluding PE): {len(self.courses)}")
        self.logger.info(f"  PE course instances: {len(self.pe_courses)}")
        self.logger.info(f"  Lab instances: {len(self.lab_courses)}")
        self.logger.info(f"  Theory instances: {len(self.theory_courses)}")
        self.logger.info(f"  Unique courses: {len(self.unique_courses)}")
        self.logger.info(f"  Unique teachers: {len(self.unique_teachers)}")
        self.logger.info(f"  Target groups: {self.num_groups}")
        self.logger.info(f"  Flexible grouping enabled: {self.allows_flexible_grouping}")
        if self.allows_flexible_grouping:
            if self.consolidation_objective_enabled:
                self.logger.info(
                    "  → Consolidation policy enabled: minimize number of groups each multi-instance course spans"
                )
            else:
                self.logger.info("  → Multi-instance courses can have minimum 1 group (if feasible)")
        else:
            self.logger.info(f"  → Multi-instance courses must have minimum 2 groups")
        if self.pe_courses:
            pe_course_codes = list(set(inst['course_code'] for inst in self.pe_courses))
            self.logger.debug(f"  PE courses to be added as final group: {pe_course_codes}")
    
    def _load_pe_course_mapping(self):
        """
        Load PE course mapping from CSV file to identify Professional Elective courses.
        """
        if not self.pe_course_map_file or not os.path.exists(self.pe_course_map_file):
            self.logger.warning(f"PE course map file not found: {self.pe_course_map_file}")
            return
        
        try:
            import pandas as pd
            df = pd.read_csv(self.pe_course_map_file)
            
            # Extract GENERAL CODE values and filter by department and semester
            if 'GENERAL CODE' in df.columns and 'DEPT' in df.columns and 'SEM' in df.columns:
                # Filter by department and semester
                dept_mapping = {
                    "AERO": "Aeronautical Engineering",
                    'AIDS': 'Artificial Intelligence & Data Science',
                    'AIML': 'Artificial Intelligence & Machine Learning', 
                    'CSE': 'Computer Science & Engineering',
                    'BME': 'Biomedical Engineering',
                    'BT': 'Biotechnology',
                    'EEE': 'Electrical & Electronics Engineering',
                    'ECE': 'Electronics & Communication Engineering',
                    'MECH': 'Mechanical Engineering',
                    'MCT': 'Mechatronics Engineering',
                    'RA': 'Robotics & Automation',
                    'IT': 'Information Technology',
                    "AUTO": "Automobile Engineering",
                    "CHEM": "Chemical Engineering",
                    "FT": "Food Technology",
                    "CIVIL": "Civil Engineering",
                    "CSBS": "Computer Science and Business Systems",
                    "CSD": "Computer Science and Design",
                    "CSECS": "Computer Science and Engineering - Cyber Security",
                }
                
                # Find matching department abbreviation
                dept_abbrev = None
                for abbrev, full_name in dept_mapping.items():
                    if full_name == self.dept:
                        dept_abbrev = abbrev
                        break
                
                if dept_abbrev:
                    # Filter for matching department and semester
                    filtered_df = df[(df['DEPT'] == dept_abbrev) & (df['SEM'] == self.semester)]
                    
                    # Extract PE course codes
                    for _, row in filtered_df.iterrows():
                        general_code = row['GENERAL CODE']
                        if pd.notna(general_code) and general_code.strip():
                            self.pe_course_codes.add(general_code.strip())
                    
                    self.logger.info(f"Loaded {len(self.pe_course_codes)} PE course codes for {self.dept} Semester {self.semester}: {sorted(self.pe_course_codes)}")
                else:
                    self.logger.warning(f"No PE course mapping found for department: {self.dept}")
            else:
                self.logger.error(f"PE course map file missing required columns: GENERAL CODE, DEPT, SEM")
                
        except Exception as e:
            self.logger.error(f"Error loading PE course mapping: {e}")
            import traceback
            traceback.print_exc()

    def _separate_pe_courses(self, courses):
        """
        Separate PE (Professional Elective) courses from regular courses.
        
        Args:
            courses: List of all course instances
            
        Returns:
            tuple: (regular_courses, pe_courses)
        """
        regular_courses = []
        pe_courses = []
        
        for course in courses:
            course_code = course.get('course_code', '')
            if course_code in self.pe_course_codes:
                pe_courses.append(course)
                self.logger.debug(f"Identified PE course: {course_code}")
            else:
                regular_courses.append(course)
        
        if pe_courses:
            pe_course_codes = list(set(inst['course_code'] for inst in pe_courses))
            self.logger.debug(f"Separated {len(pe_courses)} PE course instances from optimization: {pe_course_codes}")
        
        return regular_courses, pe_courses
    
    def _preprocess_large_courses(self, courses):
        """
        Calculate logical weights for courses based on student count.
        Replaces the old splitting logic.
        """
        # Determine base student count (most common student count)
        # We use 70 as the standard base count as per requirements
        base_count = 70
        
        new_courses = []
        
        for course in courses:
            count = course.get('student_count', 0)
            
            # Calculate weight: round(count / 70)
            # But ensure at least 1
            if count <= 0:
                weight = 1
            else:
                # Use standard rounding
                weight = int(round(count / base_count))
                if weight < 1: weight = 1
            
            # Store weight in the course dictionary
            course['weight'] = weight
            
            # Log if weight > 1
            if weight > 1:
                self.logger.debug(f"Course {course.get('course_code')} ({count} students) assigned weight {weight}")
            
            new_courses.append(course)
            
        return new_courses
    
    def _filter_courses_by_instance_count(self, courses):
        """
        Filter courses based on instance count (weighted). Remove courses that have fewer 
        weighted instances than the most common weighted instance count.
        
        Args:
            courses: List of all course instances
            
        Returns:
            list: Filtered list of course instances
        """
        if not courses:
            self.logger.warning("No regular (non-PE) courses found after preprocessing; skipping optimization cohort")
            return []

        # Count instances (weights) per course
        course_instance_counts = defaultdict(int)
        for course in courses:
            course_instance_counts[course['course_code']] += course.get('weight', 1)

        if not course_instance_counts:
            self.logger.warning("No course instance counts available after weighting; skipping optimization cohort")
            return []
        
        # Find the most common weighted instance count
        instance_count_frequency = defaultdict(int)
        for course_code, count in course_instance_counts.items():
            instance_count_frequency[count] += 1
        
        most_common_count = max(instance_count_frequency.keys(), 
                               key=lambda x: instance_count_frequency[x])
        
        # Log instance count distribution
        self.logger.info(f"Course instance count (weighted) analysis:")
        for count, freq in sorted(instance_count_frequency.items()):
            self.logger.info(f"  {freq} courses have {count} weighted instances each")
        self.logger.info(f"Most common weighted instance count: {most_common_count}")
        
        # Process courses based on instance count
        courses_to_keep = set()
        courses_to_remove = set()
        courses_to_trim = {}  # course_code -> target_count
        
        for course_code, count in course_instance_counts.items():
            if count < most_common_count:
                courses_to_remove.add(course_code)
            elif count == most_common_count:
                courses_to_keep.add(course_code)
            else:  # count > most_common_count
                courses_to_keep.add(course_code)
                courses_to_trim[course_code] = most_common_count
        
        # Store removed courses for verification
        if courses_to_remove:
            self.logger.warning(f"Removing courses with insufficient weighted instances:")
            for course_code in sorted(courses_to_remove):
                count = course_instance_counts[course_code]
                removed_instances = [c for c in courses if c['course_code'] == course_code]
                
                # Store removed course info
                self.removed_courses.extend(removed_instances)
                
                self.logger.warning(f"  {course_code}: {count} weighted instances (< {most_common_count}) - REMOVED")
        
        if courses_to_keep:
            self.logger.info(f"Keeping courses:")
            for course_code in sorted(courses_to_keep):
                count = course_instance_counts[course_code]
                if count == most_common_count:
                    self.logger.info(f"  {course_code}: {count} weighted instances (= {most_common_count}) - KEPT")
                elif course_code in courses_to_trim:
                    target_count = courses_to_trim[course_code]
                    self.logger.info(f"  {course_code}: {count} weighted instances -> trimming to {target_count} weighted instances")
        
        # Filter and trim course instances
        import random
        filtered_courses = []
        
        for course_code in courses_to_keep:
            course_instances = [c for c in courses if c['course_code'] == course_code]
            
            if course_code in courses_to_trim:
                target_count = courses_to_trim[course_code]
                
                # Sort by weight descending to prioritize keeping large instances
                course_instances.sort(key=lambda x: x.get('weight', 1), reverse=True)
                
                selected_instances = []
                current_weight = 0
                
                for inst in course_instances:
                    w = inst.get('weight', 1)
                    if current_weight + w <= target_count:
                        selected_instances.append(inst)
                        current_weight += w
                
                if current_weight < target_count:
                    self.logger.warning(f"  {course_code}: Could not trim to exactly {target_count} weight (got {current_weight}). Removing course.")
                    self.removed_courses.extend(course_instances)
                    continue
                
                removed_instances = [inst for inst in course_instances if inst not in selected_instances]
                
                # Store trimming info
                self.trimmed_courses[course_code] = {
                    'original_count': len(course_instances),
                    'kept_count': len(selected_instances),
                    'removed_instances': removed_instances,
                    'kept_instances': selected_instances
                }
                
                filtered_courses.extend(selected_instances)
                self.logger.info(f"  {course_code}: selected {len(selected_instances)} instances (weight {current_weight}) out of {len(course_instances)}")
            else:
                # Keep all instances
                filtered_courses.extend(course_instances)
        
        # Create filtering summary
        self.filtering_summary = {
            'original_total_instances': len(courses),
            'filtered_total_instances': len(filtered_courses),
            'most_common_instance_count': most_common_count,
            'instance_count_distribution': dict(instance_count_frequency),
            'courses_removed_count': len(set(inst['course_code'] for inst in self.removed_courses)),
            'courses_trimmed_count': len(self.trimmed_courses),
            'total_instances_removed': len(self.removed_courses) + sum(len(info['removed_instances']) for info in self.trimmed_courses.values()),
            'courses_kept_unchanged': len(courses_to_keep) - len(self.trimmed_courses)
        }
        
        self.logger.info(f"Filtered courses: {len(courses)} -> {len(filtered_courses)} instances")
        self.logger.info(f"Filtering summary: {self.filtering_summary['courses_removed_count']} courses removed, "
                        f"{self.filtering_summary['courses_trimmed_count']} courses trimmed, "
                        f"{self.filtering_summary['total_instances_removed']} total instances removed")
        
        return filtered_courses
    
    def _check_feasibility(self):
        """
        Check if the problem is feasible given the constraints.
        
        Returns:
            bool: True if feasible, False otherwise
        """
        # Basic feasibility check with the updated constraints:
        # 1. We have at least 1 group
        # 2. Single-instance courses: can be in 1 group
        # 3. Multi-instance courses: must be in exactly 2 groups (min 2, max 2)
        # 4. Teacher uniqueness within groups (handled by the optimizer)
        # 5. Each group has the same number of instances (equal to most common course instance count)
        
        if self.num_groups == 0:
            self.logger.error("INFEASIBLE: No groups available")
            return False
        
        # Count instances (weights) per course
        course_instance_counts = defaultdict(int)
        course_teacher_counts = defaultdict(set)
        
        for course in self.courses:
            course_code = course['course_code']
            teacher_id = course['teacher_id']
            course_instance_counts[course_code] += course.get('weight', 1)
            course_teacher_counts[course_code].add(teacher_id)
        
        # Find the most common instance count (target group size)
        instance_count_frequency = defaultdict(int)
        for course_code, count in course_instance_counts.items():
            instance_count_frequency[count] += 1
        
        target_group_size = max(instance_count_frequency.keys(), 
                               key=lambda x: instance_count_frequency[x])
        
        # Check if total instances can be evenly distributed
        total_instances = sum(c.get('weight', 1) for c in self.courses)
        required_instances = self.num_groups * target_group_size
        
        if total_instances != required_instances:
            self.logger.error(f"INFEASIBLE: Cannot distribute {total_instances} weighted instances into "
                            f"{self.num_groups} groups of {target_group_size} weighted instances each "
                            f"(requires {required_instances} instances)")
            return False
        
        # Log distribution info
        self.logger.info(f"Feasibility analysis:")
        self.logger.info(f"  Total weighted instances: {total_instances}")
        self.logger.info(f"  Number of groups: {self.num_groups}")
        self.logger.info(f"  Target group size (weighted): {target_group_size}")
        self.logger.info(f"  Required total: {required_instances}")
        
        # Check course distribution requirements
        multi_instance_courses = 0
        single_instance_courses = 0
        
        for course_code, instance_count in course_instance_counts.items():
            teacher_count = len(course_teacher_counts[course_code])
            
            if instance_count == 1:
                single_instance_courses += 1
                self.logger.info(f"Course {course_code}: {instance_count} weighted instance, "
                               f"{teacher_count} teacher -> will be in 1 group")
            elif instance_count > 1:
                multi_instance_courses += 1
                if self.num_groups < 2:
                    self.logger.error(f"INFEASIBLE: Course {course_code} has {instance_count} weighted instances "
                                    f"but only {self.num_groups} groups available (need at least 2 groups)")
                    return False
                self.logger.info(f"Course {course_code}: {instance_count} weighted instances, "
                               f"{teacher_count} different teachers -> must be in exactly 2 groups")
        
        self.logger.info(f"Course distribution: {single_instance_courses} single-instance, "
                        f"{multi_instance_courses} multi-instance courses")
        
        self.logger.info("Feasibility check passed - OR-Tools will handle constraint satisfaction")
        return True
    
    def optimize_distribution(self):
        """
        Main optimization method using OR-Tools CP-SAT solver.
        
        Returns:
            bool: True if optimal solution found, False otherwise
        """
        if not self.courses:
            self.logger.warning("No courses to distribute")
            return False
        
        if self.num_groups == 0:
            self.logger.warning("No groups to create")
            return False
        
        # Check feasibility before optimization
        if not self._check_feasibility():
            return False
        
        self.logger.info("Starting OR-Tools optimization for course group distribution")
        
        # Create the CP-SAT model
        model = cp_model.CpModel()
        
        # Create decision variables
        assignment_vars = self._create_assignment_variables(model)
        
        # Apply constraints
        self._apply_assignment_constraints(model, assignment_vars)
        self._apply_teacher_uniqueness_constraints(model, assignment_vars)
        self._apply_course_limit_constraints(model, assignment_vars)
        self._apply_group_size_constraints(model, assignment_vars)
        self._apply_lab_priority_constraints(model, assignment_vars)
        
        # Apply special constraints for specific departments/semesters
        self._apply_special_department_constraints(model, assignment_vars)
        
        # Set objectives
        self._set_optimization_objectives(model, assignment_vars)
        
        # Solve the model
        return self._solve_model(model, assignment_vars)
    
    def _create_assignment_variables(self, model):
        """
        Create binary decision variables for course instance to group assignment.
        
        Args:
            model: CP-SAT model
            
        Returns:
            dict: Assignment variables indexed by (instance_id, group_id)
        """
        assignment_vars = {}
        
        for i, instance in enumerate(self.courses):
            instance_id = instance['id']
            for group_idx in range(self.num_groups):
                clean_instance_id = str(instance_id).replace('-', '_') # Make it a valid var name
                var_name = f"assign_inst_{clean_instance_id}_to_group_{group_idx}"
                assignment_vars[(i, group_idx)] = model.NewBoolVar(var_name)
        
        self.logger.info(f"Created {len(assignment_vars)} assignment variables")
        return assignment_vars
    
    def _apply_assignment_constraints(self, model, assignment_vars):
        """
        Apply basic assignment constraints.
        
        Args:
            model: CP-SAT model
            assignment_vars: Assignment variables
        """
        # Each instance must be assigned to exactly one group
        for i, instance in enumerate(self.courses):
            if 'co_scheduled_id' in instance and 'virtual_id' in instance and instance['virtual_id'].endswith('-B'):
                # This is the second virtual instance, skip direct assignment
                # It will be forced to follow the first instance
                continue

            instance_assignments = [assignment_vars[(i, g)] for g in range(self.num_groups)]
            model.Add(sum(instance_assignments) == 1)

            if 'co_scheduled_id' in instance and 'virtual_id' in instance and instance['virtual_id'].endswith('-A'):
                # Find the corresponding second instance
                co_id = instance['co_scheduled_id']
                second_instance_idx = -1
                for j, inst in enumerate(self.courses):
                    if inst.get('co_scheduled_id') == co_id and inst.get('virtual_id', '').endswith('-B'):
                        second_instance_idx = j
                        break
                
                if second_instance_idx != -1:
                    # Force the second instance to be in the same group as the first
                    for g in range(self.num_groups):
                        model.Add(assignment_vars[(i, g)] == assignment_vars[(second_instance_idx, g)])
        
        self.logger.info("Applied basic assignment constraints (each instance to one group, with co-scheduling links)")
    
    def _apply_teacher_uniqueness_constraints(self, model, assignment_vars):
        """
        Apply teacher uniqueness constraints: no teacher appears multiple times in same group.
        
        Args:
            model: CP-SAT model
            assignment_vars: Assignment variables
        """
        teacher_constraints_added = 0
        
        for group_idx in range(self.num_groups):
            # Group instances by teacher for this group
            teacher_instances = defaultdict(list)
            
            for i, instance in enumerate(self.courses):
                teacher_id = instance['teacher_id']
                teacher_instances[teacher_id].append(i)
            
            # Add constraints: at most one instance per teacher per group
            for teacher_id, instance_indices in teacher_instances.items():
                if len(instance_indices) > 1:
                    # Check for valid co-scheduling cases
                    co_scheduling_groups = defaultdict(list)
                    for i in instance_indices:
                        if 'co_scheduled_id' in self.courses[i]:
                            co_scheduling_groups[self.courses[i]['co_scheduled_id']].append(i)
                    
                    # For each co-scheduling group, allow up to 2 instances from the same teacher
                    for co_id, co_indices in co_scheduling_groups.items():
                        if len(co_indices) == 2:
                            co_vars = [assignment_vars[(i, group_idx)] for i in co_indices]
                            model.Add(sum(co_vars) <= 2) # Allow both in the same group
                    
                    # For non-co-scheduled instances, enforce normal teacher uniqueness
                    non_co_scheduled_indices = [
                        i for i in instance_indices if 'co_scheduled_id' not in self.courses[i]
                    ]
                    
                    # Include the first instance from any co-scheduling group of size 1
                    for co_id, co_indices in co_scheduling_groups.items():
                        if len(co_indices) == 1:
                            non_co_scheduled_indices.extend(co_indices)

                    if len(non_co_scheduled_indices) > 1:
                        teacher_assignments = [assignment_vars[(i, group_idx)] for i in non_co_scheduled_indices]
                        model.Add(sum(teacher_assignments) <= 1)
                        teacher_constraints_added += 1

        self.logger.info(f"Applied {teacher_constraints_added} teacher uniqueness constraints with co-scheduling exceptions")
    
    def _apply_course_limit_constraints(self, model, assignment_vars):
        """
        Apply course limit constraints:
        - Courses with multiple instances: 
          * Flexible departments: minimum 1 group, maximum 2 groups (allows consolidation if feasible)
          * Standard departments: minimum 2 groups, maximum 2 groups
        - Courses with single instance: allow in only 1 group
        
        Args:
            model: CP-SAT model
            assignment_vars: Assignment variables
        """
        course_constraints_added = 0
        single_instance_courses = 0
        multi_instance_courses = 0
        flexible_courses = 0

        # CSE Semester 2 is a special case: we enforce per-course spreading across 5 groups
        # (balanced) in _apply_special_department_constraints. Do NOT add the default
        # max-2-groups constraint here.
        if self.is_cse_s2:
            self.logger.info(
                "Skipping default course limit constraints for CSE Semester 2 (handled by special constraints: 5-group split)"
            )
            return
        
        for course_code in self.unique_courses:
            # Find all instances of this course
            course_instances = [i for i, inst in enumerate(self.courses) 
                             if inst['course_code'] == course_code]
            
            if len(course_instances) == 1:
                # Single instance course: can be in only 1 group (natural constraint)
                single_instance_courses += 1
                self.logger.debug(f"Course {course_code}: 1 instance -> can be in 1 group")
                
            elif len(course_instances) > 1:
                # Multiple instance course: apply constraints based on department flexibility
                multi_instance_courses += 1
                
                # Create auxiliary variables to track which groups have this course
                group_has_course = []
                for group_idx in range(self.num_groups):
                    group_var = model.NewBoolVar(f"course_{course_code}_in_group_{group_idx}")
                    group_has_course.append(group_var)
                    
                    # Link auxiliary variable to assignments
                    course_assignments_in_group = [assignment_vars[(i, group_idx)] 
                                                 for i in course_instances]
                    
                    # If any instance of this course is in this group, set the group variable to 1
                    for course_instance_idx in course_instances:
                        model.Add(group_var >= assignment_vars[(course_instance_idx, group_idx)])
                    
                    # If no instance of this course is in this group, group_var should be 0
                    # This constraint ensures group_var = 1 iff at least one instance is assigned to this group
                    model.Add(group_var <= sum(course_assignments_in_group))

                # Store for objective building (multi-instance courses only)
                self._course_group_presence_vars[course_code] = group_has_course
                
                # Apply minimum group constraint based on department flexibility
                if self.allows_flexible_grouping:
                    # Flexible departments: Allow courses to be in minimum 1 group (consolidation allowed)
                    model.Add(sum(group_has_course) >= 1)
                    course_constraints_added += 1
                    flexible_courses += 1
                    self.logger.debug(f"Course {course_code}: {len(course_instances)} instances -> flexible (min 1, max 2 groups)")
                else:
                    # Standard departments: Enforce minimum 2 groups for distribution
                    if self.num_groups >= 2:
                        model.Add(sum(group_has_course) >= 2)
                        course_constraints_added += 1
                    self.logger.debug(f"Course {course_code}: {len(course_instances)} instances -> standard (min 2, max 2 groups)")
                    
                # Maximum constraint: Course can be in at most 2 groups (always enforced)
                model.Add(sum(group_has_course) <= 2)
                course_constraints_added += 1
        
        self.logger.info(f"Applied {course_constraints_added} course limit constraints")
        self.logger.info(f"  Single-instance courses: {single_instance_courses} (can be in 1 group)")
        if self.allows_flexible_grouping:
            self.logger.info(f"  Multi-instance courses: {multi_instance_courses} (min 1, max 2 groups - FLEXIBLE)")
            self.logger.info(f"  Flexible courses allowing consolidation: {flexible_courses}")
        else:
            self.logger.info(f"  Multi-instance courses: {multi_instance_courses} (min 2, max 2 groups - STANDARD)")
    
    def _apply_group_size_constraints(self, model, assignment_vars):
        """
        Apply group size constraints: each group should have the same number of instances (weighted),
        equal to the most common number of course instances per course.
        
        Args:
            model: CP-SAT model
            assignment_vars: Assignment variables
        """
        # Calculate the most common number of instances per course (weighted)
        course_instance_counts = defaultdict(int)
        for course in self.courses:
            course_instance_counts[course['course_code']] += course.get('weight', 1)
        
        # Find the most frequent instance count
        instance_count_frequency = defaultdict(int)
        for course_code, count in course_instance_counts.items():
            instance_count_frequency[count] += 1
        
        # Get the most common instance count
        target_group_size = max(instance_count_frequency.keys(), 
                               key=lambda x: instance_count_frequency[x])
        
        self.target_group_size = target_group_size
        
        self.logger.info(f"Course instance distribution (weighted):")
        for count, freq in sorted(instance_count_frequency.items()):
            self.logger.info(f"  {freq} courses have {count} weighted instances each")
        self.logger.info(f"Target group size: {target_group_size} weighted instances per group")
        
        # Apply constraint: each group must have exactly target_group_size instances (weighted)
        group_size_constraints_added = 0
        for group_idx in range(self.num_groups):
            group_assignments_weighted = []
            for i, instance in enumerate(self.courses):
                weight = instance.get('weight', 1)
                group_assignments_weighted.append(assignment_vars[(i, group_idx)] * weight)
            
            # Each group must have exactly target_group_size instances
            model.Add(sum(group_assignments_weighted) == target_group_size)
            group_size_constraints_added += 1
        
        self.logger.info(f"Applied {group_size_constraints_added} group size constraints "
                        f"(each group = {target_group_size} weighted instances)")
    
    def _apply_lab_priority_constraints(self, model, assignment_vars):
        """
        Apply lab priority constraints: courses with practical hours occupy initial groups first.
        
        Args:
            model: CP-SAT model
            assignment_vars: Assignment variables
        """
        # CSE S2 special case requires each course to span 5 groups.
        # The current lab-priority rule is a hard partition (labs only in early groups,
        # theory only in late groups). With typical inputs (e.g., 6 lab courses => only
        # 2 remaining theory groups), that can make the model INFEASIBLE.
        if getattr(self, "is_cse_s2", False):
            self.logger.info(
                "Skipping lab priority constraint for CSE S2 (conflicts with 5-group split requirement)"
            )
            return

        # Identify lab and theory-only courses
        lab_courses = set()
        theory_only_courses = set()
        
        for course in self.courses:
            practical_hours = course.get('practical_hours', 0)
            if practical_hours > 0:
                lab_courses.add(course['course_code'])
            else:
                theory_only_courses.add(course['course_code'])
        
        # Skip constraint if only 1 lab course or only 1 theory-only course
        if len(lab_courses) <= 1 or len(theory_only_courses) <= 1:
            self.logger.info(f"Skipping lab priority constraint: "
                           f"{len(lab_courses)} lab courses, {len(theory_only_courses)} theory-only courses")
            return
        
        num_lab_courses = len(lab_courses)
        num_theory_courses = len(theory_only_courses)
        
        self.logger.info(f"Applying lab priority constraint:")
        self.logger.info(f"  Lab courses ({num_lab_courses}): {sorted(lab_courses)} -> Groups 1-{num_lab_courses}")
        self.logger.info(f"  Theory courses ({num_theory_courses}): {sorted(theory_only_courses)} -> Groups {num_lab_courses+1}-{self.num_groups}")
        
        lab_priority_constraints_added = 0
        
        # Constraint 1: Lab course instances can only be in the first num_lab_courses groups
        for i, instance in enumerate(self.courses):
            course_code = instance['course_code']
            practical_hours = instance.get('practical_hours', 0)
            
            if practical_hours > 0:  # This is a lab course instance
                # Can only be assigned to groups 0 to (num_lab_courses - 1)
                for group_idx in range(num_lab_courses, self.num_groups):
                    model.Add(assignment_vars[(i, group_idx)] == 0)
                    lab_priority_constraints_added += 1
        
        # Constraint 2: Theory-only course instances can only be in the remaining groups
        for i, instance in enumerate(self.courses):
            course_code = instance['course_code']
            practical_hours = instance.get('practical_hours', 0)
            
            if practical_hours == 0:  # This is a theory-only course instance
                # Can only be assigned to groups num_lab_courses to (num_groups - 1)
                for group_idx in range(0, num_lab_courses):
                    model.Add(assignment_vars[(i, group_idx)] == 0)
                    lab_priority_constraints_added += 1
        
        self.logger.info(f"Applied {lab_priority_constraints_added} lab priority constraints")
    
    def _apply_special_department_constraints(self, model, assignment_vars):
        """
        Apply special constraints for specific departments/semesters.
        
        Args:
            model: CP-SAT model
            assignment_vars: Assignment variables
        """
        constraints_added = 0
        
        # Special constraint for Electronics & Communication Engineering 2nd semester
        if (self.dept == "Electronics & Communication Engineering" and self.semester == 2):
            constraints_added += self._apply_ece_s2_even_core_split(model, assignment_vars)

        # Special constraint for Computer Science & Engineering 2nd semester
        if (self.dept == "Computer Science & Engineering" and self.semester == 2):
            constraints_added += self._apply_cse_s2_five_group_split(model, assignment_vars)

        # Special constraint for Artificial Intelligence & Data Science 4th semester (fixed grouping)
        if (self.dept == "Artificial Intelligence & Data Science" and self.semester == 4):
            constraints_added += self._apply_aids_s4_fixed_grouping(model, assignment_vars)

        # Special constraint for Biomedical Engineering 4th semester (fixed grouping)
        if (self.dept == "Biomedical Engineering" and self.semester == 4):
            constraints_added += self._apply_biomed_s4_fixed_grouping(model, assignment_vars)

        # Special constraint for Electrical & Electronics Engineering 4th semester (fixed grouping)
        if (self.dept == "Electrical & Electronics Engineering" and self.semester == 4):
            constraints_added += self._apply_eee_s4_fixed_grouping(model, assignment_vars)

        # Special constraint for Electronics & Communication Engineering 4th semester (fixed grouping)
        if (self.dept == "Electronics & Communication Engineering" and self.semester == 4):
            constraints_added += self._apply_ece_s4_fixed_grouping(model, assignment_vars)

        # Special constraint for Mechanical Engineering 4th semester (fixed grouping)
        if (self.dept == "Mechanical Engineering" and self.semester == 4):
            constraints_added += self._apply_mech_s4_fixed_grouping(model, assignment_vars)

        # Special constraint for Computer Science & Engineering 4th semester (fixed grouping)
        if (self.dept == "Computer Science & Engineering" and self.semester == 4):
            constraints_added += self._apply_cse_s4_fixed_grouping(model, assignment_vars)

        # Special constraint for Biotechnology 4th semester (fixed grouping)
        if (self.dept == "Biotechnology" and self.semester == 4):
            constraints_added += self._apply_biotech_s4_fixed_grouping(model, assignment_vars)
        
        if constraints_added > 0:
            self.logger.info(f"Applied {constraints_added} special department-specific constraints")
        else:
            self.logger.info("No special department-specific constraints applied")

    def _apply_aids_s4_fixed_grouping(self, model, assignment_vars):
        """Force AI&DS S4 to use a fixed course->group mapping (STRICT)."""
        if self.num_groups < 5:
            self.logger.warning(
                "Skipping AI&DS S4 fixed grouping: expected >= 5 groups, got %s",
                self.num_groups,
            )
            return 0

        self.logger.info("Applying AI&DS S4 fixed group mapping")

        fixed_group_counts = {
            # G1..G5 => 0..4
            "AD23431": {2: 2, 4: 2},
            "AI23431": {0: 5},
            "CS23431": {3: 4},
            "CS23432": {2: 3, 4: 1},
            "MA23434": {1: 5},
        }

        required_courses = set(fixed_group_counts.keys())
        present_courses = set(self.unique_courses)
        if present_courses != required_courses:
            missing = sorted(required_courses - present_courses)
            extra = sorted(present_courses - required_courses)
            raise ValueError(
                "AI&DS S4 fixed grouping requires exactly these courses after filtering: "
                f"{sorted(required_courses)}. Missing={missing}, Extra={extra}."
            )

        constraints_added = 0
        for course_code, group_targets in fixed_group_counts.items():
            allowed_groups = set(group_targets.keys())
            instance_indices = [
                i
                for i, inst in enumerate(self.courses)
                if inst.get("course_code") == course_code
            ]

            expected_total = sum(group_targets.values())
            if len(instance_indices) != expected_total:
                raise ValueError(
                    f"AI&DS S4 fixed grouping: {course_code} has {len(instance_indices)} instances "
                    f"(expected {expected_total})."
                )

            for instance_idx in instance_indices:
                for group_idx in range(self.num_groups):
                    if group_idx in allowed_groups:
                        continue
                    model.Add(assignment_vars[(instance_idx, group_idx)] == 0)
                    constraints_added += 1

            for group_idx, target in group_targets.items():
                group_count = model.NewIntVar(
                    0,
                    len(instance_indices),
                    f"aids_s4_{course_code}_count_g{group_idx}",
                )
                model.Add(group_count == sum(assignment_vars[(i, group_idx)] for i in instance_indices))
                constraints_added += 1
                model.Add(group_count == target)
                constraints_added += 1

        return constraints_added

    def _apply_biomed_s4_fixed_grouping(self, model, assignment_vars):
        """Force Biomedical Engineering S4 to use a fixed course->group mapping (STRICT)."""
        if self.num_groups < 8:
            self.logger.warning(
                "Skipping Biomedical S4 fixed grouping: expected >= 8 groups, got %s",
                self.num_groups,
            )
            return 0

        self.logger.info("Applying Biomedical Engineering S4 fixed group mapping")

        fixed_group_counts = {
            # G1..G8 => 0..7
            "BM23411": {5: 1, 6: 1},
            "BM23412": {5: 1, 7: 1},
            "BM23421": {3: 1, 4: 1},
            "BM23422": {2: 1, 4: 1},
            "BM23431": {0: 1, 1: 1},
            "CS23336": {2: 1, 3: 1},
            "MA23436": {0: 1, 1: 1},
            "MC23111": {6: 1, 7: 1},
        }

        required_courses = set(fixed_group_counts.keys())
        present_courses = set(self.unique_courses)
        if present_courses != required_courses:
            missing = sorted(required_courses - present_courses)
            extra = sorted(present_courses - required_courses)
            raise ValueError(
                "Biomedical S4 fixed grouping requires exactly these courses after filtering: "
                f"{sorted(required_courses)}. Missing={missing}, Extra={extra}."
            )

        constraints_added = 0
        for course_code, group_targets in fixed_group_counts.items():
            allowed_groups = set(group_targets.keys())
            instance_indices = [
                i
                for i, inst in enumerate(self.courses)
                if inst.get("course_code") == course_code
            ]

            expected_total = sum(group_targets.values())
            if len(instance_indices) != expected_total:
                raise ValueError(
                    f"Biomedical S4 fixed grouping: {course_code} has {len(instance_indices)} instances "
                    f"(expected {expected_total})."
                )

            for instance_idx in instance_indices:
                for group_idx in range(self.num_groups):
                    if group_idx in allowed_groups:
                        continue
                    model.Add(assignment_vars[(instance_idx, group_idx)] == 0)
                    constraints_added += 1

            for group_idx, target in group_targets.items():
                group_count = model.NewIntVar(
                    0,
                    len(instance_indices),
                    f"biomed_s4_{course_code}_count_g{group_idx}",
                )
                model.Add(group_count == sum(assignment_vars[(i, group_idx)] for i in instance_indices))
                constraints_added += 1
                model.Add(group_count == target)
                constraints_added += 1

        return constraints_added

    def _apply_eee_s4_fixed_grouping(self, model, assignment_vars):
        """Force Electrical & Electronics Engineering S4 to use a fixed mapping (STRICT)."""
        if self.num_groups < 6:
            self.logger.warning(
                "Skipping EEE S4 fixed grouping: expected >= 6 groups, got %s",
                self.num_groups,
            )
            return 0

        self.logger.info("Applying Electrical & Electronics Engineering S4 fixed group mapping")

        fixed_group_counts = {
            # G1..G6 => 0..5
            "CS23422": {0: 1, 2: 1},
            "EE23411": {4: 1, 5: 1},
            "EE23412": {4: 1, 5: 1},
            "EE23421": {0: 1, 2: 1},
            "EE23431": {1: 1, 3: 1},
            "EE23432": {1: 1, 3: 1},
        }

        required_courses = set(fixed_group_counts.keys())
        present_courses = set(self.unique_courses)
        if present_courses != required_courses:
            missing = sorted(required_courses - present_courses)
            extra = sorted(present_courses - required_courses)
            raise ValueError(
                "EEE S4 fixed grouping requires exactly these courses after filtering: "
                f"{sorted(required_courses)}. Missing={missing}, Extra={extra}."
            )

        constraints_added = 0
        for course_code, group_targets in fixed_group_counts.items():
            allowed_groups = set(group_targets.keys())
            instance_indices = [
                i
                for i, inst in enumerate(self.courses)
                if inst.get("course_code") == course_code
            ]

            expected_total = sum(group_targets.values())
            if len(instance_indices) != expected_total:
                raise ValueError(
                    f"EEE S4 fixed grouping: {course_code} has {len(instance_indices)} instances "
                    f"(expected {expected_total})."
                )

            for instance_idx in instance_indices:
                for group_idx in range(self.num_groups):
                    if group_idx in allowed_groups:
                        continue
                    model.Add(assignment_vars[(instance_idx, group_idx)] == 0)
                    constraints_added += 1

            for group_idx, target in group_targets.items():
                group_count = model.NewIntVar(
                    0,
                    len(instance_indices),
                    f"eee_s4_{course_code}_count_g{group_idx}",
                )
                model.Add(group_count == sum(assignment_vars[(i, group_idx)] for i in instance_indices))
                constraints_added += 1
                model.Add(group_count == target)
                constraints_added += 1

        return constraints_added

    def _apply_ece_s4_fixed_grouping(self, model, assignment_vars):
        """Force ECE S4 to use a fixed course->group mapping (STRICT)."""
        if self.num_groups < 6:
            self.logger.warning(
                "Skipping ECE S4 fixed grouping: expected >= 6 groups, got %s",
                self.num_groups,
            )
            return 0

        self.logger.info("Applying Electronics & Communication Engineering S4 fixed group mapping")

        fixed_group_counts = {
            # G1..G6 => 0..5
            "CS23422": {0: 5, 2: 1},
            "EC23411": {4: 2, 5: 4},
            "EC23412": {3: 4, 5: 2},
            "EC23413": {3: 2, 4: 4},
            "EC23431": {0: 1, 1: 5},
            "MA23436": {1: 1, 2: 5},
        }

        required_courses = set(fixed_group_counts.keys())
        present_courses = set(self.unique_courses)
        if present_courses != required_courses:
            missing = sorted(required_courses - present_courses)
            extra = sorted(present_courses - required_courses)
            raise ValueError(
                "ECE S4 fixed grouping requires exactly these courses after filtering: "
                f"{sorted(required_courses)}. Missing={missing}, Extra={extra}."
            )

        constraints_added = 0
        for course_code, group_targets in fixed_group_counts.items():
            allowed_groups = set(group_targets.keys())
            instance_indices = [
                i
                for i, inst in enumerate(self.courses)
                if inst.get("course_code") == course_code
            ]

            expected_total = sum(group_targets.values())
            if len(instance_indices) != expected_total:
                raise ValueError(
                    f"ECE S4 fixed grouping: {course_code} has {len(instance_indices)} instances "
                    f"(expected {expected_total})."
                )

            for instance_idx in instance_indices:
                for group_idx in range(self.num_groups):
                    if group_idx in allowed_groups:
                        continue
                    model.Add(assignment_vars[(instance_idx, group_idx)] == 0)
                    constraints_added += 1

            for group_idx, target in group_targets.items():
                group_count = model.NewIntVar(
                    0,
                    len(instance_indices),
                    f"ece_s4_{course_code}_count_g{group_idx}",
                )
                model.Add(group_count == sum(assignment_vars[(i, group_idx)] for i in instance_indices))
                constraints_added += 1
                model.Add(group_count == target)
                constraints_added += 1

        return constraints_added

    def _apply_mech_s4_fixed_grouping(self, model, assignment_vars):
        """Force Mechanical Engineering S4 to use a fixed course->group mapping (STRICT)."""
        if self.num_groups < 8:
            self.logger.warning(
                "Skipping Mechanical S4 fixed grouping: expected >= 8 groups, got %s",
                self.num_groups,
            )
            return 0

        self.logger.info("Applying Mechanical Engineering S4 fixed group mapping")

        fixed_group_counts = {
            # G1..G8 => 0..7
            "ME23411": {6: 1, 7: 1},
            "ME23412": {6: 1, 7: 1},
            "ME23421": {2: 1, 5: 1},
            "ME23422": {3: 1, 5: 1},
            "ME23431": {1: 1, 4: 1},
            "ME23432": {0: 1, 1: 1},
            "ME23433": {0: 1, 4: 1},
            "ME23VAP2": {2: 1, 3: 1},
        }

        required_courses = set(fixed_group_counts.keys())
        present_courses = set(self.unique_courses)
        if present_courses != required_courses:
            missing = sorted(required_courses - present_courses)
            extra = sorted(present_courses - required_courses)
            raise ValueError(
                "Mechanical S4 fixed grouping requires exactly these courses after filtering: "
                f"{sorted(required_courses)}. Missing={missing}, Extra={extra}."
            )

        constraints_added = 0
        for course_code, group_targets in fixed_group_counts.items():
            allowed_groups = set(group_targets.keys())
            instance_indices = [
                i
                for i, inst in enumerate(self.courses)
                if inst.get("course_code") == course_code
            ]

            expected_total = sum(group_targets.values())
            if len(instance_indices) != expected_total:
                raise ValueError(
                    f"Mechanical S4 fixed grouping: {course_code} has {len(instance_indices)} instances "
                    f"(expected {expected_total})."
                )

            for instance_idx in instance_indices:
                for group_idx in range(self.num_groups):
                    if group_idx in allowed_groups:
                        continue
                    model.Add(assignment_vars[(instance_idx, group_idx)] == 0)
                    constraints_added += 1

            for group_idx, target in group_targets.items():
                group_count = model.NewIntVar(
                    0,
                    len(instance_indices),
                    f"mech_s4_{course_code}_count_g{group_idx}",
                )
                model.Add(group_count == sum(assignment_vars[(i, group_idx)] for i in instance_indices))
                constraints_added += 1
                model.Add(group_count == target)
                constraints_added += 1

        return constraints_added

    def _apply_cse_s4_fixed_grouping(self, model, assignment_vars):
        """Force CSE S4 to use a fixed course->group mapping.

        This encodes the exact distribution from the curated summary provided by the user.
        Groups are 0-indexed internally (G1 -> 0, ...).

        This mapping is enforced STRICTLY:
        - The optimizer must see exactly these 5 courses (after preprocessing/filtering).
        - Each course must have the expected number of instances (teacher-assignments).
        """
        if self.num_groups < 5:
            self.logger.warning(
                "Skipping CSE S4 fixed grouping: expected >= 5 groups, got %s",
                self.num_groups,
            )
            return 0

        self.logger.info("Applying CSE S4 fixed group mapping")

        # Fixed mapping based on the curated summary.
        # Values are the exact number of instances (teacher-assignments) per group.
        fixed_group_counts = {
            # G1..G5 => 0..4
            "CS23431": {1: 4, 2: 4},
            "CS23432": {2: 5, 3: 4},
            "CS23PE01": {4: 9},
            "GE23627": {0: 4, 1: 4},
            "MA23435": {0: 5, 3: 5},
        }

        required_courses = set(fixed_group_counts.keys())
        present_courses = set(self.unique_courses)
        if present_courses != required_courses:
            missing = sorted(required_courses - present_courses)
            extra = sorted(present_courses - required_courses)
            raise ValueError(
                "CSE S4 fixed grouping requires exactly these courses after filtering: "
                f"{sorted(required_courses)}. Missing={missing}, Extra={extra}."
            )

        constraints_added = 0

        for course_code, group_targets in fixed_group_counts.items():
            allowed_groups = set(group_targets.keys())
            instance_indices = [
                i
                for i, inst in enumerate(self.courses)
                if inst.get("course_code") == course_code
            ]

            expected_total = sum(group_targets.values())
            if len(instance_indices) != expected_total:
                raise ValueError(
                    f"CSE S4 fixed grouping: {course_code} has {len(instance_indices)} instances "
                    f"(expected {expected_total})."
                )

            # 1) Forbid assignments outside the allowed groups.
            for instance_idx in instance_indices:
                for group_idx in range(self.num_groups):
                    if group_idx in allowed_groups:
                        continue
                    model.Add(assignment_vars[(instance_idx, group_idx)] == 0)
                    constraints_added += 1

            # 2) Enforce exact per-group counts.
            for group_idx, target in group_targets.items():
                group_count = model.NewIntVar(
                    0,
                    len(instance_indices),
                    f"cse_s4_{course_code}_count_g{group_idx}",
                )
                model.Add(group_count == sum(assignment_vars[(i, group_idx)] for i in instance_indices))
                constraints_added += 1
                model.Add(group_count == target)
                constraints_added += 1

        return constraints_added

    def _apply_biotech_s4_fixed_grouping(self, model, assignment_vars):
        """Force Biotechnology S4 to use a fixed course->group mapping.

        This encodes the expected two-group placement per course from the
        curated summary (G1..G8). Groups are 0-indexed internally.
        """
        if self.num_groups < 8:
            self.logger.warning(
                "Skipping Biotechnology S4 fixed grouping: expected >= 8 groups, got %s",
                self.num_groups,
            )
            return 0

        self.logger.info("Applying Biotechnology S4 fixed group mapping")

        # Fixed mapping based on the curated summary.
        # Groups are 0-indexed here (G1 -> 0 ... G8 -> 7).
        # Values are the exact number of instances (teacher-assignments) per group.
        fixed_group_counts = {
            # G1/G2
            "CS23422": {0: 1, 1: 2},
            "MA23431": {0: 2, 1: 1},
            # G3/G4
            "BT23421": {2: 2, 3: 1},
            "BT23422": {2: 1, 3: 2},
            # G5/G6/G7/G8
            "BT23413": {4: 2, 5: 1},
            "BT23414": {4: 1, 7: 2},
            "BT23411": {5: 2, 6: 1},
            "BT23412": {6: 2, 7: 1},
        }

        constraints_added = 0

        for course_code, group_targets in fixed_group_counts.items():
            allowed_groups = set(group_targets.keys())
            instance_indices = [
                i for i, inst in enumerate(self.courses)
                if inst.get("course_code") == course_code
            ]

            if not instance_indices:
                self.logger.warning(
                    "Biotechnology S4 fixed grouping: no instances found for %s",
                    course_code,
                )
                continue

            # 1) Forbid assignments outside the allowed groups.
            for instance_idx in instance_indices:
                for group_idx in range(self.num_groups):
                    if group_idx in allowed_groups:
                        continue
                    model.Add(assignment_vars[(instance_idx, group_idx)] == 0)
                    constraints_added += 1

            # 2) Enforce exact per-group counts (the 2/1 split).
            # If the input data no longer has the expected total instances, fall back to
            # "present in each allowed group" to avoid infeasibility.
            expected_total = sum(group_targets.values())
            if len(instance_indices) != expected_total:
                self.logger.warning(
                    "Biotechnology S4 fixed grouping: %s has %s instances (expected %s). "
                    "Falling back to presence-only constraints.",
                    course_code,
                    len(instance_indices),
                    expected_total,
                )

                for group_idx in sorted(allowed_groups):
                    group_count = model.NewIntVar(
                        0,
                        len(instance_indices),
                        f"biotech_s4_{course_code}_count_g{group_idx}",
                    )
                    model.Add(group_count == sum(assignment_vars[(i, group_idx)] for i in instance_indices))
                    constraints_added += 1
                    model.Add(group_count >= 1)
                    constraints_added += 1
            else:
                for group_idx, target in group_targets.items():
                    group_count = model.NewIntVar(
                        0,
                        len(instance_indices),
                        f"biotech_s4_{course_code}_count_g{group_idx}",
                    )
                    model.Add(group_count == sum(assignment_vars[(i, group_idx)] for i in instance_indices))
                    constraints_added += 1
                    model.Add(group_count == target)
                    constraints_added += 1

        return constraints_added

    def _apply_ece_s2_even_core_split(self, model, assignment_vars):
        """Ensure GE23121 and EE23132 split evenly across the two groups (as balanced as possible)."""
        self.logger.info("Applying ECE S2 special constraint: even split for GE23121 and EE23132")
        constraints_added = 0

        target_courses = {"GE23121", "EE23132"}

        for course_code in target_courses:
            # Collect all instances for this course
            instance_indices = [
                i for i, inst in enumerate(self.courses)
                if inst.get('course_code') == course_code
            ]

            num_instances = len(instance_indices)
            if num_instances == 0:
                continue

            # Track presence and counts per group
            group_has_course = []
            group_instance_counts = []

            for group_idx in range(self.num_groups):
                group_var = model.NewBoolVar(f"ece_s2_{course_code}_in_group_{group_idx}")
                group_has_course.append(group_var)

                group_count = model.NewIntVar(0, num_instances, f"ece_s2_{course_code}_count_group_{group_idx}")
                group_instance_counts.append(group_count)

                course_assignments_in_group = [assignment_vars[(i, group_idx)] for i in instance_indices]
                model.Add(group_count == sum(course_assignments_in_group))

                for instance_idx in instance_indices:
                    model.Add(group_var >= assignment_vars[(instance_idx, group_idx)])
                model.Add(group_var <= sum(course_assignments_in_group))

                constraints_added += 3

            # Even split logic: target half each if even, otherwise difference <= 1
            if num_instances % 2 == 0:
                target_per_group = num_instances // 2
                for g1 in range(self.num_groups):
                    for g2 in range(g1 + 1, self.num_groups):
                        both_have_course = model.NewBoolVar(f"ece_s2_{course_code}_in_both_g{g1}_g{g2}")

                        model.Add(both_have_course <= group_has_course[g1])
                        model.Add(both_have_course <= group_has_course[g2])
                        model.Add(both_have_course >= group_has_course[g1] + group_has_course[g2] - 1)

                        model.Add(group_instance_counts[g1] == target_per_group).OnlyEnforceIf(both_have_course)
                        model.Add(group_instance_counts[g2] == target_per_group).OnlyEnforceIf(both_have_course)

                        constraints_added += 5

                self.logger.info(f"  {course_code}: enforcing {target_per_group} instances per group (even split)")
            else:
                target_low = num_instances // 2
                target_high = target_low + 1

                for g1 in range(self.num_groups):
                    for g2 in range(g1 + 1, self.num_groups):
                        both_have_course = model.NewBoolVar(f"ece_s2_{course_code}_in_both_g{g1}_g{g2}")

                        model.Add(both_have_course <= group_has_course[g1])
                        model.Add(both_have_course <= group_has_course[g2])
                        model.Add(both_have_course >= group_has_course[g1] + group_has_course[g2] - 1)

                        g1_valid = model.NewBoolVar(f"ece_s2_{course_code}_g{g1}_valid")
                        g2_valid = model.NewBoolVar(f"ece_s2_{course_code}_g{g2}_valid")

                        model.Add(group_instance_counts[g1] >= target_low).OnlyEnforceIf([both_have_course, g1_valid])
                        model.Add(group_instance_counts[g1] <= target_high).OnlyEnforceIf([both_have_course, g1_valid])

                        model.Add(group_instance_counts[g2] >= target_low).OnlyEnforceIf([both_have_course, g2_valid])
                        model.Add(group_instance_counts[g2] <= target_high).OnlyEnforceIf([both_have_course, g2_valid])

                        model.Add(g1_valid == 1).OnlyEnforceIf(both_have_course)
                        model.Add(g2_valid == 1).OnlyEnforceIf(both_have_course)

                        constraints_added += 9

                self.logger.info(f"  {course_code}: enforcing {target_low}-{target_high} instances per group (balanced split)")

        return constraints_added

    def _apply_cse_s2_five_group_split(self, model, assignment_vars):
        """CSE Semester 2: force every course to span 5 groups (balanced) when possible.

        Rules per course (based on number of input instances):
        - 1 instance  -> exactly 1 group
        - 2 instances -> exactly 2 groups (1+1)
        - 3 instances -> exactly 3 groups (1+1+1)
        - 4 instances -> exactly 4 groups (1+1+1+1)
        - >=5         -> exactly 5 groups, balanced as evenly as possible
        """
        self.logger.info("Applying CSE S2 special constraint: each course split across 5 groups (balanced)")
        constraints_added = 0

        if self.num_groups < 5:
            self.logger.warning(
                "CSE S2 5-group split requested, but only %s groups exist; using <=num_groups where needed",
                self.num_groups,
            )

        for course_code in self.unique_courses:
            instance_indices = [
                i for i, inst in enumerate(self.courses)
                if inst.get('course_code') == course_code
            ]
            num_instances = len(instance_indices)
            if num_instances == 0:
                continue

            if num_instances >= 5 and self.num_groups >= 5:
                k = 5
            else:
                k = min(num_instances, self.num_groups)

            group_has_course = []
            group_instance_counts = []

            for group_idx in range(self.num_groups):
                group_var = model.NewBoolVar(f"cse_s2_{course_code}_in_group_{group_idx}")
                group_has_course.append(group_var)

                group_count = model.NewIntVar(0, num_instances, f"cse_s2_{course_code}_count_group_{group_idx}")
                group_instance_counts.append(group_count)

                course_assignments_in_group = [assignment_vars[(i, group_idx)] for i in instance_indices]
                model.Add(group_count == sum(course_assignments_in_group))

                for instance_idx in instance_indices:
                    model.Add(group_var >= assignment_vars[(instance_idx, group_idx)])
                model.Add(group_var <= sum(course_assignments_in_group))

                constraints_added += 3

            # Exactly k groups should carry this course
            model.Add(sum(group_has_course) == k)
            constraints_added += 1

            low = num_instances // k
            high = (num_instances + k - 1) // k  # ceil

            for group_idx in range(self.num_groups):
                model.Add(group_instance_counts[group_idx] >= low).OnlyEnforceIf(group_has_course[group_idx])
                model.Add(group_instance_counts[group_idx] <= high).OnlyEnforceIf(group_has_course[group_idx])
                model.Add(group_instance_counts[group_idx] == 0).OnlyEnforceIf(group_has_course[group_idx].Not())
                constraints_added += 3

        return constraints_added
    
    def _apply_ece_s7_even_lab_distribution(self, model, assignment_vars):
        """
        Special constraint for ECE 7th semester: ensure even distribution of lab course instances.
        
        For courses with practical hours > 0 and multiple instances, ensure that instances
        are distributed evenly across the groups they appear in.
        
        Args:
            model: CP-SAT model
            assignment_vars: Assignment variables
            
        Returns:
            int: Number of constraints added
        """
        self.logger.info("Applying ECE S7 special constraint: even lab distribution")
        constraints_added = 0
        
        # Identify lab courses with multiple instances
        lab_courses_multi_instance = {}
        for course in self.courses:
            if course.get('practical_hours', 0) > 0:
                course_code = course['course_code']
                if course_code not in lab_courses_multi_instance:
                    lab_courses_multi_instance[course_code] = []
                lab_courses_multi_instance[course_code].append(course)
        
        # Filter to only courses with multiple instances
        lab_courses_multi_instance = {
            course_code: instances 
            for course_code, instances in lab_courses_multi_instance.items() 
            if len(instances) > 1
        }
        
        if not lab_courses_multi_instance:
            self.logger.info("No multi-instance lab courses found for ECE S7 even distribution constraint")
            return 0
        
        self.logger.info(f"Applying even distribution to {len(lab_courses_multi_instance)} lab courses:")
        for course_code, instances in lab_courses_multi_instance.items():
            self.logger.info(f"  {course_code}: {len(instances)} instances")
        
        # For each multi-instance lab course, ensure even distribution
        for course_code, course_instances in lab_courses_multi_instance.items():
            num_instances = len(course_instances)
            instance_indices = [
                i for i, inst in enumerate(self.courses) 
                if inst['course_code'] == course_code and inst.get('practical_hours', 0) > 0
            ]
            
            # Since course limit constraint forces multi-instance courses into exactly 2 groups,
            # we need to ensure even distribution across those 2 groups
            
            # Create auxiliary variables to track which groups have this course
            group_has_course = []
            group_instance_counts = []
            
            for group_idx in range(self.num_groups):
                # Track if this group has any instance of this course
                group_var = model.NewBoolVar(f"ece_s7_{course_code}_in_group_{group_idx}")
                group_has_course.append(group_var)
                
                # Count instances of this course in this group
                group_count = model.NewIntVar(0, num_instances, f"ece_s7_{course_code}_count_group_{group_idx}")
                group_instance_counts.append(group_count)
                
                # Link count to actual assignments
                course_assignments_in_group = [assignment_vars[(i, group_idx)] for i in instance_indices]
                model.Add(group_count == sum(course_assignments_in_group))
                
                # Link group_has_course to assignments
                for instance_idx in instance_indices:
                    model.Add(group_var >= assignment_vars[(instance_idx, group_idx)])
                model.Add(group_var <= sum(course_assignments_in_group))
                
                constraints_added += 3
            
            # Constraint: Course must be in exactly 2 groups (enforced by course limit constraint)
            # Additional constraint: Even distribution across those 2 groups
            
            # If course has even number of instances, each group should have exactly half
            if num_instances % 2 == 0:
                target_per_group = num_instances // 2
                
                # For each pair of groups that could contain this course, if both contain it,
                # they must have equal instances
                for g1 in range(self.num_groups):
                    for g2 in range(g1 + 1, self.num_groups):
                        # If both groups have this course, they must have equal counts
                        both_have_course = model.NewBoolVar(f"ece_s7_{course_code}_in_both_g{g1}_g{g2}")
                        
                        # both_have_course is true iff both groups have the course
                        model.Add(both_have_course <= group_has_course[g1])
                        model.Add(both_have_course <= group_has_course[g2])
                        model.Add(both_have_course >= group_has_course[g1] + group_has_course[g2] - 1)
                        
                        # If both have the course, they must have equal instances (target_per_group each)
                        model.Add(group_instance_counts[g1] == target_per_group).OnlyEnforceIf(both_have_course)
                        model.Add(group_instance_counts[g2] == target_per_group).OnlyEnforceIf(both_have_course)
                        
                        constraints_added += 5
                
                self.logger.info(f"  {course_code}: enforcing {target_per_group} instances per group (even split)")
                
            else:
                # Odd number of instances: as even as possible (difference of at most 1)
                target_low = num_instances // 2
                target_high = target_low + 1
                
                for g1 in range(self.num_groups):
                    for g2 in range(g1 + 1, self.num_groups):
                        # If both groups have this course, difference should be at most 1
                        both_have_course = model.NewBoolVar(f"ece_s7_{course_code}_in_both_g{g1}_g{g2}")
                        
                        model.Add(both_have_course <= group_has_course[g1])
                        model.Add(both_have_course <= group_has_course[g2])
                        model.Add(both_have_course >= group_has_course[g1] + group_has_course[g2] - 1)
                        
                        # If both have the course, each must have target_low or target_high instances
                        g1_valid = model.NewBoolVar(f"ece_s7_{course_code}_g{g1}_valid")
                        g2_valid = model.NewBoolVar(f"ece_s7_{course_code}_g{g2}_valid")
                        
                        # g1 is valid if it has target_low or target_high instances
                        model.Add(group_instance_counts[g1] >= target_low).OnlyEnforceIf([both_have_course, g1_valid])
                        model.Add(group_instance_counts[g1] <= target_high).OnlyEnforceIf([both_have_course, g1_valid])
                        
                        # g2 is valid if it has target_low or target_high instances  
                        model.Add(group_instance_counts[g2] >= target_low).OnlyEnforceIf([both_have_course, g2_valid])
                        model.Add(group_instance_counts[g2] <= target_high).OnlyEnforceIf([both_have_course, g2_valid])
                        
                        # If both groups have the course, both must be valid
                        model.Add(g1_valid == 1).OnlyEnforceIf(both_have_course)
                        model.Add(g2_valid == 1).OnlyEnforceIf(both_have_course)
                        
                        constraints_added += 9
                
                self.logger.info(f"  {course_code}: enforcing {target_low}-{target_high} instances per group (balanced split)")
        
        self.logger.info(f"Applied {constraints_added} ECE S7 even lab distribution constraints")
        return constraints_added
    
    def _apply_ece_s5_even_lab_distribution(self, model, assignment_vars):
        """
        Special constraint for ECE 5th semester: ensure even distribution of lab course instances.
        
        For courses with practical hours > 0 and multiple instances, ensure that instances
        are distributed evenly across the groups they appear in.
        
        Args:
            model: CP-SAT model
            assignment_vars: Assignment variables
            
        Returns:
            int: Number of constraints added
        """
        self.logger.info("Applying ECE S5 special constraint: even lab distribution")
        constraints_added = 0
        
        # Identify lab courses with multiple instances
        lab_courses_multi_instance = {}
        for course in self.courses:
            if course.get('practical_hours', 0) > 0:
                course_code = course['course_code']
                if course_code not in lab_courses_multi_instance:
                    lab_courses_multi_instance[course_code] = []
                lab_courses_multi_instance[course_code].append(course)
        
        # Filter to only courses with multiple instances
        lab_courses_multi_instance = {
            course_code: instances 
            for course_code, instances in lab_courses_multi_instance.items() 
            if len(instances) > 1
        }
        
        if not lab_courses_multi_instance:
            self.logger.info("No multi-instance lab courses found for ECE S5 even distribution constraint")
            return 0
        
        self.logger.info(f"Applying even distribution to {len(lab_courses_multi_instance)} lab courses:")
        for course_code, instances in lab_courses_multi_instance.items():
            self.logger.info(f"  {course_code}: {len(instances)} instances")
        
        # For each multi-instance lab course, ensure even distribution
        for course_code, course_instances in lab_courses_multi_instance.items():
            num_instances = len(course_instances)
            instance_indices = [
                i for i, inst in enumerate(self.courses) 
                if inst['course_code'] == course_code and inst.get('practical_hours', 0) > 0
            ]
            
            # Since course limit constraint forces multi-instance courses into exactly 2 groups,
            # we need to ensure even distribution across those 2 groups
            
            # Create auxiliary variables to track which groups have this course
            group_has_course = []
            group_instance_counts = []
            
            for group_idx in range(self.num_groups):
                # Track if this group has any instance of this course
                group_var = model.NewBoolVar(f"ece_s5_{course_code}_in_group_{group_idx}")
                group_has_course.append(group_var)
                
                # Count instances of this course in this group
                group_count = model.NewIntVar(0, num_instances, f"ece_s5_{course_code}_count_group_{group_idx}")
                group_instance_counts.append(group_count)
                
                # Link count to actual assignments
                course_assignments_in_group = [assignment_vars[(i, group_idx)] for i in instance_indices]
                model.Add(group_count == sum(course_assignments_in_group))
                
                # Link group_has_course to assignments
                for instance_idx in instance_indices:
                    model.Add(group_var >= assignment_vars[(instance_idx, group_idx)])
                model.Add(group_var <= sum(course_assignments_in_group))
                
                constraints_added += 3
            
            # Constraint: Course must be in exactly 2 groups (enforced by course limit constraint)
            # Additional constraint: Even distribution across those 2 groups
            
            # If course has even number of instances, each group should have exactly half
            if num_instances % 2 == 0:
                target_per_group = num_instances // 2
                
                # For each pair of groups that could contain this course, if both contain it,
                # they must have equal instances
                for g1 in range(self.num_groups):
                    for g2 in range(g1 + 1, self.num_groups):
                        # If both groups have this course, they must have equal counts
                        both_have_course = model.NewBoolVar(f"ece_s5_{course_code}_in_both_g{g1}_g{g2}")
                        
                        # both_have_course is true iff both groups have the course
                        model.Add(both_have_course <= group_has_course[g1])
                        model.Add(both_have_course <= group_has_course[g2])
                        model.Add(both_have_course >= group_has_course[g1] + group_has_course[g2] - 1)
                        
                        # If both have the course, they must have equal instances (target_per_group each)
                        model.Add(group_instance_counts[g1] == target_per_group).OnlyEnforceIf(both_have_course)
                        model.Add(group_instance_counts[g2] == target_per_group).OnlyEnforceIf(both_have_course)
                        
                        constraints_added += 5
                
                self.logger.info(f"  {course_code}: enforcing {target_per_group} instances per group (even split)")
                
            else:
                # Odd number of instances: as even as possible (difference of at most 1)
                target_low = num_instances // 2
                target_high = target_low + 1
                
                for g1 in range(self.num_groups):
                    for g2 in range(g1 + 1, self.num_groups):
                        # If both groups have this course, difference should be at most 1
                        both_have_course = model.NewBoolVar(f"ece_s5_{course_code}_in_both_g{g1}_g{g2}")
                        
                        model.Add(both_have_course <= group_has_course[g1])
                        model.Add(both_have_course <= group_has_course[g2])
                        model.Add(both_have_course >= group_has_course[g1] + group_has_course[g2] - 1)
                        
                        # If both have the course, each must have target_low or target_high instances
                        g1_valid = model.NewBoolVar(f"ece_s5_{course_code}_g{g1}_valid")
                        g2_valid = model.NewBoolVar(f"ece_s5_{course_code}_g{g2}_valid")
                        
                        # g1 is valid if it has target_low or target_high instances
                        model.Add(group_instance_counts[g1] >= target_low).OnlyEnforceIf([both_have_course, g1_valid])
                        model.Add(group_instance_counts[g1] <= target_high).OnlyEnforceIf([both_have_course, g1_valid])
                        
                        # g2 is valid if it has target_low or target_high instances  
                        model.Add(group_instance_counts[g2] >= target_low).OnlyEnforceIf([both_have_course, g2_valid])
                        model.Add(group_instance_counts[g2] <= target_high).OnlyEnforceIf([both_have_course, g2_valid])
                        
                        # If both groups have the course, both must be valid
                        model.Add(g1_valid == 1).OnlyEnforceIf(both_have_course)
                        model.Add(g2_valid == 1).OnlyEnforceIf(both_have_course)
                        
                        constraints_added += 9
                
                self.logger.info(f"  {course_code}: enforcing {target_low}-{target_high} instances per group (balanced split)")
        
        self.logger.info(f"Applied {constraints_added} ECE S5 even lab distribution constraints")
        return constraints_added
    
    def _set_optimization_objectives(self, model, assignment_vars):
        """
        Set optimization objectives. This now includes a primary objective to
        minimize the variance in total hours within each group to improve
        room utilization.
        
        Args:
            model: CP-SAT model
            assignment_vars: Assignment variables
        """
        self.logger.info("Setting optimization objectives...")

        # Consolidation policy: prioritize consolidating each course into as few groups
        # as possible (ideally 1) while satisfying all hard constraints.
        if getattr(self, "consolidation_objective_enabled", False):
            consolidation_terms = []
            for course_code, group_vars in (self._course_group_presence_vars or {}).items():
                if group_vars:
                    consolidation_terms.append(sum(group_vars))

            if consolidation_terms:
                model.Minimize(sum(consolidation_terms))
                self.logger.info("Primary Objective: Minimize number of groups each course spans")
                return
            else:
                # No multi-instance courses detected; fall back to variance objective.
                self.logger.info("No multi-instance courses found for consolidation objective; falling back")
        
        # Objective 1: Minimize workload variance within each group (primary objective)
        # This encourages forming groups with courses that have similar total hours,
        # which is the key to reducing underutilized room-slots.
        
        total_variance_terms = []
        
        for group_idx in range(self.num_groups):
            # Simplified approach: minimize the range (max - min) of hours within each group
            # This is easier to implement in OR-Tools and achieves similar results
            
            # Get all possible hour values in the dataset
            all_hour_values = []
            for instance in self.courses:
                total_hours = instance.get('lecture_hours', 0) + instance.get('tutorial_hours', 0)
                if total_hours not in all_hour_values:
                    all_hour_values.append(total_hours)
            
            all_hour_values.sort()
            
            # For each group, create variables to track min and max hours
            group_min_hours = model.NewIntVar(0, max(all_hour_values), f'group_{group_idx}_min_hours')
            group_max_hours = model.NewIntVar(0, max(all_hour_values), f'group_{group_idx}_max_hours')
            
            # Create indicator variables for each possible hour value being present in the group
            hour_present = {}
            for hour_val in all_hour_values:
                hour_present[hour_val] = model.NewBoolVar(f'group_{group_idx}_has_{hour_val}_hours')
                
                # This hour is present if any instance with this hour count is assigned to this group
                instances_with_this_hour = []
                for i, instance in enumerate(self.courses):
                    instance_hours = instance.get('lecture_hours', 0) + instance.get('tutorial_hours', 0)
                    if instance_hours == hour_val:
                        instances_with_this_hour.append(assignment_vars[(i, group_idx)])
                
                if instances_with_this_hour:
                    # hour_present[hour_val] is 1 if any instance with hour_val is in this group
                    model.Add(hour_present[hour_val] <= sum(instances_with_this_hour))
                    for var in instances_with_this_hour:
                        model.Add(hour_present[hour_val] >= var)
                else:
                    # No instances with this hour value, so it can't be present
                    model.Add(hour_present[hour_val] == 0)
            
            # Set min_hours to the smallest hour value present in the group
            for hour_val in all_hour_values:
                # If this hour is present, min_hours must be <= hour_val
                model.Add(group_min_hours <= hour_val).OnlyEnforceIf(hour_present[hour_val])
                
                # If all smaller hours are absent and this hour is present, min_hours = hour_val
                smaller_hours_absent = []
                for smaller_hour in all_hour_values:
                    if smaller_hour < hour_val:
                        smaller_hours_absent.append(hour_present[smaller_hour].Not())
                
                if smaller_hours_absent:
                    model.Add(group_min_hours == hour_val).OnlyEnforceIf(
                        [hour_present[hour_val]] + smaller_hours_absent
                    )
                elif hour_val == min(all_hour_values):
                    model.Add(group_min_hours == hour_val).OnlyEnforceIf(hour_present[hour_val])
            
            # Set max_hours to the largest hour value present in the group
            for hour_val in all_hour_values:
                # If this hour is present, max_hours must be >= hour_val
                model.Add(group_max_hours >= hour_val).OnlyEnforceIf(hour_present[hour_val])
                
                # If all larger hours are absent and this hour is present, max_hours = hour_val
                larger_hours_absent = []
                for larger_hour in all_hour_values:
                    if larger_hour > hour_val:
                        larger_hours_absent.append(hour_present[larger_hour].Not())
                
                if larger_hours_absent:
                    model.Add(group_max_hours == hour_val).OnlyEnforceIf(
                        [hour_present[hour_val]] + larger_hours_absent
                    )
                elif hour_val == max(all_hour_values):
                    model.Add(group_max_hours == hour_val).OnlyEnforceIf(hour_present[hour_val])
            
            # The range for this group (what we want to minimize)
            group_range = model.NewIntVar(0, max(all_hour_values), f'group_{group_idx}_range')
            model.Add(group_range == group_max_hours - group_min_hours)
            
            total_variance_terms.append(group_range)

        # The model will try to make the sum of all group variances as small as possible.
        model.Minimize(sum(total_variance_terms))
        self.logger.info("Primary Objective: Minimize workload variance within groups to improve room utilization.")

    def _solve_model(self, model, assignment_vars):
        """
        Solve the optimization model.
        
        Args:
            model: CP-SAT model
            assignment_vars: Assignment variables
            
        Returns:
            bool: True if solution found, False otherwise
        """
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 300  # 5 minutes timeout
        
        self.logger.info("Starting CP-SAT solver...")
        status = solver.Solve(model)
        
        if status == cp_model.OPTIMAL:
            self.logger.info("OPTIMAL solution found!")
            self.solution_found = True
        elif status == cp_model.FEASIBLE:
            self.logger.info("FEASIBLE solution found!")
            self.solution_found = True
        else:
            self.logger.error(f"No solution found. Status: {solver.StatusName(status)}")
            return False
        
        # Extract solution
        self._extract_solution(solver, assignment_vars)
        
        # Log solver statistics
        self.logger.info(f"Solver statistics:")
        self.logger.info(f"  Status: {solver.StatusName(status)}")
        self.logger.info(f"  Objective value: {solver.ObjectiveValue()}")
        self.logger.info(f"  Solve time: {solver.WallTime():.2f} seconds")
        self.logger.info(f"  Branches: {solver.NumBranches()}")
        self.logger.info(f"  Conflicts: {solver.NumConflicts()}")
        
        self.objective_value = solver.ObjectiveValue()
        return True
    
    def _extract_solution(self, solver, assignment_vars):
        """Extract the solution from the solver and append PE courses.

        Regular (non-PE) courses are assigned by the CP-SAT solver into
        `self.num_groups` groups.

        PE courses are not part of the optimization cohort (they are separated
        up-front). They are appended after the regular groups.

        Note: PE courses are appended as *one group per PE general code*
        (course_code), so that different PE general codes do not end up
        in the same group.
        """
        # Initialize groups
        self.groups = [[] for _ in range(self.num_groups)]
        
        # Extract assignments
        for i, instance in enumerate(self.courses):
            for group_idx in range(self.num_groups):
                if solver.Value(assignment_vars[(i, group_idx)]) == 1:
                    self.groups[group_idx].append(instance)
                    break
        
        # Add PE courses after the optimized groups.
        # Keep each PE general code as its own group.
        if self.pe_courses:
            pe_groups_by_code = defaultdict(list)
            for inst in self.pe_courses:
                pe_groups_by_code[inst.get('course_code')].append(inst)

            for pe_code in sorted(k for k in pe_groups_by_code.keys() if k):
                self.groups.append(pe_groups_by_code[pe_code])

            self.logger.debug(
                f"Added {len(pe_groups_by_code)} PE groups after optimization "
                f"(one per PE course_code): {sorted(pe_groups_by_code.keys())}"
            )
        
        # Log group distribution
        self.logger.info(f"Optimal group distribution for {self.dept} Semester {self.semester}:")
        
        course_distribution = defaultdict(list)
        
        for group_idx, group in enumerate(self.groups):
            if group:  # Only show non-empty groups
                teachers = sorted(set(str(inst['teacher_id']) for inst in group))
                courses = sorted(set(inst['course_code'] for inst in group))
                lab_instances = [inst for inst in group if inst.get('has_lab', False)]
                theory_instances = [inst for inst in group if inst.get('has_theory', False)]
                
                # Check if this is the PE group
                is_pe_group = group_idx >= self.num_groups
                
                # Track course distribution (excluding PE courses from regular analysis)
                if not is_pe_group:
                    for course_code in courses:
                        course_distribution[course_code].append(group_idx + 1)
                
                total_workload = sum(
                    inst.get('practical_hours', 0) + 
                    inst.get('lecture_hours', 0) + 
                    inst.get('tutorial_hours', 0)
                    for inst in group
                )
                
                group_type = " (PE Group)" if is_pe_group else ""
                self.logger.info(f"  Group {group_idx + 1}{group_type}: {len(group)} instances")
                self.logger.info(f"    Lab: {len(lab_instances)}, Theory: {len(theory_instances)}")
                self.logger.info(f"    Teachers: [{', '.join(teachers)}]")
                self.logger.info(f"    Courses: [{', '.join(courses)}]")
                self.logger.info(f"    Total workload: {total_workload} hours")
        
        # Log course distribution summary (excluding PE courses)
        self.logger.info(f"\nCourse distribution summary (excluding PE courses):")
        total_courses = len(course_distribution)
        courses_with_choice = 0

        instance_counts = Counter(inst["course_code"] for inst in self.courses)
        
        for course_code, group_list in sorted(course_distribution.items()):
            if len(group_list) > 1:
                courses_with_choice += 1
            group_names = [f"G{g}" for g in group_list]

            if getattr(self, "is_cse_s2", False):
                # CSE S2 special case: use up to 5 groups, bounded by available instances/groups.
                num_instances = instance_counts.get(course_code, 0)
                expected_groups = 5 if (num_instances >= 5 and self.num_groups >= 5) else min(num_instances, self.num_groups)
                status = "[OK]" if len(group_list) == expected_groups else "[ERROR]"
            else:
                status = "[OK]" if len(group_list) <= 2 else "[ERROR]"
            self.logger.info(f"  {course_code}: {', '.join(group_names)} ({len(group_list)} groups) {status}")
        
        choice_percentage = (courses_with_choice / total_courses * 100) if total_courses > 0 else 0
        self.logger.info(f"\nStudent choice analysis (excluding PE courses):")
        self.logger.info(f"  Total regular courses: {total_courses}")
        self.logger.info(f"  Courses with multiple group options: {courses_with_choice}")
        self.logger.info(f"  Student choice percentage: {choice_percentage:.1f}%")
        
        # Log PE course information
        if self.pe_courses:
            pe_course_codes = sorted(set(inst['course_code'] for inst in self.pe_courses))
            pe_group_count = len(self.groups) - self.num_groups
            self.logger.debug(
                f"PE Course information: {len(pe_course_codes)} courses ({len(self.pe_courses)} instances) "
                f"across {pe_group_count} PE groups"
            )
    
    def validate_solution(self):
        """
        Validate the solution against all constraints.
        
        Returns:
            bool: True if solution is valid, False otherwise
        """
        if not self.solution_found:
            self.logger.error("No solution to validate")
            return False
        
        validation_passed = True
        
        # Validate teacher uniqueness
        if not self._validate_teacher_uniqueness():
            validation_passed = False
        
        # Validate course limits
        if not self._validate_course_limits():
            validation_passed = False
        
        # Validate assignment completeness
        if not self._validate_assignment_completeness():
            validation_passed = False
        
        # Validate group sizes
        if not self._validate_group_sizes():
            validation_passed = False
        
        # Validate lab priority
        if not self._validate_lab_priority():
            validation_passed = False
        
        if validation_passed:
            self.logger.info("[OK] All constraints satisfied in optimal solution")
        else:
            self.logger.error("[ERROR] Constraint violations found in solution")
        
        return validation_passed
    
    def _validate_teacher_uniqueness(self):
        """Validate teacher uniqueness constraint."""
        violations = 0
        
        for group_idx, group in enumerate(self.groups):
            # Check if this is the PE group
            is_pe_group = group_idx >= self.num_groups
            
            teacher_instance_map = defaultdict(list)
            
            for instance in group:
                teacher_instance_map[instance['teacher_id']].append(instance)
            
            for teacher_id, instances in teacher_instance_map.items():
                if len(instances) > 1:
                    # For PE groups, teacher uniqueness might be more relaxed
                    if is_pe_group:
                        # PE courses often have the same teacher for multiple instances/choices
                        # Only flag as violation if it's clearly a problem
                        pe_course_codes = set(inst['course_code'] for inst in instances)
                        if len(pe_course_codes) == 1:
                            # Same teacher for same PE course is acceptable (different sections)
                            self.logger.debug(f"PE Group {group_idx + 1}: Teacher {teacher_id} has {len(instances)} instances of same PE course {list(pe_course_codes)[0]} - acceptable")
                            continue
                    
                    # Check if this is a valid co-scheduling case
                    co_scheduled_pairs = 0
                    co_schedule_ids = [inst.get('co_scheduled_id') for inst in instances if 'co_scheduled_id' in inst]
                    
                    if len(co_schedule_ids) == 2 and co_schedule_ids[0] == co_schedule_ids[1]:
                        # This is a valid pair
                        co_scheduled_pairs = 1
                    
                    # A violation occurs if the number of instances exceeds the valid pairs
                    if len(instances) - co_scheduled_pairs > 1:
                        violations += 1
                        group_type = " (PE Group)" if is_pe_group else ""
                        self.logger.error(f"Teacher {teacher_id} appears {len(instances)} times in Group {group_idx + 1}{group_type}, but only {co_scheduled_pairs} co-scheduled pairs found.")

        if violations == 0:
            self.logger.info("[OK] Teacher uniqueness constraint satisfied")
            return True
        else:
            self.logger.error(f"[ERROR] {violations} teacher uniqueness violations")
            return False
    
    def _validate_course_limits(self):
        """
        Validate course limit constraints:
        - Single-instance courses: can be in 1 group
        - Multi-instance courses: 
          * Flexible departments: can be in 1-2 groups
          * Standard departments: must be in exactly 2 groups
        """
        violations = 0
        course_group_counts = defaultdict(set)
        course_instance_counts = defaultdict(int)
        
        # Count instances per course
        for course in self.courses:
            course_instance_counts[course['course_code']] += 1
        
        # Count groups per course
        for group_idx, group in enumerate(self.groups):
            for instance in group:
                course_group_counts[instance['course_code']].add(group_idx)
        
        for course_code, groups_set in course_group_counts.items():
            instance_count = course_instance_counts[course_code]
            group_count = len(groups_set)
            group_names = [f"G{g+1}" for g in sorted(groups_set)]

            # CSE S2 special case: expected group count depends on available instances/groups.
            # - 1 instance  -> 1 group
            # - 2 instances -> 2 groups
            # - 3 instances -> 3 groups
            # - 4 instances -> 4 groups
            # - >=5         -> 5 groups
            if self.is_cse_s2:
                expected = 5 if (instance_count >= 5 and self.num_groups >= 5) else min(instance_count, self.num_groups)
                if group_count != expected:
                    violations += 1
                    self.logger.error(
                        f"CSE S2 course {course_code} ({instance_count} instances) appears in {group_count} groups: {', '.join(group_names)} (should be in {expected} groups)"
                    )
                continue
            
            if instance_count == 1:
                # Single instance course: should be in exactly 1 group
                if group_count != 1:
                    violations += 1
                    self.logger.error(f"Single-instance course {course_code} appears in {group_count} groups: {', '.join(group_names)} (should be in 1 group)")
                else:
                    self.logger.debug(f"Single-instance course {course_code} correctly in 1 group: {group_names[0]}")
                    
            elif instance_count > 1:
                # Multi-instance course: validation depends on department flexibility
                if self.allows_flexible_grouping:
                    # Flexible departments: 1-2 groups allowed
                    if group_count < 1:
                        violations += 1
                        self.logger.error(f"Multi-instance course {course_code} ({instance_count} instances) appears in {group_count} groups: {', '.join(group_names)} (should be in 1-2 groups)")
                    elif group_count > 2:
                        violations += 1
                        self.logger.error(f"Multi-instance course {course_code} ({instance_count} instances) appears in {group_count} groups: {', '.join(group_names)} (should be in 1-2 groups)")
                    else:
                        if group_count == 1:
                            self.logger.debug(f"Multi-instance course {course_code} ({instance_count} instances) consolidated in 1 group: {group_names[0]} [FLEXIBLE]")
                        else:
                            self.logger.debug(f"Multi-instance course {course_code} ({instance_count} instances) distributed across 2 groups: {', '.join(group_names)} [FLEXIBLE]")
                else:
                    # Standard departments: exactly 2 groups required
                    if group_count < 2:
                        violations += 1
                        self.logger.error(f"Multi-instance course {course_code} ({instance_count} instances) appears in only {group_count} groups: {', '.join(group_names)} (should be in 2 groups)")
                    elif group_count > 2:
                        violations += 1
                        self.logger.error(f"Multi-instance course {course_code} ({instance_count} instances) appears in {group_count} groups: {', '.join(group_names)} (should be in 2 groups)")
                    else:
                        self.logger.debug(f"Multi-instance course {course_code} ({instance_count} instances) correctly in 2 groups: {', '.join(group_names)} [STANDARD]")
        
        if violations == 0:
            constraint_type = "flexible (1-2 groups)" if self.allows_flexible_grouping else "standard (2 groups)"
            self.logger.info(f"[OK] Course limit constraints satisfied [{constraint_type}]")
            return True
        else:
            self.logger.error(f"[ERROR] {violations} course limit violations")
            return False
    
    def _validate_assignment_completeness(self):
        """Validate that all instances are assigned exactly once."""
        assigned_instances = set()
        
        for group in self.groups:
            for instance in group:
                instance_id = instance['id']
                if instance_id in assigned_instances:
                    self.logger.error(f"Instance {instance_id} assigned multiple times")
                    return False
                assigned_instances.add(instance_id)
        
        # Check all regular course instances
        missing_instances = []
        for instance in self.courses:
            if instance['id'] not in assigned_instances:
                missing_instances.append(instance['id'])
        
        # Check all PE course instances
        for instance in self.pe_courses:
            if instance['id'] not in assigned_instances:
                missing_instances.append(instance['id'])
        
        if missing_instances:
            self.logger.error(f"Instances not assigned: {missing_instances}")
            return False
        
        total_expected = len(self.courses) + len(self.pe_courses)
        total_assigned = len(assigned_instances)
        self.logger.info(f"[OK] All instances assigned exactly once ({total_assigned}/{total_expected})")
        return True
    
    def _validate_group_sizes(self):
        """Validate that all regular groups have the same size equal to target group size (weighted)."""
        if not hasattr(self, 'target_group_size'):
            self.logger.warning("Target group size not set, skipping group size validation")
            return True
        
        violations = 0
        expected_size = self.target_group_size
        
        # Only validate the first num_groups (regular optimization groups), exclude PE group
        groups_to_validate = min(len(self.groups), self.num_groups)
        
        for group_idx in range(groups_to_validate):
            group = self.groups[group_idx]
            actual_size = sum(inst.get('weight', 1) for inst in group)
            if actual_size != expected_size:
                violations += 1
                self.logger.error(f"Group {group_idx + 1} has {actual_size} weighted instances, "
                                f"expected {expected_size}")
        
        # Log PE group separately if it exists
        if len(self.groups) > self.num_groups:
            pe_group = self.groups[-1]  # PE group is always the last group
            pe_size = sum(inst.get('weight', 1) for inst in pe_group)
            self.logger.info(f"PE Group {len(self.groups)} has {pe_size} weighted instances (validation skipped - special group)")
        
        if violations == 0:
            self.logger.info(f"[OK] All {groups_to_validate} regular groups have {expected_size} weighted instances each")
            return True
        else:
            self.logger.error(f"[ERROR] {violations} group size violations in regular groups")
            return False
    
    def _validate_lab_priority(self):
        """Validate lab priority constraint."""
        if getattr(self, "is_cse_s2", False):
            self.logger.info("[SKIP] Lab priority constraint validation for CSE S2 (constraint skipped)")
            return True

        # Identify lab and theory-only courses
        lab_courses = set()
        theory_only_courses = set()
        
        for course in self.courses:
            practical_hours = course.get('practical_hours', 0)
            if practical_hours > 0:
                lab_courses.add(course['course_code'])
            else:
                theory_only_courses.add(course['course_code'])
        
        # Skip validation if constraint was not applied
        if len(lab_courses) <= 1 or len(theory_only_courses) <= 1:
            self.logger.info("[SKIP] Lab priority constraint validation (constraint not applied)")
            return True
        
        violations = 0
        num_lab_courses = len(lab_courses)
        
        # Check that lab courses are only in first num_lab_courses groups
        for group_idx in range(num_lab_courses, self.num_groups):
            for instance in self.groups[group_idx]:
                practical_hours = instance.get('practical_hours', 0)
                if practical_hours > 0:
                    violations += 1
                    self.logger.error(f"Lab course {instance['course_code']} found in Group {group_idx + 1} "
                                    f"(should be in Groups 1-{num_lab_courses})")
        
        # Check that theory-only courses are only in remaining groups  
        for group_idx in range(0, num_lab_courses):
            for instance in self.groups[group_idx]:
                practical_hours = instance.get('practical_hours', 0)
                if practical_hours == 0:
                    violations += 1
                    self.logger.error(f"Theory-only course {instance['course_code']} found in Group {group_idx + 1} "
                                    f"(should be in Groups {num_lab_courses + 1}-{self.num_groups})")
        
        if violations == 0:
            self.logger.info(f"[OK] Lab priority constraint satisfied "
                           f"(lab courses in Groups 1-{num_lab_courses}, "
                           f"theory courses in Groups {num_lab_courses + 1}-{self.num_groups})")
            return True
        else:
            self.logger.error(f"[ERROR] {violations} lab priority violations")
            return False
    
    def get_groups(self):
        """
        Get the optimized groups.
        
        Returns:
            list: List of groups, each containing course instances
        """
        return self.groups
    
    def get_removed_courses(self):
        """
        Get courses that were removed during filtering.
        
        Returns:
            list: List of removed course instances
        """
        return self.removed_courses
    
    def get_trimmed_courses(self):
        """
        Get courses that were trimmed during filtering.
        
        Returns:
            dict: Dictionary with trimming information per course
        """
        return self.trimmed_courses
    
    def get_filtering_summary(self):
        """
        Get summary of the filtering process.
        
        Returns:
            dict: Filtering summary statistics
        """
        return self.filtering_summary
    
    def save_filtering_report(self, output_file, output_dir=None):
        """
        Save detailed filtering report to file for verification.
        
        Args:
            output_file: Path to output file (can be just filename if output_dir is provided)
            output_dir: Optional directory to save the file in
        """
        if not hasattr(self, 'filtering_summary'):
            self.logger.error("No filtering data to save")
            return
        
        # Handle output directory
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            if not os.path.isabs(output_file):
                output_file = os.path.join(output_dir, output_file)
        
        # Create comprehensive filtering report
        report = {
            'department': self.dept,
            'semester': self.semester,
            'timestamp': datetime.now().isoformat(),
            'summary': self.filtering_summary,
            'removed_courses': {
                'total_instances': len(self.removed_courses),
                'unique_courses': list(set(inst['course_code'] for inst in self.removed_courses)),
                'instances': []
            },
            'trimmed_courses': {},
            'detailed_analysis': {
                'instance_count_breakdown': {},
                'teacher_impact': {},
                'course_type_impact': {}
            }
        }
        
        # Add removed course instances details
        for instance in self.removed_courses:
            report['removed_courses']['instances'].append({
                'id': instance['id'],
                'course_code': instance['course_code'],
                'course_name': instance.get('course_name', ''),
                'teacher_id': instance['teacher_id'],
                'student_count': instance.get('student_count', 0),
                'practical_hours': instance.get('practical_hours', 0),
                'lecture_hours': instance.get('lecture_hours', 0),
                'tutorial_hours': instance.get('tutorial_hours', 0),
                'has_lab': instance.get('has_lab', False),
                'has_theory': instance.get('has_theory', False),
                'reason': 'Insufficient instances (below most common count)'
            })
        
        # Add trimmed courses details
        for course_code, trim_info in self.trimmed_courses.items():
            report['trimmed_courses'][course_code] = {
                'original_count': trim_info['original_count'],
                'kept_count': trim_info['kept_count'],
                'removed_count': len(trim_info['removed_instances']),
                'removed_instances': [],
                'kept_instances': [inst['id'] for inst in trim_info['kept_instances']]
            }
            
            for instance in trim_info['removed_instances']:
                report['trimmed_courses'][course_code]['removed_instances'].append({
                    'id': instance['id'],
                    'teacher_id': instance['teacher_id'],
                    'student_count': instance.get('student_count', 0),
                    'practical_hours': instance.get('practical_hours', 0),
                    'lecture_hours': instance.get('lecture_hours', 0),
                    'tutorial_hours': instance.get('tutorial_hours', 0),
                    'reason': f'Randomly selected for removal during trimming to {trim_info["kept_count"]} instances'
                })
        
        # Add detailed analysis
        if hasattr(self, 'filtering_summary') and 'instance_count_distribution' in self.filtering_summary:
            report['detailed_analysis']['instance_count_breakdown'] = self.filtering_summary['instance_count_distribution']
        
        # Analyze teacher impact
        affected_teachers = set()
        for instance in self.removed_courses:
            affected_teachers.add(instance['teacher_id'])
        for trim_info in self.trimmed_courses.values():
            for instance in trim_info['removed_instances']:
                affected_teachers.add(instance['teacher_id'])
        
        report['detailed_analysis']['teacher_impact'] = {
            'total_teachers_affected': len(affected_teachers),
            'affected_teacher_ids': list(affected_teachers)
        }
        
        # Analyze course type impact
        lab_courses_removed = len([inst for inst in self.removed_courses if inst.get('has_lab', False)])
        theory_courses_removed = len([inst for inst in self.removed_courses if inst.get('has_theory', False)])
        
        report['detailed_analysis']['course_type_impact'] = {
            'lab_instances_removed': lab_courses_removed,
            'theory_instances_removed': theory_courses_removed,
            'total_instances_removed': len(self.removed_courses) + sum(len(info['removed_instances']) for info in self.trimmed_courses.values())
        }
        
        # Save to file
        with open(output_file, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        
        self.logger.info(f"Filtering verification report saved to {output_file}")
        self.logger.info(f"Report summary:")
        self.logger.info(f"  - {report['removed_courses']['total_instances']} course instances completely removed")
        self.logger.info(f"  - {len(report['removed_courses']['unique_courses'])} unique courses removed: {report['removed_courses']['unique_courses']}")
        self.logger.info(f"  - {len(self.trimmed_courses)} courses trimmed")
        self.logger.info(f"  - {len(affected_teachers)} teachers affected")
        
        return report
    
    def print_filtering_summary(self):
        """
        Print a concise summary of the filtering process for quick verification.
        """
        if not hasattr(self, 'filtering_summary'):
            self.logger.warning("No filtering data available")
            return
        
        print(f"\n{'='*60}")
        print(f"COURSE FILTERING SUMMARY - {self.dept} Semester {self.semester}")
        print(f"{'='*60}")
        
        print(f"Original instances: {self.filtering_summary['original_total_instances']}")
        print(f"Filtered instances: {self.filtering_summary['filtered_total_instances']}")
        print(f"Most common instance count: {self.filtering_summary['most_common_instance_count']}")
        
        print(f"\nInstance count distribution:")
        for count, freq in sorted(self.filtering_summary['instance_count_distribution'].items()):
            print(f"  {freq} courses had {count} instances each")
        
        print(f"\nFiltering actions:")
        print(f"  • {self.filtering_summary['courses_removed_count']} courses COMPLETELY REMOVED (insufficient instances)")
        print(f"  • {self.filtering_summary['courses_trimmed_count']} courses TRIMMED (excess instances)")
        print(f"  • {self.filtering_summary['courses_kept_unchanged']} courses kept unchanged")
        print(f"  • {self.filtering_summary['total_instances_removed']} total instances removed")
        
        if self.removed_courses:
            removed_course_codes = list(set(inst['course_code'] for inst in self.removed_courses))
            print(f"\nRemoved courses: {removed_course_codes}")
        
        if self.trimmed_courses:
            print(f"\nTrimmed courses:")
            for course_code, info in self.trimmed_courses.items():
                print(f"  • {course_code}: {info['original_count']} → {info['kept_count']} instances")
        
        print(f"{'='*60}\n")
    
    def generate_group_distribution_visualizations(self, output_dir: Optional[str] = None, include_summary: bool = True):
        """Create heatmap + text summary of the current course-group distribution."""

        if not self.groups:
            self.logger.warning("No groups available to visualize")
            return {}

        if output_dir is None:
            project_root = Path(__file__).resolve().parents[2]
            base_dir = project_root / "data"
        else:
            base_dir = Path(output_dir)

        viz_output_dir = base_dir / "grouping_visualizations" 
        dept_dir = viz_output_dir / f"{self.dept.replace(' ', '_').replace('&', 'and')}_S{self.semester}"
        dept_dir.mkdir(parents=True, exist_ok=True)

        self.logger.info(
            "🎨 Generating course-group visualization for %s Semester %s → %s",
            self.dept,
            self.semester,
            dept_dir,
        )

        course_group_matrix: Dict[str, Dict[str, int]] = {}
        all_courses: Set[str] = set()
        group_names: List[str] = []
        lab_courses: Set[str] = set()
        theory_courses: Set[str] = set()

        for group_idx, group in enumerate(self.groups):
            if not group:
                continue
            group_name = f"G{group_idx + 1}"
            group_names.append(group_name)

            course_teacher_counts: Dict[str, Set[str]] = defaultdict(set)
            for instance in group:
                course_code = instance['course_code']
                teacher_id = instance['teacher_id']
                all_courses.add(course_code)

                if instance.get('has_lab', False):
                    lab_courses.add(course_code)
                if instance.get('has_theory', False):
                    theory_courses.add(course_code)

                course_teacher_counts[course_code].add(teacher_id)

            for course_code, teachers in course_teacher_counts.items():
                course_group_matrix.setdefault(course_code, {})[group_name] = len(teachers)

        if not all_courses or not group_names:
            self.logger.warning("No data to visualize after processing groups")
            return {}

        courses_list = sorted(all_courses)
        matrix_data = [
            [course_group_matrix.get(course, {}).get(group_name, 0) for group_name in group_names]
            for course in courses_list
        ]

        matrix_array = np.array(matrix_data)
        plt.figure(figsize=(max(8, len(group_names) * 1.2), max(6, len(courses_list) * 0.4)))
        ax = sns.heatmap(
            matrix_array,
            xticklabels=group_names,
            yticklabels=courses_list,
            annot=True,
            fmt='d',
            cmap='viridis',
            cbar_kws={'label': 'Number of Teacher Assignments'},
            linewidths=0.5,
        )
        plt.title(
            f"Course-Group Distribution\n{self.dept} - Semester {self.semester}\n"
            "(Teacher assignments per course per group)",
            fontsize=14,
            fontweight='bold',
            pad=20,
        )
        plt.xlabel('Groups', fontsize=12, fontweight='bold')
        plt.ylabel('Courses', fontsize=12, fontweight='bold')
        plt.xticks(rotation=0, ha='center')
        plt.yticks(rotation=0)
        ax.set_facecolor('white')

        for i, course in enumerate(courses_list):
            tags = []
            if course in lab_courses:
                tags.append('L')
            if course in theory_courses:
                tags.append('T')
            if tags:
                plt.text(
                    -0.5,
                    i + 0.5,
                    f"[{'+'.join(tags)}]",
                    ha='right',
                    va='center',
                    fontsize=8,
                    bbox=dict(boxstyle="round,pad=0.2", facecolor="lightblue", alpha=0.7),
                )

        total_assignments = int(matrix_array.sum()) if matrix_array.size else 0
        max_assignments = int(matrix_array.max()) if matrix_array.size else 0
        courses_with_choice = sum(
            1 for course in courses_list if sum(course_group_matrix.get(course, {}).values()) > 1
        )
        choice_percentage = (courses_with_choice / len(courses_list) * 100) if courses_list else 0
        stats_lines = [
            f"Stats: {len(courses_list)} courses ({len(lab_courses)} lab, {len(theory_courses)} theory)",
            f"Groups: {len(group_names)}, Total assignments: {total_assignments}, Max cell: {max_assignments}",
            f"Courses with multiple groups: {courses_with_choice} ({choice_percentage:.1f}%)",
            "[L] Lab, [T] Theory, [L+T] Both",
        ]
        plt.figtext(
            0.02,
            0.02,
            "\n".join(stats_lines),
            fontsize=9,
            bbox=dict(boxstyle="round,pad=0.3", facecolor="lightgray", alpha=0.8),
        )
        plt.tight_layout()

        safe_dept_name = (
            self.dept.replace(' ', '_').replace('&', 'and').replace('(', '').replace(')', '')
        )
        heatmap_path = dept_dir / f"course_group_heatmap_{safe_dept_name}_S{self.semester}.png"
        plt.savefig(heatmap_path, dpi=300, bbox_inches='tight')
        plt.close()
        self.logger.info("✅ Saved heatmap to %s", heatmap_path)

        summary_path = None
        if include_summary:
            summary_path = dept_dir / f"course_group_summary_{safe_dept_name}_S{self.semester}.txt"
            with open(summary_path, 'w', encoding='utf-8') as handle:
                handle.write("Course-Group Distribution Summary\n")
                handle.write(f"Department: {self.dept}\n")
                handle.write(f"Semester: {self.semester}\n")
                handle.write(f"Generated: {datetime.now():%Y-%m-%d %H:%M:%S}\n")
                handle.write("=" * 60 + "\n\n")

                handle.write("OVERVIEW\n")
                handle.write(f"- Courses: {len(courses_list)} (Lab {len(lab_courses)}, Theory {len(theory_courses)})\n")
                handle.write(f"- Groups: {len(group_names)}\n")
                handle.write(f"- Total assignments: {total_assignments}\n")
                handle.write(
                    f"- Courses with multiple options: {courses_with_choice} ({choice_percentage:.1f}%)\n\n"
                )

                handle.write("COURSE DISTRIBUTION BY GROUP\n")
                for course in courses_list:
                    course_data = course_group_matrix.get(course, {})
                    groups_with_course = [g for g, count in course_data.items() if count > 0]
                    total_teachers = sum(course_data.values())
                    type_tags = []
                    if course in lab_courses:
                        type_tags.append('Lab')
                    if course in theory_courses:
                        type_tags.append('Theory')
                    type_label = ' + '.join(type_tags) if type_tags else 'Unknown'
                    handle.write(
                        f"- {course} [{type_label}]: {len(groups_with_course)} groups, {total_teachers} teachers\n"
                    )
                    for group_name in groups_with_course:
                        handle.write(
                            f"  └─ {group_name}: {course_data.get(group_name, 0)} teacher assignments\n"
                        )

                handle.write("\nGROUP COMPOSITION\n")
                for group_idx, group in enumerate(self.groups):
                    if not group:
                        continue
                    group_name = f"G{group_idx + 1}"
                    courses_in_group = {inst['course_code'] for inst in group}
                    teachers_in_group = {inst['teacher_id'] for inst in group}
                    handle.write(
                        f"- {group_name}: {len(courses_in_group)} courses, {len(teachers_in_group)} teachers\n"
                    )
                    for course in sorted(courses_in_group):
                        instances = [inst for inst in group if inst['course_code'] == course]
                        tags = []
                        if any(inst.get('has_lab', False) for inst in instances):
                            tags.append('L')
                        if any(inst.get('has_theory', False) for inst in instances):
                            tags.append('T')
                        teacher_count = len({inst['teacher_id'] for inst in instances})
                        tag_str = '+'.join(tags) if tags else ''
                        handle.write(
                            f"  └─ {course} [{tag_str}]: {len(instances)} instances, {teacher_count} teachers\n"
                        )

            self.logger.info("✅ Saved summary to %s", summary_path)

        return {
            'heatmap': str(heatmap_path),
            'summary': str(summary_path) if summary_path else None,
            'output_dir': str(dept_dir),
        }
    
    def save_results(self, output_file):
        """
        Save optimization results to file.
        
        Args:
            output_file: Path to output file
        """
        if not self.solution_found:
            self.logger.error("No solution to save")
            return
        
        results = {
            'department': self.dept,
            'semester': self.semester,
            'solution_found': self.solution_found,
            'objective_value': self.objective_value,
            'num_groups': self.num_groups,
            'groups': [],
            'pe_group_included': len(self.pe_courses) > 0,
            'summary': {
                'total_instances': len(self.courses),
                'pe_instances': len(self.pe_courses),
                'lab_instances': len(self.lab_courses),
                'theory_instances': len(self.theory_courses),
                'unique_courses': len(self.unique_courses),
                'unique_teachers': len(self.unique_teachers),
                'pe_course_codes': list(set(inst['course_code'] for inst in self.pe_courses)) if self.pe_courses else []
            }
        }
        
        # Add group details
        for group_idx, group in enumerate(self.groups):
            if group:
                # Check if this is the PE group
                is_pe_group = group_idx >= self.num_groups
                
                group_data = {
                    'group_id': group_idx + 1,
                    'is_pe_group': is_pe_group,
                    'group_type': 'PE' if is_pe_group else 'Regular',
                    'instances': [],
                    'teachers': list(set(inst['teacher_id'] for inst in group)),
                    'courses': list(set(inst['course_code'] for inst in group)),
                    'total_workload': sum(
                        inst.get('practical_hours', 0) + 
                        inst.get('lecture_hours', 0) + 
                        inst.get('tutorial_hours', 0)
                        for inst in group
                    )
                }
                
                for instance in group:
                    group_data['instances'].append({
                        'id': instance['id'],
                        'course_id': instance.get('course_id', instance['id']),
                        'course_code': instance['course_code'],
                        'course_name': instance.get('course_name', ''),
                        'course_type': instance.get('course_type', 'T'),
                        'teacher_id': instance['teacher_id'],
                        'semester': instance.get('semester', self.semester),
                        'course_dept': instance.get('course_dept', self.dept),
                        'student_dept': instance.get('student_dept', self.dept),
                        'has_lab': instance.get('has_lab', False),
                        'has_theory': instance.get('has_theory', False),
                        'practical_hours': instance.get('practical_hours', 0),
                        'lecture_hours': instance.get('lecture_hours', 0),
                        'tutorial_hours': instance.get('tutorial_hours', 0),
                        'student_count': instance.get('student_count', 0),
                        'virtual_id': instance.get('virtual_id', None),
                        'co_scheduled_id': instance.get('co_scheduled_id', None)
                    })
                
                results['groups'].append(group_data)
        
        # Save to file
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        
        self.logger.info(f"Results saved to {output_file}")


def main():
    """Example usage of the CourseGroupOptimizer."""
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger(__name__)
    
    # Example course instances (replace with actual data loading)
    sample_courses = [
        {
            'id': 1,
            'course_code': 'CS101',
            'teacher_id': 'T001',
            'has_lab': True,
            'has_theory': True,
            'practical_hours': 3,
            'lecture_hours': 2,
            'tutorial_hours': 1,
            'student_count': 70
        },
        {
            'id': 2,
            'course_code': 'CS101',
            'teacher_id': 'T002',
            'has_lab': True,
            'has_theory': True,
            'practical_hours': 3,
            'lecture_hours': 2,
            'tutorial_hours': 1,
            'student_count': 65
        },
        {
            'id': 3,
            'course_code': 'MATH201',
            'teacher_id': 'T003',
            'has_lab': False,
            'has_theory': True,
            'practical_hours': 0,
            'lecture_hours': 3,
            'tutorial_hours': 1,
            'student_count': 120
        },
        {
            'id': 4,
            'course_code': 'MATH201',
            'teacher_id': 'T004',
            'has_lab': False,
            'has_theory': True,
            'practical_hours': 0,
            'lecture_hours': 3,
            'tutorial_hours': 1,
            'student_count': 115
        },
        {
            'id': 5,
            'course_code': 'PHY301',
            'teacher_id': 'T005',
            'has_lab': True,
            'has_theory': True,
            'practical_hours': 2,
            'lecture_hours': 3,
            'tutorial_hours': 0,
            'student_count': 80
        }
    ]
    
    # Create and run optimizer with PE course mapping
    optimizer = CourseGroupOptimizer(
        courses=sample_courses,
        dept="Computer Science",
        semester=5,
        logger=logger,
        pe_course_map_file="data/pe_course_map.csv"  # Optional PE course mapping
    )
    
    # Optimize distribution
    if optimizer.optimize_distribution():
        # Validate solution
        if optimizer.validate_solution():
            logger.info("Optimization completed successfully!")
            
            # Save results
            optimizer.save_results("course_group_optimization_results.json")
            optimizer.generate_group_distribution_visualizations()
            
            # Get optimized groups
            groups = optimizer.get_groups()
            logger.info(f"Created {len(groups)} optimized groups")
        else:
            logger.error("Solution validation failed")
    else:
        logger.error("Optimization failed")


def optimize_course_groups(csv_file, dept_name, semester, pe_course_map_file=None, flexible_grouping_depts=None):
    """
    Load courses from CSV and optimize groups for a specific department and semester.
    
    Args:
        csv_file: Path to CSV file containing course data
        dept_name: Department name to filter by (uses student_dept field)
        semester: Semester to filter by
        pe_course_map_file: Path to PE course mapping CSV file (optional)
        flexible_grouping_depts: List of departments that can have minimum 1 group for multi-instance courses (optional)
        
    Returns:
        list: Optimized groups or None if failed
    """
    import pandas as pd
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger(__name__)
    
    try:
        # Load CSV data
        logger.info(f"Loading course data from {csv_file}")
        df = pd.read_csv(csv_file)
        
        # Filter by student department and semester
        filtered_df = df[
            (df['student_dept'] == dept_name) & 
            (df['semester'] == semester)
        ]
        
        if filtered_df.empty:
            logger.error(f"No courses found for department '{dept_name}' semester '{semester}'")
            return None
        
        logger.info(f"Found {len(filtered_df)} course instances for {dept_name} Semester {semester}")
        
        # Convert to course instances
        courses = []
        for _, row in filtered_df.iterrows():
            course = {
                'id': int(row['id']),
                'teacher_id': str(row['teacher_id']),
                'course_id': row.get('course_id', row['id']),
                'course_code': row['course_code'],
                'course_name': row.get('course_name', ''),
                'course_type': row.get('course_type', 'T'),
                'lecture_hours': int(row.get('lecture_hours', 0)),
                'tutorial_hours': int(row.get('tutorial_hours', 0)),
                'practical_hours': int(row.get('practical_hours', 0)),
                'student_count': int(row.get('student_count', 0)),
                'semester': row.get('semester', semester),
                'course_dept': row.get('course_dept', dept_name),
                'student_dept': row.get('student_dept', dept_name),
                'has_lab': bool(row.get('practical_hours', 0) > 0),
                'has_theory': bool(row.get('lecture_hours', 0) > 0 or row.get('tutorial_hours', 0) > 0)
            }
            
            courses.append(course)
        
        # Create and run optimizer with PE course mapping and flexible grouping option
        optimizer = CourseGroupOptimizer(courses, dept_name, semester, logger, pe_course_map_file, flexible_grouping_depts)
        
        # Save filtering report before optimization (for verification)
        # Create reports directory if it doesn't exist
        reports_dir = "course_filtering_reports"
        os.makedirs(reports_dir, exist_ok=True)
        
        filtering_report_file = os.path.join(reports_dir, f"filtering_report_{dept_name.replace(' ', '_').replace('&', 'and')}_S{semester}.json")
        optimizer.save_filtering_report(filtering_report_file)
        
        # Optimize distribution
        if optimizer.optimize_distribution():
            # Validate solution
            if optimizer.validate_solution():
                logger.info("Optimization completed successfully!")
                
                # Save results
                output_file = f"optimization_{dept_name.replace(' ', '_').replace('&', 'and')}_{semester}.json"
                optimizer.save_results(output_file)
                optimizer.generate_group_distribution_visualizations()
                
                # Return optimized groups
                return optimizer.get_groups()
            else:
                logger.error("Solution validation failed")
                return None
        else:
            logger.error("Optimization failed")
            return None
            
    except Exception as e:
        logger.error(f"Error in course group optimization: {e}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    main() 