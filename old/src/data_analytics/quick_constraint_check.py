#!/usr/bin/env python3
"""
Quick Group Constraint Verification Script

Verifies the 4 main group-based scheduling constraints:
1. Same group courses CAN overlap ✅
2. Different groups in same semester CANNOT overlap ❌  
3. Different semesters CAN overlap ✅
4. Teachers cannot teach simultaneously ❌
"""

import json
import pandas as pd
import os
import sys
from collections import defaultdict

def load_schedule(file_path):
    """Load lab schedule from JSON or CSV."""
    if file_path.endswith('.json'):
        with open(file_path, 'r') as f:
            return json.load(f)
    elif file_path.endswith('.csv'):
        df = pd.read_csv(file_path)
        return df.to_dict('records')
    else:
        raise ValueError("Use .json or .csv file")

def check_constraints(schedule):
    """Check all group-based constraints."""
    print("\n🔍 GROUP CONSTRAINT VERIFICATION")
    print("=" * 50)
    
    # Group schedule by time slots
    time_slots = defaultdict(list)
    for entry in schedule:
        slot_key = f"{entry['day']}_{entry['session_name']}"
        time_slots[slot_key].append(entry)
    
    print(f"📊 Schedule: {len(schedule)} sessions across {len(time_slots)} time slots")
    
    violations = []
    
    # Check each time slot
    for slot, entries in time_slots.items():
        if len(entries) <= 1:
            continue
            
        print(f"\n⏰ Checking {slot} ({len(entries)} sessions):")
        
        # Group by semester and group
        semester_groups = defaultdict(lambda: defaultdict(list))
        teachers = defaultdict(list)
        
        for entry in entries:
            # Extract info
            semester = entry['semester']
            group = entry['group_index']
            teacher = entry['teacher_id']
            course = entry['course_code']
            
            semester_groups[semester][group].append(entry)
            teachers[teacher].append(entry)
            
            print(f"  - {course} (S{semester}G{group}, T{teacher})")
        
        # CONSTRAINT 2: Different groups in same semester CANNOT overlap
        for semester, groups in semester_groups.items():
            if len(groups) > 1:
                group_ids = list(groups.keys())
                print(f"  ❌ VIOLATION: Semester {semester} has multiple groups: {group_ids}")
                violations.append({
                    'type': 'same_semester_different_groups',
                    'slot': slot,
                    'semester': semester,
                    'groups': group_ids,
                    'details': {g: [e['course_code'] for e in entries] for g, entries in groups.items()}
                })
        
        # CONSTRAINT 4: Teachers cannot teach simultaneously  
        for teacher, assignments in teachers.items():
            if len(assignments) > 1:
                courses = [a['course_code'] for a in assignments]
                print(f"  ❌ VIOLATION: Teacher {teacher} teaching multiple courses: {courses}")
                violations.append({
                    'type': 'teacher_conflict',
                    'slot': slot,
                    'teacher': teacher,
                    'courses': courses
                })
    
    # Summary
    print(f"\n📋 CONSTRAINT VERIFICATION SUMMARY")
    print("=" * 50)
    
    constraint_2_violations = len([v for v in violations if v['type'] == 'same_semester_different_groups'])
    constraint_4_violations = len([v for v in violations if v['type'] == 'teacher_conflict'])
    
    print(f"1. Same group overlap: ✅ ALLOWED (not checked)")
    print(f"2. Different groups same semester: {'❌ ' + str(constraint_2_violations) + ' VIOLATIONS' if constraint_2_violations > 0 else '✅ PASSED'}")
    print(f"3. Different semester overlap: ✅ ALLOWED (not checked)")  
    print(f"4. Teacher conflicts: {'❌ ' + str(constraint_4_violations) + ' VIOLATIONS' if constraint_4_violations > 0 else '✅ PASSED'}")
    
    if len(violations) == 0:
        print(f"\n🎉 ALL CRITICAL CONSTRAINTS SATISFIED!")
        print(f"✅ Group-based scheduling is working correctly!")
    else:
        print(f"\n⚠️ FOUND {len(violations)} CONSTRAINT VIOLATIONS!")
        print(f"❌ Group-based scheduling needs fixes!")
        
        # Show detailed violations
        print(f"\nDETAILED VIOLATIONS:")
        for i, violation in enumerate(violations, 1):
            print(f"\n{i}. {violation['type'].upper()}:")
            print(f"   Time Slot: {violation['slot']}")
            if violation['type'] == 'same_semester_different_groups':
                print(f"   Semester: {violation['semester']}")
                print(f"   Conflicting Groups: {violation['groups']}")
                for group, courses in violation['details'].items():
                    print(f"     Group {group}: {', '.join(courses)}")
            elif violation['type'] == 'teacher_conflict':
                print(f"   Teacher: {violation['teacher']}")
                print(f"   Conflicting Courses: {', '.join(violation['courses'])}")
    
    return len(violations) == 0

def find_latest_schedule():
    """Find the most recent lab schedule file."""
    output_dirs = [d for d in os.listdir('.') if d.startswith('output')]
    if not output_dirs:
        output_dirs = ['output']
    
    for output_dir in output_dirs:
        if os.path.exists(output_dir):
            schedule_dirs = [d for d in os.listdir(output_dir) if d.startswith('lab_schedule_')]
            if schedule_dirs:
                latest_dir = max(schedule_dirs)
                
                # Try JSON first, then CSV
                json_file = os.path.join(output_dir, latest_dir, 'lab_schedule.json')
                csv_file = os.path.join(output_dir, latest_dir, 'lab_schedule.csv')
                
                if os.path.exists(json_file):
                    return json_file
                elif os.path.exists(csv_file):
                    return csv_file
    
    return None

def main():
    """Main verification function."""
    print("Quick Group Constraint Checker")
    print("=" * 30)
    
    # Get file path
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
    else:
        file_path = find_latest_schedule()
        if not file_path:
            print("❌ No lab schedule found!")
            print("Usage: python quick_constraint_check.py [schedule_file]")
            return
    
    print(f"📁 Checking: {file_path}")
    
    try:
        # Load and verify
        schedule = load_schedule(file_path)
        success = check_constraints(schedule)
        
        # Exit code for automation
        sys.exit(0 if success else 1)
        
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main() 