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
        course_file = os.path.join(base_dir, 'data/mapped_data/cs_teacher_courses.csv')
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
        print("• 12 time slots per day (Tuesday-Saturday)")
        print("• Macroblock structure: a1/a2/a3, b1/b2/b3, c1/c2/c3, d1/d2/d3, e1/e2/e3, f1/f2/f3, g1/g2/g3")
        print("• Tutorial blocks: ta1/ta2/ta3, tb1/tb2/tb3, tc1/tc2/tc3, td1/td2/td3")
        print("• 3-shift system: Shift1(blocks x1), Shift2(blocks x2), Shift3(blocks x3)")
        print("• Course consistency: If assigned to a1, all lecture slots must be a1")
        print("• Tutorial allocation: If tutorial_hours > 0 OR lecture_hours == 4")
        print("• Semester & Department grouping: Courses grouped by semester with teacher diversity")
        print("• Vertical Macroblock Grouping: Promotes a1→b1→c1 over a1→f1→a2 patterns")
        print("• Weekly Working Hour Constraint: Max 21 hours per teacher (theory: 1hr, lab: 2hr)")
        print("• Teacher Shift System: 3 shifts (8:00-15:00, 10:00-17:00, 12:00-19:00)")
        print("• Shift Distribution: 33% teachers per department per shift")
        print("• Overlapping Slot Management: Separate macro blocks for overlapping time slots")
        print("• No teacher double-booking across slots or rooms")
        print("• Lab allocation temporarily disabled")
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