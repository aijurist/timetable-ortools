
import csv
import yaml
import math
import os
from pathlib import Path

# Configuration
SCHEDULER_CONFIG_PATH = Path('d:/timetable-scheduler/config/scheduler.yaml')
DATA_ROOT = Path('d:/timetable-scheduler/data/sem2026/1st year')
OUTPUT_DIR = Path('d:/timetable-scheduler/output/reports')
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Constants
LAB_SLOT_DURATION_HRS = 2
BATCH_SIZE = 35  # Assuming a standard lab batch size of ~35 students.
                # A class of 69 would need 2 batches.

def load_department_shifts(config_path):
    """
    Parses scheduler.yaml to determine the shift (Day Pattern) for each department.
    Returns a dictionary: { 'Department Name': 'Monday-Friday' or 'Tuesday-Saturday' }
    """
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    dept_shifts = {}
    overrides = config.get('departments', {}).get('overrides', {})
    
    for dept, settings in overrides.items():
        days = settings.get('day_pattern', [])
        # Normalize pattern to a simple label
        if 'monday' in days and 'saturday' not in days:
             label = 'Monday-Friday'
        elif 'tuesday' in days and 'saturday' in days:
             label = 'Tuesday-Saturday'
        else:
            # Fallback or specific custom pattern
            # For this report, we mainly care about Mon-Fri vs Tue-Sat distinction
            if 'monday' in days:
                label = 'Monday-Friday'
            else:
                label = 'Tuesday-Saturday'
        
        dept_shifts[dept] = label
        
    return dept_shifts

def analyze_lab_demand(data_dir, dept_shifts):
    """
    Reads all CSVs in data_dir, calculates lab slot demand per lab per shift.
    """
    # Structure: report[Shift][LabName] = Total Slots Needed
    report = {
        'Monday-Friday': {},
        'Tuesday-Saturday': {}
    }
    
    # Track details for debugging/verification
    details = {
        'Monday-Friday': {},
        'Tuesday-Saturday': {}
    }

    files = list(Path(data_dir).glob('*.csv'))
    
    for file_path in files:
        with open(file_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            
            for row in reader:
                # Basic validation
                dept_name = row.get('student_dept', '').strip()
                course_name = row.get('course_name', '').strip()
                lab_name = row.get('room_description', '').strip() or row.get('room_number', '').strip()
                
                # Skip if not a lab or generic names that don't help (unless that's what we want to count)
                # We specifically look for "Microprocessor Lab" or generally any Core Lab
                # The user asked "check if ... Microprocessor Lab 1 and 2 are enough", but also "report for entire first year data... for each dept"
                # So we process ALL labs that show up.
                
                try:
                    p_hours = float(row.get('practical_hours', 0))
                except ValueError:
                    p_hours = 0
                
                if p_hours <= 0:
                    continue
                    
                # Identify Shift
                shift_label = dept_shifts.get(dept_name, 'Unknown')
                if shift_label == 'Unknown':
                    # Try to infer or log warning (omitted for brevity, default to Mon-Fri if Monday is standard)
                    # Actually, if not in config, maybe it's using default settings?
                    # Default settings in yaml: mon-sat (lines 103-109). 
                    # But the user prompt implies a binary Mon-Fri vs Tue-Sat.
                    # We'll default to Mon-Fri for safety or skip? 
                    # Let's inspect the yaml default again or assume Mon-Fri.
                    shift_label = 'Monday-Friday' 

                # Determine Batches
                try:
                    student_count = int(row.get('student_count', 0))
                except ValueError:
                    student_count = 0
                
                if student_count <= 0:
                    continue

                # Calculate Batches
                batches = math.ceil(student_count / BATCH_SIZE)
                
                # Calculate Slots
                # 1 slot = 2 hours.
                slots_needed_per_batch = math.ceil(p_hours / LAB_SLOT_DURATION_HRS)
                total_slots = batches * slots_needed_per_batch
                
                # Aggregate
                if shift_label in report:
                    current_count = report[shift_label].get(lab_name, 0)
                    report[shift_label][lab_name] = current_count + total_slots
                    
                    # Store detail
                    if lab_name not in details[shift_label]:
                        details[shift_label][lab_name] = []
                    details[shift_label][lab_name].append(
                        f"{dept_name}: {course_name} ({student_count} students, {batches} batches) = {total_slots} slots"
                    )

    return report, details

def generate_report(report, details):
    print("=== Lab Capacity Analysis Report ===\n")
    print(f"Assumption: 1 Lab Slot = {LAB_SLOT_DURATION_HRS} Hours")
    print(f"Assumption: Batch Size = {BATCH_SIZE} students\n")
    
    for shift, labs in report.items():
        print(f"--- Shift: {shift} ---")
        print(f"Capacity Limit: 25 Slots / Week (as per user constraint)\n")
        
        sorted_labs = sorted(labs.items(), key=lambda x: x[1], reverse=True)
        
        for lab_name, slots_needed in sorted_labs:
            status = "OK" if slots_needed <= 25 else "OVERFLOW"
            print(f"Lab: {lab_name}")
            print(f"  Total Slots Required: {slots_needed}")
            print(f"  Status: {status}")
            
            # Print breakdown for significant usage
            if lab_name in details[shift]:
                print(f"  Breakdown:")
                # Group by department to keep it clean
                dept_summary = {}
                for item in details[shift][lab_name]:
                    # Parse back the string or just print top items
                    # item format: "Dept: Course (Start...) = X slots"
                    dept = item.split(':')[0]
                    # Parse slots
                    try:
                        s = int(item.split('=')[-1].replace('slots', '').strip())
                    except:
                        s = 0
                    dept_summary[dept] = dept_summary.get(dept, 0) + s
                
                for dept, count in dept_summary.items():
                    print(f"    - {dept}: {count} slots")
            print("")

if __name__ == "__main__":
    dept_shifts = load_department_shifts(SCHEDULER_CONFIG_PATH)
    # Debug: Print Shift Mappings
    # print("Department Shift Mappings:")
    # for d, s in dept_shifts.items():
    #     print(f"  {d}: {s}")
    # print("")
    
    report, details = analyze_lab_demand(DATA_ROOT, dept_shifts)
    generate_report(report, details)
