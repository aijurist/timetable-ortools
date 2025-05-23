import pandas as pd
import os
from collections import defaultdict

def verify_intelligent_lab_batching():
    """Verify that intelligent lab capacity allocation is working correctly."""
    
    # Find the latest schedule
    output_dir = "output"
    folders = [f for f in os.listdir(output_dir) if f.startswith("schedule_")]
    latest_folder = max(folders) if folders else None
    
    if not latest_folder:
        print("No schedule found!")
        return
    
    schedule_file = os.path.join(output_dir, latest_folder, "schedule.csv")
    df = pd.read_csv(schedule_file)
    
    print("🔍 INTELLIGENT LAB CAPACITY VERIFICATION")
    print("=" * 60)
    
    # Filter lab assignments only
    lab_data = df[df['slot_type'] == 'Lab'].copy()
    
    if lab_data.empty:
        print("No lab assignments found!")
        return
    
    # Group by course instance to analyze batching
    instance_groups = lab_data.groupby(['teacher_id', 'course_instance_id', 'course_code'])
    
    print(f"{'Course':<15} {'Teacher':<8} {'Students':<9} {'Lab Cap':<8} {'Batches':<8} {'Slots':<6} {'Status':<20}")
    print("-" * 85)
    
    intelligent_cases = 0
    total_cases = 0
    slot_savings = 0
    
    for (teacher_id, instance_id, course_code), group in instance_groups:
        total_cases += 1
        
        # Get course details
        first_row = group.iloc[0]
        total_students = first_row['total_students']
        room_capacity = first_row['room_capacity']
        intelligent_batching = first_row.get('intelligent_batching', 'No')
        
        # Count unique batches and total slots
        unique_batches = group['batch'].nunique()
        total_slots = len(group)
        
        # Determine expected slots with traditional batching
        if total_students > 35:
            traditional_batches = (total_students + 34) // 35
            practical_hours = 2  # Assuming 2 practical hours (most common)
            expected_traditional_slots = traditional_batches * ((practical_hours + 1) // 2)
        else:
            expected_traditional_slots = (2 + 1) // 2  # Base case
        
        # Status determination
        status = "Standard"
        if total_students > 60 and room_capacity >= 70:
            if unique_batches == 1 and total_slots < expected_traditional_slots:
                status = "✅ Intelligent (Optimized)"
                intelligent_cases += 1
                slot_savings += (expected_traditional_slots - total_slots)
            elif room_capacity >= total_students:
                status = "✅ Large Lab Used"
                intelligent_cases += 1
                if total_slots < expected_traditional_slots:
                    slot_savings += (expected_traditional_slots - total_slots)
            else:
                status = "❌ Could Optimize"
        elif total_students <= 35:
            status = "Standard (Small)"
        
        print(f"{course_code:<15} {teacher_id:<8} {total_students:<9} {room_capacity:<8} {unique_batches:<8} {total_slots:<6} {status:<20}")
    
    print("-" * 85)
    print(f"\n📊 OPTIMIZATION RESULTS:")
    print(f"✅ Courses using intelligent allocation: {intelligent_cases}/{total_cases}")
    print(f"💡 Total lab slots saved: {slot_savings}")
    print(f"📈 Optimization rate: {(intelligent_cases/total_cases)*100:.1f}%")
    
    if slot_savings > 0:
        print(f"\n🎉 SUCCESS: Intelligent lab capacity allocation is working!")
        print(f"   Lab utilization optimized by reducing {slot_savings} unnecessary slot assignments")
    
    # Show capacity distribution
    print(f"\n🏗️  LAB CAPACITY USAGE:")
    capacity_usage = lab_data.groupby('room_capacity').agg({
        'course_instance_id': 'nunique',
        'total_students': 'mean'
    }).round(1)
    capacity_usage.columns = ['Instances_Assigned', 'Avg_Students']
    print(capacity_usage)
    
    # Show intelligent batching cases specifically
    intelligent_data = lab_data[lab_data.get('intelligent_batching', 'No') == 'Yes']
    if not intelligent_data.empty:
        print(f"\n✨ INTELLIGENT BATCHING EXAMPLES:")
        examples = intelligent_data.groupby(['course_code', 'teacher_id']).first()[
            ['total_students', 'room_capacity', 'batch', 'batch_students']
        ].head(5)
        print(examples)
    
    return intelligent_cases > 0

if __name__ == "__main__":
    verify_intelligent_lab_batching() 