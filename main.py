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
from datetime import datetime

# Add parent directory to path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

# Import the scheduler modules
try:
    from src.lab_scheduler import LabScheduler
    from src.visualizer import visualize_lab_schedule
except ImportError:
    try:
        from timetable_scheduler.src.lab_scheduler import LabScheduler
        from timetable_scheduler.src.visualizer import visualize_lab_schedule
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
            'data/block_wise',  # Block-wise data directory
            os.path.join('..', 'data'),  # Parent data directory
            os.path.join('timetable_scheduler', 'data'),  # Project data directory
            os.path.join('timetable_scheduler', 'data', 'block_wise')  # Project block-wise directory
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
    
    parser.add_argument('--course-file', type=str, default='cse.csv',
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
    
    # Create the scheduler based on the mode
    if args.mode in ['lab', 'all']:
        logger.info("Starting lab scheduling...")
        lab_scheduler = LabScheduler(course_file, room_file)
        
        # Generate the lab schedule
        success = lab_scheduler.generate_lab_schedule()
        
        if success:
            logger.info("Lab schedule generated successfully!")
            
            # Check if visualization should be generated
            if args.visualize:
                try:
                    logger.info("Generating lab schedule visualizations...")
                    
                    # Find the JSON file that was created
                    json_file = os.path.join(lab_scheduler.output_dir, 'lab_schedule.json')
                    if os.path.exists(json_file):
                        # Create visualizations directory
                        viz_dir = os.path.join(lab_scheduler.output_dir, 'visualizations')
                        os.makedirs(viz_dir, exist_ok=True)
                        
                        # Generate visualizations
                        viz_result = visualize_lab_schedule(json_file, viz_dir)
                        logger.info(f"Visualizations successfully generated in: {viz_result}")
                    else:
                        logger.warning("JSON file not found for visualization")
                except Exception as e:
                    logger.error(f"Visualization failed: {e}")
                    import traceback
                    logger.error(f"Traceback: {traceback.format_exc()}")
        else:
            logger.error("Failed to generate lab schedule")
    
    if args.mode in ['theory', 'all']:
        # TODO: Implement theory scheduling
        logger.info("Theory scheduling not implemented yet")
    
    logger.info("Timetable scheduling completed")

if __name__ == "__main__":
    main() 