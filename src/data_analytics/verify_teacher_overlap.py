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

def find_latest_schedule():
    """Find the most recent schedule file (theory or combined)."""
    output_dir = "output"
    if not os.path.exists(output_dir):
        return None, None
    
    # Look for lab schedules first (combined theory + lab)
    lab_folders = [f for f in os.listdir(output_dir) if f.startswith("lab_schedule_")]
    if lab_folders:
        latest_lab_folder = max(lab_folders)
        combined_file = os.path.join(output_dir, latest_lab_folder, "combined_theory_lab_schedule.csv")
        if os.path.exists(combined_file):
            return combined_file, "combined"
    
    # Fall back to theory-only schedules
    theory_folders = [f for f in os.listdir(output_dir) if f.startswith("macroblock_schedule_")]
    if theory_folders:
        latest_theory_folder = max(theory_folders)
        theory_file = os.path.join(output_dir, latest_theory_folder, "macroblock_schedule.csv")
        if os.path.exists(theory_file):
            return theory_file, "theory_only"
    
    return None, None

def verify_lab_overlaps(schedule_df):
    """Verify lab-specific overlapping conflicts."""
    print("\n🧪 LAB OVERLAP VERIFICATION")
    print("=" * 80)
    print("Checking for theory-lab conflicts and lab-to-lab overlaps")
    print("=" * 80)
    
    # Separate theory and lab data
    theory_data = schedule_df[schedule_df['slot_type'].isin(['Lecture', 'Tutorial'])]
    lab_data = schedule_df[schedule_df['slot_type'] == 'Practical']
    
    print(f"📊 Theory assignments: {len(theory_data)}")
    print(f"🧪 Lab assignments: {len(lab_data)}")
    
    theory_lab_conflicts = []
    lab_lab_conflicts = []
    
    # Check for theory-lab overlaps (same teacher, same day, overlapping times)
    print("\n🔍 Checking theory-lab time conflicts...")
    
    for teacher_id in schedule_df['teacher_id'].unique():
        teacher_theory = theory_data[theory_data['teacher_id'] == teacher_id]
        teacher_labs = lab_data[lab_data['teacher_id'] == teacher_id]
        
        for _, theory_row in teacher_theory.iterrows():
            theory_day = theory_row['day']
            theory_time = theory_row['time_interval']
            
            for _, lab_row in teacher_labs.iterrows():
                lab_day = lab_row['day']
                lab_time = lab_row['time_interval']
                
                # Check if same day and time overlap
                if theory_day == lab_day and time_ranges_overlap(theory_time, lab_time):
                    conflict = {
                        'teacher_id': teacher_id,
                        'day': theory_day,
                        'theory_time': theory_time,
                        'lab_time': lab_time,
                        'theory_course': theory_row['course_code'],
                        'lab_course': lab_row['course_code'],
                        'theory_room': theory_row['room_number'],
                        'lab_room': lab_row['room_number'],
                        'theory_instance': theory_row.get('course_instance_id', ''),
                        'lab_instance': lab_row.get('course_instance_id', ''),
                        'overlap_type': 'theory_lab'
                    }
                    theory_lab_conflicts.append(conflict)
    
    # Check for lab-lab overlaps (same teacher, same day, overlapping lab times)
    print("🔍 Checking lab-to-lab time conflicts...")
    
    for teacher_id in lab_data['teacher_id'].unique():
        teacher_labs = lab_data[lab_data['teacher_id'] == teacher_id]
        
        # Group by day for efficiency
        for day in teacher_labs['day'].unique():
            day_labs = teacher_labs[teacher_labs['day'] == day]
            
            # Check each pair of lab assignments for overlaps
            for i, lab1 in day_labs.iterrows():
                for j, lab2 in day_labs.iterrows():
                    if i >= j:  # Avoid duplicate checks
                        continue
                    
                    if time_ranges_overlap(lab1['time_interval'], lab2['time_interval']):
                        conflict = {
                            'teacher_id': teacher_id,
                            'day': day,
                            'lab1_time': lab1['time_interval'],
                            'lab2_time': lab2['time_interval'],
                            'lab1_course': lab1['course_code'],
                            'lab2_course': lab2['course_code'],
                            'lab1_room': lab1['room_number'],
                            'lab2_room': lab2['room_number'],
                            'lab1_instance': lab1.get('course_instance_id', ''),
                            'lab2_instance': lab2.get('course_instance_id', ''),
                            'overlap_type': 'lab_lab'
                        }
                        lab_lab_conflicts.append(conflict)
    
    # Report theory-lab conflicts
    print(f"\n📈 THEORY-LAB CONFLICT ANALYSIS:")
    print(f"Theory-lab conflicts found: {len(theory_lab_conflicts)}")
    
    if theory_lab_conflicts:
        print("❌ THEORY-LAB CONFLICTS DETECTED!")
        print("\n📋 DETAILED THEORY-LAB CONFLICT REPORT:")
        print("=" * 140)
        print(f"{'Teacher':<8} {'Day':<10} {'Theory Time':<15} {'Lab Time':<15} {'Theory Course':<15} {'Lab Course':<15} {'Theory Room':<12} {'Lab Room':<12}")
        print("-" * 140)
        
        for conflict in theory_lab_conflicts:
            print(f"{conflict['teacher_id']:<8} {conflict['day'].capitalize():<10} {conflict['theory_time']:<15} {conflict['lab_time']:<15} "
                  f"{conflict['theory_course']:<15} {conflict['lab_course']:<15} {conflict['theory_room']:<12} {conflict['lab_room']:<12}")
            
            # Show instance details if available
            if conflict['theory_instance'] or conflict['lab_instance']:
                print(f"{'':>10} └─ Instances: Theory ID {conflict['theory_instance']}, Lab ID {conflict['lab_instance']}")
    else:
        print("✅ NO THEORY-LAB CONFLICTS - Theory and lab schedules are properly separated!")
    
    # Report lab-lab conflicts
    print(f"\n📈 LAB-TO-LAB CONFLICT ANALYSIS:")
    print(f"Lab-to-lab conflicts found: {len(lab_lab_conflicts)}")
    
    if lab_lab_conflicts:
        print("❌ LAB-TO-LAB CONFLICTS DETECTED!")
        print("\n📋 DETAILED LAB-TO-LAB CONFLICT REPORT:")
        print("=" * 140)
        print(f"{'Teacher':<8} {'Day':<10} {'Lab1 Time':<15} {'Lab2 Time':<15} {'Lab1 Course':<15} {'Lab2 Course':<15} {'Lab1 Room':<12} {'Lab2 Room':<12}")
        print("-" * 140)
        
        for conflict in lab_lab_conflicts:
            print(f"{conflict['teacher_id']:<8} {conflict['day'].capitalize():<10} {conflict['lab1_time']:<15} {conflict['lab2_time']:<15} "
                  f"{conflict['lab1_course']:<15} {conflict['lab2_course']:<15} {conflict['lab1_room']:<12} {conflict['lab2_room']:<12}")
            
            # Show instance details if available
            if conflict['lab1_instance'] or conflict['lab2_instance']:
                print(f"{'':>10} └─ Instances: Lab1 ID {conflict['lab1_instance']}, Lab2 ID {conflict['lab2_instance']}")
    else:
        print("✅ NO LAB-TO-LAB CONFLICTS - All lab sessions are properly scheduled!")
    
    return len(theory_lab_conflicts), len(lab_lab_conflicts)

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
    theory_lab_conflicts = 0
    lab_lab_conflicts = 0
    if 'Practical' in schedule_df['slot_type'].values:
        theory_lab_conflicts, lab_lab_conflicts = verify_lab_overlaps(schedule_df)
    else:
        print("\n🧪 LAB OVERLAP VERIFICATION")
        print("=" * 80)
        print("⚠️  No lab/practical assignments found in schedule")
        print("✅ Lab overlap verification skipped (theory-only schedule)")
    
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
    print(f"   Theory-lab time conflicts: {theory_lab_conflicts}")
    print(f"   Lab-to-lab time conflicts: {lab_lab_conflicts}")
    print()
    
    total_issues = total_conflicts + room_conflict_count + theory_lab_conflicts + lab_lab_conflicts
    
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