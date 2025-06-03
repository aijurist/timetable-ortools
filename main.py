import os
import logging
import argparse
from src.scheduler import MacroblockTimetableScheduler
from src.utils.validate_scheduler_output import validate_scheduler_output
from src.utils.fix_combinations import fix_course_combinations

# Configure basic logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("timetable_scheduler.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Macroblock Timetable Scheduler')
    parser.add_argument('--fix-combinations', action='store_true',
                        help='Attempt to fix course combination issues if validation fails')
    parser.add_argument('--student-count', type=int, default=700,
                        help='Number of students to accommodate (default: 700)')
    args = parser.parse_args()
    
    try:
        # Get the base directory of the project
        base_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Path to data files
        course_file = os.path.join(base_dir, 'data/mapped_data/cs_5sem.csv')
        if not os.path.exists(course_file):
            print(f"Error: Course file not found at {course_file}")
            return
        
        # Use rooms.csv file for all rooms (both classrooms and labs)
        room_file = os.path.join(base_dir, 'data/block_wise/techlongue.csv')
        if not os.path.exists(room_file):
            print(f"Error: Room file not found at {room_file}")
            return
        
        print("*" * 80)
        print("Macroblock Timetable Scheduler – Computer Science Department")
        print("*" * 80)
        print("Key macroblock constraints:")
        print("• 11 theory time slots per day (Tuesday-Saturday): 8:00-8:50 to 6:00-6:50")
        print("• Proper theory timing: 50-minute classes with 10-minute breaks")
        print("• DISABLED: Teacher Shift Constraints (focusing on course grouping)")
        print("• Macroblock structure: a1/a2, b1/b2, c1/c2, d1/d2, e1/e2, f1/f2, g1/g2")
        print("• Tutorial blocks: ta1/ta2, tb1/tb2, tc1/tc2, td1/td2, te1/te2, tf1/tf2, tg1/tg2")
        print("• Extended tutorial blocks: taa1/taa2, tbb1/tbb2, tcc1/tcc2 (v1/v2 excluded)")
        print("• Course consistency: If assigned to a1, all lecture slots must be a1")
        print("• Tutorial as 3rd hour: ta1/tb1/tc1 used as 3rd lecture hour for 3-lecture courses")
        print("• Tutorial allocation: If tutorial_hours > 0 OR lecture_hours == 4")
        print("• PRIORITY CONSTRAINT: 4L, 3L+1T, 2L+2T courses restricted to a1-c2 blocks")
        print("• REMOVED: Teacher course instance overlap prevention")
        print("• NEW: Different courses assigned to different macroblocks")
        print("• NEW: Courses with lecture + tutorial = 4 hours get PRIORITY for blocks a1-c1")
        print("• NEW: c1 courses → a1, c2 courses → b1, c3 courses → c1, etc.")
        print("• NEW: PRIORITY CONSTRAINT SYSTEM:")
        print("  - HIGHEST PRIORITY: Teacher cannot have multiple course instances in same block")
        print("  - FLEXIBLE PRIORITY: Different courses prefer different blocks")
        print("  - EXCEPTION HANDLING: Teacher conflicts override course-block preferences")
        print("  - RESULT: Teacher conflicts resolved by placing courses in alternative blocks")
        print("  - BENEFIT: No infeasibility due to conflicting constraints")
        print("• REMOVED: Course Code Diversity Constraints (no limit on instances per course per block)")
        print("• REMOVED: Teacher Instance Diversity Constraints (teachers can have multiple instances per block)")
        print("• Weekly Working Hour Constraint: Max 21 hours per teacher (theory: 1hr, lab: 2hr)")
        print("• No teacher double-booking across slots or rooms")
        print("• Lab allocation completely skipped as requested")
        print("• Theory-only scheduling with classroom assignments")
        print("• ENHANCED: Department-specific block allocation constraints")
        print("  - Computer Science & Engineering: RESTRICTED to a1-g1 blocks ONLY")
        print("  - Artificial Intelligence & Data Science: RESTRICTED to a1-g1 blocks ONLY")
        print("  - Artificial Intelligence & Machine Learning: RESTRICTED to a1-g1 blocks ONLY")
        print("  - Computer Science & Design: RESTRICTED to a1-g1 blocks ONLY")
        print("  - Course cohorts for each semester grouped within department's allowed blocks")
        print("  - Enhanced semester grouping with different courses in different blocks")
        print("  - Department utilization tracking and monitoring")
        print("• Schedule structure: Tuesday-Saturday (Monday excluded)")
        print("• FOCUS: Different courses in different macroblocks with priority system")
        print("• BENEFIT: Clear course separation and priority allocation for high-hour courses")
        print("• NEW: Course combination validation for student registration")
        print(f"  - Checks if {args.student_count} students can select one teacher per course without conflicts")
        print("  - Ensures students can register for all required courses in their semester")
        print("*" * 80)
        
        # Create and run the scheduler
        print("Creating macroblock timetable scheduler...")
        scheduler = MacroblockTimetableScheduler(course_file, room_file)
        
        print("Generating timetable...")
        solution = scheduler.generate_timetable()
        
        if solution:
            print("Macroblock timetable generated successfully!")
            print(f"Timetable outputs saved to: {scheduler.output_dir}")
            print("\nThe following files have been generated:")
            print("  - macroblock_schedule.csv: Master schedule with macroblock assignments (theory only)")
            print("  - macroblock_schedule.json: Structured schedule in JSON format")
            print("  - teacher_*_schedule.csv: Individual teacher schedules")
            print("  - room_*_schedule.csv: Individual room schedules (classrooms only)")
            print("  - macroblock_summary.txt: Overview of the generated macroblock schedule")
            print("  - macroblock_master_schedule.png: Visual master schedule")
            print("  - teacher_*_macroblock_schedule.png: Individual teacher visualizations")
            print("  - room_*_macroblock_schedule.png: Individual room visualizations")
            print("  - macroblock_analysis.png: Macroblock distribution analysis")
            
            # Validate student course combinations
            print("\nValidating student course combinations...")
            validation_result = validate_scheduler_output(scheduler.output_dir, student_count=args.student_count)
            
            if validation_result:
                print("✅ VALIDATION PASSED: The timetable allows students to select all required courses")
                print("  - Each student can find at least one valid combination of courses")
                print("  - See combination_validation_report.txt for details")
            else:
                print("❌ VALIDATION FAILED: The timetable does not allow all students to select required courses")
                print("  - Check combination_validation_report.txt for details")
                
                # Try to fix combination issues if requested
                if args.fix_combinations:
                    print("\nAttempting to fix course combination issues...")
                    schedule_path = os.path.join(scheduler.output_dir, 'macroblock_schedule.csv')
                    fix_success = fix_course_combinations(
                        schedule_path, scheduler.output_dir, semester=5, student_count=args.student_count
                    )
                    
                    if fix_success:
                        print("✅ Fixed timetable generated successfully!")
                        print("  - modified_macroblock_schedule.csv contains the fixed timetable")
                        print("  - See combination_fix_report.txt for details on applied fixes")
                    else:
                        print("⚠️ Could not fully resolve combination issues automatically")
                        print("  - Partial fixes may have been applied")
                        print("  - Consider adjusting the constraints or running with different parameters")
                else:
                    print("  - Run with --fix-combinations to attempt automatic fixes")
        else:
            print("Failed to generate a feasible macroblock timetable.")
    except Exception as e:
        print(f"Error in timetable generation: {str(e)}")
        logger.exception("Unhandled exception in main function")

if __name__ == "__main__":
    main()