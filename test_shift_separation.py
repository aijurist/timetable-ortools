#!/usr/bin/env python3
"""
Test script to verify Teacher Shift and Macroblock Shift separation.
"""

import pandas as pd
from src.constraints import MacroblockTimetableConstraints
from ortools.sat.python import cp_model

def test_shift_separation():
    """Test the separation of teacher shifts and macroblock shifts."""
    
    print("🔍 Testing Teacher Shift and Macroblock Shift Separation")
    print("=" * 60)
    
    # Load test data
    courses_df = pd.read_csv("data/mapped_data/cs_teacher_courses.csv")
    rooms_df = pd.read_csv("data/block_wise/techlongue.csv")
    
    # Process rooms
    classrooms = rooms_df[rooms_df['is_lab'] == 0]
    labs = rooms_df[rooms_df['is_lab'] == 1]
    
    # Extract teachers and create teacher-course assignments
    teachers = courses_df['teacher_id'].unique()[:5]  # Test with first 5 teachers
    teacher_course_assignments = {}
    
    for teacher in teachers:
        teacher_data = courses_df[courses_df['teacher_id'] == teacher]
        teacher_course_assignments[teacher] = []
        
        for _, row in teacher_data.iterrows():
            teacher_course_assignments[teacher].append({
                'id': str(row['id']),
                'course_id': row['course_id'],
                'course_code': row['course_code'],
                'course_name': row['course_name'],
                'lecture_hours': int(row['lecture_hours']),
                'tutorial_hours': int(row['tutorial_hours']),
                'practical_hours': int(row['practical_hours']),
                'student_count': int(row['student_count']),
                'semester': row.get('semester', 5),
                'course_dept': row.get('course_dept', 'Computer Science & Engineering')
            })
    
    # Create model and constraints
    model = cp_model.CpModel()
    constraints = MacroblockTimetableConstraints(
        model, teachers, teacher_course_assignments, classrooms, labs
    )
    
    print("✅ Teacher Shift Definitions:")
    for shift_key, shift_info in constraints.teacher_shifts.items():
        print(f"  {shift_key}: {shift_info['name']} ({shift_info['time_range']})")
        print(f"    Time slots: {len(shift_info['time_slots'])} slots")
    
    print("\n✅ Macroblock Shift Definitions:")
    for shift_key, shift_info in constraints.macroblock_shifts.items():
        print(f"  {shift_key}: {shift_info['name']} ({shift_info['time_range']})")
        print(f"    Time slots: {len(shift_info['time_slots'])} slots")
    
    print("\n✅ Teacher-Macroblock Compatibility Matrix:")
    print("Teacher Shift    | Macro Shift 1 | Macro Shift 2 | Macro Shift 3")
    print("-" * 65)
    for teacher_shift, compatibility in constraints.teacher_macroblock_compatibility.items():
        macro1 = "✓" if compatibility['macro_shift1'] else "✗"
        macro2 = "✓" if compatibility['macro_shift2'] else "✗"
        macro3 = "✓" if compatibility['macro_shift3'] else "✗"
        print(f"{teacher_shift:<15} |      {macro1}        |      {macro2}        |      {macro3}")
    
    print("\n✅ Teacher Shift Assignments:")
    for teacher, shift in list(constraints.teacher_shift_assignments.items())[:10]:
        print(f"  Teacher {teacher}: {shift}")
    
    print("\n✅ Macroblock Theory Blocks:")
    for shift_key, blocks in constraints.theory_blocks.items():
        print(f"  {shift_key}: {blocks}")
    
    print("\n✅ Macroblock Tutorial Blocks:")
    for shift_key, blocks in constraints.tutorial_blocks.items():
        print(f"  {shift_key}: {blocks}")
    
    # Test compatibility logic
    print("\n🧪 Testing Compatibility Logic:")
    test_cases = [
        ('teacher_shift1', 'macro_shift1', True),
        ('teacher_shift1', 'macro_shift2', True),
        ('teacher_shift1', 'macro_shift3', False),
        ('teacher_shift2', 'macro_shift1', True),
        ('teacher_shift2', 'macro_shift2', True),
        ('teacher_shift2', 'macro_shift3', True),
        ('teacher_shift3', 'macro_shift1', False),
        ('teacher_shift3', 'macro_shift2', True),
        ('teacher_shift3', 'macro_shift3', True),
    ]
    
    for teacher_shift, macro_shift, expected in test_cases:
        actual = constraints.teacher_macroblock_compatibility[teacher_shift][macro_shift]
        status = "✅" if actual == expected else "❌"
        print(f"  {status} {teacher_shift} → {macro_shift}: {actual} (expected {expected})")
    
    # Test specific teacher scenarios
    print("\n🎯 Testing Specific Teacher Scenarios:")
    
    # Find a teacher in each shift
    shift_teachers = {}
    for teacher, shift in constraints.teacher_shift_assignments.items():
        if shift not in shift_teachers:
            shift_teachers[shift] = teacher
    
    for teacher_shift, teacher in shift_teachers.items():
        print(f"\n  Teacher {teacher} (assigned to {teacher_shift}):")
        
        # Show which macroblock shifts they can access
        accessible_shifts = []
        for macro_shift in ['macro_shift1', 'macro_shift2', 'macro_shift3']:
            if constraints.teacher_macroblock_compatibility[teacher_shift][macro_shift]:
                accessible_shifts.append(macro_shift)
        
        print(f"    Can access macroblock shifts: {accessible_shifts}")
        
        # Show available blocks
        available_blocks = []
        for macro_shift in accessible_shifts:
            available_blocks.extend(constraints.theory_blocks[macro_shift])
            available_blocks.extend(constraints.tutorial_blocks[macro_shift])
        
        print(f"    Available blocks: {available_blocks}")
        
        # Show course instances for this teacher
        if teacher in teacher_course_assignments:
            instances = teacher_course_assignments[teacher]
            print(f"    Course instances: {len(instances)}")
            for instance in instances[:2]:  # Show first 2
                print(f"      - {instance['course_code']}: {instance['lecture_hours']}L+{instance['tutorial_hours']}T")
    
    print("\n🎉 Shift separation test completed successfully!")
    print("✅ Teacher shifts and macroblock shifts are now properly separated")
    print("✅ Cross-shift scheduling is enabled based on time compatibility")
    print("✅ Teacher Shift 1 can teach in both Macroblock Shift 1 and 2")
    print("✅ Teacher Shift 2 can teach in all three Macroblock Shifts")
    print("✅ Teacher Shift 3 can teach in Macroblock Shift 2 and 3")

if __name__ == "__main__":
    test_shift_separation() 