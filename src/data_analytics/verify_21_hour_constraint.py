import pandas as pd
import os
from collections import defaultdict

def verify_21_hour_constraint():
    """Verify that no teacher exceeds 21 hours in the generated schedule."""
    
    # Find the latest schedule file
    output_dir = "output"
    latest_schedule = None
    latest_time = 0
    
    for folder in os.listdir(output_dir):
        if folder.startswith("schedule_"):
            folder_path = os.path.join(output_dir, folder)
            folder_time = os.path.getctime(folder_path)
            if folder_time > latest_time:
                latest_time = folder_time
                latest_schedule = folder_path
    
    if not latest_schedule:
        print("No schedule found!")
        return
    
    schedule_file = os.path.join(latest_schedule, "schedule.csv")
    if not os.path.exists(schedule_file):
        print(f"Schedule file not found: {schedule_file}")
        return
    
    print(f"Verifying schedule: {schedule_file}")
    print("=" * 80)
    
    # Load the schedule
    df = pd.read_csv(schedule_file)
    
    # Calculate hours per teacher
    teacher_hours = defaultdict(lambda: {'theory': 0, 'lab': 0, 'total': 0})
    
    for _, row in df.iterrows():
        teacher_id = row['teacher_id']
        slot_type = row['slot_type']
        
        if slot_type == 'Theory':
            teacher_hours[teacher_id]['theory'] += 1  # 1 hour per theory slot
        elif slot_type == 'Lab':
            teacher_hours[teacher_id]['lab'] += 2   # 2 hours per lab slot
        
        teacher_hours[teacher_id]['total'] = (
            teacher_hours[teacher_id]['theory'] + teacher_hours[teacher_id]['lab']
        )
    
    # Check for violations
    violations = []
    compliant_teachers = []
    
    print(f"{'Teacher ID':<12} {'Name':<25} {'Theory':<8} {'Lab':<8} {'Total':<8} {'Status':<15}")
    print("-" * 85)
    
    for teacher_id, hours in teacher_hours.items():
        # Get teacher name from the schedule
        teacher_row = df[df['teacher_id'] == teacher_id].iloc[0]
        teacher_name = f"{teacher_row['first_name']} {teacher_row['last_name']}".strip()
        
        theory_hours = hours['theory']
        lab_hours = hours['lab']
        total_hours = hours['total']
        
        if total_hours > 21:
            status = f"VIOLATION (+{total_hours-21})"
            violations.append({
                'teacher_id': teacher_id,
                'name': teacher_name,
                'total_hours': total_hours,
                'excess': total_hours - 21
            })
        else:
            status = "COMPLIANT"
            compliant_teachers.append(teacher_id)
        
        print(f"{teacher_id:<12} {teacher_name[:24]:<25} {theory_hours:<8} {lab_hours:<8} {total_hours:<8} {status:<15}")
    
    print("-" * 85)
    print(f"\n📊 CONSTRAINT VERIFICATION RESULTS:")
    print(f"✅ Compliant teachers: {len(compliant_teachers)}")
    print(f"❌ Violation count: {len(violations)}")
    
    if violations:
        print(f"\n🚨 21-HOUR CONSTRAINT VIOLATIONS:")
        for v in violations:
            print(f"  • {v['name']} (ID: {v['teacher_id']}): {v['total_hours']} hours (+{v['excess']} over limit)")
        print(f"\n⚠️  CONSTRAINT ENFORCEMENT FAILED!")
        return False
    else:
        print(f"\n✅ ALL TEACHERS COMPLY WITH 21-HOUR CONSTRAINT!")
        print(f"   Maximum hours assigned: {max(h['total'] for h in teacher_hours.values())}")
        print(f"   Average hours assigned: {sum(h['total'] for h in teacher_hours.values()) / len(teacher_hours):.1f}")
        return True

if __name__ == "__main__":
    verify_21_hour_constraint() 