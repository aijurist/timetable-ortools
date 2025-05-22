import os
import logging
from src.scheduler import TimetableScheduler

# Configure basic logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    try:
        # Get the base directory of the project
        base_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Path to data files
        course_file = os.path.join(base_dir, 'data/mapped_data/cs_teacher_course_formatted.csv')
        room_file = os.path.join(base_dir, 'data/mapped_data/rooms.csv')
        
        # Check if files exist
        for file_path in [course_file, room_file]:
            if not os.path.exists(file_path):
                print(f"Error: Required file not found: {file_path}")
                print(f"Looking for file at: {os.path.abspath(file_path)}")
                return
        
        print("*" * 80)
        print("Timetable Scheduler with Updated Lab Scheduling Logic")
        print("*" * 80)
        print("Lab scheduling changes implemented:")
        print("1. Labs are always scheduled as continuous blocks of at least 2 hours")
        print("2. Lab hours are calculated based on P hours in course type")
        print("3. Each lab has a fixed capacity of 35 students")
        print("4. Same teacher teaches all batches of a lab")
        print("   E.g. For 70 students: 2 batches of 35 each, teacher teaches both")
        print("*" * 80)
        
        # Create and run the scheduler
        print("Creating timetable scheduler...")
        scheduler = TimetableScheduler(course_file, room_file)
        
        print("Generating timetable...")
        solution = scheduler.generate_timetable()
        
        if solution:
            print("Timetable generated successfully!")
            print(f"Timetable visualizations saved to: {scheduler.output_dir}")
        else:
            print("Failed to generate a feasible timetable.")
    except Exception as e:
        print(f"Error in timetable generation: {str(e)}")
        logger.exception("Unhandled exception in main function")

if __name__ == "__main__":
    main()