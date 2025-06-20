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
        
        # Processing results
        self.groups = []
        self.solution_found = False
        self.objective_value = 0
        
        # Filter courses based on instance count before analysis
        self.courses = self._filter_courses_by_instance_count(courses)
        
        # Course analysis
        self.lab_courses = [inst for inst in self.courses if inst.get('has_lab', False)]
        self.theory_courses = [inst for inst in self.courses if inst.get('has_theory', False)]
        self.unique_courses = list(set(inst['course_code'] for inst in self.courses))
        self.unique_teachers = list(set(inst['teacher_id'] for inst in self.courses))
        
        # Number of groups equals number of unique courses (as requested by user)
        self.num_groups = len(self.unique_courses)
        
        self.logger.info(f"Initializing Course Group Optimizer for {dept} Semester {semester}")
        self.logger.info(f"  Total instances: {len(courses)}")
        self.logger.info(f"  Lab instances: {len(self.lab_courses)}")
        self.logger.info(f"  Theory instances: {len(self.theory_courses)}")
        self.logger.info(f"  Unique courses: {len(self.unique_courses)}")
        self.logger.info(f"  Unique teachers: {len(self.unique_teachers)}")
        self.logger.info(f"  Target groups: {self.num_groups}")
    
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
        
        # Log filtering results
        if courses_to_remove:
            self.logger.warning(f"Removing courses with insufficient instances:")
            for course_code in sorted(courses_to_remove):
                count = course_instance_counts[course_code]
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
                filtered_courses.extend(selected_instances)
                self.logger.info(f"  {course_code}: selected {target_count} out of {len(course_instances)} instances")
            else:
                # Keep all instances
                filtered_courses.extend(course_instances)
        
        self.logger.info(f"Filtered courses: {len(courses)} -> {len(filtered_courses)} instances")
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
                var_name = f"assign_inst_{instance_id}_to_group_{group_idx}"
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
            instance_assignments = [assignment_vars[(i, g)] for g in range(self.num_groups)]
            model.Add(sum(instance_assignments) == 1)
        
        self.logger.info("Applied basic assignment constraints (each instance to exactly one group)")
    
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
                    teacher_assignments = [assignment_vars[(i, group_idx)] for i in instance_indices]
                    model.Add(sum(teacher_assignments) <= 1)
                    teacher_constraints_added += 1
        
        self.logger.info(f"Applied {teacher_constraints_added} teacher uniqueness constraints")
    
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
    
    def _set_optimization_objectives(self, model, assignment_vars):
        """
        Set optimization objectives.
        
        Args:
            model: CP-SAT model
            assignment_vars: Assignment variables
        """
        # Primary objective: Maximize student choice (courses in multiple groups)
        # Since we now enforce exactly 2 groups for multi-instance courses,
        # we focus on maximizing overall assignment satisfaction
        objective_terms = []
        
        for course_code in self.unique_courses:
            course_instances = [i for i, inst in enumerate(self.courses) 
                             if inst['course_code'] == course_code]
            
            if len(course_instances) > 1:
                # Multi-instance course: will be in exactly 2 groups due to constraints
                # Reward balanced distribution across groups
                for group_idx in range(self.num_groups):
                    for i in course_instances:
                        objective_terms.append(assignment_vars[(i, group_idx)] * 10)
            else:
                # Single-instance course: will be in exactly 1 group
                # Add smaller reward for assignment
                for group_idx in range(self.num_groups):
                    for i in course_instances:
                        objective_terms.append(assignment_vars[(i, group_idx)] * 5)
        
        # Set objective: maximize overall assignment satisfaction
        if objective_terms:
            model.Maximize(sum(objective_terms))
        
        self.logger.info("Set optimization objectives (maximize balanced distribution)")
    
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
            teacher_counts = defaultdict(int)
            
            for instance in group:
                teacher_counts[instance['teacher_id']] += 1
            
            for teacher_id, count in teacher_counts.items():
                if count > 1:
                    violations += 1
                    self.logger.error(f"Teacher {teacher_id} appears {count} times in Group {group_idx + 1}")
        
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
                        'student_count': instance.get('student_count', 0)
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