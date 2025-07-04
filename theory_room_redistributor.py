#!/usr/bin/env python3
"""
Theory Room Redistributor for 70-Capacity Classrooms

This script redistributes room allocations for theory sessions in 70-capacity classrooms
with priority for A and B blocks, avoiding TIFAC rooms unless necessary. It optimizes room assignments by:
- Grouping departments by blocks (A and B Block preferred, avoiding TIFAC rooms)
- C Block as fallback option
- TIFAC A Block rooms as last resort fallback only
- Floor-wise grouping within blocks  
- Keeping continuous classes in the same room when possible
- Maintaining existing time slots (only changing room assignments)
- PREVENTING DOUBLE BOOKINGS through proper room registry tracking
"""

import os
import sys
import pandas as pd
import logging
import json
import numpy as np
from datetime import datetime
from collections import defaultdict, Counter
import shutil

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("room_redistribution.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

class TheoryRoomRedistributor:
    """Redistributes theory room allocations for 70-capacity classrooms efficiently."""
    
    def __init__(self):
        """Initialize the redistributor."""
        self.theory_timetable_file = "data/timetable/combined_schedule_theory.csv"
        self.room_file = "data/block_wise/techlongue.csv"
        
        # Room occupancy registry - prevents double bookings
        self.room_registry = {}  # (day, time_slot, room_id) -> session_info
        
        # Load data
        self._load_data()
        self._setup_redistribution_parameters()
    
    def _load_data(self):
        """Load theory timetable and room data."""
        logger.info("Loading data files...")
        
        # Load theory timetable
        self.theory_df = pd.read_csv(self.theory_timetable_file)
        logger.info(f"Loaded {len(self.theory_df)} theory sessions")
        
        # Load room data
        self.rooms_df = pd.read_csv(self.room_file)
        logger.info(f"Loaded {len(self.rooms_df)} rooms")
        
        # Filter for 70-capacity classrooms (include all blocks, but prioritize A and B)
        self.available_rooms = self.rooms_df[
            (self.rooms_df['room_max_cap'] == 70) & 
            (self.rooms_df['is_lab'] == 0)
        ].copy()
        
        logger.info(f"Found {len(self.available_rooms)} available 70-capacity classrooms")
        
        # Group rooms by block and floor for efficient assignment
        self._analyze_room_distribution()
    
    def _analyze_room_distribution(self):
        """Analyze room distribution across blocks and floors."""
        logger.info("Analyzing room distribution...")
        
        self.rooms_by_block = defaultdict(list)
        self.rooms_by_floor = defaultdict(list)
        
        for _, room in self.available_rooms.iterrows():
            block = room['block']
            room_number = room['room_number']
            room_id = room['id']
            
            # Extract floor from room number (e.g., A302 -> 3rd floor)
            floor = 'Ground'
            if len(room_number) >= 3 and room_number[1:2].isdigit():
                floor_digit = room_number[1:2]
                if floor_digit == '1':
                    floor = '1st'
                elif floor_digit == '2':
                    floor = '2nd'
                elif floor_digit == '3':
                    floor = '3rd'
                elif floor_digit == '4':
                    floor = '4th'
            
            self.rooms_by_block[block].append({
                'id': room_id,
                'room_number': room_number,
                'floor': floor,
                'block': block
            })
            
            floor_key = f"{block}_{floor}"
            self.rooms_by_floor[floor_key].append({
                'id': room_id,
                'room_number': room_number,
                'floor': floor,
                'block': block
            })
        
        # Log distribution
        for block, rooms in self.rooms_by_block.items():
            logger.info(f"Block {block}: {len(rooms)} rooms")
            
        for floor_key, rooms in self.rooms_by_floor.items():
            logger.info(f"Floor {floor_key}: {len(rooms)} rooms")
    
    def _setup_redistribution_parameters(self):
        """Setup redistribution parameters and department groupings."""
        # Department-to-block mapping for efficient grouping (A and B Block preferred)
        self.dept_block_preference = {
            # A Block - Computer Science and Engineering departments
            'Computer Science & Engineering': 'A Block',
            'Computer Science & Business Systems': 'A Block',
            'Computer Science & Design': 'A Block',
            'Computer Science & Engineering (Cyber Security)': 'A Block',
            'Information Technology': 'A Block',
            'Artificial Intelligence & Data Science': 'A Block',
            'Artificial Intelligence & Machine Learning': 'A Block',
            'Food Technology': 'A Block',
            
            # B Block - All other Engineering departments  
            'Electronics & Communication Engineering': 'B Block',
            'Biomedical Engineering': 'B Block',
             'Biotechnology': 'B Block',
            'Electrical & Electronics Engineering': 'B Block',
            'Chemical Engineering': 'B Block',
            'Civil Engineering': 'B Block',
            'Mechanical Engineering': 'B Block',
            'Automobile Engineering': 'B Block',
            'Aeronautical Engineering': 'B Block',
            'Mechatronics Engineering': 'B Block',
            'Robotics & Automation': 'B Block'
        }
        
        # Time slots for proper conflict detection
        self.theory_time_slots = [
            "8:00 - 8:50", "9:00 - 9:50", "10:00 - 10:50", "11:00 - 11:50",
            "12:00 - 12:50", "1:00 - 1:50", "2:00 - 2:50", "3:00 - 3:50",
            "4:00 - 4:50", "5:00 - 5:50", "6:00 - 6:50", "7:00 - 7:50"
        ]
        
        # Day normalization (must match combined_scheduler)
        self.day_mapping = {
            'monday': 'monday',
            'tue': 'tuesday', 'tuesday': 'tuesday',
            'wed': 'wed', 'wednesday': 'wed', 
            'thu': 'thur', 'thur': 'thur', 'thursday': 'thur',
            'fri': 'fri', 'friday': 'fri',
            'sat': 'saturday', 'saturday': 'saturday'
        }
    
    def _normalize_day_name(self, day_name):
        """Normalize day names for consistency."""
        return self.day_mapping.get(day_name.lower(), day_name.lower())
    
    def _initialize_room_registry(self):
        """Initialize room registry with existing non-70-capacity sessions."""
        logger.info("Initializing room registry to prevent double bookings...")
        
        self.room_registry = {}
        
        # Register all non-70-capacity sessions to prevent conflicts
        for _, session in self.theory_df.iterrows():
            if session['student_count'] != 70 or session.get('is_co_scheduled', False):
                day_normalized = self._normalize_day_name(session['day'])
                time_slot = session['time_slot']
                room_id = session['room_id']
                
                key = (day_normalized, time_slot, room_id)
                
                session_info = {
                    'course_code': session['course_code'],
                    'teacher_id': session['teacher_id'],
                    'department': session['department'],
                    'student_count': session['student_count'],
                    'is_protected': True  # Protected from redistribution
                }
                
                self.room_registry[key] = session_info
        
        logger.info(f"Protected {len(self.room_registry)} existing room assignments from redistribution")
    
    def _is_room_available(self, day, time_slot, room_id):
        """Check if room is available at the given time."""
        day_normalized = self._normalize_day_name(day)
        key = (day_normalized, time_slot, room_id)
        return key not in self.room_registry
    
    def _register_room_usage(self, day, time_slot, room_id, session_info):
        """Register room usage to prevent double booking."""
        day_normalized = self._normalize_day_name(day)
        key = (day_normalized, time_slot, room_id)
        
        if key in self.room_registry:
            existing = self.room_registry[key]
            logger.error(f"DOUBLE BOOKING DETECTED!")
            logger.error(f"  Room {room_id} on {day} {time_slot}")
            logger.error(f"  Existing: {existing.get('course_code', 'Unknown')}")
            logger.error(f"  New: {session_info.get('course_code', 'Unknown')}")
            return False
        
        self.room_registry[key] = session_info
        return True
    
    def _get_preferred_rooms_for_department(self, department):
        """Get preferred rooms for a department with A/B Block priority, avoiding TIFAC rooms, C Block as fallback."""
        preferred_block = self.dept_block_preference.get(department, 'A Block')
        
        preferred_rooms = []
        
        # Priority 1: Preferred block (A or B) - NON-TIFAC rooms only
        if preferred_block in self.rooms_by_block:
            block_rooms = [room for room in self.rooms_by_block[preferred_block] 
                          if not self._is_tifac_room(room['room_number'])]
            block_rooms = sorted(block_rooms, key=lambda x: (x['floor'], x['room_number']))
            preferred_rooms.extend(block_rooms)
        
        # Priority 2: Other high-priority block (A or B, whichever wasn't preferred) - NON-TIFAC rooms only
        high_priority_blocks = ['A Block', 'B Block']
        for block in high_priority_blocks:
            if block != preferred_block and block in self.rooms_by_block:
                block_rooms = [room for room in self.rooms_by_block[block] 
                              if not self._is_tifac_room(room['room_number'])]
                block_rooms = sorted(block_rooms, key=lambda x: (x['floor'], x['room_number']))
                preferred_rooms.extend(block_rooms)
        
        # Priority 3: C Block as fallback (all C Block rooms)
        if 'C Block' in self.rooms_by_block:
            c_block_rooms = sorted(self.rooms_by_block['C Block'], 
                                  key=lambda x: (x['floor'], x['room_number']))
            preferred_rooms.extend(c_block_rooms)
        
        # Priority 4: TIFAC A Block rooms as last resort fallback
        tifac_rooms = []
        for block in ['A Block', 'B Block']:
            if block in self.rooms_by_block:
                tifac_block_rooms = [room for room in self.rooms_by_block[block] 
                                    if self._is_tifac_room(room['room_number'])]
                tifac_block_rooms = sorted(tifac_block_rooms, key=lambda x: (x['floor'], x['room_number']))
                tifac_rooms.extend(tifac_block_rooms)
        
        preferred_rooms.extend(tifac_rooms)
        
        return preferred_rooms
    
    def _is_tifac_room(self, room_number):
        """Check if a room is a TIFAC room based on room number."""
        return str(room_number).upper().startswith('TIFAC')
    
    def _find_best_room_for_session(self, session, teacher_schedule, preferred_rooms):
        """Find the best room for a session considering teacher continuity."""
        day = session['day']
        time_slot = session['time_slot']
        teacher_id = session['teacher_id']
        
        # Strategy 1: Try to keep teacher in same room for continuous classes
        if teacher_id in teacher_schedule:
            for prev_session in teacher_schedule[teacher_id]:
                prev_day = prev_session['day']
                prev_time_slot = prev_session['time_slot']
                prev_room_id = prev_session['room_id']
                
                # Check if this is a continuous class (same day, adjacent time slot)
                if (prev_day == day and 
                    self._are_adjacent_time_slots(prev_time_slot, time_slot) and
                    self._is_room_available(day, time_slot, prev_room_id)):
                    
                    # Check if the previous room is in our preferred list
                    for room in preferred_rooms:
                        if room['id'] == prev_room_id:
                            return room['id']
        
        # Strategy 2: Find first available room in preferred order
        for room in preferred_rooms:
            room_id = room['id']
            if self._is_room_available(day, time_slot, room_id):
                return room_id
        
        logger.warning(f"No available room found for {session['course_code']} on {day} {time_slot}")
        return None
    
    def _are_adjacent_time_slots(self, slot1, slot2):
        """Check if two time slots are adjacent."""
        try:
            if slot1 in self.theory_time_slots and slot2 in self.theory_time_slots:
                idx1 = self.theory_time_slots.index(slot1)
                idx2 = self.theory_time_slots.index(slot2)
                return abs(idx1 - idx2) == 1
        except (ValueError, IndexError):
            pass
        return False
    
    def redistribute_rooms(self):
        """Main redistribution logic that prevents double bookings."""
        logger.info("="*60)
        logger.info("STARTING THEORY ROOM REDISTRIBUTION")
        logger.info("="*60)
        
        # Initialize room registry to prevent conflicts
        self._initialize_room_registry()
        
        # Filter 70-capacity sessions that need redistribution
        sessions_to_redistribute = self.theory_df[
            (self.theory_df['student_count'] == 70) & 
            (self.theory_df['is_co_scheduled'] == False)
        ].copy()
        
        logger.info(f"Redistributing {len(sessions_to_redistribute)} theory sessions")
        
        # Group sessions by department for block-wise assignment
        sessions_by_dept = sessions_to_redistribute.groupby('department')
        
        # Track teacher schedules for continuity optimization
        teacher_schedule = defaultdict(list)
        
        # Statistics tracking
        stats = {
            'total_redistributed': 0,
            'continuity_preserved': 0,
            'block_grouped': 0,
            'failed_assignments': 0
        }
        
        # Process each department
        for department, dept_sessions in sessions_by_dept:
            logger.info(f"Processing {department}: {len(dept_sessions)} sessions")
            
            # Get preferred rooms for this department
            preferred_rooms = self._get_preferred_rooms_for_department(department)
            logger.info(f"  Preferred block: {self.dept_block_preference.get(department, 'A Block')}")
            
            # Sort sessions by day and time for better continuity
            dept_sessions_sorted = dept_sessions.sort_values(['day', 'time_slot', 'teacher_id'])
            
            # Assign rooms to each session
            for _, session in dept_sessions_sorted.iterrows():
                new_room_id = self._find_best_room_for_session(
                    session, teacher_schedule, preferred_rooms
                )
                
                if new_room_id:
                    # Update the dataframe
                    original_room = session['room_id']
                    self.theory_df.loc[session.name, 'room_id'] = new_room_id
                    
                    # Get new room details
                    new_room = self.available_rooms[self.available_rooms['id'] == new_room_id].iloc[0]
                    self.theory_df.loc[session.name, 'room_number'] = new_room['room_number']
                    self.theory_df.loc[session.name, 'block'] = new_room['block']
                    
                    # Register the room usage
                    session_info = {
                        'course_code': session['course_code'],
                        'teacher_id': session['teacher_id'],
                        'department': session['department'],
                        'student_count': session['student_count'],
                        'is_redistributed': True
                    }
                    
                    success = self._register_room_usage(
                        session['day'], session['time_slot'], new_room_id, session_info
                    )
                    
                    if success:
                        # Update teacher schedule for continuity tracking
                        teacher_schedule[session['teacher_id']].append({
                            'day': session['day'],
                            'time_slot': session['time_slot'],
                            'room_id': new_room_id,
                            'course_code': session['course_code']
                        })
                        
                        stats['total_redistributed'] += 1
                        
                        # Check if this preserved continuity
                        if len(teacher_schedule[session['teacher_id']]) > 1:
                            prev_room = teacher_schedule[session['teacher_id']][-2]['room_id']
                            if prev_room == new_room_id:
                                stats['continuity_preserved'] += 1
                        
                        # Check if this achieved block grouping
                        preferred_block = self.dept_block_preference.get(department, 'A Block')
                        if new_room['block'] == preferred_block:
                            stats['block_grouped'] += 1
                        
                        if original_room != new_room_id:
                            logger.debug(f"  {session['course_code']}: {session['day']} {session['time_slot']} "
                                       f"moved from room {original_room} to {new_room_id} ({new_room['room_number']})")
                    else:
                        logger.error(f"Failed to register room usage for {session['course_code']}")
                        stats['failed_assignments'] += 1
                else:
                    logger.error(f"No room available for {session['course_code']} on {session['day']} {session['time_slot']}")
                    stats['failed_assignments'] += 1
                    
                    # For failed assignments, we still need to register the original room to prevent conflicts
                    # This ensures the verification doesn't show false positives
                    original_session_info = {
                        'course_code': session['course_code'],
                        'teacher_id': session['teacher_id'],
                        'department': session['department'],
                        'student_count': session['student_count'],
                        'is_failed_redistribution': True
                    }
                    
                    # Try to register the original room assignment
                    original_success = self._register_room_usage(
                        session['day'], session['time_slot'], session['room_id'], original_session_info
                    )
                    
                    if not original_success:
                        logger.error(f"CRITICAL: Original room {session['room_id']} also conflicts for {session['course_code']}")
                        logger.error(f"This indicates the original schedule had conflicts - removing session from final schedule")
                        # Mark this session for removal from final schedule
                        self.theory_df.drop(session.name, inplace=True)
        
        # Log final statistics
        logger.info("="*60)
        logger.info("REDISTRIBUTION COMPLETED")
        logger.info("="*60)
        logger.info(f"Total sessions redistributed: {stats['total_redistributed']}")
        logger.info(f"Continuity preserved: {stats['continuity_preserved']}")
        logger.info(f"Block grouping achieved: {stats['block_grouped']}")
        logger.info(f"Failed assignments: {stats['failed_assignments']}")
        
        # Verify no double bookings
        self._verify_no_double_bookings()
        
        return stats
    
    def _verify_no_double_bookings(self):
        """Verify that no double bookings exist in the final schedule."""
        logger.info("Verifying no double bookings in final schedule...")
        
        conflicts = 0
        room_time_usage = defaultdict(list)
        
        # Check all theory sessions
        for _, session in self.theory_df.iterrows():
            day_normalized = self._normalize_day_name(session['day'])
            time_slot = session['time_slot']
            room_id = session['room_id']
            
            key = (day_normalized, time_slot, room_id)
            room_time_usage[key].append({
                'course_code': session['course_code'],
                'teacher_id': session['teacher_id'],
                'department': session['department']
            })
        
        # Check for conflicts
        for key, sessions in room_time_usage.items():
            if len(sessions) > 1:
                day, time_slot, room_id = key
                conflicts += 1
                logger.error(f"DOUBLE BOOKING: Room {room_id} on {day} {time_slot}")
                for session in sessions:
                    logger.error(f"  - {session['course_code']} ({session['department']})")
        
        if conflicts == 0:
            logger.info("✅ VERIFICATION PASSED: No double bookings found")
        else:
            logger.error(f"❌ VERIFICATION FAILED: {conflicts} double bookings found")
        
        return conflicts == 0
    
    def save_results(self):
        """Save the redistributed timetable and generate reports."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Create backup
        backup_file = f"{self.theory_timetable_file}.backup_{timestamp}"
        shutil.copy2(self.theory_timetable_file, backup_file)
        logger.info(f"Backup created: {backup_file}")
        
        # Save redistributed timetable
        self.theory_df.to_csv(self.theory_timetable_file, index=False)
        logger.info(f"✅ Redistributed timetable saved to: {self.theory_timetable_file}")
        
        # Generate JSON output
        self._save_json_output(timestamp)
        
        # Generate redistribution report
        self._generate_redistribution_report(timestamp)
        
        logger.info("✅ All output files generated successfully")
    
    def _save_json_output(self, timestamp):
        """Save redistributed timetable in JSON format."""
        logger.info("Generating JSON output...")
        
        try:
            # Convert DataFrame to records
            theory_schedule = self.theory_df.to_dict('records')
            
            # Clean data for JSON serialization
            def clean_for_json(obj):
                if pd.isna(obj) or obj != obj:  # NaN check
                    return None
                elif isinstance(obj, np.integer):
                    return int(obj)
                elif isinstance(obj, np.floating):
                    if np.isnan(obj) or np.isinf(obj):
                        return None
                    return float(obj)
                elif isinstance(obj, (np.bool_, bool)):
                    return bool(obj)
                return obj
            
            # Clean the data
            clean_schedule = []
            for session in theory_schedule:
                clean_session = {k: clean_for_json(v) for k, v in session.items()}
                clean_schedule.append(clean_session)
            
            # Save JSON
            json_file = f"data/timetable/combined_schedule_theory_redistributed_{timestamp}.json"
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(clean_schedule, f, indent=2, default=str)
            
            logger.info(f"✅ JSON output saved to: {json_file}")
            
        except Exception as e:
            logger.error(f"Failed to save JSON output: {e}")
    
    def _generate_redistribution_report(self, timestamp):
        """Generate detailed redistribution report."""
        report_file = f"room_redistribution_report_{timestamp}.txt"
        
        try:
            with open(report_file, 'w', encoding='utf-8') as f:
                f.write("THEORY ROOM REDISTRIBUTION REPORT\n")
                f.write("=" * 50 + "\n\n")
                f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                
                # Summary statistics
                total_70_capacity = len(self.theory_df[
                    (self.theory_df['student_count'] == 70) & 
                    (self.theory_df['is_co_scheduled'] == False)
                ])
                
                f.write(f"Total 70-capacity sessions: {total_70_capacity}\n")
                f.write(f"Available 70-capacity rooms: {len(self.available_rooms)}\n\n")
                
                # Department distribution
                f.write("DEPARTMENT DISTRIBUTION:\n")
                dept_stats = self.theory_df[
                    (self.theory_df['student_count'] == 70) & 
                    (self.theory_df['is_co_scheduled'] == False)
                ].groupby(['department', 'block']).size().reset_index(name='sessions')
                
                for dept in dept_stats['department'].unique():
                    dept_data = dept_stats[dept_stats['department'] == dept]
                    preferred_block = self.dept_block_preference.get(dept, 'A Block')
                    f.write(f"\n{dept} (Preferred: {preferred_block}):\n")
                    
                    total_dept_sessions = dept_data['sessions'].sum()
                    for _, row in dept_data.iterrows():
                        block = row['block']
                        sessions = row['sessions']
                        percentage = (sessions / total_dept_sessions) * 100
                        f.write(f"  {block}: {sessions} sessions ({percentage:.1f}%)\n")
                
                # Block utilization
                f.write("\nBLOCK UTILIZATION:\n")
                block_stats = self.theory_df[
                    (self.theory_df['student_count'] == 70) & 
                    (self.theory_df['is_co_scheduled'] == False)
                ].groupby('block').size()
                
                for block, count in block_stats.items():
                    available_rooms = len(self.rooms_by_block.get(block, []))
                    f.write(f"{block}: {count} sessions using {available_rooms} available rooms\n")
                
                # Room efficiency metrics
                f.write("\nROOM EFFICIENCY:\n")
                room_usage = self.theory_df[
                    (self.theory_df['student_count'] == 70) & 
                    (self.theory_df['is_co_scheduled'] == False)
                ].groupby('room_id').size()
                
                f.write(f"Rooms used: {len(room_usage)} out of {len(self.available_rooms)} available\n")
                f.write(f"Average sessions per room: {room_usage.mean():.1f}\n")
                f.write(f"Max sessions in one room: {room_usage.max()}\n")
                f.write(f"Min sessions in used rooms: {room_usage.min()}\n")
                
            logger.info(f"✅ Redistribution report saved to: {report_file}")
            
        except Exception as e:
            logger.error(f"Failed to generate report: {e}")


def main():
    """Main function to run the room redistribution."""
    logger.info("🚀 Starting Theory Room Redistribution...")
    
    try:
        # Create redistributor
        redistributor = TheoryRoomRedistributor()
        
        # Perform redistribution
        stats = redistributor.redistribute_rooms()
        
        # Save results
        redistributor.save_results()
        
        logger.info("🎉 Theory room redistribution completed successfully!")
        return True
        
    except Exception as e:
        logger.error(f"❌ Redistribution failed: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1) 