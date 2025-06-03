#!/usr/bin/env python3
"""
Timetable Combination Analyzer

This script analyzes the teacher distribution across macroblocks to determine
if there are enough valid combinations for all students to register for their
required courses without conflicts.
"""

import os
import sys
import pandas as pd
import numpy as np
import math
import glob
from pathlib import Path

def find_latest_output_dir():
    """Find the latest output directory from the scheduler."""
    # Get the base directory of the project
    base_dir = Path(__file__).parent.parent.parent.parent
    
    # Path to output directories
    output_base = base_dir / 'timetable_scheduler' / 'output'
    
    # Find all macroblock schedule directories
    dirs = glob.glob(str(output_base / 'macroblock_schedule_*'))
    
    if not dirs:
        print("No output directories found!")
        return None
    
    # Sort by creation time (latest first)
    latest_dir = max(dirs, key=os.path.getctime)
    
    return latest_dir

def load_schedule_data(output_dir):
    """Load schedule data from the output directory."""
    schedule_file = os.path.join(output_dir, 'macroblock_schedule.csv')
    
    if not os.path.exists(schedule_file):
        print(f"Schedule file not found at {schedule_file}")
        return None
    
    return pd.read_csv(schedule_file)

def extract_teacher_distribution(schedule_df):
    """Extract the teacher distribution across macroblocks for each course."""
    # Focus only on theory/tutorial slots
    theory_df = schedule_df[schedule_df['slot_type'].isin(['Lecture', 'Tutorial'])]
    
    # IMPORTANT: Filter for a1-g1 blocks only, exclude a2-g2 blocks
    valid_blocks = ['a1', 'b1', 'c1', 'd1', 'e1', 'f1', 'g1']
    theory_df = theory_df[theory_df['macroblock'].isin(valid_blocks)]
    
    # Group by course and macroblock
    # Count unique teachers per course per macroblock
    distribution = theory_df.groupby(['course_id', 'course_code', 'course_name', 'macroblock'])['teacher_id'].nunique().unstack().fillna(0)
    
    # Ensure all valid blocks are in the distribution, fill missing with 0
    for block in valid_blocks:
        if block not in distribution.columns:
            distribution[block] = 0
    
    # Only include valid blocks
    distribution = distribution[valid_blocks]
    
    # Add course information
    # Instead of using 'lecture_hours' and 'tutorial_hours' columns directly,
    # infer them from the slot_type counts
    course_hours = {}
    for course_id in theory_df['course_id'].unique():
        course_df = theory_df[theory_df['course_id'] == course_id]
        lecture_count = len(course_df[course_df['slot_type'] == 'Lecture'])
        tutorial_count = len(course_df[course_df['slot_type'] == 'Tutorial'])
        
        # We need to divide by the number of teachers to get hours per course
        teacher_count = course_df['teacher_id'].nunique()
        if teacher_count > 0:
            lecture_hours = lecture_count / teacher_count
            tutorial_hours = tutorial_count / teacher_count
        else:
            lecture_hours = 0
            tutorial_hours = 0
            
        course_hours[course_id] = {
            'lecture_hours': lecture_hours,
            'tutorial_hours': tutorial_hours
        }
    
    # Get student counts
    student_counts = theory_df.groupby('course_id')['student_count'].first()
    
    # Prepare course info dataframe
    course_info_data = {
        'lecture_hours': [course_hours.get(course_id, {}).get('lecture_hours', 0) for course_id in distribution.index.get_level_values(0)],
        'tutorial_hours': [course_hours.get(course_id, {}).get('tutorial_hours', 0) for course_id in distribution.index.get_level_values(0)],
        'student_count': [student_counts.get(course_id, 0) for course_id in distribution.index.get_level_values(0)]
    }
    
    course_info = pd.DataFrame(course_info_data, index=distribution.index)
    
    # Join with distribution
    distribution = distribution.join(course_info)
    
    # Calculate total teachers per course
    distribution['total_teachers'] = distribution[valid_blocks].sum(axis=1)
    
    # Calculate student capacity per course (teachers * 70)
    distribution['student_capacity'] = distribution['total_teachers'] * 70
    
    return distribution

def analyze_combinations(distribution, student_per_teacher=70, display_detailed=True, student_count=700):
    """
    Analyze if there are enough valid combinations for all students.
    
    Args:
        distribution: DataFrame with teacher distribution across macroblocks
        student_per_teacher: Number of students each teacher can handle
        display_detailed: Whether to print detailed analysis
        student_count: Total number of students to accommodate
    
    Returns:
        Boolean indicating if all students can find valid combinations
    """
    # Make a copy to avoid modifying the original
    df = distribution.copy()
    
    # Define valid blocks (a1-g1 only)
    valid_blocks = ['a1', 'b1', 'c1', 'd1', 'e1', 'f1', 'g1']
    
    # Extract course information and filter rows with no index
    course_info = {
        idx: {
            'id': idx[0],
            'code': idx[1],
            'name': idx[2],
            'hours': row.get('lecture_hours', 0) + row.get('tutorial_hours', 0),
            'student_count': student_count,  # Use the provided student_count
            'teachers': row['total_teachers'],
            'student_capacity': row['student_capacity']
        }
        for idx, row in df.iterrows() if idx is not None
    }
    
    # Calculate actual supportable student count based on minimum course capacity
    min_capacity = min([info['student_capacity'] for info in course_info.values()])
    actual_student_count = min(student_count, min_capacity)
    
    # Generate output
    print("\n" + "="*80)
    print(f"ANALYSIS OF TEACHER DISTRIBUTION FOR {student_count} STUDENTS")
    print("="*80)
    print(f"RESTRICTION: Only a1-g1 blocks are considered, a2-g2 blocks are excluded")
    
    # Print actual supportable student count
    print(f"\nActual supportable student count: {actual_student_count} (minimum capacity across courses)")
    
    # STEP 1: Print the teacher distribution table
    print("\nCURRENT TEACHER DISTRIBUTION:")
    print(f"{'Course':10} | {'Course Name':30} | " + 
          " | ".join([f"{block:4}" for block in valid_blocks]) + 
          f" | {'Total':5} | {'Capacity':8}")
    print("-"*120)
    
    for idx, row in df.iterrows():
        if idx is not None:
            course_id, course_code, course_name = idx
            block_cells = " | ".join([f"{int(row[block]):4}" for block in valid_blocks])
            print(f"{course_code:10} | {course_name[:30]:30} | {block_cells} | " +
                  f"{int(row['total_teachers']):5} | {int(row['student_capacity']):8}")
    
    # STEP 2: Calculate required teachers per block for student load
    # For n students, 5 courses, 7 blocks, and t teachers per student:
    # Each block needs at least: ceil(n * 5/7 / t) teachers
    required_teachers_per_block = math.ceil((actual_student_count * 5) / (7 * student_per_teacher))
    max_students_per_block = math.ceil(actual_student_count * 5 / 7)
    
    print(f"\nMINIMUM REQUIREMENTS:")
    print(f"• For {actual_student_count} students taking 5 courses across 7 blocks:")
    print(f"• Each block needs {required_teachers_per_block}+ teachers to handle {max_students_per_block} students")
    print(f"• Each course needs {math.ceil(actual_student_count/student_per_teacher)}+ teachers ({actual_student_count} students)")
    
    # STEP 3: Block capacity analysis
    print("\nBLOCK CAPACITY ANALYSIS:")
    print(f"{'Block':10} | {'Teachers':10} | {'Capacity':15} | {'Required':10} | {'Status':10}")
    print("-"*60)
    
    all_blocks_sufficient = True
    problematic_blocks = []
    
    block_capacity = {}
    for block in valid_blocks:
        teachers_per_block = sum([int(row[block]) for idx, row in df.iterrows() if idx is not None])
        capacity = teachers_per_block * student_per_teacher
        block_capacity[block] = capacity
        
        required = max_students_per_block
        status = "✅" if capacity >= required else "❌"
        if capacity < required:
            all_blocks_sufficient = False
            problematic_blocks.append(block)
        
        print(f"{block:10} | {teachers_per_block:10} | {capacity:15} | {required:10} | {status:10}")
    
    # STEP 4: Course capacity analysis
    print("\nCOURSE CAPACITY ANALYSIS:")
    print(f"{'Course':10} | {'Teachers':10} | {'Capacity':15} | {'Required':10} | {'Status':10}")
    print("-"*60)
    
    all_courses_sufficient = True
    problematic_courses = []
    
    for idx, row in df.iterrows():
        if idx is not None:
            course_id, course_code, course_name = idx
            total_teachers = int(row['total_teachers'])
            capacity = total_teachers * student_per_teacher
            required = actual_student_count
            
            status = "✅" if capacity >= required else "❌"
            if capacity < required:
                all_courses_sufficient = False
                problematic_courses.append(course_code)
            
            print(f"{course_code:10} | {total_teachers:10} | {capacity:15} | {required:10} | {status:10}")
    
    # STEP 5: Enhanced combination analysis
    print("\nENHANCED COMBINATION ANALYSIS:")
    
    # Create course distribution mapping
    courses_by_hours = {}
    for idx, row in df.iterrows():
        if idx is not None:
            course_id, course_code, course_name = idx
            hours = row.get('lecture_hours', 0) + row.get('tutorial_hours', 0)
            
            # Store course distribution by block for combination analysis
            courses_by_hours[course_code] = {
                'hours': hours,
                'blocks': {block: int(row[block]) for block in valid_blocks},
                'total_teachers': int(row['total_teachers'])
            }
    
    # Classify courses by hours
    four_hour_courses = []
    three_hour_courses = []
    
    for course_code, info in courses_by_hours.items():
        if info['hours'] >= 4:
            four_hour_courses.append(course_code)
        else:
            three_hour_courses.append(course_code)
    
    print(f"\n4-hour courses: {', '.join(four_hour_courses)}")
    print(f"3-hour courses: {', '.join(three_hour_courses)}")
    
    # Check if at least one valid combination exists
    def can_form_valid_combination(course_assignments, remaining_courses, used_blocks):
        if not remaining_courses:
            return True  # Successfully assigned all courses
        
        course = remaining_courses[0]
        course_info = courses_by_hours[course]
        
        # Try each available block for this course
        for block in valid_blocks:
            # Skip if block is already used or has no teachers
            if block in used_blocks or course_info['blocks'][block] == 0:
                continue
            
            # Try this block
            new_assignments = course_assignments.copy()
            new_assignments[course] = block
            
            new_used_blocks = used_blocks.copy()
            new_used_blocks.add(block)
            
            # Recursively try to assign remaining courses
            if can_form_valid_combination(new_assignments, remaining_courses[1:], new_used_blocks):
                return True
        
        return False  # No valid assignment found
    
    # Get list of all courses
    all_courses = list(courses_by_hours.keys())
    
    # Check if a valid combination exists
    valid_combination_exists = can_form_valid_combination({}, all_courses, set())
    print(f"\nCan form at least one valid combination: {'✅ Yes' if valid_combination_exists else '❌ No'}")
    
    # Find a valid combination example if one exists
    if valid_combination_exists:
        print("\nExample valid combination:")
        
        def find_valid_combination(remaining_courses, used_blocks, assignments):
            if not remaining_courses:
                return assignments
            
            course = remaining_courses[0]
            course_info = courses_by_hours[course]
            
            for block in valid_blocks:
                if block in used_blocks or course_info['blocks'][block] == 0:
                    continue
                
                # Try this block
                new_used_blocks = used_blocks.copy()
                new_used_blocks.add(block)
                new_assignments = assignments.copy()
                new_assignments[course] = block
                
                result = find_valid_combination(remaining_courses[1:], new_used_blocks, new_assignments)
                if result:
                    return result
            
            return None
        
        valid_combo = find_valid_combination(all_courses, set(), {})
        if valid_combo:
            # Calculate capacity of this combination
            combo_capacities = []
            for course, block in valid_combo.items():
                teachers = courses_by_hours[course]['blocks'][block]
                capacity = teachers * student_per_teacher
                combo_capacities.append(capacity)
                print(f"  {course}: Block {block} ({teachers} teachers, {capacity} students)")
            
            min_combo_capacity = min(combo_capacities)
            print(f"\n  This combination can accommodate {min_combo_capacity} students")
            if min_combo_capacity < student_count:
                print(f"  ⚠️ This is less than the target {student_count} students")
            else:
                print(f"  ✅ This meets the target of {student_count} students")
    
    # Calculate remaining capacity needed
    capacity_needed = {}
    if not all_blocks_sufficient:
        print("\nADDITIONAL CAPACITY NEEDED:")
        for block in problematic_blocks:
            deficit = max_students_per_block - block_capacity[block]
            teachers_needed = math.ceil(deficit / student_per_teacher)
            capacity_needed[block] = {
                'deficit': deficit,
                'teachers': teachers_needed
            }
            print(f"  {block}: {deficit} more student slots ({teachers_needed} teachers)")
    
    # Final conclusion
    print("\n" + "="*80)
    print("CONCLUSION")
    valid_for_all = valid_combination_exists and all_courses_sufficient and all_blocks_sufficient
    
    if valid_for_all:
        print(f"✅ The current distribution CAN support {student_count} students.")
        print("All students should be able to find a valid combination of courses.")
    else:
        print(f"❌ The current distribution CANNOT support {student_count} students.")
        
        if actual_student_count < student_count:
            print(f"Maximum supportable students: {actual_student_count} (limited by course capacity)")
        
        if not valid_combination_exists:
            print("❌ No valid combination of courses exists due to block conflicts.")
        
        if not all_courses_sufficient:
            print(f"❌ Courses with insufficient capacity: {', '.join(problematic_courses)}")
        
        if not all_blocks_sufficient:
            print(f"❌ Blocks with insufficient capacity: {', '.join(problematic_blocks)}")
            
            # Show how many more teachers are needed
            print("\nMore teachers needed:")
            total_additional_teachers = sum(info['teachers'] for info in capacity_needed.values())
            for block, info in capacity_needed.items():
                print(f"  {block}: {info['teachers']} more teachers ({info['deficit']} student slots)")
            print(f"  Total: {total_additional_teachers} more teachers needed across problematic blocks")
    
    print("="*80)
    
    return valid_for_all

def main():
    # Find the latest output directory
    output_dir = find_latest_output_dir()
    if not output_dir:
        sys.exit(1)
    
    print(f"Analyzing latest output directory: {output_dir}")
    
    # Load schedule data
    schedule_df = load_schedule_data(output_dir)
    if schedule_df is None:
        sys.exit(1)
    
    # Extract teacher distribution
    distribution = extract_teacher_distribution(schedule_df)
    
    # Analyze combinations for 700 students
    analyze_combinations(distribution, student_per_teacher=70, student_count=700)

if __name__ == "__main__":
    main() 