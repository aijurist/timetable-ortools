import os
import logging
from src.scheduler import TimetableScheduler

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
        print("Timetable Scheduler – Computer Science Department")
        print("*" * 80)
        print("Key constraint highlights:")
        print("• 11 theory slots per day (50 min with 10 min break)")
        print("• 5 lab slots per day (1hr:50min with 10 min break)")
        print("• Courses allocated according to LTP hours (Lecture, Tutorial, Practical)")
        print("• No teacher assigned to overlapping slots")
        print("• Labs scheduled only in computer labs")
        print("• Theory classes scheduled only in classrooms (not labs)")
        print("• Lab batches created for classes exceeding lab capacity (35 students)")
        print("• Weekly working hour limit: 21 hours per teacher")
        print("• No continuous lab slots unless 20+ minute break (L1-L2 and L5-L6 allowed)")
        print("• Teachers work either Monday OR Saturday, not both days")
        print("*" * 80)
        
        # Create and run the scheduler
        print("Creating timetable scheduler...")
        scheduler = TimetableScheduler(course_file, room_file)
        
        print("Generating timetable...")
        solution = scheduler.generate_timetable()
        
        if solution:
            print("Timetable generated successfully!")
            print(f"Timetable outputs saved to: {scheduler.output_dir}")
            print("\nThe following files have been generated:")
            print("  - schedule.csv: Master schedule with all assignments")
            print("  - teacher_*_schedule.csv: Individual teacher schedules")
            print("  - room_*_schedule.csv: Individual room schedules")
            print("  - constraint_summary.txt: Detailed impact analysis of each constraint")
            print("  - constraint_summary.json: Machine-readable constraint analysis")
            print("  - summary.txt: Overview of the generated schedule")
            print("  - *.png: Visualizations of the timetable")
        else:
            print("Failed to generate a feasible timetable.")
    except Exception as e:
        print(f"Error in timetable generation: {str(e)}")
        logger.exception("Unhandled exception in main function")

if __name__ == "__main__":
    main()