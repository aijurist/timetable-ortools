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
        # DYNAMIC: Set groups = number of courses for optimal Hall's theorem compliance
        num_courses = len(self.courses)
        optimal_group_count = num_courses  # Dynamic: groups = courses for perfect Hall's theorem
        # optimal_group_count = max(3, min(8, total_instances // instances_per_group))  # Original dynamic calculation
        
        print(f"\n📊 Group Configuration (DYNAMIC - COURSES = GROUPS):")
        print(f"   🔢 Total instances to distribute: {total_instances}")
        print(f"   📚 Number of courses: {num_courses}")
        print(f"   📦 Target groups: {optimal_group_count} (DYNAMIC: groups = courses)")
        print(f"   📊 Target instances per group: {instances_per_group}")
        print(f"   🎯 Hall's Theorem Optimal: Each course needs {optimal_group_count} teachers for perfect compliance")
        print(f"   👥 Students per group: {420 // optimal_group_count} students")
        print(f"   📈 Teachers per group: ~{(420 // optimal_group_count)/70:.1f} teachers needed")
        
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
        """CORRECTED: Distribute teacher instances ensuring no teacher appears multiple times in SAME group."""
        print(f"\n📦 DISTRIBUTING MULTI-INSTANCE TEACHERS (CORRECTED CONSTRAINT):")
        print("-" * 40)
        print("🔧 CORRECT CONSTRAINT: No teacher multiple times in SAME group (same time slot)")
        print("✅ ALLOWED: Teacher in different groups (different time slots)")
        
        for teacher_id, teacher_info in multi_instance_teachers.items():
            print(f"\n👨‍🏫 Processing Teacher {teacher_id}:")
            
            for course_code, course_instances in teacher_info['course_distribution'].items():
                print(f"   📖 Course {course_code}: {len(course_instances)} instances to distribute")
                
                for i, instance in enumerate(course_instances):
                    # Find group where this teacher doesn't already appear
                    target_group = self._find_best_group_without_teacher_conflict(
                        groups, teacher_id, instance
                    )
                    
                    if target_group:
                        # Assign instance to the group
                        target_group['course_instances'].append((course_code, instance))
                        target_group['courses_represented'].add(course_code)
                        target_group['teachers_assigned'].add(teacher_id)
                        target_group['teacher_instances'].append(instance)
                        target_group['student_capacity'] += self.students_per_teacher
                        
                        # Track that this teacher is now in this group
                        if teacher_id not in global_teacher_assignments:
                            global_teacher_assignments[teacher_id] = set()
                        global_teacher_assignments[teacher_id].add(target_group['group_id'])
                        
                        print(f"      ✅ Instance {instance['instance_id']} → Group {target_group['group_id']}")
                    else:
                        print(f"      ❌ Could not assign instance {instance['instance_id']}")
        
        return groups
    
    def _find_best_group_without_teacher_conflict(self, groups, teacher_id, instance):
        """Find the best group where teacher doesn't already appear (to avoid same-time conflicts)."""
        course_code = instance['course_code']
        
        # Find groups where this teacher is NOT already assigned
        valid_groups = []
        
        for group in groups:
            # Check if teacher is already in this group (same time slot)
            if teacher_id not in group['teachers_assigned']:
                # This group is valid - teacher not already scheduled in this time slot
                valid_groups.append(group)
            else:
                # Teacher already in this group - would create time conflict
                print(f"      ⚠️  Skipping Group {group['group_id']} - Teacher {teacher_id} already scheduled in this time slot")
        
        if not valid_groups:
            print(f"      ❌ No valid groups found - Teacher {teacher_id} already in all groups")
            return None
        
        # Choose the group with the lowest current capacity (for balance)
        best_group = min(valid_groups, key=lambda g: g['student_capacity'])
        return best_group
    
    def _assign_remaining_teachers_fixed(self, groups, global_teacher_assignments):
        """CORRECTED: Assign remaining teachers ensuring no teacher appears multiple times in same group."""
        print(f"\n📋 ASSIGNING REMAINING SINGLE-INSTANCE TEACHERS (CORRECTED):")
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
            
            # Find best group where this teacher doesn't already appear
            best_group = self._find_best_group_without_teacher_conflict(
                groups, teacher_id, instance
            )
            
            if best_group:
                # Assign teacher to group
                best_group['course_instances'].append((course_code, instance))
                best_group['courses_represented'].add(course_code)
                best_group['teachers_assigned'].add(teacher_id)
                best_group['teacher_instances'].append(instance)
                best_group['student_capacity'] += self.students_per_teacher
                
                # Track assignment
                if teacher_id not in global_teacher_assignments:
                    global_teacher_assignments[teacher_id] = set()
                global_teacher_assignments[teacher_id].add(best_group['group_id'])
                
                print(f"   ✅ Teacher {teacher_id} ({course_code}) → Group {best_group['group_id']}")
            else:
                # Teacher already in all groups - need to extend to more groups
                print(f"   ⚠️  Teacher {teacher_id} ({course_code}) already in all groups - need more groups")
        
        return groups
    
    def _final_enhanced_constraint_verification_fixed(self, groups, global_teacher_assignments):
        """CORRECTED: Verify constraints - no teacher multiple times in SAME group, but can be in different groups."""
        print(f"\n✅ FINAL CONSTRAINT VERIFICATION (CORRECT UNDERSTANDING):")
        print("-" * 50)
        print("🔧 CORRECT CONSTRAINT LOGIC:")
        print("   🕘 Each GROUP = Single Time Slot (e.g., Monday 9:00-10:00 AM)")
        print("   🚫 Same teacher CANNOT be in a group multiple times (can't be in multiple places simultaneously)")
        print("   ✅ Teacher CAN be in different groups (different time slots)")
        
        # Verify within-group uniqueness constraint (the REAL constraint)
        within_group_violations = 0
        
        for group in groups:
            print(f"\n🎯 Checking Group {group['group_id']} (Single Time Slot):")
            
            # Check for duplicate teachers within the same group
            teachers_in_group = []
            teacher_course_count = {}
            
            for course_code, instance in group['course_instances']:
                teacher_id = instance['teacher_id']
                teachers_in_group.append(teacher_id)
                
                if teacher_id not in teacher_course_count:
                    teacher_course_count[teacher_id] = []
                teacher_course_count[teacher_id].append(course_code)
            
            # Check for teachers appearing multiple times in THIS group
            teacher_counts = {}
            for teacher_id in teachers_in_group:
                teacher_counts[teacher_id] = teacher_counts.get(teacher_id, 0) + 1
            
            group_has_violations = False
            for teacher_id, count in teacher_counts.items():
                if count > 1:
                    within_group_violations += 1
                    group_has_violations = True
                    courses = teacher_course_count[teacher_id]
                    print(f"   ❌ VIOLATION: Teacher {teacher_id} appears {count} times in same group (courses: {courses})")
                    print(f"      → Teacher cannot be in multiple places at the same time!")
                else:
                    courses = teacher_course_count[teacher_id]
                    print(f"   ✅ Teacher {teacher_id}: 1 assignment in this group (course: {courses[0]})")
            
            if not group_has_violations:
                print(f"   ✅ Group {group['group_id']}: No within-group teacher conflicts")
        
        within_group_satisfied = within_group_violations == 0
        print(f"\n🔒 Within-Group Uniqueness Constraint: {'✅ SATISFIED' if within_group_satisfied else f'❌ VIOLATED ({within_group_violations} violations)'}")
        
        # Show cross-group assignments (which ARE allowed)
        print(f"\n🕘 CROSS-GROUP TEACHER ASSIGNMENTS (ALLOWED):")
        teacher_group_assignments = {}
        
        for group in groups:
            for teacher_id in group['teachers_assigned']:
                if teacher_id not in teacher_group_assignments:
                    teacher_group_assignments[teacher_id] = []
                teacher_group_assignments[teacher_id].append(group['group_id'])
        
        for teacher_id, group_list in teacher_group_assignments.items():
            if len(group_list) > 1:
                print(f"   ✅ Teacher {teacher_id} teaching in {len(group_list)} different time slots: Groups {group_list}")
            else:
                print(f"   ℹ️  Teacher {teacher_id} teaching in 1 time slot: Group {group_list[0]}")
        
        # Verify Hall's theorem overall
        halls_satisfied_count = sum(1 for g in groups if g['halls_satisfied'])
        print(f"\n🧮 Hall's Theorem: {halls_satisfied_count}/{len(groups)} groups satisfied")
        
        # Calculate summary statistics
        total_instances_assigned = sum(len(g['course_instances']) for g in groups)
        total_unique_teachers = len(teacher_group_assignments)
        total_capacity = sum(g['student_capacity'] for g in groups)
        
        print(f"\n📊 CORRECTED DISTRIBUTION SUMMARY:")
        print(f"   📦 Groups created: {len(groups)} (each = 1 time slot)")
        print(f"   🔢 Course instances distributed: {total_instances_assigned}")
        print(f"   👥 Unique teachers involved: {total_unique_teachers}")
        print(f"   👨‍🎓 Total student capacity: {total_capacity}")
        print(f"   🔒 Within-group uniqueness: {'✅ SATISFIED' if within_group_satisfied else '❌ VIOLATED'}")
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
    
    def run_complete_analysis(self, target_students=420):
        """Run the complete 5th semester grouping analysis with student choice optimization."""
        print("🚀 STARTING COMPLETE FIFTH SEMESTER GROUPING ANALYSIS")
        print("=" * 80)
        
        # Step 1: Analyze current distribution
        distribution_analysis = self.analyze_fifth_semester_distribution()
        
        # Step 2: Create optimal groups
        optimal_groups = self.create_optimal_groups(courses_per_group=None)
        
        # Step 3: OPTIMIZE FOR MAXIMUM STUDENT CHOICE (NEW!)
        print("\n" + "🎯" * 40)
        print("OPTIMIZING FOR MAXIMUM STUDENT CHOICE")
        print("🎯" * 40)
        student_optimized_groups = self.optimize_for_maximum_student_choice(optimal_groups, target_students)
        
        # Step 4: Generate visualizations
        self.generate_group_visualizations(student_optimized_groups)
        
        # Step 5: Generate course-group heatmap
        heatmap_data = self.generate_course_group_heatmap(student_optimized_groups)
        
        # Step 6: Generate final student choice report
        final_report = self._generate_student_choice_final_report(student_optimized_groups, target_students)
        
        # Step 7: Save results
        results = self.save_grouping_results(student_optimized_groups)
        
        print("\n🎉 ANALYSIS COMPLETED SUCCESSFULLY!")
        print(f"📁 All results saved to: {self.output_dir}")
        print(f"📊 Created {len(student_optimized_groups)} optimal groups")
        print(f"✅ Hall's theorem satisfied: {results['summary']['halls_satisfied_groups']}/{len(student_optimized_groups)} groups")
        print(f"👨‍🎓 Student capacity sufficient: {results['summary']['capacity_sufficient_groups']}/{len(student_optimized_groups)} groups")
        print(f"📈 Average efficiency: {results['summary']['avg_group_efficiency']:.1f}%")
        print(f"🎯 Student choice optimized for {target_students} students")
        print(f"🔥 Final choice index: {final_report['choice_index']:.2f}")
        
        return results
    
    def _generate_student_choice_final_report(self, groups, target_students):
        """Generate final report on student choice optimization."""
        print(f"\n📊 FINAL STUDENT CHOICE REPORT:")
        print("=" * 60)
        
        # Calculate final metrics
        final_metrics = self._calculate_student_choice_metrics(groups, target_students)
        
        # Calculate choice satisfaction for different student positions
        choice_satisfaction = {}
        for percentile in [50, 90, 95, 99, 100]:  # 50th, 90th, 95th, 99th, 100th percentile students
            student_position = int(target_students * percentile / 100)
            satisfaction = self._calculate_choice_satisfaction_for_student_position(groups, student_position, target_students)
            choice_satisfaction[percentile] = satisfaction
        
        print(f"🎯 CHOICE SATISFACTION BY STUDENT POSITION:")
        print(f"   👥 50th percentile student (#{int(target_students*0.5)}): {choice_satisfaction[50]:.1f}% choice satisfaction")
        print(f"   👥 90th percentile student (#{int(target_students*0.9)}): {choice_satisfaction[90]:.1f}% choice satisfaction")
        print(f"   👥 95th percentile student (#{int(target_students*0.95)}): {choice_satisfaction[95]:.1f}% choice satisfaction")
        print(f"   👥 99th percentile student (#{int(target_students*0.99)}): {choice_satisfaction[99]:.1f}% choice satisfaction")
        print(f"   👥 420th student (last): {choice_satisfaction[100]:.1f}% choice satisfaction")
        
        # Overall assessment
        worst_case_satisfaction = choice_satisfaction[100]
        if worst_case_satisfaction >= 80:
            overall_grade = "🏆 EXCELLENT"
            recommendation = "Even the 420th student has excellent course choices!"
        elif worst_case_satisfaction >= 60:
            overall_grade = "✅ GOOD"
            recommendation = "The 420th student has reasonable course choices."
        elif worst_case_satisfaction >= 40:
            overall_grade = "⚠️ FAIR"
            recommendation = "The 420th student has limited but acceptable choices."
        else:
            overall_grade = "❌ POOR"
            recommendation = "Need more optimization - 420th student has insufficient choices."
        
        print(f"\n📈 OVERALL STUDENT CHOICE GRADE: {overall_grade}")
        print(f"💡 RECOMMENDATION: {recommendation}")
        
        # Detailed capacity analysis
        print(f"\n📊 DETAILED CAPACITY ANALYSIS:")
        print(f"   📦 Total Groups: {len(groups)}")
        print(f"   👨‍🎓 Total Capacity: {final_metrics['total_capacity']}")
        print(f"   📈 Capacity Buffer: {((final_metrics['total_capacity'] - target_students) / target_students * 100):.1f}%")
        print(f"   ⚖️  Capacity Balance (lower = better): {final_metrics['capacity_variance']:.0f}")
        print(f"   🎯 Choice Index: {final_metrics['choice_index']:.2f}")
        print(f"   🚫 Bottleneck Groups: {final_metrics['bottleneck_groups']}")
        
        return {
            'choice_index': final_metrics['choice_index'],
            'choice_satisfaction': choice_satisfaction,
            'overall_grade': overall_grade,
            'worst_case_satisfaction': worst_case_satisfaction,
            'total_capacity': final_metrics['total_capacity'],
            'capacity_buffer': ((final_metrics['total_capacity'] - target_students) / target_students * 100),
            'recommendation': recommendation
        }
    
    def _calculate_choice_satisfaction_for_student_position(self, groups, student_position, total_students):
        """Calculate choice satisfaction for a student at a specific position in the queue."""
        # Simulate how many choices this student would have
        # Assumes students are assigned in order and popular courses fill up first
        
        remaining_capacity_per_group = []
        
        for group in groups:
            # Calculate remaining capacity if this many students have already been assigned
            students_per_group = student_position // len(groups)  # Even distribution assumption
            remaining_in_group = max(0, group['student_capacity'] - students_per_group)
            
            # Calculate choice diversity in this group
            courses_available = len(group['courses_represented'])
            
            # If there's capacity and choices available
            if remaining_in_group > 0 and courses_available > 0:
                choice_score = min(100, (remaining_in_group / 70) * 50 + courses_available * 25)
            else:
                choice_score = 0
            
            remaining_capacity_per_group.append(choice_score)
        
        # Average satisfaction across all groups
        avg_satisfaction = sum(remaining_capacity_per_group) / len(groups) if groups else 0
        
        return min(100, avg_satisfaction)
    
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
    
    def _find_best_group_for_instance_corrected(self, groups, teacher_id, instance, teacher_groups):
        """Find the best group for a teacher instance with corrected constraint logic."""
        course_code = instance['course_code']
        
        # With corrected logic: teachers can be in multiple groups
        # Focus on load balancing and optimal distribution
        valid_groups = []
        
        for group in groups:
            # All groups are potentially valid since teachers can be in multiple groups
            valid_groups.append(group)
        
        if not valid_groups:
            return None
        
        # Choose the group with the lowest current capacity for load balancing
        best_group = min(valid_groups, key=lambda g: g['student_capacity'])
        return best_group
    
    def optimize_for_maximum_student_choice(self, groups, target_students=420):
        """Optimize groups to ensure maximum student choice, even for the 420th student."""
        print(f"\n🎯 OPTIMIZING FOR MAXIMUM STUDENT CHOICE ({target_students} students)")
        print("=" * 80)
        
        # Calculate current capacity and choice metrics
        current_metrics = self._calculate_student_choice_metrics(groups, target_students)
        print(f"📊 CURRENT STUDENT CHOICE ANALYSIS:")
        print(f"   👥 Target Students: {target_students}")
        print(f"   📦 Current Groups: {len(groups)}")
        print(f"   👨‍🎓 Total Capacity: {current_metrics['total_capacity']}")
        print(f"   📈 Capacity Utilization: {current_metrics['capacity_utilization']:.1f}%")
        print(f"   🎯 Choice Index: {current_metrics['choice_index']:.2f} (higher = better choice)")
        
        # Identify optimization opportunities
        optimization_needed = self._identify_optimization_opportunities(groups, current_metrics, target_students)
        
        if optimization_needed['needs_optimization']:
            print(f"\n⚠️  OPTIMIZATION NEEDED:")
            for issue in optimization_needed['issues']:
                print(f"   • {issue}")
            
            # Apply optimization strategies
            optimized_groups = self._apply_student_choice_optimizations(groups, optimization_needed, target_students)
            
            # Recalculate metrics
            new_metrics = self._calculate_student_choice_metrics(optimized_groups, target_students)
            
            print(f"\n✅ OPTIMIZATION RESULTS:")
            print(f"   📈 Choice Index: {current_metrics['choice_index']:.2f} → {new_metrics['choice_index']:.2f}")
            print(f"   👨‍🎓 Total Capacity: {current_metrics['total_capacity']} → {new_metrics['total_capacity']}")
            print(f"   📊 Groups: {len(groups)} → {len(optimized_groups)}")
            
            return optimized_groups
        else:
            print(f"\n✅ CURRENT CONFIGURATION OPTIMAL FOR STUDENT CHOICE!")
            return groups
    
    def _calculate_student_choice_metrics(self, groups, target_students):
        """Calculate comprehensive metrics for student choice quality."""
        total_capacity = sum(g['student_capacity'] for g in groups)
        
        # Calculate choice diversity (how many options students have)
        course_choices_per_group = []
        for group in groups:
            unique_courses = len(group['courses_represented'])
            course_choices_per_group.append(unique_courses)
        
        avg_choices_per_group = sum(course_choices_per_group) / len(groups) if groups else 0
        
        # Calculate capacity distribution variance (lower = more balanced)
        group_capacities = [g['student_capacity'] for g in groups]
        capacity_variance = np.var(group_capacities) if group_capacities else 0
        
        # Calculate choice index (combines choice diversity and capacity balance)
        choice_index = avg_choices_per_group * (total_capacity / target_students) / (1 + capacity_variance/1000)
        
        # Calculate bottleneck risk (groups with very low capacity)
        bottleneck_groups = sum(1 for cap in group_capacities if cap < target_students / len(groups) * 0.8)
        
        return {
            'total_capacity': total_capacity,
            'capacity_utilization': (target_students / total_capacity * 100) if total_capacity > 0 else 0,
            'avg_choices_per_group': avg_choices_per_group,
            'capacity_variance': capacity_variance,
            'choice_index': choice_index,
            'bottleneck_groups': bottleneck_groups,
            'group_capacities': group_capacities
        }
    
    def _identify_optimization_opportunities(self, groups, metrics, target_students):
        """Identify what optimizations are needed for better student choice."""
        issues = []
        needs_optimization = False
        
        # Check total capacity
        if metrics['total_capacity'] < target_students * 1.2:  # Need 20% buffer
            issues.append(f"Insufficient capacity: {metrics['total_capacity']} < {target_students * 1.2:.0f} (need 20% buffer)")
            needs_optimization = True
        
        # Check capacity balance
        if metrics['capacity_variance'] > 500:  # High variance in group capacities
            issues.append(f"Unbalanced group capacities (variance: {metrics['capacity_variance']:.0f})")
            needs_optimization = True
        
        # Check for bottleneck groups
        if metrics['bottleneck_groups'] > 0:
            issues.append(f"{metrics['bottleneck_groups']} groups have insufficient capacity")
            needs_optimization = True
        
        # Check choice diversity
        if metrics['avg_choices_per_group'] < 2:
            issues.append(f"Limited course choices per group (avg: {metrics['avg_choices_per_group']:.1f})")
            needs_optimization = True
        
        # Check for courses with single teacher instances
        single_teacher_courses = 0
        for group in groups:
            for course_code in group['courses_represented']:
                course_teachers = set()
                for cc, instance in group['course_instances']:
                    if cc == course_code:
                        course_teachers.add(instance['teacher_id'])
                if len(course_teachers) == 1:
                    single_teacher_courses += 1
        
        if single_teacher_courses > len(groups) * 0.5:
            issues.append(f"Too many single-teacher courses ({single_teacher_courses})")
            needs_optimization = True
        
        return {
            'needs_optimization': needs_optimization,
            'issues': issues,
            'single_teacher_courses': single_teacher_courses
        }
    
    def _apply_student_choice_optimizations(self, groups, optimization_needed, target_students):
        """Apply optimization strategies to improve student choice."""
        print(f"\n🔧 APPLYING STUDENT CHOICE OPTIMIZATIONS:")
        print("-" * 50)
        
        optimized_groups = groups.copy()
        
        # Strategy 1: Add more groups if capacity is insufficient
        if any("Insufficient capacity" in issue for issue in optimization_needed['issues']):
            optimized_groups = self._add_capacity_groups(optimized_groups, target_students)
        
        # Strategy 2: Redistribute teachers for better balance
        if any("Unbalanced" in issue for issue in optimization_needed['issues']):
            optimized_groups = self._rebalance_group_capacities(optimized_groups)
        
        # Strategy 3: Create backup teacher instances for popular courses
        # DISABLED: This was creating additional instances (e.g., 7th CS23511 instance)
        # if optimization_needed['single_teacher_courses'] > len(groups) * 0.5:
        #     optimized_groups = self._create_backup_teacher_instances(optimized_groups)
        
        # Strategy 4: Ensure minimum capacity per group
        optimized_groups = self._ensure_minimum_group_capacity(optimized_groups, target_students)
        
        return optimized_groups
    
    def _add_capacity_groups(self, groups, target_students):
        """Add additional groups to increase total capacity."""
        print("📦 Strategy 1: Adding capacity groups...")
        
        current_capacity = sum(g['student_capacity'] for g in groups)
        needed_capacity = target_students * 1.2 - current_capacity
        
        if needed_capacity > 0:
            additional_groups_needed = max(1, int(needed_capacity / (self.students_per_teacher * 2)))
            print(f"   ➕ Adding {additional_groups_needed} groups for {needed_capacity:.0f} additional capacity")
            
            # Identify underutilized teachers to create new groups
            utilized_teachers = set()
            for group in groups:
                utilized_teachers.update(group['teachers_assigned'])
            
            available_teachers = [t for t in self.teachers if t not in utilized_teachers]
            
            for i in range(additional_groups_needed):
                if available_teachers:
                    new_group = self._create_additional_group(groups, available_teachers, i)
                    if new_group:
                        groups.append(new_group)
                        print(f"   ✅ Created Group {new_group['group_id']} with {new_group['student_capacity']} capacity")
        
        return groups
    
    def _create_additional_group(self, existing_groups, available_teachers, group_index):
        """Create an additional group with available teachers."""
        new_group_id = len(existing_groups) + 1 + group_index
        
        # Select teachers and courses for new group
        selected_teachers = available_teachers[:min(3, len(available_teachers))]  # Max 3 teachers per new group
        
        if not selected_teachers:
            return None
        
        new_group = {
            'group_id': new_group_id,
            'course_instances': [],
            'courses_represented': set(),
            'teachers_assigned': set(selected_teachers),
            'teacher_instances': [],
            'student_capacity': len(selected_teachers) * self.students_per_teacher,
            'halls_satisfied': True,  # Will be verified later
            'halls_violations': [],
            'instance_constraint_satisfied': True,
            'enhanced_constraint_satisfied': True,
            'course_teacher_matrix': {}
        }
        
        # Assign courses to these teachers
        for teacher_id in selected_teachers:
            if teacher_id in self.teacher_course_instances:
                for instance in self.teacher_course_instances[teacher_id][:1]:  # One instance per teacher
                    course_code = instance['course_code']
                    new_group['course_instances'].append((course_code, instance))
                    new_group['courses_represented'].add(course_code)
                    new_group['teacher_instances'].append(instance)
        
        return new_group
    
    def _rebalance_group_capacities(self, groups):
        """Rebalance teacher distribution to reduce capacity variance."""
        print("⚖️  Strategy 2: Rebalancing group capacities...")
        
        # Calculate target capacity per group
        total_capacity = sum(g['student_capacity'] for g in groups)
        target_per_group = total_capacity / len(groups)
        
        print(f"   🎯 Target capacity per group: {target_per_group:.0f}")
        
        # Identify overfull and underfull groups
        overfull_groups = [g for g in groups if g['student_capacity'] > target_per_group * 1.2]
        underfull_groups = [g for g in groups if g['student_capacity'] < target_per_group * 0.8]
        
        print(f"   📊 Overfull groups: {len(overfull_groups)}, Underfull groups: {len(underfull_groups)}")
        
        # Move teacher instances from overfull to underfull groups
        for overfull in overfull_groups:
            for underfull in underfull_groups:
                if overfull['student_capacity'] > target_per_group * 1.1 and underfull['student_capacity'] < target_per_group * 0.9:
                    # Move one teacher instance
                    if overfull['teacher_instances']:
                        instance = overfull['teacher_instances'][-1]
                        course_code = None
                        
                        # Find the course for this instance
                        for cc, inst in overfull['course_instances']:
                            if inst == instance:
                                course_code = cc
                                break
                        
                        if course_code and instance['teacher_id'] not in underfull['teachers_assigned']:
                            # Move instance
                            overfull['course_instances'] = [(cc, inst) for cc, inst in overfull['course_instances'] if inst != instance]
                            overfull['teacher_instances'].remove(instance)
                            overfull['teachers_assigned'].discard(instance['teacher_id'])
                            overfull['student_capacity'] -= self.students_per_teacher
                            
                            underfull['course_instances'].append((course_code, instance))
                            underfull['teacher_instances'].append(instance)
                            underfull['teachers_assigned'].add(instance['teacher_id'])
                            underfull['courses_represented'].add(course_code)
                            underfull['student_capacity'] += self.students_per_teacher
                            
                            print(f"   🔄 Moved teacher {instance['teacher_id']} from Group {overfull['group_id']} to Group {underfull['group_id']}")
                            break
        
        return groups
    
    def _create_backup_teacher_instances(self, groups):
        """Create backup teacher instances for courses with only single teachers."""
        print("👥 Strategy 3: Creating backup teacher instances...")
        
        # Identify courses that need backup teachers
        courses_needing_backup = set()
        
        for group in groups:
            for course_code in group['courses_represented']:
                course_teachers = set()
                for cc, instance in group['course_instances']:
                    if cc == course_code:
                        course_teachers.add(instance['teacher_id'])
                
                if len(course_teachers) == 1:
                    courses_needing_backup.add(course_code)
        
        print(f"   📚 Courses needing backup teachers: {len(courses_needing_backup)}")
        
        # Try to add backup teachers from available pool
        for course_code in courses_needing_backup:
            # Find groups that have this course
            groups_with_course = [g for g in groups if course_code in g['courses_represented']]
            
            # Find teachers who can teach this course but aren't already in these groups
            course_teachers = list(self.course_teacher_matrix.get(course_code, []))
            
            for group in groups_with_course:
                available_backup_teachers = [t for t in course_teachers if t not in group['teachers_assigned']]
                
                if available_backup_teachers:
                    # Add one backup teacher
                    backup_teacher = available_backup_teachers[0]
                    
                    # Create backup instance
                    if backup_teacher in self.teacher_course_instances:
                        for instance in self.teacher_course_instances[backup_teacher]:
                            if instance['course_code'] == course_code:
                                group['course_instances'].append((course_code, instance))
                                group['teachers_assigned'].add(backup_teacher)
                                group['teacher_instances'].append(instance)
                                group['student_capacity'] += self.students_per_teacher
                                
                                print(f"   ✅ Added backup teacher {backup_teacher} for {course_code} in Group {group['group_id']}")
                                break
                        break
        
        return groups
    
    def _ensure_minimum_group_capacity(self, groups, target_students):
        """Ensure each group has minimum capacity for student choice."""
        print("📊 Strategy 4: Ensuring minimum group capacity...")
        
        min_capacity_per_group = target_students / len(groups) * 0.8  # 80% of average
        
        for group in groups:
            if group['student_capacity'] < min_capacity_per_group:
                deficit = min_capacity_per_group - group['student_capacity']
                teachers_needed = max(1, int(deficit / self.students_per_teacher))
                
                print(f"   ⚠️  Group {group['group_id']} below minimum ({group['student_capacity']:.0f} < {min_capacity_per_group:.0f})")
                print(f"   ➕ Need {teachers_needed} additional teachers")
                
                # Try to add teachers from the available pool
                utilized_teachers = group['teachers_assigned']
                available_teachers = [t for t in self.teachers if t not in utilized_teachers]
                
                added_teachers = 0
                for teacher_id in available_teachers[:teachers_needed]:
                    if teacher_id in self.teacher_course_instances:
                        for instance in self.teacher_course_instances[teacher_id][:1]:  # One instance
                            course_code = instance['course_code']
                            group['course_instances'].append((course_code, instance))
                            group['teachers_assigned'].add(teacher_id)
                            group['teacher_instances'].append(instance)
                            group['courses_represented'].add(course_code)
                            group['student_capacity'] += self.students_per_teacher
                            added_teachers += 1
                            break
                
                if added_teachers > 0:
                    print(f"   ✅ Added {added_teachers} teachers to Group {group['group_id']}")
        
        return groups

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