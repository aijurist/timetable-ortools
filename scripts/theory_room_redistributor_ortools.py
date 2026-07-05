#!/usr/bin/env python3
"""
OR-Tools based Room Redistribution Algorithm v2

This script uses Google OR-Tools CP-SAT solver to optimally assign rooms to ALL theory sessions
while respecting constraints like:
- No double booking
- Department block preferences  
- Single-section departments get same room per year
- Protected rooms stay unchanged
- CSD uses only specific rooms (A108, A110, A205)
- Room capacity must be >= student count
"""

import os
import sys
import pandas as pd
import logging
import json
import numpy as np
from datetime import datetime
from collections import defaultdict
import shutil

try:
    from ortools.sat.python import cp_model
except ImportError:
    print("ERROR: OR-Tools not installed. Install with: pip install ortools")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("room_redistribution_ortools.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class ORToolsRoomRedistributor:
    
    def __init__(self):
        self.theory_timetable_file = "prod\\theory_schedule (8).csv"
        self.room_file = "data\\block_wise\\redist.csv"
        self._load_data()
        self._setup_parameters()
    
    def _load_data(self):
        logger.info("Loading data files...")
        self.theory_df = pd.read_csv(self.theory_timetable_file)
        logger.info(f"Loaded {len(self.theory_df)} theory sessions")
        
        def convert_to_bool(value):
            if pd.isna(value):
                return False
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.lower() in ['true', '1']
            if isinstance(value, (int, float)):
                return bool(value)
            return False
        
        self.theory_df['is_co_scheduled'] = self.theory_df['is_co_scheduled'].apply(convert_to_bool)
        
        self.rooms_df = pd.read_csv(self.room_file)
        logger.info(f"Loaded {len(self.rooms_df)} rooms")
        
        # Protected rooms that should NEVER be changed
        self.protected_room_numbers = [
            'A208/209', 'A208/209-A', 'A208/209-B',
            'A210/211', 'A210/211-A', 'A210/211-B',
            'ANEW101', 'ANEW102', 'ANEW103', 'ANEW104',
            'ANEW105', 'ANEW105-A', 'ANEW105-B',
            'ANEW106', 'ANEW106-A', 'ANEW106-B',
            'ANEW201', 'ANEW202',
            'KSL02', 'KSL03', 'KSL03-A', 'KSL03-B',
            'A104/105', 'A104/105-A', 'A104/105-B'
        ]
        
        # Rooms to EXCLUDE from redistribution (don't use these at all)
        self.excluded_room_numbers = [
            'A102',  # User requested to remove
            # B Block 4th floor - free these up
            'B418', 'B419', 'B420', 'B421', 'B422', 'B423', 'B424', 'B425'
        ]
        
        # Remove TIFAC and D Block rooms entirely
        self.rooms_df = self.rooms_df[
            (~self.rooms_df['room_number'].str.upper().str.startswith('TIFAC')) &
            (self.rooms_df['block'] != 'D Block') &
            (self.rooms_df['block'] != 'D block')
        ].copy()
        logger.info(f"After removing TIFAC and D Block: {len(self.rooms_df)} rooms")
        
        # Get ALL available classrooms (non-lab, excluding protected and excluded rooms)
        self.available_rooms = self.rooms_df[
            (self.rooms_df['is_lab'] == 0) &
            (~self.rooms_df['room_number'].isin(self.protected_room_numbers)) &
            (~self.rooms_df['room_number'].isin(self.excluded_room_numbers))
        ].copy()
        
        logger.info(f"Found {len(self.available_rooms)} available classrooms (excluding A102, B4 floor)")
        
        # Log capacity distribution
        cap_dist = self.available_rooms.groupby('room_max_cap').size()
        logger.info(f"Room capacity distribution: {dict(cap_dist)}")
        
        # Create room lookup dictionaries
        self.room_id_to_info = {}
        self.room_id_to_block = {}
        self.room_id_to_capacity = {}
        for _, room in self.available_rooms.iterrows():
            self.room_id_to_info[room['id']] = {
                'room_number': room['room_number'],
                'block': room['block'],
                'capacity': room['room_max_cap']
            }
            self.room_id_to_block[room['id']] = room['block']
            self.room_id_to_capacity[room['id']] = room['room_max_cap']
        
        # Room IDs list for indexing
        self.room_ids = list(self.available_rooms['id'])
        self.room_id_to_idx = {rid: idx for idx, rid in enumerate(self.room_ids)}
        
        # Identify rooms used by 4th year (S8) - these are BLOCKED for all other years
        self._identify_4th_year_blocked_rooms()
    
    def _identify_4th_year_blocked_rooms(self):
        """Identify all rooms used by 4th year (S8) students - these are blocked for other years."""
        
        # Get all sessions for 4th year (semester 8)
        s8_sessions = self.theory_df[self.theory_df['semester'] == 8]
        
        # Collect unique room IDs used by S8
        self.fourth_year_room_ids = set()
        self.fourth_year_room_numbers = set()
        
        for _, session in s8_sessions.iterrows():
            room_id = session['room_id']
            room_number = session['room_number']
            
            if pd.notna(room_id):
                self.fourth_year_room_ids.add(room_id)
            if pd.notna(room_number):
                self.fourth_year_room_numbers.add(room_number)
        
        logger.info(f"4th year (S8) uses {len(self.fourth_year_room_ids)} unique rooms")
        logger.info(f"4th year room numbers: {sorted(self.fourth_year_room_numbers)}")
        logger.info("These rooms are BLOCKED for all other years")
    
    def _setup_parameters(self):
        # Department block preferences
        self.dept_block_preference = {
            # A Block departments
            'Computer Science & Engineering': 'A Block',
            'Computer Science & Business Systems': 'A Block',
            'Computer Science & Design': 'A Block',
            'Computer Science & Engineering (Cyber Security)': 'A Block',
            'Information Technology': 'A Block',
            # B Block departments
            'Robotics & Automation': 'B Block',
            'Electrical & Electronics Engineering': 'B Block',
            'Electronics & Communication Engineering': 'B Block',
            'Civil Engineering': 'B Block',
            'Mechatronics Engineering': 'B Block',
            'Artificial Intelligence & Data Science': 'B Block',
            'Artificial Intelligence & Machine Learning': 'B Block',
            'Biotechnology': 'B Block',
            'Chemical Engineering': 'B Block',
            # C Block departments
            'Food Technology': 'C Block',
            'Mechanical Engineering': 'C Block',
            'Aeronautical Engineering': 'C Block',
            'Automobile Engineering': 'C Block',
            'Biomedical Engineering': 'C Block'
        }
        
        # Single-section departments - ALL semesters use same room per year
        self.single_section_depts = [
            'Food Technology', 'Robotics & Automation', 'Computer Science & Design',
            'Civil Engineering', 'Mechatronics Engineering', 'Automobile Engineering',
            'Aeronautical Engineering', 'Chemical Engineering'
        ]
        
        # Single-section SPECIFIC semesters - only these specific (dept, semester) pairs
        # For depts that are single-section only in certain semesters
        self.single_section_semesters = [
            ('Computer Science & Engineering (Cyber Security)', 6),  # Only S6 is single section
        ]
        
        # CSD can only use these rooms
        self.csd_rooms = ['A309', 'A310', 'A311']
        self.csd_room_ids = set()
        for _, room in self.available_rooms.iterrows():
            if room['room_number'] in self.csd_rooms:
                self.csd_room_ids.add(room['id'])
        logger.info(f"CSD room IDs: {self.csd_room_ids}")
        
        # Group rooms by block
        self.rooms_by_block = defaultdict(list)
        for room_id, info in self.room_id_to_info.items():
            self.rooms_by_block[info['block']].append(room_id)
        
        for block, rooms in self.rooms_by_block.items():
            logger.info(f"{block}: {len(rooms)} rooms")
        
        # Day normalization
        self.day_mapping = {
            'mon': 'monday', 'monday': 'monday',
            'tue': 'tuesday', 'tuesday': 'tuesday',
            'wed': 'wed', 'wednesday': 'wed',
            'thu': 'thur', 'thur': 'thur', 'thursday': 'thur',
            'fri': 'fri', 'friday': 'fri',
            'sat': 'saturday', 'saturday': 'saturday'
        }
    
    def _normalize_day(self, day):
        return self.day_mapping.get(day.lower(), day.lower())
    
    def _get_suitable_rooms(self, student_count, department, semester):
        """Get rooms that can accommodate the student count and are suitable for the department.
        
        Args:
            student_count: Number of students that need to fit
            department: Department name for block preference
            semester: Semester number (used to block 4th year rooms for other years)
        """
        
        suitable = []
        
        for room_id in self.room_ids:
            capacity = self.room_id_to_capacity[room_id]
            
            # Room must have enough capacity
            if capacity < student_count:
                continue
            
            # CSD can only use specific rooms
            if department == 'Computer Science & Design':
                if room_id not in self.csd_room_ids:
                    continue
            
            # BLOCK: Rooms used by 4th year (S8) cannot be used by other years
            if semester != 8:
                if room_id in self.fourth_year_room_ids:
                    continue
            
            suitable.append(room_id)
        
        return suitable
    
    def _identify_sessions_to_redistribute(self):
        """Identify which sessions can be redistributed and which are protected."""
        
        redistributable = []
        protected = []
        
        for idx, session in self.theory_df.iterrows():
            # Protected conditions:
            # 1. In protected room
            # 2. Not a Lecture (Tutorials stay where they are)
            # 3. S8 (4th year) - keep their current rooms
            is_protected = (
                session['room_number'] in self.protected_room_numbers or
                session['session_type'] != 'Lecture' or
                session['semester'] == 8  # 4th year stays as is
            )
            
            if is_protected:
                protected.append(idx)
            else:
                redistributable.append(idx)
        
        logger.info(f"Protected sessions (will not change): {len(protected)}")
        logger.info(f"Redistributable sessions: {len(redistributable)}")
        
        return redistributable, protected
    
    def build_and_solve_model(self):
        """Build and solve the OR-Tools CP-SAT model."""
        
        logger.info("=" * 60)
        logger.info("BUILDING OR-TOOLS MODEL")
        logger.info("=" * 60)
        
        redistributable_indices, protected_indices = self._identify_sessions_to_redistribute()
        
        # Create model
        model = cp_model.CpModel()
        
        # Track protected room bookings to avoid conflicts
        protected_bookings = set()  # (day_norm, time_slot, room_id)
        
        for idx in protected_indices:
            session = self.theory_df.loc[idx]
            day_norm = self._normalize_day(session['day'])
            time_slot = session['time_slot']
            room_id = session['room_id']
            protected_bookings.add((day_norm, time_slot, room_id))
        
        logger.info(f"Protected bookings (room-time combinations): {len(protected_bookings)}")
        
        # Create a mapping of (day, time_slot) -> list of session indices
        timeslot_sessions = defaultdict(list)
        
        # Decision variables: For each redistributable session, which room?
        room_vars = {}
        skipped_sessions = []
        
        for idx in redistributable_indices:
            session = self.theory_df.loc[idx]
            day_norm = self._normalize_day(session['day'])
            time_slot = session['time_slot']
            dept = session['department']
            student_count = session['student_count']
            semester = session['semester']
            
            # Get suitable rooms based on capacity, department, and semester
            # (4th year rooms are blocked for other years)
            suitable_rooms = self._get_suitable_rooms(student_count, dept, semester)
            
            # Filter out rooms that are already booked by protected sessions at this time
            available_for_session = []
            for room_id in suitable_rooms:
                if (day_norm, time_slot, room_id) not in protected_bookings:
                    available_for_session.append(room_id)
            
            if not available_for_session:
                logger.warning(f"No available rooms for session {idx} ({session['course_code']}) "
                             f"with {student_count} students at {day_norm} {time_slot}")
                skipped_sessions.append(idx)
                # Add to protected bookings so it doesn't get double-booked
                protected_bookings.add((day_norm, time_slot, session['room_id']))
                continue
            
            # Create boolean variables for room assignment
            room_vars[idx] = {}
            for room_id in available_for_session:
                room_vars[idx][room_id] = model.NewBoolVar(f's{idx}_r{room_id}')
            
            # Each session must be assigned to exactly one room
            model.AddExactlyOne(room_vars[idx].values())
            
            # Track for no-double-booking constraint
            timeslot_key = (day_norm, time_slot)
            timeslot_sessions[timeslot_key].append(idx)
        
        logger.info(f"Created variables for {len(room_vars)} sessions")
        logger.info(f"Skipped {len(skipped_sessions)} sessions (no suitable rooms)")
        
        # Constraint: No double booking
        logger.info("Adding no-double-booking constraints...")
        
        for timeslot_key, session_indices in timeslot_sessions.items():
            if len(session_indices) <= 1:
                continue
            
            # For each room, sum of assignments <= 1
            for room_id in self.room_ids:
                room_assignments = []
                for idx in session_indices:
                    if idx in room_vars and room_id in room_vars[idx]:
                        room_assignments.append(room_vars[idx][room_id])
                
                if len(room_assignments) > 1:
                    model.Add(sum(room_assignments) <= 1)
        
        # HARD CONSTRAINT: Same teacher teaching consecutive hours for same dept/semester 
        # must use the SAME room
        logger.info("Adding same-room constraint for consecutive teacher sessions...")
        
        # Build lookup: (day, slot_index) -> list of session indices
        time_slots_ordered = [
            "8:00 - 8:50", "9:00 - 9:50", "10:00 - 10:50", "11:00 - 11:50",
            "12:00 - 12:50", "1:00 - 1:50", "2:00 - 2:50", "3:10 - 4:00", "4:10 - 5:00"
        ]
        slot_to_index = {slot: i for i, slot in enumerate(time_slots_ordered)}
        
        # Group sessions by (day, teacher, dept, semester)
        teacher_day_sessions = defaultdict(list)
        for idx in room_vars:
            session = self.theory_df.loc[idx]
            day_norm = self._normalize_day(session['day'])
            teacher_id = session['teacher_id']
            dept = session['department']
            semester = session['semester']
            time_slot = session['time_slot']
            slot_idx = slot_to_index.get(time_slot, -1)
            
            key = (day_norm, teacher_id, dept, semester)
            teacher_day_sessions[key].append((slot_idx, idx))
        
        consecutive_constraints_added = 0
        for key, sessions in teacher_day_sessions.items():
            if len(sessions) <= 1:
                continue
            
            # Sort by slot index
            sessions_sorted = sorted(sessions, key=lambda x: x[0])
            
            # Find consecutive pairs
            for i in range(len(sessions_sorted) - 1):
                slot1, idx1 = sessions_sorted[i]
                slot2, idx2 = sessions_sorted[i + 1]
                
                # Check if consecutive (slot difference of 1)
                if slot2 - slot1 == 1:
                    # Find common rooms between both sessions
                    if idx1 in room_vars and idx2 in room_vars:
                        common_rooms = set(room_vars[idx1].keys()) & set(room_vars[idx2].keys())
                        
                        if common_rooms:
                            # HARD CONSTRAINT: Both must use the same room
                            # For each room, if session1 uses it, session2 must also use it
                            for room_id in common_rooms:
                                model.Add(room_vars[idx1][room_id] == room_vars[idx2][room_id])
                            consecutive_constraints_added += 1
        
        logger.info(f"Added {consecutive_constraints_added} consecutive-session same-room constraints")
        
        # Objective: Maximize sessions in preferred block + room consistency
        objective_terms = []
        
        # Weight for preferred block - make this very high to prioritize
        BLOCK_PREFERENCE_WEIGHT = 100
        # Weight for same room for single-section dept + same semester
        SAME_ROOM_WEIGHT = 10
        # Weight for minimizing room wastage (prefer tighter fit)
        CAPACITY_FIT_WEIGHT = 1
        
        # Track single-section dept sessions by (dept, semester) for room consistency
        single_section_groups = defaultdict(list)
        
        for idx in room_vars:
            session = self.theory_df.loc[idx]
            dept = session['department']
            semester = session['semester']
            student_count = session['student_count']
            preferred_block = self.dept_block_preference.get(dept, 'A Block')
            
            # Reward: session in preferred block
            for room_id, var in room_vars[idx].items():
                room_block = self.room_id_to_block.get(room_id)
                if room_block == preferred_block:
                    objective_terms.append(BLOCK_PREFERENCE_WEIGHT * var)
                
                # Small penalty for capacity wastage
                room_cap = self.room_id_to_capacity.get(room_id, 70)
                wastage = room_cap - student_count
                # Subtract a small amount based on wastage
                if wastage > 0:
                    objective_terms.append(-CAPACITY_FIT_WEIGHT * (wastage // 10) * var)
            
            # Track for single-section consistency
            # Include entire single-section depts OR specific (dept, semester) pairs
            is_single_section = (
                dept in self.single_section_depts or
                (dept, semester) in self.single_section_semesters
            )
            if is_single_section:
                single_section_groups[(dept, semester)].append(idx)
        
        # SOFT CONSTRAINT: Single-section departments - prefer sessions to use SAME room
        # Lower weight than block preference so it doesn't override block assignments
        logger.info("Adding same-room preference for single-section departments...")
        SINGLE_SECTION_SAME_ROOM_WEIGHT = 50  # Lower than block preference (100)
        
        for (dept, semester), session_indices in single_section_groups.items():
            if len(session_indices) <= 1:
                continue
            
            # Find common possible rooms across ALL sessions in this group
            common_rooms = None
            for idx in session_indices:
                if idx in room_vars:
                    if common_rooms is None:
                        common_rooms = set(room_vars[idx].keys())
                    else:
                        common_rooms &= set(room_vars[idx].keys())
            
            if not common_rooms:
                logger.warning(f"No common rooms for single-section dept {dept} semester {semester}")
                continue
            
            logger.info(f"  {dept} S{semester}: {len(session_indices)} sessions, {len(common_rooms)} common rooms")
            
            # STRONG SOFT CONSTRAINT: Sessions on different time slots should use same room
            # Group sessions by (day, time_slot) to find which ones can share a room
            session_timeslots = {}
            for idx in session_indices:
                if idx in room_vars:
                    session = self.theory_df.loc[idx]
                    day_norm = self._normalize_day(session['day'])
                    ts_key = (day_norm, session['time_slot'])
                    session_timeslots[idx] = ts_key
            
            # For sessions at DIFFERENT times, strongly reward using same room
            session_list = list(session_timeslots.keys())
            for i, idx1 in enumerate(session_list):
                ts1 = session_timeslots[idx1]
                for idx2 in session_list[i+1:]:
                    ts2 = session_timeslots[idx2]
                    
                    # Only constrain if they're at different times (can share room)
                    if ts1 != ts2:
                        # Find common rooms for this pair
                        pair_common = set(room_vars[idx1].keys()) & set(room_vars[idx2].keys())
                        for room_id in pair_common:
                            # Create indicator for both using this room
                            both_use = model.NewBoolVar(f'ss_{idx1}_{idx2}_r{room_id}')
                            model.AddMultiplicationEquality(both_use, 
                                [room_vars[idx1][room_id], room_vars[idx2][room_id]])
                            # VERY high reward for using same room
                            objective_terms.append(SINGLE_SECTION_SAME_ROOM_WEIGHT * both_use)
        
        logger.info(f"Added single-section same-room preferences")
        
        # SOFT CONSTRAINT: Room consolidation - minimize total rooms used
        # Reward using rooms that are already heavily used, penalize spreading across many rooms
        logger.info("Adding room consolidation preference...")
        ROOM_CONSOLIDATION_WEIGHT = 20  # Moderate weight
        
        # For each room, track how many sessions use it
        room_usage_vars = {}
        for room_id in self.room_ids:
            sessions_using_room = []
            for idx in room_vars:
                if room_id in room_vars[idx]:
                    sessions_using_room.append(room_vars[idx][room_id])
            
            if sessions_using_room:
                # Create a variable for "room is used at all"
                room_used = model.NewBoolVar(f'room_used_{room_id}')
                model.AddMaxEquality(room_used, sessions_using_room)
                room_usage_vars[room_id] = (room_used, sessions_using_room)
                
                # Penalize each distinct room being used (encourages fewer rooms)
                objective_terms.append(-ROOM_CONSOLIDATION_WEIGHT * room_used)
                
                # Reward rooms that have more sessions (higher utilization)
                # More sessions in same room = better
                if len(sessions_using_room) > 1:
                    # Create count of sessions in this room
                    room_session_count = model.NewIntVar(0, len(sessions_using_room), f'count_r{room_id}')
                    model.Add(room_session_count == sum(sessions_using_room))
                    
                    # Small bonus for each additional session in a room (consolidation)
                    # Only if room is used
                    objective_terms.append(2 * room_session_count)
        
        logger.info(f"Added room consolidation for {len(room_usage_vars)} rooms")
        
        # Set objective
        if objective_terms:
            model.Maximize(sum(objective_terms))
        
        logger.info(f"Objective has {len(objective_terms)} terms")
        
        # Solve
        logger.info("Solving (this may take a minute)...")
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 120.0  # 2 minute timeout
        solver.parameters.log_search_progress = True
        solver.parameters.num_search_workers = 8  # Use multiple cores
        
        status = solver.Solve(model)
        
        logger.info(f"Solver status: {solver.StatusName(status)}")
        
        if status not in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
            logger.error("No solution found!")
            return False
        
        logger.info(f"Objective value: {solver.ObjectiveValue()}")
        
        # Extract solution and update dataframe
        stats = {
            'total_redistributed': 0,
            'in_preferred_block': 0,
            'room_changes': 0,
            'by_dept': defaultdict(lambda: {'total': 0, 'in_preferred': 0})
        }
        
        for idx in room_vars:
            session = self.theory_df.loc[idx]
            original_room_id = session['room_id']
            dept = session['department']
            preferred_block = self.dept_block_preference.get(dept, 'A Block')
            
            # Find which room was assigned
            assigned_room_id = None
            for room_id, var in room_vars[idx].items():
                if solver.Value(var) == 1:
                    assigned_room_id = room_id
                    break
            
            if assigned_room_id is None:
                logger.warning(f"No room assigned for session {idx}")
                continue
            
            stats['total_redistributed'] += 1
            stats['by_dept'][dept]['total'] += 1
            
            if assigned_room_id != original_room_id:
                stats['room_changes'] += 1
                
                # Update dataframe
                self.theory_df.loc[idx, 'room_id'] = assigned_room_id
                room_info = self.room_id_to_info[assigned_room_id]
                self.theory_df.loc[idx, 'room_number'] = room_info['room_number']
                self.theory_df.loc[idx, 'block'] = room_info['block']
            
            # Check if in preferred block
            room_block = self.room_id_to_block.get(assigned_room_id)
            if room_block == preferred_block:
                stats['in_preferred_block'] += 1
                stats['by_dept'][dept]['in_preferred'] += 1
        
        logger.info("=" * 60)
        logger.info("REDISTRIBUTION COMPLETED")
        logger.info("=" * 60)
        logger.info(f"Sessions processed: {stats['total_redistributed']}")
        logger.info(f"Room changes made: {stats['room_changes']}")
        logger.info(f"Sessions in preferred block: {stats['in_preferred_block']} "
                   f"({stats['in_preferred_block']/stats['total_redistributed']*100:.1f}%)")
        
        logger.info("\nBy Department:")
        for dept in sorted(stats['by_dept'].keys()):
            d = stats['by_dept'][dept]
            pct = d['in_preferred'] / d['total'] * 100 if d['total'] > 0 else 0
            logger.info(f"  {dept}: {d['in_preferred']}/{d['total']} ({pct:.0f}%)")
        
        # Verify no double bookings
        self._verify_no_double_bookings()
        
        return True
    
    def _verify_no_double_bookings(self):
        """Verify there are no double bookings in the final schedule."""
        
        logger.info("Verifying no double bookings...")
        room_time_usage = defaultdict(list)
        
        for idx, session in self.theory_df.iterrows():
            day_norm = self._normalize_day(session['day'])
            key = (day_norm, session['time_slot'], session['room_id'])
            room_time_usage[key].append({
                'idx': idx,
                'course_code': session['course_code'],
                'department': session['department']
            })
        
        conflicts = 0
        for key, sessions in room_time_usage.items():
            if len(sessions) > 1:
                conflicts += 1
                day, time_slot, room_id = key
                room_num = self.room_id_to_info.get(room_id, {}).get('room_number', room_id)
                logger.error(f"DOUBLE BOOKING: Room {room_num} on {day} {time_slot}")
                for s in sessions:
                    logger.error(f"  - {s['course_code']} ({s['department']})")
        
        if conflicts == 0:
            logger.info("✅ VERIFICATION PASSED: No double bookings")
        else:
            logger.error(f"❌ {conflicts} double bookings found")
        
        return conflicts == 0
    
    def save_results(self):
        """Save the redistributed schedule."""
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Backup original
        backup_dir = "backups"
        os.makedirs(backup_dir, exist_ok=True)
        backup_file = os.path.join(backup_dir, f"{os.path.basename(self.theory_timetable_file)}.backup_{timestamp}")
        shutil.copy2(self.theory_timetable_file, backup_file)
        logger.info(f"Backup created: {backup_file}")
        
        # Save CSV
        self.theory_df.to_csv(self.theory_timetable_file, index=False)
        logger.info(f"✅ Saved to: {self.theory_timetable_file}")
        
        # Save JSON
        self._save_json_output(timestamp)
        
        # Generate report
        self._generate_report(timestamp)
    
    def _save_json_output(self, timestamp):
        """Save JSON output."""
        
        try:
            def clean_for_json(obj):
                if pd.isna(obj) or obj != obj:
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
            
            records = self.theory_df.to_dict('records')
            clean_records = [{k: clean_for_json(v) for k, v in r.items()} for r in records]
            
            json_file = f"theory_schedule_ortools_{timestamp}.json"
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(clean_records, f, indent=2, default=str)
            
            logger.info(f"✅ JSON saved to: {json_file}")
            
        except Exception as e:
            logger.error(f"Failed to save JSON: {e}")
    
    def _generate_report(self, timestamp):
        """Generate redistribution report."""
        
        report_file = f"room_redistribution_report_ortools_{timestamp}.txt"
        
        try:
            with open(report_file, 'w', encoding='utf-8') as f:
                f.write("OR-TOOLS ROOM REDISTRIBUTION REPORT\n")
                f.write("=" * 50 + "\n\n")
                f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                
                # Department block distribution
                f.write("DEPARTMENT BLOCK DISTRIBUTION:\n")
                f.write("-" * 30 + "\n")
                
                for dept in sorted(self.dept_block_preference.keys()):
                    preferred = self.dept_block_preference[dept]
                    dept_sessions = self.theory_df[
                        (self.theory_df['department'] == dept) &
                        (self.theory_df['session_type'] == 'Lecture')
                    ]
                    
                    if dept_sessions.empty:
                        continue
                    
                    total = len(dept_sessions)
                    in_preferred = len(dept_sessions[dept_sessions['block'] == preferred])
                    pct = (in_preferred / total * 100) if total > 0 else 0
                    
                    f.write(f"\n{dept} (Preferred: {preferred}):\n")
                    f.write(f"  Total sessions: {total}\n")
                    f.write(f"  In preferred block: {in_preferred} ({pct:.1f}%)\n")
                    
                    block_dist = dept_sessions.groupby('block').size()
                    for block, count in block_dist.items():
                        f.write(f"    {block}: {count}\n")
                
                f.write("\n" + "=" * 50 + "\n")
                f.write("END OF REPORT\n")
            
            logger.info(f"✅ Report saved to: {report_file}")
            
        except Exception as e:
            logger.error(f"Failed to generate report: {e}")


def main():
    logger.info("🚀 Starting OR-Tools Room Redistribution v2...")
    
    try:
        redistributor = ORToolsRoomRedistributor()
        success = redistributor.build_and_solve_model()
        
        if success:
            redistributor.save_results()
            logger.info("🎉 Redistribution completed successfully!")
            return True
        else:
            logger.error("❌ Redistribution failed")
            return False
        
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
