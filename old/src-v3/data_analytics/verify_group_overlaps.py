#!/usr/bin/env python3
"""
Group Overlap Verification Tool

This script verifies that groups from the same semester do not have overlapping 
time slots in the theory schedule, which would violate the core constraint that
students from the same semester should be able to choose between groups.
"""

import pandas as pd
import json
import os
from datetime import datetime
from collections import defaultdict


def load_theory_schedule(schedule_file):
    """Load theory schedule from CSV or JSON file."""
    if not os.path.exists(schedule_file):
        print(f"Error: Schedule file not found: {schedule_file}")
        return None
    
    try:
        if schedule_file.endswith('.csv'):
            df = pd.read_csv(schedule_file)
            print(f"Loaded theory schedule from CSV with {len(df)} sessions")
        elif schedule_file.endswith('.json'):
            with open(schedule_file, 'r') as f:
                data = json.load(f)
            df = pd.DataFrame(data)
            print(f"Loaded theory schedule from JSON with {len(df)} sessions")
        else:
            print(f"Error: Unsupported file format. Use CSV or JSON.")
            return None
        
        return df
    except Exception as e:
        print(f"Error loading schedule file: {e}")
        return None


def analyze_group_overlaps(schedule_df):
    """Analyze group overlaps within the same semester."""
    print("\n" + "="*80)
    print("GROUP OVERLAP VERIFICATION")
    print("="*80)
    
    # Group sessions by time slot and semester
    time_slot_groups = defaultdict(lambda: defaultdict(list))
    semester_groups = defaultdict(set)
    
    for _, session in schedule_df.iterrows():
        day = session['day']
        time_slot = session['time_slot']
        group_name = session['group_name']
        semester = session['semester']
        department = session['department']
        
        # Create time slot key
        time_key = f"{day}_{time_slot}"
        
        # Track groups by semester
        semester_key = f"{department}_S{semester}"
        semester_groups[semester_key].add(group_name)
        
        # Group sessions by time slot and semester
        time_slot_groups[time_key][semester_key].append({
            'group_name': group_name,
            'course_code': session['course_code'],
            'teacher_name': session['teacher_name'],
            'session_type': session['session_type'],
            'room_number': session['room_number']
        })
    
    # Analyze overlaps
    overlap_violations = []
    total_time_slots = len(time_slot_groups)
    violation_count = 0
    
    print(f"\nAnalyzing {total_time_slots} time slots for group overlaps...")
    print(f"Semesters found: {list(semester_groups.keys())}")
    
    for time_key, semester_data in time_slot_groups.items():
        day, time_slot = time_key.split('_', 1)
        
        for semester_key, sessions in semester_data.items():
            # Check if multiple groups from same semester are in same time slot
            unique_groups = set(session['group_name'] for session in sessions)
            
            if len(unique_groups) > 1:
                violation_count += 1
                overlap_info = {
                    'time_slot': f"{day} {time_slot}",
                    'semester': semester_key,
                    'overlapping_groups': list(unique_groups),
                    'sessions': sessions
                }
                overlap_violations.append(overlap_info)
                
                print(f"\nVIOLATION:")
                print(f"   Time Slot: {day} {time_slot}")
                print(f"   Semester: {semester_key}")
                print(f"   Overlapping Groups: {', '.join(unique_groups)}")
                print(f"   Sessions:")
                for session in sessions:
                    print(f"     - {session['group_name']}: {session['course_code']} "
                          f"({session['session_type']}) - {session['teacher_name']} "
                          f"in {session['room_number']}")
    
    # Summary
    print(f"\n" + "="*80)
    print("OVERLAP VERIFICATION SUMMARY")
    print("="*80)
    print(f"Total time slots analyzed: {total_time_slots}")
    print(f"Overlap violations found: {violation_count}")
    
    if violation_count == 0:
        print("SUCCESS: NO GROUP OVERLAPS DETECTED")
        print("   - Different groups from same semester are properly separated")
        print("   - Students can choose between groups without conflicts")
    else:
        print(f"ERROR: {violation_count} OVERLAP VIOLATIONS DETECTED")
        print("   - Some groups from same semester share time slots")
        print("   - This violates student choice constraints")
    
    return overlap_violations


def verify_constraint_compliance(schedule_df):
    """Verify core scheduling constraints."""
    print(f"\n" + "="*80)
    print("CONSTRAINT COMPLIANCE VERIFICATION")
    print("="*80)
    
    violations = []
    
    # 1. Check teacher conflicts (teacher in multiple groups at same time)
    print("\n1. Checking teacher conflicts...")
    teacher_conflicts = defaultdict(lambda: defaultdict(list))
    
    for _, session in schedule_df.iterrows():
        time_key = f"{session['day']}_{session['time_slot']}"
        teacher_id = session['teacher_id']
        teacher_conflicts[time_key][teacher_id].append({
            'group_name': session['group_name'],
            'course_code': session['course_code'],
            'room_number': session['room_number']
        })
    
    teacher_violation_count = 0
    for time_key, teachers in teacher_conflicts.items():
        for teacher_id, sessions in teachers.items():
            if len(sessions) > 1:
                teacher_violation_count += 1
                day, time_slot = time_key.split('_', 1)
                print(f"   ❌ Teacher {teacher_id} has {len(sessions)} sessions at {day} {time_slot}:")
                for session in sessions:
                    print(f"      - {session['group_name']}: {session['course_code']} in {session['room_number']}")
    
    if teacher_violation_count == 0:
        print("   ✅ No teacher conflicts detected")
    else:
        violations.append(f"Teacher conflicts: {teacher_violation_count}")
    
    # 2. Check room conflicts (room used by multiple groups at same time)
    print("\n2. Checking room conflicts...")
    room_conflicts = defaultdict(lambda: defaultdict(list))
    
    for _, session in schedule_df.iterrows():
        time_key = f"{session['day']}_{session['time_slot']}"
        room_id = session['room_id']
        room_conflicts[time_key][room_id].append({
            'group_name': session['group_name'],
            'course_code': session['course_code'],
            'teacher_name': session['teacher_name']
        })
    
    room_violation_count = 0
    for time_key, rooms in room_conflicts.items():
        for room_id, sessions in rooms.items():
            if len(sessions) > 1:
                room_violation_count += 1
                day, time_slot = time_key.split('_', 1)
                print(f"   ❌ Room {room_id} has {len(sessions)} sessions at {day} {time_slot}:")
                for session in sessions:
                    print(f"      - {session['group_name']}: {session['course_code']} by {session['teacher_name']}")
    
    if room_violation_count == 0:
        print("   ✅ No room conflicts detected")
    else:
        violations.append(f"Room conflicts: {room_violation_count}")
    
    # 3. Check group session distribution
    print("\n3. Checking group session distribution...")
    group_sessions = defaultdict(list)
    
    for _, session in schedule_df.iterrows():
        group_name = session['group_name']
        group_sessions[group_name].append({
            'time_slot': f"{session['day']} {session['time_slot']}",
            'course_code': session['course_code'],
            'session_type': session['session_type']
        })
    
    for group_name, sessions in group_sessions.items():
        time_slots = [s['time_slot'] for s in sessions]
        unique_time_slots = set(time_slots)
        
        if len(time_slots) != len(unique_time_slots):
            print(f"   ❌ Group {group_name} has duplicate time slots")
            violations.append(f"Group {group_name} duplicate time slots")
        else:
            print(f"   ✅ Group {group_name}: {len(sessions)} sessions in {len(unique_time_slots)} unique time slots")
    
    print(f"\n" + "="*60)
    print("CONSTRAINT COMPLIANCE SUMMARY")
    print("="*60)
    
    if not violations:
        print("✅ ALL CONSTRAINTS SATISFIED")
        print("   - No teacher conflicts")
        print("   - No room conflicts") 
        print("   - No group time slot duplicates")
        print("   - Proper group separation by semester")
    else:
        print(f"❌ {len(violations)} CONSTRAINT VIOLATIONS:")
        for violation in violations:
            print(f"   - {violation}")
    
    return violations


def generate_overlap_report(schedule_df, overlap_violations, output_dir="output/verification_reports"):
    """Generate a detailed overlap verification report."""
    os.makedirs(output_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_file = os.path.join(output_dir, f"group_overlap_verification_{timestamp}.html")
    
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write("""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Group Overlap Verification Report</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 20px; }
                h1, h2 { color: #333; }
                .summary { background-color: #f5f5f5; padding: 15px; border-radius: 5px; margin-bottom: 20px; }
                .violation { background-color: #ffebee; padding: 10px; border-left: 4px solid #f44336; margin: 10px 0; }
                .success { background-color: #e8f5e8; padding: 10px; border-left: 4px solid #4caf50; margin: 10px 0; }
                table { border-collapse: collapse; width: 100%; margin-top: 20px; }
                th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
                th { background-color: #f2f2f2; }
                tr:nth-child(even) { background-color: #f9f9f9; }
            </style>
        </head>
        <body>
        """)
        
        f.write(f"<h1>Group Overlap Verification Report</h1>")
        f.write(f"<p>Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>")
        
        # Summary
        f.write("<div class='summary'>")
        f.write("<h2>Summary</h2>")
        f.write(f"<p>Total sessions analyzed: {len(schedule_df)}</p>")
        f.write(f"<p>Overlap violations found: {len(overlap_violations)}</p>")
        
        if not overlap_violations:
            f.write("<div class='success'>✅ No group overlaps detected - All constraints satisfied!</div>")
        else:
            f.write(f"<div class='violation'>❌ {len(overlap_violations)} overlap violations detected</div>")
        
        f.write("</div>")
        
        # Violations detail
        if overlap_violations:
            f.write("<h2>Overlap Violations</h2>")
            for i, violation in enumerate(overlap_violations, 1):
                f.write(f"<div class='violation'>")
                f.write(f"<h3>Violation {i}</h3>")
                f.write(f"<p><strong>Time Slot:</strong> {violation['time_slot']}</p>")
                f.write(f"<p><strong>Semester:</strong> {violation['semester']}</p>")
                f.write(f"<p><strong>Overlapping Groups:</strong> {', '.join(violation['overlapping_groups'])}</p>")
                f.write(f"<h4>Sessions:</h4>")
                f.write("<ul>")
                for session in violation['sessions']:
                    f.write(f"<li>{session['group_name']}: {session['course_code']} "
                           f"({session['session_type']}) - {session['teacher_name']} "
                           f"in {session['room_number']}</li>")
                f.write("</ul>")
                f.write("</div>")
        
        # Group distribution table
        f.write("<h2>Group Distribution by Semester</h2>")
        f.write("<table>")
        f.write("<tr><th>Semester</th><th>Group</th><th>Sessions</th><th>Time Slots</th></tr>")
        
        # Organize by semester and group
        semester_data = defaultdict(lambda: defaultdict(list))
        for _, session in schedule_df.iterrows():
            semester_key = f"{session['department']}_S{session['semester']}"
            group_name = session['group_name']
            semester_data[semester_key][group_name].append(session)
        
        for semester_key in sorted(semester_data.keys()):
            groups = semester_data[semester_key]
            for group_name in sorted(groups.keys()):
                sessions = groups[group_name]
                time_slots = set(f"{s['day']} {s['time_slot']}" for s in sessions)
                f.write(f"<tr>")
                f.write(f"<td>{semester_key}</td>")
                f.write(f"<td>{group_name}</td>")
                f.write(f"<td>{len(sessions)}</td>")
                f.write(f"<td>{len(time_slots)}</td>")
                f.write(f"</tr>")
        
        f.write("</table>")
        f.write("</body></html>")
    
    print(f"\nOverlap verification report generated: {report_file}")
    return report_file


def verify_group_overlaps(schedule_file):
    """Main function to verify group overlaps."""
    # Load schedule
    schedule_df = load_theory_schedule(schedule_file)
    if schedule_df is None:
        return False
    
    # Verify required columns exist
    required_columns = ['day', 'time_slot', 'group_name', 'semester', 'department', 
                       'course_code', 'teacher_name', 'session_type', 'room_number',
                       'teacher_id', 'room_id']
    
    missing_columns = [col for col in required_columns if col not in schedule_df.columns]
    if missing_columns:
        print(f"Error: Missing required columns: {missing_columns}")
        return False
    
    # Analyze overlaps
    overlap_violations = analyze_group_overlaps(schedule_df)
    
    # Verify other constraints
    constraint_violations = verify_constraint_compliance(schedule_df)
    
    # Generate report
    generate_overlap_report(schedule_df, overlap_violations)
    
    # Return success status
    return len(overlap_violations) == 0 and len(constraint_violations) == 0


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Verify group overlaps in theory scheduling.')
    parser.add_argument('--schedule-file', type=str, help='Path to theory schedule CSV or JSON file')
    
    args = parser.parse_args()
    
    if not args.schedule_file:
        # Try to find the latest theory schedule file
        output_dirs = [d for d in os.listdir('output') if d.startswith('theory_schedule_')]
        if output_dirs:
            latest_dir = max(output_dirs)
            schedule_file = os.path.join('output', latest_dir, 'theory_schedule.csv')
            print(f"Using latest theory schedule: {schedule_file}")
        else:
            print("Error: No schedule file specified and no theory schedule found in output directory")
            exit(1)
    else:
        schedule_file = args.schedule_file
    
    success = verify_group_overlaps(schedule_file)
    exit(0 if success else 1) 