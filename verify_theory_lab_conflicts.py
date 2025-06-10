#!/usr/bin/env python3
"""
Verification script to check that no theory group overlaps with lab groups 
from the same semester and department.
"""

import json
import os
import sys
from collections import defaultdict

def parse_time_range(time_str):
    """Parse time range string to start and end times in minutes from midnight."""
    try:
        start_str, end_str = time_str.split(' - ')
        
        def time_to_minutes(time_part):
            hour, minute = map(int, time_part.split(':'))
            return hour * 60 + minute
        
        start_minutes = time_to_minutes(start_str)
        end_minutes = time_to_minutes(end_str)
        
        return start_minutes, end_minutes
    except Exception as e:
        print(f"Could not parse time range '{time_str}': {e}")
        return None, None

def time_ranges_overlap(start1, end1, start2, end2):
    """Check if two time ranges overlap (excluding adjacent endpoints)."""
    if start1 is None or end1 is None or start2 is None or end2 is None:
        return False
    
    # Two ranges overlap if: start1 < end2 AND start2 < end1
    # This excludes cases where one ends exactly when the other starts
    return start1 < end2 and start2 < end1

def get_lab_session_time_ranges():
    """Get the time ranges for each lab session."""
    return {
        'L1': ['8:00 - 8:50', '8:50 - 9:40'],      # 8:00 - 9:40
        'L2': ['9:50 - 10:40', '10:40 - 11:30'],   # 9:50 - 11:30  
        'L3': ['11:50 - 12:40', '12:40 - 1:30'],   # 11:50 - 1:30
        'L4': ['1:50 - 2:40', '2:40 - 3:30'],      # 1:50 - 3:30
        'L5': ['3:50 - 4:40', '4:40 - 5:30'],      # 3:50 - 5:30
        'L6': ['5:30 - 6:20', '6:20 - 7:10']       # 5:30 - 7:10
    }

def theory_timeslot_conflicts_with_lab_session(theory_timeslot, lab_session_name):
    """Check if a theory timeslot conflicts with a lab session."""
    lab_sessions = get_lab_session_time_ranges()
    
    if lab_session_name not in lab_sessions:
        return False
    
    # Parse theory timeslot
    theory_start, theory_end = parse_time_range(theory_timeslot)
    if theory_start is None or theory_end is None:
        return False
    
    # Check if theory timeslot overlaps with any slot in the lab session
    for lab_timeslot in lab_sessions[lab_session_name]:
        lab_start, lab_end = parse_time_range(lab_timeslot)
        if lab_start is None or lab_end is None:
            continue
        
        if time_ranges_overlap(theory_start, theory_end, lab_start, lab_end):
            return True
    
    return False

def load_schedule_data(file_path):
    """Load schedule data from JSON file."""
    if not os.path.exists(file_path):
        print(f"❌ Schedule file not found: {file_path}")
        return None
    
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)
        print(f"✅ Loaded {len(data)} sessions from {file_path}")
        return data
    except Exception as e:
        print(f"❌ Error loading {file_path}: {e}")
        return None

def find_schedule_files():
    """Find the most recent theory and lab schedule files."""
    output_dir = 'output'
    if not os.path.exists(output_dir):
        print(f"❌ Output directory not found: {output_dir}")
        return None, None
    
    # Find theory schedule files
    theory_files = []
    lab_files = []
    
    for item in os.listdir(output_dir):
        item_path = os.path.join(output_dir, item)
        if os.path.isdir(item_path):
            # Check for theory schedule
            theory_json = os.path.join(item_path, 'theory_schedule.json')
            if os.path.exists(theory_json):
                theory_files.append((item, theory_json))
            
            # Check for lab schedule
            lab_json = os.path.join(item_path, 'lab_schedule.json')
            if os.path.exists(lab_json):
                lab_files.append((item, lab_json))
    
    # Sort by directory name (timestamp) to get most recent
    theory_files.sort(reverse=True)
    lab_files.sort(reverse=True)
    
    theory_file = theory_files[0][1] if theory_files else None
    lab_file = lab_files[0][1] if lab_files else None
    
    if theory_file:
        print(f"📋 Found theory schedule: {theory_file}")
    if lab_file:
        print(f"🧪 Found lab schedule: {lab_file}")
    
    return theory_file, lab_file

def verify_theory_lab_conflicts(theory_file=None, lab_file=None):
    """
    Verify that NO theory group overlaps with ANY lab group of the same semester and department.
    This ensures maximum student choice - students can pick any theory group and any lab group.
    """
    print("🔍 VERIFYING THEORY-LAB CONFLICTS FOR MAXIMUM STUDENT CHOICE")
    print("=" * 70)
    print("CONSTRAINT: No theory group should overlap with ANY lab group of same semester/department")
    print("BENEFIT: Students can freely choose any theory group + any lab group")
    print("=" * 70)
    
    # Find schedule files
    theory_file_path, lab_file_path = find_schedule_files()
    
    if theory_file:
        theory_file_path = theory_file
    if lab_file:
        lab_file_path = lab_file
    
    print(f"Theory schedule: {theory_file_path}")
    print(f"Lab schedule: {lab_file_path}")
    print()
    
    # Load schedule data
    theory_schedule = load_schedule_data(theory_file_path)
    lab_schedule = load_schedule_data(lab_file_path)
    
    if not theory_schedule or not lab_schedule:
        print("❌ Failed to load schedule data")
        return False
    
    print(f"Loaded {len(theory_schedule)} theory sessions and {len(lab_schedule)} lab sessions")
    print()
    
    # Group theory sessions by department and semester
    theory_by_dept_sem = defaultdict(lambda: defaultdict(list))
    for session in theory_schedule:
        dept = session.get('department', 'Unknown')
        semester = session.get('semester', 0)
        theory_by_dept_sem[dept][semester].append(session)
    
    # Group lab sessions by department and semester  
    lab_by_dept_sem = defaultdict(lambda: defaultdict(list))
    for session in lab_schedule:
        dept = session.get('department', 'Unknown')
        semester = session.get('semester', 0)
        lab_by_dept_sem[dept][semester].append(session)
    
    conflicts_found = []
    total_dept_sem_combinations = 0
    
    # Check each department-semester combination
    for dept in set(list(theory_by_dept_sem.keys()) + list(lab_by_dept_sem.keys())):
        for semester in set(list(theory_by_dept_sem[dept].keys()) + list(lab_by_dept_sem[dept].keys())):
            if semester == 0 or dept == 'Unknown':
                continue
                
            theory_sessions = theory_by_dept_sem[dept][semester]
            lab_sessions = lab_by_dept_sem[dept][semester]
            
            if not theory_sessions or not lab_sessions:
                continue
                
            total_dept_sem_combinations += 1
            print(f"📋 Checking {dept} Semester {semester}:")
            print(f"   Theory sessions: {len(theory_sessions)}")
            print(f"   Lab sessions: {len(lab_sessions)}")
            
            # Get unique theory groups for this dept-sem
            theory_groups = set()
            for session in theory_sessions:
                group_index = session.get('group_index', 0)
                if group_index > 0:
                    theory_groups.add(group_index)
            
            # Get unique lab groups for this dept-sem
            lab_groups = set()
            for session in lab_sessions:
                group_index = session.get('group_index', 0)
                if group_index > 0:
                    lab_groups.add(group_index)
            
            print(f"   Theory groups: {sorted(theory_groups)}")
            print(f"   Lab groups: {sorted(lab_groups)}")
            
            # Check EVERY theory group against EVERY lab group
            dept_sem_conflicts = 0
            for theory_group in theory_groups:
                theory_group_sessions = [s for s in theory_sessions if s.get('group_index') == theory_group]
                
                for lab_group in lab_groups:
                    lab_group_sessions = [s for s in lab_sessions if s.get('group_index') == lab_group]
                    
                    # Check for conflicts between this theory group and this lab group
                    for theory_session in theory_group_sessions:
                        theory_day = theory_session.get('day')
                        theory_timeslot = theory_session.get('time_slot', '')
                        
                        for lab_session in lab_group_sessions:
                            lab_day = lab_session.get('day')
                            lab_session_name = lab_session.get('session_name', '')
                            
                            # Only check sessions on the same day
                            if theory_day == lab_day:
                                # Check if theory timeslot conflicts with lab session
                                if theory_timeslot_conflicts_with_lab_session(theory_timeslot, lab_session_name):
                                    conflicts_found.append({
                                        'department': dept,
                                        'semester': semester,
                                        'theory_group': theory_group,
                                        'lab_group': lab_group,
                                        'day': theory_day,
                                        'theory_session': {
                                            'course': f"{theory_session.get('course_code', 'Unknown')} ({theory_session.get('session_type', 'Unknown')})",
                                            'timeslot': theory_timeslot,
                                            'teacher': theory_session.get('teacher_name', 'Unknown')
                                        },
                                        'lab_session': {
                                            'course': lab_session.get('course_code', 'Unknown'),
                                            'session': f"{lab_session_name} ({lab_session.get('time_interval', 'Unknown')})",
                                            'teacher': lab_session.get('teacher_name', 'Unknown')
                                        }
                                    })
                                    dept_sem_conflicts += 1
            
            if dept_sem_conflicts > 0:
                print(f"   ❌ Found {dept_sem_conflicts} conflicts")
            else:
                print(f"   ✅ No conflicts - students have full choice flexibility")
            print()
    
    # Report results
    print("=" * 70)
    print("VERIFICATION RESULTS")
    print("=" * 70)
    print(f"Checked {total_dept_sem_combinations} department-semester combinations")
    print(f"Total conflicts found: {len(conflicts_found)}")
    print()
    
    if conflicts_found:
        print(f"❌ CHOICE CONSTRAINT VIOLATION")
        print(f"The following theory-lab conflicts restrict student choice:")
        print()
        
        # Group conflicts by department-semester for better reporting
        conflicts_by_dept_sem = defaultdict(list)
        for conflict in conflicts_found:
            key = f"{conflict['department']}_S{conflict['semester']}"
            conflicts_by_dept_sem[key].append(conflict)
        
        for dept_sem, dept_conflicts in conflicts_by_dept_sem.items():
            print(f"📍 {dept_sem.replace('_', ' ')}:")
            
            # Show unique theory-lab group pairs that conflict
            conflicting_pairs = set()
            for conflict in dept_conflicts:
                pair = (conflict['theory_group'], conflict['lab_group'])
                conflicting_pairs.add(pair)
            
            print(f"   Conflicting group pairs: {sorted(conflicting_pairs)}")
            print(f"   Impact: Students in theory groups {sorted(set(c['theory_group'] for c in dept_conflicts))} cannot choose lab groups {sorted(set(c['lab_group'] for c in dept_conflicts))}")
            
            # Show sample conflicts
            sample_conflicts = dept_conflicts[:3]  # Show first 3 conflicts as examples
            for i, conflict in enumerate(sample_conflicts, 1):
                print(f"   Example {i}: Theory G{conflict['theory_group']} vs Lab G{conflict['lab_group']} on {conflict['day']}")
                print(f"     Theory: {conflict['theory_session']['course']} ({conflict['theory_session']['timeslot']})")
                print(f"     Lab: {conflict['lab_session']['course']} ({conflict['lab_session']['session']})")
            
            if len(dept_conflicts) > 3:
                print(f"   ... and {len(dept_conflicts) - 3} more conflicts")
            print()
        
        print(f"🚨 STUDENT CHOICE RESTRICTED")
        print(f"Students cannot freely choose theory and lab groups due to scheduling conflicts")
        return False
    else:
        print(f"✅ MAXIMUM STUDENT CHOICE ACHIEVED")
        print(f"No conflicts found - students can freely choose any theory group and any lab group")
        print(f"All department-semester combinations allow full flexibility")
        return True

def main():
    """Main function."""
    # Allow command line arguments for specific files
    theory_file = sys.argv[1] if len(sys.argv) > 1 else None
    lab_file = sys.argv[2] if len(sys.argv) > 2 else None
    
    success = verify_theory_lab_conflicts(theory_file, lab_file)
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main() 