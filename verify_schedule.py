import csv
import json
import argparse
from datetime import datetime
import os
import sys

def parse_time_range(time_range_str):
    """
    Parses a time range string like "3:00 - 3:50" or "8:00 - 9:40".
    Returns start_minutes, end_minutes (from midnight).
    Assumes 24-hour format logic if possible, or 12-hour.
    Given the data samples: "3:00 - 3:50", "8:00 - 8:50", "1:20 - 3:00"
    It seems mixed or 12-hour. 
    "3:00" is likely 15:00 if it's afternoon. 
    However, standard timetable usually runs 8am to 5pm.
    Let's handle specific mappings or basic parsing.
    
    If start < 8, add 12? No, 1:20 is 13:20.
    Standard college hours: 8:00 to 17:00 (5pm).
    So:
    1, 2, 3, 4, 5 -> PM (add 12)
    8, 9, 10, 11, 12 -> AM/PM (No change, 12 is 12)
    """
    try:
        start_str, end_str = [x.strip() for x in time_range_str.split('-')]
        
        def to_minutes(t_str):
            parts = t_str.split(':')
            h = int(parts[0])
            m = int(parts[1])
            # Heuristic for PM
            if 1 <= h <= 5: 
                h += 12
            return h * 60 + m

        return to_minutes(start_str), to_minutes(end_str)
    except Exception as e:
        print(f"Error parsing time: {time_range_str} - {e}")
        return 0, 0

def load_sessions_csv(file_path):
    sessions = []
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return sessions
        
    with open(file_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Skip empty rows
            if not row.get('day'): continue
            
            s, e = parse_time_range(row.get('time_slot') or row.get('time_range', ''))
            
            sessions.append({
                'day': row.get('day', '').lower(),
                'start_time': s,
                'end_time': e,
                'teacher_id': row.get('teacher_id'),
                'teacher_name': row.get('teacher_name', ''),
                'staff_code': row.get('staff_code', ''),
                'room_id': row.get('room_id'),
                'room_number': row.get('room_number', ''),
                'course_code': row.get('course_code', ''),
                'session_type': row.get('session_type', 'Theory'), # Default theory if missing
                'source': os.path.basename(file_path)
            })
    return sessions

def load_sessions_json(file_path):
    sessions = []
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return sessions

    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        # Assuming data is a list of session objects
        for row in data:
            s, e = parse_time_range(row.get('time_range', ''))
            
            sessions.append({
                'day': row.get('day', '').lower(),
                'start_time': s,
                'end_time': e,
                'teacher_id': row.get('teacher_id'),
                'teacher_name': row.get('teacher_name', ''),
                'staff_code': row.get('staff_code', ''),
                'room_id': row.get('room_id'),
                'room_number': row.get('room_number', ''),
                'course_code': row.get('course_code', ''),
                'session_type': 'Lab', 
                'source': os.path.basename(file_path)
            })
    return sessions

def check_cross_clashes(sessions1, sessions2, name1="Dataset 1", name2="Dataset 2"):
    """
    Checks for clashes strictly between two datasets.
    Matches using persistent identifiers: 'room_number' and 'staff_code' (or 'teacher_name' if code missing).
    """
    # Index sessions2 for faster lookup
    # Day -> TeacherIdentifier -> List of sessions
    s2_by_teacher = {}
    # Day -> RoomIdentifier -> List of sessions
    s2_by_room = {}

    for s in sessions2:
        d = s['day']
        
        # Identifier for Teacher: Staff Code prefered, else Name
        t_id = s.get('staff_code', '').strip() or s.get('teacher_name', '').strip()
        
        # Identifier for Room: Room Number
        r_id = s.get('room_number', '').strip()

        # Index by Teacher
        if t_id:
            key = (d, t_id)
            if key not in s2_by_teacher: s2_by_teacher[key] = []
            s2_by_teacher[key].append(s)
        
        # Index by Room
        if r_id:
            key = (d, r_id)
            if key not in s2_by_room: s2_by_room[key] = []
            s2_by_room[key].append(s)
            
    issues = []
    
    # Iterate through sessions1 and check against indexed sessions2
    for s1 in sessions1:
        d = s1['day']
        
        # 1. Check Teacher Clashes
        t_id = s1.get('staff_code', '').strip() or s1.get('teacher_name', '').strip()
        if t_id:
            if (d, t_id) in s2_by_teacher:
                potential_clashes = s2_by_teacher[(d, t_id)]
                for s2 in potential_clashes:
                    if max(s1['start_time'], s2['start_time']) < min(s1['end_time'], s2['end_time']):
                        issues.append(f"CROSS CLASH [Teacher]: {s1.get('teacher_name')} ({t_id}) on {d.title()}\n  {name1}: {s1['course_code']} ({min_to_time(s1['start_time'])}-{min_to_time(s1['end_time'])})\n  {name2}: {s2['course_code']} ({min_to_time(s2['start_time'])}-{min_to_time(s2['end_time'])})")

        # 2. Check Room Clashes
        r_id = s1.get('room_number', '').strip()
        if r_id:
            if (d, r_id) in s2_by_room:
                potential_clashes = s2_by_room[(d, r_id)]
                for s2 in potential_clashes:
                    if max(s1['start_time'], s2['start_time']) < min(s1['end_time'], s2['end_time']):
                        issues.append(f"CROSS CLASH [Room]: {r_id} on {d.title()}\n  {name1}: {s1['course_code']} ({min_to_time(s1['start_time'])}-{min_to_time(s1['end_time'])})\n  {name2}: {s2['course_code']} ({min_to_time(s2['start_time'])}-{min_to_time(s2['end_time'])})")

    return issues

def min_to_time(minutes):
    """Helper to convert minutes back to HH:MM for readable output"""
    h = minutes // 60
    m = minutes % 60
    # Cosmetic fix for 24h to 12h if desired, but 24h is fine
    return f"{h:02d}:{m:02d}"

def main():
    # 1st Year Paths
    yr1_base = r"d:\timetable-scheduler\output\1st_year\2026-01-20_21-26-48"
    yr1_theory = os.path.join(yr1_base, "csv", "theory_schedule.csv")
    yr1_lab = os.path.join(yr1_base, "csv", "lab_schedule.csv")
    
    # Final Paths
    final_base = r"d:\timetable-scheduler\output\final\2025-12-26_04-47-12"
    final_theory = os.path.join(final_base, "csv", "theory_schedule.csv")
    final_lab = os.path.join(final_base, "lab_schedule.json")
    
    print("Loading 1st Year Data...")
    yr1_sessions = load_sessions_csv(yr1_theory) + load_sessions_csv(yr1_lab)
    print(f"Loaded {len(yr1_sessions)} sessions for 1st Year.")
    
    print("Loading Final Data...")
    final_sessions = load_sessions_csv(final_theory) + load_sessions_json(final_lab)
    print(f"Loaded {len(final_sessions)} sessions for Final.")
    
    print("\nChecking Clashes BETWEEN 1st Year and Final...")
    cross_issues = check_cross_clashes(yr1_sessions, final_sessions, "1st Year", "Final")
    
    if cross_issues:
        print(f"\nFound {len(cross_issues)} cross-schedule clashes!")
        with open("verification_issues.txt", "w") as f:
            for issue in cross_issues:
                f.write(issue + "\n")
                print(issue)
        print("\nIssues saved to verification_issues.txt")
    else:
        print("\nNo cross-schedule clashes found! The schedules are compatible.")

if __name__ == "__main__":
    main()
