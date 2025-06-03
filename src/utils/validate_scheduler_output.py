import os
import sys
import argparse
import logging
from pathlib import Path
import pandas as pd
from .combination_analyzer import load_schedule_data, extract_teacher_distribution, analyze_combinations

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.utils.combination_validator import validate_student_combinations

def validate_scheduler_output(output_dir, student_count=700):
    """
    Validate the scheduler output to ensure all students can create valid schedules.
    
    Args:
        output_dir: Directory containing the scheduler output files
        student_count: Number of students to accommodate
        
    Returns:
        Boolean indicating if the validation passed
    """
    print(f"\nValidating scheduler output for {student_count} students...")
    
    # Ensure output directory exists
    if not os.path.exists(output_dir):
        print(f"Error: Output directory {output_dir} does not exist.")
        return False
    
    # Load the schedule data
    schedule_file = os.path.join(output_dir, 'macroblock_schedule.csv')
    if not os.path.exists(schedule_file):
        print(f"Error: Schedule file {schedule_file} not found.")
        return False
    
    try:
        # Load schedule data
        schedule_df = load_schedule_data(output_dir)
        
        # Extract teacher distribution
        distribution = extract_teacher_distribution(schedule_df)
        
        # Generate validation report
        validation_report_path = os.path.join(output_dir, 'combination_validation_report.txt')
        
        # Redirect stdout to capture the analysis output
        from io import StringIO
        
        # Save original stdout
        original_stdout = sys.stdout
        
        # Create a string buffer to capture output
        output_buffer = StringIO()
        sys.stdout = output_buffer
        
        # Run the analysis
        is_valid = analyze_combinations(distribution, student_per_teacher=70, 
                                       display_detailed=True, student_count=student_count)
        
        # Get the captured output
        analysis_output = output_buffer.getvalue()
        
        # Restore original stdout
        sys.stdout = original_stdout
        
        # Write the analysis output to the validation report file
        with open(validation_report_path, 'w', encoding='utf-8') as f:
            f.write(analysis_output)
        
        # Print a summary
        if is_valid:
            print(f"✅ Validation PASSED: All {student_count} students can create valid schedules.")
            print(f"See {validation_report_path} for detailed analysis.")
        else:
            print(f"❌ Validation FAILED: Not all {student_count} students can create valid schedules.")
            print(f"See {validation_report_path} for details on the issues.")
        
        return is_valid
        
    except Exception as e:
        print(f"Error validating scheduler output: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Validate timetable for student course combinations')
    parser.add_argument('--output-dir', required=True, help='Output directory with schedule files')
    parser.add_argument('--students', type=int, default=700, help='Number of students to accommodate')
    
    args = parser.parse_args()
    
    success = validate_scheduler_output(args.output_dir, args.students)
    
    sys.exit(0 if success else 1) 