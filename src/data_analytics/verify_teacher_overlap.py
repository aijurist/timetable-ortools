import pandas as pd
import os
from collections import defaultdict
from datetime import datetime

def verify_teacher_overlap():
    """Verify that no teacher has overlapping assignments at the same time slot."""
    
    print("🔍 TEACHER OVERLAP VERIFICATION")
    print("=" * 80)
    print("Checking for teacher double-booking conflicts at the same time slots")
    print("=" * 80)
    
    # Find the latest schedule
    output_dir = "output"
    if not os.path.exists(output_dir):
        print("❌ No output directory found!")
        return False
    
    folders = [f for f in os.listdir(output_dir) if f.startswith("macroblock_schedule_")]
    if not folders:
        print("❌ No macroblock schedule found!")
        return False
        
    latest_folder = max(folders)
    print(f"📁 Latest folder: {latest_folder}")
    schedule_file = os.path.join(output_dir, latest_folder, "macroblock_schedule.csv")
    print(f"📄 Schedule file: {schedule_file}")
    
    if not os.path.exists(schedule_file):
        print(f"❌ Schedule file not found: {schedule_file}")
        return False
    
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
            'course_instance_id': row['course_instance_id']
        }
        
        teacher_schedule[teacher_id][time_key].append(assignment_info)
    
    # Check for overlaps (same teacher, same time slot, multiple assignments)
    print("🔍 CHECKING FOR TEACHER OVERLAPS...")
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
    
    print(f"\n📈 OVERLAP ANALYSIS RESULTS:")
    print(f"Total overlap conflicts found: {total_conflicts}")
    print(f"Teachers with conflicts: {len(teachers_with_conflicts)} out of {len(teacher_schedule)}")
    
    if total_conflicts == 0:
        print("✅ NO TEACHER OVERLAPS DETECTED - All teachers have clean schedules!")
    else:
        print(f"❌ {total_conflicts} OVERLAP CONFLICTS DETECTED!")
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
                detail = f"{assignment['course_code']}({assignment['slot_type']}) in {assignment['room_number']}"
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
                print(f" " * 12 + f"{j}. {assignment['course_code']} - {assignment['course_name'][:40]}")
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
            'course_instance_id': row['course_instance_id']
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
            courses = ", ".join(set(a['course_code'] for a in assignments))
            
            print(f"{room_id:<10} {day.capitalize():<10} {time_interval:<15} {teachers:<30} {courses:<30}")
    
    # Summary report
    print("\n" + "=" * 80)
    print("📊 FINAL VERIFICATION SUMMARY")
    print("=" * 80)
    print(f"✅ Schedule file analyzed: {schedule_file}")
    print(f"📅 Analysis timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📈 Total assignments checked: {len(schedule_df)}")
    print(f"👥 Teachers analyzed: {len(teacher_schedule)}")
    print(f"🏫 Rooms analyzed: {len(room_schedule)}")
    print()
    print("🎯 CONFLICT RESULTS:")
    print(f"   Teacher overlap conflicts: {total_conflicts}")
    print(f"   Room double-booking conflicts: {room_conflict_count}")
    print()
    
    if total_conflicts == 0 and room_conflict_count == 0:
        print("🎉 VERIFICATION PASSED: No overlapping conflicts detected!")
        return True
    else:
        print("⚠️  VERIFICATION FAILED: Conflicts detected that need resolution!")
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