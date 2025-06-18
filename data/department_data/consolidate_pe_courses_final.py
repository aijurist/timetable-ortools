#!/usr/bin/env python3
"""
Professional Elective Course Consolidation Script - Universal Version

This script consolidates Professional Elective courses for all departments
based on the pe.csv mapping. It updates course codes and names while 
preserving all course instances and taking the maximum lecture, tutorial, 
and practical hours.
"""

import pandas as pd
import os
import shutil
from collections import defaultdict

def load_pe_mapping():
    """Load and process the PE mapping from pe.csv to understand course groupings."""
    try:
        pe_df = pd.read_csv('../pe.csv')
        
        # Group PE courses by department and PE group
        pe_mapping = defaultdict(lambda: defaultdict(list))
        
        for _, row in pe_df.iterrows():
            if pd.notna(row['course_id']) and pd.notna(row['course_dept']) and pd.notna(row['Professional Elective']):
                dept = row['course_dept']
                pe_group = row['Professional Elective']
                course_code = row['course_code']
                course_name = row['course_name']
                course_id = row['course_id']
                
                pe_mapping[dept][pe_group].append({
                    'course_id': course_id,
                    'course_code': course_code,
                    'course_name': course_name,
                    'lecture_hours': row.get('lecture_hours', 0),
                    'practical_hours': row.get('practical_hours', 0),
                    'tutorial_hours': row.get('tutorial_hours', 0),
                    'credits': row.get('credits', 0)
                })
        
        return pe_mapping
    except Exception as e:
        print(f"Error loading pe.csv: {e}")
        return None

def identify_department_from_file(file_path):
    """Identify the department from the file path or data."""
    if 'Artificial_Intelligence___Machine_Learning' in file_path:
        return 'Artificial Intelligence & Machine Learning'
    elif 'Computing_department' in file_path:
        # For Computing department, we need to check the data to see which departments are present
        return 'Mixed'  # Will handle multiple departments
    else:
        # Extract department name from filename if possible
        filename = os.path.basename(file_path)
        return filename.replace('_courses.csv', '').replace('_', ' ')

def consolidate_pe_courses_universal(file_path):
    """Consolidate PE courses for any department file based on pe.csv mapping."""
    
    # Load PE mapping
    pe_mapping = load_pe_mapping()
    if not pe_mapping:
        print("Failed to load PE mapping from pe.csv")
        return False
    
    print(f"Processing file: {file_path}")
    
    # Load the department file
    try:
        df = pd.read_csv(file_path)
        print(f"Loaded {len(df)} course instances")
    except Exception as e:
        print(f"Error loading {file_path}: {e}")
        return False
    
    # Create backup
    backup_file = file_path.replace('.csv', '_backup.csv')
    shutil.copy2(file_path, backup_file)
    print(f"Created backup: {backup_file}")
    
    changes_made = False
    consolidation_summary = defaultdict(list)
    
    # Process each department in the PE mapping
    for dept_name, pe_groups in pe_mapping.items():
        print(f"\nProcessing department: {dept_name}")
        
        # Filter courses for this department (check both course_dept and teaching_dept)
        dept_courses = df[
            (df['course_dept'].str.contains(dept_name, na=False)) |
            (df['teaching_dept'].str.contains(dept_name, na=False)) |
            (df['student_dept'].str.contains(dept_name, na=False))
        ]
        
        if dept_courses.empty:
            print(f"  No courses found for {dept_name}")
            continue
        
        print(f"  Found {len(dept_courses)} course instances for {dept_name}")
        
        # Process each PE group for this department
        for pe_group, pe_courses in pe_groups.items():
            if len(pe_courses) <= 1:
                continue  # Skip groups with only one course
                
            print(f"    Processing {pe_group}: {len(pe_courses)} courses to consolidate")
            
            # Find course instances that match the PE courses in this group
            course_codes_in_group = [course['course_code'] for course in pe_courses]
            course_ids_in_group = [course['course_id'] for course in pe_courses]
            
            # Find matching instances in the dataframe
            matching_instances = df[
                (df['course_code'].isin(course_codes_in_group)) |
                (df['course_id'].isin(course_ids_in_group))
            ]
            
            if matching_instances.empty:
                print(f"      No instances found for {pe_group}")
                continue
            
            print(f"      Found {len(matching_instances)} instances to consolidate")
            
            # Calculate consolidated course details
            max_lecture_hours = max([course['lecture_hours'] for course in pe_courses if pd.notna(course['lecture_hours'])] or [0])
            max_practical_hours = max([course['practical_hours'] for course in pe_courses if pd.notna(course['practical_hours'])] or [0])
            max_tutorial_hours = max([course['tutorial_hours'] for course in pe_courses if pd.notna(course['tutorial_hours'])] or [0])
            max_credits = max([course['credits'] for course in pe_courses if pd.notna(course['credits'])] or [0])
            
            # Use the first course code as the unified code
            unified_course_code = pe_courses[0]['course_code']
            unified_course_name = f"{pe_group} (Consolidated)"
            
            # Update all matching instances
            for idx in matching_instances.index:
                df.at[idx, 'course_code'] = unified_course_code
                df.at[idx, 'course_name'] = unified_course_name
                df.at[idx, 'lecture_hours'] = max_lecture_hours
                df.at[idx, 'practical_hours'] = max_practical_hours
                df.at[idx, 'tutorial_hours'] = max_tutorial_hours
                df.at[idx, 'credits'] = max_credits
                
                changes_made = True
                
                # Track for summary
                consolidation_summary[pe_group].append({
                    'teacher_id': df.at[idx, 'teacher_id'],
                    'old_course_code': matching_instances.at[idx, 'course_code'],
                    'new_course_code': unified_course_code,
                    'new_course_name': unified_course_name
                })
            
            print(f"      ✅ Consolidated {len(matching_instances)} instances into {unified_course_code} - {unified_course_name}")
            print(f"         Hours: L={max_lecture_hours}, P={max_practical_hours}, T={max_tutorial_hours}, Credits={max_credits}")
    
    if changes_made:
        # Save the updated file
        df.to_csv(file_path, index=False)
        print(f"\n✅ Updated file saved: {file_path}")
        
        # Print consolidation summary
        print(f"\n📊 CONSOLIDATION SUMMARY:")
        for pe_group, instances in consolidation_summary.items():
            print(f"\n{pe_group}:")
            print(f"  Total instances: {len(instances)}")
            unique_teachers = set([inst['teacher_id'] for inst in instances])
            print(f"  Teachers involved: {sorted(unique_teachers)}")
            if instances:
                print(f"  Unified as: {instances[0]['new_course_code']} - {instances[0]['new_course_name']}")
    else:
        print(f"\n⚠️  No Professional Elective courses found for consolidation in {file_path}")
    
    return changes_made

def final_verification(file_path):
    """Verify the consolidation results."""
    try:
        df = pd.read_csv(file_path)
        
        # Find all PE courses
        pe_courses = df[df['course_name'].str.contains('PE.*Consolidated', na=False)]
        
        if pe_courses.empty:
            consolidated_courses = df[df['course_name'].str.contains('Professional Elective.*Consolidated', na=False)]
            pe_courses = consolidated_courses
        
        print(f"\n🔍 FINAL VERIFICATION:")
        print(f"Total course instances: {len(df)}")
        
        if not pe_courses.empty:
            print(f"Professional Elective courses found: {len(pe_courses)}")
            
            # Group by course code and name
            pe_groups = pe_courses.groupby(['course_code', 'course_name']).size().reset_index(name='instances')
            
            for _, group in pe_groups.iterrows():
                print(f"  {group['course_code']} - {group['course_name']}: {group['instances']} instances")
                
                # Show teachers for this group
                group_courses = pe_courses[
                    (pe_courses['course_code'] == group['course_code']) & 
                    (pe_courses['course_name'] == group['course_name'])
                ]
                teachers = sorted(group_courses['teacher_id'].unique())
                print(f"    Teachers: {teachers}")
        else:
            print("No consolidated Professional Elective courses found")
            
        return True
        
    except Exception as e:
        print(f"Error in verification: {e}")
        return False

def main():
    """Main function to consolidate PE courses."""
    
    # List of possible department files to process
    department_files = [
        'Computing_department.csv',
        'Artificial_Intelligence___Machine_Learning_courses.csv'
        # Add more department files as needed
    ]
    
    files_processed = 0
    
    for file_name in department_files:
        if os.path.exists(file_name):
            print(f"\n{'='*60}")
            print(f"PROCESSING: {file_name}")
            print(f"{'='*60}")
            
            success = consolidate_pe_courses_universal(file_name)
            if success:
                final_verification(file_name)
                files_processed += 1
        else:
            print(f"File not found: {file_name}")
    
    print(f"\n{'='*60}")
    print(f"CONSOLIDATION COMPLETE!")
    print(f"Files processed: {files_processed}")
    print(f"{'='*60}")

if __name__ == "__main__":
    main() 