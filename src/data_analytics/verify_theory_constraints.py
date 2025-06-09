#!/usr/bin/env python3
"""
Theory Schedule Constraint Verification Script

This script verifies that the generated theory schedule meets all the required constraints:
1. Correct number of lecture/tutorial hours per course
2. No teacher assigned to multiple classes at the same time
3. No room double-booked
4. Each course has the right number of sessions
"""

import os
import sys
import json
import pandas as pd
import argparse
from collections import defaultdict

def load_schedule(schedule_file):
    """Load the theory schedule from JSON or CSV file."""
    if schedule_file.endswith('.json'):
        with open(schedule_file, 'r') as f:
            return json.load(f)
    elif schedule_file.endswith('.csv'):
        df = pd.read_csv(schedule_file)
        return df.to_dict('records')
    else:
        raise ValueError("Schedule file must be either JSON or CSV format")

def verify_lecture_hours(schedule_data, course_file=None):
    """Verify that each course has the correct number of lecture/tutorial hours scheduled."""
    # Load original course requirements if available
    course_requirements = {}
    if course_file and os.path.exists(course_file):
        course_df = pd.read_csv(course_file)
        for _, row in course_df.iterrows():
            course_id = row.get('course_id', 'unknown')
            course_code = row.get('course_code', 'unknown')
            lecture_hours = int(row.get('lecture_hours', 0))
            course_requirements[course_code] = {
                'id': course_id,
                'lecture_hours': lecture_hours
            }
    
    # Count actual scheduled hours
    scheduled_hours = defaultdict(int)
    for session in schedule_data:
        course_code = session.get('course_code', 'unknown')
        # Each theory session is typically 1 hour
        scheduled_hours[course_code] += 1
    
    # Compare scheduled vs required
    discrepancies = []
    
    if course_requirements:
        # If we have the original requirements, compare against them
        for course_code, req in course_requirements.items():
            required_hours = req['lecture_hours']
            actual_hours = scheduled_hours.get(course_code, 0)
            
            if required_hours > 0 and actual_hours != required_hours:
                discrepancies.append({
                    'course_code': course_code,
                    'required_hours': required_hours,
                    'scheduled_hours': actual_hours,
                    'difference': actual_hours - required_hours
                })
    else:
        # Without original requirements, check internal consistency with theory_hours field
        course_requirements = {}
        for session in schedule_data:
            course_code = session.get('course_code', 'unknown')
            theory_hours = session.get('theory_hours', 0)
            if theory_hours > 0 and course_code not in course_requirements:
                course_requirements[course_code] = {'theory_hours': theory_hours}
        
        for course_code, req in course_requirements.items():
            required_hours = req['theory_hours']
            actual_hours = scheduled_hours.get(course_code, 0)
            
            if actual_hours != required_hours:
                discrepancies.append({
                    'course_code': course_code,
                    'required_hours': required_hours,
                    'scheduled_hours': actual_hours,
                    'difference': actual_hours - required_hours
                })
    
    return discrepancies

def verify_teacher_conflicts(schedule_data):
    """Verify no teacher is scheduled for multiple sessions at the same time."""
    teacher_schedule = defaultdict(list)
    teacher_conflicts = []
    
    for session in schedule_data:
        teacher_id = session.get('teacher_id', 'unknown')
        day = session.get('day', 'unknown')
        time_slot = session.get('time_slot', session.get('slot_index', 0))
        course_code = session.get('course_code', 'unknown')
        
        time_key = f"{day}_{time_slot}"
        teacher_schedule[teacher_id].append({
            'time_key': time_key,
            'course_code': course_code,
            'day': day,
            'time_slot': time_slot
        })
    
    # Check for conflicts
    for teacher_id, sessions in teacher_schedule.items():
        time_counts = defaultdict(list)
        for session in sessions:
            time_counts[session['time_key']].append(session)
        
        # Find conflicts
        for time_key, overlaps in time_counts.items():
            if len(overlaps) > 1:
                teacher_conflicts.append({
                    'teacher_id': teacher_id,
                    'time_key': time_key,
                    'conflicts': overlaps
                })
    
    return teacher_conflicts

def verify_room_conflicts(schedule_data):
    """Verify no room is double-booked."""
    room_schedule = defaultdict(list)
    room_conflicts = []
    
    for session in schedule_data:
        room_id = session.get('room_id', 'unknown')
        day = session.get('day', 'unknown')
        time_slot = session.get('time_slot', session.get('slot_index', 0))
        course_code = session.get('course_code', 'unknown')
        teacher_id = session.get('teacher_id', 'unknown')
        
        time_key = f"{day}_{time_slot}"
        room_schedule[room_id].append({
            'time_key': time_key,
            'course_code': course_code,
            'teacher_id': teacher_id,
            'day': day,
            'time_slot': time_slot
        })
    
    # Check for conflicts
    for room_id, sessions in room_schedule.items():
        time_counts = defaultdict(list)
        for session in sessions:
            time_counts[session['time_key']].append(session)
        
        # Find conflicts
        for time_key, overlaps in time_counts.items():
            if len(overlaps) > 1:
                room_conflicts.append({
                    'room_id': room_id,
                    'time_key': time_key,
                    'conflicts': overlaps
                })
    
    return room_conflicts

def verify_group_conflicts(schedule_data):
    """Verify that different groups in the same semester don't have overlapping sessions."""
    group_schedule = defaultdict(list)
    group_conflicts = []
    
    for session in schedule_data:
        group_name = session.get('group_name', 'unknown')
        # Extract department and semester from group name (format: "dept_Ssemester_Ggroup")
        dept_sem = '_'.join(group_name.split('_')[:2]) if '_' in group_name else 'unknown'
        
        day = session.get('day', 'unknown')
        time_slot = session.get('time_slot', session.get('slot_index', 0))
        course_code = session.get('course_code', 'unknown')
        
        time_key = f"{day}_{time_slot}"
        group_schedule[dept_sem].append({
            'time_key': time_key,
            'group_name': group_name,
            'course_code': course_code,
            'day': day,
            'time_slot': time_slot
        })
    
    # Check for conflicts within same department/semester
    for dept_sem, sessions in group_schedule.items():
        time_group_counts = defaultdict(list)
        for session in sessions:
            time_group_counts[session['time_key']].append(session)
        
        # Find conflicts - different groups from same dept/semester in same time slot
        for time_key, overlaps in time_group_counts.items():
            if len(overlaps) > 1:
                # Check if different groups are involved
                groups = set(session['group_name'] for session in overlaps)
                if len(groups) > 1:  # Different groups
                    group_conflicts.append({
                        'dept_sem': dept_sem,
                        'time_key': time_key,
                        'conflicts': overlaps
                    })
    
    return group_conflicts

def verify_all_constraints(schedule_data, course_file=None):
    """Verify all theory schedule constraints."""
    results = {
        'lecture_hour_discrepancies': verify_lecture_hours(schedule_data, course_file),
        'teacher_conflicts': verify_teacher_conflicts(schedule_data),
        'room_conflicts': verify_room_conflicts(schedule_data),
        'group_conflicts': verify_group_conflicts(schedule_data)
    }
    
    return results

def display_results(results):
    """Display constraint verification results."""
    print("\n===== THEORY SCHEDULE CONSTRAINT VERIFICATION =====\n")
    
    # Check lecture hour discrepancies
    lecture_discrepancies = results['lecture_hour_discrepancies']
    if lecture_discrepancies:
        print(f"❌ LECTURE HOUR DISCREPANCIES: {len(lecture_discrepancies)} courses")
        for discrepancy in lecture_discrepancies:
            print(f"  - {discrepancy['course_code']}: Required {discrepancy['required_hours']} hours, " 
                  f"Scheduled {discrepancy['scheduled_hours']} hours "
                  f"(Diff: {discrepancy['difference']})")
    else:
        print("✅ LECTURE HOURS: All courses have correct number of hours scheduled")
    
    # Check teacher conflicts
    teacher_conflicts = results['teacher_conflicts']
    if teacher_conflicts:
        print(f"\n❌ TEACHER CONFLICTS: {len(teacher_conflicts)} conflicts")
        for conflict in teacher_conflicts[:5]:  # Show first 5 conflicts
            teacher_id = conflict['teacher_id']
            time_key = conflict['time_key']
            day, slot = time_key.split('_')
            courses = [c['course_code'] for c in conflict['conflicts']]
            print(f"  - Teacher {teacher_id} assigned multiple courses on {day} at slot {slot}: {', '.join(courses)}")
        if len(teacher_conflicts) > 5:
            print(f"    ... and {len(teacher_conflicts) - 5} more conflicts")
    else:
        print("✅ TEACHER CONFLICTS: No teachers double-booked")
    
    # Check room conflicts
    room_conflicts = results['room_conflicts']
    if room_conflicts:
        print(f"\n❌ ROOM CONFLICTS: {len(room_conflicts)} conflicts")
        for conflict in room_conflicts[:5]:  # Show first 5 conflicts
            room_id = conflict['room_id']
            time_key = conflict['time_key']
            day, slot = time_key.split('_')
            courses = [f"{c['course_code']} (T{c['teacher_id']})" for c in conflict['conflicts']]
            print(f"  - Room {room_id} double-booked on {day} at slot {slot}: {', '.join(courses)}")
        if len(room_conflicts) > 5:
            print(f"    ... and {len(room_conflicts) - 5} more conflicts")
    else:
        print("✅ ROOM CONFLICTS: No rooms double-booked")
    
    # Check group conflicts
    group_conflicts = results['group_conflicts']
    if group_conflicts:
        print(f"\n❌ GROUP CONFLICTS: {len(group_conflicts)} conflicts")
        for conflict in group_conflicts[:5]:  # Show first 5 conflicts
            dept_sem = conflict['dept_sem']
            time_key = conflict['time_key']
            day, slot = time_key.split('_')
            groups = set(c['group_name'] for c in conflict['conflicts'])
            print(f"  - {dept_sem}: Multiple groups scheduled on {day} at slot {slot}: {', '.join(groups)}")
        if len(group_conflicts) > 5:
            print(f"    ... and {len(group_conflicts) - 5} more conflicts")
    else:
        print("✅ GROUP CONFLICTS: No groups from same department/semester overlap")
    
    # Summary
    all_passed = (not lecture_discrepancies and not teacher_conflicts and 
                 not room_conflicts and not group_conflicts)
    
    print("\n===== SUMMARY =====")
    if all_passed:
        print("✅ ALL CONSTRAINTS SATISFIED: The theory schedule meets all requirements")
    else:
        total_issues = (len(lecture_discrepancies) + len(teacher_conflicts) + 
                        len(room_conflicts) + len(group_conflicts))
        print(f"❌ CONSTRAINTS VIOLATED: Found {total_issues} issues in the theory schedule")

def main():
    """Main entry point for the verification script."""
    parser = argparse.ArgumentParser(description='Verify theory schedule constraints')
    
    parser.add_argument('--schedule', type=str, required=True,
                        help='Path to the theory schedule file (JSON or CSV)')
    
    parser.add_argument('--course-file', type=str, default=None,
                        help='Path to the original course CSV file for hours verification')
    
    args = parser.parse_args()
    
    # Load the schedule
    try:
        schedule_data = load_schedule(args.schedule)
        print(f"Loaded theory schedule with {len(schedule_data)} sessions")
    except Exception as e:
        print(f"Error loading schedule: {e}")
        sys.exit(1)
    
    # Verify all constraints
    results = verify_all_constraints(schedule_data, args.course_file)
    
    # Display results
    display_results(results)
    
    # Return error code if any constraints are violated
    if (results['lecture_hour_discrepancies'] or results['teacher_conflicts'] or
        results['room_conflicts'] or results['group_conflicts']):
        sys.exit(1)
    
    sys.exit(0)

if __name__ == "__main__":
    main() 