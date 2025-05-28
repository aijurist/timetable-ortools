#!/usr/bin/env python3
"""
Standalone shift constraint verification script.
Verifies teacher shift constraints on the latest generated schedule.
"""

import os
import sys
import pandas as pd
import logging
from datetime import datetime

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))
from utils.shift_verifier import ShiftVerifier

def setup_logging():
    """Setup logging configuration."""
    # Create a formatter
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # Create console handler with UTF-8 encoding
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    
    # Create file handler with UTF-8 encoding
    file_handler = logging.FileHandler(
        f"shift_verification_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log",
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    
    # Configure root logger
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    
    return logger

def find_latest_schedule():
    """Find the latest schedule file."""
    output_dir = "output"
    if not os.path.exists(output_dir):
        return None
    
    # Find latest schedule directory
    schedule_dirs = [d for d in os.listdir(output_dir) if d.startswith('macroblock_schedule_')]
    if not schedule_dirs:
        return None
    
    latest_dir = max(schedule_dirs)
    schedule_path = os.path.join(output_dir, latest_dir, 'macroblock_schedule.csv')
    
    return schedule_path if os.path.exists(schedule_path) else None

def main():
    """Main verification function with enhanced distribution analysis."""
    logger = setup_logging()
    
    try:
        # Find latest schedule
        schedule_path = find_latest_schedule()
        if not schedule_path:
            logger.error("No schedule file found")
            return
        
        logger.info(f"Loading schedule from: {schedule_path}")
        schedule_data = pd.read_csv(schedule_path)
        
        if schedule_data.empty:
            logger.error("Schedule data is empty")
            return
        
        logger.info(f"Loaded {len(schedule_data)} schedule entries")
        
        # Create enhanced shift verifier with 2,2,1 distribution pattern
        shift_verifier = ShiftVerifier(logger)
        shift_verifier.preferred_pattern = [2, 2, 1]  # 2 days S1, 2 days S2, 1 day S3
        
        # Convert DataFrame to list of dictionaries
        schedule_list = schedule_data.to_dict('records')
        
        logger.info("="*80)
        logger.info("ENHANCED SHIFT VERIFICATION WITH WEEKLY DISTRIBUTION PATTERNS")
        logger.info("="*80)
        logger.info("TARGET PATTERN: 2 days Shift1, 2 days Shift2, 1 day Shift3")
        logger.info("SMART ALLOCATION: When multiple shifts are compatible, choose based on weekly distribution goals")
        
        # Run enhanced verification
        verification_result = shift_verifier.verify_shift_constraints_with_distribution(schedule_list)
        
        # Print detailed results
        shift_verifier.print_distribution_verification_report(verification_result)
        
        # Demonstrate specific teacher analysis
        demonstrate_teacher_distribution_analysis(schedule_data, logger, shift_verifier)
        
        # Save enhanced report
        output_path = f"enhanced_shift_verification_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        shift_verifier.save_distribution_verification_report(verification_result, output_path)
        logger.info(f"Enhanced verification report saved to: {output_path}")
        
    except Exception as e:
        logger.error(f"Error during enhanced verification: {str(e)}")
        logger.exception("Detailed error information:")

def demonstrate_teacher_distribution_analysis(schedule_data, logger, shift_verifier):
    """Demonstrate distribution analysis for specific teachers."""
    logger.info("\\n" + "="*60)
    logger.info("DETAILED TEACHER DISTRIBUTION ANALYSIS")
    logger.info("="*60)
    
    # Define shift boundaries for reference
    teacher_shifts = {
        'shift1': {'name': 'Shift 1 (8:00-3:00)', 'start_slot': 0, 'end_slot': 6},
        'shift2': {'name': 'Shift 2 (10:00-5:00)', 'start_slot': 2, 'end_slot': 8},
        'shift3': {'name': 'Shift 3 (12:00-7:00)', 'start_slot': 4, 'end_slot': 10}
    }
    
    # Get a few teachers for detailed analysis
    teachers_to_analyze = schedule_data['teacher_id'].unique()[:5]  # First 5 teachers
    
    for teacher_id in teachers_to_analyze:
        teacher_schedule = schedule_data[schedule_data['teacher_id'] == teacher_id]
        if teacher_schedule.empty:
            continue
            
        logger.info(f"\\nDETAILED ANALYSIS: Teacher {teacher_id}")
        logger.info("-" * 40)
        
        days = ["tuesday", "wed", "thur", "fri", "sat"]
        
        for day in days:
            day_assignments = teacher_schedule[teacher_schedule['day'] == day]
            if day_assignments.empty:
                logger.info(f"  {day.capitalize()}: No classes")
                continue
            
            slots_used = sorted(day_assignments['slot_index'].tolist())
            min_slot = min(slots_used)
            max_slot = max(slots_used)
            
            # Check compatibility with each shift
            compatible_shifts = []
            for shift_name, shift_info in teacher_shifts.items():
                if min_slot >= shift_info['start_slot'] and max_slot <= shift_info['end_slot']:
                    compatible_shifts.append(shift_name)
            
            # Show courses and time slots
            courses = day_assignments['course_code'].tolist()
            time_slots = [f"Slot {slot}" for slot in slots_used]
            
            logger.info(f"  {day.capitalize()}: Slots {slots_used} (range: {min_slot}-{max_slot})")
            logger.info(f"    - Courses: {', '.join(courses)}")
            logger.info(f"    - Time slots: {', '.join(time_slots)}")
            
            if compatible_shifts:
                shift_names = [teacher_shifts[s]['name'] for s in compatible_shifts]
                logger.info(f"    [OK] Compatible with: {', '.join(shift_names)}")
                
                if len(compatible_shifts) > 1:
                    logger.info(f"    [FLEXIBLE] Multiple shifts available - distribution algorithm will choose optimal")
                else:
                    logger.info(f"    [FORCED] Only one compatible shift")
            else:
                logger.info(f"    [ERROR] VIOLATION: No single shift can accommodate slots {min_slot}-{max_slot}")
        
        # Show what optimal distribution would look like for this teacher
        teacher_assignments = teacher_schedule.to_dict('records')
        teacher_day_assignments = {}
        for assignment in teacher_assignments:
            day = assignment['day']
            if day not in teacher_day_assignments:
                teacher_day_assignments[day] = []
            teacher_day_assignments[day].append(assignment)
        
        optimal_shifts = shift_verifier._determine_optimal_weekly_shifts(teacher_id, teacher_day_assignments)
        
        logger.info(f"\\n  OPTIMAL WEEKLY DISTRIBUTION FOR TEACHER {teacher_id}:")
        shift_counts = {'shift1': 0, 'shift2': 0, 'shift3': 0}
        for day in days:
            shift_info = optimal_shifts.get(day, {})
            shift = shift_info.get('shift')
            reason = shift_info.get('assignment_reason', 'unknown')
            
            if shift and shift in shift_counts:
                shift_counts[shift] += 1
                shift_display = shift.replace('shift', 'S')
                logger.info(f"    {day.capitalize()}: {shift_display} ({reason})")
            elif shift == 'invalid':
                logger.info(f"    {day.capitalize()}: XX (violation)")
            else:
                logger.info(f"    {day.capitalize()}: -- (no classes)")
        
        actual_pattern = [shift_counts['shift1'], shift_counts['shift2'], shift_counts['shift3']]
        target_pattern = shift_verifier.preferred_pattern
        
        logger.info(f"  SUMMARY: Actual pattern {actual_pattern} vs Target {target_pattern}")
        
        # Calculate quality score
        if sum(actual_pattern) > 0:
            score = 100 - sum(abs(t - a) for t, a in zip(target_pattern, actual_pattern)) * 20
            logger.info(f"  QUALITY SCORE: {score:.1f}% match to target distribution")
        
        logger.info("")  # Blank line between teachers

if __name__ == "__main__":
    main() 