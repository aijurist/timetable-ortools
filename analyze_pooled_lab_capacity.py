
import csv
import yaml
import math
import os
from pathlib import Path
from collections import defaultdict

# Configuration
SCHEDULER_CONFIG_PATH = Path('d:/timetable-scheduler/config/scheduler.yaml')
DATA_ROOT = Path('d:/timetable-scheduler/data/sem2026/1st year')

# Constants
LAB_SLOT_DURATION_HRS = 2
BATCH_SIZE = 35
SLOTS_PER_DAY = 5  # Typical max slots per day for labs

# Resource Pools (Combine these rooms into one capacity bucket)
RESOURCE_POOLS = {
    'Microprocessor Lab Pool': {'Microprocessor Lab-1', 'Microprocessor Lab-2'}
    # Add others if needed
}

def load_department_shifts(config_path):
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    dept_shifts = {}
    overrides = config.get('departments', {}).get('overrides', {})
    
    for dept, settings in overrides.items():
        days = settings.get('day_pattern', [])
        if 'monday' in days and 'saturday' not in days:
             days_list = ['monday', 'tuesday', 'wed', 'thur', 'fri']
        elif 'tuesday' in days and 'saturday' in days:
             days_list = ['tuesday', 'wed', 'thur', 'fri', 'saturday']
        else:
             days_list = days # Custom
        
        dept_shifts[dept] = days_list
        
    return dept_shifts

def analyze_pooled_capacity(data_dir, dept_shifts):
    # Load: Day -> PoolName -> SlotsRequired
    daily_load = defaultdict(lambda: defaultdict(float))
    
    files = list(Path(data_dir).glob('*.csv'))
    
    for file_path in files:
        with open(file_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                dept_name = row.get('student_dept', '').strip()
                course = row.get('course_name', '').strip()
                lab_name = row.get('room_description', '').strip() or row.get('room_number', '').strip()
                
                try:
                    p_hours = float(row.get('practical_hours', 0))
                    student_count = int(row.get('student_count', 0))
                except ValueError:
                    continue
                
                if p_hours <= 0 or student_count <= 0:
                    continue

                # Identify Pool
                pool_name = lab_name
                for p_name, members in RESOURCE_POOLS.items():
                    if lab_name in members:
                        pool_name = p_name
                        break
                
                # Check if we care about this lab (only analyze pools + overflows from before)
                # Let's analyze everything for completeness
                
                # Calculate Weekly Slots
                batches = math.ceil(student_count / BATCH_SIZE)
                slots_needed_per_batch = math.ceil(p_hours / LAB_SLOT_DURATION_HRS)
                total_weekly_slots = batches * slots_needed_per_batch
                
                # Distribute over working days
                working_days = dept_shifts.get(dept_name, ['monday', 'tuesday', 'wed', 'thur', 'fri'])
                num_days = len(working_days)
                if num_days == 0: continue
                
                daily_demand = total_weekly_slots / num_days
                
                for day in working_days:
                    daily_load[day][pool_name] += daily_demand
                    
    return daily_load

def generate_day_report(daily_load):
    print("=== Pooled Resource Day-wise Analysis ===\n")
    
    # Define Days Order
    days_order = ['monday', 'tuesday', 'wed', 'thur', 'fri', 'saturday']
    
    # Identify all known pools
    all_pools = set()
    for day in daily_load:
        all_pools.update(daily_load[day].keys())
        
    # Filter for Microprocessor Lab Pool primarily
    target_pools = ['Microprocessor Lab Pool', 'Engineering Practices Lab (Electrical)'] 
    # Check if 'Engineering Practices Lab (Electrical)' is in all_pools, strictly it's not a pool but a room name
    # But analyze_pooled_capacity uses lab_name as pool_name if not in RESOURCE_POOLS map.
    
    for pool in target_pools:
        # Determine Capacity
        if pool == 'Microprocessor Lab Pool':
            room_count = 2
        else:
            room_count = 1 
            
        daily_capacity = room_count * SLOTS_PER_DAY
        
        print(f"Resource: {pool} (Rooms: {room_count}, Daily Cap: {daily_capacity} slots)")
        
        for day in days_order:
            load = daily_load[day].get(pool, 0)
            status = "OK" if load <= daily_capacity else "OVERLOAD"
            print(f"  {day.capitalize():<10}: Demand = {load:.2f} slots | {status}")
        print("")

if __name__ == "__main__":
    dept_shifts = load_department_shifts(SCHEDULER_CONFIG_PATH)
    daily_load = analyze_pooled_capacity(DATA_ROOT, dept_shifts)
    generate_day_report(daily_load)
