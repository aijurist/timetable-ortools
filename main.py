#!/usr/bin/env python3
"""
University Timetable Scheduler

Main entry point for the timetable scheduler application.
"""

import os
import sys
import argparse
import logging
import json
import shutil
from datetime import datetime
import glob

# Add parent directory to path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

# Import the scheduler modules
try:
    from src.lab_scheduler import LabScheduler
    from src.theory_scheduler import TheoryScheduler
    from src.visualizer import visualize_lab_schedule, visualize_theory_schedule, visualize_combined_schedule
except ImportError:
    try:
        from timetable_scheduler.src.lab_scheduler import LabScheduler
        from timetable_scheduler.src.theory_scheduler import TheoryScheduler
        from timetable_scheduler.src.visualizer import visualize_lab_schedule, visualize_theory_schedule, visualize_combined_schedule
    except ImportError:
        print("Error: Cannot import scheduler modules. Please run from the project root directory.")
        sys.exit(1)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("timetable_scheduler.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

def find_file(filename, search_paths=None):
    """Find a file in various possible locations."""
    if search_paths is None:
        # Define default search paths
        search_paths = [
            '',  # Current directory
            'data',  # Data directory
            'data/block_wise',  # Block-wise data directory,
            'data/department_data',  # Department data directory,
            os.path.join('..', 'data'),  # Parent data directory
            os.path.join('timetable_scheduler', 'data'),  # Project data directory
            os.path.join('timetable_scheduler', 'data', 'block_wise'),  # Project block-wise directory,
            os.path.join('timetable_scheduler', 'data', 'department_data')  # Project block-wise directory
        ]
    
    # First check if the file exists as specified
    if os.path.isfile(filename):
        return filename
    
    # Try all search paths
    for path in search_paths:
        filepath = os.path.join(path, filename)
        if os.path.isfile(filepath):
            logger.info(f"Found file at: {filepath}")
            return filepath
    
    # If similar filenames exist, suggest them
    potential_matches = []
    for path in search_paths:
        if os.path.exists(path):
            for file in os.listdir(path):
                if file.lower().endswith('.csv') and any(part in file.lower() for part in filename.lower().split('.')):
                    potential_matches.append(os.path.join(path, file))
    
    if potential_matches:
        logger.warning(f"File {filename} not found, but found similar files: {potential_matches}")
    
    return None

def main():
    """Main entry point for the timetable scheduler."""
    parser = argparse.ArgumentParser(description='University Timetable Scheduler')
    
    parser.add_argument('--mode', type=str, choices=['lab', 'theory', 'all'], default='lab',
                        help='Scheduling mode (lab, theory, or all)')
    
    parser.add_argument('--course-file', type=str, default='./department_data/Computing_department.csv',
                        help='Path to the courses CSV file')
    
    parser.add_argument('--room-file', type=str, default='techlongue.csv',
                        help='Path to the rooms CSV file')
    
    parser.add_argument('--output-dir', type=str, default='output',
                        help='Directory to save the output files')
    
    parser.add_argument('--visualize', action='store_true', default=True,
                        help='Generate visualizations of the schedule')
    
    args = parser.parse_args()
    
    # Create output directory if it doesn't exist
    if not os.path.exists(args.output_dir):
        os.makedirs(args.output_dir)
    
    # Log the arguments
    logger.info(f"Running with mode: {args.mode}")
    logger.info(f"Course file: {args.course_file}")
    logger.info(f"Room file: {args.room_file}")
    logger.info(f"Output directory: {args.output_dir}")
    
    # Find the course file
    course_file = find_file(args.course_file)
    if not course_file:
        logger.error(f"Course file not found: {args.course_file}")
        sys.exit(1)
    logger.info(f"Using course file: {course_file}")
    
    # Find the room file
    room_file = find_file(args.room_file)
    if not room_file:
        logger.error(f"Room file not found: {args.room_file}")
        sys.exit(1)
    logger.info(f"Using room file: {room_file}")
    
    # Store lab schedule data for theory scheduling
    lab_schedule_data = None
    lab_output_dir = None
    
    # Create the scheduler based on the mode - LAB FIRST, THEN THEORY
    if args.mode in ['lab', 'all']:
        logger.info("Starting lab scheduling...")
        
        # Create lab scheduler
        lab_scheduler = LabScheduler(course_file, room_file, None)
        
        # Generate the lab schedule
        lab_success = lab_scheduler.generate_lab_schedule()
        
        if lab_success:
            logger.info("Lab schedule generated successfully!")
            lab_output_dir = lab_scheduler.output_dir
            
            # Load lab schedule data for theory scheduling
            try:
                lab_json_file = os.path.join(lab_scheduler.output_dir, 'lab_schedule.json')
                if os.path.exists(lab_json_file):
                    with open(lab_json_file, 'r') as f:
                        lab_schedule_data = json.load(f)
                    logger.info(f"Loaded lab schedule data for theory scheduling: {len(lab_schedule_data)} lab sessions")
                else:
                    logger.warning("Lab schedule JSON not found for theory scheduling")
            except Exception as e:
                logger.error(f"Failed to load lab schedule data: {e}")
            
            # Check if visualization should be generated
            if args.visualize:
                try:
                    logger.info("Generating lab schedule visualizations...")
                    
                    # Find the JSON file that was created
                    lab_json_file = os.path.join(lab_scheduler.output_dir, 'lab_schedule.json')
                    if os.path.exists(lab_json_file):
                        # Create visualizations directory
                        lab_viz_dir = os.path.join(lab_scheduler.output_dir, 'visualizations')
                        os.makedirs(lab_viz_dir, exist_ok=True)
                        
                        # Generate lab visualizations
                        viz_result = visualize_lab_schedule(lab_json_file, lab_viz_dir)
                        logger.info(f"Lab visualizations successfully generated in: {viz_result}")
                    else:
                        logger.warning("Lab JSON file not found for visualization")
                except Exception as e:
                    logger.error(f"Lab visualization failed: {e}")
                    import traceback
                    logger.error(f"Traceback: {traceback.format_exc()}")
        else:
            logger.error("Failed to generate lab schedule")
    
    if args.mode in ['theory', 'all']:
        logger.info("Starting theory scheduling...")
        
        # If we're only doing theory scheduling, load the latest lab schedule data
        if args.mode == 'theory' and lab_schedule_data is None:
            logger.info("Loading latest lab schedule data for conflict avoidance...")
            try:
                # Find the latest lab schedule directory
                lab_dirs = glob.glob(os.path.join(args.output_dir, 'lab_schedule_*'))
                if lab_dirs:
                    latest_lab_dir = max(lab_dirs)
                    lab_json_file = os.path.join(latest_lab_dir, 'lab_schedule.json')
                    if os.path.exists(lab_json_file):
                        with open(lab_json_file, 'r') as f:
                            lab_schedule_data = json.load(f)
                        logger.info(f"Loaded lab schedule data from {lab_json_file}: {len(lab_schedule_data)} lab sessions")
                    else:
                        logger.warning(f"Lab schedule JSON not found at {lab_json_file}")
                else:
                    logger.warning("No lab schedule directories found - theory scheduling will proceed without lab conflict avoidance")
            except Exception as e:
                logger.error(f"Failed to load existing lab schedule data: {e}")
                logger.warning("Theory scheduling will proceed without lab conflict avoidance")
        
        # Create theory scheduler with lab schedule data to prevent overlaps
        theory_scheduler = TheoryScheduler(course_file, room_file, None)
        
        # Generate the theory schedule
        theory_success = theory_scheduler.generate_theory_schedule()
        
        if theory_success:
            logger.info("Theory schedule generated successfully!")
            theory_output_dir = theory_scheduler.output_dir
            
            # Check if visualization should be generated
            if args.visualize:
                try:
                    logger.info("Generating theory schedule visualizations...")
                    
                    # Find the JSON file that was created
                    theory_json_file = os.path.join(theory_scheduler.output_dir, 'theory_schedule.json')
                    if os.path.exists(theory_json_file):
                        # Create visualizations directory
                        theory_viz_dir = os.path.join(theory_scheduler.output_dir, 'visualizations')
                        os.makedirs(theory_viz_dir, exist_ok=True)
                        
                        # Generate theory visualizations
                        viz_result = visualize_theory_schedule(theory_json_file, theory_viz_dir)
                        logger.info(f"Theory visualizations successfully generated in: {viz_result}")
                    else:
                        logger.warning("Theory JSON file not found for visualization")
                except Exception as e:
                    logger.error(f"Theory visualization failed: {e}")
                    import traceback
                    logger.error(f"Traceback: {traceback.format_exc()}")
        else:
            logger.error("Failed to generate theory schedule")

    # Final combined visualization if both schedules were generated
    if args.visualize and args.mode == 'all' and lab_output_dir and theory_output_dir:
        logger.info("Generating combined schedule visualizations...")
        try:
            lab_json_file = os.path.join(lab_output_dir, 'lab_schedule.json')
            theory_json_file = os.path.join(theory_output_dir, 'theory_schedule.json')

            if os.path.exists(lab_json_file) and os.path.exists(theory_json_file):
                combined_viz_dir = os.path.join(args.output_dir, f'combined_visuals_{datetime.now().strftime("%Y%m%d_%H%M%S")}')
                os.makedirs(combined_viz_dir, exist_ok=True)
                
                visualize_combined_schedule(lab_json_file, theory_json_file, combined_viz_dir)
                logger.info(f"Combined visualizations generated in: {combined_viz_dir}")
            else:
                logger.warning("Could not find both lab and theory JSON files for combined visualization")
        except Exception as e:
            logger.error(f"Combined visualization failed: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            
    logger.info("Timetable scheduling completed")

if __name__ == "__main__":
    main() 