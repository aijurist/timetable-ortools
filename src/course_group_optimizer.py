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
    
    def __init__(self, courses, dept, semester, logger=None):
        """
        Initialize the optimizer with course instances.
        
        Args:
            courses: List of course instances to distribute
            dept: Department name
            semester: Semester number
            logger: Logger instance (optional)
        """
        self.courses = courses
        self.dept = dept
        self.semester = semester
        self.logger = logger or logging.getLogger(__name__)
        
        # Preprocess courses to handle large instances
        self.courses = self._preprocess_large_courses(self.courses)
        
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
        
        # Course analysis
        self.lab_courses = [inst for inst in self.courses if inst.get('has_lab', False)]
        self.theory_courses = [inst for inst in self.courses if inst.get('has_theory', False)]
        self.unique_courses = list(set(inst['course_code'] for inst in self.courses))
        self.unique_teachers = list(set(inst['teacher_id'] for inst in self.courses))
        
        # Number of groups equals number of unique courses (as requested by user)
        self.num_groups = len(self.unique_courses)
        
        self.logger.info(f"Initializing Course Group Optimizer for {dept} Semester {semester}")
        self.logger.info(f"  Total instances: {len(self.courses)}")
        self.logger.info(f"  Lab instances: {len(self.lab_courses)}")
        self.logger.info(f"  Theory instances: {len(self.theory_courses)}")
        self.logger.info(f"  Unique courses: {len(self.unique_courses)}")
        self.logger.info(f"  Unique teachers: {len(self.unique_teachers)}")
        self.logger.info(f"  Target groups: {self.num_groups}")
    
    def _preprocess_large_courses(self, courses):
        """
        Preprocess courses to split instances with >= 140 students into two
        virtual 70-student instances.
        """
        new_courses = []
        co_schedule_counter = 1
        for course in courses:
            if course.get('student_count', 0) >= 140:
                self.logger.info(f"Splitting large course instance {course['id']} ({course['course_code']}) with {course['student_count']} students.")
                
                # Create two virtual instances
                instance1 = course.copy()
                instance1['student_count'] = 70
                instance1['virtual_id'] = f"{course['id']}-A"
                instance1['id'] = f"{course['id']}-A"
                instance1['co_scheduled_id'] = co_schedule_counter
                
                instance2 = course.copy()
                instance2['student_count'] = 70
                instance2['virtual_id'] = f"{course['id']}-B"
                instance2['id'] = f"{course['id']}-B"
                instance2['co_scheduled_id'] = co_schedule_counter
                
                new_courses.extend([instance1, instance2])
                co_schedule_counter += 1
            else:
                new_courses.append(course)
        
        if co_schedule_counter > 1:
            self.logger.info(f"Created {co_schedule_counter - 1} pairs of virtual co-scheduled instances.")
            
        return new_courses
    
    def _filter_courses_by_instance_count(self, courses):
        """
        Filter courses based on instance count. Remove courses that have fewer instances
        than the most common instance count.
        
        Args:
            courses: List of all course instances
            
        Returns:
            list: Filtered list of course instances
        """
        # Count instances per course
        course_instance_counts = defaultdict(int)
        for course in courses:
            course_instance_counts[course['course_code']] += 1
        
        # Find the most common instance count
        instance_count_frequency = defaultdict(int)
        for course_code, count in course_instance_counts.items():
            instance_count_frequency[count] += 1
        
        most_common_count = max(instance_count_frequency.keys(), 
                               key=lambda x: instance_count_frequency[x])
        
        # Log instance count distribution
        self.logger.info(f"Course instance count analysis:")
        for count, freq in sorted(instance_count_frequency.items()):
            self.logger.info(f"  {freq} courses have {count} instances each")
        self.logger.info(f"Most common instance count: {most_common_count}")
        
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
            self.logger.warning(f"Removing courses with insufficient instances:")
            for course_code in sorted(courses_to_remove):
                count = course_instance_counts[course_code]
                removed_instances = [c for c in courses if c['course_code'] == course_code]
                
                # Store removed course info
                self.removed_courses.extend(removed_instances)
                
                self.logger.warning(f"  {course_code}: {count} instances (< {most_common_count}) - REMOVED")
        
        if courses_to_keep:
            self.logger.info(f"Keeping courses:")
            for course_code in sorted(courses_to_keep):
                count = course_instance_counts[course_code]
                if count == most_common_count:
                    self.logger.info(f"  {course_code}: {count} instances (= {most_common_count}) - KEPT")
                elif course_code in courses_to_trim:
                    target_count = courses_to_trim[course_code]
                    self.logger.info(f"  {course_code}: {count} instances -> trimming to {target_count} instances")
        
        # Filter and trim course instances
        import random
        filtered_courses = []
        
        for course_code in courses_to_keep:
            course_instances = [c for c in courses if c['course_code'] == course_code]
            
            if course_code in courses_to_trim:
                # Randomly select target_count instances from this course
                target_count = courses_to_trim[course_code]
                selected_instances = random.sample(course_instances, target_count)
                removed_instances = [inst for inst in course_instances if inst not in selected_instances]
                
                # Store trimming info
                self.trimmed_courses[course_code] = {
                    'original_count': len(course_instances),
                    'kept_count': target_count,
                    'removed_instances': removed_instances,
                    'kept_instances': selected_instances
                }
                
                filtered_courses.extend(selected_instances)
                self.logger.info(f"  {course_code}: selected {target_count} out of {len(course_instances)} instances")
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
        
        # Count instances per course
        course_instance_counts = defaultdict(int)
        course_teacher_counts = defaultdict(set)
        
        for course in self.courses:
            course_code = course['course_code']
            teacher_id = course['teacher_id']
            course_instance_counts[course_code] += 1
            course_teacher_counts[course_code].add(teacher_id)
        
        # Find the most common instance count (target group size)
        instance_count_frequency = defaultdict(int)
        for course_code, count in course_instance_counts.items():
            instance_count_frequency[count] += 1
        
        target_group_size = max(instance_count_frequency.keys(), 
                               key=lambda x: instance_count_frequency[x])
        
        # Check if total instances can be evenly distributed
        total_instances = len(self.courses)
        required_instances = self.num_groups * target_group_size
        
        if total_instances != required_instances:
            self.logger.error(f"INFEASIBLE: Cannot distribute {total_instances} instances into "
                            f"{self.num_groups} groups of {target_group_size} instances each "
                            f"(requires {required_instances} instances)")
            return False
        
        # Log distribution info
        self.logger.info(f"Feasibility analysis:")
        self.logger.info(f"  Total instances: {total_instances}")
        self.logger.info(f"  Number of groups: {self.num_groups}")
        self.logger.info(f"  Target group size: {target_group_size}")
        self.logger.info(f"  Required total: {required_instances}")
        
        # Check course distribution requirements
        multi_instance_courses = 0
        single_instance_courses = 0
        
        for course_code, instance_count in course_instance_counts.items():
            teacher_count = len(course_teacher_counts[course_code])
            
            if instance_count == 1:
                single_instance_courses += 1
                self.logger.info(f"Course {course_code}: {instance_count} instance, "
                               f"{teacher_count} teacher -> will be in 1 group")
            elif instance_count > 1:
                multi_instance_courses += 1
                if self.num_groups < 2:
                    self.logger.error(f"INFEASIBLE: Course {course_code} has {instance_count} instances "
                                    f"but only {self.num_groups} groups available (need at least 2 groups)")
                    return False
                self.logger.info(f"Course {course_code}: {instance_count} instances, "
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
        - Courses with multiple instances: minimum 2 groups, maximum 2 groups
        - Courses with single instance: allow in only 1 group
        
        Args:
            model: CP-SAT model
            assignment_vars: Assignment variables
        """
        course_constraints_added = 0
        single_instance_courses = 0
        multi_instance_courses = 0
        
        for course_code in self.unique_courses:
            # Find all instances of this course
            course_instances = [i for i, inst in enumerate(self.courses) 
                             if inst['course_code'] == course_code]
            
            if len(course_instances) == 1:
                # Single instance course: can be in only 1 group (natural constraint)
                single_instance_courses += 1
                self.logger.debug(f"Course {course_code}: 1 instance -> can be in 1 group")
                
            elif len(course_instances) > 1:
                # Multiple instance course: enforce min 2 groups, max 2 groups
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
                
                # Constraint 1: Course must be in at least 2 groups (minimum distribution)
                if self.num_groups >= 2:
                    model.Add(sum(group_has_course) >= 2)
                    course_constraints_added += 1
                    
                # Constraint 2: Course can be in at most 2 groups (maximum distribution)
                model.Add(sum(group_has_course) <= 2)
                course_constraints_added += 1
                
                self.logger.debug(f"Course {course_code}: {len(course_instances)} instances -> must be in exactly 2 groups")
        
        self.logger.info(f"Applied {course_constraints_added} course limit constraints")
        self.logger.info(f"  Single-instance courses: {single_instance_courses} (can be in 1 group)")
        self.logger.info(f"  Multi-instance courses: {multi_instance_courses} (must be in exactly 2 groups)")
    
    def _apply_group_size_constraints(self, model, assignment_vars):
        """
        Apply group size constraints: each group should have the same number of instances,
        equal to the most common number of course instances per course.
        
        Args:
            model: CP-SAT model
            assignment_vars: Assignment variables
        """
        # Calculate the most common number of instances per course
        course_instance_counts = defaultdict(int)
        for course in self.courses:
            course_instance_counts[course['course_code']] += 1
        
        # Find the most frequent instance count
        instance_count_frequency = defaultdict(int)
        for course_code, count in course_instance_counts.items():
            instance_count_frequency[count] += 1
        
        # Get the most common instance count
        target_group_size = max(instance_count_frequency.keys(), 
                               key=lambda x: instance_count_frequency[x])
        
        self.target_group_size = target_group_size
        
        self.logger.info(f"Course instance distribution:")
        for count, freq in sorted(instance_count_frequency.items()):
            self.logger.info(f"  {freq} courses have {count} instances each")
        self.logger.info(f"Target group size: {target_group_size} instances per group")
        
        # Apply constraint: each group must have exactly target_group_size instances
        group_size_constraints_added = 0
        for group_idx in range(self.num_groups):
            group_assignments = []
            for i, instance in enumerate(self.courses):
                group_assignments.append(assignment_vars[(i, group_idx)])
            
            # Each group must have exactly target_group_size instances
            model.Add(sum(group_assignments) == target_group_size)
            group_size_constraints_added += 1
        
        self.logger.info(f"Applied {group_size_constraints_added} group size constraints "
                        f"(each group = {target_group_size} instances)")
    
    def _apply_lab_priority_constraints(self, model, assignment_vars):
        """
        Apply lab priority constraints: courses with practical hours occupy initial groups first.
        
        Args:
            model: CP-SAT model
            assignment_vars: Assignment variables
        """
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
        
        # Special constraint for Electronics & Communication Engineering 7th semester
        if (self.dept == "Electronics & Communication Engineering" and self.semester == 7):
            constraints_added += self._apply_ece_s7_even_lab_distribution(model, assignment_vars)
        
        # Special constraint for Electronics & Communication Engineering 5th semester
        if (self.dept == "Electronics & Communication Engineering" and self.semester == 5):
            constraints_added += self._apply_ece_s5_even_lab_distribution(model, assignment_vars)
        
        if constraints_added > 0:
            self.logger.info(f"Applied {constraints_added} special department-specific constraints")
        else:
            self.logger.info("No special department-specific constraints applied")
    
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
        """
        Extract the solution from the solver.
        
        Args:
            solver: CP-SAT solver
            assignment_vars: Assignment variables
        """
        # Initialize groups
        self.groups = [[] for _ in range(self.num_groups)]
        
        # Extract assignments
        for i, instance in enumerate(self.courses):
            for group_idx in range(self.num_groups):
                if solver.Value(assignment_vars[(i, group_idx)]) == 1:
                    self.groups[group_idx].append(instance)
                    break
        
        # Log group distribution
        self.logger.info(f"Optimal group distribution for {self.dept} Semester {self.semester}:")
        
        course_distribution = defaultdict(list)
        
        for group_idx, group in enumerate(self.groups):
            if group:  # Only show non-empty groups
                teachers = sorted(set(str(inst['teacher_id']) for inst in group))
                courses = sorted(set(inst['course_code'] for inst in group))
                lab_instances = [inst for inst in group if inst.get('has_lab', False)]
                theory_instances = [inst for inst in group if inst.get('has_theory', False)]
                
                # Track course distribution
                for course_code in courses:
                    course_distribution[course_code].append(group_idx + 1)
                
                total_workload = sum(
                    inst.get('practical_hours', 0) + 
                    inst.get('lecture_hours', 0) + 
                    inst.get('tutorial_hours', 0)
                    for inst in group
                )
                
                self.logger.info(f"  Group {group_idx + 1}: {len(group)} instances")
                self.logger.info(f"    Lab: {len(lab_instances)}, Theory: {len(theory_instances)}")
                self.logger.info(f"    Teachers: [{', '.join(teachers)}]")
                self.logger.info(f"    Courses: [{', '.join(courses)}]")
                self.logger.info(f"    Total workload: {total_workload} hours")
        
        # Log course distribution summary
        self.logger.info(f"\nCourse distribution summary:")
        total_courses = len(course_distribution)
        courses_with_choice = 0
        
        for course_code, group_list in sorted(course_distribution.items()):
            if len(group_list) > 1:
                courses_with_choice += 1
            group_names = [f"G{g}" for g in group_list]
            status = "[OK]" if len(group_list) <= 2 else "[ERROR]"
            self.logger.info(f"  {course_code}: {', '.join(group_names)} ({len(group_list)} groups) {status}")
        
        choice_percentage = (courses_with_choice / total_courses * 100) if total_courses > 0 else 0
        self.logger.info(f"\nStudent choice analysis:")
        self.logger.info(f"  Total courses: {total_courses}")
        self.logger.info(f"  Courses with multiple group options: {courses_with_choice}")
        self.logger.info(f"  Student choice percentage: {choice_percentage:.1f}%")
    
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
            teacher_instance_map = defaultdict(list)
            
            for instance in group:
                teacher_instance_map[instance['teacher_id']].append(instance)
            
            for teacher_id, instances in teacher_instance_map.items():
                if len(instances) > 1:
                    # Check if this is a valid co-scheduling case
                    co_scheduled_pairs = 0
                    co_schedule_ids = [inst.get('co_scheduled_id') for inst in instances if 'co_scheduled_id' in inst]
                    
                    if len(co_schedule_ids) == 2 and co_schedule_ids[0] == co_schedule_ids[1]:
                        # This is a valid pair
                        co_scheduled_pairs = 1
                    
                    # A violation occurs if the number of instances exceeds the valid pairs
                    if len(instances) - co_scheduled_pairs > 1:
                        violations += 1
                        self.logger.error(f"Teacher {teacher_id} appears {len(instances)} times in Group {group_idx + 1}, but only {co_scheduled_pairs} co-scheduled pairs found.")

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
        - Multi-instance courses: must be in exactly 2 groups
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
            
            if instance_count == 1:
                # Single instance course: should be in exactly 1 group
                if group_count != 1:
                    violations += 1
                    self.logger.error(f"Single-instance course {course_code} appears in {group_count} groups: {', '.join(group_names)} (should be in 1 group)")
                else:
                    self.logger.debug(f"Single-instance course {course_code} correctly in 1 group: {group_names[0]}")
                    
            elif instance_count > 1:
                # Multi-instance course: should be in exactly 2 groups
                if group_count < 2:
                    violations += 1
                    self.logger.error(f"Multi-instance course {course_code} ({instance_count} instances) appears in only {group_count} groups: {', '.join(group_names)} (should be in 2 groups)")
                elif group_count > 2:
                    violations += 1
                    self.logger.error(f"Multi-instance course {course_code} ({instance_count} instances) appears in {group_count} groups: {', '.join(group_names)} (should be in 2 groups)")
                else:
                    self.logger.debug(f"Multi-instance course {course_code} ({instance_count} instances) correctly in 2 groups: {', '.join(group_names)}")
        
        if violations == 0:
            self.logger.info("[OK] Course limit constraints satisfied")
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
        
        missing_instances = []
        for instance in self.courses:
            if instance['id'] not in assigned_instances:
                missing_instances.append(instance['id'])
        
        if missing_instances:
            self.logger.error(f"Instances not assigned: {missing_instances}")
            return False
        
        self.logger.info("[OK] All instances assigned exactly once")
        return True
    
    def _validate_group_sizes(self):
        """Validate that all groups have the same size equal to target group size."""
        if not hasattr(self, 'target_group_size'):
            self.logger.warning("Target group size not set, skipping group size validation")
            return True
        
        violations = 0
        expected_size = self.target_group_size
        
        for group_idx, group in enumerate(self.groups):
            actual_size = len(group)
            if actual_size != expected_size:
                violations += 1
                self.logger.error(f"Group {group_idx + 1} has {actual_size} instances, "
                                f"expected {expected_size}")
        
        if violations == 0:
            self.logger.info(f"[OK] All groups have {expected_size} instances each")
            return True
        else:
            self.logger.error(f"[ERROR] {violations} group size violations")
            return False
    
    def _validate_lab_priority(self):
        """Validate lab priority constraint."""
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
            'summary': {
                'total_instances': len(self.courses),
                'lab_instances': len(self.lab_courses),
                'theory_instances': len(self.theory_courses),
                'unique_courses': len(self.unique_courses),
                'unique_teachers': len(self.unique_teachers)
            }
        }
        
        # Add group details
        for group_idx, group in enumerate(self.groups):
            if group:
                group_data = {
                    'group_id': group_idx + 1,
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
    
    # Create and run optimizer
    optimizer = CourseGroupOptimizer(
        courses=sample_courses,
        dept="Computer Science",
        semester=5,
        logger=logger
    )
    
    # Optimize distribution
    if optimizer.optimize_distribution():
        # Validate solution
        if optimizer.validate_solution():
            logger.info("Optimization completed successfully!")
            
            # Save results
            optimizer.save_results("course_group_optimization_results.json")
            
            # Get optimized groups
            groups = optimizer.get_groups()
            logger.info(f"Created {len(groups)} optimized groups")
        else:
            logger.error("Solution validation failed")
    else:
        logger.error("Optimization failed")


def optimize_course_groups(csv_file, dept_name, semester):
    """
    Load courses from CSV and optimize groups for a specific department and semester.
    
    Args:
        csv_file: Path to CSV file containing course data
        dept_name: Department name to filter by (uses student_dept field)
        semester: Semester to filter by
        
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
        
        # Create and run optimizer
        optimizer = CourseGroupOptimizer(courses, dept_name, semester, logger)
        
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