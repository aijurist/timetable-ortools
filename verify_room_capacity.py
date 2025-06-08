#!/usr/bin/env python3
"""
Room Capacity Constraint Verification Script

This script analyzes a previously generated timetable schedule to verify
if the room capacity constraint was actively limiting the schedule.

Usage:
  python verify_room_capacity.py [--schedule SCHEDULE_FILE]

Options:
  --schedule SCHEDULE_FILE  Path to a schedule.json file [default: most recent in output/]
"""

import os
import sys
import json
import logging
import argparse
import glob
from datetime import datetime
from src.utils.room_verifier import RoomVerifier

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("room_capacity_verification.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("room_capacity_verification")

def find_latest_schedule():
    """Find the most recent schedule.json file in the output directory."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(base_dir, 'output')
    
    if not os.path.exists(output_dir):
        logger.error(f"Output directory not found: {output_dir}")
        return None
    
    # Find all schedule directories
    schedule_dirs = glob.glob(os.path.join(output_dir, 'schedule_*'))
    if not schedule_dirs:
        logger.error("No schedule directories found in output/")
        return None
    
    # Sort by creation time (newest first)
    latest_dir = max(schedule_dirs, key=os.path.getctime)
    
    # Look for schedule.json in this directory
    schedule_file = os.path.join(latest_dir, 'schedule.json')
    if not os.path.exists(schedule_file):
        logger.error(f"No schedule.json found in {latest_dir}")
        return None
    
    logger.info(f"Found latest schedule: {schedule_file}")
    return schedule_file

def load_schedule(schedule_file):
    """Load schedule data from file."""
    try:
        with open(schedule_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Check if it's a valid schedule
        if 'daily_schedules' not in data:
            logger.error(f"Invalid schedule file format: {schedule_file}")
            return None
        
        # Convert the daily schedule format to the flat schedule_data format
        schedule_data = []
        
        # Extract assignments from daily schedules
        for day, day_data in data['daily_schedules'].items():
            # Process theory slots
            for slot in day_data.get('theory_slots', []):
                for assignment in slot.get('assignments', []):
                    schedule_data.append(assignment)
            
            # Process lab sessions
            for session in day_data.get('lab_sessions', []):
                for assignment in session.get('assignments', []):
                    schedule_data.append(assignment)
        
        logger.info(f"Loaded {len(schedule_data)} assignments from schedule")
        return {'schedule_data': schedule_data}
    
    except Exception as e:
        logger.error(f"Error loading schedule: {e}")
        return None

def main():
    """Main entry point for room capacity verification."""
    parser = argparse.ArgumentParser(description="Verify room capacity constraints in a timetable schedule")
    parser.add_argument('--schedule', help="Path to a schedule.json file")
    args = parser.parse_args()
    
    # Find schedule file
    schedule_file = args.schedule
    if not schedule_file:
        schedule_file = find_latest_schedule()
    
    if not schedule_file:
        logger.error("No schedule file specified or found")
        sys.exit(1)
    
    # Load schedule data
    schedule_result = load_schedule(schedule_file)
    if not schedule_result:
        logger.error("Failed to load schedule data")
        sys.exit(1)
    
    print("=" * 80)
    print(f"ROOM CAPACITY CONSTRAINT VERIFICATION")
    print(f"Schedule: {schedule_file}")
    print("=" * 80)
    
    # Create room verifier and run verification
    verifier = RoomVerifier(logger)
    
    # Generate verification report
    report_dir = os.path.dirname(schedule_file)
    report_file = os.path.join(report_dir, 'room_capacity_verification.txt')
    verifier.generate_room_verification_report(schedule_result, report_file)
    
    print(f"\nVerification report saved to: {report_file}")
    print("\nSummary of findings:")
    
    # Get summary and print key points
    summary = verifier.get_room_conflicts_summary(schedule_result)
    capacity_info = summary['room_capacity']
    
    print(f"Total rooms available: {capacity_info['total_rooms_available']}")
    print(f"Maximum groups in any timeslot: {capacity_info['max_groups_in_any_timeslot']}")
    print(f"Maximum rooms used in any timeslot: {capacity_info['max_rooms_in_any_timeslot']}")
    print(f"Room capacity utilization: {capacity_info['capacity_hit_ratio']:.1%}")
    print(f"Timeslots hitting capacity limit: {capacity_info['capacity_hit_slots_count']}")
    print(f"Timeslots approaching capacity (≥80%): {capacity_info['near_capacity_slots_count']}")
    
    # Special check for Tuesday 3rd slot
    verification_result = verifier.verify_room_distribution_and_overlaps(schedule_result)
    room_capacity = verification_result['room_capacity_verification']
    
    # Extract room and group counts for specific slots
    all_timeslot_room_usage = room_capacity.get('all_timeslot_room_usage', {})
    all_timeslot_group_counts = room_capacity.get('all_timeslot_group_counts', {})
    
    # Look for Tuesday 3rd slot specifically
    tuesday_3rd_slots = [key for key in all_timeslot_room_usage.keys() 
                       if key.startswith('tuesday') and '_slot_2_' in key]
    
    if tuesday_3rd_slots:
        tuesday_3rd_slot = tuesday_3rd_slots[0]
        room_count = all_timeslot_room_usage.get(tuesday_3rd_slot, 0)
        group_count = all_timeslot_group_counts.get(tuesday_3rd_slot, 0)
        total_rooms = room_capacity['total_rooms_available']
        
        print("\n" + "=" * 40)
        print("SPECIFIC CHECK: TUESDAY 3RD SLOT (10:00-10:50)")
        print("=" * 40)
        print(f"Room usage: {room_count}/{total_rooms} rooms ({room_count/total_rooms:.1%})")
        print(f"Group count: {group_count}/{total_rooms} groups ({group_count/total_rooms:.1%})")
        
        if room_count == total_rooms:
            print("✅ Tuesday 3rd slot is AT FULL CAPACITY (all rooms used)")
            
            # Check if it was properly identified in capacity hit slots
            tuesday_in_hits = any(slot['timeslot'] == tuesday_3rd_slot 
                                for slot in room_capacity.get('capacity_hit_slots', []))
            
            if tuesday_in_hits:
                print("✅ Correctly identified as capacity-hitting slot")
            else:
                print("❌ NOT correctly identified as capacity-hitting slot")
                
                # Add to capacity hit slots for the report
                if room_count == total_rooms and not tuesday_in_hits:
                    print("   -> This is a verification issue that has been fixed in the latest code")
        else:
            print(f"❌ Tuesday 3rd slot is NOT at full capacity ({room_count}/{total_rooms} rooms)")
    else:
        print("\n❌ Tuesday 3rd slot not found in the schedule")
    
    if capacity_info['constraint_was_limiting']:
        print("\n⚠️  ROOM CAPACITY CONSTRAINT WAS ACTIVELY LIMITING THE SCHEDULE")
        print("    Some timeslots used 100% of available rooms")
    elif capacity_info['constraint_nearly_limiting']:
        print("\n⚠️  ROOM CAPACITY CONSTRAINT WAS NEARLY LIMITING THE SCHEDULE")
        print("    Some timeslots used ≥80% of available rooms")
    else:
        print("\n✅ ROOM CAPACITY CONSTRAINT WAS NOT LIMITING THE SCHEDULE")
        print("    All timeslots had sufficient room capacity")

if __name__ == "__main__":
    main() 