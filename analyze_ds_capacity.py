
import csv
import math
from pathlib import Path
from collections import defaultdict

DATA_ROOT = Path('d:/timetable-scheduler/data/sem2026/1st year')
BATCH_SIZE = 35
LAB_SLOT_DURATION_HRS = 2

def analyze_data_structures_demand():
    print("=== Data Structures Demand Analysis ===\n")
    
    total_students = 0
    total_batches = 0
    total_slots_needed = 0 # In terms of Room-Slots (1 batch for 1 session duration)
    
    files = list(Path(DATA_ROOT).glob('*.csv'))
    
    dept_breakdown = []
    
    for file_path in files:
        if not file_path.exists(): continue
        
        with open(file_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                course = row.get('course_name', '').strip()
                if 'Data Structures' not in course:
                    continue
                
                dept = row['student_dept']
                try:
                    cnt = int(row.get('student_count', 0))
                    phours = float(row.get('practical_hours', 0))
                except:
                    continue
                    
                if cnt <= 0 or phours <= 0: continue
                
                batches = math.ceil(cnt / BATCH_SIZE)
                # Assuming 1 slot = 2 hours usually, but let's check phours
                # If phours is 4, that's 2 slots per batch per week.
                slots_per_batch = math.ceil(phours / LAB_SLOT_DURATION_HRS)
                
                required_slots = batches * slots_per_batch
                
                total_students += cnt
                total_batches += batches
                total_slots_needed += required_slots
                
                dept_breakdown.append(f"{dept:<40}: {cnt} students -> {batches} batches ({phours} hrs/wk) -> {required_slots} slots")
    
    print(f"Total Students: {total_students}")
    print(f"Total Batches: {total_batches}")
    print(f"Total Room-Slots Required: {total_slots_needed}")
    print("\n--- Breakdown ---")
    for line in dept_breakdown:
        print(line)
        
    print("\n--- Capacity Check ---")
    print(f"Given Constraint: 20 Time-Slots Available (assumed)")
    print(f"Given Capacity Factor: 7 Staff/Rooms per Session (7 parallel batches?)")
    
    # Analysis
    # If 7 batches can run at once:
    # Capacity in 'Batch-Slots' = 20 Time-Slots * 7 = 140 Batch-Slots.
    
    if total_slots_needed <= (20 * 7):
        print(f"Result: YES. (Demand {total_slots_needed} <= Capacity {20*7})")
    else:
        print(f"Result: NO. (Demand {total_slots_needed} > Capacity {20*7})")

if __name__ == "__main__":
    analyze_data_structures_demand()
