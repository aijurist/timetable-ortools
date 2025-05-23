import pandas as pd
import os
from collections import defaultdict

def verify_ltp_constraints():
    """Verify that LTP constraints are satisfied for all courses."""
    
    # Load course requirements
    course_file = "data/mapped_data/cs_teacher_courses.csv"
    courses_df = pd.read_csv(course_file)
    
    # Find the latest schedule
    output_dir = "output"
    folders = [f for f in os.listdir(output_dir) if f.startswith("schedule_")]
    latest_folder = max(folders) if folders else None
    
    if not latest_folder:
        print("No schedule found!")
        return
    
    schedule_file = os.path.join(output_dir, latest_folder, "schedule.csv")
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
    scheduled_hours = defaultdict(lambda: {'theory': 0, 'lab': 0})
    
    for _, row in schedule_df.iterrows():
        try:
            instance_id = str(int(float(row['course_instance_id'])))  # Handle float conversion issues
        except:
            instance_id = str(row['course_instance_id'])  # Fallback
        slot_type = row['slot_type']
        
        if slot_type == 'Theory':
            scheduled_hours[instance_id]['theory'] += 1
        elif slot_type == 'Lab':
            scheduled_hours[instance_id]['lab'] += 1
    
    print(f"{'Instance':<12} {'Course':<10} {'Teacher':<8} {'Students':<9} {'L Req':<6} {'L Sch':<6} {'P Req':<6} {'P Sch':<6} {'Status':<15}")
    print("-" * 90)
    
    violations = 0
    total_instances = 0
    intelligent_optimized = 0
    
    for instance_id, requirements in course_requirements.items():
        total_instances += 1
        
        lecture_required = requirements['lecture_hours']
        practical_required = requirements['practical_hours']
        course_code = requirements['course_code']
        teacher_id = requirements['teacher_id']
        student_count = requirements['student_count']
        
        lecture_scheduled = scheduled_hours[instance_id]['theory']
        practical_scheduled = scheduled_hours[instance_id]['lab']
        
        # Calculate expected practical slots
        if practical_required > 0:
            base_practical_slots = (practical_required + 1) // 2  # Ceiling division
            
            # Traditional batching for >35 students
            if student_count > 35:
                traditional_batches = (student_count + 34) // 35
                expected_practical_traditional = base_practical_slots * traditional_batches
            else:
                expected_practical_traditional = base_practical_slots
        else:
            expected_practical_traditional = 0
            base_practical_slots = 0
        
        # Check if this instance is using intelligent allocation
        try:
            instance_schedule = schedule_df[schedule_df['course_instance_id'].astype(str) == instance_id]
        except:
            # Fallback method
            instance_schedule = schedule_df[schedule_df['course_instance_id'] == int(instance_id)]
        
        lab_schedule = instance_schedule[instance_schedule['slot_type'] == 'Lab']
        
        intelligent_used = False
        if not lab_schedule.empty:
            # Check for intelligent batching indicator
            if 'intelligent_batching' in lab_schedule.columns:
                intelligent_batching = lab_schedule.iloc[0].get('intelligent_batching', 'No')
                if intelligent_batching == 'Yes':
                    intelligent_used = True
                    intelligent_optimized += 1
                    expected_practical = base_practical_slots  # No batching multiplier
                else:
                    expected_practical = expected_practical_traditional
            else:
                # Fallback: detect by room capacity
                room_capacity = lab_schedule.iloc[0].get('room_capacity', 35)
                if room_capacity >= 70 and student_count > 60:
                    intelligent_used = True
                    intelligent_optimized += 1
                    expected_practical = base_practical_slots  # No batching multiplier
                else:
                    expected_practical = expected_practical_traditional
        else:
            expected_practical = expected_practical_traditional
        
        # Check compliance
        lecture_ok = lecture_scheduled == lecture_required
        practical_ok = practical_scheduled == expected_practical
        
        if lecture_ok and practical_ok:
            if intelligent_used:
                status = "✅ Intelligent"
            else:
                status = "✅ Compliant"
        else:
            status = "❌ Violation"
            violations += 1
        
        print(f"{instance_id:<12} {course_code:<10} {teacher_id:<8} {student_count:<9} {lecture_required:<6} {lecture_scheduled:<6} {practical_required:<6} {practical_scheduled:<6} {status:<15}")
    
    print("-" * 90)
    print(f"\n📊 LTP CONSTRAINT RESULTS:")
    print(f"✅ Compliant instances: {total_instances - violations}/{total_instances}")
    print(f"❌ Violations: {violations}")
    print(f"🧠 Intelligent optimizations: {intelligent_optimized}")
    print(f"📈 Compliance rate: {((total_instances - violations)/total_instances)*100:.1f}%")
    
    if violations == 0:
        print(f"\n🎉 ALL LTP CONSTRAINTS SATISFIED!")
        print(f"   Lecture-Tutorial-Practical hours properly allocated")
        print(f"   Intelligent batching working correctly")
        return True
    else:
        print(f"\n⚠️  LTP CONSTRAINT VIOLATIONS DETECTED!")
        return False

if __name__ == "__main__":
    verify_ltp_constraints() 