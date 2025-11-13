#!/usr/bin/env python3
"""
Double Booking Checker for Combined Schedules

This script checks for room conflicts and double bookings in both
combined_lab_schedule.csv and combined_theory_schedule.csv files.
"""

import os
import pandas as pd
import numpy as np
from collections import defaultdict
from datetime import datetime
import glob

def find_latest_schedule_files():
    """Find the latest combined schedule files."""
    # Look for the most recent output directory
    output_pattern = "output/combined_schedule_*"
    output_dirs = glob.glob(output_pattern)
    
    if not output_dirs:
        print("❌ No combined schedule output directories found!")
        return None, None
    
    # Get the most recent directory
    latest_dir = max(output_dirs, key=os.path.getctime)
    print(f"📁 Using latest schedule directory: {latest_dir}")
    
    lab_file = os.path.join(latest_dir, "combined_lab_schedule.csv")
    theory_file = os.path.join(latest_dir, "combined_theory_schedule.csv")
    
    if not os.path.exists(lab_file):
        print(f"❌ Lab schedule file not found: {lab_file}")
        lab_file = None
    
    if not os.path.exists(theory_file):
        print(f"❌ Theory schedule file not found: {theory_file}")
        theory_file = None
    
    return lab_file, theory_file

def parse_time_slot(time_slot):
    """Parse time slot string to get start and end times in minutes."""
    try:
        if " to " in time_slot:
            # Lab format: "8:00 - 8:50 to 8:50 - 9:40"
            parts = time_slot.split(" to ")
            start_time = parts[0].split(" - ")[0]
            end_time = parts[1].split(" - ")[1]
        elif " - " in time_slot:
            # Theory format: "8:00 - 8:50"
            start_time, end_time = time_slot.split(" - ")
        else:
            print(f"⚠️ Unknown time format: {time_slot}")
            return None, None
        
        def time_to_minutes(time_str):
            h, m = map(int, time_str.split(':'))
            # Handle PM times (1:00-7:10 are PM)
            if h >= 1 and h <= 7 and not (h >= 8 and h <= 12):
                h += 12
            return h * 60 + m
        
        start_minutes = time_to_minutes(start_time.strip())
        end_minutes = time_to_minutes(end_time.strip())
        
        return start_minutes, end_minutes
    except Exception as e:
        print(f"⚠️ Error parsing time slot '{time_slot}': {e}")
        return None, None

def times_overlap(start1, end1, start2, end2):
    """Check if two time ranges overlap."""
    if start1 is None or end1 is None or start2 is None or end2 is None:
        return False
    return start1 < end2 and end1 > start2

def is_valid_co_scheduling(session1, session2):
    """
    Check if two overlapping sessions in the same room represent valid co-scheduling.
    
    Co-scheduling is valid when:
    1. Same course code
    2. Same time slot (exact match)
    3. 140-capacity lab room (KSL03)
    4. Different teachers
    5. Both are lab sessions
    6. Same department and semester
    """
    # Must be in 140-capacity lab (KSL03 has room_id 172)
    if session1['room_id'] != 172 or session2['room_id'] != 172:
        return False
    
    # Must be exact same time slot
    if session1['time_slot'] != session2['time_slot']:
        return False
    
    # Must be same course code
    if session1['course_code'] != session2['course_code']:
        return False
    
    # Must be different teachers
    if session1['teacher_id'] == session2['teacher_id']:
        return False
    
    # Must both be lab sessions
    if session1['type'] != 'lab' or session2['type'] != 'lab':
        return False
    
    # Must be same department and semester
    if (session1['department'] != session2['department'] or 
        session1['semester'] != session2['semester']):
        return False
    
    return True

def load_and_prepare_schedules(lab_file, theory_file):
    """Load and prepare both schedule files for analysis."""
    schedules = {}
    
    # Load lab schedule
    if lab_file and os.path.exists(lab_file):
        try:
            lab_df = pd.read_csv(lab_file)
            print(f"📊 Loaded lab schedule: {len(lab_df)} sessions")
            
            # Prepare lab schedule data
            lab_sessions = []
            for _, row in lab_df.iterrows():
                start_time, end_time = parse_time_slot(str(row.get('time_range', '')))
                
                lab_sessions.append({
                    'type': 'lab',
                    'day': str(row.get('day', '')).lower(),
                    'time_slot': str(row.get('time_range', '')),
                    'start_time': start_time,
                    'end_time': end_time,
                    'room_id': int(row.get('room_id', 0)) if pd.notna(row.get('room_id')) else 0,
                    'room_number': str(row.get('room_number', '')),
                    'block': str(row.get('block', '')),
                    'course_code': str(row.get('course_code_display', row.get('course_code', ''))),
                    'course_name': str(row.get('course_name', '')),
                    'teacher_id': str(row.get('teacher_id', '')),
                    'teacher_name': str(row.get('teacher_name', '')),
                    'student_count': int(row.get('student_count', 0)) if pd.notna(row.get('student_count')) else 0,
                    'session_name': str(row.get('session_name', '')),
                    'department': str(row.get('department', '')),
                    'semester': int(row.get('semester', 0)) if pd.notna(row.get('semester')) else 0,
                    'day_pattern': str(row.get('day_pattern', ''))
                })
            
            schedules['lab'] = lab_sessions
            print(f"✅ Processed {len(lab_sessions)} lab sessions")
            
        except Exception as e:
            print(f"❌ Error loading lab schedule: {e}")
            schedules['lab'] = []
    else:
        schedules['lab'] = []
    
    # Load theory schedule
    if theory_file and os.path.exists(theory_file):
        try:
            theory_df = pd.read_csv(theory_file)
            print(f"📊 Loaded theory schedule: {len(theory_df)} sessions")
            
            # Prepare theory schedule data
            theory_sessions = []
            for _, row in theory_df.iterrows():
                start_time, end_time = parse_time_slot(str(row.get('time_slot', '')))
                
                theory_sessions.append({
                    'type': 'theory',
                    'day': str(row.get('day', '')).lower(),
                    'time_slot': str(row.get('time_slot', '')),
                    'start_time': start_time,
                    'end_time': end_time,
                    'room_id': int(row.get('room_id', 0)) if pd.notna(row.get('room_id')) else 0,
                    'room_number': str(row.get('room_number', '')),
                    'block': str(row.get('block', '')),
                    'course_code': str(row.get('course_code', '')),
                    'course_name': str(row.get('course_name', '')),
                    'teacher_id': str(row.get('teacher_id', '')),
                    'teacher_name': str(row.get('teacher_name', '')),
                    'student_count': int(row.get('student_count', 0)) if pd.notna(row.get('student_count')) else 0,
                    'session_type': str(row.get('session_type', '')),
                    'department': str(row.get('department', '')),
                    'semester': int(row.get('semester', 0)) if pd.notna(row.get('semester')) else 0,
                    'day_pattern': str(row.get('day_pattern', ''))
                })
            
            schedules['theory'] = theory_sessions
            print(f"✅ Processed {len(theory_sessions)} theory sessions")
            
        except Exception as e:
            print(f"❌ Error loading theory schedule: {e}")
            schedules['theory'] = []
    else:
        schedules['theory'] = []
    
    return schedules

def check_room_conflicts(schedules):
    """Check for room conflicts within and across schedules."""
    print("\n🔍 CHECKING FOR ROOM CONFLICTS...")
    print("=" * 60)
    
    all_sessions = schedules['lab'] + schedules['theory']
    conflicts = []
    
    # Group sessions by day for efficient checking
    sessions_by_day = defaultdict(list)
    for session in all_sessions:
        if session['day'] and session['room_id'] > 0:
            sessions_by_day[session['day']].append(session)
    
    total_conflicts = 0
    total_co_scheduling = 0
    
    for day, day_sessions in sessions_by_day.items():
        print(f"\n📅 Checking {day.upper()}...")
        day_conflicts = 0
        
        # Check each pair of sessions for conflicts
        for i in range(len(day_sessions)):
            for j in range(i + 1, len(day_sessions)):
                session1 = day_sessions[i]
                session2 = day_sessions[j]
                
                # Check if same room
                if session1['room_id'] == session2['room_id']:
                    # Check if times overlap
                    if times_overlap(session1['start_time'], session1['end_time'],
                                   session2['start_time'], session2['end_time']):
                        
                        # Check if this is valid co-scheduling (NOT a conflict)
                        is_co_scheduling = is_valid_co_scheduling(session1, session2)
                        
                        if is_co_scheduling:
                            # This is valid co-scheduling - not a conflict
                            total_co_scheduling += 1
                            print(f"  ✅ CO-SCHEDULING #{total_co_scheduling} (Valid):")
                            print(f"     Room: {session1['room_number']} (140-capacity lab)")
                            print(f"     Course: {session1['course_code']} - {session1['course_name']}")
                            print(f"     Time: {session1['time_slot']}")
                            print(f"     Teacher 1: {session1['teacher_name']} (ID: {session1['teacher_id']})")
                            print(f"     Teacher 2: {session2['teacher_name']} (ID: {session2['teacher_id']})")
                            print(f"     Department: {session1['department']} Semester: {session1['semester']}")
                            print()
                        else:
                            conflict = {
                                'day': day,
                                'room_id': session1['room_id'],
                                'room_number': session1['room_number'],
                                'block': session1['block'],
                                'session1': session1,
                                'session2': session2
                            }
                            conflicts.append(conflict)
                            day_conflicts += 1
                            total_conflicts += 1
                        
                        print(f"  ❌ CONFLICT #{total_conflicts}:")
                        print(f"     Room: {session1['room_number']} (ID: {session1['room_id']}) in {session1['block']}")
                        print(f"     Session 1: {session1['type'].upper()} - {session1['course_code']}")
                        print(f"                Time: {session1['time_slot']}")
                        print(f"                Teacher: {session1['teacher_name']} (ID: {session1['teacher_id']})")
                        print(f"                Dept: {session1['department']} Sem: {session1['semester']}")
                        print(f"     Session 2: {session2['type'].upper()} - {session2['course_code']}")
                        print(f"                Time: {session2['time_slot']}")
                        print(f"                Teacher: {session2['teacher_name']} (ID: {session2['teacher_id']})")
                        print(f"                Dept: {session2['department']} Sem: {session2['semester']}")
                        print()
        
        if day_conflicts == 0:
            print(f"  ✅ No conflicts found for {day}")
        else:
            print(f"  ❌ Found {day_conflicts} conflicts for {day}")
    
    print(f"\n📊 ROOM USAGE SUMMARY:")
    print(f"   Total conflicts: {total_conflicts}")
    print(f"   Co-scheduling instances: {total_co_scheduling}")
    if total_co_scheduling > 0:
        print(f"   ✅ {total_co_scheduling} valid co-scheduling pairs found (140-capacity lab optimization)")
    
    return conflicts

def check_teacher_conflicts(schedules):
    """Check for teacher conflicts within and across schedules."""
    print("\n👨‍🏫 CHECKING FOR TEACHER CONFLICTS...")
    print("=" * 60)
    
    all_sessions = schedules['lab'] + schedules['theory']
    conflicts = []
    
    # Group sessions by day and teacher
    sessions_by_day_teacher = defaultdict(lambda: defaultdict(list))
    for session in all_sessions:
        if session['day'] and session['teacher_id']:
            sessions_by_day_teacher[session['day']][session['teacher_id']].append(session)
    
    total_conflicts = 0
    
    for day, teachers in sessions_by_day_teacher.items():
        print(f"\n📅 Checking {day.upper()}...")
        day_conflicts = 0
        
        for teacher_id, teacher_sessions in teachers.items():
            if len(teacher_sessions) > 1:
                # Check each pair of sessions for time overlaps
                for i in range(len(teacher_sessions)):
                    for j in range(i + 1, len(teacher_sessions)):
                        session1 = teacher_sessions[i]
                        session2 = teacher_sessions[j]
                        
                        # Check if times overlap
                        if times_overlap(session1['start_time'], session1['end_time'],
                                       session2['start_time'], session2['end_time']):
                            conflict = {
                                'day': day,
                                'teacher_id': teacher_id,
                                'teacher_name': session1['teacher_name'],
                                'session1': session1,
                                'session2': session2
                            }
                            conflicts.append(conflict)
                            day_conflicts += 1
                            total_conflicts += 1
                            
                            print(f"  ❌ TEACHER CONFLICT #{total_conflicts}:")
                            print(f"     Teacher: {session1['teacher_name']} (ID: {teacher_id})")
                            print(f"     Session 1: {session1['type'].upper()} - {session1['course_code']}")
                            print(f"                Time: {session1['time_slot']}")
                            print(f"                Room: {session1['room_number']} (ID: {session1['room_id']})")
                            print(f"     Session 2: {session2['type'].upper()} - {session2['course_code']}")
                            print(f"                Time: {session2['time_slot']}")
                            print(f"                Room: {session2['room_number']} (ID: {session2['room_id']})")
                            print()
        
        if day_conflicts == 0:
            print(f"  ✅ No teacher conflicts found for {day}")
        else:
            print(f"  ❌ Found {day_conflicts} teacher conflicts for {day}")
    
    return conflicts

def check_day_pattern_consistency(schedules):
    """Check for day pattern consistency issues."""
    print("\n🔍 CHECKING DAY PATTERN CONSISTENCY...")
    print("=" * 60)
    
    all_sessions = schedules['lab'] + schedules['theory']
    issues = []
    
    # Define expected days for each pattern
    pattern_days = {
        'Monday-Friday': ['monday', 'tuesday', 'wed', 'thur', 'fri'],
        'Tuesday-Saturday': ['tuesday', 'wed', 'thur', 'fri', 'saturday']
    }
    
    total_issues = 0
    
    for session in all_sessions:
        day = session.get('day', '').lower().strip()
        day_pattern = session.get('day_pattern', '').strip()
        department = session.get('department', '')
        course_code = session.get('course_code', '')
        
        if day and day_pattern and day_pattern in pattern_days:
            expected_days = pattern_days[day_pattern]
            
            if day not in expected_days:
                issue = {
                    'department': department,
                    'course_code': course_code,
                    'day': day,
                    'day_pattern': day_pattern,
                    'expected_days': expected_days,
                    'session_type': session.get('type', ''),
                    'teacher_name': session.get('teacher_name', '')
                }
                issues.append(issue)
                total_issues += 1
                
                print(f"❌ DAY PATTERN VIOLATION:")
                print(f"   Department: {department}")
                print(f"   Course: {course_code}")
                print(f"   Scheduled on: {day}")
                print(f"   Expected pattern: {day_pattern} ({', '.join(expected_days)})")
                print(f"   Session type: {session.get('type', '')}")
                print()
    
    if total_issues == 0:
        print("✅ No day pattern violations found!")
    else:
        print(f"❌ Found {total_issues} day pattern violations")
    
    return issues

def generate_summary_report(schedules, room_conflicts, teacher_conflicts, day_pattern_issues=None):
    """Generate a comprehensive summary report."""
    print("\n📋 SUMMARY REPORT")
    print("=" * 60)
    
    lab_sessions = schedules['lab']
    theory_sessions = schedules['theory']
    total_sessions = len(lab_sessions) + len(theory_sessions)
    
    print(f"📊 SCHEDULE STATISTICS:")
    print(f"   Total sessions: {total_sessions}")
    print(f"   Lab sessions: {len(lab_sessions)}")
    print(f"   Theory sessions: {len(theory_sessions)}")
    
    # Room usage analysis
    all_sessions = lab_sessions + theory_sessions
    used_rooms = set()
    lab_rooms = set()
    theory_rooms = set()
    room_usage_count = defaultdict(int)
    
    for session in all_sessions:
        if session['room_id'] > 0:
            used_rooms.add(session['room_id'])
            room_usage_count[session['room_id']] += 1
            
            if session['type'] == 'lab':
                lab_rooms.add(session['room_id'])
            else:
                theory_rooms.add(session['room_id'])
    
    print(f"\n🏛️ ROOM USAGE:")
    print(f"   Total rooms used: {len(used_rooms)}")
    print(f"   Lab rooms used: {len(lab_rooms)}")
    print(f"   Theory rooms used: {len(theory_rooms)}")
    print(f"   Shared rooms (both lab & theory): {len(lab_rooms & theory_rooms)}")
    
    # Day pattern analysis
    day_patterns = defaultdict(int)
    days_used = set()
    
    for session in all_sessions:
        if session['day']:
            days_used.add(session['day'])
            if session['day_pattern']:
                day_patterns[session['day_pattern']] += 1
    
    print(f"\n📅 DAY USAGE:")
    print(f"   Days with sessions: {sorted(days_used)}")
    if day_patterns:
        print(f"   Day patterns:")
        for pattern, count in day_patterns.items():
            print(f"     {pattern}: {count} sessions")
    
    # Department and semester analysis
    departments = set()
    semesters = set()
    dept_sem_combinations = set()
    
    for session in all_sessions:
        if session['department']:
            departments.add(session['department'])
        if session['semester'] > 0:
            semesters.add(session['semester'])
        if session['department'] and session['semester'] > 0:
            dept_sem_combinations.add((session['department'], session['semester']))
    
    print(f"\n🏫 ACADEMIC DISTRIBUTION:")
    print(f"   Departments: {len(departments)}")
    print(f"   Semesters: {sorted(semesters)}")
    print(f"   Dept-Semester combinations: {len(dept_sem_combinations)}")
    
    # Conflict summary
    print(f"\n⚠️ CONFLICTS SUMMARY:")
    print(f"   Room conflicts: {len(room_conflicts)}")
    print(f"   Teacher conflicts: {len(teacher_conflicts)}")
    if day_pattern_issues is not None:
        print(f"   Day pattern violations: {len(day_pattern_issues)}")
    
    total_issues = len(room_conflicts) + len(teacher_conflicts)
    if day_pattern_issues is not None:
        total_issues += len(day_pattern_issues)
    
    if total_issues == 0:
        print(f"   ✅ NO CONFLICTS FOUND - Schedule is valid!")
    else:
        print(f"   ❌ CONFLICTS DETECTED - Schedule needs attention!")
    
    # Most used rooms
    if room_usage_count:
        print(f"\n🔥 TOP 10 MOST USED ROOMS:")
        sorted_rooms = sorted(room_usage_count.items(), key=lambda x: x[1], reverse=True)
        for i, (room_id, count) in enumerate(sorted_rooms[:10], 1):
            # Find room details
            room_info = None
            for session in all_sessions:
                if session['room_id'] == room_id:
                    room_info = session
                    break
            
            if room_info:
                print(f"   {i:2d}. Room {room_info['room_number']} (ID: {room_id}) - {count} sessions")
            else:
                print(f"   {i:2d}. Room ID {room_id} - {count} sessions")

def save_conflicts_to_file(room_conflicts, teacher_conflicts, output_dir):
    """Save conflict details to files."""
    if not room_conflicts and not teacher_conflicts:
        return
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Save room conflicts
    if room_conflicts:
        room_conflicts_file = os.path.join(output_dir, f"room_conflicts_{timestamp}.txt")
        with open(room_conflicts_file, 'w', encoding='utf-8') as f:
            f.write("ROOM CONFLICTS REPORT\n")
            f.write("=" * 50 + "\n\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Total conflicts: {len(room_conflicts)}\n\n")
            
            for i, conflict in enumerate(room_conflicts, 1):
                f.write(f"CONFLICT #{i}:\n")
                f.write(f"Day: {conflict['day']}\n")
                f.write(f"Room: {conflict['room_number']} (ID: {conflict['room_id']}) in {conflict['block']}\n")
                f.write(f"Session 1: {conflict['session1']['type'].upper()} - {conflict['session1']['course_code']}\n")
                f.write(f"           Time: {conflict['session1']['time_slot']}\n")
                f.write(f"           Teacher: {conflict['session1']['teacher_name']}\n")
                f.write(f"Session 2: {conflict['session2']['type'].upper()} - {conflict['session2']['course_code']}\n")
                f.write(f"           Time: {conflict['session2']['time_slot']}\n")
                f.write(f"           Teacher: {conflict['session2']['teacher_name']}\n")
                f.write("\n" + "-" * 50 + "\n\n")
        
        print(f"💾 Room conflicts saved to: {room_conflicts_file}")
    
    # Save teacher conflicts
    if teacher_conflicts:
        teacher_conflicts_file = os.path.join(output_dir, f"teacher_conflicts_{timestamp}.txt")
        with open(teacher_conflicts_file, 'w', encoding='utf-8') as f:
            f.write("TEACHER CONFLICTS REPORT\n")
            f.write("=" * 50 + "\n\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Total conflicts: {len(teacher_conflicts)}\n\n")
            
            for i, conflict in enumerate(teacher_conflicts, 1):
                f.write(f"CONFLICT #{i}:\n")
                f.write(f"Day: {conflict['day']}\n")
                f.write(f"Teacher: {conflict['teacher_name']} (ID: {conflict['teacher_id']})\n")
                f.write(f"Session 1: {conflict['session1']['type'].upper()} - {conflict['session1']['course_code']}\n")
                f.write(f"           Time: {conflict['session1']['time_slot']}\n")
                f.write(f"           Room: {conflict['session1']['room_number']}\n")
                f.write(f"Session 2: {conflict['session2']['type'].upper()} - {conflict['session2']['course_code']}\n")
                f.write(f"           Time: {conflict['session2']['time_slot']}\n")
                f.write(f"           Room: {conflict['session2']['room_number']}\n")
                f.write("\n" + "-" * 50 + "\n\n")
        
        print(f"💾 Teacher conflicts saved to: {teacher_conflicts_file}")

def main():
    """Main function to run the double booking checker."""
    print("🔍 DOUBLE BOOKING CHECKER FOR COMBINED SCHEDULES")
    print("=" * 60)
    print(f"⏰ Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Find the latest schedule files
    lab_file, theory_file = find_latest_schedule_files()
    
    if not lab_file and not theory_file:
        print("❌ No schedule files found. Please run the scheduler first.")
        return
    
    # Load and prepare schedules
    schedules = load_and_prepare_schedules(lab_file, theory_file)
    
    if not schedules['lab'] and not schedules['theory']:
        print("❌ No valid schedule data found.")
        return
    
    # Check for conflicts
    room_conflicts = check_room_conflicts(schedules)
    teacher_conflicts = check_teacher_conflicts(schedules)
    day_pattern_issues = check_day_pattern_consistency(schedules)
    
    # Generate summary report
    generate_summary_report(schedules, room_conflicts, teacher_conflicts, day_pattern_issues)
    
    # Save conflicts to files if any exist
    if room_conflicts or teacher_conflicts:
        # Use the same directory as the input files
        output_dir = os.path.dirname(lab_file or theory_file)
        save_conflicts_to_file(room_conflicts, teacher_conflicts, output_dir)
    
    print(f"\n⏰ Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("🔍 Double booking check complete!")

if __name__ == "__main__":
    main() 