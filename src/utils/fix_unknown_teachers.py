#!/usr/bin/env python3
"""
Script to fix Unknown teachers by assigning unique IDs
"""

import pandas as pd
import os

def fix_unknown_teachers():
    """Assign unique teacher IDs to Unknown teachers."""
    
    # Read the data
    csv_file = 'timetable_scheduler/data/cse.csv'
    df = pd.read_csv(csv_file)
    
    print(f"Original data shape: {df.shape}")
    print(f"Unknown teachers before fix: {(df['teacher_id'] == 'Unknown').sum()}")
    
    # Find the highest existing teacher ID to start numbering from
    numeric_teacher_ids = []
    for teacher_id in df['teacher_id'].unique():
        if teacher_id != 'Unknown' and str(teacher_id).isdigit():
            numeric_teacher_ids.append(int(teacher_id))
    
    if numeric_teacher_ids:
        next_id = max(numeric_teacher_ids) + 1
    else:
        next_id = 1000  # Start from 1000 if no numeric IDs exist
    
    print(f"Starting unknown teacher IDs from: {next_id}")
    
    # Create backup
    backup_file = csv_file + '.backup'
    df.to_csv(backup_file, index=False)
    print(f"Backup created: {backup_file}")
    
    # Assign unique IDs to Unknown teachers
    unknown_mask = df['teacher_id'] == 'Unknown'
    unknown_indices = df[unknown_mask].index.tolist()
    
    # Group by course to assign same teacher ID to same course instances
    unknown_courses = df[unknown_mask].groupby(['course_code', 'course_name']).first().reset_index()
    
    # Create mapping of course to unique teacher ID
    course_to_teacher_id = {}
    teacher_id_counter = next_id
    
    for _, course_row in unknown_courses.iterrows():
        course_key = (course_row['course_code'], course_row['course_name'])
        course_to_teacher_id[course_key] = teacher_id_counter
        print(f"Assigning Teacher ID {teacher_id_counter} to course: {course_row['course_code']} - {course_row['course_name']}")
        teacher_id_counter += 1
    
    # Apply the mapping to all unknown teacher entries
    for idx in unknown_indices:
        course_code = df.loc[idx, 'course_code']
        course_name = df.loc[idx, 'course_name']
        course_key = (course_code, course_name)
        
        new_teacher_id = course_to_teacher_id[course_key]
        df.loc[idx, 'teacher_id'] = new_teacher_id
        
        # Also update staff_code and names to be meaningful
        df.loc[idx, 'staff_code'] = f'CS{new_teacher_id}'
        df.loc[idx, 'first_name'] = f'Teacher_{new_teacher_id}'
        df.loc[idx, 'last_name'] = 'Unknown'
        df.loc[idx, 'teacher_email'] = f'teacher_{new_teacher_id}@university.edu'
    
    # Verify the fix
    print(f"Unknown teachers after fix: {(df['teacher_id'] == 'Unknown').sum()}")
    print(f"New unique teachers created: {len(course_to_teacher_id)}")
    
    # Save the updated data
    df.to_csv(csv_file, index=False)
    print(f"Updated data saved to: {csv_file}")
    
    # Print summary of changes
    print("\nSummary of teacher assignments:")
    for course_key, teacher_id in course_to_teacher_id.items():
        course_code, course_name = course_key
        count = ((df['course_code'] == course_code) & 
                (df['course_name'] == course_name) & 
                (df['teacher_id'] == teacher_id)).sum()
        print(f"  Teacher {teacher_id} ({course_code}): {count} course instances")
    
    return True

if __name__ == '__main__':
    fix_unknown_teachers() 