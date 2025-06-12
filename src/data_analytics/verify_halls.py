#!/usr/bin/env python3
"""
Hall's Theorem Verification Script

This script verifies that course groups satisfy Hall's theorem, which is necessary
for ensuring optimal student course choices.

Hall's theorem states that for any subset of courses S, the number of
unique teachers assigned to courses in S must be at least |S|.
"""

import os
import json
import argparse
import pandas as pd
from itertools import combinations
from collections import defaultdict

def load_schedule_data(csv_file):
    """Load schedule data from CSV file."""
    if csv_file is None:
        print("Error: No schedule file specified")
        return None
        
    if not os.path.exists(csv_file):
        print(f"Error: Schedule file not found at {csv_file}")
        return None
    
    try:
        df = pd.read_csv(csv_file)
        print(f"Loaded {len(df)} schedule records")
        return df
    except Exception as e:
        print(f"Error loading schedule data: {e}")
        return None

def extract_groups(df):
    """Extract groups from schedule data."""
    groups = defaultdict(lambda: {'courses': set(), 'course_teacher_matrix': defaultdict(set)})
    
    for _, row in df.iterrows():
        group_name = row.get('group_name', 'Unknown')
        course_code = row.get('course_code', 'Unknown')
        teacher_id = row.get('teacher_id', 'Unknown')
        
        groups[group_name]['courses'].add(course_code)
        groups[group_name]['course_teacher_matrix'][course_code].add(teacher_id)
    
    print(f"Extracted {len(groups)} unique groups")
    return groups

def check_halls_theorem(group_data):
    """
    Check if a group satisfies Hall's theorem.
    
    Returns:
        dict: Result with condition_satisfied and violations
    """
    courses = group_data['courses']
    course_teacher_matrix = group_data['course_teacher_matrix']
    
    violations = []
    
    # Check all non-empty subsets of courses
    for r in range(1, len(courses) + 1):
        for course_subset in combinations(courses, r):
            # Find all teachers assigned to any course in this subset
            neighbor_teachers = set()
            for course in course_subset:
                neighbor_teachers.update(course_teacher_matrix.get(course, set()))
            
            # Hall's condition: |N(S)| >= |S|
            if len(neighbor_teachers) < len(course_subset):
                violations.append({
                    'subset': list(course_subset),
                    'subset_size': len(course_subset),
                    'teacher_count': len(neighbor_teachers),
                    'teachers': list(neighbor_teachers)
                })
    
    return {
        'condition_satisfied': len(violations) == 0,
        'violations': violations
    }

def verify_all_groups(groups):
    """Verify all groups satisfy Hall's theorem."""
    satisfied_count = 0
    violation_count = 0
    total_violations = 0
    
    print("\nHALL'S THEOREM VERIFICATION RESULTS:")
    print("=" * 60)
    
    for group_name, group_data in sorted(groups.items()):
        result = check_halls_theorem(group_data)
        
        if result['condition_satisfied']:
            satisfied_count += 1
            print(f"✅ Group {group_name}: SATISFIED Hall's theorem")
        else:
            violation_count += 1
            total_violations += len(result['violations'])
            print(f"❌ Group {group_name}: VIOLATED Hall's theorem with {len(result['violations'])} violations")
            
            # Print first 3 violations
            for i, violation in enumerate(result['violations'][:3]):
                print(f"  Violation {i+1}: Courses {', '.join(violation['subset'])} have only {violation['teacher_count']} teachers")
                print(f"    Need at least: {violation['subset_size']} teachers")
            
            if len(result['violations']) > 3:
                print(f"  (... {len(result['violations']) - 3} more violations ...)")
    
    print("\nSUMMARY:")
    print(f"  Total Groups: {len(groups)}")
    print(f"  Groups Satisfying Hall's Theorem: {satisfied_count}/{len(groups)} ({(satisfied_count/len(groups))*100:.1f}%)")
    print(f"  Groups Violating Hall's Theorem: {violation_count}/{len(groups)}")
    print(f"  Total Violations: {total_violations}")
    
    return satisfied_count == len(groups)

def analyze_student_choice(groups):
    """Analyze student choice implications based on Hall's theorem satisfaction."""
    print("\nSTUDENT CHOICE ANALYSIS:")
    print("=" * 60)
    
    # Calculate choice metrics
    groups_with_violations = []
    for group_name, group_data in groups.items():
        result = check_halls_theorem(group_data)
        if not result['condition_satisfied']:
            groups_with_violations.append((group_name, result['violations']))
    
    if not groups_with_violations:
        print("✅ OPTIMAL STUDENT CHOICE: All groups satisfy Hall's theorem")
        print("  Every student has optimal course choices across all groups")
        choice_quality = "EXCELLENT"
    elif len(groups_with_violations) <= len(groups) * 0.25:
        print("⚠️ GOOD STUDENT CHOICE: Most groups satisfy Hall's theorem")
        print(f"  {len(groups_with_violations)}/{len(groups)} groups have Hall's theorem violations")
        print("  Most students will have good course choices, with some limitations")
        choice_quality = "GOOD"
    elif len(groups_with_violations) <= len(groups) * 0.5:
        print("⚠️ FAIR STUDENT CHOICE: Only some groups satisfy Hall's theorem")
        print(f"  {len(groups_with_violations)}/{len(groups)} groups have Hall's theorem violations")
        print("  Students may face limited choices in some groups")
        choice_quality = "FAIR"
    else:
        print("❌ POOR STUDENT CHOICE: Many groups violate Hall's theorem")
        print(f"  {len(groups_with_violations)}/{len(groups)} groups have Hall's theorem violations")
        print("  Students will face significant limitations in course choices")
        choice_quality = "POOR"
    
    # Analyze bottleneck courses in violating groups
    if groups_with_violations:
        print("\nBOTTLENECK ANALYSIS:")
        
        bottleneck_courses = defaultdict(int)
        for group_name, violations in groups_with_violations:
            for violation in violations:
                for course in violation['subset']:
                    bottleneck_courses[course] += 1
        
        # Sort courses by violation frequency
        bottleneck_courses = sorted(bottleneck_courses.items(), key=lambda x: x[1], reverse=True)
        
        print("  Most problematic courses (appearing in multiple violations):")
        for course, count in bottleneck_courses[:5]:
            print(f"  • {course}: Appears in {count} violations")
        
        # Recommendation
        print("\nRECOMMENDATION:")
        print("  To improve student choice, focus on adding more teachers to these courses")
        print("  or redistribute teachers more evenly across groups")
    
    return choice_quality

def main():
    parser = argparse.ArgumentParser(description='Verify Hall\'s theorem in timetable schedule')
    parser.add_argument('--schedule', type=str, help='Path to schedule CSV file')
    parser.add_argument('--output-dir', type=str, help='Output directory for verification results')
    args = parser.parse_args()
    
    # Default to latest output directory if not specified
    if not args.output_dir:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        output_dir = os.path.join(base_dir, 'output')
        
        # Find most recent output directory
        if os.path.exists(output_dir):
            output_dirs = [d for d in os.listdir(output_dir) if d.startswith('schedule_')]
            if output_dirs:
                latest_dir = sorted(output_dirs)[-1]
                args.output_dir = os.path.join(output_dir, latest_dir)
                print(f"Using most recent output directory: {args.output_dir}")
            else:
                print(f"No schedule output directories found in {output_dir}")
        else:
            print(f"Output directory not found: {output_dir}")
    
    # Use schedule.csv in output directory if not specified
    if not args.schedule:
        if args.output_dir and os.path.exists(args.output_dir):
            args.schedule = os.path.join(args.output_dir, 'schedule.csv')
            print(f"Using schedule file: {args.schedule}")
        else:
            print("Error: No schedule file specified and no valid output directory found")
            print("Usage:")
            print("  python verify_halls.py --schedule path/to/schedule.csv")
            print("  or run from timetable_scheduler directory after generating a schedule")
            return 1
    
    # Verify the schedule file exists
    if not os.path.exists(args.schedule):
        print(f"Error: Schedule file not found: {args.schedule}")
        print("Please run the timetable scheduler first to generate a schedule.csv file")
        return 1
    
    # Load schedule data
    df = load_schedule_data(args.schedule)
    if df is None:
        return 1
    
    # Extract groups
    groups = extract_groups(df)
    
    if not groups:
        print("Error: No groups found in schedule data")
        return 1
    
    # Verify Hall's theorem for all groups
    all_satisfied = verify_all_groups(groups)
    
    # Analyze student choice implications
    choice_quality = analyze_student_choice(groups)
    
    # Save verification results if output directory specified
    if args.output_dir and os.path.exists(args.output_dir):
        results = {
            'all_satisfied': all_satisfied,
            'choice_quality': choice_quality,
            'groups_checked': len(groups),
            'groups_satisfied': sum(1 for g in groups.values() if check_halls_theorem(g)['condition_satisfied']),
            'timestamp': pd.Timestamp.now().isoformat()
        }
        
        results_file = os.path.join(args.output_dir, 'halls_theorem_verification.json')
        with open(results_file, 'w') as f:
            json.dump(results, f, indent=2)
        
        print(f"\nResults saved to: {results_file}")
    
    # Return code based on verification result
    return 0 if all_satisfied else 1

if __name__ == '__main__':
    exit(main()) 