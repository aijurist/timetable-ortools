#!/usr/bin/env python3
"""
Extract Group Details from Combined Schedule

This script extracts group details from both lab and theory schedules 
and returns the output in the same format as CourseGroupOptimizer.
Lab and theory instances of the same course instance are combined into single instances.
Virtual instances (like 493-A, 493-B) are handled as separate sections of the same course.
"""

import pandas as pd
import json
from collections import defaultdict
import argparse
import os
import re


def get_base_instance_id(course_instance_id):
    """
    Extract base instance ID from virtual instance IDs.
    
    Args:
        course_instance_id: Course instance ID (e.g., '493-A', '493-B', '493', '504')
    
    Returns:
        str: Base instance ID (e.g., '493' for both '493-A' and '493-B')
    """
    # Remove virtual suffixes like -A, -B, etc.
    base_id = re.sub(r'-[A-Z]$', '', str(course_instance_id))
    return base_id


def is_virtual_instance(course_instance_id):
    """
    Check if a course instance ID is a virtual instance.
    
    Args:
        course_instance_id: Course instance ID
    
    Returns:
        bool: True if it's a virtual instance (e.g., '493-A'), False otherwise
    """
    return bool(re.search(r'-[A-Z]$', str(course_instance_id)))


def extract_groups_from_schedules(lab_schedule_file, theory_schedule_file):
    """
    Extract group details from both lab and theory schedules.
    
    Args:
        lab_schedule_file: Path to lab schedule CSV
        theory_schedule_file: Path to theory schedule CSV
    
    Returns:
        dict: Group details organized by department and semester
    """
    # Read both schedules
    lab_df = pd.read_csv(lab_schedule_file)
    theory_df = pd.read_csv(theory_schedule_file)
    
    # Combine all course instances from both schedules
    # Key: (dept, semester, group_index), Value: {'courses': {course_instance_id: course_data}}
    all_groups = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))
    
    # Track 140-student courses to create virtual A and B instances
    course_140_instances = {}  # base_id -> course_data
    
    # Process lab schedule
    print("Processing lab schedule...")
    for _, row in lab_df.iterrows():
        dept = row['department']
        semester = row['semester']
        group_name = row['group_name']
        group_index = row['group_index']
        course_instance_id = str(row['course_instance_id'])
        course_code = row['course_code']
        
        # Group by (dept, semester, group_index)
        group_key = (dept, semester, group_index)
        
        # Check if this is a 140-student course (student_count = 140)
        is_140_course = int(row['student_count']) == 140
        
        if is_140_course:
            # For 140-student courses, store the base data and create virtual A and B instances
            base_id = get_base_instance_id(course_instance_id)
            course_140_instances[base_id] = {
                'lab_data': row,
                'group_key': group_key,
                'group_name': group_name
            }
            
            # Create both A and B virtual instances
            for suffix in ['A', 'B']:
                virtual_id = f"{base_id}-{suffix}"
                
                all_groups[group_key]['courses'][virtual_id] = {
                    'id': virtual_id,
                    'base_id': base_id,
                    'is_virtual': True,
                    'is_140_course': True,
                    'virtual_instances': [f"{base_id}-A", f"{base_id}-B"],
                    'teacher_id': str(row['teacher_id']),
                    'course_id': row.get('course_id', ''),
                    'course_code': course_code,
                    'course_name': row['course_name'],
                    'lecture_hours': 0,
                    'tutorial_hours': 0,
                    'practical_hours': 0,
                    'student_count': int(row['student_count']) // 2,  # Split 140 students into 70 each
                    'semester': semester,
                    'course_dept': dept,
                    'student_dept': dept,
                    'has_lab': False,
                    'has_theory': False,
                    'teacher_name': row['teacher_name'],
                    'staff_code': row['staff_code'],
                    'lab_teacher_id': None,
                    'lab_teacher_name': None,
                    'lab_staff_code': None,
                    'theory_teacher_id': None,
                    'theory_teacher_name': None,
                    'theory_staff_code': None
                }
                
                # Update with lab information
                course_instance = all_groups[group_key]['courses'][virtual_id]
                course_instance['practical_hours'] = int(row['practical_hours'])
                course_instance['has_lab'] = True
                course_instance['lab_teacher_id'] = str(row['teacher_id'])
                course_instance['lab_teacher_name'] = row['teacher_name']
                course_instance['lab_staff_code'] = row['staff_code']
        else:
            # Handle regular instances (including existing virtual instances like 493-A)
            instance_key = course_instance_id
            
            # Create or update course instance
            if instance_key not in all_groups[group_key]['courses']:
                all_groups[group_key]['courses'][instance_key] = {
                    'id': course_instance_id,
                    'base_id': get_base_instance_id(course_instance_id),
                    'is_virtual': is_virtual_instance(course_instance_id),
                    'is_140_course': False,
                    'virtual_instances': [],
                    'teacher_id': str(row['teacher_id']),
                    'course_id': row.get('course_id', ''),
                    'course_code': course_code,
                    'course_name': row['course_name'],
                    'lecture_hours': 0,
                    'tutorial_hours': 0,
                    'practical_hours': 0,
                    'student_count': int(row['student_count']),
                    'semester': semester,
                    'course_dept': dept,
                    'student_dept': dept,
                    'has_lab': False,
                    'has_theory': False,
                    'teacher_name': row['teacher_name'],
                    'staff_code': row['staff_code'],
                    'lab_teacher_id': None,
                    'lab_teacher_name': None,
                    'lab_staff_code': None,
                    'theory_teacher_id': None,
                    'theory_teacher_name': None,
                    'theory_staff_code': None
                }
            
            # Update with lab information
            course_instance = all_groups[group_key]['courses'][instance_key]
            course_instance['practical_hours'] = int(row['practical_hours'])
            course_instance['has_lab'] = True
            course_instance['lab_teacher_id'] = str(row['teacher_id'])
            course_instance['lab_teacher_name'] = row['teacher_name']
            course_instance['lab_staff_code'] = row['staff_code']
        
        # Set group metadata
        all_groups[group_key]['group_name'] = group_name
    
    # Process theory schedule
    print("Processing theory schedule...")
    for _, row in theory_df.iterrows():
        dept = row['department']
        semester = row['semester']
        group_name = row['group_name']
        group_index = row['group_index']
        course_instance_id = str(row['course_instance_id'])
        course_code = row['course_code']
        
        # Group by (dept, semester, group_index)
        group_key = (dept, semester, group_index)
        
        # Check if this is a 140-student course or virtual instance of one
        is_140_course = "Combined 140-student course" in row['course_name']
        base_id = get_base_instance_id(course_instance_id)
        
        if is_140_course:
            # For 140-student courses, update the virtual A and B instances
            for suffix in ['A', 'B']:
                virtual_id = f"{base_id}-{suffix}"
                
                if virtual_id in all_groups[group_key]['courses']:
                    # Update existing virtual instance with theory information
                    course_instance = all_groups[group_key]['courses'][virtual_id]
                    course_instance['lecture_hours'] = int(row['lecture_hours'])
                    course_instance['tutorial_hours'] = int(row['tutorial_hours'])
                    course_instance['has_theory'] = True
                    course_instance['theory_teacher_id'] = str(row['teacher_id'])
                    course_instance['theory_teacher_name'] = row['teacher_name']
                    course_instance['theory_staff_code'] = row['staff_code']
                    
                    # Update course name to include "Combined 140-student course"
                    course_instance['course_name'] = row['course_name']
                else:
                    # Create virtual instance if it doesn't exist (theory-only 140-student course)
                    all_groups[group_key]['courses'][virtual_id] = {
                        'id': virtual_id,
                        'base_id': base_id,
                        'is_virtual': True,
                        'is_140_course': True,
                        'virtual_instances': [f"{base_id}-A", f"{base_id}-B"],
                        'teacher_id': str(row['teacher_id']),
                        'course_id': row.get('course_id', ''),
                        'course_code': course_code,
                        'course_name': row['course_name'],
                        'lecture_hours': int(row['lecture_hours']),
                        'tutorial_hours': int(row['tutorial_hours']),
                        'practical_hours': 0,
                        'student_count': int(row['student_count']) // 2,  # Split 140 students into 70 each
                        'semester': semester,
                        'course_dept': dept,
                        'student_dept': dept,
                        'has_lab': False,
                        'has_theory': True,
                        'teacher_name': row['teacher_name'],
                        'staff_code': row['staff_code'],
                        'lab_teacher_id': None,
                        'lab_teacher_name': None,
                        'lab_staff_code': None,
                        'theory_teacher_id': str(row['teacher_id']),
                        'theory_teacher_name': row['teacher_name'],
                        'theory_staff_code': row['staff_code']
                    }
        else:
            # Handle regular instances
            instance_key = course_instance_id
            
            # Create or update course instance
            if instance_key not in all_groups[group_key]['courses']:
                all_groups[group_key]['courses'][instance_key] = {
                    'id': course_instance_id,
                    'base_id': get_base_instance_id(course_instance_id),
                    'is_virtual': is_virtual_instance(course_instance_id),
                    'is_140_course': False,
                    'virtual_instances': [],
                    'teacher_id': str(row['teacher_id']),
                    'course_id': row.get('course_id', ''),
                    'course_code': course_code,
                    'course_name': row['course_name'],
                    'lecture_hours': 0,
                    'tutorial_hours': 0,
                    'practical_hours': 0,
                    'student_count': int(row['student_count']),
                    'semester': semester,
                    'course_dept': dept,
                    'student_dept': dept,
                    'has_lab': False,
                    'has_theory': False,
                    'teacher_name': row['teacher_name'],
                    'staff_code': row['staff_code'],
                    'lab_teacher_id': None,
                    'lab_teacher_name': None,
                    'lab_staff_code': None,
                    'theory_teacher_id': None,
                    'theory_teacher_name': None,
                    'theory_staff_code': None
                }
            
            # Update with theory information
            course_instance = all_groups[group_key]['courses'][instance_key]
            course_instance['lecture_hours'] = int(row['lecture_hours'])
            course_instance['tutorial_hours'] = int(row['tutorial_hours'])
            course_instance['has_theory'] = True
            course_instance['theory_teacher_id'] = str(row['teacher_id'])
            course_instance['theory_teacher_name'] = row['teacher_name']
            course_instance['theory_staff_code'] = row['staff_code']
            
            # Update primary teacher info to theory teacher if this is a theory-only course
            if not course_instance['has_lab']:
                course_instance['teacher_id'] = str(row['teacher_id'])
                course_instance['teacher_name'] = row['teacher_name']
                course_instance['staff_code'] = row['staff_code']
        
        # Set group metadata
        all_groups[group_key]['group_name'] = group_name
    
    # Post-process to finalize combined instances
    for group_key in all_groups:
        for instance_key, course_instance in all_groups[group_key]['courses'].items():
            # Determine course type for display
            if course_instance['has_lab'] and course_instance['has_theory']:
                course_instance['course_type'] = 'combined'
                course_instance['schedule_type'] = 'combined'
                # For combined courses, use theory teacher as primary if different from lab teacher
                if (course_instance['theory_teacher_id'] and 
                    course_instance['theory_teacher_id'] != course_instance['lab_teacher_id']):
                    course_instance['teacher_id'] = course_instance['theory_teacher_id']
                    course_instance['teacher_name'] = course_instance['theory_teacher_name']
                    course_instance['staff_code'] = course_instance['theory_staff_code']
            elif course_instance['has_lab']:
                course_instance['course_type'] = 'lab'
                course_instance['schedule_type'] = 'lab'
                course_instance['teacher_id'] = course_instance['lab_teacher_id']
                course_instance['teacher_name'] = course_instance['lab_teacher_name']
                course_instance['staff_code'] = course_instance['lab_staff_code']
            else:
                course_instance['course_type'] = 'theory'
                course_instance['schedule_type'] = 'theory'
                course_instance['teacher_id'] = course_instance['theory_teacher_id']
                course_instance['teacher_name'] = course_instance['theory_teacher_name']
                course_instance['staff_code'] = course_instance['theory_staff_code']
    
    return all_groups


def format_output_like_optimization(all_groups):
    """
    Format the output to match the optimization results structure.
    
    Args:
        all_groups: Dictionary of group data
    
    Returns:
        dict: Formatted data matching optimization results format
    """
    formatted_data = {}
    
    for group_key, group_data in all_groups.items():
        dept, semester, group_index = group_key
        dept_sem_key = f"{dept}_S{semester}"
        
        if dept_sem_key not in formatted_data:
            formatted_data[dept_sem_key] = {
                "department": dept,
                "semester": str(semester),
                "groups": [],
                "summary": {
                    "total_instances": 0,
                    "pe_instances": 0,
                    "lab_instances": 0,
                    "theory_instances": 0,
                    "unique_courses": set(),
                    "unique_teachers": set(),
                    "pe_course_codes": set()
                }
            }
        
        # Determine if this is a PE group based on course codes
        is_pe_group = any(
            'PE' in inst['course_code'] for inst in group_data['courses'].values()
        )
        
        # Format instances
        instances = []
        teachers = set()
        courses = set()
        total_workload = 0
        
        for instance_key, inst in group_data['courses'].items():
            # Determine course type
            if inst['has_lab'] and inst['has_theory']:
                course_type = "LoT"
            elif inst['has_lab']:
                course_type = "L"
            else:
                course_type = "T"
            
            # Format instance
            instance_data = {
                "id": inst['id'] if not inst['id'].isdigit() else int(inst['id']),
                "course_id": inst.get('course_id', ''),
                "course_code": inst['course_code'],
                "course_name": inst['course_name'],
                "course_type": course_type,
                "teacher_id": inst['teacher_id'],
                "semester": inst['semester'],
                "course_dept": inst['course_dept'],
                "student_dept": inst['student_dept'],
                "has_lab": inst['has_lab'],
                "has_theory": inst['has_theory'],
                "practical_hours": inst['practical_hours'],
                "lecture_hours": inst['lecture_hours'],
                "tutorial_hours": inst['tutorial_hours'],
                "student_count": inst['student_count'],
                "virtual_id": inst['id'] if inst['is_virtual'] else None,
                "co_scheduled_id": 1 if inst['is_140_course'] else None
            }
            
            instances.append(instance_data)
            teachers.add(inst['teacher_id'])
            courses.add(inst['course_code'])
            
            # Calculate workload
            total_workload += inst['lecture_hours'] + inst['tutorial_hours'] + inst['practical_hours']
            
            # Update summary
            formatted_data[dept_sem_key]["summary"]["total_instances"] += 1
            if is_pe_group:
                formatted_data[dept_sem_key]["summary"]["pe_instances"] += 1
                formatted_data[dept_sem_key]["summary"]["pe_course_codes"].add(inst['course_code'])
            if inst['has_lab']:
                formatted_data[dept_sem_key]["summary"]["lab_instances"] += 1
            if inst['has_theory']:
                formatted_data[dept_sem_key]["summary"]["theory_instances"] += 1
            
            formatted_data[dept_sem_key]["summary"]["unique_courses"].add(inst['course_code'])
            formatted_data[dept_sem_key]["summary"]["unique_teachers"].add(inst['teacher_id'])
        
        # Create group data
        group_data_formatted = {
            "group_id": group_index,
            "is_pe_group": is_pe_group,
            "group_type": "PE" if is_pe_group else "Regular",
            "instances": instances,
            "teachers": sorted(list(teachers)),
            "courses": sorted(list(courses)),
            "total_workload": total_workload
        }
        
        formatted_data[dept_sem_key]["groups"].append(group_data_formatted)
    
    # Convert sets to lists in summary
    for dept_sem_key in formatted_data:
        summary = formatted_data[dept_sem_key]["summary"]
        summary["unique_courses"] = len(summary["unique_courses"])
        summary["unique_teachers"] = len(summary["unique_teachers"])
        summary["pe_course_codes"] = sorted(list(summary["pe_course_codes"]))
        
        # Add additional fields to match optimization format
        formatted_data[dept_sem_key]["solution_found"] = True
        formatted_data[dept_sem_key]["objective_value"] = 0.0
        formatted_data[dept_sem_key]["num_groups"] = len(formatted_data[dept_sem_key]["groups"])
        formatted_data[dept_sem_key]["pe_group_included"] = any(g["is_pe_group"] for g in formatted_data[dept_sem_key]["groups"])
    
    return formatted_data


def main():
    parser = argparse.ArgumentParser(description='Extract group details from combined schedules')
    parser.add_argument('--lab-schedule', 
                       default='data/timetable/combined_schedule_20250628_085608/combined_lab_schedule.csv',
                       help='Path to lab schedule CSV file')
    parser.add_argument('--theory-schedule', 
                       default='data/timetable/combined_schedule_20250628_085608/combined_theory_schedule.csv',
                       help='Path to theory schedule CSV file')
    parser.add_argument('--dept', help='Filter by department name')
    parser.add_argument('--semester', type=int, help='Filter by semester number')
    parser.add_argument('--output', default='extracted_group_details_optimization_format.json',
                       help='Output JSON file name')
    
    args = parser.parse_args()
    
    print("Extracting group details from combined schedules...")
    print("Note: Lab and theory instances of the same course instance will be combined")
    print("Note: 140-student courses will be split into separate A and B virtual instances")
    print("Note: Output format matches optimization results structure")
    
    all_groups = extract_groups_from_schedules(args.lab_schedule, args.theory_schedule)
    
    # Format in optimization style
    formatted_output = format_output_like_optimization(all_groups)
    
    # Apply filters if specified
    if args.dept or args.semester:
        filtered_output = {}
        for dept_sem_key, data in formatted_output.items():
            dept_name = data['department']
            semester = int(data['semester'])
            
            if args.dept and args.dept.lower() not in dept_name.lower():
                continue
            if args.semester and args.semester != semester:
                continue
            
            filtered_output[dept_sem_key] = data
        formatted_output = filtered_output
    
    # Save to JSON file
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(formatted_output, f, indent=2, ensure_ascii=False)
    
    # Print summary
    print(f"\n{'='*80}")
    print("EXTRACTED GROUP DETAILS (Optimization Format)")
    print(f"{'='*80}")
    
    for dept_sem_key, data in formatted_output.items():
        print(f"\n{data['department']} - Semester {data['semester']}")
        print("-" * 60)
        print(f"Solution Found: {data['solution_found']}")
        print(f"Objective Value: {data['objective_value']}")
        print(f"Number of Groups: {data['num_groups']}")
        print(f"PE Group Included: {data['pe_group_included']}")
        print(f"Total Instances: {data['summary']['total_instances']}")
        print(f"PE Instances: {data['summary']['pe_instances']}")
        print(f"Lab Instances: {data['summary']['lab_instances']}")
        print(f"Theory Instances: {data['summary']['theory_instances']}")
        print(f"Unique Courses: {data['summary']['unique_courses']}")
        print(f"Unique Teachers: {data['summary']['unique_teachers']}")
        print(f"PE Course Codes: {data['summary']['pe_course_codes']}")
        
        print(f"\nGroups:")
        for group in data['groups']:
            print(f"  Group {group['group_id']} ({group['group_type']}):")
            print(f"    PE Group: {group['is_pe_group']}")
            print(f"    Instances: {len(group['instances'])}")
            print(f"    Teachers: {group['teachers']}")
            print(f"    Courses: {group['courses']}")
            print(f"    Total Workload: {group['total_workload']}")
            
            print(f"    Instance Details:")
            for inst in group['instances']:
                virtual_info = f" (Virtual: {inst['virtual_id']})" if inst['virtual_id'] else ""
                co_sched_info = f" (Co-scheduled: {inst['co_scheduled_id']})" if inst['co_scheduled_id'] else ""
                print(f"      {inst['id']}: {inst['course_code']} - {inst['course_type']} - Teacher: {inst['teacher_id']} - Students: {inst['student_count']}{virtual_info}{co_sched_info}")
    
    print(f"\nDetailed data saved to: {args.output}")
    print(f"{'='*80}")


if __name__ == "__main__":
    main() 