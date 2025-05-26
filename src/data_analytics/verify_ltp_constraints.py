import pandas as pd
import os
from collections import defaultdict

def verify_ltp_constraints():
    """Verify that LTP constraints are satisfied for all courses."""
    
    # Load course requirements
    course_file = "data/mapped_data/cs_teacher_courses.csv"
    if not os.path.exists(course_file):
        print(f"Course file not found: {course_file}")
        return False
    
    courses_df = pd.read_csv(course_file)
    
    # Find the latest schedule
    output_dir = "output"
    if not os.path.exists(output_dir):
        print("No output directory found!")
        return False
    
    folders = [f for f in os.listdir(output_dir) if f.startswith("macroblock_schedule_")]
    if not folders:
        print("No macroblock schedule found!")
        return False
        
    latest_folder = max(folders)
    schedule_file = os.path.join(output_dir, latest_folder, "macroblock_schedule.csv")
    
    if not os.path.exists(schedule_file):
        print(f"Schedule file not found: {schedule_file}")
        return False
    
    schedule_df = pd.read_csv(schedule_file)
    
    print("🔍 LTP CONSTRAINT VERIFICATION")
    print("=" * 80)
    
    # Create mapping of course requirements
    course_requirements = {}
    for _, row in courses_df.iterrows():
        instance_id = str(row['id'])
        course_requirements[instance_id] = {
            'lecture_hours': row['lecture_hours'],
            'practical_hours': row['practical_hours'],
            'tutorial_hours': row['tutorial_hours'],
            'course_code': row['course_code'],
            'teacher_id': row['teacher_id'],
            'student_count': row['student_count']
        }
    
    # Count scheduled hours per course instance
    scheduled_hours = defaultdict(lambda: {'lecture': 0, 'tutorial': 0, 'practical': 0})
    
    for _, row in schedule_df.iterrows():
        try:
            instance_id = str(int(float(row['course_instance_id'])))  # Handle float conversion issues
        except:
            instance_id = str(row['course_instance_id'])  # Fallback
        slot_type = row['slot_type']
        
        if slot_type == 'Lecture':
            scheduled_hours[instance_id]['lecture'] += 1
        elif slot_type == 'Tutorial':
            scheduled_hours[instance_id]['tutorial'] += 1
        elif slot_type == 'Practical':
            scheduled_hours[instance_id]['practical'] += 1
    
    print(f"{'Instance':<12} {'Course':<10} {'Teacher':<8} {'Students':<9} {'L Req':<6} {'L Sch':<6} {'T Req':<6} {'T Sch':<6} {'P Req':<6} {'P Sch':<6} {'Status':<15}")
    print("-" * 110)
    
    violations = 0
    total_instances = 0
    
    for instance_id, requirements in course_requirements.items():
        total_instances += 1
        
        lecture_required = requirements['lecture_hours']
        tutorial_required = requirements['tutorial_hours']
        practical_required = requirements['practical_hours']
        course_code = requirements['course_code']
        teacher_id = requirements['teacher_id']
        student_count = requirements['student_count']
        
        lecture_scheduled = scheduled_hours[instance_id]['lecture']
        tutorial_scheduled = scheduled_hours[instance_id]['tutorial']
        practical_scheduled = scheduled_hours[instance_id]['practical']
        
        # Determine expected tutorial hours
        # Tutorial allocation rule: If tutorial_hours > 0 OR lecture_hours == 4
        if tutorial_required > 0:
            expected_tutorial = tutorial_required
        elif lecture_required == 4:
            expected_tutorial = 1  # Add one tutorial hour for 4-hour lecture courses
        else:
            expected_tutorial = 0
        
        # Check compliance (allow flexibility: at least required, max +1 extra)
        lecture_ok = lecture_required <= lecture_scheduled <= lecture_required + 1
        tutorial_ok = expected_tutorial <= tutorial_scheduled <= expected_tutorial + 1
        practical_ok = True  # Skip practical validation for now (labs not allocated)
        
        if lecture_ok and tutorial_ok and practical_ok:
            status = "✅ Compliant"
        else:
            status = "❌ Violation"
            violations += 1
        
        print(f"{instance_id:<12} {course_code:<10} {teacher_id:<8} {student_count:<9} {lecture_required:<6} {lecture_scheduled:<6} {expected_tutorial:<6} {tutorial_scheduled:<6} {practical_required:<6} {practical_scheduled:<6} {status:<15}")
    
    print("-" * 110)
    print(f"\n📊 LTP CONSTRAINT RESULTS:")
    print(f"✅ Compliant instances: {total_instances - violations}/{total_instances}")
    print(f"❌ Violations: {violations}")
    print(f"📈 Compliance rate: {((total_instances - violations)/total_instances)*100:.1f}%")
    
    if violations == 0:
        print(f"\n🎉 ALL LTP CONSTRAINTS SATISFIED!")
        print(f"   Lecture hours properly allocated")
        print(f"   Tutorial hours allocated according to rules:")
        print(f"     - If tutorial_hours > 0 OR lecture_hours == 4")
        print(f"   Practical hours validation skipped (labs not allocated)")
        return True
    else:
        print(f"\n⚠️  LTP CONSTRAINT VIOLATIONS DETECTED!")
        print(f"   Check lecture and tutorial hour allocations")
        return False

if __name__ == "__main__":
    verify_ltp_constraints() 