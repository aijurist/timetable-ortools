#!/usr/bin/env python3
"""
Run the verification of lecture and tutorial hours from theory scheduling output.
"""

import os
import sys

# Add parent directory to path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

from src.data_analytics.verify_lecture_tutorial_hours import verify_lecture_tutorial_hours

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Verify lecture and tutorial hours from theory scheduling output.')
    parser.add_argument('--theory-schedule', type=str, help='Path to theory schedule CSV or JSON file')
    parser.add_argument('--course-file', type=str, default='data/cse.csv', help='Path to course requirements CSV file')
    
    args = parser.parse_args()
    
    # Run the verification
    success = verify_lecture_tutorial_hours(args.theory_schedule, args.course_file)
    
    # Exit with appropriate status code
    sys.exit(0 if success else 1) 