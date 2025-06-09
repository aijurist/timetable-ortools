#!/usr/bin/env python3
"""
Command script to verify group overlaps in theory scheduling.
"""

import os
import sys

# Add parent directory to path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

from src.data_analytics.verify_group_overlaps import verify_group_overlaps


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Verify group overlaps in theory scheduling.')
    parser.add_argument('--schedule-file', type=str, help='Path to theory schedule CSV or JSON file')
    
    args = parser.parse_args()
    
    if not args.schedule_file:
        # Try to find the latest theory schedule file
        output_dir = os.path.join(parent_dir, 'output')
        if os.path.exists(output_dir):
            output_dirs = [d for d in os.listdir(output_dir) if d.startswith('theory_schedule_')]
            if output_dirs:
                latest_dir = max(output_dirs)
                schedule_file = os.path.join(output_dir, latest_dir, 'theory_schedule.csv')
                print(f"Using latest theory schedule: {schedule_file}")
            else:
                print("Error: No schedule file specified and no theory schedule found in output directory")
                sys.exit(1)
        else:
            print("Error: Output directory not found")
            sys.exit(1)
    else:
        schedule_file = args.schedule_file
    
    success = verify_group_overlaps(schedule_file)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main() 