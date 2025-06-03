#!/usr/bin/env python3
import os
import sys
import argparse
from src.utils.validate_scheduler_output import validate_scheduler_output
from src.utils.fix_combinations import fix_course_combinations

def main():
    """Check and fix course combinations in an existing timetable."""
    parser = argparse.ArgumentParser(
        description='Check and fix course combinations in a timetable'
    )
    parser.add_argument(
        '--schedule-dir', required=True,
        help='Directory containing the timetable schedule files'
    )
    parser.add_argument(
        '--fix', action='store_true',
        help='Attempt to fix combination issues if validation fails'
    )
    parser.add_argument(
        '--student-count', type=int, default=700,
        help='Number of students to accommodate (default: 700)'
    )
    
    args = parser.parse_args()
    
    # Check for schedule file
    schedule_file = os.path.join(args.schedule_dir, 'macroblock_schedule.csv')
    if not os.path.exists(schedule_file):
        print(f"Error: Schedule file not found at {schedule_file}")
        return 1
    
    print(f"Checking timetable for {args.student_count} students...")
    
    # Validate the combinations
    validation_result = validate_scheduler_output(
        args.schedule_dir, student_count=args.student_count
    )
    
    if validation_result:
        print("✅ VALIDATION PASSED")
        return 0
    else:
        print("❌ VALIDATION FAILED")
        
        # Try to fix if requested
        if args.fix:
            print("Attempting to fix issues...")
            fix_success = fix_course_combinations(
                schedule_file, args.schedule_dir, 
                semester=5, student_count=args.student_count
            )
            
            return 0 if fix_success else 1
        else:
            print("Run with --fix to attempt automatic fixes")
            return 1

if __name__ == "__main__":
    sys.exit(main()) 