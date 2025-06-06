import os
import logging
import argparse
from src.scheduler import TimetableScheduler

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
    parser = argparse.ArgumentParser(description='Timetable Scheduler')
    args = parser.parse_args()
    
    try:
        # Get the base directory of the project
        base_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Path to data files
        course_file = os.path.join(base_dir, 'data/cse.csv')
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
        print("ENHANCED: Theory + Lab Scheduling System")
        print("*" * 80)
        print("Key scheduling constraints:")
        print("• 11 theory time slots per day (Tuesday-Saturday): 8:00-8:50 to 6:00-6:50")
        print("• 6 lab sessions per day (Tuesday-Saturday): L1-L6, each 2 hours (100 minutes)")
        print("• Theory timing: 50-minute classes with 10-minute breaks")
        print("• Lab timing: 2-hour sessions for practical work")
        print("• ENHANCED: Integrated theory and lab scheduling for optimal resource utilization")
        print("• Course types handled: Theory-only (T), Lecture+Practical (LoT)")
        print("• Lab scheduling based on practical hours in course structure")
        print("• Conflict prevention: Teachers cannot have overlapping theory and lab assignments")
        print("• Resource allocation: Classrooms for theory, Labs for practical work")
        print("• Workload management: 21-hour weekly limit (theory: 1hr/slot, lab: 2hr/session)")
        print("• Weekly Working Hour Constraint: Max 21 hours per teacher")
        print("• No teacher double-booking across slots, rooms, or time conflicts")
        print("• Enhanced room verification: Both classroom and lab assignments")
        print("• Schedule structure: Tuesday-Saturday (Monday excluded)")
        print("• COMPREHENSIVE: Full academic schedule with theory and practical components")
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
            print("  - schedule.csv: Master schedule with theory and lab assignments")
            print("  - schedule.json: Structured schedule in JSON format")
            print("  - teacher_*_schedule.csv: Individual teacher schedules (theory + lab)")
            print("  - room_*_schedule.csv: Individual room schedules (classrooms + labs)")
            print("  - schedule_summary.txt: Overview of the generated comprehensive schedule")
            print("  - visualizations: Visual master schedule (theory + lab)")
            print("  - room_verification_report.txt: Comprehensive room utilization report")
        else:
            print("Failed to generate a feasible timetable.")
    except Exception as e:
        print(f"Error in timetable generation: {str(e)}")
        logger.exception("Unhandled exception in main function")

if __name__ == "__main__":
    main()