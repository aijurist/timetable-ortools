import pandas as pd
import os
from collections import defaultdict
from datetime import datetime

def parse_time(time_str):
    """Parse time string like '11:00' to minutes since midnight."""
    if ' - ' in time_str:
        time_part = time_str.split(' - ')[0]  # Get start time from range
    else:
        time_part = time_str.split()[0]  # Get '11:00' from '11:00 - 11:50'
    hours, minutes = map(int, time_part.split(':'))
    return hours * 60 + minutes

def time_ranges_overlap(range1, range2):
    """Check if two time ranges overlap."""
    try:
        # Parse range1 (e.g., "11:00 - 11:50")
        start1_str, end1_str = range1.split(' - ')
        start1 = parse_time(start1_str)
        end1 = parse_time(end1_str)
        
        # Parse range2 (e.g., "10:40 - 11:30") 
        start2_str, end2_str = range2.split(' - ')
        start2 = parse_time(start2_str)
        end2 = parse_time(end2_str)
        
        # Check for overlap: ranges overlap if start1 < end2 and start2 < end1
        return start1 < end2 and start2 < end1
    except (ValueError, AttributeError):
        return False

def find_latest_schedules():
    """Find the most recent lab and theory schedule files."""
    output_dir = "output"
    if not os.path.exists(output_dir):
        return None, None, None, None
    
    # Find latest lab schedule
    lab_file = None
    lab_type = None
    lab_folders = [f for f in os.listdir(output_dir) if f.startswith("lab_schedule_")]
    if lab_folders:
        latest_lab_folder = max(lab_folders)
        combined_file = os.path.join(output_dir, latest_lab_folder, "combined_theory_lab_schedule.csv")
        if os.path.exists(combined_file):
            lab_file = combined_file
            lab_type = "combined"
    
    # Find latest theory schedule
    theory_file = None
    theory_type = None
    theory_folders = [f for f in os.listdir(output_dir) if f.startswith("macroblock_schedule_")]
    if theory_folders:
        latest_theory_folder = max(theory_folders)
        theory_file = os.path.join(output_dir, latest_theory_folder, "macroblock_schedule.csv")
        if os.path.exists(theory_file):
            theory_type = "theory_only"
    
    return lab_file, lab_type, theory_file, theory_type

def find_latest_schedule():
    """Find the most recent schedule file (prioritizing lab schedules for lab analysis)."""
    output_dir = "output"
    if not os.path.exists(output_dir):
        return None, None
    
    # MODIFIED: Prioritize lab schedules first for lab assignment analysis
    lab_folders = [f for f in os.listdir(output_dir) if f.startswith("lab_schedule_")]
    if lab_folders:
        latest_lab_folder = max(lab_folders)
        combined_file = os.path.join(output_dir, latest_lab_folder, "combined_theory_lab_schedule.csv")
        if os.path.exists(combined_file):
            return combined_file, "combined"
    
    # Fall back to theory-only schedules if no lab schedules exist
    theory_folders = [f for f in os.listdir(output_dir) if f.startswith("macroblock_schedule_")]
    if theory_folders:
        latest_theory_folder = max(theory_folders)
        theory_file = os.path.join(output_dir, latest_theory_folder, "macroblock_schedule.csv")
        if os.path.exists(theory_file):
            return theory_file, "theory_only"
    
    return None, None

def verify_cross_schedule_overlaps():
    """Verify that teachers don't have overlapping assignments between lab and theory schedules."""
    print("\n🔄 CROSS-SCHEDULE OVERLAP VERIFICATION (Lab vs Theory)")
    print("=" * 80)
    print("Checking for teacher conflicts between lab_schedule and macroblock_schedule")
    print("=" * 80)
    
    # Find both schedule files
    lab_file, lab_type, theory_file, theory_type = find_latest_schedules()
    
    if lab_file is None or theory_file is None:
        if lab_file is None:
            print("❌ No lab schedule file found!")
        if theory_file is None:
            print("❌ No theory schedule file found!")
        print("⚠️  Cannot perform cross-schedule verification without both files.")
        return []
    
    print(f"📁 Lab schedule file: {lab_file}")
    print(f"📁 Theory schedule file: {theory_file}")
    
    try:
        # Load lab schedule and filter for lab assignments only
        lab_df = pd.read_csv(lab_file)
        lab_assignments = lab_df[lab_df['slot_type'] == 'Practical'].copy()
        print(f"✅ Loaded {len(lab_assignments)} lab assignments from {lab_file}")
        
        # Load theory schedule and filter for theory assignments only
        theory_df = pd.read_csv(theory_file)
        theory_assignments = theory_df[theory_df['slot_type'].isin(['Lecture', 'Tutorial'])].copy()
        print(f"✅ Loaded {len(theory_assignments)} theory assignments from {theory_file}")
        
    except Exception as e:
        print(f"❌ Error loading schedule files: {e}")
        return []
    
    if lab_assignments.empty and theory_assignments.empty:
        print("❌ Both schedules are empty!")
        return []
    
    if lab_assignments.empty:
        print("⚠️  No lab assignments found - skipping cross-schedule verification")
        return []
    
    if theory_assignments.empty:
        print("⚠️  No theory assignments found - skipping cross-schedule verification")
        return []
    
    # Find common teachers between both schedules
    lab_teachers = set(lab_assignments['teacher_id'].unique())
    theory_teachers = set(theory_assignments['teacher_id'].unique())
    common_teachers = lab_teachers.intersection(theory_teachers)
    
    print(f"\n📊 TEACHER ANALYSIS:")
    print(f"Teachers with lab assignments: {len(lab_teachers)}")
    print(f"Teachers with theory assignments: {len(theory_teachers)}")
    print(f"Teachers with both lab and theory: {len(common_teachers)}")
    
    if not common_teachers:
        print("✅ No teachers have both lab and theory assignments - no cross-schedule conflicts possible")
        return []
    
    # Check for overlaps between lab and theory for each common teacher
    cross_schedule_conflicts = []
    
    print(f"\n🔍 CHECKING CROSS-SCHEDULE CONFLICTS FOR {len(common_teachers)} TEACHERS...")
    print("-" * 80)
    
    for teacher_id in common_teachers:
        teacher_lab_assignments = lab_assignments[lab_assignments['teacher_id'] == teacher_id]
        teacher_theory_assignments = theory_assignments[theory_assignments['teacher_id'] == teacher_id]
        
        teacher_conflicts = 0
        
        # Check each lab assignment against each theory assignment for the same teacher
        for _, lab_row in teacher_lab_assignments.iterrows():
            for _, theory_row in teacher_theory_assignments.iterrows():
                # Check if they're on the same day
                if lab_row['day'] == theory_row['day']:
                    lab_time = lab_row['time_interval']
                    theory_time = theory_row['time_interval']
                    
                    # Check for time overlap
                    if time_ranges_overlap(lab_time, theory_time):
                        conflict_info = {
                            'teacher_id': teacher_id,
                            'day': lab_row['day'],
                            'lab_course': lab_row.get('display_course_code', lab_row.get('course_code', 'Unknown')),
                            'lab_time': lab_time,
                            'lab_room': lab_row['room_number'],
                            'lab_session': lab_row.get('lab_session', 'Unknown'),
                            'theory_course': theory_row['course_code'],
                            'theory_time': theory_time,
                            'theory_room': theory_row['room_number'],
                            'theory_macroblock': theory_row.get('macroblock', 'Unknown'),
                            'conflict_type': 'cross_schedule_overlap'
                        }
                        cross_schedule_conflicts.append(conflict_info)
                        teacher_conflicts += 1
        
        if teacher_conflicts > 0:
            print(f"⚠️  Teacher {teacher_id}: {teacher_conflicts} cross-schedule conflict(s)")
    
    print(f"\n📈 CROSS-SCHEDULE OVERLAP ANALYSIS RESULTS:")
    print(f"Total cross-schedule conflicts found: {len(cross_schedule_conflicts)}")
    print(f"Teachers with cross-schedule conflicts: {len(set(c['teacher_id'] for c in cross_schedule_conflicts))}")
    
    if not cross_schedule_conflicts:
        print("✅ NO CROSS-SCHEDULE OVERLAPS DETECTED - Lab and theory schedules are compatible!")
    else:
        print(f"❌ {len(cross_schedule_conflicts)} CROSS-SCHEDULE CONFLICTS DETECTED!")
        print("\n📋 DETAILED CROSS-SCHEDULE CONFLICT REPORT:")
        print("=" * 120)
        print(f"{'Teacher':<10} {'Day':<10} {'Lab Course':<15} {'Lab Time':<15} {'Lab Room':<12} {'Theory Course':<15} {'Theory Time':<15} {'Theory Room':<12}")
        print("-" * 120)
        
        for conflict in cross_schedule_conflicts:
            print(f"{conflict['teacher_id']:<10} "
                 f"{conflict['day'].capitalize():<10} "
                 f"{conflict['lab_course']:<15} "
                 f"{conflict['lab_time']:<15} "
                 f"{conflict['lab_room']:<12} "
                 f"{conflict['theory_course']:<15} "
                 f"{conflict['theory_time']:<15} "
                 f"{conflict['theory_room']:<12}")
        
        print(f"\n⚠️  CRITICAL: These teachers are double-booked between lab and theory schedules!")
        print(f"   - Lab assignments are from: {lab_file}")
        print(f"   - Theory assignments are from: {theory_file}")
    
    return cross_schedule_conflicts

def verify_lab_overlaps(schedule_df):
    """Verify lab assignments for overlaps and capacity constraint violations."""
    print("🧪 LAB SCHEDULE OVERLAP VERIFICATION")
    print("=" * 60)
    
    # Filter for lab assignments only
    lab_schedule = schedule_df[schedule_df['slot_type'] == 'Practical'].copy()
    
    if lab_schedule.empty:
        print("❌ No lab assignments found in schedule")
        return [], []
    
    print(f"📊 Found {len(lab_schedule)} lab assignments to verify")
    
    # Teacher overlap detection
    teacher_overlaps = []
    teachers = lab_schedule['teacher_id'].unique()
    
    for teacher in teachers:
        teacher_labs = lab_schedule[lab_schedule['teacher_id'] == teacher]
        
        # Check for overlapping lab sessions for the same teacher
        for i, (_, lab1) in enumerate(teacher_labs.iterrows()):
            for j, (_, lab2) in enumerate(teacher_labs.iterrows()):
                if i >= j:  # Avoid duplicate comparisons
                    continue
                
                # Check if labs are on the same day
                if lab1['day'] == lab2['day']:
                    # Parse time intervals
                    time1 = lab1['time_interval']
                    time2 = lab2['time_interval']
                    
                    # Check for overlap
                    if time_ranges_overlap(time1, time2):
                        overlap_info = {
                            'teacher_id': teacher,
                            'day': lab1['day'],
                            'course1': lab1.get('display_course_code', lab1.get('course_code', 'Unknown')),
                            'time1': time1,
                            'room1': lab1['room_number'],
                            'course2': lab2.get('display_course_code', lab2.get('course_code', 'Unknown')),
                            'time2': time2,
                            'room2': lab2['room_number'],
                            'type': 'teacher_lab_overlap'
                        }
                        teacher_overlaps.append(overlap_info)
    
    # Lab room overlap detection
    lab_room_overlaps = []
    lab_rooms = lab_schedule['room_id'].unique()
    
    for room in lab_rooms:
        room_labs = lab_schedule[lab_schedule['room_id'] == room]
        
        # Check for overlapping assignments in the same lab room
        for i, (_, lab1) in enumerate(room_labs.iterrows()):
            for j, (_, lab2) in enumerate(room_labs.iterrows()):
                if i >= j:  # Avoid duplicate comparisons
                    continue
                
                # Check if labs are on the same day
                if lab1['day'] == lab2['day']:
                    # Parse time intervals
                    time1 = lab1['time_interval']
                    time2 = lab2['time_interval']
                    
                    # Check for overlap
                    if time_ranges_overlap(time1, time2):
                        overlap_info = {
                            'room_id': room,
                            'room_number': lab1['room_number'],
                            'day': lab1['day'],
                            'course1': lab1.get('display_course_code', lab1.get('course_code', 'Unknown')),
                            'teacher1': lab1['teacher_id'],
                            'time1': time1,
                            'course2': lab2.get('display_course_code', lab2.get('course_code', 'Unknown')),
                            'teacher2': lab2['teacher_id'],
                            'time2': time2,
                            'type': 'lab_room_overlap'
                        }
                        lab_room_overlaps.append(overlap_info)
    
    # NEW: Hard constraint validation - capacity assignments
    capacity_violations = []
    if 'room_capacity' in lab_schedule.columns and 'practical_hours' in lab_schedule.columns:
        print(f"\n🚨 HARD CONSTRAINT VALIDATION (Capacity Assignment Rules)")
        print("=" * 60)
        
        # Check for hard constraint violations: courses with <3 practical hours in 70+ capacity labs
        for _, lab in lab_schedule.iterrows():
            practical_hours = lab.get('practical_hours', 0)
            room_capacity = lab.get('room_capacity', 0)
            student_count = lab.get('student_count', 70)
            course_code = lab.get('display_course_code', lab.get('course_code', 'Unknown'))
            
            # Apply hard constraint check for 70-student courses
            if student_count == 70 and practical_hours < 3 and room_capacity > 35:
                violation_info = {
                    'course_code': course_code,
                    'teacher_id': lab['teacher_id'],
                    'practical_hours': practical_hours,
                    'room_capacity': room_capacity,
                    'room_number': lab['room_number'],
                    'day': lab['day'],
                    'time_interval': lab['time_interval'],
                    'violation_type': 'hard_constraint_capacity',
                    'description': f"Course with {practical_hours} practical hours assigned to {room_capacity}-capacity lab (should be ≤35)"
                }
                capacity_violations.append(violation_info)
        
        if capacity_violations:
            print(f"❌ Found {len(capacity_violations)} hard constraint violations:")
            for violation in capacity_violations:
                print(f"   - {violation['course_code']} (Teacher {violation['teacher_id']}): "
                     f"{violation['practical_hours']} practical hours → {violation['room_capacity']}-capacity lab "
                     f"({violation['room_number']}) on {violation['day']} at {violation['time_interval']}")
            print(f"\n⚠️  RULE: Courses with <3 practical hours MUST use 35-capacity labs only!")
        else:
            print(f"✅ All lab assignments respect the hard constraint!")
            print(f"   - Courses with <3 practical hours → 35-capacity labs only")
            print(f"   - Courses with ≥3 practical hours → can use 70-capacity labs")
    
    # Report lab overlap results
    total_lab_violations = len(teacher_overlaps) + len(lab_room_overlaps) + len(capacity_violations)
    
    if teacher_overlaps:
        print(f"\n❌ Found {len(teacher_overlaps)} teacher lab overlaps:")
        for overlap in teacher_overlaps:
            print(f"   - Teacher {overlap['teacher_id']} on {overlap['day']}: "
                 f"{overlap['course1']} at {overlap['time1']} in {overlap['room1']} "
                 f"overlaps with {overlap['course2']} at {overlap['time2']} in {overlap['room2']}")
    else:
        print(f"\n✅ No teacher lab overlaps detected")
    
    if lab_room_overlaps:
        print(f"\n❌ Found {len(lab_room_overlaps)} lab room overlaps:")
        for overlap in lab_room_overlaps:
            print(f"   - Room {overlap['room_number']} on {overlap['day']}: "
                 f"{overlap['course1']} (T:{overlap['teacher1']}) at {overlap['time1']} "
                 f"overlaps with {overlap['course2']} (T:{overlap['teacher2']}) at {overlap['time2']}")
    else:
        print(f"\n✅ No lab room overlaps detected")
    
    print(f"\n📊 LAB VERIFICATION SUMMARY:")
    print(f"Total lab assignments verified: {len(lab_schedule)}")
    print(f"Teacher lab overlaps: {len(teacher_overlaps)}")
    print(f"Lab room overlaps: {len(lab_room_overlaps)}")
    print(f"Capacity constraint violations: {len(capacity_violations)}")
    print(f"Total lab violations: {total_lab_violations}")
    
    # Combine all lab violations
    all_lab_violations = teacher_overlaps + lab_room_overlaps + capacity_violations
    
    return all_lab_violations, lab_schedule

def verify_teacher_overlap():
    """Verify that no teacher has overlapping assignments at the same time slot."""
    
    print("🔍 COMPREHENSIVE TEACHER & LAB OVERLAP VERIFICATION")
    print("=" * 80)
    print("Checking for teacher double-booking conflicts and lab overlaps")
    print("=" * 80)
    
    # Find the latest schedule
    schedule_file, schedule_type = find_latest_schedule()
    
    if schedule_file is None:
        print("❌ No schedule files found!")
        return False
    
    print(f"📁 Schedule file: {schedule_file}")
    print(f"📄 Schedule type: {schedule_type}")
    
    try:
        schedule_df = pd.read_csv(schedule_file)
        print(f"✅ Successfully loaded schedule with {len(schedule_df)} assignments")
    except Exception as e:
        print(f"❌ Error loading schedule file: {e}")
        return False
    
    if schedule_df.empty:
        print("❌ Schedule file is empty!")
        return False
    
    print("\n📊 SCHEDULE SUMMARY:")
    print(f"Total scheduled assignments: {len(schedule_df)}")
    print(f"Unique teachers: {schedule_df['teacher_id'].nunique()}")
    print(f"Unique courses: {schedule_df['course_code'].nunique()}")
    print(f"Unique rooms: {schedule_df['room_id'].nunique()}")
    print(f"Days covered: {', '.join(sorted(schedule_df['day'].unique()))}")
    
    # Check slot types present
    slot_types = schedule_df['slot_type'].value_counts()
    print(f"Slot types: {dict(slot_types)}")
    print("=" * 80)
    
    # Group assignments by teacher and time slot to detect overlaps
    overlap_conflicts = []
    teacher_schedule = defaultdict(lambda: defaultdict(list))
    
    # Build teacher schedule mapping: teacher_id -> {(day, slot_index): [assignments]}
    for _, row in schedule_df.iterrows():
        teacher_id = row['teacher_id']
        day = row['day']
        slot_index = row['slot_index']
        time_key = (day, slot_index)
        
        assignment_info = {
            'course_code': row['course_code'],
            'course_name': row['course_name'],
            'room_number': row['room_number'],
            'room_id': row['room_id'],
            'slot_type': row['slot_type'],
            'macroblock': row.get('macroblock', 'Unknown'),
            'time_interval': row['time_interval'],
            'course_instance_id': row['course_instance_id'],
            'lab_session': row.get('lab_session', ''),
            'display_course_code': row.get('display_course_code', row['course_code'])
        }
        
        teacher_schedule[teacher_id][time_key].append(assignment_info)
    
    # Check for overlaps (same teacher, same time slot, multiple assignments)
    print("🔍 CHECKING FOR TEACHER TIME SLOT OVERLAPS...")
    print("-" * 80)
    
    total_conflicts = 0
    teachers_with_conflicts = set()
    
    # Check each teacher's schedule
    for teacher_id, teacher_slots in teacher_schedule.items():
        teacher_conflicts = 0
        
        for time_key, assignments in teacher_slots.items():
            if len(assignments) > 1:
                # Found overlap conflict!
                day, slot_index = time_key
                conflict = {
                    'teacher_id': teacher_id,
                    'day': day,
                    'slot_index': slot_index,
                    'time_interval': assignments[0]['time_interval'],
                    'assignments': assignments
                }
                overlap_conflicts.append(conflict)
                teacher_conflicts += 1
                total_conflicts += 1
                teachers_with_conflicts.add(teacher_id)
        
        if teacher_conflicts > 0:
            print(f"⚠️  Teacher {teacher_id}: {teacher_conflicts} time slot conflict(s)")
    
    print(f"\n📈 TIME SLOT OVERLAP ANALYSIS RESULTS:")
    print(f"Total time slot conflicts found: {total_conflicts}")
    print(f"Teachers with conflicts: {len(teachers_with_conflicts)} out of {len(teacher_schedule)}")
    
    if total_conflicts == 0:
        print("✅ NO TEACHER TIME SLOT OVERLAPS DETECTED - All teachers have clean schedules!")
    else:
        print(f"❌ {total_conflicts} TIME SLOT OVERLAP CONFLICTS DETECTED!")
        print("\n📋 DETAILED CONFLICT REPORT:")
        print("=" * 120)
        print(f"{'Teacher':<10} {'Day':<10} {'Time':<15} {'Slot':<5} {'Conflicts':<12} {'Details':<60}")
        print("-" * 120)
        
        for i, conflict in enumerate(overlap_conflicts, 1):
            teacher_id = conflict['teacher_id']
            day = conflict['day']
            time_interval = conflict['time_interval']
            slot_index = conflict['slot_index']
            assignments = conflict['assignments']
            num_conflicts = len(assignments)
            
            # Create conflict details string
            conflict_details = []
            for assignment in assignments:
                course_display = assignment.get('display_course_code', assignment['course_code'])
                detail = f"{course_display}({assignment['slot_type']}) in {assignment['room_number']}"
                if assignment['lab_session']:
                    detail += f" [{assignment['lab_session']}]"
                conflict_details.append(detail)
            
            details_str = " | ".join(conflict_details)
            if len(details_str) > 58:
                details_str = details_str[:55] + "..."
            
            print(f"{teacher_id:<10} {day.capitalize():<10} {time_interval:<15} {slot_index:<5} {num_conflicts:<12} {details_str:<60}")
            
            # Print detailed breakdown for each conflict
            print(" " * 10 + "└─ Breakdown:")
            for j, assignment in enumerate(assignments, 1):
                course_instance = assignment['course_instance_id']
                macroblock = assignment['macroblock']
                course_display = assignment.get('display_course_code', assignment['course_code'])
                print(f" " * 12 + f"{j}. {course_display} - {assignment['course_name'][:40]}")
                print(f" " * 15 + f"Instance: {course_instance}, Macroblock: {macroblock}, Room: {assignment['room_number']}, Type: {assignment['slot_type']}")
            print()
    
    # Additional analysis: Room conflicts (same room, same time, different teachers)
    print("\n🏫 CHECKING FOR ROOM CONFLICTS...")
    print("-" * 80)
    
    room_conflicts = []
    room_schedule = defaultdict(lambda: defaultdict(list))
    
    # Build room schedule mapping: room_id -> {(day, slot_index): [assignments]}
    for _, row in schedule_df.iterrows():
        room_id = row['room_id']
        day = row['day']
        slot_index = row['slot_index']
        time_key = (day, slot_index)
        
        assignment_info = {
            'teacher_id': row['teacher_id'],
            'course_code': row['course_code'],
            'slot_type': row['slot_type'],
            'time_interval': row['time_interval'],
            'course_instance_id': row['course_instance_id'],
            'display_course_code': row.get('display_course_code', row['course_code'])
        }
        
        room_schedule[room_id][time_key].append(assignment_info)
    
    # Check for room conflicts
    room_conflict_count = 0
    for room_id, room_slots in room_schedule.items():
        for time_key, assignments in room_slots.items():
            if len(assignments) > 1:
                # Check if different teachers are using the same room
                teachers_in_room = set(assignment['teacher_id'] for assignment in assignments)
                if len(teachers_in_room) > 1:
                    day, slot_index = time_key
                    room_conflicts.append({
                        'room_id': room_id,
                        'day': day,
                        'slot_index': slot_index,
                        'time_interval': assignments[0]['time_interval'],
                        'assignments': assignments
                    })
                    room_conflict_count += 1
    
    if room_conflict_count == 0:
        print("✅ NO ROOM CONFLICTS DETECTED - All rooms properly allocated!")
    else:
        print(f"❌ {room_conflict_count} ROOM CONFLICTS DETECTED!")
        print(f"{'Room':<10} {'Day':<10} {'Time':<15} {'Teachers':<30} {'Courses':<30}")
        print("-" * 95)
        
        for conflict in room_conflicts:
            room_id = conflict['room_id']
            day = conflict['day']
            time_interval = conflict['time_interval']
            assignments = conflict['assignments']
            
            teachers = ", ".join(set(str(a['teacher_id']) for a in assignments))
            courses = ", ".join(set(a.get('display_course_code', a['course_code']) for a in assignments))
            
            print(f"{room_id:<10} {day.capitalize():<10} {time_interval:<15} {teachers:<30} {courses:<30}")
    
    # Lab overlap verification (if we have lab data)
    all_lab_violations, lab_schedule = verify_lab_overlaps(schedule_df)
    
    # Cross-schedule verification
    cross_schedule_conflicts = verify_cross_schedule_overlaps()
    
    # Summary report
    print("\n" + "=" * 80)
    print("📊 FINAL VERIFICATION SUMMARY")
    print("=" * 80)
    print(f"✅ Schedule file analyzed: {schedule_file}")
    print(f"📅 Analysis timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📈 Total assignments checked: {len(schedule_df)}")
    print(f"👥 Teachers analyzed: {len(teacher_schedule)}")
    print(f"🏫 Rooms analyzed: {len(room_schedule)}")
    print(f"📋 Schedule type: {schedule_type}")
    print()
    print("🎯 CONFLICT RESULTS:")
    print(f"   Teacher time slot conflicts: {total_conflicts}")
    print(f"   Room double-booking conflicts: {room_conflict_count}")
    print(f"   Teacher lab overlaps: {len(all_lab_violations)}")
    print(f"   Cross-schedule conflicts: {len(cross_schedule_conflicts)}")
    print()
    
    total_issues = total_conflicts + room_conflict_count + len(all_lab_violations) + len(cross_schedule_conflicts)
    
    if total_issues == 0:
        print("🎉 VERIFICATION PASSED: No overlapping conflicts detected!")
        return True
    else:
        print(f"⚠️  VERIFICATION FAILED: {total_issues} total conflicts detected that need resolution!")
        return False

def main():
    """Main function to run teacher overlap verification."""
    # Change to the correct directory if needed
    if os.path.exists("timetable_scheduler"):
        os.chdir("timetable_scheduler")
    
    # Run verification
    success = verify_teacher_overlap()
    
    if success:
        print("\n✅ Teacher overlap verification completed successfully!")
    else:
        print("\n❌ Teacher overlap verification found issues!")
    
    return success

if __name__ == "__main__":
    main() 