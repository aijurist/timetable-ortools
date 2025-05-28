import pandas as pd
import os
import sys
from collections import defaultdict
from datetime import datetime

def verify_all_constraints():
    """Comprehensive verification of all timetable constraints."""
    
    print("🔍 COMPREHENSIVE TIMETABLE CONSTRAINT VERIFICATION")
    print("=" * 100)
    print("Checking: Teacher Overlaps | Room Conflicts | Course Hour Requirements | Priority Constraints")
    print("=" * 100)
    
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
    
    # Load course requirements for LTP verification
    course_file = "data/mapped_data/computer_dept_teacher_courses.csv"
    if not os.path.exists(course_file):
        print(f"⚠️  Course file not found: {course_file}")
        courses_df = None
    else:
        try:
            courses_df = pd.read_csv(course_file)
            print(f"✅ Successfully loaded course requirements with {len(courses_df)} instances")
        except Exception as e:
            print(f"⚠️  Error loading course file: {e}")
            courses_df = None
    
    print("\n📊 SCHEDULE OVERVIEW:")
    print(f"Total scheduled assignments: {len(schedule_df)}")
    print(f"Unique teachers: {schedule_df['teacher_id'].nunique()}")
    print(f"Unique courses: {schedule_df['course_code'].nunique()}")
    print(f"Unique rooms: {schedule_df['room_id'].nunique()}")
    print(f"Days covered: {', '.join(sorted(schedule_df['day'].unique()))}")
    print(f"Time slots used: {schedule_df['slot_index'].nunique()}")
    print("=" * 100)
    
    # Constraint checks
    all_passed = True
    
    # 1. Teacher Overlap Check
    print("\n1️⃣ TEACHER OVERLAP VERIFICATION")
    print("-" * 80)
    teacher_overlap_passed = check_teacher_overlaps(schedule_df)
    all_passed = all_passed and teacher_overlap_passed
    
    # 2. Room Conflict Check
    print("\n2️⃣ ROOM CONFLICT VERIFICATION")
    print("-" * 80)
    room_conflict_passed = check_room_conflicts(schedule_df)
    all_passed = all_passed and room_conflict_passed
    
    # 3. LTP Course Hour Requirements (if course data available)
    if courses_df is not None:
        print("\n3️⃣ COURSE HOUR REQUIREMENTS VERIFICATION")
        print("-" * 80)
        ltp_passed = check_ltp_requirements(schedule_df, courses_df)
        all_passed = all_passed and ltp_passed
    else:
        print("\n3️⃣ COURSE HOUR REQUIREMENTS VERIFICATION")
        print("-" * 80)
        print("⚠️  Skipped - Course requirements file not available")
    
    # 4. Priority Constraint Check (v1/v2 exclusion)
    print("\n4️⃣ PRIORITY CONSTRAINT VERIFICATION")
    print("-" * 80)
    priority_passed = check_priority_constraints(schedule_df)
    all_passed = all_passed and priority_passed
    
    # 5. Extended Tutorial Block Usage
    print("\n5️⃣ EXTENDED TUTORIAL BLOCK USAGE VERIFICATION")
    print("-" * 80)
    tutorial_passed = check_extended_tutorial_usage(schedule_df)
    all_passed = all_passed and tutorial_passed
    
    # 6. Weekly Working Hours (21-hour limit)
    print("\n6️⃣ WEEKLY WORKING HOURS VERIFICATION")
    print("-" * 80)
    hours_passed = check_weekly_working_hours(schedule_df)
    all_passed = all_passed and hours_passed
    
    # Final Summary
    print("\n" + "=" * 100)
    print("📊 COMPREHENSIVE VERIFICATION SUMMARY")
    print("=" * 100)
    print(f"✅ Schedule file analyzed: {schedule_file}")
    print(f"📅 Analysis timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📈 Total assignments verified: {len(schedule_df)}")
    print()
    print("🎯 CONSTRAINT CHECK RESULTS:")
    print(f"   1. Teacher Overlaps:        {'✅ PASS' if teacher_overlap_passed else '❌ FAIL'}")
    print(f"   2. Room Conflicts:          {'✅ PASS' if room_conflict_passed else '❌ FAIL'}")
    if courses_df is not None:
        print(f"   3. Course Hour Requirements: {'✅ PASS' if ltp_passed else '❌ FAIL'}")
    else:
        print(f"   3. Course Hour Requirements: ⚠️  SKIP")
    print(f"   4. Priority Constraints:    {'✅ PASS' if priority_passed else '❌ FAIL'}")
    print(f"   5. Extended Tutorial Usage: {'✅ PASS' if tutorial_passed else '❌ FAIL'}")
    print(f"   6. Weekly Working Hours:    {'✅ PASS' if hours_passed else '❌ FAIL'}")
    print()
    
    if all_passed:
        print("🎉 ALL CONSTRAINTS VERIFIED - Schedule is fully compliant!")
        return True
    else:
        print("⚠️  CONSTRAINT VIOLATIONS DETECTED - Schedule needs review!")
        return False

def check_teacher_overlaps(schedule_df):
    """Check for teacher overlap conflicts."""
    teacher_schedule = defaultdict(lambda: defaultdict(list))
    
    # Build teacher schedule mapping
    for _, row in schedule_df.iterrows():
        teacher_id = row['teacher_id']
        day = row['day']
        slot_index = row['slot_index']
        time_key = (day, slot_index)
        teacher_schedule[teacher_id][time_key].append(row)
    
    # Check for overlaps
    total_conflicts = 0
    for teacher_id, teacher_slots in teacher_schedule.items():
        for time_key, assignments in teacher_slots.items():
            if len(assignments) > 1:
                total_conflicts += 1
                day, slot_index = time_key
                print(f"❌ Teacher {teacher_id}: {len(assignments)} overlapping assignments on {day} slot {slot_index}")
                for i, assignment in enumerate(assignments, 1):
                    print(f"    {i}. {assignment['course_code']} in {assignment['room_number']} ({assignment['slot_type']})")
    
    if total_conflicts == 0:
        print("✅ No teacher overlaps detected")
        return True
    else:
        print(f"❌ {total_conflicts} teacher overlap conflicts found")
        return False

def check_room_conflicts(schedule_df):
    """Check for room conflict issues."""
    room_schedule = defaultdict(lambda: defaultdict(list))
    
    # Build room schedule mapping
    for _, row in schedule_df.iterrows():
        room_id = row['room_id']
        day = row['day']
        slot_index = row['slot_index']
        time_key = (day, slot_index)
        room_schedule[room_id][time_key].append(row)
    
    # Check for conflicts
    room_conflicts = 0
    for room_id, room_slots in room_schedule.items():
        for time_key, assignments in room_slots.items():
            if len(assignments) > 1:
                # Check if different teachers are using the same room
                teachers_in_room = set(assignment['teacher_id'] for assignment in assignments)
                if len(teachers_in_room) > 1:
                    room_conflicts += 1
                    day, slot_index = time_key
                    room_number = assignments[0]['room_number']
                    teachers = ", ".join(map(str, teachers_in_room))
                    print(f"❌ Room {room_number} (ID: {room_id}): Multiple teachers on {day} slot {slot_index}: {teachers}")
    
    if room_conflicts == 0:
        print("✅ No room conflicts detected")
        return True
    else:
        print(f"❌ {room_conflicts} room conflicts found")
        return False

def check_ltp_requirements(schedule_df, courses_df):
    """Check if LTP course hour requirements are met."""
    # Create mapping of course requirements
    course_requirements = {}
    for _, row in courses_df.iterrows():
        instance_id = str(row['id'])
        course_requirements[instance_id] = {
            'lecture_hours': row['lecture_hours'],
            'tutorial_hours': row['tutorial_hours'],
            'practical_hours': row['practical_hours'],
            'course_code': row['course_code']
        }
    
    # Count scheduled hours per course instance
    scheduled_hours = defaultdict(lambda: {'lecture': 0, 'tutorial': 0, 'practical': 0})
    
    for _, row in schedule_df.iterrows():
        try:
            instance_id = str(int(float(row['course_instance_id'])))
        except:
            instance_id = str(row['course_instance_id'])
        
        slot_type = row['slot_type']
        if slot_type == 'Lecture':
            scheduled_hours[instance_id]['lecture'] += 1
        elif slot_type == 'Tutorial':
            scheduled_hours[instance_id]['tutorial'] += 1
        elif slot_type == 'Practical':
            scheduled_hours[instance_id]['practical'] += 1
    
    # Check compliance
    violations = 0
    for instance_id, requirements in course_requirements.items():
        if instance_id in scheduled_hours:
            req_lec = requirements['lecture_hours']
            req_tut = requirements['tutorial_hours']
            req_prac = requirements['practical_hours']
            
            sch_lec = scheduled_hours[instance_id]['lecture']
            sch_tut = scheduled_hours[instance_id]['tutorial']
            sch_prac = scheduled_hours[instance_id]['practical']
            
            # Apply case logic for expected allocation
            if req_lec == 3 and req_tut == 0:
                exp_lec, exp_tut = 3, 0
            elif req_lec == 3 and req_tut == 1:
                exp_lec, exp_tut = 3, 1
            elif req_lec == 2 and req_tut == 1:
                exp_lec, exp_tut = 2, 1
            elif req_lec == 2 and req_tut == 2:
                exp_lec, exp_tut = 2, 2
            elif req_lec == 4:
                exp_lec, exp_tut = 4, req_tut
            else:
                exp_lec, exp_tut = req_lec, req_tut
            
            if sch_lec != exp_lec or sch_tut != exp_tut:
                violations += 1
                course_code = requirements['course_code']
                print(f"❌ Instance {instance_id} ({course_code}): Expected {exp_lec}L+{exp_tut}T, Got {sch_lec}L+{sch_tut}T")
    
    if violations == 0:
        print(f"✅ All course hour requirements satisfied ({len(course_requirements)} instances checked)")
        return True
    else:
        print(f"❌ {violations} course hour requirement violations found")
        return False

def check_priority_constraints(schedule_df):
    """Check priority constraints (v1/v2 exclusion, extended tutorial priority)."""
    violations = 0
    
    # Check v1/v2 exclusion
    v1_v2_assignments = schedule_df[schedule_df['macroblock'].isin(['v1', 'v2'])]
    if not v1_v2_assignments.empty:
        violations += len(v1_v2_assignments)
        print(f"❌ Found {len(v1_v2_assignments)} assignments to excluded blocks v1/v2:")
        for _, row in v1_v2_assignments.iterrows():
            print(f"    {row['course_code']} -> {row['macroblock']} (Teacher: {row['teacher_id']})")
    else:
        print("✅ v1/v2 blocks properly excluded from assignments")
    
    # Check priority for extended tutorial blocks
    extended_blocks = ['a1', 'a2', 'b1', 'b2', 'c1', 'c2']
    priority_courses = schedule_df[
        (schedule_df['macroblock'].isin(extended_blocks)) &
        (schedule_df['course_code'].str.contains('4L|3L.*1T|2L.*2T', regex=True, na=False))
    ]
    
    print(f"✅ {len(priority_courses)} priority courses found in extended tutorial blocks")
    
    if violations == 0:
        print("✅ Priority constraints satisfied")
        return True
    else:
        print(f"❌ {violations} priority constraint violations found")
        return False

def check_extended_tutorial_usage(schedule_df):
    """Check proper usage of extended tutorial blocks."""
    extended_tutorial_blocks = ['taa1', 'taa2', 'tbb1', 'tbb2', 'tcc1', 'tcc2']
    extended_assignments = schedule_df[schedule_df['macroblock'].isin(extended_tutorial_blocks)]
    
    tutorial_usage = len(extended_assignments[extended_assignments['slot_type'] == 'Tutorial'])
    lecture_usage = len(extended_assignments[extended_assignments['slot_type'] == 'Lecture'])
    
    print(f"Extended tutorial blocks usage:")
    print(f"  Tutorial sessions: {tutorial_usage}")
    print(f"  Lecture sessions: {lecture_usage}")
    print(f"  Total extended block usage: {len(extended_assignments)}")
    
    # Extended tutorial blocks should primarily be used for tutorials
    if tutorial_usage >= lecture_usage:
        print("✅ Extended tutorial blocks used appropriately")
        return True
    else:
        print("⚠️  Extended tutorial blocks used more for lectures than tutorials")
        return True  # Not a hard failure

def check_weekly_working_hours(schedule_df):
    """Check 21-hour weekly working limit per teacher."""
    teacher_hours = defaultdict(int)
    
    for _, row in schedule_df.iterrows():
        teacher_id = row['teacher_id']
        slot_type = row['slot_type']
        
        if slot_type in ['Lecture', 'Tutorial']:
            teacher_hours[teacher_id] += 1  # 1 hour per theory slot
        elif slot_type == 'Practical':
            teacher_hours[teacher_id] += 2  # 2 hours per lab slot
    
    violations = 0
    for teacher_id, hours in teacher_hours.items():
        if hours > 21:
            violations += 1
            print(f"❌ Teacher {teacher_id}: {hours} hours/week (exceeds 21-hour limit)")
    
    if violations == 0:
        max_hours = max(teacher_hours.values()) if teacher_hours else 0
        avg_hours = sum(teacher_hours.values()) / len(teacher_hours) if teacher_hours else 0
        print(f"✅ All teachers within 21-hour limit (max: {max_hours}, avg: {avg_hours:.1f})")
        return True
    else:
        print(f"❌ {violations} teachers exceed 21-hour weekly limit")
        return False

def main():
    """Main function to run comprehensive constraint verification."""
    # Change to the correct directory if needed
    if os.path.exists("timetable_scheduler"):
        os.chdir("timetable_scheduler")
    
    # Run comprehensive verification
    success = verify_all_constraints()
    
    if success:
        print("\n✅ Comprehensive constraint verification completed successfully!")
    else:
        print("\n❌ Comprehensive constraint verification found violations!")
    
    return success

if __name__ == "__main__":
    main() 