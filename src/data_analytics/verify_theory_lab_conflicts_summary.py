#!/usr/bin/env python3
"""
Summary verification script to check theory-lab conflicts with condensed reporting.
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
        return None, None

def time_ranges_overlap(start1, end1, start2, end2):
    """Check if two time ranges overlap (excluding adjacent endpoints)."""
    if start1 is None or end1 is None or start2 is None or end2 is None:
        return False
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
    
    theory_start, theory_end = parse_time_range(theory_timeslot)
    if theory_start is None or theory_end is None:
        return False
    
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
        return data
    except Exception as e:
        print(f"❌ Error loading {file_path}: {e}")
        return None

def find_schedule_files():
    """Find the most recent theory and lab schedule files."""
    output_dir = 'output'
    if not os.path.exists(output_dir):
        return None, None
    
    theory_files = []
    lab_files = []
    
    for item in os.listdir(output_dir):
        item_path = os.path.join(output_dir, item)
        if os.path.isdir(item_path):
            theory_json = os.path.join(item_path, 'theory_schedule.json')
            if os.path.exists(theory_json):
                theory_files.append((item, theory_json))
            
            lab_json = os.path.join(item_path, 'lab_schedule.json')
            if os.path.exists(lab_json):
                lab_files.append((item, lab_json))
    
    theory_files.sort(reverse=True)
    lab_files.sort(reverse=True)
    
    theory_file = theory_files[0][1] if theory_files else None
    lab_file = lab_files[0][1] if lab_files else None
    
    return theory_file, lab_file

def verify_theory_lab_conflicts_summary():
    """
    Summary verification that NO theory group overlaps with ANY lab group 
    of the same semester and department (for maximum student choice).
    """
    print("🔍 STUDENT CHOICE VERIFICATION SUMMARY")
    print("=" * 50)
    print("Checking: Theory groups vs ALL lab groups (same dept/semester)")
    print()
    
    # Find schedule files
    theory_file, lab_file = find_schedule_files()
    
    if not theory_file or not lab_file:
        print("❌ Schedule files not found")
        return False
    
    # Load schedule data
    theory_schedule = load_schedule_data(theory_file)
    lab_schedule = load_schedule_data(lab_file)
    
    if not theory_schedule or not lab_schedule:
        print("❌ Failed to load schedule data")
        return False
    
    # Group by department and semester
    theory_by_dept_sem = defaultdict(lambda: defaultdict(list))
    lab_by_dept_sem = defaultdict(lambda: defaultdict(list))
    
    for session in theory_schedule:
        dept = session.get('department', 'Unknown')
        semester = session.get('semester', 0)
        if semester > 0 and dept != 'Unknown':
            theory_by_dept_sem[dept][semester].append(session)
    
    for session in lab_schedule:
        dept = session.get('department', 'Unknown')
        semester = session.get('semester', 0)
        if semester > 0 and dept != 'Unknown':
            lab_by_dept_sem[dept][semester].append(session)
    
    total_conflicts = 0
    dept_sem_with_conflicts = 0
    total_dept_sem = 0
    
    # Check each department-semester combination
    for dept in theory_by_dept_sem.keys():
        if dept in lab_by_dept_sem:
            for semester in theory_by_dept_sem[dept].keys():
                if semester in lab_by_dept_sem[dept]:
                    total_dept_sem += 1
                    
                    theory_sessions = theory_by_dept_sem[dept][semester]
                    lab_sessions = lab_by_dept_sem[dept][semester]
                    
                    # Get theory and lab groups
                    theory_groups = set(s.get('group_index', 0) for s in theory_sessions if s.get('group_index', 0) > 0)
                    lab_groups = set(s.get('group_index', 0) for s in lab_sessions if s.get('group_index', 0) > 0)
                    
                    # Check ALL theory groups against ALL lab groups
                    dept_sem_conflicts = 0
                    conflicting_pairs = set()
                    
                    for theory_group in theory_groups:
                        theory_group_sessions = [s for s in theory_sessions if s.get('group_index') == theory_group]
                        
                        for lab_group in lab_groups:
                            lab_group_sessions = [s for s in lab_sessions if s.get('group_index') == lab_group]
                            
                            # Check for conflicts
                            for theory_session in theory_group_sessions:
                                theory_day = theory_session.get('day')
                                theory_timeslot = theory_session.get('time_slot', '')
                                
                                for lab_session in lab_group_sessions:
                                    lab_day = lab_session.get('day')
                                    lab_session_name = lab_session.get('session_name', '')
                                    
                                    if theory_day == lab_day:
                                        if theory_timeslot_conflicts_with_lab_session(theory_timeslot, lab_session_name):
                                            dept_sem_conflicts += 1
                                            conflicting_pairs.add((theory_group, lab_group))
                    
                    if dept_sem_conflicts > 0:
                        dept_sem_with_conflicts += 1
                        total_conflicts += dept_sem_conflicts
                        print(f"❌ {dept} Semester {semester}:")
                        print(f"   Theory groups: {sorted(theory_groups)}")
                        print(f"   Lab groups: {sorted(lab_groups)}")
                        print(f"   Conflicting pairs: {sorted(conflicting_pairs)}")
                        print(f"   Conflicts: {dept_sem_conflicts}")
                        print()
                    else:
                        print(f"✅ {dept} Semester {semester}: No conflicts - full choice flexibility")
    
    # Summary
    print("=" * 50)
    print("CHOICE VERIFICATION SUMMARY")
    print("=" * 50)
    print(f"Department-Semester combinations checked: {total_dept_sem}")
    print(f"Combinations with conflicts: {dept_sem_with_conflicts}")
    print(f"Total conflicts found: {total_conflicts}")
    print()
    
    if total_conflicts > 0:
        choice_percentage = ((total_dept_sem - dept_sem_with_conflicts) / total_dept_sem * 100) if total_dept_sem > 0 else 0
        print(f"🎯 STUDENT CHOICE ANALYSIS:")
        print(f"   Choice flexibility: {choice_percentage:.1f}% of dept-sem combinations")
        print(f"   Restricted combinations: {dept_sem_with_conflicts}")
        print()
        print(f"❌ STUDENT CHOICE RESTRICTED")
        print(f"Students cannot freely choose theory and lab groups in some combinations")
        return False
    else:
        print(f"✅ MAXIMUM STUDENT CHOICE ACHIEVED")
        print(f"Students can freely choose any theory group + any lab group")
        return True

if __name__ == "__main__":
    success = verify_theory_lab_conflicts_summary()
    sys.exit(0 if success else 1) 