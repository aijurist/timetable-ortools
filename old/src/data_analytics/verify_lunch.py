#!/usr/bin/env python3
"""
Test lunch break violations in the generated schedule
"""

import pandas as pd
import os

def test_lunch_break_violations():
    """Test if there are any theory sessions scheduled during lunch break times."""
    
    try:
        # Find the latest combined schedule directory
        output_dir = 'output'
        combined_dirs = [d for d in os.listdir(output_dir) if d.startswith('combined_schedule_')]
        if not combined_dirs:
            print("No combined schedule directories found!")
            return
        
        latest_dir = max(combined_dirs)
        theory_csv = f'output/{latest_dir}/combined_theory_schedule.csv'
        
        if not os.path.exists(theory_csv):
            print(f"Theory schedule file not found: {theory_csv}")
            return
        
        # Load the theory schedule
        theory_df = pd.read_csv(theory_csv)
        
        print("=== Lunch Break Violation Analysis ===")
        print(f"Total theory sessions: {len(theory_df)}")
        print(f"Schedule file: {theory_csv}")
        
        # Define lunch break time slots
        lunch_break_slots = {
            3: "11:00 - 11:50",  # Early lunch
            4: "12:00 - 12:50",  # Standard lunch  
            5: "1:00 - 1:50"     # Late lunch
        }
        
        # Department lunch break assignments (from the scheduler configuration)
        department_lunch_breaks = {
            # Computer Science & Engineering departments
            'Computer Science & Engineering': 4,  # Standard lunch (12:00 - 12:50)
            'Artificial Intelligence & Data Science': 4,
            'Artificial Intelligence & Machine Learning': 4,  # Added missing department
            'Information Technology': 4,
            'Computer Science & Business Systems': 4,
            'Computer Science & Design': 4,
            'Computer Science & Cyber Security': 4,
            
            # Engineering departments
            'Electronics & Communication Engineering': 3,  # Early lunch (11:00 - 11:50)
            'Electrical & Electronics Engineering': 3,
            'Mechanical Engineering': 3,
            'Civil Engineering': 3,
            'Aeronautical Engineering': 3,  # Added missing department
            'Chemical Engineering': 3,  # Added missing department
            'Biomedical Engineering': 3,  # Added missing department
            'Biotechnology': 5,  # Late lunch (1:00 - 1:50)
            
            # Default for any department not explicitly listed
            'default': 4  # Standard lunch
        }
        
        # Check for lunch break violations
        violations = []
        
        for _, row in theory_df.iterrows():
            day = row.get('day', '')
            time_slot = row.get('time_slot', '')
            group_name = row.get('group_name', '')
            course_name = row.get('course_name', '')
            teacher_name = row.get('teacher_name', '')
            
            # Extract department from group name
            dept_name = group_name.split('_S')[0] if '_S' in group_name else "Computer Science & Engineering"
            
            # Get the lunch break slot for this department
            lunch_slot_idx = department_lunch_breaks.get(dept_name, department_lunch_breaks['default'])
            lunch_time = lunch_break_slots[lunch_slot_idx]
            
            # Check if this session is during the department's lunch break
            if time_slot == lunch_time:
                violations.append({
                    'day': day,
                    'time_slot': time_slot,
                    'department': dept_name,
                    'group': group_name,
                    'course': course_name,
                    'teacher': teacher_name,
                    'expected_lunch': lunch_time
                })
        
        if violations:
            print(f"\n❌ Found {len(violations)} lunch break violations:")
            print("=" * 80)
            for i, violation in enumerate(violations, 1):
                print(f"{i}. {violation['day'].upper()} {violation['time_slot']}")
                print(f"   Department: {violation['department']}")
                print(f"   Group: {violation['group']}")
                print(f"   Course: {violation['course']}")
                print(f"   Teacher: {violation['teacher']}")
                print(f"   Expected Lunch: {violation['expected_lunch']}")
                print()
        else:
            print("\n✅ No lunch break violations found!")
            print("🎉 Lunch break constraint is working perfectly!")
            
            # Show lunch break summary
            print("\n📋 Lunch Break Summary:")
            print("=" * 50)
            for slot_idx, time_slot in lunch_break_slots.items():
                depts = [dept for dept, slot in department_lunch_breaks.items() if slot == slot_idx]
                print(f"{time_slot} (Slot {slot_idx}): {', '.join(depts)}")
        
    except Exception as e:
        print(f"Error analyzing lunch breaks: {e}")

if __name__ == "__main__":
    test_lunch_break_violations()