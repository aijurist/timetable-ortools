import os
import logging
from src.scheduler import MacroblockTimetableScheduler

# Configure basic logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("timetable_scheduler.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def main():
    try:
        # Get the base directory of the project
        base_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Path to data files
        course_file = os.path.join(base_dir, 'data/mapped_data/computer_dept_teacher_courses.csv')
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
        print("• Teacher Shift Constraints: Shift 1 (8:00-3:00), Shift 2 (10:00-5:00), Shift 3 (12:00-7:00)")
        print("• NEW: No cross-shift violations - teachers stay within one shift per day")
        print("• Macroblock structure: a1/a2, b1/b2, c1/c2, d1/d2, e1/e2, f1/f2, g1/g2")
        print("• Tutorial blocks: ta1/ta2, tb1/tb2, tc1/tc2, td1/td2, te1/te2, tf1/tf2, tg1/tg2")
        print("• Extended tutorial blocks: taa1/taa2, tbb1/tbb2, tcc1/tcc2 (v1/v2 excluded)")
        print("• Course consistency: If assigned to a1, all lecture slots must be a1")
        print("• Tutorial as 3rd hour: ta1/tb1/tc1 used as 3rd lecture hour for 3-lecture courses")
        print("• Tutorial allocation: If tutorial_hours > 0 OR lecture_hours == 4")
        print("• PRIORITY CONSTRAINT: 4L, 3L+1T, 2L+2T courses restricted to a1-c2 blocks")
        print("• Teacher course instance overlap prevention: Same teacher cannot have multiple course instances in same macroblock")
        print("• Semester & Department grouping: Courses grouped by semester with teacher diversity")
        print("• Weekly Working Hour Constraint: Max 21 hours per teacher (theory: 1hr, lab: 2hr)")
        print("• No teacher double-booking across slots or rooms")
        print("• Lab allocation completely skipped as requested")
        print("• Theory-only scheduling with classroom assignments")
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
        else:
            print("Failed to generate a feasible macroblock timetable.")
    except Exception as e:
        print(f"Error in timetable generation: {str(e)}")
        logger.exception("Unhandled exception in main function")

if __name__ == "__main__":
    main()