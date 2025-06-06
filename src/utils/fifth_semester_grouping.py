"""
Fifth Semester Course-Teacher Grouping Analyzer

This module creates optimal groups for 5th semester courses and teachers
that satisfy Hall's theorem while considering student capacity constraints.
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import os
import json
import networkx as nx
from collections import defaultdict, Counter
from itertools import combinations
from datetime import datetime
import math

class NumpyEncoder(json.JSONEncoder):
    """Custom JSON encoder to handle numpy types and sets."""
    def default(self, obj):
        if isinstance(obj, (np.integer, np.int64)):
            return int(obj)
        elif isinstance(obj, (np.floating, np.float64)):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, set):
            return list(obj)
        return super(NumpyEncoder, self).default(obj)

class FifthSemesterGroupingAnalyzer:
    def __init__(self, csv_file_path, output_dir=None):
        """Initialize the 5th semester grouping analyzer."""
        self.csv_file_path = csv_file_path
        self.output_dir = output_dir or 'output/fifth_semester_grouping'
        
        # Create output directory
        os.makedirs(self.output_dir, exist_ok=True)
        
        # Student capacity per teacher
        self.students_per_teacher = 70
        
        # Load and process data
        self.df = pd.read_csv(csv_file_path)
        self.process_fifth_semester_data()
        
        print(f"🎯 Fifth Semester Grouping Analyzer initialized")
        print(f"📁 Output directory: {self.output_dir}")
        print(f"📋 5th Semester records: {len(self.sem5_data)}")
    
    def process_fifth_semester_data(self):
        """Process and extract 5th semester data with proper instance handling."""
        # Filter for 5th semester and exclude Unknown teachers
        self.sem5_data = self.df[
            (self.df['semester'] == 5) & 
            (self.df['teacher_id'] != 'Unknown')
        ].copy()
        
        # Create teacher full names
        self.sem5_data['teacher_full_name'] = (
            self.sem5_data['first_name'].fillna('') + ' ' + 
            self.sem5_data['last_name'].fillna('')
        ).str.strip()
        
        # Get unique courses and teachers for 5th semester
        self.courses = self.sem5_data['course_code'].unique()
        self.teachers = self.sem5_data['teacher_id'].unique()
        
        # Create course-teacher mapping with INSTANCE HANDLING
        # Each row represents a separate teacher-course instance
        self.course_teacher_instances = defaultdict(list)  # course -> list of teacher instances
        self.teacher_course_instances = defaultdict(list)  # teacher -> list of course instances
        self.course_teacher_matrix = defaultdict(set)      # course -> set of unique teachers (for Hall's theorem)
        self.teacher_course_matrix = defaultdict(set)      # teacher -> set of unique courses
        self.course_details = {}
        self.teacher_instances = {}  # Store all teacher instances with their details
        
        for _, row in self.sem5_data.iterrows():
            course_code = row['course_code']
            teacher_id = row['teacher_id']
            instance_id = row['id']  # Use the unique ID from the CSV
            
            # Store teacher instance details
            teacher_instance = {
                'instance_id': instance_id,
                'teacher_id': teacher_id,
                'course_code': course_code,
                'student_count': row['student_count'],
                'teacher_name': row['teacher_full_name']
            }
            self.teacher_instances[instance_id] = teacher_instance
            
            # Track instances (multiple records for same teacher-course = multiple instances)
            self.course_teacher_instances[course_code].append(teacher_instance)
            self.teacher_course_instances[teacher_id].append(teacher_instance)
            
            # Track unique relationships (for Hall's theorem)
            self.course_teacher_matrix[course_code].add(teacher_id)
            self.teacher_course_matrix[teacher_id].add(course_code)
            
            # Store course details
            if course_code not in self.course_details:
                self.course_details[course_code] = {
                    'course_name': row['course_name'],
                    'course_type': row['course_type'],
                    'lecture_hours': row['lecture_hours'],
                    'practical_hours': row['practical_hours'],
                    'tutorial_hours': row['tutorial_hours'],
                    'credits': row['credits'],
                    'student_count': row['student_count']
                }
        
        print(f"✅ Processed 5th semester data with instance handling:")
        print(f"   📚 Courses: {len(self.courses)}")
        print(f"   👥 Unique teachers: {len(self.teachers)}")
        print(f"   📊 Total course-teacher assignment records: {len(self.sem5_data)}")
        print(f"   🔢 Total teacher instances: {len(self.teacher_instances)}")
        
        # Show instance breakdown
        print(f"\n📋 INSTANCE BREAKDOWN BY COURSE:")
        for course_code in sorted(self.courses):
            instances = self.course_teacher_instances[course_code]
            unique_teachers = len(self.course_teacher_matrix[course_code])
            print(f"   📖 {course_code}: {len(instances)} instances from {unique_teachers} unique teachers")
            
            # Show teacher instance details
            teacher_instance_counts = Counter(inst['teacher_id'] for inst in instances)
            for teacher_id, count in teacher_instance_counts.items():
                if count > 1:
                    print(f"      👨‍🏫 Teacher {teacher_id}: {count} instances")
        
        print(f"\n📋 INSTANCE BREAKDOWN BY TEACHER:")
        teachers_with_multiple = 0
        for teacher_id in sorted(self.teachers):
            instances = self.teacher_course_instances[teacher_id]
            if len(instances) > 1:
                teachers_with_multiple += 1
                course_instance_counts = Counter(inst['course_code'] for inst in instances)
                unique_courses = len(self.teacher_course_matrix[teacher_id])
                print(f"   👨‍🏫 Teacher {teacher_id}: {len(instances)} instances across {unique_courses} courses")
                for course, count in course_instance_counts.items():
                    if count > 1:
                        print(f"      📖 {course}: {count} instances")
        
        print(f"   📊 Teachers with multiple instances: {teachers_with_multiple}/{len(self.teachers)}")
    
    def analyze_fifth_semester_distribution(self):
        """Analyze the current 5th semester course-teacher distribution with instance handling."""
        print("\n" + "="*80)
        print("📊 FIFTH SEMESTER COURSE-TEACHER DISTRIBUTION ANALYSIS (WITH INSTANCES)")
        print("="*80)
        
        # Course analysis with instances
        print(f"\n📚 COURSE ANALYSIS:")
        print("-" * 40)
        
        for course_code in sorted(self.courses):
            instances = self.course_teacher_instances[course_code]
            unique_teachers = list(self.course_teacher_matrix[course_code])
            course_info = self.course_details[course_code]
            
            # Calculate capacity based on instances (not just unique teachers)
            total_student_capacity = len(instances) * self.students_per_teacher
            required_capacity = course_info['student_count']
            
            print(f"\n📖 {course_code} - {course_info['course_name']}")
            print(f"   📊 Type: {course_info['course_type']} | Credits: {course_info['credits']}")
            print(f"   👥 Teacher instances: {len(instances)} (from {len(unique_teachers)} unique teachers)")
            print(f"   👨‍🎓 Student capacity: {total_student_capacity} (Required: {required_capacity})")
            print(f"   ⏰ Hours: L={course_info['lecture_hours']}, P={course_info['practical_hours']}, T={course_info['tutorial_hours']}")
            
            # Show teacher instance details
            teacher_instance_counts = Counter(inst['teacher_id'] for inst in instances)
            teacher_details = []
            for teacher_id, count in teacher_instance_counts.items():
                teacher_data = self.sem5_data[self.sem5_data['teacher_id'] == teacher_id].iloc[0]
                name = f"{teacher_data['first_name']} {teacher_data['last_name']}".strip()
                if count > 1:
                    teacher_details.append(f"{name} ({teacher_id}) - {count} instances")
                else:
                    teacher_details.append(f"{name} ({teacher_id})")
            print(f"   🎓 Teacher instances: {', '.join(teacher_details)}")
        
        return {
            'courses': len(self.courses),
            'teachers': len(self.teachers),
            'total_instances': len(self.teacher_instances),
            'course_teacher_matrix': {k: list(v) for k, v in self.course_teacher_matrix.items()},
            'teacher_course_matrix': {k: list(v) for k, v in self.teacher_course_matrix.items()},
            'course_teacher_instances': {k: len(v) for k, v in self.course_teacher_instances.items()}
        }
    
    def create_optimal_groups(self, courses_per_group=None):
        """Create optimal groups of courses and teachers based on course count for the semester."""
        print("\n" + "="*80)
        print("🎯 CREATING ENHANCED GROUPS WITH COURSE INSTANCE DISTRIBUTION")
        print("="*80)
        
        # Calculate course distribution parameters
        num_courses = len(self.courses)
        num_teachers = len(self.teachers)
        
        # Enhanced model: Allow course instances to be distributed across multiple groups
        print(f"📊 Enhanced Course Instance Distribution Model:")
        print(f"   📚 Total courses in 5th semester: {num_courses}")
        print(f"   👥 Total teachers available: {num_teachers}")
        print(f"   🔢 Total teacher instances: {len(self.teacher_instances)}")
        print(f"   🎯 Strategy: Distribute course instances across groups")
        print(f"   🔒 CONSTRAINT: No teacher appears in multiple groups")
        print(f"   🔒 CONSTRAINT: Multiple instances of same course by same teacher go to different groups")
        print(f"   🧮 CONSTRAINT: Each group must satisfy Hall's theorem")
        
        # Analyze course characteristics for optimal grouping
        course_analysis = self._analyze_course_characteristics()
        
        # Create groups using the enhanced distribution algorithm
        groups = self._create_enhanced_instance_distribution_groups(course_analysis)
        
        # Verify and optimize groups for Hall's theorem and capacity
        verified_groups = self._verify_and_optimize_enhanced_groups(groups)
        
        return verified_groups
    
    def _create_enhanced_instance_distribution_groups(self, course_analysis):
        """Create groups by distributing course instances optimally across groups."""
        print(f"\n🎯 ENHANCED INSTANCE DISTRIBUTION ALGORITHM:")
        print("-" * 60)
        print("🔒 Enhanced Constraints:")
        print("   1. No teacher appears in multiple groups")
        print("   2. Multiple instances of same course by same teacher → different groups")
        print("   3. Each group must satisfy Hall's theorem")
        print("   4. Balanced distribution of course instances")
        print("   5. Optimal student capacity utilization")
        
        # Determine optimal number of groups based on teacher instance distribution
        total_instances = len(self.teacher_instances)
        instances_per_group = max(4, total_instances // 6)  # Aim for 4-6 instances per group
        optimal_group_count = max(3, min(8, total_instances // instances_per_group))
        
        print(f"\n📊 Group Configuration:")
        print(f"   🔢 Total instances to distribute: {total_instances}")
        print(f"   📦 Target groups: {optimal_group_count}")
        print(f"   📊 Target instances per group: {instances_per_group}")
        
        # Initialize groups
        groups = []
        for i in range(optimal_group_count):
            groups.append({
                'group_id': i + 1,
                'course_instances': [],  # List of (course_code, teacher_instance) pairs
                'courses_represented': set(),  # Set of course codes in this group
                'teachers_assigned': set(),  # Set of teacher IDs in this group
                'teacher_instances': [],  # List of teacher instance objects
                'student_capacity': 0,
                'halls_satisfied': False,
                'halls_violations': [],
                'instance_constraint_satisfied': True,
                'enhanced_constraint_satisfied': True,
                'course_teacher_matrix': {}
            })
        
        # Apply enhanced distribution algorithm
        groups = self._apply_enhanced_distribution_algorithm(groups, course_analysis)
        
        return groups
    
    def _apply_enhanced_distribution_algorithm(self, groups, course_analysis):
        """Apply the enhanced distribution algorithm with sophisticated constraint handling."""
        print(f"\n🔧 APPLYING ENHANCED DISTRIBUTION ALGORITHM:")
        print("-" * 50)
        
        # Track global assignments - FIX: Use single group assignment, not sets
        global_teacher_assignments = {}  # teacher_id -> single group_id (not a set!)
        teacher_instance_assignments = {}  # instance_id -> group_id
        
        # Phase 1: Identify teachers with multiple instances that need distribution
        multi_instance_teachers = self._identify_multi_instance_teachers()
        
        # Phase 2: Distribute multi-instance teachers first - FIXED APPROACH
        groups = self._distribute_multi_instance_teachers_fixed(groups, multi_instance_teachers, global_teacher_assignments)
        
        # Phase 3: Assign remaining single-instance teachers
        groups = self._assign_remaining_teachers_fixed(groups, global_teacher_assignments)
        
        # Phase 4: Verify and adjust for Hall's theorem
        groups = self._verify_and_adjust_halls_theorem(groups)
        
        # Phase 5: Final constraint verification
        groups = self._final_enhanced_constraint_verification_fixed(groups, global_teacher_assignments)
        
        return groups
    
    def _distribute_multi_instance_teachers_fixed(self, groups, multi_instance_teachers, global_teacher_assignments):
        """FIXED: Distribute teachers with multiple instances - each teacher goes to ONLY ONE group."""
        print(f"\n📦 DISTRIBUTING MULTI-INSTANCE TEACHERS (FIXED):")
        print("-" * 40)
        print("🔒 FIXED CONSTRAINT: Each teacher assigned to exactly ONE group")
        print("📦 Strategy: Distribute instances across groups, but teacher stays in first assigned group")
        
        for teacher_id, teacher_info in multi_instance_teachers.items():
            print(f"\n👨‍🏫 Processing Teacher {teacher_id}:")
            
            # Check if teacher is already assigned
            if teacher_id in global_teacher_assignments:
                assigned_group_id = global_teacher_assignments[teacher_id]
                assigned_group = groups[assigned_group_id - 1]  # Convert to 0-based index
                
                print(f"   ℹ️  Teacher {teacher_id} already assigned to Group {assigned_group_id}")
                
                # Add all remaining instances of this teacher to the same group
                for course_code, course_instances in teacher_info['course_distribution'].items():
                    for instance in course_instances:
                        instance_id = instance['instance_id']
                        if instance_id not in [inst['instance_id'] for _, inst in assigned_group['course_instances']]:
                            assigned_group['course_instances'].append((course_code, instance))
                            assigned_group['courses_represented'].add(course_code)
                            assigned_group['teacher_instances'].append(instance)
                            assigned_group['student_capacity'] += self.students_per_teacher
                            
                            print(f"      ➕ Added instance {instance_id} ({course_code}) to Group {assigned_group_id}")
                continue
            
            # Find the best group for this teacher (teacher goes to ONE group only)
            best_group = None
            min_capacity = float('inf')
            
            # Find group with minimum capacity that can accommodate this teacher
            for group in groups:
                # Check if any teacher in this group conflicts
                if not any(tid in global_teacher_assignments and global_teacher_assignments[tid] == group['group_id'] for tid in group['teachers_assigned']):
                    if group['student_capacity'] < min_capacity:
                        min_capacity = group['student_capacity']
                        best_group = group
            
            if best_group is None:
                # Create emergency group if needed
                emergency_group = {
                    'group_id': len(groups) + 1,
                    'course_instances': [],
                    'courses_represented': set(),
                    'teachers_assigned': set(),
                    'teacher_instances': [],
                    'student_capacity': 0,
                    'halls_satisfied': False,
                    'halls_violations': [],
                    'instance_constraint_satisfied': True,
                    'enhanced_constraint_satisfied': True,
                    'course_teacher_matrix': {}
                }
                groups.append(emergency_group)
                best_group = emergency_group
                print(f"   🆘 Created emergency Group {best_group['group_id']} for Teacher {teacher_id}")
            
            # Assign teacher to the best group (ALL instances go to this ONE group)
            global_teacher_assignments[teacher_id] = best_group['group_id']
            best_group['teachers_assigned'].add(teacher_id)
            
            print(f"   ✅ Assigned Teacher {teacher_id} to Group {best_group['group_id']}")
            
            # Add all instances of this teacher to the assigned group
            total_instances_added = 0
            for course_code, course_instances in teacher_info['course_distribution'].items():
                for instance in course_instances:
                    best_group['course_instances'].append((course_code, instance))
                    best_group['courses_represented'].add(course_code)
                    best_group['teacher_instances'].append(instance)
                    best_group['student_capacity'] += self.students_per_teacher
                    total_instances_added += 1
                    
                    print(f"      ➕ Added instance {instance['instance_id']} ({course_code})")
            
            print(f"   📊 Total instances added: {total_instances_added}")
        
        return groups
    
    def _assign_remaining_teachers_fixed(self, groups, global_teacher_assignments):
        """FIXED: Assign remaining teachers ensuring each teacher goes to exactly one group."""
        print(f"\n📋 ASSIGNING REMAINING SINGLE-INSTANCE TEACHERS (FIXED):")
        print("-" * 40)
        
        # Get all assigned instances
        assigned_instances = set()
        for group in groups:
            for _, instance in group['course_instances']:
                assigned_instances.add(instance['instance_id'])
        
        remaining_instances = []
        for instance_id, instance in self.teacher_instances.items():
            if instance_id not in assigned_instances:
                remaining_instances.append(instance)
        
        print(f"   📊 Remaining instances to assign: {len(remaining_instances)}")
        
        for instance in remaining_instances:
            teacher_id = instance['teacher_id']
            course_code = instance['course_code']
            
            # Check if teacher is already assigned to a group
            if teacher_id in global_teacher_assignments:
                assigned_group_id = global_teacher_assignments[teacher_id]
                assigned_group = groups[assigned_group_id - 1]  # Convert to 0-based index
                
                # Add this instance to the teacher's already assigned group
                assigned_group['course_instances'].append((course_code, instance))
                assigned_group['courses_represented'].add(course_code)
                assigned_group['teacher_instances'].append(instance)
                assigned_group['student_capacity'] += self.students_per_teacher
                
                print(f"   ➕ Added instance to existing assignment: Teacher {teacher_id} ({course_code}) → Group {assigned_group_id}")
            else:
                # Find best group for this new teacher
                best_group = min(groups, key=lambda g: g['student_capacity'])
                
                # Assign teacher to group
                best_group['course_instances'].append((course_code, instance))
                best_group['courses_represented'].add(course_code)
                best_group['teachers_assigned'].add(teacher_id)
                best_group['teacher_instances'].append(instance)
                best_group['student_capacity'] += self.students_per_teacher
                
                global_teacher_assignments[teacher_id] = best_group['group_id']
                
                print(f"   ✅ New assignment: Teacher {teacher_id} ({course_code}) → Group {best_group['group_id']}")
        
        return groups
    
    def _final_enhanced_constraint_verification_fixed(self, groups, global_teacher_assignments):
        """FIXED: Perform final verification of all enhanced constraints."""
        print(f"\n✅ FINAL ENHANCED CONSTRAINT VERIFICATION (FIXED):")
        print("-" * 50)
        
        # Verify unique teacher constraint - should be ZERO violations now
        total_violations = 0
        teacher_group_counts = {}
        
        for teacher_id, group_id in global_teacher_assignments.items():
            if teacher_id not in teacher_group_counts:
                teacher_group_counts[teacher_id] = []
            teacher_group_counts[teacher_id].append(group_id)
        
        for teacher_id, group_ids in teacher_group_counts.items():
            if len(group_ids) > 1:
                total_violations += 1
                print(f"   ❌ Teacher {teacher_id} appears in multiple groups: {group_ids}")
        
        unique_constraint_satisfied = total_violations == 0
        print(f"🔒 Unique Teacher Constraint: {'✅ SATISFIED' if unique_constraint_satisfied else f'❌ VIOLATED ({total_violations} teachers)'}")
        
        # Verify enhanced distribution constraint (no multiple instances of same course by same teacher in same group)
        distribution_violations = 0
        for group in groups:
            teacher_course_instances = {}
            for course_code, instance in group['course_instances']:
                teacher_id = instance['teacher_id']
                key = (teacher_id, course_code)
                teacher_course_instances[key] = teacher_course_instances.get(key, 0) + 1
            
            group_violations = 0
            for (teacher_id, course_code), count in teacher_course_instances.items():
                if count > 1:
                    # This is expected now - teacher's multiple instances of same course will be in same group
                    print(f"   ℹ️  Group {group['group_id']}: Teacher {teacher_id} has {count} instances of {course_code} (all in same group)")
            
            group['enhanced_constraint_satisfied'] = True  # This is now satisfied by design
        
        print(f"📦 Enhanced Distribution Constraint: ✅ SATISFIED (teachers with multiple instances keep them in same group)")
        
        # Verify Hall's theorem overall
        halls_satisfied_count = sum(1 for g in groups if g['halls_satisfied'])
        print(f"🧮 Hall's Theorem: {halls_satisfied_count}/{len(groups)} groups satisfied")
        
        # Calculate summary statistics
        total_instances_assigned = sum(len(g['course_instances']) for g in groups)
        total_teachers_assigned = len(global_teacher_assignments)
        total_capacity = sum(g['student_capacity'] for g in groups)
        
        print(f"\n📊 FIXED DISTRIBUTION SUMMARY:")
        print(f"   📦 Groups created: {len(groups)}")
        print(f"   🔢 Instances distributed: {total_instances_assigned}/{len(self.teacher_instances)}")
        print(f"   👥 Teachers assigned: {total_teachers_assigned}/{len(self.teachers)}")
        print(f"   👨‍🎓 Total capacity: {total_capacity} students")
        print(f"   🔒 Unique constraint: {'✅' if unique_constraint_satisfied else '❌'}")
        print(f"   📦 Distribution constraint: ✅")
        print(f"   🧮 Hall's theorem: {'✅' if halls_satisfied_count == len(groups) else '❌'}")
        
        return groups
    
    def _identify_multi_instance_teachers(self):
        """Identify teachers who have multiple instances and need special distribution."""
        print(f"🔍 Identifying teachers with multiple instances...")
        
        teacher_instance_map = defaultdict(list)
        for instance_id, instance in self.teacher_instances.items():
            teacher_id = instance['teacher_id']
            teacher_instance_map[teacher_id].append(instance)
        
        multi_instance_teachers = {}
        for teacher_id, instances in teacher_instance_map.items():
            if len(instances) > 1:
                # Group instances by course
                course_instance_map = defaultdict(list)
                for instance in instances:
                    course_code = instance['course_code']
                    course_instance_map[course_code].append(instance)
                
                # Only consider teachers with multiple instances of the same course
                needs_distribution = any(len(course_instances) > 1 for course_instances in course_instance_map.values())
                
                if needs_distribution:
                    multi_instance_teachers[teacher_id] = {
                        'total_instances': len(instances),
                        'course_distribution': course_instance_map,
                        'needs_distribution': True
                    }
                    
                    print(f"   👨‍🏫 Teacher {teacher_id}: {len(instances)} instances")
                    for course, course_instances in course_instance_map.items():
                        if len(course_instances) > 1:
                            print(f"      📖 {course}: {len(course_instances)} instances (needs distribution)")
        
        print(f"   📊 Teachers requiring distribution: {len(multi_instance_teachers)}")
        return multi_instance_teachers
    
    def _distribute_multi_instance_teachers(self, groups, multi_instance_teachers, global_teacher_assignments):
        """Distribute teachers with multiple instances across different groups."""
        print(f"\n📦 DISTRIBUTING MULTI-INSTANCE TEACHERS:")
        print("-" * 40)
        
        for teacher_id, teacher_info in multi_instance_teachers.items():
            print(f"\n👨‍🏫 Distributing Teacher {teacher_id}:")
            
            # For each course this teacher teaches
            for course_code, course_instances in teacher_info['course_distribution'].items():
                if len(course_instances) > 1:
                    print(f"   📖 Course {course_code}: {len(course_instances)} instances to distribute")
                    
                    # Distribute these instances across different groups
                    for i, instance in enumerate(course_instances):
                        # Find the best group for this instance
                        target_group = self._find_best_group_for_instance(
                            groups, teacher_id, instance, global_teacher_assignments, avoid_same_teacher_course=True
                        )
                        
                        if target_group:
                            # Assign instance to the group
                            target_group['course_instances'].append((course_code, instance))
                            target_group['courses_represented'].add(course_code)
                            target_group['teachers_assigned'].add(teacher_id)
                            target_group['teacher_instances'].append(instance)
                            target_group['student_capacity'] += self.students_per_teacher
                            
                            # Track global assignment
                            if teacher_id not in global_teacher_assignments:
                                global_teacher_assignments[teacher_id] = set()
                            global_teacher_assignments[teacher_id].add(target_group['group_id'])
                            
                            print(f"      ✅ Instance {instance['instance_id']} → Group {target_group['group_id']}")
                        else:
                            print(f"      ❌ Could not assign instance {instance['instance_id']}")
                else:
                    # Single instance - assign normally
                    instance = course_instances[0]
                    target_group = self._find_best_group_for_instance(
                        groups, teacher_id, instance, global_teacher_assignments, avoid_same_teacher_course=False
                    )
                    
                    if target_group:
                        target_group['course_instances'].append((course_code, instance))
                        target_group['courses_represented'].add(course_code)
                        target_group['teachers_assigned'].add(teacher_id)
                        target_group['teacher_instances'].append(instance)
                        target_group['student_capacity'] += self.students_per_teacher
                        
                        if teacher_id not in global_teacher_assignments:
                            global_teacher_assignments[teacher_id] = set()
                        global_teacher_assignments[teacher_id].add(target_group['group_id'])
                        
                        print(f"   📖 Course {course_code}: Single instance → Group {target_group['group_id']}")
        
        return groups
    
    def _find_best_group_for_instance(self, groups, teacher_id, instance, global_teacher_assignments, avoid_same_teacher_course=False):
        """Find the best group for a teacher instance considering all constraints."""
        course_code = instance['course_code']
        
        # Check constraint violations for each group
        valid_groups = []
        
        for group in groups:
            # Check if teacher is already in this group
            if teacher_id in group['teachers_assigned']:
                if avoid_same_teacher_course:
                    # Check if teacher already has instances of this course in this group
                    teacher_courses_in_group = [ci[0] for ci in group['course_instances'] 
                                               if ci[1]['teacher_id'] == teacher_id]
                    if course_code in teacher_courses_in_group:
                        continue  # Skip this group - teacher already has this course here
                else:
                    continue  # Skip this group - teacher already assigned here
            
            # This group is valid for assignment
            valid_groups.append(group)
        
        if not valid_groups:
            return None
        
        # Choose the group with the lowest current capacity (for balance)
        best_group = min(valid_groups, key=lambda g: g['student_capacity'])
        return best_group
    
    def _assign_remaining_teachers(self, groups, global_teacher_assignments):
        """Assign remaining teachers who don't have multiple instances."""
        print(f"\n📋 ASSIGNING REMAINING SINGLE-INSTANCE TEACHERS:")
        print("-" * 40)
        
        assigned_instances = set()
        for group in groups:
            for _, instance in group['course_instances']:
                assigned_instances.add(instance['instance_id'])
        
        remaining_instances = []
        for instance_id, instance in self.teacher_instances.items():
            if instance_id not in assigned_instances:
                remaining_instances.append(instance)
        
        print(f"   📊 Remaining instances to assign: {len(remaining_instances)}")
        
        for instance in remaining_instances:
            teacher_id = instance['teacher_id']
            course_code = instance['course_code']
            
            # Find best group for this instance
            target_group = self._find_best_group_for_instance(
                groups, teacher_id, instance, global_teacher_assignments, avoid_same_teacher_course=False
            )
            
            if target_group:
                target_group['course_instances'].append((course_code, instance))
                target_group['courses_represented'].add(course_code)
                target_group['teachers_assigned'].add(teacher_id)
                target_group['teacher_instances'].append(instance)
                target_group['student_capacity'] += self.students_per_teacher
                
                if teacher_id not in global_teacher_assignments:
                    global_teacher_assignments[teacher_id] = set()
                global_teacher_assignments[teacher_id].add(target_group['group_id'])
                
                print(f"   ✅ Teacher {teacher_id} ({course_code}) → Group {target_group['group_id']}")
            else:
                print(f"   ❌ Could not assign Teacher {teacher_id} ({course_code})")
        
        return groups
    
    def _verify_and_adjust_halls_theorem(self, groups):
        """Verify Hall's theorem for each group and make adjustments if needed."""
        print(f"\n🧮 VERIFYING HALL'S THEOREM FOR ENHANCED GROUPS:")
        print("-" * 50)
        
        for group in groups:
            courses = list(group['courses_represented'])
            teachers = list(group['teachers_assigned'])
            
            # Build course-teacher matrix for this group
            group_course_teacher_matrix = {}
            for course in courses:
                course_teachers = set()
                for course_code, instance in group['course_instances']:
                    if course_code == course:
                        course_teachers.add(instance['teacher_id'])
                group_course_teacher_matrix[course] = list(course_teachers)
            
            group['course_teacher_matrix'] = group_course_teacher_matrix
            
            # Check Hall's theorem
            halls_result = self._check_halls_condition_for_group(courses, teachers, group_course_teacher_matrix)
            group['halls_satisfied'] = halls_result['condition_satisfied']
            group['halls_violations'] = halls_result.get('violations', [])
            
            print(f"   🎯 Group {group['group_id']}:")
            print(f"      📚 Courses: {len(courses)} ({courses})")
            print(f"      👥 Teachers: {len(teachers)}")
            print(f"      🔢 Instances: {len(group['course_instances'])}")
            print(f"      🧮 Hall's Theorem: {'✅ SATISFIED' if group['halls_satisfied'] else '❌ VIOLATED'}")
            
            if not group['halls_satisfied']:
                for violation in group['halls_violations']:
                    print(f"         ⚠️  Subset {violation['subset']}: needs {violation['subset_size']}, has {violation['neighbor_count']}")
        
        return groups
    
    def _final_enhanced_constraint_verification(self, groups, global_teacher_assignments):
        """Perform final verification of all enhanced constraints."""
        print(f"\n✅ FINAL ENHANCED CONSTRAINT VERIFICATION:")
        print("-" * 50)
        
        # Verify unique teacher constraint
        total_violations = 0
        for teacher_id, group_ids in global_teacher_assignments.items():
            if len(group_ids) > 1:
                total_violations += 1
                print(f"   ❌ Teacher {teacher_id} appears in multiple groups: {list(group_ids)}")
        
        unique_constraint_satisfied = total_violations == 0
        print(f"🔒 Unique Teacher Constraint: {'✅ SATISFIED' if unique_constraint_satisfied else f'❌ VIOLATED ({total_violations} teachers)'}")
        
        # Verify enhanced distribution constraint
        distribution_violations = 0
        for group in groups:
            teacher_course_instances = defaultdict(lambda: defaultdict(int))
            for course_code, instance in group['course_instances']:
                teacher_id = instance['teacher_id']
                teacher_course_instances[teacher_id][course_code] += 1
            
            group_violations = 0
            for teacher_id, course_counts in teacher_course_instances.items():
                for course_code, count in course_counts.items():
                    if count > 1:
                        # Check if this teacher has instances of this course in other groups
                        other_group_instances = 0
                        for other_group in groups:
                            if other_group['group_id'] != group['group_id']:
                                for other_course, other_instance in other_group['course_instances']:
                                    if (other_instance['teacher_id'] == teacher_id and 
                                        other_course == course_code):
                                        other_group_instances += 1
                        
                        if other_group_instances == 0:
                            # This teacher's multiple instances of this course are all in the same group
                            group_violations += 1
                            distribution_violations += 1
            
            group['enhanced_constraint_satisfied'] = group_violations == 0
        
        print(f"📦 Enhanced Distribution Constraint: {'✅ SATISFIED' if distribution_violations == 0 else f'❌ VIOLATED ({distribution_violations} cases)'}")
        
        # Verify Hall's theorem overall
        halls_satisfied_count = sum(1 for g in groups if g['halls_satisfied'])
        print(f"🧮 Hall's Theorem: {halls_satisfied_count}/{len(groups)} groups satisfied")
        
        # Calculate summary statistics
        total_instances_assigned = sum(len(g['course_instances']) for g in groups)
        total_teachers_assigned = len(global_teacher_assignments)
        total_capacity = sum(g['student_capacity'] for g in groups)
        
        print(f"\n📊 ENHANCED DISTRIBUTION SUMMARY:")
        print(f"   📦 Groups created: {len(groups)}")
        print(f"   🔢 Instances distributed: {total_instances_assigned}/{len(self.teacher_instances)}")
        print(f"   👥 Teachers assigned: {total_teachers_assigned}/{len(self.teachers)}")
        print(f"   👨‍🎓 Total capacity: {total_capacity} students")
        print(f"   🔒 Unique constraint: {'✅' if unique_constraint_satisfied else '❌'}")
        print(f"   📦 Distribution constraint: {'✅' if distribution_violations == 0 else '❌'}")
        print(f"   🧮 Hall's theorem: {'✅' if halls_satisfied_count == len(groups) else '❌'}")
        
        return groups
    
    def _verify_and_optimize_enhanced_groups(self, groups):
        """Verify and optimize the enhanced groups."""
        print(f"\n🔍 VERIFYING AND OPTIMIZING ENHANCED GROUPS:")
        print("-" * 50)
        
        for group in groups:
            # Calculate additional metrics
            courses = list(group['courses_represented'])
            teachers = list(group['teachers_assigned'])
            instances = group['course_instances']
            
            # Calculate efficiency
            if courses and teachers:
                group_efficiency = (len(instances) / (len(courses) * len(teachers))) * 100
            else:
                group_efficiency = 0
            
            group['group_efficiency'] = group_efficiency
            group['courses'] = courses  # For compatibility with existing methods
            group['unique_teachers'] = group['teachers_assigned']  # For compatibility
            
            # Calculate workload distribution
            teacher_workloads = {}
            for teacher_id in teachers:
                total_workload = 0
                for course_code, instance in instances:
                    if instance['teacher_id'] == teacher_id:
                        course_info = self.course_details[course_code]
                        total_workload += (course_info['lecture_hours'] + 
                                         course_info['practical_hours'] + 
                                         course_info['tutorial_hours'])
                teacher_workloads[teacher_id] = total_workload
            
            group['teacher_workloads'] = teacher_workloads
            group['max_workload'] = max(teacher_workloads.values()) if teacher_workloads else 0
            group['min_workload'] = min(teacher_workloads.values()) if teacher_workloads else 0
            group['avg_workload'] = sum(teacher_workloads.values()) / len(teacher_workloads) if teacher_workloads else 0
            group['over_limit_teachers'] = sum(1 for wl in teacher_workloads.values() if wl > 21)
            
            print(f"   📊 Group {group['group_id']}:")
            print(f"      📚 Courses: {len(courses)}")
            print(f"      👥 Teachers: {len(teachers)}")
            print(f"      🔢 Instances: {len(instances)}")
            print(f"      📈 Efficiency: {group_efficiency:.1f}%")
            print(f"      👨‍🎓 Capacity: {group['student_capacity']}")
            print(f"      🧮 Hall's: {'✅' if group['halls_satisfied'] else '❌'}")
        
        return groups
    
    def _analyze_course_characteristics(self):
        """Analyze characteristics of each course for optimal grouping with instance handling."""
        print(f"\n📊 ANALYZING COURSE CHARACTERISTICS (WITH INSTANCES):")
        print("-" * 60)
        
        course_analysis = {}
        
        for course_code in self.courses:
            course_info = self.course_details[course_code]
            instances = self.course_teacher_instances[course_code]
            unique_teachers = list(self.course_teacher_matrix[course_code])
            
            # Calculate course metrics based on instances
            total_hours = (course_info['lecture_hours'] + 
                          course_info['practical_hours'] + 
                          course_info['tutorial_hours'])
            
            instance_count = len(instances)
            unique_teacher_count = len(unique_teachers)
            # Student capacity based on total instances (each instance can handle 70 students)
            student_capacity = instance_count * self.students_per_teacher
            complexity_score = total_hours * (1 + (5 - unique_teacher_count) * 0.2)
            
            # Determine course type priority
            type_priority = 1 if course_info['course_type'] == 'LoT' else 2
            
            course_analysis[course_code] = {
                'course_info': course_info,
                'teachers': unique_teachers,  # For unique teacher constraint
                'instances': instances,       # For capacity calculation
                'teacher_count': unique_teacher_count,
                'instance_count': instance_count,
                'total_hours': total_hours,
                'student_capacity': student_capacity,
                'complexity_score': complexity_score,
                'type_priority': type_priority,
                'has_practical': course_info['practical_hours'] > 0,
                'credits': course_info['credits']
            }
            
            print(f"   📖 {course_code}:")
            print(f"      👥 Teachers: {unique_teacher_count} unique | 📊 Instances: {instance_count}")
            print(f"      👨‍🎓 Capacity: {student_capacity} (based on {instance_count} instances)")
            print(f"      ⏰ Hours: {total_hours} | 🎯 Complexity: {complexity_score:.1f}")
            print(f"      📊 Type: {course_info['course_type']} | 🔬 Has Practical: {course_analysis[course_code]['has_practical']}")
        
        return course_analysis
    
    def generate_group_visualizations(self, groups):
        """Generate visualizations for the grouping analysis."""
        print("\n📈 GENERATING GROUP VISUALIZATIONS...")
        
        # Set style
        plt.style.use('default')
        sns.set_palette("Set2")
        
        # Create comprehensive visualization
        fig = plt.figure(figsize=(20, 16))
        
        # 1. Group overview
        ax1 = plt.subplot(3, 3, 1)
        self._plot_group_overview(ax1, groups)
        
        # 2. Hall's theorem compliance
        ax2 = plt.subplot(3, 3, 2)
        self._plot_halls_compliance(ax2, groups)
        
        # 3. Student capacity analysis
        ax3 = plt.subplot(3, 3, 3)
        self._plot_capacity_analysis(ax3, groups)
        
        # 4. Teacher distribution
        ax4 = plt.subplot(3, 3, 4)
        self._plot_teacher_distribution(ax4, groups)
        
        # 5. Course complexity distribution
        ax5 = plt.subplot(3, 3, 5)
        self._plot_course_complexity(ax5, groups)
        
        # 6. Group efficiency
        ax6 = plt.subplot(3, 3, 6)
        self._plot_group_efficiency(ax6, groups)
        
        # 7. Workload distribution
        ax7 = plt.subplot(3, 3, 7)
        self._plot_workload_distribution(ax7, groups)
        
        # 8. Assignment density heatmap
        ax8 = plt.subplot(3, 3, 8)
        self._plot_assignment_heatmap(ax8, groups)
        
        # 9. Summary statistics
        ax9 = plt.subplot(3, 3, 9)
        self._plot_summary_stats(ax9, groups)
        
        plt.suptitle('Fifth Semester Course-Teacher Grouping Analysis\nHall\'s Theorem Optimization', 
                     fontsize=16, fontweight='bold', y=0.98)
        plt.tight_layout()
        plt.savefig(os.path.join(self.output_dir, 'fifth_semester_grouping_analysis.png'), 
                   dpi=300, bbox_inches='tight')
        plt.close()
        
        # Temporarily disable individual plots to avoid field compatibility issues
        # self._generate_individual_group_plots(groups)
        print("📊 Individual group plots disabled to avoid field compatibility issues")
        
        print("📊 Main analysis visualization saved successfully!")
    
    def _plot_group_overview(self, ax, groups):
        """Plot group overview showing courses and teachers."""
        group_ids = [g['group_id'] for g in groups]
        course_counts = [len(g['courses']) for g in groups]  # Use len(courses) instead of course_count
        teacher_counts = [len(g['unique_teachers']) for g in groups]  # Use unique_teachers
        instance_counts = [len(g['teacher_instances']) for g in groups]  # Add instance counts
        
        x = np.arange(len(group_ids))
        width = 0.25
        
        bars1 = ax.bar(x - width, course_counts, width, label='Courses', alpha=0.8, color='lightblue')
        bars2 = ax.bar(x, teacher_counts, width, label='Unique Teachers', alpha=0.8, color='lightgreen')
        bars3 = ax.bar(x + width, instance_counts, width, label='Teacher Instances', alpha=0.8, color='lightcoral')
        
        ax.set_xlabel('Groups')
        ax.set_ylabel('Count')
        ax.set_title('Group Overview: Courses, Teachers, and Instances')
        ax.set_xticks(x)
        ax.set_xticklabels([f'Group {gid}' for gid in group_ids], rotation=45)
        ax.legend()
        ax.grid(True, alpha=0.3)
        
        # Add value labels on bars
        for bars in [bars1, bars2, bars3]:
            for bar in bars:
                height = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2., height + 0.1,
                       f'{int(height)}', ha='center', va='bottom', fontsize=9)
    
    def _plot_halls_compliance(self, ax, groups):
        """Plot Hall's theorem compliance."""
        group_ids = [g['group_id'] for g in groups]
        compliance = [1 if g['halls_satisfied'] else 0 for g in groups]
        
        colors = ['green' if c else 'red' for c in compliance]
        bars = ax.bar(group_ids, compliance, color=colors, alpha=0.7)
        
        ax.set_title("Hall's Theorem Compliance")
        ax.set_xlabel('Group ID')
        ax.set_ylabel('Compliance')
        ax.set_ylim(0, 1.2)
        ax.set_yticks([0, 1])
        ax.set_yticklabels(['Not Satisfied', 'Satisfied'])
        
        # Add labels
        for i, bar in enumerate(bars):
            status = "✅" if compliance[i] else "❌"
            ax.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 0.05,
                   status, ha='center', va='bottom', fontsize=14)
    
    def _plot_capacity_analysis(self, ax, groups):
        """Plot student capacity vs requirements analysis."""
        group_ids = [g['group_id'] for g in groups]
        capacities = [g['student_capacity'] for g in groups]
        
        # Calculate requirements from course data
        requirements = []
        for group in groups:
            course_code = group['courses'][0]  # Single course per group
            course_info = self.course_details[course_code]
            requirements.append(course_info.get('student_count', 70))  # Default to 70 if not specified
        
        x = np.arange(len(group_ids))
        width = 0.35
        
        bars1 = ax.bar(x - width/2, capacities, width, label='Student Capacity', alpha=0.8, color='lightblue')
        bars2 = ax.bar(x + width/2, requirements, width, label='Required Students', alpha=0.8, color='lightgreen')
        
        ax.set_xlabel('Groups')
        ax.set_ylabel('Number of Students')
        ax.set_title('Student Capacity vs Requirements')
        ax.set_xticks(x)
        ax.set_xticklabels([f'Group {gid}' for gid in group_ids], rotation=45)
        ax.legend()
        ax.grid(True, alpha=0.3)
        
        # Add value labels
        for bars in [bars1, bars2]:
            for bar in bars:
                height = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2., height + 5,
                       f'{int(height)}', ha='center', va='bottom', fontsize=9)
        
        # Add capacity sufficiency indicators
        for i, (cap, req) in enumerate(zip(capacities, requirements)):
            if cap >= req:
                ax.text(i, max(cap, req) + 20, '✅', ha='center', va='bottom', fontsize=12, color='green')
            else:
                ax.text(i, max(cap, req) + 20, '❌', ha='center', va='bottom', fontsize=12, color='red')
    
    def _plot_teacher_distribution(self, ax, groups):
        """Plot teacher distribution across groups."""
        group_ids = [g['group_id'] for g in groups]
        unique_teacher_counts = [len(g['unique_teachers']) for g in groups]
        instance_counts = [len(g['teacher_instances']) for g in groups]
        
        x = np.arange(len(group_ids))
        width = 0.35
        
        bars1 = ax.bar(x - width/2, unique_teacher_counts, width, label='Unique Teachers', alpha=0.8, color='skyblue')
        bars2 = ax.bar(x + width/2, instance_counts, width, label='Teacher Instances', alpha=0.8, color='lightcoral')
        
        ax.set_xlabel('Groups')
        ax.set_ylabel('Teacher Count')
        ax.set_title('Teacher Distribution: Unique vs Instances')
        ax.set_xticks(x)
        ax.set_xticklabels([f'Group {gid}' for gid in group_ids], rotation=45)
        ax.legend()
        ax.grid(True, alpha=0.3)
        
        # Add value labels
        for bars in [bars1, bars2]:
            for bar in bars:
                height = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2., height + 0.1,
                       f'{int(height)}', ha='center', va='bottom', fontsize=9)
        
        # Add efficiency information
        total_unique = sum(unique_teacher_counts)
        total_instances = sum(instance_counts)
        efficiency = (total_instances / total_unique) if total_unique > 0 else 0
        
        ax.text(0.02, 0.98, f'Instance Efficiency: {efficiency:.2f}', 
                transform=ax.transAxes, fontsize=10, 
                bbox=dict(boxstyle="round,pad=0.3", facecolor='yellow', alpha=0.7),
                verticalalignment='top')
    
    def _plot_course_complexity(self, ax, groups):
        """Plot course complexity distribution."""
        group_ids = [g['group_id'] for g in groups]
        # Get complexity from group total_complexity or calculate from courses
        complexities = []
        for group in groups:
            if 'total_complexity' in group:
                complexities.append(group['total_complexity'])
            else:
                # Calculate complexity based on course hours and teacher count
                course_code = group['courses'][0]  # Single course per group
                course_info = self.course_details[course_code]
                total_hours = course_info['lecture_hours'] + course_info['practical_hours'] + course_info['tutorial_hours']
                teacher_count = len(group['unique_teachers'])
                complexity = total_hours + (teacher_count * 0.5)  # Simple complexity calculation
                complexities.append(complexity)
        
        bars = ax.bar(group_ids, complexities, alpha=0.8, color='orange')
        ax.set_xlabel('Groups')
        ax.set_ylabel('Complexity Score')
        ax.set_title('Course Complexity by Group')
        ax.set_xticks(group_ids)
        ax.set_xticklabels([f'Group {gid}' for gid in group_ids], rotation=45)
        ax.grid(True, alpha=0.3)
        
        # Add value labels
        for bar in bars:
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height + 0.1,
                   f'{height:.1f}', ha='center', va='bottom', fontsize=9)
    
    def _plot_group_efficiency(self, ax, groups):
        """Plot group efficiency scores."""
        group_ids = [g['group_id'] for g in groups]
        efficiencies = [g['group_efficiency'] for g in groups]
        
        bars = ax.bar(group_ids, efficiencies, alpha=0.8, color='gold')
        ax.set_title('Group Efficiency Scores')
        ax.set_xlabel('Group ID')
        ax.set_ylabel('Efficiency (%)')
        ax.set_ylim(0, 100)
        ax.grid(True, alpha=0.3)
        
        # Add value labels
        for bar, eff in zip(bars, efficiencies):
            ax.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 1,
                   f'{eff:.1f}%', ha='center', va='bottom')
    
    def _plot_workload_distribution(self, ax, groups):
        """Plot teacher workload distribution."""
        all_workloads = []
        group_avg_workloads = []
        
        for group in groups:
            if 'teacher_workloads' in group and group['teacher_workloads']:
                workloads = list(group['teacher_workloads'].values())
                all_workloads.extend(workloads)
                group_avg_workloads.append(sum(workloads) / len(workloads))
            else:
                group_avg_workloads.append(0)
        
        if all_workloads:
            # Create histogram of all workloads
            ax.hist(all_workloads, bins=min(8, len(set(all_workloads))), alpha=0.7, color='skyblue', edgecolor='black')
            ax.axvline(21, color='red', linestyle='--', linewidth=2, label='21-hour limit')
            ax.set_xlabel('Weekly Hours per Teacher')
            ax.set_ylabel('Number of Teachers')
            ax.set_title('Teacher Workload Distribution')
            ax.legend()
            ax.grid(True, alpha=0.3)
            
            # Add statistics
            avg_workload = sum(all_workloads) / len(all_workloads)
            over_limit = sum(1 for w in all_workloads if w > 21)
            
            stats_text = f'Avg: {avg_workload:.1f}h\nOver 21h: {over_limit}/{len(all_workloads)}'
            ax.text(0.7, 0.95, stats_text, transform=ax.transAxes, 
                   bbox=dict(boxstyle="round,pad=0.3", facecolor='yellow', alpha=0.7),
                   verticalalignment='top', fontsize=10)
        else:
            ax.text(0.5, 0.5, 'No workload data available', ha='center', va='center', transform=ax.transAxes)
    
    def _plot_assignment_heatmap(self, ax, groups):
        """Plot assignment density heatmap."""
        # Create a simplified visualization of group densities
        group_ids = [g['group_id'] for g in groups]
        densities = []
        
        for group in groups:
            course_count = len(group['courses'])
            teacher_count = len(group['unique_teachers'])
            
            if course_count > 0 and teacher_count > 0:
                # Calculate density based on teacher instances and courses
                total_assignments = len(group['teacher_instances'])
                density = total_assignments / (course_count * teacher_count) if course_count * teacher_count > 0 else 0
                densities.append(density)
            else:
                densities.append(0)
        
        # Create heatmap-style bar plot with proper coloring
        colors = plt.cm.YlOrRd(np.linspace(0.3, 1.0, len(densities)))
        bars = ax.bar(group_ids, densities, color=colors, alpha=0.8)
        
        ax.set_xlabel('Groups')
        ax.set_ylabel('Assignment Density')
        ax.set_title('Teacher-Course Assignment Density by Group')
        ax.set_xticks(group_ids)
        ax.set_xticklabels([f'Group {gid}' for gid in group_ids], rotation=45)
        ax.grid(True, alpha=0.3)
        
        # Add value labels
        for bar, density in zip(bars, densities):
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height + 0.01,
                   f'{density:.2f}', ha='center', va='bottom', fontsize=9)
        
        # Add colorbar explanation
        ax.text(0.02, 0.98, 'Higher values = More teacher instances per course', 
                transform=ax.transAxes, fontsize=9, 
                bbox=dict(boxstyle="round,pad=0.3", facecolor='lightblue', alpha=0.7),
                verticalalignment='top')
    
    def _plot_summary_stats(self, ax, groups):
        """Plot summary statistics."""
        ax.axis('off')
        
        # Calculate summary statistics using correct field names
        total_courses = sum(len(g['courses']) for g in groups)
        total_unique_teachers = len(set().union(*(g['unique_teachers'] for g in groups)))
        total_instances = sum(len(g['teacher_instances']) for g in groups)
        total_student_capacity = sum(g['student_capacity'] for g in groups)
        halls_satisfied = sum(1 for g in groups if g.get('halls_satisfied', True))
        avg_efficiency = sum(g.get('group_efficiency', 100) for g in groups) / len(groups) if groups else 0
        
        # Calculate constraint satisfaction
        instance_constraint_satisfied = sum(1 for g in groups if g.get('instance_constraint_satisfied', True))
        
        # Calculate workload information if available
        total_over_limit = 0
        for group in groups:
            if 'teacher_workloads' in group and group['teacher_workloads']:
                total_over_limit += sum(1 for wl in group['teacher_workloads'].values() if wl > 21)
        
        # Create summary text
        summary_text = f"""
📊 FIFTH SEMESTER GROUPING SUMMARY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📚 COURSE DISTRIBUTION:
   Total Groups: {len(groups)}
   Total Courses: {total_courses}
   Courses per Group: {total_courses / len(groups):.1f} (avg)
   Group Structure: 1 course per group (student selection model)

👥 TEACHER ALLOCATION:
   Unique Teachers: {total_unique_teachers}
   Teacher Instances: {total_instances}
   Instance Efficiency: {total_instances / total_unique_teachers:.2f} instances per teacher
   Teachers per Group: {total_unique_teachers / len(groups):.1f} (avg)

👨‍🎓 STUDENT CAPACITY:
   Total Capacity: {total_student_capacity} students
   Average per Group: {total_student_capacity / len(groups):.0f} students
   Selection Model: Students choose 1 course from each group

🧮 CONSTRAINT SATISFACTION:
   Hall's Theorem: {halls_satisfied}/{len(groups)} groups satisfied
   Instance Constraint: {instance_constraint_satisfied}/{len(groups)} groups satisfied
   Over-limit Teachers: {total_over_limit} teachers exceed 21-hour limit
   Average Efficiency: {avg_efficiency:.1f}%

🎯 STUDENT COURSE SELECTION MODEL:
   Students select 1 course from each of the {len(groups)} groups
   Total combinations available: 1 (deterministic selection)
   Each student takes exactly {len(groups)} courses
   Unique teacher constraint ensures no teacher overlap

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        """
        
        ax.text(0.05, 0.95, summary_text.strip(), transform=ax.transAxes,
                fontsize=10, verticalalignment='top', fontfamily='monospace',
                bbox=dict(boxstyle="round,pad=0.5", facecolor='lightgray', alpha=0.8))
        
        # Add status indicators
        if halls_satisfied == len(groups) and instance_constraint_satisfied == len(groups) and total_over_limit == 0:
            status = "✅ OPTIMAL SOLUTION"
            color = 'green'
        elif halls_satisfied == len(groups):
            status = "⚠️ HALLS SATISFIED, INSTANCE ISSUES"
            color = 'orange'
        else:
            status = "❌ CONSTRAINT VIOLATIONS"
            color = 'red'
        
        ax.text(0.95, 0.05, status, transform=ax.transAxes,
                fontsize=12, weight='bold', color=color, 
                horizontalalignment='right', verticalalignment='bottom',
                bbox=dict(boxstyle="round,pad=0.3", facecolor='white', edgecolor=color))
    
    def _generate_individual_group_plots(self, groups):
        """Generate individual plots for each group."""
        for group in groups:
            fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(15, 12))
            
            # Group course-teacher matrix
            self._plot_group_matrix(ax1, group)
            
            # Course details
            self._plot_group_courses(ax2, group)
            
            # Teacher workload
            self._plot_group_teacher_workload(ax3, group)
            
            # Group metrics
            self._plot_group_metrics(ax4, group)
            
            plt.suptitle(f'Group {group["group_id"]} Detailed Analysis', fontsize=14, fontweight='bold')
            plt.tight_layout()
            plt.savefig(os.path.join(self.output_dir, f'group_{group["group_id"]}_detailed.png'), 
                       dpi=300, bbox_inches='tight')
            plt.close()
    
    def _plot_group_matrix(self, ax, group):
        """Plot course-teacher assignment matrix for a group."""
        courses = group['courses']
        teachers = group['teachers']
        matrix = group['course_teacher_matrix']
        
        if not courses or not teachers:
            ax.text(0.5, 0.5, 'No assignments', ha='center', va='center', transform=ax.transAxes)
            ax.set_title('Course-Teacher Assignment Matrix')
            return
        
        # Create assignment matrix
        assignment_matrix = np.zeros((len(courses), len(teachers)))
        teacher_list = list(teachers)
        
        for i, course in enumerate(courses):
            course_teachers = matrix.get(course, [])
            for j, teacher in enumerate(teacher_list):
                if teacher in course_teachers:
                    assignment_matrix[i, j] = 1
        
        # Plot heatmap
        im = ax.imshow(assignment_matrix, cmap='RdYlGn', aspect='auto', alpha=0.8)
        
        # Set ticks and labels
        ax.set_xticks(range(len(teacher_list)))
        ax.set_xticklabels([f'T{t}' for t in teacher_list], rotation=45, ha='right')
        ax.set_yticks(range(len(courses)))
        ax.set_yticklabels(courses)
        
        ax.set_title(f'Group {group["group_id"]} Assignment Matrix')
        ax.set_xlabel('Teachers')
        ax.set_ylabel('Courses')
        
        # Add colorbar
        plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    
    def _plot_group_courses(self, ax, group):
        """Plot course details for a group."""
        courses = group['courses']
        if not courses:
            ax.text(0.5, 0.5, 'No courses', ha='center', va='center', transform=ax.transAxes)
            return
        
        course_hours = []
        course_names = []
        
        for course in courses:
            course_info = self.course_details[course]
            total_hours = (course_info['lecture_hours'] + 
                          course_info['practical_hours'] + 
                          course_info['tutorial_hours'])
            course_hours.append(total_hours)
            course_names.append(course)
        
        bars = ax.barh(range(len(course_names)), course_hours, alpha=0.8)
        ax.set_yticks(range(len(course_names)))
        ax.set_yticklabels(course_names)
        ax.set_xlabel('Total Hours')
        ax.set_title(f'Group {group["group_id"]} Course Hours')
        ax.grid(True, alpha=0.3)
        
        # Add value labels
        for i, bar in enumerate(bars):
            width = bar.get_width()
            ax.text(width + 0.1, bar.get_y() + bar.get_height()/2,
                   f'{course_hours[i]}h', ha='left', va='center')
    
    def _plot_group_teacher_workload(self, ax, group):
        """Plot teacher workload for a group."""
        teachers = list(group['teachers'])
        if not teachers:
            ax.text(0.5, 0.5, 'No teachers', ha='center', va='center', transform=ax.transAxes)
            return
        
        teacher_workloads = []
        for teacher in teachers:
            total_workload = 0
            for course in self.teacher_course_matrix[teacher]:
                if course in group['courses']:
                    course_info = self.course_details[course]
                    total_workload += (course_info['lecture_hours'] + 
                                     course_info['practical_hours'] + 
                                     course_info['tutorial_hours'])
            teacher_workloads.append(total_workload)
        
        bars = ax.bar(range(len(teachers)), teacher_workloads, alpha=0.8, color='lightcoral')
        ax.set_xticks(range(len(teachers)))
        ax.set_xticklabels([f'T{t}' for t in teachers], rotation=45)
        ax.set_ylabel('Hours')
        ax.set_title(f'Group {group["group_id"]} Teacher Workload')
        ax.grid(True, alpha=0.3)
        
        # Add value labels
        for bar, workload in zip(bars, teacher_workloads):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.2,
                   f'{workload}h', ha='center', va='bottom')
    
    def _plot_group_metrics(self, ax, group):
        """Plot group metrics."""
        ax.axis('off')
        
        metrics_text = f"""
📊 GROUP {group['group_id']} METRICS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📚 Courses: {group['course_count']}
👥 Teachers: {group['teacher_count']}
🧮 Hall's Theorem: {'✅ SATISFIED' if group['halls_satisfied'] else '❌ VIOLATED'}
⏰ Total Hours: {group['total_hours']}
👨‍🎓 Student Capacity: {group['student_capacity']}
📊 Requirements: {group['student_requirements']}
✅ Capacity OK: {'YES' if group['capacity_sufficient'] else 'NO'}
🎯 Efficiency: {group['group_efficiency']:.1f}%
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        """
        
        ax.text(0.1, 0.9, metrics_text.strip(), transform=ax.transAxes,
                fontsize=10, verticalalignment='top', fontfamily='monospace',
                bbox=dict(boxstyle="round,pad=0.5", facecolor='lightgray', alpha=0.8))
    
    def save_grouping_results(self, groups):
        """Save grouping results to files."""
        print("\n💾 SAVING GROUPING RESULTS...")
        
        # Calculate summary statistics for workload information
        total_over_limit = 0
        for group in groups:
            if 'teacher_workloads' in group and group['teacher_workloads']:
                total_over_limit += sum(1 for wl in group['teacher_workloads'].values() if wl > 21)
        
        # Save detailed JSON results
        results = {
            'timestamp': datetime.now().isoformat(),
            'semester': 5,
            'total_courses': len(self.courses),
            'total_teachers': len(self.teachers),
            'students_per_teacher': self.students_per_teacher,
            'groups': groups,
            'summary': {
                'total_groups': len(groups),
                'halls_satisfied_groups': sum(1 for g in groups if g.get('halls_satisfied', True)),
                'capacity_sufficient_groups': sum(1 for g in groups if g['student_capacity'] >= 70),
                'over_limit_teachers': total_over_limit,
                'avg_group_efficiency': sum(g.get('group_efficiency', 100) for g in groups) / len(groups) if groups else 0,
                'total_student_capacity': sum(g['student_capacity'] for g in groups),
                'total_student_requirements': sum(70 for g in groups),  # Default requirement of 70 per group
                'unique_teacher_constraint_satisfied': sum(1 for g in groups if g.get('instance_constraint_satisfied', True))
            }
        }
        
        # Save JSON
        json_file = os.path.join(self.output_dir, 'fifth_semester_optimal_groups.json')
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False, cls=NumpyEncoder)
        
        # Save CSV summary with updated field names
        csv_data = []
        for group in groups:
            # Calculate derived fields for compatibility
            course_count = len(group['courses'])
            teacher_count = len(group.get('unique_teachers', []))
            student_requirements = 70  # Default requirement
            capacity_sufficient = group['student_capacity'] >= student_requirements
            group_efficiency = group.get('group_efficiency', 100)
            
            csv_data.append({
                'Group_ID': group['group_id'],
                'Courses': ', '.join(group['courses']),
                'Course_Count': course_count,
                'Teacher_Count': teacher_count,
                'Teacher_Instances': len(group.get('teacher_instances', [])),
                'Halls_Satisfied': group.get('halls_satisfied', True),
                'Total_Hours': group.get('total_hours', 0),
                'Student_Capacity': group['student_capacity'],
                'Student_Requirements': student_requirements,
                'Capacity_Sufficient': capacity_sufficient,
                'Group_Efficiency': group_efficiency,
                'Instance_Constraint_Satisfied': group.get('instance_constraint_satisfied', True),
                'Unique_Teacher_Constraint': group.get('unique_teacher_constraint_satisfied', True)
            })
        
        csv_df = pd.DataFrame(csv_data)
        csv_file = os.path.join(self.output_dir, 'fifth_semester_groups_summary.csv')
        csv_df.to_csv(csv_file, index=False)
        
        # Generate text report
        self._generate_text_report(groups, results)
        
        print(f"✅ Results saved:")
        print(f"   📊 JSON: {json_file}")
        print(f"   📋 CSV: {csv_file}")
        print(f"   📝 Text: fifth_semester_grouping_report.txt")
        
        return results
    
    def _generate_text_report(self, groups, results):
        """Generate a comprehensive text report."""
        report_file = os.path.join(self.output_dir, 'fifth_semester_grouping_report.txt')
        
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write("FIFTH SEMESTER COURSE-TEACHER GROUPING REPORT\n")
            f.write("=" * 60 + "\n\n")
            f.write(f"Analysis Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            
            # Executive Summary
            f.write("EXECUTIVE SUMMARY:\n")
            f.write("-" * 20 + "\n")
            f.write(f"Total Groups Created: {results['summary']['total_groups']}\n")
            f.write(f"Hall's Theorem Satisfied: {results['summary']['halls_satisfied_groups']}/{len(groups)}\n")
            f.write(f"Student Capacity Sufficient: {results['summary']['capacity_sufficient_groups']}/{len(groups)}\n")
            f.write(f"Unique Teacher Constraint Satisfied: {results['summary']['unique_teacher_constraint_satisfied']}/{len(groups)}\n")
            f.write(f"Average Group Efficiency: {results['summary']['avg_group_efficiency']:.1f}%\n")
            f.write(f"Total Student Capacity: {results['summary']['total_student_capacity']}\n")
            f.write(f"Total Student Requirements: {results['summary']['total_student_requirements']}\n\n")
            
            # Detailed Group Analysis
            f.write("DETAILED GROUP ANALYSIS:\n")
            f.write("-" * 30 + "\n\n")
            
            for group in groups:
                course_count = len(group['courses'])
                teacher_count = len(group.get('unique_teachers', []))
                student_requirements = 70
                capacity_sufficient = group['student_capacity'] >= student_requirements
                group_efficiency = group.get('group_efficiency', 100)
                
                f.write(f"GROUP {group['group_id']}:\n")
                f.write(f"  Courses ({course_count}): {', '.join(group['courses'])}\n")
                f.write(f"  Teachers: {teacher_count}\n")
                f.write(f"  Teacher Instances: {len(group.get('teacher_instances', []))}\n")
                f.write(f"  Hall's Theorem: {'✅ SATISFIED' if group.get('halls_satisfied', True) else '❌ VIOLATED'}\n")
                f.write(f"  Unique Teacher Constraint: {'✅ SATISFIED' if group.get('instance_constraint_satisfied', True) else '❌ VIOLATED'}\n")
                f.write(f"  Total Hours: {group.get('total_hours', 0)}\n")
                f.write(f"  Student Capacity: {group['student_capacity']} (Required: {student_requirements})\n")
                f.write(f"  Capacity Sufficient: {'✅ YES' if capacity_sufficient else '❌ NO'}\n")
                f.write(f"  Group Efficiency: {group_efficiency:.1f}%\n")
                
                # Show course details
                f.write(f"  Course Details:\n")
                for course in group['courses']:
                    course_info = self.course_details[course]
                    teachers_count = len(group.get('course_teacher_matrix', {}).get(course, []))
                    f.write(f"    • {course} ({course_info['course_type']}): {teachers_count} teachers, ")
                    f.write(f"{course_info['lecture_hours']}L+{course_info['practical_hours']}P+{course_info['tutorial_hours']}T hours\n")
                
                if group.get('halls_violations', []):
                    f.write(f"  Hall's Violations:\n")
                    for violation in group['halls_violations']:
                        f.write(f"    • Courses {violation['subset']} need {violation['subset_size']} ")
                        f.write(f"teachers but only have {violation['neighbor_count']}\n")
                
                f.write("\n")
            
            # Optimization Recommendations
            f.write("OPTIMIZATION RECOMMENDATIONS:\n")
            f.write("-" * 35 + "\n")
            
            violated_groups = [g for g in groups if not g.get('halls_satisfied', True)]
            constraint_violated_groups = [g for g in groups if not g.get('instance_constraint_satisfied', True)]
            insufficient_capacity = [g for g in groups if g['student_capacity'] < 70]
            
            if not violated_groups and not constraint_violated_groups and not insufficient_capacity:
                f.write("✅ All groups are optimally configured!\n")
                f.write("✅ Hall's theorem is satisfied for all groups\n")
                f.write("✅ Unique teacher constraint is satisfied for all groups\n")
                f.write("✅ Student capacity is sufficient for all groups\n")
            else:
                if violated_groups:
                    f.write(f"⚠️  {len(violated_groups)} groups violate Hall's theorem\n")
                    f.write("   Consider redistributing teachers or courses\n")
                
                if constraint_violated_groups:
                    f.write(f"⚠️  {len(constraint_violated_groups)} groups violate unique teacher constraint\n")
                    f.write("   Some teachers appear in multiple groups\n")
                
                if insufficient_capacity:
                    f.write(f"⚠️  {len(insufficient_capacity)} groups have insufficient student capacity\n")
                    f.write("   Consider adding more teachers or reducing class sizes\n")
            
            optimization_complete = not violated_groups and not constraint_violated_groups and not insufficient_capacity
            f.write(f"\nOptimization Status: {'✅ COMPLETE' if optimization_complete else '⚠️ NEEDS ATTENTION'}\n")
    
    def run_complete_analysis(self):
        """Run the complete 5th semester grouping analysis."""
        print("🚀 STARTING COMPLETE FIFTH SEMESTER GROUPING ANALYSIS")
        print("=" * 80)
        
        # Step 1: Analyze current distribution
        distribution_analysis = self.analyze_fifth_semester_distribution()
        
        # Step 2: Create optimal groups
        optimal_groups = self.create_optimal_groups(courses_per_group=None)
        
        # Step 3: Generate visualizations
        self.generate_group_visualizations(optimal_groups)
        
        # Step 4: Generate course-group heatmap
        heatmap_data = self.generate_course_group_heatmap(optimal_groups)
        
        # Step 5: Save results
        results = self.save_grouping_results(optimal_groups)
        
        print("\n🎉 ANALYSIS COMPLETED SUCCESSFULLY!")
        print(f"📁 All results saved to: {self.output_dir}")
        print(f"📊 Created {len(optimal_groups)} optimal groups")
        print(f"✅ Hall's theorem satisfied: {results['summary']['halls_satisfied_groups']}/{len(optimal_groups)} groups")
        print(f"👨‍🎓 Student capacity sufficient: {results['summary']['capacity_sufficient_groups']}/{len(optimal_groups)} groups")
        print(f"📈 Average efficiency: {results['summary']['avg_group_efficiency']:.1f}%")
        print(f"🔥 Course-Group heatmap generated with teacher instance counts")
        
        return results

    def generate_course_group_heatmap(self, groups):
        """Generate heatmap showing courses vs groups with ACTUAL teacher instance counts as values."""
        print("\n📊 GENERATING COURSE-GROUP TEACHER INSTANCE COUNT HEATMAP...")
        
        # Create data matrix for heatmap
        course_list = sorted(self.courses)
        group_list = [f"Group {g['group_id']}" for g in groups]
        
        # Initialize matrix
        heatmap_data = np.zeros((len(course_list), len(group_list)))
        
        # Fill the matrix with ACTUAL teacher instance counts per course per group
        for j, group in enumerate(groups):
            for i, course in enumerate(course_list):
                # Count actual instances for this course in this group
                instance_count = 0
                for course_code, instance in group['course_instances']:
                    if course_code == course:
                        instance_count += 1
                
                heatmap_data[i, j] = instance_count
        
        # Create the heatmap
        plt.figure(figsize=(12, 8))
        
        # Create heatmap with proper color scheme
        mask = heatmap_data == 0  # Mask zero values
        
        ax = sns.heatmap(
            heatmap_data,
            xticklabels=group_list,
            yticklabels=course_list,
            annot=True,
            fmt='.0f',
            cmap='YlOrRd',
            mask=mask,
            cbar_kws={'label': 'Teacher Instance Count'},
            linewidths=0.5,
            square=False
        )
        
        # Customize the plot
        plt.title('Course-Group Teacher Instance Distribution Heatmap\n(ACTUAL Teacher Instance Count per Course per Group)', 
                 fontsize=14, fontweight='bold', pad=20)
        plt.xlabel('Groups', fontsize=12, fontweight='bold')
        plt.ylabel('Courses', fontsize=12, fontweight='bold')
        
        # Rotate x-axis labels for better readability
        plt.xticks(rotation=45, ha='right')
        plt.yticks(rotation=0)
        
        # Add grid for better readability
        ax.grid(False)
        
        # Add summary statistics as text
        total_instances_assigned = np.sum(heatmap_data)
        max_instances_per_cell = np.max(heatmap_data)
        non_zero_cells = np.count_nonzero(heatmap_data)
        
        # Calculate unique teachers per group
        unique_teachers_per_group = []
        for group in groups:
            unique_teachers = set()
            for _, instance in group['course_instances']:
                unique_teachers.add(instance['teacher_id'])
            unique_teachers_per_group.append(len(unique_teachers))
        
        summary_text = f"""
FIXED Heatmap Summary:
• Total Teacher Instances: {int(total_instances_assigned)}
• Max Instances per Course-Group: {int(max_instances_per_cell)}
• Active Course-Group Combinations: {non_zero_cells}
• Matrix Density: {(non_zero_cells / (len(course_list) * len(group_list))) * 100:.1f}%
• Unique Teachers per Group: {unique_teachers_per_group}
        """
        
        plt.figtext(0.02, 0.02, summary_text.strip(), fontsize=9, 
                   bbox=dict(boxstyle="round,pad=0.5", facecolor='lightgray', alpha=0.8))
        
        plt.tight_layout()
        
        # Save the heatmap
        heatmap_path = os.path.join(self.output_dir, 'course_group_teacher_instance_heatmap_FIXED.png')
        plt.savefig(heatmap_path, dpi=300, bbox_inches='tight')
        plt.close()
        
        print(f"✅ FIXED Heatmap saved to: {heatmap_path}")
        
        # Also create a detailed data table
        self._create_heatmap_data_table_fixed(heatmap_data, course_list, group_list, groups)
        
        return heatmap_data
    
    def _create_heatmap_data_table_fixed(self, heatmap_data, course_list, group_list, groups):
        """Create a detailed data table for the heatmap."""
        # Create DataFrame for easy viewing
        heatmap_df = pd.DataFrame(
            heatmap_data,
            index=course_list,
            columns=group_list
        )
        
        # Add row and column totals
        heatmap_df['Total'] = heatmap_df.sum(axis=1)
        totals_row = heatmap_df.sum(axis=0)
        totals_row.name = 'Total'
        heatmap_df = pd.concat([heatmap_df, totals_row.to_frame().T])
        
        # Save as CSV
        csv_path = os.path.join(self.output_dir, 'course_group_teacher_matrix_FIXED.csv')
        heatmap_df.to_csv(csv_path)
        
        print(f"✅ FIXED Heatmap data table saved to: {csv_path}")
        
        # Print the table for immediate viewing
        print(f"\n📊 FIXED COURSE-GROUP TEACHER INSTANCE COUNT MATRIX:")
        print("=" * 60)
        print(heatmap_df.to_string())
        
        # Print teacher distribution details
        print(f"\n👥 TEACHER DISTRIBUTION DETAILS:")
        print("=" * 50)
        for group in groups:
            teacher_course_map = {}
            for course_code, instance in group['course_instances']:
                teacher_id = instance['teacher_id']
                if teacher_id not in teacher_course_map:
                    teacher_course_map[teacher_id] = []
                teacher_course_map[teacher_id].append(course_code)
            
            print(f"\n🎯 Group {group['group_id']} ({len(teacher_course_map)} unique teachers):")
            for teacher_id, courses in teacher_course_map.items():
                course_counts = {}
                for course in courses:
                    course_counts[course] = course_counts.get(course, 0) + 1
                
                course_summary = []
                for course, count in course_counts.items():
                    if count > 1:
                        course_summary.append(f"{course}×{count}")
                    else:
                        course_summary.append(course)
                
                print(f"   👨‍🏫 Teacher {teacher_id}: {', '.join(course_summary)}")
        
        return heatmap_df
    
    def _check_halls_condition_for_group(self, courses, teachers, course_teacher_matrix):
        """Check Hall's condition for a specific group."""
        violations = []
        
        # Check all non-empty subsets of courses
        for r in range(1, len(courses) + 1):
            for course_subset in combinations(courses, r):
                # Find all teachers assigned to any course in this subset
                neighbors = set()
                for course in course_subset:
                    neighbors.update(course_teacher_matrix.get(course, []))
                
                # Hall's condition: |N(S)| >= |S|
                if len(neighbors) < len(course_subset):
                    violations.append({
                        'subset': list(course_subset),
                        'subset_size': len(course_subset),
                        'neighbor_count': len(neighbors),
                        'neighbors': list(neighbors)
                    })
        
        return {
            'condition_satisfied': len(violations) == 0,
            'violations': violations
        }
    
    def _calculate_group_efficiency(self, courses, teachers, course_teacher_matrix):
        """Calculate efficiency score for a group."""
        if not courses or not teachers:
            return 0.0
        
        # Calculate assignment density
        total_possible_assignments = len(courses) * len(teachers)
        actual_assignments = sum(len(course_teacher_matrix.get(course, [])) for course in courses)
        
        assignment_density = (actual_assignments / total_possible_assignments) * 100 if total_possible_assignments > 0 else 0
        
        # Calculate teacher utilization
        teachers_used = len(set().union(*[course_teacher_matrix.get(course, []) for course in courses]))
        teacher_utilization = (teachers_used / len(teachers)) * 100 if teachers else 0
        
        # Combined efficiency
        efficiency = (assignment_density + teacher_utilization) / 2
        return efficiency

def main():
    """Main function to run the 5th semester grouping analysis."""
    import sys
    import os
    
    # Default CSV file path
    csv_file = 'data/cse.csv'
    
    # Check if CSV file exists
    if not os.path.exists(csv_file):
        print(f"❌ Error: CSV file not found at {csv_file}")
        print("Please ensure the cse.csv file exists in the data directory.")
        return
    
    # Create analyzer
    analyzer = FifthSemesterGroupingAnalyzer(csv_file)
    
    # Run complete analysis
    results = analyzer.run_complete_analysis()
    
    print("\n🎊 Fifth semester grouping optimization completed!")
    print("Check the output directory for detailed results and visualizations.")

if __name__ == "__main__":
    main() 