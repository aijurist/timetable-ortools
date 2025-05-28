#!/usr/bin/env python3
"""
Runner script for the Lab Scheduler
====================================

This script runs the lab scheduler which:
1. Reads existing theory schedules
2. Adds lab allocations with proper time structure
3. Ensures no conflicts between theory and lab sessions
4. Outputs combined theory + lab schedules

Usage:
    python run_lab_scheduler.py

Requirements:
    - Must have run theory scheduling first (main.py)
    - Lab rooms must be available in the rooms CSV file
    - Courses with practical_hours > 0 will get lab allocation
"""

import sys
import os

# Add the current directory to Python path so we can import lab_scheduler
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lab_scheduler import main

if __name__ == "__main__":
    print("=" * 80)
    print("LAB SCHEDULER FOR COMPUTER SCIENCE DEPARTMENT")
    print("=" * 80)
    print()
    print("This will:")
    print("• Read your existing theory schedule")
    print("• Add lab allocations for courses with practical hours")
    print("• Use lab session structure: L1 (8:00-9:40), L2 (9:50-11:30), etc.")
    print("• Ensure no conflicts between theory and lab sessions")
    print("• Generate combined theory + lab schedule")
    print()
    input("Press Enter to continue...")
    print()
    
    # Run the lab scheduler
    main() 