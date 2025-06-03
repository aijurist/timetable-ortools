import os
import pandas as pd
import logging
import argparse
import json
from collections import defaultdict
import random
import numpy as np
import math
from .combination_analyzer import load_schedule_data, extract_teacher_distribution, analyze_combinations

class CombinationFixer:
    """
    Fix course combination issues in a generated timetable to ensure
    all students can select a valid combination of required courses.
    """
    
    def __init__(self, schedule_path, output_dir=None, semester=5, student_count=700):
        """
        Initialize the combination fixer.
        
        Args:
            schedule_path: Path to the original schedule CSV
            output_dir: Directory to save modified schedule (defaults to same directory)
            semester: Semester to focus on (default: 5)
            student_count: Number of students to accommodate (default: 700)
        """
        self.logger = logging.getLogger(__name__)
        self.schedule_path = schedule_path
        self.output_dir = output_dir or os.path.dirname(schedule_path)
        self.semester = semester
        self.student_count = student_count
        
        # Load the schedule data
        self.schedule_df = pd.read_csv(schedule_path)
        self.logger.info(f"Loaded schedule with {len(self.schedule_df)} assignments")
        
        # Extract course, teacher, and macroblock information
        self._extract_schedule_info()
    
    def _extract_schedule_info(self):
        """Extract course, teacher, and macroblock information from the schedule."""
        # Extract semester courses
        self.semester_courses = set()
        if 'semester' in self.schedule_df.columns:
            semester_df = self.schedule_df[self.schedule_df['semester'] == self.semester]
            self.semester_courses = set(semester_df['course_id'].unique())
        else:
            # If semester column not available, try to infer from course codes
            # (This is a fallback approach)
            course_codes = self.schedule_df['course_code'].unique()
            self.semester_courses = set(self.schedule_df['course_id'].unique())
        
        self.logger.info(f"Found {len(self.semester_courses)} courses for semester {self.semester}")
        
        # Extract teachers per course
        self.course_teachers = defaultdict(set)
        for _, row in self.schedule_df.iterrows():
            course_id = row['course_id']
            teacher_id = row['teacher_id']
            if course_id in self.semester_courses:
                self.course_teachers[course_id].add(teacher_id)
        
        # Print teacher counts for each course
        for course, teachers in self.course_teachers.items():
            self.logger.info(f"Course {course}: {len(teachers)} teachers")
        
        # Extract macroblock assignments
        self.teacher_course_blocks = defaultdict(dict)
        for _, row in self.schedule_df.iterrows():
            course_id = row['course_id']
            teacher_id = row['teacher_id']
            macroblock = row.get('macroblock', '')
            
            if course_id in self.semester_courses and macroblock:
                key = (teacher_id, course_id)
                if key not in self.teacher_course_blocks:
                    self.teacher_course_blocks[key] = macroblock
    
    def _to_python_type(self, value):
        """Convert NumPy types to native Python types for JSON serialization."""
        if isinstance(value, np.integer):
            return int(value)
        elif isinstance(value, np.floating):
            return float(value)
        elif isinstance(value, np.ndarray):
            return value.tolist()
        else:
            return value
    
    def analyze_combinations(self):
        """
        Analyze the current combinations and identify issues.
        
        Returns:
            dict: Analysis results with issues identified
        """
        # Build day/slot information for each teacher-course pair
        teacher_course_slots = defaultdict(list)
        
        for _, row in self.schedule_df.iterrows():
            course_id = row['course_id']
            teacher_id = row['teacher_id']
            day = row['day']
            slot_index = row['slot_index']
            
            if course_id in self.semester_courses:
                key = (teacher_id, course_id)
                teacher_course_slots[key].append((day, slot_index))
        
        # Check for conflicts between different courses
        conflicts = []
        
        # For all possible combinations of courses and teachers
        course_list = list(self.semester_courses)
        combinations = []
        
        # Generate possible teacher combinations (one teacher per course)
        def generate_combinations(courses, current_combo=None):
            if current_combo is None:
                current_combo = []
            
            if not courses:
                combinations.append(current_combo)
                return
            
            # Check if we've already reached the limit
            if len(combinations) >= 10000:  # Limit to 10,000 combinations
                return
            
            current_course = courses[0]
            remaining_courses = courses[1:]
            
            for teacher in self.course_teachers.get(current_course, []):
                generate_combinations(
                    remaining_courses, 
                    current_combo + [(current_course, teacher)]
                )
        
        # Generate all possible combinations
        generate_combinations(course_list)
        self.logger.info(f"Generated {len(combinations)} potential combinations")
        
        # Check each combination for conflicts
        valid_combinations = []
        for combo in combinations:
            has_conflict = False
            slot_usage = {}
            
            for course_id, teacher_id in combo:
                key = (teacher_id, course_id)
                slots = teacher_course_slots.get(key, [])
                
                for day, slot in slots:
                    slot_key = f"{day}_{slot}"
                    if slot_key in slot_usage:
                        # Conflict found
                        has_conflict = True
                        conflicts.append({
                            'day': day,
                            'slot': slot,
                            'conflict': [
                                {
                                    'course': slot_usage[slot_key][0],
                                    'teacher': slot_usage[slot_key][1]
                                },
                                {
                                    'course': course_id,
                                    'teacher': teacher_id
                                }
                            ]
                        })
                        break
                    slot_usage[slot_key] = (course_id, teacher_id)
                
                if has_conflict:
                    break
            
            if not has_conflict:
                # Find the capacity (minimum student count across teachers)
                capacity = float('inf')
                for course_id, teacher_id in combo:
                    course_df = self.schedule_df[
                        (self.schedule_df['course_id'] == course_id) & 
                        (self.schedule_df['teacher_id'] == teacher_id)
                    ]
                    if not course_df.empty and 'student_count' in course_df.columns:
                        student_count = course_df['student_count'].iloc[0]
                        capacity = min(capacity, student_count)
                
                if capacity == float('inf'):
                    capacity = 1  # Default if no student count available
                
                valid_combinations.append((combo, capacity))
        
        total_capacity = sum(capacity for _, capacity in valid_combinations)
        
        # Prepare analysis results
        analysis = {
            'total_courses': len(self.semester_courses),
            'total_combinations': len(combinations),
            'valid_combinations': len(valid_combinations),
            'total_capacity': self._to_python_type(total_capacity),
            'required_capacity': self._to_python_type(self.student_count),
            'status': 'SUCCESS' if total_capacity >= self.student_count else 'FAILED',
            'conflicts': conflicts[:10],  # First 10 conflicts
            'course_teacher_counts': {str(course): len(teachers) for course, teachers in self.course_teachers.items()}
        }
        
        return analysis
    
    def suggest_fixes(self, analysis):
        """
        Suggest fixes to improve course combinations.
        
        Args:
            analysis: Analysis results from analyze_combinations
        
        Returns:
            list: Suggested fixes
        """
        if analysis['status'] == 'SUCCESS':
            self.logger.info("No fixes needed - combination requirements already met")
            return []
        
        # Analyze which macroblocks are used for each course
        course_blocks = defaultdict(set)
        for (teacher_id, course_id), macroblock in self.teacher_course_blocks.items():
            course_blocks[course_id].add(macroblock)
        
        # Identify courses with macroblock overlap
        overlap_courses = []
        courses = list(self.semester_courses)
        
        for i in range(len(courses)):
            for j in range(i+1, len(courses)):
                course1 = courses[i]
                course2 = courses[j]
                
                blocks1 = course_blocks.get(course1, set())
                blocks2 = course_blocks.get(course2, set())
                
                if blocks1.intersection(blocks2):
                    overlap_courses.append((course1, course2, blocks1.intersection(blocks2)))
        
        # Generate suggested fixes
        fixes = []
        
        if overlap_courses:
            self.logger.info(f"Found {len(overlap_courses)} course pairs with macroblock overlap")
            
            # Fix 1: Redistribute teachers to different macroblocks
            for course1, course2, overlap_blocks in overlap_courses:
                fixes.append({
                    'type': 'redistribute_macroblocks',
                    'course1': course1,
                    'course2': course2,
                    'overlap_blocks': list(overlap_blocks),
                    'description': f"Redistribute teachers for courses {course1} and {course2} to avoid overlap in blocks {', '.join(overlap_blocks)}"
                })
            
            # Fix 2: Adjust scheduling to separate courses
            fixes.append({
                'type': 'adjust_scheduling',
                'description': "Adjust scheduling constraints to enforce stricter separation between semester courses"
            })
            
            # Fix 3: Increase teacher diversity across macroblocks
            fixes.append({
                'type': 'increase_diversity',
                'description': "Increase teacher diversity across macroblocks for better combination coverage"
            })
        
        return fixes
    
    def apply_fixes(self, fixes):
        """
        Apply selected fixes to the schedule.
        
        Args:
            fixes: List of fixes to apply
        
        Returns:
            pandas.DataFrame: Modified schedule
        """
        # Make a copy of the original schedule
        modified_df = self.schedule_df.copy()
        
        applied_fixes = []
        for fix in fixes:
            if fix['type'] == 'redistribute_macroblocks':
                # Get courses and overlapping blocks
                course1 = fix['course1']
                course2 = fix['course2']
                overlap_blocks = fix['overlap_blocks']
                
                # Find teachers for these courses
                teachers1 = list(self.course_teachers.get(course1, []))
                teachers2 = list(self.course_teachers.get(course2, []))
                
                if not teachers1 or not teachers2:
                    continue
                
                # Find all macroblocks used
                all_blocks = set()
                for (teacher_id, course_id), macroblock in self.teacher_course_blocks.items():
                    all_blocks.add(macroblock)
                
                # Find alternative blocks that aren't in the overlap
                alternative_blocks = [block for block in all_blocks if block not in overlap_blocks]
                
                if not alternative_blocks:
                    continue
                
                # Randomly select teachers to move to alternative blocks
                random.shuffle(teachers1)
                random.shuffle(teachers2)
                
                # For course1, move half the teachers in overlapping blocks to alternative blocks
                for teacher_id in teachers1[:len(teachers1)//2]:
                    if (teacher_id, course1) in self.teacher_course_blocks:
                        current_block = self.teacher_course_blocks[(teacher_id, course1)]
                        if current_block in overlap_blocks:
                            # Choose a random alternative block
                            new_block = random.choice(alternative_blocks)
                            
                            # Update the schedule
                            mask = (
                                (modified_df['course_id'] == course1) & 
                                (modified_df['teacher_id'] == teacher_id) &
                                (modified_df['macroblock'] == current_block)
                            )
                            modified_df.loc[mask, 'macroblock'] = new_block
                            
                            applied_fixes.append(f"Moved teacher {teacher_id} for course {course1} from block {current_block} to {new_block}")
                
                # For course2, do the same
                for teacher_id in teachers2[:len(teachers2)//2]:
                    if (teacher_id, course2) in self.teacher_course_blocks:
                        current_block = self.teacher_course_blocks[(teacher_id, course2)]
                        if current_block in overlap_blocks:
                            # Choose a random alternative block
                            new_block = random.choice(alternative_blocks)
                            
                            # Update the schedule
                            mask = (
                                (modified_df['course_id'] == course2) & 
                                (modified_df['teacher_id'] == teacher_id) &
                                (modified_df['macroblock'] == current_block)
                            )
                            modified_df.loc[mask, 'macroblock'] = new_block
                            
                            applied_fixes.append(f"Moved teacher {teacher_id} for course {course2} from block {current_block} to {new_block}")
        
        self.logger.info(f"Applied {len(applied_fixes)} fixes to the schedule")
        for fix in applied_fixes:
            self.logger.info(f"  - {fix}")
        
        return modified_df
    
    def fix_combinations(self):
        """
        Fix course combination issues to ensure students can register for all courses.
        
        Returns:
            bool: True if fixes were applied, False otherwise
        """
        # Analyze current combinations
        analysis = self.analyze_combinations()
        
        # Save analysis to file
        analysis_path = os.path.join(self.output_dir, 'combination_analysis.json')
        
        # Use custom JSON encoder to handle NumPy types
        class NumpyEncoder(json.JSONEncoder):
            def default(self, obj):
                if isinstance(obj, np.integer):
                    return int(obj)
                elif isinstance(obj, np.floating):
                    return float(obj)
                elif isinstance(obj, np.ndarray):
                    return obj.tolist()
                return super().default(obj)
        
        with open(analysis_path, 'w', encoding='utf-8') as f:
            json.dump(analysis, f, indent=2, cls=NumpyEncoder)
        
        # If requirements already met, no fixes needed
        if analysis['status'] == 'SUCCESS':
            self.logger.info("Combination requirements already met - no fixes needed")
            return False
        
        # Suggest fixes
        fixes = self.suggest_fixes(analysis)
        
        if not fixes:
            self.logger.warning("No fixes could be identified")
            return False
        
        # Save suggested fixes to file
        fixes_path = os.path.join(self.output_dir, 'suggested_fixes.json')
        with open(fixes_path, 'w', encoding='utf-8') as f:
            json.dump(fixes, f, indent=2, cls=NumpyEncoder)
        
        # Apply fixes
        modified_df = self.apply_fixes(fixes)
        
        # Save modified schedule
        fixed_schedule_path = os.path.join(self.output_dir, 'fixed_macroblock_schedule.csv')
        modified_df.to_csv(fixed_schedule_path, index=False)
        
        # Re-analyze to check if fixed
        # Create a temporary CombinationFixer with the modified schedule
        temp_fixer = CombinationFixer(fixed_schedule_path, self.output_dir, self.semester, self.student_count)
        post_analysis = temp_fixer.analyze_combinations()
        
        # Save post-fix analysis
        post_analysis_path = os.path.join(self.output_dir, 'post_fix_analysis.json')
        with open(post_analysis_path, 'w', encoding='utf-8') as f:
            json.dump(post_analysis, f, indent=2, cls=NumpyEncoder)
        
        # Generate report
        report_path = os.path.join(self.output_dir, 'combination_fix_report.txt')
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write("Course Combination Fix Report\n")
            f.write("============================\n\n")
            
            f.write("Initial Analysis:\n")
            f.write(f"  Valid combinations: {analysis['valid_combinations']}\n")
            f.write(f"  Total capacity: {analysis['total_capacity']} students\n")
            f.write(f"  Required capacity: {analysis['required_capacity']} students\n")
            f.write(f"  Status: {analysis['status']}\n\n")
            
            f.write("Applied Fixes:\n")
            if fixes:
                for i, fix in enumerate(fixes, 1):
                    f.write(f"  {i}. {fix['description']}\n")
            else:
                f.write("  No fixes were applied\n")
            f.write("\n")
            
            f.write("Post-Fix Analysis:\n")
            f.write(f"  Valid combinations: {post_analysis['valid_combinations']}\n")
            f.write(f"  Total capacity: {post_analysis['total_capacity']} students\n")
            f.write(f"  Required capacity: {post_analysis['required_capacity']} students\n")
            f.write(f"  Status: {post_analysis['status']}\n\n")
            
            if post_analysis['status'] == 'SUCCESS':
                f.write("✅ Fixes successfully resolved combination issues!\n")
            else:
                f.write("❌ Fixes did not fully resolve combination issues.\n")
                f.write("   Consider more significant changes to the scheduling constraints.\n")
        
        self.logger.info(f"Fix report generated at {report_path}")
        
        return post_analysis['status'] == 'SUCCESS'

def fix_course_combinations(schedule_file, output_dir, semester=5, student_count=700):
    """
    Fix course combination issues by redistributing teachers to problematic blocks.
    
    Args:
        schedule_file: Path to the schedule CSV file
        output_dir: Directory to save the fixed schedule
        semester: Target semester (default: 5)
        student_count: Number of students to accommodate (default: 700)
    
    Returns:
        Boolean indicating if the fix was successful
    """
    print(f"\nAttempting to fix course combinations for {student_count} students...")
    
    try:
        # Load the schedule data
        schedule_df = pd.read_csv(schedule_file)
        
        # Filter for the target semester if specified
        if semester:
            schedule_df = schedule_df[schedule_df['semester'] == semester]
        
        # Load the distribution
        original_distribution = extract_teacher_distribution(schedule_df)
        
        # Analyze the original distribution
        print("\nAnalyzing original distribution...")
        is_valid = analyze_combinations(original_distribution, 
                                      student_per_teacher=70, 
                                      display_detailed=False, 
                                      student_count=student_count)
        
        if is_valid:
            print("✅ Original distribution already valid - no fixes needed!")
            return True
        
        # Identify problematic blocks and courses
        problematic_blocks, problematic_courses = identify_problems(
            original_distribution, student_count)
        
        if not problematic_blocks and not problematic_courses:
            print("No specific problems identified - cannot fix automatically.")
            return False
        
        # Create a copy of the schedule for modifications
        modified_schedule = schedule_df.copy()
        
        # Apply fixes
        fixed = False
        if problematic_blocks:
            print(f"Fixing problematic blocks: {problematic_blocks}")
            modified_schedule = fix_block_deficits(
                modified_schedule, problematic_blocks, student_count)
            fixed = True
        
        if problematic_courses:
            print(f"Fixing problematic courses: {problematic_courses}")
            modified_schedule = fix_course_deficits(
                modified_schedule, problematic_courses, student_count)
            fixed = True
        
        if not fixed:
            print("No fixes applied - original problems could not be resolved.")
            return False
        
        # Save the modified schedule
        fixed_schedule_path = os.path.join(output_dir, 'modified_macroblock_schedule.csv')
        modified_schedule.to_csv(fixed_schedule_path, index=False)
        
        # Reanalyze the modified distribution
        print("\nAnalyzing modified distribution...")
        modified_distribution = extract_teacher_distribution(modified_schedule)
        is_fixed = analyze_combinations(modified_distribution, 
                                      student_per_teacher=70, 
                                      display_detailed=False, 
                                      student_count=student_count)
        
        # Generate a fix report
        fix_report_path = os.path.join(output_dir, 'combination_fix_report.txt')
        with open(fix_report_path, 'w', encoding='utf-8') as f:
            f.write("="*80 + "\n")
            f.write(f"COURSE COMBINATION FIX REPORT ({student_count} STUDENTS)\n")
            f.write("="*80 + "\n\n")
            
            f.write("IDENTIFIED PROBLEMS:\n")
            if problematic_blocks:
                f.write(f"• Blocks with insufficient capacity: {', '.join(problematic_blocks)}\n")
            if problematic_courses:
                f.write(f"• Courses with insufficient capacity: {', '.join(problematic_courses)}\n")
            
            f.write("\nAPPLIED FIXES:\n")
            if fixed:
                teacher_counts_before = original_distribution['total_teachers'].to_dict()
                teacher_counts_after = modified_distribution['total_teachers'].to_dict()
                
                f.write("Teacher redistribution summary:\n")
                
                for course_idx in modified_distribution.index:
                    if course_idx in teacher_counts_before:
                        course_code = course_idx[1]
                        before = teacher_counts_before[course_idx]
                        after = teacher_counts_after[course_idx]
                        
                        if before != after:
                            f.write(f"• Course {course_code}: {int(before)} → {int(after)} teachers\n")
                
                # Block distribution changes
                f.write("\nBlock distribution changes:\n")
                
                for block in ['a1', 'b1', 'c1', 'd1', 'e1', 'f1', 'g1']:
                    before_sum = original_distribution[block].sum()
                    after_sum = modified_distribution[block].sum()
                    
                    if before_sum != after_sum:
                        f.write(f"• Block {block}: {int(before_sum)} → {int(after_sum)} teachers\n")
            else:
                f.write("• No fixes could be applied automatically\n")
            
            f.write("\nRESULT:\n")
            if is_fixed:
                f.write("✅ SUCCESS: The modified distribution can accommodate all students.\n")
            else:
                f.write("❌ PARTIAL FIX: The modified distribution still cannot accommodate all students.\n")
                f.write("   Further manual adjustments may be needed.\n")
            
            f.write("\nNote: Please review the modified schedule in 'modified_macroblock_schedule.csv'.\n")
        
        print(f"Fix report generated at: {fix_report_path}")
        
        if is_fixed:
            print("✅ Fixed schedule created successfully!")
        else:
            print("⚠️ Partially fixed schedule created - some issues remain.")
        
        return is_fixed
        
    except Exception as e:
        print(f"Error fixing course combinations: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def identify_problems(distribution, student_count=700):
    """
    Identify problematic blocks and courses in the distribution.
    
    Returns:
        Tuple of (problematic_blocks, problematic_courses)
    """
    # Define valid blocks
    valid_blocks = ['a1', 'b1', 'c1', 'd1', 'e1', 'f1', 'g1']
    
    # Calculate actual supportable student count based on min capacity
    teacher_capacity = 70  # Each teacher can handle 70 students
    min_capacity = min([row['total_teachers'] * teacher_capacity 
                      for idx, row in distribution.iterrows()])
    actual_student_count = min(student_count, min_capacity)
    
    # Calculate required teachers per block
    required_teachers_per_block = math.ceil((actual_student_count * 5) / (7 * teacher_capacity))
    max_students_per_block = math.ceil(actual_student_count * 5 / 7)
    
    # Find problematic blocks
    problematic_blocks = []
    for block in valid_blocks:
        teachers_per_block = sum([int(row[block]) for idx, row in distribution.iterrows()])
        capacity = teachers_per_block * teacher_capacity
        
        if capacity < max_students_per_block:
            problematic_blocks.append(block)
    
    # Find problematic courses
    problematic_courses = []
    for idx, row in distribution.iterrows():
        if idx is not None:
            course_id, course_code, course_name = idx
            total_teachers = int(row['total_teachers'])
            capacity = total_teachers * teacher_capacity
            
            if capacity < actual_student_count:
                problematic_courses.append(course_code)
    
    return problematic_blocks, problematic_courses

def fix_block_deficits(schedule_df, problematic_blocks, student_count=700):
    """
    Fix block deficits by redistributing teachers from surplus blocks to deficit blocks.
    
    Strategy:
    1. Identify teachers that can be moved from surplus blocks to deficit blocks
    2. For each deficit block, find suitable teachers to move
    3. Update the schedule with the new assignments
    
    Returns:
        Modified schedule DataFrame
    """
    # Define valid blocks
    valid_blocks = ['a1', 'b1', 'c1', 'd1', 'e1', 'f1', 'g1']
    
    # Make a copy to avoid modifying the original
    modified_df = schedule_df.copy()
    
    # Calculate target teachers per block
    teacher_capacity = 70  # Each teacher can handle 70 students
    required_teachers_per_block = math.ceil((student_count * 5) / (7 * teacher_capacity))
    
    # First, get the current teacher counts per block
    block_teacher_counts = {}
    for block in valid_blocks:
        block_teachers = modified_df[modified_df['macroblock'] == block]['teacher_id'].nunique()
        block_teacher_counts[block] = block_teachers
    
    # Identify deficit and surplus blocks
    deficit_blocks = []
    surplus_blocks = []
    
    for block in valid_blocks:
        if block in problematic_blocks:
            deficit = required_teachers_per_block - block_teacher_counts[block]
            if deficit > 0:
                deficit_blocks.append((block, deficit))
        else:
            surplus = block_teacher_counts[block] - required_teachers_per_block
            if surplus > 0:
                surplus_blocks.append((block, surplus))
    
    # Sort by deficit/surplus magnitude (largest first)
    deficit_blocks.sort(key=lambda x: x[1], reverse=True)
    surplus_blocks.sort(key=lambda x: x[1], reverse=True)
    
    print(f"Deficit blocks: {deficit_blocks}")
    print(f"Surplus blocks: {surplus_blocks}")
    
    # Process each deficit block
    for deficit_block, deficit in deficit_blocks:
        # Find teachers to move to this block
        teachers_to_move = []
        remaining_deficit = deficit
        
        # Try to find teachers from surplus blocks
        for surplus_block, surplus in surplus_blocks:
            if remaining_deficit <= 0:
                break
                
            # Find teachers who are in this surplus block
            surplus_teachers = modified_df[modified_df['macroblock'] == surplus_block]['teacher_id'].unique()
            
            # For each teacher, check if they can be moved
            for teacher in surplus_teachers:
                if remaining_deficit <= 0:
                    break
                    
                # Get all rows for this teacher
                teacher_rows = modified_df[modified_df['teacher_id'] == teacher]
                
                # Check if this teacher has any courses in the deficit block
                if deficit_block not in teacher_rows['macroblock'].values:
                    # Check if this teacher has multiple courses in surplus block
                    teacher_surplus_count = len(teacher_rows[teacher_rows['macroblock'] == surplus_block])
                    
                    if teacher_surplus_count > 1:
                        # Teacher has multiple courses in surplus block, can move one
                        course_instances = teacher_rows[teacher_rows['macroblock'] == surplus_block]['course_instance_id'].unique()
                        
                        if len(course_instances) > 0:
                            # Choose first course instance to move
                            instance_to_move = course_instances[0]
                            teachers_to_move.append((teacher, instance_to_move, surplus_block, deficit_block))
                            remaining_deficit -= 1
                            
                            # Update the surplus block count
                            if len(surplus_blocks) > 0:
                                surplus_blocks[0] = (surplus_blocks[0][0], surplus_blocks[0][1] - 1)
                                if surplus_blocks[0][1] <= 0:
                                    surplus_blocks.pop(0)
        
        # Apply the moves
        for teacher, instance, from_block, to_block in teachers_to_move:
            # Update the macroblock for this instance
            instance_mask = (modified_df['teacher_id'] == teacher) & (modified_df['course_instance_id'] == instance)
            modified_df.loc[instance_mask, 'macroblock'] = to_block
            
            print(f"Moved teacher {teacher}, instance {instance} from {from_block} to {to_block}")
    
    return modified_df

def fix_course_deficits(schedule_df, problematic_courses, student_count=700):
    """
    Fix course deficits by adding more teachers to courses with insufficient capacity.
    
    Strategy:
    1. Identify courses with insufficient teacher capacity
    2. Add more teacher instances by duplicating existing teacher assignments
    3. Distribute new instances across blocks to maintain balance
    
    Returns:
        Modified schedule DataFrame
    """
    # Make a copy to avoid modifying the original
    modified_df = schedule_df.copy()
    
    # Calculate required teachers per course
    teacher_capacity = 70  # Each teacher can handle 70 students
    required_teachers_per_course = math.ceil(student_count / teacher_capacity)
    
    # Get current teacher counts per course
    course_teacher_counts = {}
    for course_code in problematic_courses:
        course_rows = modified_df[modified_df['course_code'] == course_code]
        teacher_count = course_rows['teacher_id'].nunique()
        course_teacher_counts[course_code] = teacher_count
    
    # Process each problematic course
    for course_code in problematic_courses:
        current_teachers = course_teacher_counts[course_code]
        needed_teachers = required_teachers_per_course
        deficit = needed_teachers - current_teachers
        
        if deficit <= 0:
            continue
            
        print(f"Course {course_code}: Adding {deficit} more teachers")
        
        # Get existing teacher assignments for this course
        course_rows = modified_df[modified_df['course_code'] == course_code].copy()
        
        # Get distribution across blocks
        block_counts = course_rows['macroblock'].value_counts().to_dict()
        
        # Find teachers who can teach additional sections
        existing_teachers = course_rows['teacher_id'].unique()
        
        if len(existing_teachers) == 0:
            print(f"No existing teachers found for course {course_code}")
            continue
        
        # Add new instances by duplicating existing ones
        new_rows = []
        teacher_idx = 0
        
        # Define blocks to target (prefer deficit blocks)
        valid_blocks = ['a1', 'b1', 'c1', 'd1', 'e1', 'f1', 'g1']
        target_blocks = sorted(valid_blocks, key=lambda b: block_counts.get(b, 0))
        
        for i in range(deficit):
            # Select next teacher to duplicate
            teacher_id = existing_teachers[teacher_idx]
            teacher_idx = (teacher_idx + 1) % len(existing_teachers)
            
            # Get template rows for this teacher and course
            template_rows = course_rows[course_rows['teacher_id'] == teacher_id]
            
            if len(template_rows) == 0:
                continue
                
            # Choose a target block with lowest count
            target_block = target_blocks[0]
            
            # Duplicate rows with new instance ID and target block
            for _, row in template_rows.iterrows():
                new_row = row.copy()
                new_row['course_instance_id'] = f"{row['course_instance_id']}_dup_{i}"
                new_row['macroblock'] = target_block
                new_rows.append(new_row)
            
            # Update block counts
            block_counts[target_block] = block_counts.get(target_block, 0) + 1
            target_blocks = sorted(valid_blocks, key=lambda b: block_counts.get(b, 0))
        
        # Add new rows to the schedule
        if new_rows:
            modified_df = pd.concat([modified_df, pd.DataFrame(new_rows)], ignore_index=True)
            print(f"Added {len(new_rows)} new rows for course {course_code}")
    
    return modified_df

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Fix course combination issues in a timetable')
    parser.add_argument('--schedule', required=True, help='Path to schedule CSV file')
    parser.add_argument('--output-dir', help='Output directory for fixed schedule and reports')
    parser.add_argument('--semester', type=int, default=5, help='Semester to focus on')
    parser.add_argument('--students', type=int, default=700, help='Number of students to accommodate')
    
    args = parser.parse_args()
    
    success = fix_course_combinations(
        args.schedule, args.output_dir, args.semester, args.students
    )
    
    if success:
        print("✅ Course combination issues successfully fixed!")
    else:
        print("❌ Could not fully resolve course combination issues.")
        print("   Check the fix report for details.") 