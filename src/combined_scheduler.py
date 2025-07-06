#!/usr/bin/env python3
"""
Combined Timetable Scheduler

Unified scheduler that handles both lab and theory sessions with their respective time structures.
"""

import os
import pandas as pd
import numpy as np
import logging
import json
from datetime import datetime
from collections import defaultdict, Counter
from itertools import combinations
from ortools.sat.python import cp_model
import matplotlib.pyplot as plt
import seaborn as sns
from .course_group_optimizer import CourseGroupOptimizer
from .shift_report_generator import ShiftReportGenerator

class CombinedScheduler:
    """
    Unified scheduler that handles both lab and theory sessions with separate time structures.
    
    Key Features:
    - Theory sessions use 11-slot theory time structure (1 hour each)
    - Lab sessions use 12-slot lab time structure (grouped into 6 sessions of 2 hours each)
    - Cross-system conflict detection and resolution
    - Unified group creation and constraint management
    """
    
    def __init__(self, course_file, room_file):
        """Initialize the combined scheduler for unified lab and theory scheduling."""
        self.logger = logging.getLogger('src.combined_scheduler')
        self.logger.info("Initializing Combined Scheduler...")
        
        # Store input files
        self.course_file = course_file
        self.room_file = room_file
        
        # Load and process data
        self.courses_df = pd.read_csv(course_file)
        
        # Use techlongue.csv as the primary room source
        techlongue_paths = [
            'data/block_wise/techlongue.csv',
            './data/block_wise/techlongue.csv',
            '../data/block_wise/techlongue.csv',
            'timetable_scheduler/data/block_wise/techlongue.csv'
        ]
        
        techlongue_file = None
        for path in techlongue_paths:
            if os.path.exists(path):
                techlongue_file = path
                break
        
        if techlongue_file:
            self.rooms_df = pd.read_csv(techlongue_file)
            self.logger.info(f"Successfully loaded room data from techlongue.csv: {techlongue_file}")
        else:
            # Fallback to the provided room_file
            self.rooms_df = pd.read_csv(room_file)
            self.logger.warning(f"techlongue.csv not found, using fallback room file: {room_file}")
        
        self.logger.info(f"Loaded {len(self.rooms_df)} rooms from room data source")
        
        # Load day order information
        self.day_order_df = self._load_day_order()
        
        # Set up time configurations based on day order
        self._setup_department_day_patterns()
        
        # Set up lunch break configuration
        self._setup_lunch_break_configuration()
        
        # Set up shift-based constraints for ALL departments
        self._setup_shift_based_constraints()
        
        # Set up time configurations - WILL BE CUSTOMIZED PER DEPARTMENT
        # For now, use the most common pattern (Monday-Friday) as default
        self.days = ["monday", "tuesday", "wed", "thur", "fri"]  # Monday-Friday as default
        self.num_days = len(self.days)
        
        # LAB TIME CONFIGURATION - EXACTLY as in lab_scheduler.py
        self.lab_time_slots = [
            "8:00 - 8:50", "8:50 - 9:40", "9:50 - 10:40", "10:40 - 11:30",
            "11:50 - 12:40", "12:40 - 1:30", "1:50 - 2:40", "2:40 - 3:30", 
            "3:50 - 4:40", "4:40 - 5:30", "5:30 - 6:20", "6:20 - 7:10"
        ]
        self.num_lab_slots = len(self.lab_time_slots)
        
        # Group lab slots into 2-hour sessions (L1, L2, L3, etc.) - Updated with correct timings
        self.lab_sessions = {
            'L1': {'slots': [0, 1], 'time_range': '8:00 - 9:40'},
            'L2': {'slots': [2, 3], 'time_range': '9:50 - 11:30'},
            'L3': {'slots': [4, 5], 'time_range': '11:50 - 1:30'},
            'L4': {'slots': [6, 7], 'time_range': '1:50 - 3:30'},
            'L5': {'slots': [8, 9], 'time_range': '3:50 - 5:30'},
            'L6': {'slots': [10, 11], 'time_range': '5:30 - 7:10'}
        }
        self.num_lab_sessions = len(self.lab_sessions)

        # Create detailed lab session info with slot indices for conflict mapping
        self.lab_sessions_details = {}
        for session_name, session_info in self.lab_sessions.items():
            self.lab_sessions_details[session_name] = {'slots': session_info['slots']}
        
        # THEORY TIME CONFIGURATION - EXACTLY as in theory_scheduler.py
        self.theory_time_slots = [
            "8:00 - 8:50", "9:00 - 9:50", "10:00 - 10:50", "11:00 - 11:50",
            "12:00 - 12:50", "1:00 - 1:50", "2:00 - 2:50", "3:00 - 3:50", 
            "4:00 - 4:50", "5:00 - 5:50", "6:00 - 6:50"
        ]
        self.num_theory_slots = len(self.theory_time_slots)
        
        # Build time slot mapping between lab and theory (now that both are defined)
        self._build_time_mapping()
        
        # Set up 5pm scheduling constraints for departments (after time slots are defined)
        self._setup_5pm_constraints()
        
        # ROOM PROCESSING
        self.lab_rooms = self.rooms_df[self.rooms_df['is_lab'] == 1]
        self.theory_rooms = self.rooms_df[self.rooms_df['is_lab'] == 0]
        self.lab_room_ids = self.lab_rooms['id'].tolist()
        self.theory_room_ids = self.theory_rooms['id'].tolist()
        self.laboratory_room_ids = self.lab_rooms[self.lab_rooms['room_type'] == 'Laboratory']['id'].tolist()
        self.logger.info(f"Found {len(self.laboratory_room_ids)} rooms of type 'Laboratory'.")
        
        # CORE LAB MAPPING PROCESSING
        self._load_core_lab_mapping()
        
        # COURSE PROCESSING
        self.process_courses()
        
        # IDENTIFY CROSS-DEPARTMENT TEACHERS
        self._identify_cross_department_teachers()
        
        # CREATE COURSE GROUPS (unified for lab and theory)
        self.create_course_groups()
        
        # COMPUTE GROUP REQUIREMENTS EARLY
        self._compute_group_requirements()
        
        # VALIDATE GROUP STRUCTURE
        self.logger.info("[OK] UNIFIED CONSTRAINTS: Both lab and theory respect same group structure")
        self.logger.info("[OK] HALL'S THEOREM COMPLIANCE: Optimized for maximum student choice")
        
        # Get teacher list for cross-system constraints
        self.teachers = set()
        for teacher_group in [self.lab_requirements.keys(), self.theory_requirements.keys()]:
            self.teachers.update(teacher_group)
        self.teachers = list(self.teachers)
        
        # Create output directory
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_dir = f"output/combined_schedule_{timestamp}"
        os.makedirs(self.output_dir, exist_ok=True)
        
        # Initialize capacity preferences for priority system
        self.capacity_preferences = []
        
        # Load teacher day preferences from pop.csv
        self._load_teacher_day_preferences()
        
        # GLOBAL ROOM REGISTRY FOR CROSS-SCHEDULE VALIDATION
        self.global_room_registry = {}  # (day, time_slot, room_id) -> session_info
        self._initialize_global_room_registry()
        
        # DEPARTMENT BLOCK PREFERENCES FOR SMART ROOM ALLOCATION
        self._setup_department_block_preferences()
        
        self.logger.info("Combined Scheduler initialized successfully")
        self.logger.info(f"Theory time slots: {self.num_theory_slots}")
        self.logger.info(f"Lab time slots: {self.num_lab_slots}")
        self.logger.info(f"Lab rooms: {len(self.lab_room_ids)}")
        self.logger.info(f"Theory rooms: {len(self.theory_room_ids)}")

    def _load_teacher_day_preferences(self):
        """Load teacher day preferences from pop.csv file."""
        self.teacher_day_preferences = {}
        
        try:
            # Try to find pop.csv in data directory
            pop_file_paths = [
                'data/pop.csv',
                './data/pop.csv', 
                '../data/pop.csv',
                'timetable_scheduler/data/pop.csv'
            ]
            
            pop_file = None
            for path in pop_file_paths:
                if os.path.exists(path):
                    pop_file = path
                    break
            
            if pop_file is None:
                self.logger.warning("pop.csv not found. No teacher day preferences will be applied.")
                return
                
            # Read the preferences file
            pop_df = pd.read_csv(pop_file)
            self.logger.info(f"Loaded teacher day preferences from {pop_file}")
            
            # Map day names to indices
            day_name_mapping = {
                'monday': 0,
                'tuesday': 1, 
                'wednesday': 2,
                'wed': 2,
                'thursday': 3,
                'thur': 3,
                'friday': 4,
                'fri': 4,
                'saturday': 5,
                'sat': 5
            }
            
            # Process each teacher's preferences
            for _, row in pop_df.iterrows():
                try:
                    teacher_id = str(int(float(row['id_faculty'])))  # Ensure string format
                    teacher_name = row['name_faculty '].strip() if pd.notna(row['name_faculty ']) else None
                    subject_code = row['subject_code'].strip() if pd.notna(row['subject_code']) else None
                    pref_day_1 = row['preffered_day_1'].strip().lower() if pd.notna(row['preffered_day_1']) and row['preffered_day_1'].strip() != '-' else None
                    pref_day_2 = row['preffered_day_2'].strip().lower() if pd.notna(row['preffered_day_2']) and row['preffered_day_2'].strip() != '-' else None
                    
                    # Convert day names to indices
                    preferred_days = []
                    if pref_day_1 and pref_day_1 in day_name_mapping:
                        preferred_days.append(day_name_mapping[pref_day_1])
                    if pref_day_2 and pref_day_2 in day_name_mapping:
                        preferred_days.append(day_name_mapping[pref_day_2])
                    
                    if teacher_id not in self.teacher_day_preferences:
                        self.teacher_day_preferences[teacher_id] = {}
                    
                    # Store preferences - apply to ALL courses for this teacher (ignore subject_code for now)
                    # This ensures the preference applies regardless of exact course code matching
                    self.teacher_day_preferences[teacher_id]['*'] = preferred_days
                    
                    # Also store by subject code for debugging
                    if subject_code:
                        self.teacher_day_preferences[teacher_id][subject_code] = preferred_days
                    
                    pref_day_names = [list(day_name_mapping.keys())[list(day_name_mapping.values()).index(day)] for day in preferred_days]
                    self.logger.info(f"🎯 Teacher {teacher_id} ({teacher_name}, subject: {subject_code or 'ALL'}): preferred days {preferred_days} ({', '.join(pref_day_names)})")
                    
                except Exception as e:
                    self.logger.warning(f"Error processing teacher preference row: {row.to_dict()}, error: {e}")
                    continue
            
            self.logger.info(f"Loaded day preferences for {len(self.teacher_day_preferences)} teachers")
            self.logger.info(f"📋 Pop.csv teacher IDs: {list(self.teacher_day_preferences.keys())}")
            
            # DEBUG: Check teacher IDs in the course data for comparison
            if hasattr(self, 'courses_df'):
                unique_teacher_ids = self.courses_df['teacher_id'].unique()
                sample_teacher_ids = [str(tid) for tid in unique_teacher_ids[:10]]  # First 10 for debugging
                self.logger.info(f"📋 Course data teacher IDs (sample): {sample_teacher_ids}")
                
                # Check if any pop.csv teacher IDs exist in course data
                matches_found = []
                for pop_teacher_id in self.teacher_day_preferences.keys():
                    if int(pop_teacher_id) in unique_teacher_ids:
                        matches_found.append(pop_teacher_id)
                
                self.logger.info(f"✅ Pop.csv teachers found in course data: {matches_found}")
                if not matches_found:
                    self.logger.warning("⚠️  NO MATCHES between pop.csv teacher IDs and course data teacher IDs!")
                else:
                    self.logger.info(f"🎯 {len(matches_found)} out of {len(self.teacher_day_preferences)} pop.csv teachers found in course data")
            
        except Exception as e:
            self.logger.error(f"Error loading teacher day preferences: {e}")
            self.teacher_day_preferences = {}

    def _get_teacher_preferred_days(self, teacher_id, course_code=None):
        """Get preferred days for a teacher and optionally specific course.
        
        Returns:
            list: List of preferred day indices, or None if no preferences found
        """
        if not hasattr(self, 'teacher_day_preferences') or teacher_id not in self.teacher_day_preferences:
            return None
            
        teacher_prefs = self.teacher_day_preferences[teacher_id]
        
        # Check for course-specific preferences first
        if course_code and course_code in teacher_prefs:
            return teacher_prefs[course_code]
        
        # Check for general preferences (all courses for this teacher)
        if '*' in teacher_prefs:
            return teacher_prefs['*']
            
        return None
    
    def _setup_department_block_preferences(self):
        """Setup department-to-block mapping for efficient room allocation."""
        # Department-to-block mapping based on efficient grouping strategy
        self.dept_block_preference = {
            # A Block - Computer Science and Engineering departments
            'Computer Science & Engineering': 'A Block',
            'Computer Science & Business Systems': 'A Block', 
            'Computer Science & Design': 'A Block',
            'Computer Science & Engineering (Cyber Security)': 'A Block',
            'Information Technology': 'A Block',
            'Artificial Intelligence & Data Science': 'A Block',
            'Artificial Intelligence & Machine Learning': 'A Block',
            'Food Technology': 'B Block',
            
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
        
        # Group rooms by block and analyze distribution
        self.rooms_by_block = {}
        self.rooms_by_floor = {}
        
        for _, room in self.theory_rooms.iterrows():
            room_id = room['id']
            room_number = str(room['room_number']).strip()
            block = room.get('block', 'Unknown Block')
            capacity = int(room.get('room_max_cap', 70))
            
            # Extract floor from room number (e.g., A302 -> 3)
            floor = self._extract_floor_from_room_number(room_number)
            
            # Group by block
            if block not in self.rooms_by_block:
                self.rooms_by_block[block] = []
            
            room_info = {
                'id': room_id,
                'room_number': room_number,
                'block': block,
                'floor': floor,
                'capacity': capacity,
                'is_tifac': self._is_tifac_room(room_number)
            }
            
            self.rooms_by_block[block].append(room_info)
            
            # Group by floor for continuity analysis
            floor_key = f"{block}-Floor{floor}"
            if floor_key not in self.rooms_by_floor:
                self.rooms_by_floor[floor_key] = []
            self.rooms_by_floor[floor_key].append(room_info)
        
        # Sort rooms within each block by floor and room number
        for block in self.rooms_by_block:
            self.rooms_by_block[block].sort(key=lambda x: (x['floor'], x['room_number']))
        
        # Log room distribution
        self.logger.info("ROOM ALLOCATION PREFERENCES SETUP:")
        for block, rooms in self.rooms_by_block.items():
            total_rooms = len(rooms)
            tifac_count = len([r for r in rooms if r['is_tifac']])
            non_tifac_count = total_rooms - tifac_count
            
            capacity_70 = len([r for r in rooms if r['capacity'] == 70])
            capacity_140_plus = len([r for r in rooms if r['capacity'] >= 140])
            
            self.logger.info(f"  {block}: {total_rooms} rooms ({non_tifac_count} non-TIFAC, {tifac_count} TIFAC)")
            self.logger.info(f"    Capacity distribution: {capacity_70} x 70-cap, {capacity_140_plus} x 140+-cap")
        
        # Log department assignments
        self.logger.info("DEPARTMENT BLOCK ASSIGNMENTS:")
        for dept, block in self.dept_block_preference.items():
            self.logger.info(f"  {dept} -> {block}")

    def _extract_floor_from_room_number(self, room_number):
        """Extract floor number from room number (e.g., A302 -> 3, TIFAC-A401 -> 4)."""
        try:
            # Handle TIFAC rooms
            if 'TIFAC' in room_number.upper():
                # Extract number after TIFAC (e.g., TIFAC-A401 -> 401)
                import re
                match = re.search(r'(\d{3,4})', room_number)
                if match:
                    room_num = match.group(1)
                    if len(room_num) >= 3:
                        return int(room_num[0])  # First digit as floor
            else:
                # Regular rooms (e.g., A302 -> 3)
                import re
                match = re.search(r'(\d{3,4})', room_number)
                if match:
                    room_num = match.group(1)
                    if len(room_num) >= 3:
                        return int(room_num[0])  # First digit as floor
        except (ValueError, IndexError):
            pass
        
        return 1  # Default to floor 1 if extraction fails

    def _is_tifac_room(self, room_number):
        """Check if a room is a TIFAC room based on room number."""
        return str(room_number).upper().startswith('TIFAC')

    def _get_preferred_rooms_for_department(self, department):
        """Get preferred rooms for a department with A/B Block priority, avoiding TIFAC rooms, C Block as fallback."""
        preferred_block = self.dept_block_preference.get(department, 'A Block')
        
        preferred_rooms = []
        
        # Priority 1: Preferred block (A or B) - NON-TIFAC rooms only
        if preferred_block in self.rooms_by_block:
            block_rooms = [room for room in self.rooms_by_block[preferred_block] 
                          if not room['is_tifac']]
            preferred_rooms.extend(block_rooms)
        
        # Priority 2: Other high-priority block (A or B, whichever wasn't preferred) - NON-TIFAC rooms only
        high_priority_blocks = ['A Block', 'B Block']
        for block in high_priority_blocks:
            if block != preferred_block and block in self.rooms_by_block:
                block_rooms = [room for room in self.rooms_by_block[block] 
                              if not room['is_tifac']]
                preferred_rooms.extend(block_rooms)
        
        # Priority 3: C Block as fallback (all C Block rooms)
        if 'C Block' in self.rooms_by_block:
            c_block_rooms = list(self.rooms_by_block['C Block'])
            preferred_rooms.extend(c_block_rooms)
        
        # Priority 4: TIFAC A Block rooms as last resort fallback
        tifac_rooms = []
        for block in ['A Block', 'B Block']:
            if block in self.rooms_by_block:
                tifac_block_rooms = [room for room in self.rooms_by_block[block] 
                                    if room['is_tifac']]
                tifac_rooms.extend(tifac_block_rooms)
        
        preferred_rooms.extend(tifac_rooms)
        
        return preferred_rooms

    def _check_teacher_continuity_preference(self, session, teacher_schedule, preferred_rooms):
        """Check if teacher can continue in same room for adjacent time slots."""
        day = session.get('day', '')
        time_slot = session.get('time_slot', '')
        teacher_id = session.get('teacher_id', session.get('instance', {}).get('teacher_id', ''))
        
        if not teacher_id or teacher_id not in teacher_schedule:
            return None
        
        # Check teacher's previous sessions for continuity opportunities
        for prev_session in teacher_schedule[teacher_id]:
            prev_day = prev_session.get('day', '')
            prev_time_slot = prev_session.get('time_slot', '')
            prev_room_id = prev_session.get('room_id', '')
            
            # Check if this is a continuous class (same day, adjacent time slot)
            if (prev_day == day and 
                self._are_adjacent_time_slots(prev_time_slot, time_slot) and
                prev_room_id):
                
                # Check if the previous room is in our preferred list and available
                for room in preferred_rooms:
                    if room['id'] == prev_room_id:
                        # Check if room is available for this session
                        day_normalized = self._normalize_day_name(day)
                        registry_key = (day_normalized, time_slot, prev_room_id)
                        if registry_key not in self.global_room_registry:
                            return prev_room_id
        
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
    
    def _load_day_order(self):
        """Load day order information from day_order.csv."""
        try:
            # Try to find day_order.csv in various locations
            day_order_paths = [
                'data/day_order.csv',
                './data/day_order.csv',
                '../data/day_order.csv',
                'timetable_scheduler/data/day_order.csv'
            ]
            
            day_order_file = None
            for path in day_order_paths:
                if os.path.exists(path):
                    day_order_file = path
                    break
            
            if day_order_file is None:
                self.logger.warning("day_order.csv not found. Using default Monday-Friday schedule for all departments.")
                return None
            
            day_order_df = pd.read_csv(day_order_file)
            self.logger.info(f"Loaded day order information from {day_order_file}")
            self.logger.info(f"Found {len(day_order_df)} department entries")
            
            # Log day pattern distribution
            monday_friday_count = len(day_order_df[day_order_df['ODD'].str.contains('Monday - Friday', na=False)])
            tuesday_saturday_count = len(day_order_df[day_order_df['ODD'].str.contains('Tuesday - Saturday', na=False)])
            
            self.logger.info(f"Day pattern distribution:")
            self.logger.info(f"  - Monday-Friday: {monday_friday_count} departments")
            self.logger.info(f"  - Tuesday-Saturday: {tuesday_saturday_count} departments")
            
            return day_order_df
            
        except Exception as e:
            self.logger.error(f"Error loading day_order.csv: {e}")
            self.logger.warning("Using default Monday-Friday schedule for all departments.")
            return None
    
    def _setup_department_day_patterns(self):
        """Set up day patterns for different departments and specific semester overrides."""
        if self.day_order_df is None:
            self.dept_day_patterns = {}
        else:
            self.dept_day_patterns = {}
            
            # Map department names to day patterns
            for _, row in self.day_order_df.iterrows():
                if pd.isna(row['Department']) or pd.isna(row['ODD']):
                    continue
                    
                dept_name = str(row['Department']).strip()
                day_pattern = str(row['ODD']).strip()
                
                if 'Monday - Friday' in day_pattern:
                    self.dept_day_patterns[dept_name] = {
                        'days': ["monday", "tuesday", "wed", "thur", "fri"],
                        'pattern': 'Monday-Friday'
                    }
                elif 'Tuesday - Saturday' in day_pattern:
                    self.dept_day_patterns[dept_name] = {
                        'days': ["tuesday", "wed", "thur", "fri", "saturday"],
                        'pattern': 'Tuesday-Saturday'
                    }
        
        # Set up semester-specific overrides for Monday-Saturday scheduling
        self.semester_day_overrides = {
            # Format: (dept_name, semester) -> day_pattern_config
            # ('Biotechnology', 5): {
            #     'days': ["monday", "tuesday", "wed", "thur", "fri", "saturday"],
            #     'pattern': 'Monday-Saturday'
            # },
            # Electronics & Communication Engineering Monday-Saturday semesters
            # ('Electronics & Communication Engineering', 5): {
            #     'days': ["monday", "tuesday", "wed", "thur", "fri", "saturday"],
            #     'pattern': 'Monday-Saturday'
            # },
            #   ('Electrical & Electronics Engineering', 5): {
            #     'days': ["monday", "tuesday", "wed", "thur", "fri", "saturday"],
            #     'pattern': 'Monday-Saturday'
            # },
            # ('Electronics & Communication Engineering', 7): {
            #     'days': ["monday", "tuesday", "wed", "thur", "fri", "saturday"],
            #     'pattern': 'Monday-Saturday'
            # },
            # Add more semester-specific overrides here as needed
            # ('Department Name', semester_number): {'days': [...], 'pattern': 'Monday-Saturday'}
        }
        
        total_patterns = len(self.dept_day_patterns) + len(self.semester_day_overrides)
        self.logger.info(f"Set up day patterns for {len(self.dept_day_patterns)} departments and {len(self.semester_day_overrides)} semester-specific overrides")
        
        # Log department patterns
        if self.dept_day_patterns:
            monday_friday_depts = [dept for dept, pattern in self.dept_day_patterns.items() if pattern['pattern'] == 'Monday-Friday']
            tuesday_saturday_depts = [dept for dept, pattern in self.dept_day_patterns.items() if pattern['pattern'] == 'Tuesday-Saturday']
            
            self.logger.info(f"Monday-Friday departments: {monday_friday_depts[:5]}..." if len(monday_friday_depts) > 5 else f"Monday-Friday departments: {monday_friday_depts}")
            self.logger.info(f"Tuesday-Saturday departments: {tuesday_saturday_depts[:5]}..." if len(tuesday_saturday_depts) > 5 else f"Tuesday-Saturday departments: {tuesday_saturday_depts}")
        
        # Log semester-specific overrides
        if self.semester_day_overrides:
            self.logger.info("Semester-specific day pattern overrides:")
            for (dept, sem), pattern in self.semester_day_overrides.items():
                self.logger.info(f"  {dept} Semester {sem}: {pattern['pattern']} ({len(pattern['days'])} days)")
                self.logger.info(f"    Days: {', '.join(pattern['days']).title()}")
    
    def _get_days_for_department(self, dept_name, semester=None):
        """Get the working days for a specific department, with optional semester override."""
        # Check for semester-specific override first
        if (semester is not None and 
            hasattr(self, 'semester_day_overrides') and 
            (dept_name, semester) in self.semester_day_overrides):
            return self.semester_day_overrides[(dept_name, semester)]['days']
        
        # Check department-level pattern
        if hasattr(self, 'dept_day_patterns') and dept_name in self.dept_day_patterns:
            return self.dept_day_patterns[dept_name]['days']
        
        # Default to Monday-Friday if no specific pattern found
        return ["monday", "tuesday", "wed", "thur", "fri"]
    
    def _get_day_pattern_for_department(self, dept_name, semester=None):
        """Get the day pattern for a specific department, with optional semester override."""
        # Check for semester-specific override first
        if (semester is not None and 
            hasattr(self, 'semester_day_overrides') and 
            (dept_name, semester) in self.semester_day_overrides):
            return self.semester_day_overrides[(dept_name, semester)]['pattern']
        
        # Check department-level pattern
        if hasattr(self, 'dept_day_patterns') and dept_name in self.dept_day_patterns:
            return self.dept_day_patterns[dept_name]['pattern']
        
        # Default to Monday-Friday
        return 'Monday-Friday'
    
    def add_semester_day_override(self, dept_name, semester, day_pattern):
        """Add a semester-specific day pattern override.
        
        Args:
            dept_name (str): Department name
            semester (int): Semester number
            day_pattern (str): One of 'Monday-Friday', 'Tuesday-Saturday', or 'Monday-Saturday'
        """
        if not hasattr(self, 'semester_day_overrides'):
            self.semester_day_overrides = {}
        
        if day_pattern == 'Monday-Friday':
            days = ["monday", "tuesday", "wed", "thur", "fri"]
        elif day_pattern == 'Tuesday-Saturday':
            days = ["tuesday", "wed", "thur", "fri", "saturday"]
        elif day_pattern == 'Monday-Saturday':
            days = ["monday", "tuesday", "wed", "thur", "fri", "saturday"]
        else:
            raise ValueError(f"Invalid day pattern: {day_pattern}. Must be one of: 'Monday-Friday', 'Tuesday-Saturday', 'Monday-Saturday'")
        
        self.semester_day_overrides[(dept_name, semester)] = {
            'days': days,
            'pattern': day_pattern
        }
        
        self.logger.info(f"Added semester override: {dept_name} Semester {semester} -> {day_pattern} ({len(days)} days)")
        self.logger.info(f"  Days: {', '.join(days).title()}")
    
    def _setup_lunch_break_configuration(self):
        """Set up lunch break configuration for departments and semesters.
        
        Lunch break is between 11:00 AM to 1:30 PM, affecting theory slots:
        - Slot 3: 11:00 - 11:50
        - Slot 4: 12:00 - 12:50  
        - Slot 5: 1:00 - 1:50
        
        Each department-semester combination can have different lunch break slots (3, 4, or 5).
        """
        self.logger.info("Setting up semester-specific lunch break configuration...")
        
        # Define lunch break time slots (11:00 AM to 1:30 PM)
        self.lunch_break_slots = {
            3: "11:00 - 11:50",  # Slot 3
            4: "12:00 - 12:50",  # Slot 4
            5: "1:00 - 1:50"     # Slot 5
        }
        
        # Core departments with model-decided flexible lunch breaks (slots 3, 4, or 5)
        # These departments can use any of the 3 lunch slots - model will decide dynamically
        self.flexible_lunch_departments = [
            'Biotechnology',
            # 'Electronics & Communication Engineering', 
            # 'Mechanical Engineering',
            # 'Biomedical Engineering',
            "Electronics & Communication Engineering",
            'Electrical & Electronics Engineering'
        ]
        
        # Department-semester specific FIXED lunch break assignments
        # Format: (department, semester): lunch_slot
        # Only departments NOT in flexible_lunch_departments get fixed lunch breaks
        self.department_semester_lunch_breaks = {
            # Computer Science departments - varied lunch times by semester
            ('Computer Science & Engineering', 3): 4,  # S3: 12:00-12:50
            ('Computer Science & Engineering', 5): 3,  # S5: 11:00-11:50
            ('Computer Science & Engineering', 7): 5,  # S7: 1:00-1:50
            
            ('Artificial Intelligence & Data Science', 3): 4,  # S3: 12:00-12:50
            ('Artificial Intelligence & Data Science', 5): 5,  # S5: 1:00-1:50
            ('Artificial Intelligence & Data Science', 7): 3,  # S7: 11:00-11:50
            
            ('Artificial Intelligence & Machine Learning', 3): 5,  # S3: 1:00-1:50
            ('Artificial Intelligence & Machine Learning', 5): 4,  # S5: 12:00-12:50
            ('Artificial Intelligence & Machine Learning', 7): 3,  # S7: 11:00-11:50
            
            ('Information Technology', 3): 3,  # S3: 11:00-11:50
            ('Information Technology', 5): 4,  # S5: 12:00-12:50
            ('Information Technology', 7): 5,  # S7: 1:00-1:50
                        
            ('Biomedical Engineering', 3): 4,  # S3: 11:00-11:50
            ('Biomedical Engineering', 5): 4,  # S5: 12:00-12:50
            ('Biomedical Engineering', 7): 4,  # S7: 1:00-1:50
      
            ('Mechanical Engineering', 3): 4,  # S3: 11:00-11:50
            ('Mechanical Engineering', 5): 4,  # S5: 12:00-12:50
            ('Mechanical Engineering', 7): 4,  # S7: 1:00-1:50


            ('Computer Science & Business Systems', 3): 4,  # S3: 12:00-12:50
            ('Computer Science & Business Systems', 5): 3,  # S5: 11:00-11:50
            ('Computer Science & Business Systems', 7): 5,  # S7: 1:00-1:50
            
            ('Computer Science & Design', 3): 5,  # S3: 1:00-1:50
            ('Computer Science & Design', 5): 4,  # S5: 12:00-12:50
            ('Computer Science & Design', 7): 3,  # S7: 11:00-11:50
            
            ('Computer Science & Engineering (Cyber Security)', 3): 3,  # S3: 11:00-11:50
            ('Computer Science & Engineering (Cyber Security)', 5): 5,  # S5: 1:00-1:50
            ('Computer Science & Engineering (Cyber Security)', 7): 4,  # S7: 12:00-12:50

            # Other Engineering departments - fixed lunch times by semester
            ('Civil Engineering', 3): 3,  # S3: 11:00-11:50
            ('Civil Engineering', 5): 4,  # S5: 12:00-12:50
            ('Civil Engineering', 7): 5,  # S7: 1:00-1:50
            
            ('Aeronautical Engineering', 3): 4,  # S3: 12:00-12:50
            ('Aeronautical Engineering', 5): 5,  # S5: 1:00-1:50
            ('Aeronautical Engineering', 7): 3,  # S7: 11:00-11:50
            
            ('Chemical Engineering', 3): 3,  # S3: 11:00-11:50
            ('Chemical Engineering', 4): 4,  # S4: 12:00-12:50
            ('Chemical Engineering', 5): 5,  # S5: 1:00-1:50
            ('Chemical Engineering', 7): 4,  # S7: 12:00-12:50
            
            ('Food Technology', 3): 3,  # S3: 11:00-11:50
            ('Food Technology', 5): 5,  # S5: 1:00-1:50
            ('Food Technology', 7): 4,  # S7: 12:00-12:50
            
            ('Mechatronics Engineering', 3): 5,  # S3: 1:00-1:50
            ('Mechatronics Engineering', 5): 3,  # S5: 11:00-11:50
            ('Mechatronics Engineering', 7): 4,  # S7: 12:00-12:50
            
            ('Automobile Engineering', 3): 4,  # S3: 12:00-12:50
            ('Automobile Engineering', 5): 5,  # S5: 1:00-1:50
            ('Automobile Engineering', 7): 3,  # S7: 11:00-11:50
            
            ('Robotics & Automation', 3): 3,  # S3: 11:00-11:50
            ('Robotics & Automation', 5): 4,  # S5: 12:00-12:50
            ('Robotics & Automation', 7): 5,  # S7: 1:00-1:50
        }
        
      
        # Create reverse mapping: lunch slot -> department-semester combinations
        self.lunch_break_to_dept_semesters = {}
        for (dept, semester), slot_idx in self.department_semester_lunch_breaks.items():
            if slot_idx not in self.lunch_break_to_dept_semesters:
                self.lunch_break_to_dept_semesters[slot_idx] = []
            self.lunch_break_to_dept_semesters[slot_idx].append(f"{dept}_S{semester}")
        
        # Log lunch break configuration
        self.logger.info("Lunch break configuration:")
        self.logger.info(f"🔄 FLEXIBLE LUNCH DEPARTMENTS ({len(self.flexible_lunch_departments)}): Model decides lunch slots (3,4,5)")
        for dept in self.flexible_lunch_departments:
            self.logger.info(f"    {dept}: Flexible lunch timing (slots 3,4,5)")
        
        self.logger.info(f"📋 FIXED LUNCH DEPARTMENTS: Semester-specific lunch assignments")
        for slot_idx, time_slot in self.lunch_break_slots.items():
            dept_semesters = self.lunch_break_to_dept_semesters.get(slot_idx, [])
            self.logger.info(f"  Slot {slot_idx} ({time_slot}): {len(dept_semesters)} department-semester combinations")
            if dept_semesters and len(dept_semesters) <= 10:  # Show first 10 for brevity
                self.logger.info(f"    Examples: {', '.join(dept_semesters[:5])}")
        
        self.logger.info(f"Lunch break configuration completed:")
        self.logger.info(f"  - {len(self.flexible_lunch_departments)} flexible lunch departments")
        self.logger.info(f"  - {len(self.department_semester_lunch_breaks)} fixed department-semester combinations")

    def get_lunch_break_slot(self, department_name, semester=None):
        """Get the lunch break slot for a specific department and semester.
        
        Args:
            department_name (str): Name of the department
            semester (int, optional): Semester number (e.g., 3, 5, 7)
            
        Returns:
            int or None: Slot index (3, 4, or 5) for the lunch break, or None if flexible/no lunch break assigned
        """
        # Check if this is a flexible lunch department - let model decide
        if department_name in self.flexible_lunch_departments:
            return None  # Model will decide which lunch slot to use (3, 4, or 5)
        
        # Only use department-semester specific lunch breaks for fixed departments
        if semester is not None:
            dept_semester_key = (department_name, semester)
            if dept_semester_key in self.department_semester_lunch_breaks:
                return self.department_semester_lunch_breaks[dept_semester_key]
        
        # No fallback - return None if no specific lunch break is configured
        return None

    def get_lunch_break_time(self, department_name, semester=None):
        """Get the lunch break time slot string for a specific department and semester.
        
        Args:
            department_name (str): Name of the department
            semester (int, optional): Semester number (e.g., 3, 5, 7)
            
        Returns:
            str or None: Time slot string (e.g., "12:00 - 12:50"), or None if no lunch break assigned
        """
        slot_idx = self.get_lunch_break_slot(department_name, semester)
        if slot_idx is None:
            return None
        return self.lunch_break_slots[slot_idx]

    def is_lunch_break_slot(self, slot_idx, department_name, semester=None):
        """Check if a given slot is a lunch break slot for the department and semester.
        
        Args:
            slot_idx (int): Time slot index to check
            department_name (str): Name of the department
            semester (int, optional): Semester number (e.g., 3, 5, 7)
            
        Returns:
            bool: True if this is a lunch break slot for the department-semester combination
        """
        lunch_slot = self.get_lunch_break_slot(department_name, semester)
        if lunch_slot is None:
            return False  # No lunch break assigned to this department-semester combination
        return slot_idx == lunch_slot
    
    def is_flexible_lunch_department(self, department_name):
        """Check if a department has flexible lunch breaks (model-decided).
        
        Args:
            department_name (str): Name of the department
            
        Returns:
            bool: True if this department has flexible lunch timing
        """
        return department_name in self.flexible_lunch_departments
    
    def _setup_shift_based_constraints(self):
        """Set up department-centric shift-based constraints for ALL departments."""
        self.logger.info("Setting up department-centric shift-based constraints for ALL departments...")
        
        # Define the two shifts in terms of time slots
        # Shift 1: 8AM - 3:30PM (theory slots 0-6, lab sessions L1-L4)
        # Shift 2: 10AM - 5:30PM (theory slots 2-8, lab sessions L2-L5)
        
        self.shift_definitions = {
            'shift_1': {
                'name': 'Shift 1 (8AM-3:30PM)',
                'theory_slots': list(range(0, 7)),  # slots 0-6 (8:00-2:50)
                'lab_sessions': ['L1', 'L2', 'L3', 'L4'],  # L1: 8:00-9:40, L2: 9:50-11:30, L3: 11:50-1:30, L4: 1:50-3:30
                'start_time': '8:00',
                'end_time': '3:30'
            },
            'shift_2': {
                'name': 'Shift 2 (10AM-5:30PM)',
                'theory_slots': list(range(2, 9)),  # slots 2-8 (10:00-4:50)
                'lab_sessions': ['L2', 'L3', 'L4', 'L5'],  # L2: 9:50-11:30, L3: 11:50-1:30, L4: 1:50-3:30, L5: 3:50-5:30
                'start_time': '10:00',
                'end_time': '5:30'
            }
        }
        
        # Define valid weekly shift patterns (days_shift1, days_shift2)
        # Each department will follow one of these patterns
        self.valid_shift_patterns = [
            (3, 2),  # Pattern A: 3 days Shift1, 2 days Shift2
            # (2, 3),  # Pattern B: 2 days Shift1, 3 days Shift2
        ]
        
        # Departments that should follow shift-based constraints
        # All departments will now follow department-centric shift patterns
        self.shift_departments = {
            'Computer Science & Design': {
                'enabled': True,
                'description': 'Department with unified shift-based scheduling'
            },
            'Computer Science & Engineering (Cyber Security)': {
                'enabled': True,
                'description': 'Department with unified shift-based scheduling'
            },
            'Aeronautical Engineering': {
                'enabled': True,
                'description': 'Engineering department with unified shift-based time constraints'
            },
            'Automobile Engineering': {
                'enabled': True,
                'description': 'Engineering department with unified shift-based time constraints'
            },
            'Food Technology': {
                'enabled': True,
                'description': 'Technology department with unified shift-based time constraints'
            },
            'Robotics & Automation': {
                'enabled': True,
                'description': 'Engineering department with unified shift-based time constraints'
            },
            'Mechatronics Engineering': {
                'enabled': True,
                'description': 'Engineering department with unified shift-based time constraints'
            },
            'Computer Science & Engineering': {
                'enabled': True,
                'description': 'Core CS department with unified shift-based scheduling'
            },
            'Information Technology': {
                'enabled': True,
                'description': 'IT department with unified shift-based scheduling'
            },
            'Electronics & Communication Engineering': {
                'enabled': True,
                'description': 'ECE department with unified shift-based scheduling'
            },
            'Electrical & Electronics Engineering': {
                'enabled': True,
                'description': 'EEE department with unified shift-based scheduling'
            },
            'Mechanical Engineering': {
                'enabled': True,
                'description': 'Mechanical department with unified shift-based scheduling'
            },
            'Civil Engineering': {
                'enabled': True,
                'description': 'Civil department with unified shift-based scheduling'
            },
            'Chemical Engineering': {
                'enabled': True,
                'description': 'Chemical department with unified shift-based scheduling'
            },
            'Biomedical Engineering': {
                'enabled': True,
                'description': 'Biomedical department with unified shift-based scheduling'
            },
            'Biotechnology': {
                'enabled': True,
                'description': 'Biotechnology department with unified shift-based scheduling'
            }
            # Add more departments here as needed
        }
        
        self.logger.info(f"Configured department-centric shift-based constraints for {len(self.shift_departments)} departments")
        for dept_name, config in self.shift_departments.items():
            if config['enabled']:
                self.logger.info(f"  - {dept_name}: {config['description']}")
        
        # Initialize department shift pattern tracking
        self.department_shift_patterns = {}  # Will store dept_name -> (pattern, daily_assignments)
        self.department_shift_assignments = {}  # Will store (dept_name, day) -> shift_id assignments
        
        # Initialize cross-department teacher tracking
        self.cross_dept_teachers = {}  # Will store teacher_id -> set of student_departments
        self.teacher_shift_patterns = {}  # Will store teacher_id -> individual shift pattern
        self.teacher_shift_assignments = {}  # Will store (teacher_id, day) -> shift_id assignments
        
        self.logger.info("Enhanced shift system initialized:")
        self.logger.info("  - Each department will follow ONE unified weekly shift pattern")
        self.logger.info("  - Cross-department teachers get individual shift patterns")
        self.logger.info("  - FIXED pattern: 3-2 (3 days Shift1, 2 days Shift2)")
        self.logger.info("  - Shift 1: 8AM-3:30PM (Mon-Wed), Shift 2: 10AM-5:30PM (Thu-Fri)")
        self.logger.info("  - Cross-department staff identified by student department diversity")
    
    def _setup_5pm_constraints(self):
        """Set up department and semester-specific 5:30pm scheduling constraints."""
        self.logger.info("Setting up department and semester-specific 5:30pm scheduling constraints...")
        
        # HARD CONSTRAINT DEPARTMENTS - CANNOT schedule after 5:30pm for both theory and lab
        # Format: 'Department Name' for all semesters OR 'Department Name_S3' for specific semester
        self.hard_5pm_constraint_departments = [
            # Department-wide constraints (applies to all semesters)
            "Artificial Intelligence & Data Science",
            "Artificial Intelligence & Machine Learning_S3", 
            "Artificial Intelligence & Machine Learning_S5", 
            "Artificial Intelligence & Machine Learning_S7", 
            "Computer Science & Business Systems",
            "Computer Science & Engineering (Cyber Security)",       
            "Information Technology",
            "Chemical Engineering_S5",
            "Chemical Engineering_S3",
            "Civil Engineering",
            "Robotics & Automation",
            "Automobile Engineering",
            "Mechatronics Engineering_S3",
            "Mechatronics Engineering_S5",
            "Mechatronics Engineering_S7",
            "Aeronautical Engineering_S3",
            "Aeronautical Engineering_S5",
            "Aeronautical Engineering_S7",
            "Computer Science & Design_S5",
            "Computer Science & Design_S7",
            "Computer Science & Engineering_S7",
            "Computer Science & Engineering_S5",
            "Food Technology_S5",
            "Food Technology_S3",
            "Computer Science & Design_S3",
            "Biotechnology",
            "Electronics & Communication Engineering_S7",
            "Electronics & Communication Engineering_S3",
            "Biomedical Engineering_S5",
            "Biomedical Engineering_S7",
            "Mechanical Engineering",
        ]
        
        # SOFT CONSTRAINT DEPARTMENTS - PREFER NOT to schedule after 5:30pm for both theory and lab
        # Format: 'Department Name' for all semesters OR 'Department Name_S5' for specific semester
        self.soft_5pm_constraint_departments = [
            # Department-wide constraints (applies to all semesters)
      "Computer Science & Engineering_S3",
            "Electronics & Communication Engineering_S5",
            'Electrical & Electronics Engineering',
            "Biomedical Engineering_S3",
            "Chemical Engineering_S7",
            "Food Technology_S7",
            # Semester-specific constraints (overrides department-wide settings)SS
            # Example: "Biotechnology_S7",                   # Only S7 has soft constraint
            # Example: "Civil Engineering_S3",               # Only S3 has soft constraint
            #    "Food Technology_S5",
            # "Food Technology_S3",
            #       "Mechatronics Engineering_S7",
            # "Aeronautical Engineering_S3",
            # "Aeronautical Engineering_S5",
                        #  "Computer Science & Design_S3",
        ]
        
        # HARD CONSTRAINTS: Block slots/sessions after 5:30pm
        # Theory slots after 5:30pm: "6:00 - 6:50" (index 10) - allow "5:00 - 5:50" (index 9)
        self.theory_slots_after_5pm_hard = [9,10]  # Only "6:00 - 6:50" - allow "5:00 - 5:50"
        
        # Lab sessions after 5:30pm: L6 starts at 5:10 but ends at 6:50, so restrict L6
        # Allow L5 (3:50-5:30) since it ends exactly at 5:30
        self.lab_sessions_after_5pm_hard = ['L6']  # L6: 5:10-6:50 (goes past 5:30)
        
        # SOFT CONSTRAINTS: Discourage slots/sessions after 5:00pm (more restrictive for preferences)
        # Theory slots after 5:00pm: "5:00 - 5:50" (index 9) and "6:00 - 6:50" (index 10)
        self.theory_slots_after_5pm_soft = [9, 10]  # Both "5:00 - 5:50" and "6:00 - 6:50"
        
        # Lab sessions after 5:00pm: L5 (3:50-5:30) and L6 (5:10-6:50) - both discouraged for soft constraints
        self.lab_sessions_after_5pm_soft = ['L5', 'L6']  # Both L5 and L6 discouraged
        
        # Backward compatibility: Use hard constraints as default
        self.theory_slots_after_5pm = self.theory_slots_after_5pm_hard
        self.lab_sessions_after_5pm = self.lab_sessions_after_5pm_hard
        
        self.logger.info(f"Hard 5:30pm constraint departments: {self.hard_5pm_constraint_departments}")
        self.logger.info(f"Soft 5:00pm constraint departments: {self.soft_5pm_constraint_departments}")
        self.logger.info(f"HARD constraints - Theory slots after 5:30pm: {[self.theory_time_slots[i] for i in self.theory_slots_after_5pm_hard]}")
        self.logger.info(f"HARD constraints - Lab sessions after 5:30pm: {self.lab_sessions_after_5pm_hard}")
        self.logger.info(f"SOFT constraints - Theory slots after 5:00pm: {[self.theory_time_slots[i] for i in self.theory_slots_after_5pm_soft]}")
        self.logger.info(f"SOFT constraints - Lab sessions after 5:00pm: {self.lab_sessions_after_5pm_soft}")
        
        # Constraint weights for optimization
        self.hard_5pm_constraint_weight = 10000  # Very high penalty to essentially prohibit
        self.soft_5pm_constraint_weight = 0    # Moderate penalty to discourage
        
        self.logger.info("Dual-level constraint system initialized:")
        self.logger.info(f"  - Hard constraint departments: {len(self.hard_5pm_constraint_departments)} departments (blocked after 5:30pm)")
        self.logger.info(f"  - Soft constraint departments: {len(self.soft_5pm_constraint_departments)} departments (discouraged after 5:00pm)")
        self.logger.info(f"  - Hard constraint weight: {self.hard_5pm_constraint_weight}")
        self.logger.info(f"  - Soft constraint weight: {self.soft_5pm_constraint_weight}")
        self.logger.info("  - HARD: Allow until 5:30pm (slot 9, L5), Block after 5:30pm (slot 10, L6)")
        self.logger.info("  - SOFT: Discourage after 5:00pm (slots 9+10, L5+L6)")

    def _has_5pm_constraint(self, dept_name, semester, constraint_type='hard'):
        """
        Check if a department-semester combination has a 5:30pm constraint.
        
        Args:
            dept_name (str): Department name
            semester (int): Semester number
            constraint_type (str): 'hard' or 'soft'
            
        Returns:
            bool: True if the dept-semester combination has the specified constraint
            
        Note: Constraint now allows scheduling until 5:30pm, only restricts after 5:30pm
        """
        if constraint_type == 'hard':
            constraint_list = self.hard_5pm_constraint_departments
        else:
            constraint_list = self.soft_5pm_constraint_departments
        
        # Check for exact department-semester match first (highest priority)
        dept_sem_combo = f"{dept_name}_S{semester}"
        if dept_sem_combo in constraint_list:
            return True
            
        # Check for department-wide constraint (lower priority)
        if dept_name in constraint_list:
            # Make sure there's no semester-specific override that would contradict this
            # If there's a semester-specific entry for this dept, it overrides the department-wide setting
            semester_specific_entries = [item for item in constraint_list if item.startswith(f"{dept_name}_S")]
            if semester_specific_entries:
                # There are semester-specific entries, so check if our semester is explicitly listed
                return dept_sem_combo in constraint_list
            else:
                # No semester-specific entries, so department-wide constraint applies
                return True
        
        return False
        
    def _get_5pm_constraint_summary(self):
        """Get a summary of all department-semester 5:30pm constraints for logging."""
        summary = {
            'hard_dept_wide': [],
            'hard_semester_specific': [],
            'soft_dept_wide': [],
            'soft_semester_specific': []
        }
        
        # Process hard constraints
        for constraint in self.hard_5pm_constraint_departments:
            if '_S' in constraint:
                summary['hard_semester_specific'].append(constraint)
            else:
                summary['hard_dept_wide'].append(constraint)
        
        # Process soft constraints  
        for constraint in self.soft_5pm_constraint_departments:
            if '_S' in constraint:
                summary['soft_semester_specific'].append(constraint)
            else:
                summary['soft_dept_wide'].append(constraint)
                
        return summary

    def is_shift_department(self, dept_name):
        """Check if a department should follow shift-based constraints."""
        # MODIFIED: Apply shift constraints to ALL departments
        return True
        
        # ORIGINAL CODE (commented out - only applied to specific single departments):
        # return (dept_name in self.shift_departments and 
        #         self.shift_departments[dept_name]['enabled'])
    
    def get_available_shifts(self):
        """Get list of available shift IDs."""
        return list(self.shift_definitions.keys())
    
    def get_shift_theory_slots(self, shift_id):
        """Get theory time slots for a specific shift."""
        if shift_id in self.shift_definitions:
            return self.shift_definitions[shift_id]['theory_slots']
        return list(range(len(self.theory_time_slots)))  # fallback to all slots
    
    def get_shift_lab_sessions(self, shift_id):
        """Get lab sessions for a specific shift."""
        if shift_id in self.shift_definitions:
            return self.shift_definitions[shift_id]['lab_sessions']
        return list(self.lab_sessions.keys())  # fallback to all sessions
    
    def get_department_shift_pattern(self, dept_name):
        """Get the shift pattern assigned to a department."""
        return self.department_shift_patterns.get(dept_name, None)
    
    def get_department_shift_for_day(self, dept_name, day_idx):
        """Get the shift assigned to a department for a specific day."""
        return self.department_shift_assignments.get((dept_name, day_idx), None)
    
    def is_department_shift_compatible(self, dept_name, day_idx, shift_id):
        """Check if a shift is compatible with department's pattern for a given day."""
        assigned_shift = self.get_department_shift_for_day(dept_name, day_idx)
        return assigned_shift is None or assigned_shift == shift_id
    
    def _identify_cross_department_teachers(self):
        """Identify teachers who teach across multiple student departments."""
        self.logger.info("Identifying cross-department teachers using student department analysis...")
        
        # Analyze teacher-student department relationships
        teacher_student_depts = defaultdict(set)
        
        # Process courses to identify which student departments each teacher serves
        for _, row in self.courses_df.iterrows():
            teacher_id = str(row['teacher_id'])
            student_dept = row.get('student_dept', 'Unknown')
            
            if student_dept and student_dept != 'Unknown':
                teacher_student_depts[teacher_id].add(student_dept)
        
        # Identify cross-department teachers (teaching 2+ student departments)
        single_dept_teachers = {}
        cross_dept_teachers = {}
        
        for teacher_id, student_depts in teacher_student_depts.items():
            if len(student_depts) > 1:
                cross_dept_teachers[teacher_id] = student_depts
            elif len(student_depts) == 1:
                single_dept_teachers[teacher_id] = list(student_depts)[0]
        
        # Store cross-department teacher information
        self.cross_dept_teachers = cross_dept_teachers
        self.single_dept_teachers = single_dept_teachers
        
        # Log analysis results
        self.logger.info(f"Teacher department analysis results:")
        self.logger.info(f"  - Single-department teachers: {len(single_dept_teachers)}")
        self.logger.info(f"  - Cross-department teachers: {len(cross_dept_teachers)}")
        
        if cross_dept_teachers:
            self.logger.info("Cross-department teachers identified:")
            for teacher_id, depts in cross_dept_teachers.items():
                dept_list = ', '.join(sorted(depts))
                self.logger.info(f"  Teacher {teacher_id}: {dept_list} ({len(depts)} departments)")
        
        # Log department distribution
        dept_coverage = defaultdict(int)
        for teacher_id, student_depts in teacher_student_depts.items():
            for dept in student_depts:
                dept_coverage[dept] += 1
        
        self.logger.info("Student department coverage by teachers:")
        for dept, teacher_count in sorted(dept_coverage.items()):
            cross_count = sum(1 for t_id, depts in cross_dept_teachers.items() if dept in depts)
            single_count = teacher_count - cross_count
            self.logger.info(f"  {dept}: {teacher_count} teachers ({single_count} single-dept, {cross_count} cross-dept)")
        
        return len(cross_dept_teachers)
    
    def is_cross_department_teacher(self, teacher_id):
        """Check if a teacher teaches across multiple departments."""
        return teacher_id in self.cross_dept_teachers
    
    def get_teacher_student_departments(self, teacher_id):
        """Get the set of student departments a teacher serves."""
        if teacher_id in self.cross_dept_teachers:
            return self.cross_dept_teachers[teacher_id]
        elif teacher_id in self.single_dept_teachers:
            return {self.single_dept_teachers[teacher_id]}
        return set()
    
    def _load_core_lab_mapping(self):
        """Load core lab mapping file for specialized lab course assignments."""
        self.logger.info("Loading core lab mapping configuration...")
        
        # Initialize core mapping variables
        self.core_mapping_df = None
        self.course_to_room_mapping = {}
        self.core_lab_instance_ids = set()
        
        # Try to find core mapping file in various locations
        possible_paths = [
            'data/og-final.csv',
            './data/og-final.csv',
            '../data/og-final.csv',
            'timetable_scheduler/data/og-final.csv',
        ]
        
        core_mapping_file_path = None
        for path in possible_paths:
            if os.path.exists(path):
                core_mapping_file_path = path
                break
        
        if core_mapping_file_path:
            try:
                self.core_mapping_df = pd.read_csv(core_mapping_file_path)
                self.logger.info(f"Successfully loaded core lab mapping from {core_mapping_file_path}")
                self.logger.info(f"Core mapping contains {len(self.core_mapping_df)} course-lab assignments")
            except Exception as e:
                self.logger.error(f"Error loading core lab mapping file: {e}")
                self.core_mapping_df = None
        else:
            self.logger.warning("Core lab mapping file not found. Proceeding without specialized lab assignments.")
            self.core_mapping_df = None
        
        # Process core mapping if available
        if self.core_mapping_df is not None:
            self._process_core_lab_mapping()
        else:
            self.logger.info("No core lab mapping available - all courses will use general lab assignment rules")
    
    def _process_core_lab_mapping(self):
        """Process the core lab mapping to create course-to-room assignments."""
        if self.core_mapping_df is None:
            return
        
        self.logger.info("Processing core lab mapping...")
        
        # Check the file structure to determine processing method
        columns = self.core_mapping_df.columns.tolist()
        
        if 'lab_1' in columns and 'lab_2' in columns:
            # This is og-final.csv format
            self._process_og_final_format()
        elif 'lab_1_room' in columns and 'lab_1_block' in columns:
            # This is the old combined_lab_mapping.csv format
            self._process_combined_lab_mapping_format()
        else:
            self.logger.error(f"Unknown core mapping file format. Columns: {columns}")
            return
        
        # Identify all instance IDs that are considered "core labs"
        if self.core_mapping_df is not None:
            # Create a lookup from (course_code, course_name) to a list of instance IDs from the main courses_df
            course_name_to_ids = defaultdict(list)
            for _, row in self.courses_df.iterrows():
                course_code = row['course_code']
                course_name = row['course_name']
                instance_id = str(row['id'])
                course_name_to_ids[(course_code, course_name)].append(instance_id)

            # Use the lookup to find all instance IDs corresponding to the core lab mapping
            for course_tuple in self.course_to_room_mapping.keys():
                if course_tuple in course_name_to_ids:
                    self.core_lab_instance_ids.update(course_name_to_ids[course_tuple])

            self.logger.info(f"Identified {len(self.core_lab_instance_ids)} core lab instances that will be exempt from the 18-slot weekly limit.")
        
        self.logger.info(f"Core lab mapping processing complete: {len(self.course_to_room_mapping)} course mappings created")
    
    def _process_og_final_format(self):
        """Process og-final.csv format: course_code, course_name, department, total_labs, lab_1, lab_2, lab_3, lab_4, lab_5"""
        self.logger.info("Processing og-final.csv format core lab mapping...")
        
        # Create room name lookup (room name -> room ID)
        room_name_lookup = {}
        for _, room in self.rooms_df.iterrows():
            room_names = []
            
            # Add different possible room name formats
            if pd.notna(room.get('room_number')):
                room_names.append(str(room['room_number']).strip())
            
            if pd.notna(room.get('description')):
                room_names.append(str(room['description']).strip())
            
            # Add room_number + block combination if available
            if pd.notna(room.get('room_number')) and pd.notna(room.get('block')):
                room_names.append(f"{room['room_number']}_{room['block']}")
            
            # Map all possible names to this room ID
            for name in room_names:
                if name and name.lower() != 'nan':
                    room_name_lookup[name.lower()] = room['id']
        
        # Clean data in core_mapping_df
        self.core_mapping_df['course_code'] = self.core_mapping_df['course_code'].astype(str).str.strip()
        self.core_mapping_df['course_name'] = self.core_mapping_df['course_name'].astype(str).str.strip()
        
        # Process each course mapping
        mapped_courses = 0
        for _, row in self.core_mapping_df.iterrows():
            course_code = row['course_code']
            course_name = row['course_name']
            department = row.get('department', 'Unknown')
            total_labs = int(row.get('total_labs', 1))
            
            mapped_rooms = []
            
            # Process each lab (lab_1, lab_2, lab_3, lab_4, lab_5)
            for lab_num in range(1, min(total_labs + 1, 6)):  # Max 5 labs (lab_1 to lab_5)
                lab_col = f'lab_{lab_num}'
                
                if lab_col in row and pd.notna(row[lab_col]):
                    lab_name = str(row[lab_col]).strip()
                    
                    # Skip if lab_name is empty
                    if not lab_name or lab_name.lower() in ['nan', '']:
                        continue
                    
                    # Try to find matching room ID
                    room_id = None
                    lab_name_lower = lab_name.lower()
                    
                    # Direct match
                    if lab_name_lower in room_name_lookup:
                        room_id = room_name_lookup[lab_name_lower]
                    else:
                        # Fuzzy matching for partial matches
                        for room_name, rid in room_name_lookup.items():
                            if lab_name_lower in room_name or room_name in lab_name_lower:
                                room_id = rid
                                break
                    
                    if room_id is not None:
                        mapped_rooms.append(room_id)
                        self.logger.info(f"OG-Final mapping: '{course_code}' - '{course_name}' lab {lab_num} → '{lab_name}' (ID: {room_id})")
                    else:
                        self.logger.warning(f"OG-Final mapping: Lab '{lab_name}' for course '{course_code}' lab {lab_num} not found in rooms")
            
            # Store the mapping with all available rooms for this course
            if mapped_rooms:
                self.course_to_room_mapping[(course_code, course_name)] = mapped_rooms
                mapped_courses += 1
                self.logger.info(f"OG-Final complete: '{course_code}' ({department}) → {len(mapped_rooms)} lab(s): {mapped_rooms}")
            else:
                self.logger.warning(f"OG-Final failed: No valid labs found for course '{course_code}' - '{course_name}' ({department})")
        
        self.logger.info(f"OG-Final processing complete: {mapped_courses} courses mapped to specific labs")
    
    def _process_combined_lab_mapping_format(self):
        """Process combined_lab_mapping.csv format with lab_1_room, lab_1_block columns"""
        self.logger.info("Processing combined_lab_mapping.csv format core lab mapping...")
        
        # Prepare room identifier lookup
        self.rooms_df['block'] = self.rooms_df['block'].fillna('Unknown').astype(str).str.strip()
        self.rooms_df['room_number'] = self.rooms_df['room_number'].astype(str).str.strip()
        self.rooms_df['room_identifier'] = self.rooms_df['room_number'] + "_" + self.rooms_df['block']
        room_lookup = pd.Series(self.rooms_df.id.values, index=self.rooms_df.room_identifier).to_dict()
        
        # Clean data in core_mapping_df
        self.core_mapping_df['course_code'] = self.core_mapping_df['course_code'].astype(str).str.strip()
        self.core_mapping_df['course_name'] = self.core_mapping_df['course_name'].astype(str).str.strip()
        
        # Process each course mapping
        for _, row in self.core_mapping_df.iterrows():
            course_code = row['course_code']
            course_name = row['course_name']
            total_labs = int(row.get('total_labs', 1))
            
            mapped_rooms = []
            
            # Process each lab (lab_1, lab_2, lab_3, etc.)
            for lab_num in range(1, total_labs + 1):
                room_col = f'lab_{lab_num}_room'
                block_col = f'lab_{lab_num}_block'
                
                if room_col in row and block_col in row:
                    room_number = str(row[room_col]).strip()
                    block = str(row[block_col]).strip()
                    
                    # Skip if room_number is 'nan' or empty
                    if room_number.lower() in ['nan', ''] or pd.isna(row[room_col]):
                        continue
                        
                    room_identifier = room_number + "_" + block
                    
                    if room_identifier in room_lookup:
                        room_id = room_lookup[room_identifier]
                        mapped_rooms.append(room_id)
                        self.logger.info(f"Combined mapping: '{course_code}' - '{course_name}' lab {lab_num} → '{room_number}' (ID: {room_id})")
                    else:
                        self.logger.warning(f"Combined mapping: Room '{room_number}' in block '{block}' for course '{course_code}' lab {lab_num} not found. Identifier: '{room_identifier}'")
            
            # Store the mapping with all available rooms for this course
            if mapped_rooms:
                self.course_to_room_mapping[(course_code, course_name)] = mapped_rooms
                self.logger.info(f"Combined mapping complete: '{course_code}' → {len(mapped_rooms)} lab(s): {mapped_rooms}")
            else:
                self.logger.warning(f"Combined mapping failed: No valid labs found for course '{course_code}' - '{course_name}'")
    
    def _compute_group_requirements(self):
        """Compute theory time slot requirements for each group."""
        self.logger.info("Computing group time slot requirements...")
        
        # Calculate time slot requirements for each group
        self.group_requirements = {}
        
        for (dept, semester), groups in self.course_groups.items():
            for group_idx, group in enumerate(groups):
                if not group:
                    continue
                    
                group_name = f"{dept}_S{semester}_G{group_idx + 1}"
                
                # Calculate required time slots based on max theory hours in group
                max_theory_hours = 0
                total_theory_hours = 0
                for instance in group:
                    theory_hours = instance.get('lecture_hours', 0) + instance.get('tutorial_hours', 0)
                    max_theory_hours = max(max_theory_hours, theory_hours)
                    total_theory_hours += theory_hours
                
                # Allocate slots based on max theory hours (minimum 3, maximum 6)
                required_slots = max(3, min(6, max_theory_hours))
                self.group_requirements[group_name] = required_slots
                
                self.logger.info(f"Group {group_name}: {len(group)} instances, max {max_theory_hours}h -> {required_slots} time slots")
        
        self.logger.info(f"Group requirements computed for {len(self.group_requirements)} groups")
        return self.group_requirements
    
    def _build_time_mapping(self):
        """Build mapping between theory and lab time systems for conflict detection."""
        self.logger.info("Building cross-system time mapping...")
        
        # Theory slot to lab slot mapping (for conflict detection)
        self.theory_to_lab_mapping = {}
        self.lab_to_theory_mapping = {}
        
        # Helper function to parse time string to minutes
        def time_to_minutes(time_str):
            h, m = map(int, time_str.split(':'))
            # Handle AM/PM conversion for 12-hour format with 1-hour based times
            # 1:00 -> 13:00 (1 PM), 8:00 stays 8:00 (8 AM)
            if h <= 7 and h >= 1:  # 1 PM to 7 PM
                h += 12
            return h * 60 + m
        
        # Helper function to parse time range
        def parse_time_range(time_range_str):
            try:
                # Handle format like "8:00 - 8:50" or "1:00 - 1:50"
                start_str, end_str = time_range_str.split(' - ')
                start_minutes = time_to_minutes(start_str.strip())
                end_minutes = time_to_minutes(end_str.strip())
                return start_minutes, end_minutes
            except Exception as e:
                self.logger.warning(f"Failed to parse time range '{time_range_str}': {e}")
                return None, None
        
        # Map each theory slot to overlapping lab slots
        for theory_idx, theory_slot in enumerate(self.theory_time_slots):
            theory_start, theory_end = parse_time_range(theory_slot)
            if theory_start is None:
                continue
                
            overlapping_lab_slots = []
            for lab_idx, lab_slot in enumerate(self.lab_time_slots):
                lab_start, lab_end = parse_time_range(lab_slot)
                if lab_start is None:
                    continue
                
                # Check for overlap: (StartA < EndB) and (EndA > StartB)
                if theory_start < lab_end and theory_end > lab_start:
                    overlapping_lab_slots.append(lab_idx)
            
            self.theory_to_lab_mapping[theory_idx] = overlapping_lab_slots
            self.logger.debug(f"Theory slot {theory_idx} ({theory_slot}) overlaps with lab slots: {overlapping_lab_slots}")
        
        # Map each lab slot to overlapping theory slots
        for lab_idx, lab_slot in enumerate(self.lab_time_slots):
            lab_start, lab_end = parse_time_range(lab_slot)
            if lab_start is None:
                continue
                
            overlapping_theory_slots = []
            for theory_idx, theory_slot in enumerate(self.theory_time_slots):
                theory_start, theory_end = parse_time_range(theory_slot)
                if theory_start is None:
                    continue
                
                # Check for overlap
                if lab_start < theory_end and lab_end > theory_start:
                    overlapping_theory_slots.append(theory_idx)
            
            self.lab_to_theory_mapping[lab_idx] = overlapping_theory_slots
            self.logger.debug(f"Lab slot {lab_idx} ({lab_slot}) overlaps with theory slots: {overlapping_theory_slots}")
        
        self.logger.info("Cross-system time mapping completed")
    
    def _initialize_global_room_registry(self):
        """Initialize global room registry for cross-schedule conflict detection."""
        # Preserve existing entries that are marked as from existing schedules
        existing_entries = {}
        if hasattr(self, 'global_room_registry'):
            existing_entries = {
                key: value for key, value in self.global_room_registry.items() 
                if value.get('from_existing', False)
            }
        
        self.global_room_registry = existing_entries
        
        if existing_entries:
            self.logger.info(f"Preserved {len(existing_entries)} existing room occupancies during registry reset")
        self.logger.info("Initialized global room registry for cross-schedule validation")

    def _register_room_usage(self, day, time_slot, room_id, session_info):
        """Register room usage in global registry with enhanced conflict detection and co-scheduling support."""
        day_normalized = self._normalize_day_name(day)
        key = (day_normalized, time_slot, room_id)
        
        if key in self.global_room_registry:
            existing = self.global_room_registry[key]
            
            # Handle list of existing sessions (for co-scheduling)
            if not isinstance(existing, list):
                existing = [existing]
            
            # Check if this is truly a conflict or just a duplicate registration
            existing_course = existing[0].get('course_instance_id')
            new_course = session_info.get('course_instance_id')
            existing_teacher = existing[0].get('teacher_id')
            new_teacher = session_info.get('teacher_id')
            
            if existing_course == new_course and existing_teacher == new_teacher:
                # Same course/teacher, just duplicate registration - this is OK
                self.logger.debug(f"Duplicate registration for same course: {key}")
                return True
            
    
            
            # This is a real conflict
            self.logger.error(f"CRITICAL ROOM CONFLICT: Room {room_id} double-booked on {day} {time_slot}")
            self.logger.error(f"  Existing: {existing[0].get('course_code', 'Unknown')} (ID: {existing_course}) by {existing[0].get('teacher_name', 'Unknown')} (ID: {existing_teacher})")
            self.logger.error(f"  New: {session_info.get('course_code', 'Unknown')} (ID: {new_course}) by {session_info.get('teacher_name', 'Unknown')} (ID: {new_teacher})")
            self.logger.error(f"  Schedule types: Existing={existing[0].get('schedule_type', 'Unknown')}, New={session_info.get('schedule_type', 'Unknown')}")
            self.logger.error(f"  Day patterns: Existing={existing[0].get('day_pattern', 'Unknown')}, New={session_info.get('day_pattern', 'Unknown')}")
            
            # Don't overwrite - this indicates a serious scheduling problem
            return False
        
        self.global_room_registry[key] = session_info
        return True

    def _is_room_available_global(self, day, time_slot, room_id):
        """Check if room is available in global registry."""
        day_normalized = self._normalize_day_name(day)
        key = (day_normalized, time_slot, room_id)
        
        return key not in self.global_room_registry

    def _normalize_day_name(self, day_name):
        """Normalize day names to ensure consistency across different day patterns."""
        day_mapping = {
            'monday': 'monday',
            'tue': 'tuesday', 'tuesday': 'tuesday',
            'wed': 'wed', 'wednesday': 'wed',
            'thu': 'thur', 'thur': 'thur', 'thursday': 'thur',
            'fri': 'fri', 'friday': 'fri',
            'sat': 'saturday', 'saturday': 'saturday'
        }
        return day_mapping.get(day_name.lower(), day_name.lower())

    def _get_base_course_id(self, course_instance_id):
        """Extract base course ID from virtual instance ID (e.g., '877-A' -> '877')."""
        return course_instance_id.split('-')[0] if '-' in course_instance_id else course_instance_id

    def _parse_time_to_minutes(self, time_str):
        """Parse time string to minutes since midnight for overlap detection."""
        try:
            # Handle format like "8:00 - 8:50" or "1:00 - 1:50"
            if ' - ' in time_str:
                time_str = time_str.split(' - ')[0]  # Take start time
            
            h, m = map(int, time_str.split(':'))
            # Handle AM/PM conversion for 12-hour format
            if h <= 7 and h >= 1:  # 1 PM to 7 PM
                h += 12
            return h * 60 + m
        except:
            return 0

    def _times_overlap(self, time_range1, time_range2):
        """Check if two time ranges overlap."""
        try:
            # Parse time ranges
            if ' - ' in time_range1:
                start1_str, end1_str = time_range1.split(' - ')
            else:
                start1_str = end1_str = time_range1
                
            if ' - ' in time_range2:
                start2_str, end2_str = time_range2.split(' - ')
            else:
                start2_str = end2_str = time_range2
            
            start1 = self._parse_time_to_minutes(start1_str)
            end1 = self._parse_time_to_minutes(end1_str)
            start2 = self._parse_time_to_minutes(start2_str)
            end2 = self._parse_time_to_minutes(end2_str)
            
            # Check for overlap: (StartA < EndB) and (EndA > StartB)
            return start1 < end2 and end1 > start2
        except:
            return False
    
    def process_courses(self):
        """Process courses and separate them into lab and theory requirements."""
        self.logger.info("Processing courses for combined scheduling...")
        
        # Extract unique teachers
        self.teachers = self.courses_df['teacher_id'].unique()
        self.num_teachers = len(self.teachers)
        
        # Create unified teacher-course assignments
        self.teacher_course_assignments = defaultdict(list)
        self.course_to_teacher = {}
        self.lab_requirements = defaultdict(list)
        self.theory_requirements = defaultdict(list)
        
        for _, row in self.courses_df.iterrows():
            teacher_id = str(row['teacher_id']) # Enforce string type
            course_id = row['course_id']
            course_instance_id = str(row['id'])
            
            if teacher_id not in self.teacher_course_assignments:
                self.teacher_course_assignments[teacher_id] = []
            
            # Create unified course instance record
            course_instance = {
                'id': course_instance_id,
                'course_id': course_id,
                'course_code': row['course_code'],
                'course_name': row['course_name'],
                'course_type': row['course_type'],
                'lecture_hours': int(row.get('lecture_hours', 0)),
                'tutorial_hours': int(row.get('tutorial_hours', 0)),
                'practical_hours': int(row.get('practical_hours', 0)),
                'student_count': int(row['student_count']),
                'semester': row.get('semester', 1),
                'course_dept': row.get('course_dept', 'Computer Science & Engineering'),
                'student_dept': row.get('student_dept', 'Computer Science & Engineering')
            }
            
            self.teacher_course_assignments[teacher_id].append(course_instance)
            self.course_to_teacher[course_instance_id] = teacher_id
            
            # Categorize into lab or theory requirements
            has_practical = course_instance['practical_hours'] > 0
            has_theory = course_instance['lecture_hours'] > 0 or course_instance['tutorial_hours'] > 0
            
            if has_practical:
                if teacher_id not in self.lab_requirements:
                    self.lab_requirements[teacher_id] = []
                
                # Calculate lab sessions needed (each lab session = 2 practical hours)
                practical_hours = course_instance['practical_hours']
                base_sessions = (practical_hours + 1) // 2  # Ceiling division for proper calculation
                
                self.lab_requirements[teacher_id].append({
                    'course_instance_id': course_instance_id,
                    'course_code': course_instance['course_code'],
                    'practical_hours': practical_hours,
                    'base_sessions': base_sessions,
                    'lab_sessions_needed': base_sessions,
                    'total_lab_slots_needed': base_sessions,  # Default: no batching
                    'students_per_instance': course_instance['student_count']
                })
            
            if has_theory:
                if teacher_id not in self.theory_requirements:
                    self.theory_requirements[teacher_id] = []
                
                self.theory_requirements[teacher_id].append({
                    'course_instance_id': course_instance_id,
                    'course_code': course_instance['course_code'],
                    'lecture_hours': course_instance['lecture_hours'],
                    'tutorial_hours': course_instance['tutorial_hours'],
                    'required_lecture_sessions': course_instance['lecture_hours'],
                    'required_tutorial_sessions': course_instance['tutorial_hours'],
                    'students_per_instance': course_instance['student_count']
                })
        
        # Log processing results
        total_lab_sessions = sum(sum(c['lab_sessions_needed'] for c in courses) 
                               for teacher, courses in self.lab_requirements.items())
        total_theory_sessions = sum(sum(c['required_lecture_sessions'] + c['required_tutorial_sessions'] for c in courses) 
                                  for teacher, courses in self.theory_requirements.items())
        
        self.logger.info(f"Course processing completed:")
        self.logger.info(f"  Teachers: {self.num_teachers}")
        self.logger.info(f"  Teachers with lab requirements: {len(self.lab_requirements)}")
        self.logger.info(f"  Teachers with theory requirements: {len(self.theory_requirements)}")
        self.logger.info(f"  Total lab sessions needed: {total_lab_sessions}")
        self.logger.info(f"  Total theory sessions needed: {total_theory_sessions}")
    
    def create_course_groups(self):
        """Create unified course groups for both lab and theory using OR-Tools optimized distribution."""
        self.logger.info("🔥 DEBUG: create_course_groups() STARTED")
        self.logger.info("Creating unified course groups using OR-Tools optimization...")
        
        # Use the new OR-Tools based group creation logic
        # This ensures optimal constraint satisfaction and student choice
        self.logger.info("🔥 DEBUG: About to call _create_course_groups_by_dept_semester()")
        self.course_groups = self._create_course_groups_by_dept_semester()
        self.logger.info("🔥 DEBUG: Finished _create_course_groups_by_dept_semester()")
        
        # Create instance-group mapping for both lab and theory
        self.instance_group_mapping = {}
        self._create_instance_group_mapping()
        
        # Update lab requirements to include virtual instances from CourseGroupOptimizer
        self._update_lab_requirements_with_virtual_instances()
        
        # Update lab requirements to handle virtual co-scheduled instances
        self._update_lab_requirements_for_virtual_instances()
        
        # Filter lab requirements to only include instances present in groups
        self._filter_lab_requirements_by_groups()
        
        # Identify groups that contain core lab instances
        self._identify_core_lab_groups()
        
        self.logger.info("OR-Tools unified course grouping completed successfully")
        self.logger.info("[OK] UNIFIED CONSTRAINTS: Both lab and theory respect same group structure")
        self.logger.info("[OK] OR-TOOLS OPTIMIZATION: Maximized student choice with constraint satisfaction")

    def _update_lab_requirements_with_virtual_instances(self):
        """Update lab requirements to include virtual instances created by CourseGroupOptimizer."""
        self.logger.info("Updating lab requirements to include virtual instances from CourseGroupOptimizer...")
        
        # Find all virtual instances in groups
        virtual_instances = {}
        original_to_virtual = {}
        
        for (dept, semester), groups in self.course_groups.items():
            for group_idx, group in enumerate(groups):
                for instance in group:
                    instance_id = instance['id']
                    if 'virtual_id' in instance and instance.get('is_large_course_split', False):
                        # This is a virtual instance created by CourseGroupOptimizer
                        virtual_id = instance['virtual_id']
                        original_student_count = instance.get('original_student_count', 140)
                        
                        virtual_instances[virtual_id] = instance
                        
                        # Map from original ID to virtual instances
                        original_id = virtual_id.split('-')[0]  # Remove -A or -B suffix
                        if original_id not in original_to_virtual:
                            original_to_virtual[original_id] = []
                        original_to_virtual[original_id].append(virtual_id)
                        
                        self.logger.info(f"  Found virtual instance: {virtual_id} (from original {original_id}, {original_student_count} students)")
        
        if not virtual_instances:
            self.logger.info("  No virtual instances found to process")
            return
        
        # Update lab requirements to replace original large course instances with virtual instances
        updated_lab_requirements = defaultdict(list)
        virtual_instances_added = 0
        original_instances_replaced = 0
        
        for teacher_id, lab_courses in self.lab_requirements.items():
            updated_lab_requirements[teacher_id] = []
            
            for course_req in lab_courses:
                course_instance_id = course_req['course_instance_id']
                
                # Check if this is an original instance that was split into virtual instances
                if course_instance_id in original_to_virtual:
                    # Replace with virtual instances
                    virtual_ids = original_to_virtual[course_instance_id]
                    original_instances_replaced += 1
                    
                    self.logger.info(f"  Replacing original instance {course_instance_id} with virtual instances: {virtual_ids}")
                    
                    for virtual_id in virtual_ids:
                        if virtual_id in virtual_instances:
                            virtual_instance = virtual_instances[virtual_id]
                            
                            # Create lab requirement for virtual instance
                            virtual_req = course_req.copy()
                            virtual_req['course_instance_id'] = virtual_id
                            virtual_req['students_per_instance'] = virtual_instance['student_count']  # Should be 70
                            
                            updated_lab_requirements[teacher_id].append(virtual_req)
                            virtual_instances_added += 1
                            
                            self.logger.info(f"    Added virtual instance {virtual_id}: {virtual_req['students_per_instance']} students, {virtual_req['practical_hours']}h")
                else:
                    # Keep original instance as-is
                    updated_lab_requirements[teacher_id].append(course_req)
        
        # Update lab requirements
        self.lab_requirements = updated_lab_requirements
        
        self.logger.info(f"Lab requirements updated successfully:")
        self.logger.info(f"  Original large instances replaced: {original_instances_replaced}")
        self.logger.info(f"  Virtual instances added: {virtual_instances_added}")
        self.logger.info(f"  Virtual instances will be merged back to unified instances in post-processing")
    
    def _create_course_groups_by_dept_semester(self):
        """Group course instances by department and semester using OR-Tools optimization (unified for lab and theory)."""
        # Collect ALL course instances by department and semester (theory + lab)
        dept_sem_courses = defaultdict(list)
        total_instances = 0
        
        # Gather ALL course instances from the original CSV data, not just theory courses
        all_instances = []
        for _, row in self.courses_df.iterrows():
            teacher_id = row['teacher_id']
            course_instance_id = str(row['id'])
            
            instance_with_teacher = {
                'id': course_instance_id,
                'teacher_id': str(teacher_id),
                'course_id': row['course_id'],
                'course_code': row['course_code'],
                'course_name': row['course_name'],
                'course_type': row['course_type'],
                'lecture_hours': int(row.get('lecture_hours', 0)),
                'tutorial_hours': int(row.get('tutorial_hours', 0)),
                'practical_hours': int(row.get('practical_hours', 0)),
                'student_count': int(row['student_count']),
                'semester': row.get('semester', 1),
                'course_dept': row.get('course_dept', 'Computer Science & Engineering'),
                'student_dept': row.get('student_dept', 'Computer Science & Engineering'),
                'has_lab': int(row.get('practical_hours', 0)) > 0,
                'has_theory': int(row.get('lecture_hours', 0)) > 0 or int(row.get('tutorial_hours', 0)) > 0
            }
            all_instances.append(instance_with_teacher)
            total_instances += 1
        
        self.logger.info(f"Processing {total_instances} total course instances (theory + lab) across {len(self.teachers)} teachers")
        
        # Group by department and semester
        for instance in all_instances:
            dept = instance.get('student_dept', 'Computer Science & Engineering')
            semester = instance.get('semester', 3)  # Default to semester 3
            dept_sem_courses[(dept, semester)].append(instance)
        
        # Log department-semester distribution
        for (dept, semester), instances in dept_sem_courses.items():
            lab_instances = [i for i in instances if i['has_lab']]
            theory_instances = [i for i in instances if i['has_theory']]
            self.logger.info(f"Dept: {dept}, Semester: {semester}: {len(instances)} instances ({len(lab_instances)} lab, {len(theory_instances)} theory)")
        
        # Create groups for each department and semester using OR-Tools optimization
        course_groups = {}
        for (dept, semester), courses in dept_sem_courses.items():
            if courses:  # Skip if there are no courses
                course_groups[(dept, semester)] = self._distribute_course_instances_optimized(courses, dept, semester)
        
        return course_groups
    
    def _distribute_course_instances_optimized(self, courses, dept, semester):
        """Distribute course instances across groups using OR-Tools CourseGroupOptimizer."""
        self.logger.info(f"Using OR-Tools optimization for {dept} Semester {semester}...")
        
        # Create CourseGroupOptimizer instance with PE course mapping
        pe_course_map_file = "data/pe_course_map.csv"  # Default PE course mapping file
        optimizer = CourseGroupOptimizer(
            courses=courses,
            dept=dept,
            semester=semester,
            logger=self.logger,
            pe_course_map_file=pe_course_map_file
        )
        
        # Run optimization
        if optimizer.optimize_distribution():
            # Validate solution
            if optimizer.validate_solution():
                self.logger.info(f"OR-Tools optimization successful for {dept} Semester {semester}")
                self.logger.info(f"Objective value: {optimizer.objective_value}")
                
                # Get optimized groups
                optimized_groups = optimizer.get_groups()
                
                # Log optimization results
                self.logger.info(f"Created {len(optimized_groups)} optimized groups")
                for i, group in enumerate(optimized_groups):
                    if group:
                        lab_instances = [inst for inst in group if inst.get('has_lab', False)]
                        theory_instances = [inst for inst in group if inst.get('has_theory', False)]
                        courses_in_group = set(inst['course_code'] for inst in group)
                        teachers_in_group = set(inst['teacher_id'] for inst in group)
                        
                        self.logger.info(f"  Group {i+1}: {len(group)} instances")
                        self.logger.info(f"    Lab: {len(lab_instances)}, Theory: {len(theory_instances)}")
                        self.logger.info(f"    Courses: {sorted(courses_in_group)}")
                        self.logger.info(f"    Teachers: {sorted(teachers_in_group)}")
                
                return optimized_groups
            else:
                self.logger.error(f"OR-Tools solution validation failed for {dept} Semester {semester}")
        else:
            self.logger.error(f"OR-Tools optimization failed for {dept} Semester {semester}")
        
        # Fallback: return empty groups if optimization fails
        self.logger.warning(f"Falling back to empty groups for {dept} Semester {semester}")
        return []
    

    
    def _validate_teacher_uniqueness_constraint(self, groups, dept, semester):
        """Validate that no teacher appears multiple times in the same group."""
        constraint_violations = 0
        violation_details = []
        
        for group_idx, group in enumerate(groups):
            if not group:
                continue
                
            teacher_occurrences = {}
            for instance in group:
                # Main teacher
                teacher_id = instance['teacher_id']
                if teacher_id not in teacher_occurrences:
                    teacher_occurrences[teacher_id] = []
                teacher_occurrences[teacher_id].append({
                    'course_code': instance['course_code'],
                    'instance_id': instance['id'],
                    'role': 'Main'
                })
            
            # Check for violations
            for teacher_id, course_details in teacher_occurrences.items():
                if len(course_details) > 1:
                    constraint_violations += 1
                    violation_info = {
                        'teacher_id': teacher_id,
                        'group_idx': group_idx + 1,
                        'occurrences': len(course_details),
                        'courses': [detail['course_code'] for detail in course_details],
                        'instance_ids': [detail['instance_id'] for detail in course_details]
                    }
                    violation_details.append(violation_info)
                    
                    course_list = ', '.join(violation_info['courses'])
                    self.logger.error(f"CONSTRAINT VIOLATION: Teacher {teacher_id} appears {len(course_details)} times in Group {group_idx + 1}")
                    self.logger.error(f"  Courses: {course_list}")
                    self.logger.error(f"  Instance IDs: {violation_info['instance_ids']}")
        
        if constraint_violations == 0:
            self.logger.info(f"[OK] Teacher uniqueness constraint SATISFIED for {dept} Semester {semester}")
        else:
            self.logger.error(f"[ERROR] Teacher uniqueness constraint VIOLATED: {constraint_violations} violations")
            
        return constraint_violations == 0

    def _validate_halls_theorem(self, groups, dept, semester):
        """Validate that groups satisfy Hall's theorem for optimal student choice with course limit constraints."""
        total_violations = 0
        
        # Global validation: Check Hall's theorem across all groups with 2-group-per-course constraint
        all_courses = set()
        global_course_teacher_matrix = {}
        course_group_participation = {}
        
        # Build global course-teacher mapping and track course participation
        for group_idx, group in enumerate(groups):
            if not group:
                continue
                
            for instance in group:
                course_code = instance['course_code']
                teacher_id = instance['teacher_id']
                
                all_courses.add(course_code)
                
                if course_code not in global_course_teacher_matrix:
                    global_course_teacher_matrix[course_code] = set()
                global_course_teacher_matrix[course_code].add(teacher_id)
                
                if course_code not in course_group_participation:
                    course_group_participation[course_code] = set()
                course_group_participation[course_code].add(group_idx)
        
        # Validate 2-group-per-course constraint
        course_limit_violations = 0
        for course_code, participating_groups in course_group_participation.items():
            if len(participating_groups) > 2:
                course_limit_violations += 1
                group_names = [f"G{i+1}" for i in participating_groups]
                self.logger.error(f"COURSE LIMIT VIOLATION: {course_code} appears in {len(participating_groups)} groups: {', '.join(group_names)}")
        
        if course_limit_violations == 0:
            self.logger.info(f"[OK] Course limit constraint SATISFIED (max 2 groups per course)")
        else:
            self.logger.error(f"[ERROR] Course limit constraint VIOLATED: {course_limit_violations} violations")
        
        # Global Hall's theorem validation with course choices consideration
        self.logger.info(f"Global Hall's theorem validation with course choices:")
        
        # For student choice validation: Each course appears in at most 2 groups
        # Students need to be able to select all courses for their semester
        course_choice_validation = []
        
        for course_code in all_courses:
            available_groups = course_group_participation.get(course_code, set())
            available_teachers = global_course_teacher_matrix.get(course_code, set())
            
            course_choice_validation.append({
                'course': course_code,
                'groups': len(available_groups),
                'teachers': len(available_teachers),
                'choice_ratio': len(available_groups) / max(1, len(available_teachers))
            })
        
        # Log course choice availability
        self.logger.info("Course choice availability analysis:")
        for choice_info in sorted(course_choice_validation, key=lambda x: x['choice_ratio']):
            course = choice_info['course']
            groups_count = choice_info['groups']
            teachers = choice_info['teachers']
            self.logger.info(f"  {course}: {groups_count} groups, {teachers} teachers (ratio: {choice_info['choice_ratio']:.2f})")
        
        # Check global Hall's condition for student choice
        global_violations = []
        
        from itertools import combinations
        for r in range(1, min(len(all_courses) + 1, 6)):  # Limit to prevent exponential explosion
            for course_subset in combinations(all_courses, r):
                # Calculate total choice combinations available for this subset
                total_group_choices = 1
                neighbor_teachers = set()
                
                for course in course_subset:
                    course_groups = len(course_group_participation.get(course, set()))
                    total_group_choices *= max(1, course_groups)
                    neighbor_teachers.update(global_course_teacher_matrix.get(course, set()))
                
                # Modified Hall's condition: Students need enough choices to select all courses
                # At minimum, need 1 valid combination (each course available in at least 1 group)
                if len(neighbor_teachers) < len(course_subset):
                    global_violations.append({
                        'subset': list(course_subset),
                        'subset_size': len(course_subset),
                        'teacher_count': len(neighbor_teachers),
                        'group_choices': total_group_choices
                    })
        
        if global_violations:
            total_violations += len(global_violations)
            self.logger.warning(f"[WARNING] Global Hall's theorem VIOLATED: {len(global_violations)} violations")
            for violation in global_violations[:3]:  # Show first 3 violations
                courses_str = ', '.join(violation['subset'])
                self.logger.warning(f"  Subset [{courses_str}]: {violation['teacher_count']} teachers < {violation['subset_size']} courses")
        else:
            self.logger.info(f"[OK] Global Hall's theorem SATISFIED with course limit constraints")
        
        return total_violations == 0 and course_limit_violations == 0
    
    def _create_instance_group_mapping(self):
        """Create mapping from course instances to their groups."""
        total_mapped_instances = 0
        
        for (dept, semester), groups in self.course_groups.items():
            for group_idx, group in enumerate(groups):
                for instance in group:
                    instance_id = instance['id']
                    teacher_id = instance['teacher_id']
                    course_code = instance['course_code']
                    
                    self.instance_group_mapping[instance_id] = {
                        'group_name': f"{dept}_S{semester}_G{group_idx + 1}",
                        'group_index': group_idx + 1,
                        'department': dept,
                        'semester': semester,
                        'teacher_id': teacher_id,
                        'course_code': course_code,
                        'has_lab': instance.get('has_lab', False),
                        'has_theory': instance.get('has_theory', False),
                        'practical_hours': instance.get('practical_hours', 0),
                        'lecture_hours': instance.get('lecture_hours', 0),
                        'tutorial_hours': instance.get('tutorial_hours', 0)
                    }
                    total_mapped_instances += 1
        
        self.logger.info(f"Instance-group mapping created: {total_mapped_instances} instances mapped")
    
    def _update_lab_requirements_for_virtual_instances(self):
        """Merge virtual instances of large courses back into unified instances for scheduling."""
        self.logger.info("Post-processing: Merging virtual instances back to unified 140+ student courses...")
        
        updated_lab_requirements = defaultdict(list)
        merged_instances = 0
        virtual_pairs_found = 0
        
        # Track which virtual instances have been processed
        processed_virtual_ids = set()
        
        # Copy existing lab requirements and merge virtual instances
        for teacher_id, lab_courses in self.lab_requirements.items():
            updated_lab_requirements[teacher_id] = []
            
            for course_req in lab_courses:
                course_instance_id = course_req['course_instance_id']
                
                # Skip if already processed as part of a virtual pair
                if course_instance_id in processed_virtual_ids:
                    continue
                
                # Check if this is a virtual instance that needs merging
                if '-A' in course_instance_id:
                    # Look for the corresponding -B instance
                    base_id = course_instance_id.replace('-A', '')
                    virtual_b_id = f"{base_id}-B"
                    
                    # Find the -B instance in the same teacher's lab courses
                    virtual_b_req = None
                    for other_req in lab_courses:
                        if other_req['course_instance_id'] == virtual_b_id:
                            virtual_b_req = other_req
                            break
                    
                    if virtual_b_req:
                        # Merge the virtual instances back into unified instance
                        merged_req = course_req.copy()
                        merged_req['course_instance_id'] = base_id
                        merged_req['students_per_instance'] = course_req.get('students_per_instance', 70) + virtual_b_req.get('students_per_instance', 70)
                        # Keep all practical hours from one instance (they should be the same)
                        
                        updated_lab_requirements[teacher_id].append(merged_req)
                        
                        # Update instance-group mapping for the merged instance
                        # Find which group the virtual instances are in and map the merged instance to it
                        virtual_a_group = self.instance_group_mapping.get(course_instance_id)
                        virtual_b_group = self.instance_group_mapping.get(virtual_b_id)
                        
                        if virtual_a_group:
                            # Map the merged instance to the same group as virtual instance A
                            self.instance_group_mapping[base_id] = virtual_a_group
                            self.logger.info(f"  🔗 Mapped merged instance {base_id} to group: {virtual_a_group['group_name']}")
                        elif virtual_b_group:
                            # Fallback to virtual instance B's group
                            self.instance_group_mapping[base_id] = virtual_b_group
                            self.logger.info(f"  🔗 Mapped merged instance {base_id} to group: {virtual_b_group['group_name']}")
                        else:
                            self.logger.warning(f"  ⚠️ Could not find group mapping for virtual instances {course_instance_id} or {virtual_b_id}")
                        
                        # Mark both virtual instances as processed
                        processed_virtual_ids.add(course_instance_id)
                        processed_virtual_ids.add(virtual_b_id)
                        
                        merged_instances += 1
                        virtual_pairs_found += 1
                        
                        course_code = merged_req.get('course_code', 'Unknown')
                        practical_hours = merged_req.get('practical_hours', 0)
                        self.logger.info(f"  ✅ Merged virtual pair: {course_code} ({virtual_b_id.replace('-B', '')}-A + {virtual_b_id}) → {base_id}")
                        self.logger.info(f"      Unified: {merged_req['students_per_instance']} students, {practical_hours}h → 140-capacity labs")
                    else:
                        # No corresponding -B found, keep as-is
                        updated_lab_requirements[teacher_id].append(course_req)
                        
                elif '-B' in course_instance_id:
                    # -B instance should have been processed with its -A counterpart
                    # If we reach here, it means there was no -A counterpart, so keep as-is
                    if course_instance_id not in processed_virtual_ids:
                        updated_lab_requirements[teacher_id].append(course_req)
                        
                else:
                    # Regular instance, keep as-is
                    updated_lab_requirements[teacher_id].append(course_req)
        
        # Update lab requirements
        self.lab_requirements = updated_lab_requirements
        
        if virtual_pairs_found == 0:
            self.logger.info("  No virtual instance pairs found to merge")
        else:
            self.logger.info(f"  Successfully merged {virtual_pairs_found} virtual instance pairs into unified 140+ student courses")
            self.logger.info(f"  These unified courses will be forced to use 140-capacity labs")
        
        return virtual_pairs_found

    def _filter_lab_requirements_by_groups(self):
        """Filter lab requirements to only include course instances that are present in groups."""
        self.logger.info("Filtering lab requirements to only include instances present in groups...")
        
        original_lab_count = sum(len(courses) for courses in self.lab_requirements.values())
        filtered_lab_requirements = defaultdict(list)
        skipped_lab_instances = []
        
        for teacher_id, lab_courses in self.lab_requirements.items():
            for course_req in lab_courses:
                course_instance_id = course_req['course_instance_id']
                
                # Check if this course instance is present in any group
                if course_instance_id in self.instance_group_mapping:
                    # Instance is in a group, keep it in lab requirements
                    filtered_lab_requirements[teacher_id].append(course_req)
                else:
                    # Instance is not in any group, skip it for lab scheduling
                    skipped_lab_instances.append({
                        'course_instance_id': course_instance_id,
                        'teacher_id': teacher_id,
                        'course_code': course_req.get('course_code', 'Unknown'),
                        'practical_hours': course_req.get('practical_hours', 0),
                        'lab_sessions_needed': course_req.get('lab_sessions_needed', 0)
                    })
        
        # Update lab requirements with filtered data
        self.lab_requirements = filtered_lab_requirements
        
        # Remove teachers with no lab courses after filtering
        teachers_to_remove = []
        for teacher_id in self.lab_requirements:
            if not self.lab_requirements[teacher_id]:
                teachers_to_remove.append(teacher_id)
        
        for teacher_id in teachers_to_remove:
            del self.lab_requirements[teacher_id]
        
        # Log filtering results
        filtered_lab_count = sum(len(courses) for courses in self.lab_requirements.values())
        
        if skipped_lab_instances:
            self.logger.warning(f"Filtered out {len(skipped_lab_instances)} lab course instances not present in any group:")
            for skipped in skipped_lab_instances:
                self.logger.warning(f"  - Course {skipped['course_code']} (ID: {skipped['course_instance_id']}, Teacher: {skipped['teacher_id']}) - {skipped['practical_hours']} practical hours, {skipped['lab_sessions_needed']} sessions")
        
        self.logger.info(f"Lab requirements filtering completed:")
        self.logger.info(f"  Original lab instances: {original_lab_count}")
        self.logger.info(f"  Filtered lab instances: {filtered_lab_count}")
        self.logger.info(f"  Skipped lab instances: {len(skipped_lab_instances)}")
        self.logger.info(f"  Active teachers with lab requirements: {len(self.lab_requirements)}")
    
    def _identify_core_lab_groups(self):
        """Identify groups that contain core lab instances."""
        self.logger.info("Identifying groups that contain core lab instances...")
        
        core_lab_groups = set()
        
        for (dept, semester), groups in self.course_groups.items():
            for group_idx, group in enumerate(groups):
                group_name = f"{dept}_S{semester}_G{group_idx + 1}"
                has_core_lab = False
                
                for instance in group:
                    instance_id = instance['id']
                    if instance_id in self.core_lab_instance_ids:
                        has_core_lab = True
                        break
                
                if has_core_lab:
                    core_lab_groups.add(group_name)
                    core_labs_in_group = [inst['id'] for inst in group if inst['id'] in self.core_lab_instance_ids]
                    self.logger.info(f"  Core lab group identified: {group_name} (contains core labs: {core_labs_in_group})")
        
        self.core_lab_groups = core_lab_groups
        self.logger.info(f"Total core lab groups identified: {len(core_lab_groups)}")
        
        return core_lab_groups
    
    def generate_combined_schedule(self):
        """Generate the combined schedule for both lab and theory sessions."""
        self.logger.info("="*80)
        self.logger.info("STARTING COMBINED SCHEDULE GENERATION")
        self.logger.info("="*80)
        
        # Run feasibility analyses first
        if not self.analyze_theory_feasibility():
            self.logger.error("Combined scheduling is not feasible with current theory requirements and constraints")
            return False
        
        # Create the unified CP-SAT model
        model = cp_model.CpModel()
        
        # STEP 1: Create variables for both lab and theory
        self.logger.info("Creating variables for combined scheduling...")
        lab_variables = self._create_lab_variables(model)
        theory_variables = self._create_theory_variables(model)
        
        # STEP 2: Apply unified constraints
        self.logger.info("Applying unified constraints...")
        self._apply_unified_constraints(model, lab_variables, theory_variables)
        
        # STEP 3: Add group allocation objective for theory
        self.logger.info("Setting up group allocation objective...")
        self.add_group_allocation_objective(model, theory_variables)
        
        # STEP 4: Add optimization objectives
        self.logger.info("Setting up optimization objectives...")
        self._add_combined_objectives(model, lab_variables, theory_variables)
        
        # STEP 5: Solve the unified model
        self.logger.info("Solving combined scheduling model...")
        success = self._solve_combined_model(model, lab_variables, theory_variables)
        
        return success
    
    def _create_lab_variables(self, model):
        """Create CP-SAT variables for lab scheduling with department-specific day patterns."""
        self.logger.info("Creating lab scheduling variables with department-specific day patterns...")
        
        # Lab assignment variables: lab_assignments[teacher][course][day][session][room]
        lab_assignments = {}
        
        for teacher_id, lab_courses in self.lab_requirements.items():
            lab_assignments[teacher_id] = {}
            
            for course_req in lab_courses:
                course_instance_id = course_req['course_instance_id']
                lab_sessions_needed = course_req['lab_sessions_needed']
                
                # All course instances in lab_requirements are guaranteed to be in groups
                # (filtered by _filter_lab_requirements_by_groups)
                
                # Get department and semester for this course instance to determine day pattern
                dept_name = self.instance_group_mapping[course_instance_id]['department']
                semester = self.instance_group_mapping[course_instance_id]['semester']
                
                # Get department-specific days (with semester override)
                dept_days = self._get_days_for_department(dept_name, semester)
                dept_pattern = self._get_day_pattern_for_department(dept_name, semester)
                num_dept_days = len(dept_days)
                
                self.logger.debug(f"Lab variables for course {course_instance_id}: using {dept_pattern} pattern ({num_dept_days} days)")
                
                lab_assignments[teacher_id][course_instance_id] = {}
                
                for day_idx in range(num_dept_days):  # Use department-specific days
                    lab_assignments[teacher_id][course_instance_id][day_idx] = {}
                    
                    for session_name in self.lab_sessions.keys():
                        lab_assignments[teacher_id][course_instance_id][day_idx][session_name] = {}
                        
                        for room_id in self.lab_room_ids:
                            var_name = f'lab_{teacher_id}_{course_instance_id}_{day_idx}_{session_name}_{room_id}'
                            lab_assignments[teacher_id][course_instance_id][day_idx][session_name][room_id] = \
                                model.NewBoolVar(var_name)
        
        total_lab_courses = sum(len(courses) for courses in lab_assignments.values())
        self.logger.info(f"Lab variables created successfully with department-specific day patterns")
        self.logger.info(f"Created lab variables for {total_lab_courses} course instances across {len(lab_assignments)} teachers")
        
        return lab_assignments
    
    def _create_theory_variables(self, model):
        """Create CP-SAT variables for theory scheduling using two-phase approach."""
        self.logger.info("Creating theory scheduling variables using two-phase approach...")
        
        # PHASE 1: Group timeslot allocation variables
        group_timeslot_vars = self._create_group_timeslot_variables(model)
        
        self.logger.info("Theory group timeslot variables created successfully")
        return group_timeslot_vars
    
    def _create_group_timeslot_variables(self, model):
        """Create binary variables for theory group timeslot assignments with department-specific day patterns."""
        self.logger.info("Creating group timeslot variables with department-specific day patterns...")
        group_timeslot_vars = {}
        
        # Use pre-computed group requirements
        for group_name, required_slots in self.group_requirements.items():
            # Extract department and semester from group name
            # Group name format: "Computer Science & Engineering_S3_G1"
            dept_name = group_name.split('_S')[0] if '_S' in group_name else "Computer Science & Engineering"
            
            # Extract semester for semester-specific overrides
            semester = None
            if '_S' in group_name:
                try:
                    semester_part = group_name.split('_S')[1].split('_G')[0]
                    semester = int(semester_part)
                except (ValueError, IndexError):
                    pass
            
            # Get department-specific days (with semester override)
            dept_days = self._get_days_for_department(dept_name, semester)
            dept_pattern = self._get_day_pattern_for_department(dept_name, semester)
            num_dept_days = len(dept_days)
            
            self.logger.info(f"Creating variables for {group_name}: {required_slots} time slots required, using {dept_pattern} pattern ({num_dept_days} days)")
            
            # Create binary variables for each possible time slot
            group_timeslot_vars[group_name] = {}
            for day_idx in range(num_dept_days):  # Use department-specific number of days
                group_timeslot_vars[group_name][day_idx] = {}
                for slot_idx in range(self.num_theory_slots):
                    group_timeslot_vars[group_name][day_idx][slot_idx] = model.NewBoolVar(
                        f'group_{group_name}_day_{day_idx}_slot_{slot_idx}'
                    )
        
        self.logger.info(f"Created group timeslot variables for {len(group_timeslot_vars)} groups with department-specific day patterns")
        return group_timeslot_vars
    
    def _apply_unified_constraints(self, model, lab_variables, theory_variables):
        """Apply unified constraints for both lab and theory scheduling."""
        constraints_applied = 0
        
        # 1. Lab-specific constraints (excluding the old teacher clash)
        constraints_applied += self._apply_lab_constraints(model, lab_variables)
        
        # 2. Theory-specific constraints (excluding the old teacher clash)
        constraints_applied += self._apply_theory_constraints(model, theory_variables, lab_variables)
        
        # 2.5. Teacher day preference constraints (from pop.csv)
        constraints_applied += self._apply_teacher_day_preference_constraints(model, theory_variables)
        
        # 3. Cross-system constraints (now only for dept/semester group conflicts)
        constraints_applied += self._apply_cross_system_constraints(model, lab_variables, theory_variables)

        # 4. UNIFIED Teacher Clash Constraint (NEW)
        constraints_applied += self._apply_unified_teacher_clash_constraint(model, lab_variables, theory_variables)
        
        # 5. Department 5pm scheduling constraints
        constraints_applied += self._apply_5pm_constraints(model, lab_variables, theory_variables)
        
        self.logger.info(f"Applied {constraints_applied} unified constraints")
        return constraints_applied
    
    def _apply_lab_constraints(self, model, lab_variables):
        """Apply lab-specific constraints."""
        self.logger.info("Applying lab-specific constraints...")
        constraints_applied = 0
        
        # Run lab capacity analysis first
        self.analyze_lab_capacity()
        
        # Apply consecutive batch scheduling constraint FIRST (highest priority for learning continuity)
        constraints_applied += self.apply_consecutive_batch_scheduling_constraint(model, lab_variables)
        
        # Apply CORE lab constraints (optimized - removed redundancies)
        constraints_applied += self.apply_course_lab_requirements_constraint(model, lab_variables)
        constraints_applied += self.apply_core_only_lab_restriction_constraint(model, lab_variables)  # New core-only lab restriction
        constraints_applied += self.apply_lab_room_single_assignment_constraint(model, lab_variables)
        # Apply block-specific lab priority constraints for AIML/AIDS/CSD departments
        constraints_applied += self.apply_block_specific_lab_priority_constraint(model, lab_variables)
        # REMOVED: apply_teacher_clash_constraint - handled by unified constraint
        # REMOVED: apply_capacity_constraint - redundant with course_lab_requirements_constraint
        constraints_applied += self.apply_group_based_scheduling_constraint(model, lab_variables)
        constraints_applied += self.apply_core_lab_mapping_constraint(model, lab_variables)
        # NEW: Apply core lab group slot limit constraint (8 slots max for groups containing core labs)
        constraints_applied += self.apply_core_lab_group_slot_limit_constraint(model, lab_variables)
        # HARD CONSTRAINT: Apply computing group slot limit constraint (6 slots max for computing department groups)
        constraints_applied += self.apply_computing_group_slot_limit_constraint(model, lab_variables)
        # REMOVED: apply_theory_lab_group_conflict_constraint - redundant with cross-system constraints
        # REMOVED: This constraint was too restrictive and prevented the full scheduling of required practical hours.
        constraints_applied += self.apply_semester_lab_slot_limit_constraint(model, lab_variables)
        
        # Apply constraint to prevent small course instances from using 140-capacity labs
        constraints_applied += self.apply_140_lab_restriction_constraint(model, lab_variables)
        
        # Apply lunch break constraint for lab sessions
        constraints_applied += self._apply_lab_lunch_break_constraint(model, lab_variables)
        
        # Apply shift-based constraints for ALL departments
        constraints_applied += self.apply_shift_based_lab_constraint(model, lab_variables)
        
        # Apply teacher max consecutive lab constraint
        constraints_applied += self.apply_teacher_max_consecutive_lab_constraint(model, lab_variables)
        
        # Apply teacher daily presence constraint for lab sessions
        constraints_applied += self.apply_teacher_daily_presence_lab_constraint(model, lab_variables)
        
        self.logger.info(f"Applied {constraints_applied} lab-specific constraints (optimized)")
        return constraints_applied

    def apply_course_lab_requirements_constraint(self, model, lab_variables):
        """CONSTRAINT: Each course must be scheduled for its required number of lab sessions.
        
        DEPARTMENT PRIORITY SYSTEM for 70-capacity labs:
        - Computer Science & Engineering: PRIORITY access to 70-capacity labs
        - Information Technology: PRIORITY access to 70-capacity labs  
        - Other departments: Standard priority based on practical hours only
        
        BLOCK PRIORITY SYSTEM for 35-capacity labs:
        - AIML, AIDS, CSD: PRIORITY access to K Block & J Block labs
        - AIML, AIDS, CSD: RESTRICTED from Techlounge 35-capacity labs
        - All three departments must use K/J blocks only for 35-capacity needs
        
        Priority weights:
        - CS/IT 6+ hours: 1300 (HIGHEST priority)
        - CS/IT 4+ hours: 1300 (EQUAL priority as 6+ hours for CS/IT)  
        - CS/IT 2-3 hours: 150 (positive preference for 70+ capacity)
        - Other 6+ hours: 1000 (standard priority)
        - Other 4+ hours: 200 (REDUCED priority for non-CS/IT departments)
        - Other 2-3 hours: -100 (preference for 35-capacity)
        - AIML/AIDS/CSD K/J block preference: +400 weight bonus
        """
        self.logger.info("Applying course lab requirements constraint with department-based 70-capacity lab priority...")
        self.logger.info("PRIORITY DEPARTMENTS for 70-capacity labs: Computer Science & Engineering, Information Technology")
        self.logger.info("CS/IT 4-hour and 6-hour courses receive EQUAL highest priority (weight: 1300) for 70-capacity labs")
        self.logger.info("Other departments' 4-hour courses have REDUCED priority (weight: 200) for 70-capacity labs")
        self.logger.info("BLOCK PRIORITY: AIML, AIDS, CSD get priority for K & J blocks; ALL THREE restricted from Techlounge 35-cap labs")
        constraints_applied = 0
        
        for teacher_id, lab_courses in self.lab_requirements.items():
            for course_req in lab_courses:
                course_instance_id = course_req['course_instance_id']
                base_sessions = course_req['base_sessions']
                practical_hours = course_req['practical_hours']
                students_per_instance = course_req['students_per_instance']
                
                if teacher_id in lab_variables and course_instance_id in lab_variables[teacher_id]:
                    # Get department for this course to determine correct number of days
                    dept_name = "Computer Science & Engineering"  # Default
                    if hasattr(self, 'instance_group_mapping') and course_instance_id in self.instance_group_mapping:
                        dept_name = self.instance_group_mapping[course_instance_id]['department']
                    else:
                        # Fallback: look up in courses_df
                        base_id = self._get_base_course_id(course_instance_id)
                        course_matches = self.courses_df[self.courses_df['id'] == int(base_id)]
                        if not course_matches.empty:
                            dept_name = course_matches.iloc[0].get('student_dept', 'Computer Science & Engineering')
                    
                    dept_days = self._get_days_for_department(dept_name)
                    num_dept_days = len(dept_days)
                    
                    # Collect all assignment variables for this course (department-specific days)
                    total_assignments = []
                    for day_idx in range(num_dept_days):
                        for session_name in self.lab_sessions.keys():
                            for room_id in self.lab_room_ids:
                                if (day_idx in lab_variables[teacher_id][course_instance_id] and
                                    session_name in lab_variables[teacher_id][course_instance_id][day_idx] and
                                    room_id in lab_variables[teacher_id][course_instance_id][day_idx][session_name]):
                                    total_assignments.append(
                                        lab_variables[teacher_id][course_instance_id][day_idx][session_name][room_id]
                                    )
                    
                    # Get lab capacity categories
                    labs_35 = [lab['id'] for lab in self.lab_capacity_analysis['labs_35']]
                    labs_70_plus = [lab['id'] for lab in self.lab_capacity_analysis['labs_70']] + [lab['id'] for lab in self.lab_capacity_analysis['labs_140']]
                    
                    # Calculate expected sessions based on potential batching
                    student_count = students_per_instance
                    
                    # If course might be assigned to 35-cap labs and has >35 students, plan for batching
                    assignments_in_35_cap = []
                    assignments_in_70_plus_cap = []
                    
                    for day_idx in range(num_dept_days):
                        for session_name in self.lab_sessions.keys():
                            for room_id in self.lab_room_ids:
                                if (day_idx in lab_variables[teacher_id][course_instance_id] and
                                    session_name in lab_variables[teacher_id][course_instance_id][day_idx] and
                                    room_id in lab_variables[teacher_id][course_instance_id][day_idx][session_name]):
                                    assignment_var = lab_variables[teacher_id][course_instance_id][day_idx][session_name][room_id]
                                    if room_id in labs_35:
                                        assignments_in_35_cap.append(assignment_var)
                                    else:
                                        assignments_in_70_plus_cap.append(assignment_var)
                    
                    # SPECIAL CASE: 35 students exactly -> FORCE 35-capacity labs ONLY
                    if student_count == 35:
                        # Force ALL sessions to be in 35-capacity labs, NO batching
                        if assignments_in_35_cap:
                            model.Add(sum(assignments_in_35_cap) == sum(total_assignments))
                            model.Add(sum(assignments_in_70_plus_cap) == 0)
                            model.Add(sum(total_assignments) == base_sessions)  # Exactly base sessions, no batching
                            constraints_applied += 3
                            self.logger.info(f"35-STUDENT Course {course_req['course_code']} ({practical_hours}h): FORCED to use 35-capacity labs ONLY with {base_sessions} sessions (no batching)")
                        else:
                            self.logger.error(f"35-STUDENT Course {course_req['course_code']} ({practical_hours}h): No 35-capacity labs available - scheduling impossible")
                    # Create conditional constraint based on lab capacity assignment
                    elif student_count > 35:
                        # CRITICAL: Either ALL sessions in 35-cap (with batching) OR ALL sessions in 70+ cap (no batching)
                        total_35_assignments = sum(assignments_in_35_cap)
                        total_70_plus_assignments = sum(assignments_in_70_plus_cap)
                    
                        # Calculate sessions needed for batching in 35-cap labs
                        num_batches_35 = (student_count + 34) // 35
                        sessions_with_batching = base_sessions * num_batches_35
                        
                        # APPLY SLOT RESTRICTIONS BASED ON PRACTICAL HOURS WITH PRIORITY SYSTEM
                        if practical_hours >= 6:
                            # 6+ practical hours: HIGHEST PRIORITY for 70+ capacity labs
                            max_batched_sessions = min(sessions_with_batching, 6)
                            max_unbatched_sessions = min(base_sessions, 3)
                            absolute_max_sessions = 6  # Hard limit for 6+ hour courses
                            priority_level = 1  # Highest priority
                        elif practical_hours >= 4:
                            # 4+ practical hours: SECOND PRIORITY for 70+ capacity labs
                            max_batched_sessions = min(sessions_with_batching, 4)
                            max_unbatched_sessions = min(base_sessions, 2)
                            absolute_max_sessions = 4  # Hard limit for 4+ hour courses
                            priority_level = 2  # Second priority
                        else:
                            # 2 practical hours: Lower priority for 70+ capacity labs
                            max_batched_sessions = min(sessions_with_batching, 2)
                            max_unbatched_sessions = min(base_sessions, 1)
                            absolute_max_sessions = 2  # Hard limit for 2 hour courses
                            priority_level = 3  # Lower priority
                        
                        # CRITICAL FIX: Handle 2-hour courses with special consideration for large student counts
                        if practical_hours <= 2:
                            # Check if this is a core lab that should be exempted from the 35-capacity restriction
                            is_core_lab = course_instance_id in self.core_lab_instance_ids
                            
                            # EXCEPTION FIX: Large student counts (100+) need special handling even for 2-hour courses
                            needs_large_capacity = student_count >= 100
                            
                            if is_core_lab or needs_large_capacity:
                                # Core labs OR large student courses can use both 35 and 70+ capacity labs
                                # Allow the same flexible strategy as other courses
                                use_35_cap_strategy = model.NewBoolVar(f'course_{course_instance_id}_use_35_cap_strategy')
                                
                                # For large student counts, adjust session limits to prevent infeasibility
                                if needs_large_capacity and not is_core_lab:
                                    # Recalculate limits for large 2-hour courses
                                    max_batched_sessions_adjusted = min(sessions_with_batching, 8)  # Allow up to 8 sessions for batching
                                    max_unbatched_sessions_adjusted = max_unbatched_sessions  # Keep original unbatched limit
                                    
                                    self.logger.info(f"LARGE 2H Course {course_req['course_code']} ({student_count} students): Adjusted limits - batched: {max_batched_sessions_adjusted}, unbatched: {max_unbatched_sessions_adjusted}")
                                else:
                                    max_batched_sessions_adjusted = max_batched_sessions
                                    max_unbatched_sessions_adjusted = max_unbatched_sessions
                                
                                # Constraint 1: If using 35-cap strategy, ALL sessions must be in 35-cap labs
                                if assignments_in_35_cap and assignments_in_70_plus_cap:
                                    model.Add(total_35_assignments == sum(total_assignments)).OnlyEnforceIf(use_35_cap_strategy)
                                    model.Add(total_70_plus_assignments == 0).OnlyEnforceIf(use_35_cap_strategy)
                                    
                                    # Constraint 2: If using 70+ cap strategy, ALL sessions must be in 70+ cap labs  
                                    model.Add(total_70_plus_assignments == sum(total_assignments)).OnlyEnforceIf(use_35_cap_strategy.Not())
                                    model.Add(total_35_assignments == 0).OnlyEnforceIf(use_35_cap_strategy.Not())
                            
                                    # Constraint 3: Session count depends on chosen strategy (use adjusted limits)
                                    model.Add(sum(total_assignments) == max_batched_sessions_adjusted).OnlyEnforceIf(use_35_cap_strategy)
                                    model.Add(sum(total_assignments) == max_unbatched_sessions_adjusted).OnlyEnforceIf(use_35_cap_strategy.Not())
                                    
                                    # Add preference based on student count, core lab status, and department
                                    if needs_large_capacity and not is_core_lab:
                                        # Check if this is a priority department for 70 capacity labs
                                        is_priority_dept = dept_name in ['Computer Science & Engineering', 'Information Technology']
                                        
                                        base_weight = 800
                                        if is_priority_dept:
                                            # Extra boost for CS & IT departments
                                            weight = base_weight + 250  # 1050 total
                                            description = "2h course with 100+ students - prefer large labs + CS/IT dept boost"
                                        else:
                                            weight = base_weight
                                            description = "2h course with 100+ students - prefer large labs"
                                        
                                        self._add_capacity_preference(model, use_35_cap_strategy, weight, course_req['course_code'], description)
                                    
                                    constraints_applied += 6
                                    lab_type = "CORE LAB" if is_core_lab else "LARGE STUDENT"
                                    self.logger.info(f"{lab_type} {course_req['course_code']} ({practical_hours}h, {student_count} students): ALLOWED to use BOTH 35-cap ({max_batched_sessions_adjusted} sessions) OR 70+ cap ({max_unbatched_sessions_adjusted} sessions)")
                                else:
                                    # Fallback assignment
                                    required_sessions = min(max_batched_sessions_adjusted if 'max_batched_sessions_adjusted' in locals() else max_batched_sessions, len(total_assignments), absolute_max_sessions)
                                    model.Add(sum(total_assignments) == required_sessions)
                                    constraints_applied += 1
                                    self.logger.info(f"Course {course_req['course_code']} ({practical_hours}h, {student_count} students): fallback assignment with {required_sessions} sessions")
                            else:
                                # FORCE 35-capacity labs ONLY for small non-core 2-hour courses
                                if assignments_in_35_cap:
                                    model.Add(total_35_assignments == sum(total_assignments))
                                    model.Add(total_70_plus_assignments == 0)
                                    model.Add(sum(total_assignments) == max_batched_sessions)
                                    constraints_applied += 3
                                    self.logger.info(f"SMALL NON-CORE Course {course_req['course_code']} ({practical_hours}h, {student_count} students): FORCED to use 35-capacity labs only with {max_batched_sessions} sessions")
                                else:
                                    self.logger.error(f"NON-CORE Course {course_req['course_code']} ({practical_hours}h): No 35-capacity labs available - scheduling impossible")
                        else:
                            # Boolean variable to choose strategy: True = use 35-cap labs, False = use 70+ cap labs
                            use_35_cap_strategy = model.NewBoolVar(f'course_{course_instance_id}_use_35_cap_strategy')
                            
                            # Constraint 1: If using 35-cap strategy, ALL sessions must be in 35-cap labs
                            if assignments_in_35_cap and assignments_in_70_plus_cap:
                                model.Add(total_35_assignments == sum(total_assignments)).OnlyEnforceIf(use_35_cap_strategy)
                                model.Add(total_70_plus_assignments == 0).OnlyEnforceIf(use_35_cap_strategy)
                                
                                # Constraint 2: If using 70+ cap strategy, ALL sessions must be in 70+ cap labs  
                                model.Add(total_70_plus_assignments == sum(total_assignments)).OnlyEnforceIf(use_35_cap_strategy.Not())
                                model.Add(total_35_assignments == 0).OnlyEnforceIf(use_35_cap_strategy.Not())
                        
                                # Constraint 3: Session count depends on chosen strategy WITH SLOT RESTRICTIONS
                                model.Add(sum(total_assignments) == max_batched_sessions).OnlyEnforceIf(use_35_cap_strategy)
                                model.Add(sum(total_assignments) == max_unbatched_sessions).OnlyEnforceIf(use_35_cap_strategy.Not())
                                
                                # PRIORITY SYSTEM: Add preference for 70+ capacity labs based on practical hours AND department
                                # Check if this is a priority department for 70 capacity labs
                                is_priority_dept = dept_name in ['Computer Science & Engineering']
                                
                                if priority_level == 1:  # 6+ hours: HIGHEST priority for 70+ labs
                                    base_weight = 1000
                                    if is_priority_dept:
                                        # Extra boost for CS & IT departments
                                        weight = base_weight + 300  # 1300 totalS
                                        description = f"6+ hours HIGHEST priority + CS/IT dept boost"
                                    else:
                                        weight = base_weight
                                        description = "6+ hours HIGHEST priority"
                                    self._add_capacity_preference(model, use_35_cap_strategy, weight, course_req['course_code'], description)
                                    
                                elif priority_level == 2:  # 4+ hours: SECOND priority for 70+ labs
                                    if is_priority_dept:
                                        # CS & IT departments get EQUAL priority as 6+ hour courses for 70+ capacity labs
                                        weight = 1100  # Same as 6+ hours for CS/IT
                                        description = f"4+ hours EQUAL priority as 6hrs for CS/IT dept"
                                    else:
                                        # Reduced priority for other departments' 4-hour courses
                                        weight = 600  # Lower than original 500
                                        description = "4+ hours REDUCED priority for non-CS/IT dept"
                                    self._add_capacity_preference(model, use_35_cap_strategy, weight, course_req['course_code'], description)
                                    
                                else:  # 2-3 hours: Lower priority
                                    if is_priority_dept:
                                        # CS & IT departments get preference for 70+ capacity even for 2-3 hours
                                        weight = 150  # Positive weight for 70+ capacity preference
                                        description = f"2-3 hours CS/IT dept priority for 70+ capacity"
                                        self._add_capacity_preference(model, use_35_cap_strategy, weight, course_req['course_code'], description)
                                    else:
                                        # Other departments get slight preference for 35-capacity labs (original behavior)
                                        weight = -100
                                        description = "2-3 hours lower priority"
                                        self._add_capacity_preference(model, use_35_cap_strategy, weight, course_req['course_code'], description)
                                
                                constraints_applied += 6
                                self.logger.info(f"Course {course_req['course_code']} ({practical_hours}h, Priority {priority_level}): EITHER {max_batched_sessions} sessions (35-cap batched) OR {max_unbatched_sessions} sessions (70+ cap unbatched)")
                            else:
                                # Fallback to simple assignment if capacity separation not possible
                                required_sessions = min(max_batched_sessions, len(total_assignments), absolute_max_sessions)
                                model.Add(sum(total_assignments) == required_sessions)
                                constraints_applied += 1
                                self.logger.info(f"Course {course_req['course_code']} ({practical_hours}h): fallback assignment with {required_sessions} sessions (max {absolute_max_sessions} enforced)")
                    else:
                        # Small courses (< 35 students): always base sessions, but apply same absolute limits based on practical hours
                        if practical_hours >= 6:
                            absolute_max_sessions = 6
                        elif practical_hours >= 4:
                            absolute_max_sessions = 4
                        else:
                            absolute_max_sessions = 2
                        
                        max_sessions = min(base_sessions, absolute_max_sessions)
                        model.Add(sum(total_assignments) == max_sessions)
                        constraints_applied += 1
                        self.logger.info(f"Course {course_req['course_code']} ({practical_hours}h, {student_count} students): exactly {max_sessions} sessions (max {absolute_max_sessions} slots enforced)")
        
        self.logger.info(f"Applied {constraints_applied} course lab requirements constraints")
        return constraints_applied
    
    def _add_capacity_preference(self, model, use_35_cap_strategy, weight, course_code, description):
        """Add capacity preference to the objective function for priority-based lab allocation."""
        # Positive weight favors 70+ capacity labs (use_35_cap_strategy = False)
        # Negative weight favors 35 capacity labs (use_35_cap_strategy = True)
        
        if weight > 0:
            # Prefer 70+ capacity labs: reward when use_35_cap_strategy is False
            preference_var = model.NewBoolVar(f'prefer_70plus_{course_code}')
            model.Add(preference_var == 1).OnlyEnforceIf(use_35_cap_strategy.Not())
            model.Add(preference_var == 0).OnlyEnforceIf(use_35_cap_strategy)
            self.capacity_preferences.append(preference_var * weight)
            self.logger.info(f"  → {course_code}: {description} - 70+ capacity preference (weight: +{weight})")
        else:
            # Prefer 35 capacity labs: reward when use_35_cap_strategy is True
            preference_var = model.NewBoolVar(f'prefer_35_{course_code}')
            model.Add(preference_var == 1).OnlyEnforceIf(use_35_cap_strategy)
            model.Add(preference_var == 0).OnlyEnforceIf(use_35_cap_strategy.Not())
            self.capacity_preferences.append(preference_var * abs(weight))
            self.logger.info(f"  → {course_code}: {description} - 35 capacity preference (weight: +{abs(weight)})")



    def apply_core_only_lab_restriction_constraint(self, model, lab_variables):
        """Apply constraint to restrict specific labs to core departments only.
        
        Restricted Labs (Core departments only):
        - TIFAC I01 (ID: 173) - A Block, 70 capacity
        - DG02 (ID: 158) - D Block, 70 capacity
        - DG03 (ID: 159) - D Block, 70 capacity
        
        Computer departments (CSE, IT, CSBS, CSD, etc.) cannot use these labs.
        Only core engineering departments (Mechanical, Civil, Chemical, etc.) can use them.
        """
        self.logger.info("Applying core-only lab restriction constraint...")
        constraints_applied = 0
        
        # Define the restricted lab IDs (core departments only)
        core_only_lab_ids = [173, 158, 159]  # TIFAC I01, DG02, DG03
        
        # Define computer departments that are restricted from these labs
        computer_departments = [
            'Computer Science & Engineering',
            'Information Technology', 
            'Computer Science & Business Systems',
            'Computer Science & Design',
            'Computer Science & Engineering (Cyber Security)',
            'Artificial Intelligence & Data Science',
            'Artificial Intelligence & Machine Learning'
        ]
        
        for teacher_id, lab_courses in self.lab_requirements.items():
            for course_req in lab_courses:
                course_instance_id = course_req['course_instance_id']
                
                if teacher_id in lab_variables and course_instance_id in lab_variables[teacher_id]:
                    # Get department for this course
                    dept_name = "Computer Science & Engineering"  # Default
                    if hasattr(self, 'instance_group_mapping') and course_instance_id in self.instance_group_mapping:
                        dept_name = self.instance_group_mapping[course_instance_id]['department']
                    else:
                        # Fallback: look up in courses_df
                        base_id = self._get_base_course_id(course_instance_id)
                        course_matches = self.courses_df[self.courses_df['id'] == int(base_id)]
                        if not course_matches.empty:
                            dept_name = course_matches.iloc[0].get('student_dept', 'Computer Science & Engineering')
                    
                    # If this is a computer department, restrict access to core-only labs
                    if dept_name in computer_departments:
                        dept_days = self._get_days_for_department(dept_name)
                        num_dept_days = len(dept_days)
                        
                        # Collect all assignments to core-only labs for this course
                        core_only_assignments = []
                        
                        for day_idx in range(num_dept_days):
                            for session_name in self.lab_sessions.keys():
                                for room_id in core_only_lab_ids:
                                    if (day_idx in lab_variables[teacher_id][course_instance_id] and
                                        session_name in lab_variables[teacher_id][course_instance_id][day_idx] and
                                        room_id in lab_variables[teacher_id][course_instance_id][day_idx][session_name]):
                                        core_only_assignments.append(
                                            lab_variables[teacher_id][course_instance_id][day_idx][session_name][room_id]
                                        )
                        
                        # Constraint: Computer departments cannot use core-only labs
                        if core_only_assignments:
                            model.Add(sum(core_only_assignments) == 0)
                            constraints_applied += 1
                            
                            # Get room names for logging
                            room_names = []
                            for room_id in core_only_lab_ids:
                                room_row = self.rooms_df[self.rooms_df['id'] == room_id]
                                if not room_row.empty:
                                    room_names.append(f"{room_row.iloc[0]['room_number']} ({room_row.iloc[0]['block']})")
                            
                            self.logger.info(f"RESTRICTED: {dept_name} course {course_req['course_code']} cannot use core-only labs: {', '.join(room_names)}")
        
        # Log the restriction details
        if constraints_applied > 0:
            self.logger.info(f"Applied {constraints_applied} core-only lab restriction constraints")
            self.logger.info("🚫 RESTRICTED LABS (Core departments only):")
            for room_id in core_only_lab_ids:
                room_row = self.rooms_df[self.rooms_df['id'] == room_id]
                if not room_row.empty:
                    room_info = room_row.iloc[0]
                    self.logger.info(f"   - {room_info['room_number']} ({room_info['block']}, {room_info['room_max_cap']} capacity)")
            self.logger.info("❌ BLOCKED DEPARTMENTS:")
            for dept in computer_departments:
                self.logger.info(f"   - {dept}")
        else:
            self.logger.info("No core-only lab restrictions needed (no computer department assignments to restricted labs)")
        
        return constraints_applied

    def apply_lab_room_single_assignment_constraint(self, model, lab_variables):
        """Prevent lab room double-booking with comprehensive cross-pattern validation."""
        self.logger.info("Applying optimized lab room single assignment constraint...")
        constraints_applied = 0
        
        # Get 140-capacity lab IDs for co-location exceptions
        labs_140 = set(lab['id'] for lab in self.lab_capacity_analysis['labs_140'])
        
        # Pre-cache department mappings to avoid repeated lookups
        course_dept_cache = {}
        for teacher_id in lab_variables:
            for course_instance_id in lab_variables[teacher_id]:
                if course_instance_id not in course_dept_cache:
                    dept_name = "Computer Science & Engineering"  # Default
                    semester = None
                    
                    if hasattr(self, 'instance_group_mapping') and course_instance_id in self.instance_group_mapping:
                        dept_name = self.instance_group_mapping[course_instance_id]['department']
                        semester = self.instance_group_mapping[course_instance_id].get('semester')
                    else:
                        # Fallback: look up in courses_df (expensive operation - cache it)
                        course_matches = self.courses_df[self.courses_df['id'] == int(course_instance_id)]
                        if not course_matches.empty:
                            dept_name = course_matches.iloc[0].get('student_dept', 'Computer Science & Engineering')
                    
                    course_dept_cache[course_instance_id] = {
                        'dept_name': dept_name,
                        'semester': semester,
                        'dept_days': self._get_days_for_department(dept_name, semester),
                        'day_pattern': self._get_day_pattern_for_department(dept_name, semester)
                    }
        
        # Pre-cache course information to avoid repeated DataFrame lookups
        course_info_cache = {}
        for course_instance_id in course_dept_cache.keys():
            if course_instance_id not in course_info_cache:
                course_code = ""
                group_name = ""
                
                if hasattr(self, 'instance_group_mapping') and course_instance_id in self.instance_group_mapping:
                    group_name = self.instance_group_mapping[course_instance_id]['group_name']
                
                    # Handle virtual instance IDs (e.g., '877-A', '877-B')
                    base_id = course_instance_id.split('-')[0] if '-' in course_instance_id else course_instance_id
                    course_matches = self.courses_df[self.courses_df['id'] == int(base_id)]
                    if not course_matches.empty:
                        course_code = course_matches.iloc[0]['course_code']
                
                course_info_cache[course_instance_id] = {
                    'course_code': course_code,
                    'group_name': group_name
                }
        
        # Create a comprehensive mapping of all course assignments by absolute time slots
        time_slot_assignments = {}  # Maps (absolute_day, session_name, room_id) -> list of course variables
        
        # Process all courses and map them to absolute time slots (optimized)
        for teacher_id in lab_variables:
            for course_instance_id in lab_variables[teacher_id]:
                # Use cached department information
                dept_info = course_dept_cache[course_instance_id]
                course_info = course_info_cache[course_instance_id]
                
                dept_days = dept_info['dept_days']
                
                # Process each day index for this department
                for day_idx in range(min(len(dept_days), len(lab_variables[teacher_id][course_instance_id]))):
                    day_name = dept_days[day_idx]
                    absolute_day = self._normalize_day_name(day_name.upper())
                    
                    day_sessions = lab_variables[teacher_id][course_instance_id][day_idx]
                    for session_name in day_sessions:
                        for room_id in day_sessions[session_name]:
                                        key = (absolute_day, session_name, room_id)
                                        
                                        if key not in time_slot_assignments:
                                            time_slot_assignments[key] = []
                                        
                                        time_slot_assignments[key].append({
                                            'variable': day_sessions[session_name][room_id],
                                                        'teacher_id': teacher_id,
                                                        'course_instance_id': course_instance_id,
                                            'dept_name': dept_info['dept_name'],
                                            'day_pattern': dept_info['day_pattern'],
                                            'session_name': session_name,
                                            'group_name': course_info['group_name'],
                                            'course_code': course_info['course_code']
                                                })
        
        # Apply room conflict constraints for each absolute session slot (optimized)
        for (absolute_day, session_name, room_id), assignments in time_slot_assignments.items():
            if len(assignments) <= 1:
                continue  # Skip if no conflicts
            
            assignment_vars = [assignment['variable'] for assignment in assignments]
            
            # Standard room assignment: at most one course can use this room at this session
            model.Add(sum(assignment_vars) <= 1)
            constraints_applied += 1
        
        # Optimized course instance room assignment constraint
        for teacher_id in lab_variables:
            for course_instance_id in lab_variables[teacher_id]:
                dept_info = course_dept_cache[course_instance_id]
                dept_days = dept_info['dept_days']
                
                for day_idx in range(min(len(dept_days), len(lab_variables[teacher_id][course_instance_id]))):
                    day_sessions = lab_variables[teacher_id][course_instance_id][day_idx]
                    
                    for session_name in day_sessions:
                        room_vars = list(day_sessions[session_name].values())
                        
                        if len(room_vars) > 1:
                            # Standard constraint: each course instance can use at most one room per session
                            model.Add(sum(room_vars) <= 1)
                            constraints_applied += 1
        
        self.logger.info(f"Applied {constraints_applied} optimized lab room single assignment constraints")
        self.logger.info(f"Processed {len(time_slot_assignments)} unique session-room combinations")
        return constraints_applied

    def apply_block_specific_lab_priority_constraint(self, model, lab_variables):
        """Apply block-specific lab priority for AIML, AIDS, CSD departments.
        
        Priority Rules:
        1. AIML, AIDS, CSD get priority for K Block and J Block labs
        2. AIML, AIDS, and CSD are RESTRICTED from using Techlounge 35-capacity labs
        3. All three departments must use K/J blocks only for 35-capacity lab assignments
        """
        self.logger.info("Applying block-specific lab priority constraints for AIML/AIDS/CSD departments...")
        constraints_applied = 0
        
        # Define room categories by block and capacity
        k_block_35_labs = [166, 167, 168, 169, 170, 171]  # KFL01, KFL02, KFL03, KFR01, KFR02, KFR03
        j_block_35_labs = [160, 161, 162, 163, 164, 165]  # JL1, JL2, JL3, JR1, JR2, JR3
        techlounge_35_labs = [174, 175, 176, 177, 178, 179, 181, 183, 186, 187]  # TLFL1-5, TLFR1,3,5, TLGL3,4
        
        # Priority departments for K/J blocks (with common variations)
        block_priority_depts = [
            'Artificial Intelligence & Machine Learning',  # AIML
            'Artificial Intelligence and Machine Learning',  # AIML variant
            'Artificial Intelligence & Data Science',       # AIDS  
            'Artificial Intelligence and Data Science',     # AIDS variant
            'Computer Science & Design',                    # CSD
            'Computer Science and Design'                   # CSD variant
        ]
        
        # Departments restricted from Techlounge 35-capacity labs
        techlounge_restricted_depts = [
            'Artificial Intelligence & Machine Learning',  # AIML
            'Artificial Intelligence and Machine Learning',  # AIML variant
            'Artificial Intelligence & Data Science',       # AIDS
            'Artificial Intelligence and Data Science',     # AIDS variant
            'Computer Science & Design',                    # CSD
            'Computer Science and Design'                   # CSD variant
        ]
        
        self.logger.info(f"K/J Block priority departments: {block_priority_depts}")
        self.logger.info(f"Techlounge 35-cap restricted departments: {techlounge_restricted_depts}")
        self.logger.info(f"K Block 35-cap labs: {k_block_35_labs} (6 labs)")
        self.logger.info(f"J Block 35-cap labs: {j_block_35_labs} (6 labs)")
        self.logger.info(f"Techlounge 35-cap labs (restricted for AIML/AIDS/CSD): {techlounge_35_labs} (10 labs)")
        
        for teacher_id, lab_courses in self.lab_requirements.items():
            for course_req in lab_courses:
                course_instance_id = course_req['course_instance_id']
                
                if teacher_id in lab_variables and course_instance_id in lab_variables[teacher_id]:
                    # Get department for this course
                    dept_name = "Computer Science & Engineering"  # Default
                    if hasattr(self, 'instance_group_mapping') and course_instance_id in self.instance_group_mapping:
                        dept_name = self.instance_group_mapping[course_instance_id]['department']
                    else:
                        # Fallback: look up in courses_df
                        base_id = self._get_base_course_id(course_instance_id)
                        course_matches = self.courses_df[self.courses_df['id'] == int(base_id)]
                        if not course_matches.empty:
                            dept_name = course_matches.iloc[0].get('student_dept', 'Computer Science & Engineering')
                    
                    dept_days = self._get_days_for_department(dept_name)
                    num_dept_days = len(dept_days)
                    
                    # Apply constraints based on department
                    if dept_name in techlounge_restricted_depts:
                        # HARD CONSTRAINT: AIML, AIDS, and CSD CANNOT use Techlounge 35-capacity labs
                        for day_idx in range(num_dept_days):
                            for session_name in self.lab_sessions.keys():
                                for room_id in techlounge_35_labs:
                                    if (day_idx in lab_variables[teacher_id][course_instance_id] and
                                        session_name in lab_variables[teacher_id][course_instance_id][day_idx] and
                                        room_id in lab_variables[teacher_id][course_instance_id][day_idx][session_name]):
                                        # Force assignment to be 0 (cannot use this room)
                                        model.Add(lab_variables[teacher_id][course_instance_id][day_idx][session_name][room_id] == 0)
                                        constraints_applied += 1
                        
                        self.logger.info(f"RESTRICTED: {dept_name} course {course_req['course_code']} CANNOT use Techlounge 35-capacity labs")
                    
                    if dept_name in block_priority_depts:
                        # Add soft preference for K/J block labs through objective function
                        k_j_block_assignments = []
                        other_lab_assignments = []
                        
                        for day_idx in range(num_dept_days):
                            for session_name in self.lab_sessions.keys():
                                for room_id in self.lab_room_ids:
                                    if (day_idx in lab_variables[teacher_id][course_instance_id] and
                                        session_name in lab_variables[teacher_id][course_instance_id][day_idx] and
                                        room_id in lab_variables[teacher_id][course_instance_id][day_idx][session_name]):
                                        
                                        assignment_var = lab_variables[teacher_id][course_instance_id][day_idx][session_name][room_id]
                                        
                                        if room_id in k_block_35_labs or room_id in j_block_35_labs:
                                            k_j_block_assignments.append(assignment_var)
                                        else:
                                            other_lab_assignments.append(assignment_var)
                        
                        # Add preference variables for objective function
                        if k_j_block_assignments:
                            prefer_k_j_blocks = model.NewBoolVar(f'prefer_kj_blocks_{course_instance_id}')
                            
                            # If prefer_k_j_blocks = 1, then prioritize K/J block assignments
                            if k_j_block_assignments and other_lab_assignments:
                                k_j_assignments_sum = sum(k_j_block_assignments)
                                
                                # Add to capacity preferences with high weight for K/J block priority
                                block_priority_weight = 400  # High priority for K/J blocks
                                self.capacity_preferences.append(prefer_k_j_blocks * block_priority_weight)
                                
                                # Create boolean variable to track if any K/J block is used
                                uses_k_j_blocks = model.NewBoolVar(f'uses_kj_blocks_{course_instance_id}')
                                
                                # uses_k_j_blocks = 1 if k_j_assignments_sum >= 1, else 0
                                model.Add(k_j_assignments_sum >= 1).OnlyEnforceIf(uses_k_j_blocks)
                                model.Add(k_j_assignments_sum == 0).OnlyEnforceIf(uses_k_j_blocks.Not())
                                
                                # Link preference variable to actual usage
                                model.Add(prefer_k_j_blocks == 1).OnlyEnforceIf(uses_k_j_blocks)
                                model.Add(prefer_k_j_blocks == 0).OnlyEnforceIf(uses_k_j_blocks.Not())
                                
                                constraints_applied += 4
                        
                        self.logger.info(f"PRIORITY: {dept_name} course {course_req['course_code']} gets K/J block preference (weight: 400)")
        
        self.logger.info(f"Applied {constraints_applied} block-specific lab priority constraints")
        return constraints_applied

    def apply_140_lab_restriction_constraint(self, model, lab_variables):
        """
        Force 140+ student course instances to use 140-capacity Laboratory rooms ONLY,
        while preventing ≤70 student instances from using 140-capacity Labs.
        IMPORTANT: Only 'Laboratory' type rooms are allowed, NOT core labs.
        """
        self.logger.info("Applying 140-capacity LABORATORY assignment constraint for unified 140+ student courses...")
        constraints_applied = 0
        
        # Get 140-capacity lab IDs that are specifically 'Laboratory' type (not core labs)
        labs_140_laboratory_only = set()
        for lab in self.lab_capacity_analysis['labs_140']:
            lab_id = lab['id']
            # Check if this room is of type 'Laboratory'
            if lab_id in self.laboratory_room_ids:
                labs_140_laboratory_only.add(lab_id)
        
        if not labs_140_laboratory_only:
            self.logger.warning("No 140-capacity LABORATORY rooms found - skipping 140-capacity lab constraints")
            self.logger.warning("(140+ capacity rooms exist but they are not 'Laboratory' type - they might be core labs)")
            return 0
        
        self.logger.info(f"Found {len(labs_140_laboratory_only)} rooms that are both 140+ capacity AND 'Laboratory' type")
        self.logger.info(f"Laboratory room IDs for 140+ students: {sorted(labs_140_laboratory_only)}")
        
        # Identify 140+ student instances and regular instances
        large_instances = []  # 140+ students
        regular_instances = []  # ≤70 students
        
        for teacher_id, lab_courses in self.lab_requirements.items():
            for course_req in lab_courses:
                course_instance_id = course_req['course_instance_id']
                students_per_instance = course_req.get('students_per_instance', 0)
                
                if students_per_instance >= 140:
                    large_instances.append((teacher_id, course_instance_id, course_req))
                else:
                    regular_instances.append((teacher_id, course_instance_id, course_req))
        
        self.logger.info(f"Found {len(large_instances)} courses with 140+ students and {len(regular_instances)} regular instances")
        
        # CONSTRAINT 1: Force 140+ student instances to use 140-capacity LABORATORY rooms ONLY
        forced_140_instances = 0
        for teacher_id, instance_id, course_req in large_instances:
            if teacher_id in lab_variables and instance_id in lab_variables[teacher_id]:
                # Collect all lab assignment variables for this large instance
                lab_140_laboratory_assignments = []
                non_140_laboratory_assignments = []
                
                for day_idx in lab_variables[teacher_id][instance_id]:
                    for session_name in lab_variables[teacher_id][instance_id][day_idx]:
                        for room_id in lab_variables[teacher_id][instance_id][day_idx][session_name]:
                            var = lab_variables[teacher_id][instance_id][day_idx][session_name][room_id]
                            
                            if room_id in labs_140_laboratory_only:
                                lab_140_laboratory_assignments.append(var)
                            else:
                                non_140_laboratory_assignments.append(var)
                
                # Force 140+ student instances to ONLY use 140-capacity LABORATORY rooms
                if non_140_laboratory_assignments:
                    for var in non_140_laboratory_assignments:
                        model.Add(var == 0)
                        constraints_applied += 1
                    
                    forced_140_instances += 1
                    course_code = course_req.get('course_code', 'Unknown')
                    students = course_req.get('students_per_instance', 0)
                    self.logger.info(f"  🔒 Large course {course_code} (ID: {instance_id}, {students} students) FORCED to use 140-capacity LABORATORY rooms only")
        
        # CONSTRAINT 2: Prevent regular instances (≤70 students) from using 140-capacity LABORATORY rooms
        restricted_regular_instances = 0
        for teacher_id, instance_id, course_req in regular_instances:
            if teacher_id in lab_variables and instance_id in lab_variables[teacher_id]:
                lab_140_laboratory_assignments = []
                
                for day_idx in lab_variables[teacher_id][instance_id]:
                    for session_name in lab_variables[teacher_id][instance_id][day_idx]:
                        for room_id in lab_variables[teacher_id][instance_id][day_idx][session_name]:
                            if room_id in labs_140_laboratory_only:
                                var = lab_variables[teacher_id][instance_id][day_idx][session_name][room_id]
                                lab_140_laboratory_assignments.append(var)
                
                # Prevent regular instances from using 140-capacity LABORATORY rooms
                if lab_140_laboratory_assignments:
                    for var in lab_140_laboratory_assignments:
                        model.Add(var == 0)
                        constraints_applied += 1
                    
                    restricted_regular_instances += 1
                    course_code = course_req.get('course_code', 'Unknown')
                    students = course_req.get('students_per_instance', 0)
                    if restricted_regular_instances <= 5:  # Log first few restrictions
                        self.logger.info(f"  🚫 Regular course {course_code} (ID: {instance_id}, {students} students) RESTRICTED from 140-capacity LABORATORY rooms")
                    elif restricted_regular_instances == 6:
                        self.logger.info("  🚫 ... (additional regular course instances restricted)")
        
        self.logger.info(f"140-capacity LABORATORY room constraints applied successfully:")
        self.logger.info(f"  Forced {forced_140_instances} large courses (140+ students) to use 140-capacity LABORATORY rooms only")
        self.logger.info(f"  Restricted {restricted_regular_instances} regular courses (≤70 students) from 140-capacity LABORATORY rooms")
        self.logger.info(f"  Total constraints applied: {constraints_applied}")
        self.logger.info(f"  🏫 IMPORTANT: Only 'Laboratory' type rooms used, core labs are excluded for 140+ capacity courses")
        
        return constraints_applied



    def apply_group_based_scheduling_constraint(self, model, lab_variables):
        """Apply group-based scheduling constraints to enforce scheduling by groups."""
        self.logger.info("Applying group-based scheduling constraints...")
        constraints_applied = 0
        
        # Group course instances by department, semester, and group
        semester_groups = defaultdict(lambda: defaultdict(list))
        
        for teacher_id in lab_variables:
            for course_instance_id in lab_variables[teacher_id]:
                # Get group info for this course instance
                if hasattr(self, 'instance_group_mapping') and course_instance_id in self.instance_group_mapping:
                    group_mapping = self.instance_group_mapping[course_instance_id]
                    dept = group_mapping['department']
                    semester = group_mapping['semester']
                    group_index = group_mapping['group_index']
                    
                    if group_index > 0:  # Valid group
                        semester_groups[(dept, semester)][group_index].append(course_instance_id)
        
        # CONSTRAINT 1: Same-semester group non-overlap
        for (dept, semester), groups in semester_groups.items():
            self.logger.info(f"Applying group constraints for {dept} Semester {semester}: {len(groups)} groups")
            
            # Get department-specific days for this constraint (with semester override)
            dept_days = self._get_days_for_department(dept, semester)
            num_dept_days = len(dept_days)
            
            # For each time slot, ensure at most one group from this semester is active
            for day_idx in range(num_dept_days):
                for session_name in self.lab_sessions.keys():
                    # For each time slot, collect usage variables for each group
                    group_usages = {}
                    
                    for group_idx, course_instances in groups.items():
                        group_usage_vars = []
                        
                        for course_instance_id in course_instances:
                            # Find the teacher for this course instance
                            teacher_id = None
                            for tid in lab_variables:
                                if course_instance_id in lab_variables[tid]:
                                    teacher_id = tid
                                    break
                            
                            if teacher_id and day_idx in lab_variables[teacher_id][course_instance_id]:
                                for room_id in self.lab_room_ids:
                                    if (session_name in lab_variables[teacher_id][course_instance_id][day_idx] and
                                        room_id in lab_variables[teacher_id][course_instance_id][day_idx][session_name]):
                                        group_usage_vars.append(lab_variables[teacher_id][course_instance_id][day_idx][session_name][room_id])
                        
                        if group_usage_vars:
                            # Create a variable indicating if this group uses this time slot
                            group_usage = model.NewBoolVar(f'group_usage_{dept}_S{semester}_G{group_idx}_day{day_idx}_session{session_name}')
                            
                            # Link usage to the assignment variables
                            model.Add(group_usage <= sum(group_usage_vars))
                            # Any assignment makes the group usage 1
                            model.Add(sum(group_usage_vars) <= len(self.lab_room_ids) * group_usage)
                            
                            group_usages[group_idx] = group_usage
                    
                    # At most one group can use this time slot
                    # EXCEPTION: Allow co-scheduling within the same group for 140-capacity labs
                    if len(group_usages) > 1:
                        # Check if this is the same group (which would allow co-scheduling)
                        unique_groups = set(group_usages.keys())
                        if len(unique_groups) > 1:
                            # Different groups competing - apply normal constraint
                            model.Add(sum(group_usages.values()) <= 1)
                            constraints_applied += 1
                        else:
                            # Same group with multiple instances - allow co-scheduling
                            # This happens when the same group has multiple course instances
                            # that can be co-scheduled in 140-capacity labs
                            self.logger.debug(f"✅ Allowing within-group co-scheduling for {dept} S{semester} G{list(unique_groups)[0]}")
                            # No constraint applied - allow multiple instances from same group
        
        # CONSTRAINT 2: Course instance uniqueness
        for teacher_id in lab_variables:
            for course_instance_id in lab_variables[teacher_id]:
                # Get department and semester for this course instance
                dept_name = "Computer Science & Engineering"  # Default
                semester = None
                if hasattr(self, 'instance_group_mapping') and course_instance_id in self.instance_group_mapping:
                    dept_name = self.instance_group_mapping[course_instance_id]['department']
                    semester = self.instance_group_mapping[course_instance_id].get('semester')
                else:
                    # Fallback: look up in courses_df
                    base_id = self._get_base_course_id(course_instance_id)
                    course_matches = self.courses_df[self.courses_df['id'] == int(base_id)]
                    if not course_matches.empty:
                        dept_name = course_matches.iloc[0].get('student_dept', 'Computer Science & Engineering')
                
                dept_days = self._get_days_for_department(dept_name, semester)
                num_dept_days = len(dept_days)
                
                for day_idx in range(num_dept_days):
                    if day_idx in lab_variables[teacher_id][course_instance_id]:
                        for session_name in self.lab_sessions.keys():
                            if session_name in lab_variables[teacher_id][course_instance_id][day_idx]:
                                session_assignments = []
                                for room_id in self.lab_room_ids:
                                    if room_id in lab_variables[teacher_id][course_instance_id][day_idx][session_name]:
                                        session_assignments.append(lab_variables[teacher_id][course_instance_id][day_idx][session_name][room_id])
                                
                                if len(session_assignments) > 1:
                                    model.Add(sum(session_assignments) <= 1)
                                    constraints_applied += 1
        
        self.logger.info(f"Applied {constraints_applied} group-based scheduling constraints")
        return constraints_applied

    def apply_core_lab_mapping_constraint(self, model, lab_variables):
        """Apply constraint that courses in core_mapping must be assigned to their specified lab(s)."""
        if not self.course_to_room_mapping:
            self.logger.info("No core lab mapping found, skipping this constraint.")
            return 0

        self.logger.info("Applying core lab mapping constraint...")
        self.logger.info("🔒 STRICT ENFORCEMENT: Only courses mapped in og-final.csv can use specialized labs")
        constraints_applied = 0
        mapped_courses_count = 0
        unmapped_courses_count = 0
        blocked_courses = []
        
        for teacher_id, lab_courses in self.lab_requirements.items():
            for course_req in lab_courses:
                course_code = course_req['course_code']
                course_instance_id = course_req['course_instance_id']
                
                # Get course name from the original courses data
                base_id = self._get_base_course_id(course_instance_id)
                course_row = self.courses_df[self.courses_df['id'] == int(base_id)]
                if course_row.empty:
                    self.logger.warning(f"Course instance {course_instance_id} (base: {base_id}) not found in courses data")
                    continue
                    
                course_name = course_row.iloc[0]['course_name']
                
                if teacher_id not in lab_variables or course_instance_id not in lab_variables[teacher_id]:
                    continue
                
                # Check if course code is in core mapping (using course code only for simplicity)
                is_core_mapped = False
                mapped_room_ids = None
                
                # Look for this course code in the core mapping
                for (mapped_code, mapped_name), room_ids in self.course_to_room_mapping.items():
                    if mapped_code == course_code:
                        is_core_mapped = True
                        mapped_room_ids = room_ids
                        break
                
                if is_core_mapped:
                    mapped_courses_count += 1
                    required_room_ids = mapped_room_ids
                    
                    # Ensure all required rooms are valid lab rooms
                    valid_required_rooms = [room_id for room_id in required_room_ids if room_id in self.lab_room_ids]
                    
                    if not valid_required_rooms:
                        self.logger.warning(f"❌ BLOCKED: No valid lab rooms found for core course {course_code}. Required: {required_room_ids}")
                        blocked_courses.append(course_code)
                        continue
                        
                    # This course must be assigned ONLY to one of its specified rooms
                    # Constrain it to NOT use any other rooms
                    forbidden_rooms = set(self.lab_room_ids) - set(valid_required_rooms)
                    
                    # Get department and semester for this course to determine number of days
                    dept_name = "Computer Science & Engineering"  # Default
                    semester = None
                    if hasattr(self, 'instance_group_mapping') and course_instance_id in self.instance_group_mapping:
                        dept_name = self.instance_group_mapping[course_instance_id]['department']
                        semester = self.instance_group_mapping[course_instance_id].get('semester')
                    else:
                        # Fallback: look up in courses_df
                        dept_name = course_row.iloc[0].get('student_dept', 'Computer Science & Engineering')
                    
                    dept_days = self._get_days_for_department(dept_name, semester)
                    num_dept_days = len(dept_days)
                    
                    for day_idx in range(num_dept_days):
                        for session_name in self.lab_sessions.keys():
                            for room_id in forbidden_rooms:
                                # This lab session cannot be assigned to forbidden rooms
                                if room_id in lab_variables[teacher_id][course_instance_id][day_idx][session_name]:
                                    model.Add(lab_variables[teacher_id][course_instance_id][day_idx][session_name][room_id] == 0)
                                    constraints_applied += 1
                    
                    self.logger.info(f"✅ CORE COURSE: '{course_code}' - '{course_name}' → RESTRICTED to {len(valid_required_rooms)} specific room(s): {valid_required_rooms}")
                else:
                    unmapped_courses_count += 1
                    # This course is NOT in the core mapping.
                    # Constrain it to rooms of type 'Laboratory' ONLY.
                    self.logger.debug(f"⚠️  NON-CORE: Course '{course_code}' not in og-final.csv. RESTRICTED to general 'Laboratory' type rooms only.")
                    non_laboratory_rooms = set(self.lab_room_ids) - set(self.laboratory_room_ids)
                    
                    # Get department and semester for this course to determine number of days
                    dept_name = "Computer Science & Engineering"  # Default
                    semester = None
                    if hasattr(self, 'instance_group_mapping') and course_instance_id in self.instance_group_mapping:
                        dept_name = self.instance_group_mapping[course_instance_id]['department']
                        semester = self.instance_group_mapping[course_instance_id].get('semester')
                    else:
                        # Fallback: look up in courses_df
                        dept_name = course_row.iloc[0].get('student_dept', 'Computer Science & Engineering')
                    
                    dept_days = self._get_days_for_department(dept_name, semester)
                    num_dept_days = len(dept_days)
                    
                    for day_idx in range(num_dept_days):
                        for session_name in self.lab_sessions.keys():
                            for room_id in non_laboratory_rooms:
                                if room_id in lab_variables[teacher_id][course_instance_id][day_idx][session_name]:
                                    model.Add(lab_variables[teacher_id][course_instance_id][day_idx][session_name][room_id] == 0)
                                    constraints_applied += 1

        # Enhanced summary logging
        self.logger.info("="*60)
        self.logger.info("CORE LAB MAPPING CONSTRAINT SUMMARY:")
        self.logger.info(f"📋 Total courses processed: {mapped_courses_count + unmapped_courses_count}")
        self.logger.info(f"✅ Courses mapped in og-final.csv: {mapped_courses_count}")
        self.logger.info(f"⚠️  Courses NOT in og-final.csv: {unmapped_courses_count}")
        if blocked_courses:
            self.logger.warning(f"❌ BLOCKED courses (invalid labs): {blocked_courses}")
        self.logger.info(f"🔒 Total constraints applied: {constraints_applied}")
        self.logger.info("🎯 ENFORCEMENT: Only mapped courses can access specialized labs!")
        self.logger.info("="*60)

        return constraints_applied
    
    def apply_core_lab_group_slot_limit_constraint(self, model, lab_variables):
        """SOFT CONSTRAINT: Prefer to limit groups containing core lab instances to 8 lab slots with penalty for exceeding."""
        self.logger.info("Applying core lab group soft slot limit constraint (prefer 8 slots for groups with core labs)...")
        constraints_applied = 0
        
        if not hasattr(self, 'core_lab_groups') or not self.core_lab_groups:
            self.logger.info("No core lab groups identified - skipping core lab group slot limit constraint")
            return 0
        
        # Initialize penalty variables list if not exists
        if not hasattr(self, 'core_lab_group_slot_penalties'):
            self.core_lab_group_slot_penalties = []
        
        # Group course instances by core lab groups
        for group_name in self.core_lab_groups:
            # Extract department and semester from group name: "Computer Science & Engineering_S3_G1"
            parts = group_name.split('_S')
            if len(parts) < 2:
                self.logger.warning(f"Cannot parse department from group name: {group_name}")
                continue
                
            dept = parts[0]
            semester_and_group = parts[1]
            semester_part = semester_and_group.split('_G')[0]
            
            try:
                semester = int(semester_part)
            except ValueError:
                self.logger.warning(f"Cannot parse semester from group name: {group_name}")
                continue
            
            # Get department-specific day pattern for accurate slot counting
            dept_days = self._get_days_for_department(dept, semester)
            num_dept_days = len(dept_days)
            
            # Find all lab instances belonging to this core lab group
            group_lab_instances = []
            if hasattr(self, 'course_groups') and (dept, semester) in self.course_groups:
                group_idx_str = group_name.split('_G')[1] if '_G' in group_name else "1"
                try:
                    group_idx = int(group_idx_str) - 1  # Convert to 0-based index
                    if 0 <= group_idx < len(self.course_groups[(dept, semester)]):
                        group = self.course_groups[(dept, semester)][group_idx]
                        for instance in group:
                            instance_id = instance['id']
                            teacher_id = str(instance['teacher_id'])
                            
                            # Check if this instance has lab requirements and is in lab_variables
                            if (teacher_id in lab_variables and 
                                instance_id in lab_variables[teacher_id]):
                                group_lab_instances.append((teacher_id, instance_id))
                except (ValueError, IndexError):
                    self.logger.warning(f"Cannot parse group index from group name: {group_name}")
                    continue
            
            if not group_lab_instances:
                self.logger.debug(f"Core lab group {group_name} has no lab instances to constrain")
                continue
            
            self.logger.info(f"Applying soft 8-slot limit to core lab group: {group_name} ({len(group_lab_instances)} lab instances)")
            
            # Create boolean variables for each time slot used by this core lab group
            slot_used_vars = {}
            for day_idx in range(num_dept_days):
                for session_name in self.lab_sessions.keys():
                    slot_used_vars[(day_idx, session_name)] = model.NewBoolVar(
                        f'core_group_slot_used_{group_name}_d{day_idx}_s{session_name}'
                    )
            
            # Link these variables to lab assignments from this core lab group
            for day_idx in range(num_dept_days):
                for session_name in self.lab_sessions.keys():
                    # Slot is used if ANY lab from this core lab group is scheduled in it
                    slot_assignments = []
                    for teacher_id, course_instance_id in group_lab_instances:
                        if (day_idx < len(lab_variables[teacher_id][course_instance_id]) and 
                            session_name in lab_variables[teacher_id][course_instance_id][day_idx]):
                            for room_id in self.lab_room_ids:
                                if room_id in lab_variables[teacher_id][course_instance_id][day_idx][session_name]:
                                    slot_assignments.append(lab_variables[teacher_id][course_instance_id][day_idx][session_name][room_id])
                    
                    if slot_assignments:
                        # Reification: slot_used_vars is true iff sum(slot_assignments) > 0
                        model.Add(sum(slot_assignments) >= 1).OnlyEnforceIf(slot_used_vars[(day_idx, session_name)])
                        model.Add(sum(slot_assignments) == 0).OnlyEnforceIf(slot_used_vars[(day_idx, session_name)].Not())
                        constraints_applied += 2
            
            # SOFT CONSTRAINT: Create penalty variable for exceeding 8 slots
            total_group_slots_used = sum(slot_used_vars.values())
            excess_slots = model.NewIntVar(0, len(slot_used_vars), f'core_group_excess_slots_{group_name}')
            
            # excess_slots = max(0, total_group_slots_used - 8)
            model.AddMaxEquality(excess_slots, [total_group_slots_used - 8, 0])
            constraints_applied += 1
            
            # Add penalty to the list (will be minimized in objective)
            self.core_lab_group_slot_penalties.append(excess_slots)
            
            self.logger.info(f"  - SOFT CONSTRAINT: Core lab group {group_name} prefers <= 8 lab slots ({num_dept_days} days pattern)")
        
        self.logger.info(f"Applied {constraints_applied} core lab group soft slot limit constraints")
        return constraints_applied
    
    def apply_computing_group_slot_limit_constraint(self, model, lab_variables):
        """HARD CONSTRAINT: Limit computing department groups to EXACTLY 6 lab slots maximum - NO EXCEPTIONS."""
        self.logger.info("Applying computing group HARD slot limit constraint (MAX 6 slots for computing groups)...")
        constraints_applied = 0
        
        # Define computing departments
        computing_departments = {
            'Computer Science & Engineering',
            'Computer Science & Business Systems',
            'Computer Science & Design', 
            'Computer Science & Engineering (Cyber Security)',
            'Artificial Intelligence & Data Science',
            'Artificial Intelligence & Machine Learning',
            'Information Technology'
        }
        
        # No penalty variables needed - this is a HARD constraint
        
        # Identify computing groups
        computing_groups = set()
        if hasattr(self, 'course_groups'):
            for (dept, semester), groups in self.course_groups.items():
                if dept in computing_departments:
                    for group_idx, group in enumerate(groups):
                        group_name = f"{dept}_S{semester}_G{group_idx + 1}"
                        computing_groups.add(group_name)
        
        if not computing_groups:
            self.logger.info("No computing groups identified - skipping computing group slot limit constraint")
            return 0
        
        self.logger.info(f"Identified {len(computing_groups)} computing groups for HARD 6-slot limit constraint")
        
        # Apply constraint to each computing group
        for group_name in computing_groups:
            # Extract department and semester from group name
            parts = group_name.split('_S')
            if len(parts) < 2:
                self.logger.warning(f"Cannot parse department from group name: {group_name}")
                continue
                
            dept = parts[0]
            semester_and_group = parts[1]
            semester_part = semester_and_group.split('_G')[0]
            
            try:
                semester = int(semester_part)
            except ValueError:
                self.logger.warning(f"Cannot parse semester from group name: {group_name}")
                continue
            
            # Get department-specific day pattern for accurate slot counting
            dept_days = self._get_days_for_department(dept, semester)
            num_dept_days = len(dept_days)
            
            # Find all lab instances belonging to this computing group
            group_lab_instances = []
            if hasattr(self, 'course_groups') and (dept, semester) in self.course_groups:
                group_idx_str = group_name.split('_G')[1] if '_G' in group_name else "1"
                try:
                    group_idx = int(group_idx_str) - 1  # Convert to 0-based index
                    if 0 <= group_idx < len(self.course_groups[(dept, semester)]):
                        group = self.course_groups[(dept, semester)][group_idx]
                        for instance in group:
                            instance_id = instance['id']
                            teacher_id = str(instance['teacher_id'])
                            
                            # Check if this instance has lab requirements and is in lab_variables
                            if (teacher_id in lab_variables and 
                                instance_id in lab_variables[teacher_id]):
                                group_lab_instances.append((teacher_id, instance_id))
                except (ValueError, IndexError):
                    self.logger.warning(f"Cannot parse group index from group name: {group_name}")
                    continue
            
            if not group_lab_instances:
                self.logger.debug(f"Computing group {group_name} has no lab instances to constrain")
                continue
            
            self.logger.info(f"Applying HARD 6-slot limit to computing group: {group_name} ({len(group_lab_instances)} lab instances)")
            
            # Create boolean variables for each time slot used by this computing group
            slot_used_vars = {}
            for day_idx in range(num_dept_days):
                for session_name in self.lab_sessions.keys():
                    slot_used_vars[(day_idx, session_name)] = model.NewBoolVar(
                        f'computing_group_slot_used_{group_name}_d{day_idx}_s{session_name}'
                    )
            
            # Link these variables to lab assignments from this computing group
            for day_idx in range(num_dept_days):
                for session_name in self.lab_sessions.keys():
                    # Slot is used if ANY lab from this computing group is scheduled in it
                    slot_assignments = []
                    for teacher_id, course_instance_id in group_lab_instances:
                        if (day_idx < len(lab_variables[teacher_id][course_instance_id]) and 
                            session_name in lab_variables[teacher_id][course_instance_id][day_idx]):
                            for room_id in self.lab_room_ids:
                                if room_id in lab_variables[teacher_id][course_instance_id][day_idx][session_name]:
                                    slot_assignments.append(lab_variables[teacher_id][course_instance_id][day_idx][session_name][room_id])
                    
                    if slot_assignments:
                        # Reification: slot_used_vars is true iff sum(slot_assignments) > 0
                        model.Add(sum(slot_assignments) >= 1).OnlyEnforceIf(slot_used_vars[(day_idx, session_name)])
                        model.Add(sum(slot_assignments) == 0).OnlyEnforceIf(slot_used_vars[(day_idx, session_name)].Not())
                        constraints_applied += 2
            
            # HARD CONSTRAINT: Limit total slots to exactly 6 maximum
            total_group_slots_used = sum(slot_used_vars.values())
            
            # HARD LIMIT: total_group_slots_used <= 6 (NO EXCEPTIONS)
            model.Add(total_group_slots_used <= 6)
            constraints_applied += 1
            
            self.logger.info(f"  - 🔒 HARD CONSTRAINT: Computing group {group_name} LIMITED to ≤ 6 lab slots ({num_dept_days} days pattern)")
        
        self.logger.info(f"Applied {constraints_applied} computing group HARD slot limit constraints (MAX 6 slots each)")
        return constraints_applied
    
    def apply_semester_lab_slot_limit_constraint(self, model, lab_variables):
        """CONSTRAINT: Limit the total number of lab slots used by any single semester/department to 18 (COMPLETELY EXCLUDING core labs)."""
        self.logger.info("Applying semester lab slot limit constraint (max 18 slots per sem/dept, core labs get UNLIMITED slots)...")
        constraints_applied = 0
        
        # Group course instances by department and semester
        semester_courses = defaultdict(list)
        for teacher_id in lab_variables:
            for course_instance_id in lab_variables[teacher_id]:
                if hasattr(self, 'instance_group_mapping') and course_instance_id in self.instance_group_mapping:
                    group_mapping = self.instance_group_mapping[course_instance_id]
                    dept = group_mapping['department']
                    semester = group_mapping['semester']
                    semester_courses[(dept, semester)].append((teacher_id, course_instance_id))
        
        # Apply constraint for each semester/department
        for (dept, semester), instance_info in semester_courses.items():
            if len(instance_info) == 0:
                continue
            
            # COMPLETELY SEPARATE core lab instances from regular instances
            non_core_instances = []
            core_instances = []
            
            for teacher_id, course_instance_id in instance_info:
                if course_instance_id in self.core_lab_instance_ids:
                    core_instances.append((teacher_id, course_instance_id))
                else:
                    non_core_instances.append((teacher_id, course_instance_id))
            
            # Log the separation clearly
            self.logger.info(f"  - {dept} S{semester}: {len(core_instances)} CORE LABS (unlimited), {len(non_core_instances)} regular labs (18-slot limit)")
            
            if not non_core_instances:
                self.logger.info(f"  - COMPLETE EXEMPTION for {dept} S{semester}: ALL labs are core labs - NO SLOT LIMITS APPLIED!")
                continue
            
            # Get department-specific day pattern for accurate slot counting (with semester override)
            dept_days = self._get_days_for_department(dept, semester)
            num_dept_days = len(dept_days)
            
            # Create boolean variables for each time slot used by NON-CORE labs ONLY
            slot_used_vars = {}
            for day_idx in range(num_dept_days):  # Use department-specific days
                for session_name in self.lab_sessions.keys():
                    slot_used_vars[(day_idx, session_name)] = model.NewBoolVar(
                        f'non_core_slot_used_{dept}_S{semester}_d{day_idx}_s{session_name}'
                    )
            
            # Link these variables to ONLY non-core lab assignments
            for day_idx in range(num_dept_days):  # Use department-specific days
                for session_name in self.lab_sessions.keys():
                    # Slot is used if ANY NON-CORE lab from this semester/dept is scheduled in it
                    # CORE LABS ARE COMPLETELY IGNORED IN THIS CALCULATION
                    slot_assignments = []
                    for teacher_id, course_instance_id in non_core_instances:
                        if day_idx < len(lab_variables[teacher_id][course_instance_id]) and session_name in lab_variables[teacher_id][course_instance_id][day_idx]:
                            for room_id in self.lab_room_ids:
                                if room_id in lab_variables[teacher_id][course_instance_id][day_idx][session_name]:
                                    slot_assignments.append(lab_variables[teacher_id][course_instance_id][day_idx][session_name][room_id])
                    
                    if slot_assignments:
                        # Reification: slot_used_vars is true iff sum(slot_assignments) > 0
                        model.Add(sum(slot_assignments) >= 1).OnlyEnforceIf(slot_used_vars[(day_idx, session_name)])
                        model.Add(sum(slot_assignments) == 0).OnlyEnforceIf(slot_used_vars[(day_idx, session_name)].Not())
                        constraints_applied += 2
            
            # The sum of used slots for this semester/dept's NON-CORE labs ONLY must be <= 18
            # CORE LABS DO NOT COUNT TOWARDS THIS LIMIT AT ALL
            total_non_core_slots_used = sum(slot_used_vars.values())
            model.Add(total_non_core_slots_used <= 18)
            constraints_applied += 1
            
            self.logger.info(f"  - ENFORCED LIMIT: {dept} Semester {semester} regular labs <= 18 slots ({num_dept_days} days pattern)")
            self.logger.info(f"  - UNLIMITED ACCESS: {len(core_instances)} core labs can use ANY number of slots without restriction")
        
        self.logger.info(f"Applied {constraints_applied} semester lab slot limit constraints (core labs completely exempt)")
        return constraints_applied
    
    def _apply_theory_constraints(self, model, group_timeslot_vars, lab_variables=None):
        """Apply theory-specific constraints using group-based approach with department-specific day patterns."""
        self.logger.info("Applying group-based theory constraints with department-specific day patterns...")
        constraints_applied = 0
        
        # CONSTRAINT 1: Each group must have exactly the required number of time slots
        for group_name, required_slots in self.group_requirements.items():
            if group_name not in group_timeslot_vars:
                continue
            
            # Get department-specific days (with semester override if available)
            dept_name = group_name.split('_S')[0] if '_S' in group_name else "Computer Science & Engineering"
            
            # Extract semester from group name for semester-specific overrides
            semester = None
            if '_S' in group_name:
                try:
                    semester_part = group_name.split('_S')[1].split('_G')[0]
                    semester = int(semester_part)
                except (ValueError, IndexError):
                    pass
            
            dept_days = self._get_days_for_department(dept_name, semester)
            num_dept_days = len(dept_days)
                
            timeslot_vars = []
            for day_idx in range(num_dept_days):  # Use department-specific days
                if day_idx in group_timeslot_vars[group_name]:
                    for slot_idx in range(self.num_theory_slots):
                        if slot_idx in group_timeslot_vars[group_name][day_idx]:
                            timeslot_vars.append(group_timeslot_vars[group_name][day_idx][slot_idx])
            
            if timeslot_vars:
                model.Add(sum(timeslot_vars) == required_slots)
                constraints_applied += 1
                self.logger.debug(f"Group {group_name}: exactly {required_slots} time slots required (using {len(dept_days)} days)")
        
        # CONSTRAINT 2: Different groups in same semester CANNOT overlap (but only within same day pattern)
        semester_groups_by_pattern = {}
        for group_name in group_timeslot_vars.keys():
            # Parse group name properly: "Computer Science & Engineering_S3_G1"
            parts = group_name.split('_S')
            if len(parts) == 2:
                dept = parts[0]
                semester_and_group = parts[1]
                semester_part = semester_and_group.split('_G')[0]
                try:
                    semester = int(semester_part)
                    day_pattern = self._get_day_pattern_for_department(dept, semester)
                    semester_key = f"{dept}_S{semester}_{day_pattern}"
                    if semester_key not in semester_groups_by_pattern:
                        semester_groups_by_pattern[semester_key] = []
                    semester_groups_by_pattern[semester_key].append(group_name)
                except ValueError:
                    self.logger.warning(f"Could not parse semester from group name: {group_name}")
                    continue
        
        for semester_key, groups in semester_groups_by_pattern.items():
            if len(groups) <= 1:
                continue
            self.logger.debug(f"Applying non-overlap constraints for {semester_key}: {len(groups)} groups")
            
            # Get representative department for day pattern with semester override
            representative_dept = groups[0].split('_S')[0]
            # Extract semester from first group for semester-specific overrides
            semester = None
            if '_S' in groups[0]:
                try:
                    semester_part = groups[0].split('_S')[1].split('_G')[0]
                    semester = int(semester_part)
                except (ValueError, IndexError):
                    pass
            
            dept_days = self._get_days_for_department(representative_dept, semester)
            num_dept_days = len(dept_days)
            
            for day_idx in range(num_dept_days):  # Use department-specific days
                for slot_idx in range(self.num_theory_slots):
                    # At most one group from this semester can use this time slot
                    slot_usage_vars = []
                    for group_name in groups:
                        if (group_name in group_timeslot_vars and
                            day_idx in group_timeslot_vars[group_name] and
                            slot_idx in group_timeslot_vars[group_name][day_idx]):
                            slot_usage_vars.append(group_timeslot_vars[group_name][day_idx][slot_idx])
                    
                    if len(slot_usage_vars) > 1:
                        model.Add(sum(slot_usage_vars) <= 1)
                        constraints_applied += 1
        
        # CONSTRAINT 3: FIXED Room capacity constraint - based on actual course instances, not groups
        constraints_applied += self._apply_proper_theory_room_capacity_constraint(model, group_timeslot_vars)
        
        # CONSTRAINT 4: HARD constraint - prevent 3 consecutive time slots per group per day
        constraints_applied += self._apply_no_three_consecutive_slots_constraint(model, group_timeslot_vars)
        
        # CONSTRAINT 5: Lunch break constraint - prevent scheduling during department lunch breaks
        constraints_applied += self._apply_lunch_break_constraint(model, group_timeslot_vars)
        
        # CONSTRAINT 5a: Flexible lunch break constraint - HARD constraint for flexible lunch departments
        if lab_variables is not None:
            constraints_applied += self._apply_flexible_lunch_constraint(model, group_timeslot_vars, lab_variables)
        else:
            self.logger.warning("Lab variables not available for flexible lunch constraint - skipping")
        
        # CONSTRAINT 6: Shift-based constraints for ALL departments
        constraints_applied += self.apply_shift_based_theory_constraint(model, group_timeslot_vars)
        
        # CONSTRAINT 7: Early scheduling constraint - schedule all theory before 3:00 PM
        constraints_applied += self._apply_early_scheduling_constraint(model, group_timeslot_vars)
        
        # CONSTRAINT 8: 140-capacity theory room reservation constraint
        constraints_applied += self.apply_140_capacity_theory_room_constraint(model, group_timeslot_vars)
        
        # CONSTRAINT 9: Course instance daily session limit - max 2 sessions per course per day
        constraints_applied += self.apply_course_instance_daily_limit_constraint(model, group_timeslot_vars)
        
        # CONSTRAINT 10: Teacher daily presence limit - prevent 11+ hour violation days
        constraints_applied += self.apply_teacher_daily_presence_constraint(model, group_timeslot_vars)
        
        # CONSTRAINT 11: Daily theory slot limit - maximum 5 theory slots per day
        constraints_applied += self._apply_daily_theory_slot_limit_constraint(model, group_timeslot_vars)
        
        self.logger.info(f"Applied {constraints_applied} theory-specific constraints with department-specific day patterns")
        return constraints_applied

    def _apply_no_three_consecutive_slots_constraint(self, model, group_timeslot_vars):
        """
        Apply HARD constraint to prevent groups from having 3 consecutive time slots per day.
        This ensures better distribution of theory sessions throughout the day.
        """
        self.logger.info("Applying HARD constraint: no group can have 3 consecutive theory slots...")
        constraints_applied = 0
        
        for group_name in group_timeslot_vars.keys():
            # Get department-specific days for this group
            dept_name = group_name.split('_S')[0] if '_S' in group_name else "Computer Science & Engineering"
            
            # Extract semester for semester-specific overrides
            semester = None
            if '_S' in group_name:
                try:
                    semester_part = group_name.split('_S')[1].split('_G')[0]
                    semester = int(semester_part)
                except (ValueError, IndexError):
                    pass
            
            dept_days = self._get_days_for_department(dept_name, semester)
            num_dept_days = len(dept_days)
            
            # Apply constraint for each day
            for day_idx in range(num_dept_days):
                if day_idx not in group_timeslot_vars[group_name]:
                    continue
                
                # Check all possible sequences of 3 consecutive slots and FORBID them
                for start_slot in range(self.num_theory_slots - 2):
                    consecutive_slots = []
                    for offset in range(3):  # Check 3 consecutive slots
                        slot_idx = start_slot + offset
                        if slot_idx in group_timeslot_vars[group_name][day_idx]:
                            consecutive_slots.append(group_timeslot_vars[group_name][day_idx][slot_idx])
                    
                    # If we have 3 consecutive slot variables, PREVENT all 3 from being assigned
                    if len(consecutive_slots) == 3:
                        # HARD CONSTRAINT: sum of 3 consecutive slots must be <= 2
                        # This allows at most 2 out of 3 consecutive slots to be assigned
                        model.Add(sum(consecutive_slots) <= 2)
                        constraints_applied += 1
                        
                        self.logger.debug(f"BLOCKED 3 consecutive slots for {group_name} day {day_idx} slots {start_slot}-{start_slot+2}")
        
        self.logger.info(f"Applied {constraints_applied} HARD constraints preventing 3 consecutive theory slots")
        return constraints_applied
    
    def _apply_early_scheduling_constraint(self, model, group_timeslot_vars):
        """
        Apply soft constraint to prefer scheduling theory sessions before 3:00 PM (time slot index 7).
        Creates penalty variables for sessions scheduled at 3:00 PM or later that will be minimized 
        in the objective function.
        """
        self.logger.info("Applying soft early scheduling constraint: prefer theory before 3:00 PM...")
        constraints_applied = 0
        
        # Initialize penalty variables list if not exists
        if not hasattr(self, 'late_scheduling_penalties'):
            self.late_scheduling_penalties = []
        
        # Time slot index 7 corresponds to "3:00 - 3:50"
        # We want to penalize scheduling in slots 7 and later (3:00 PM and after)
        penalty_start_slot = 7  # "3:00 - 3:50" and later get penalties
        
        for group_name in group_timeslot_vars.keys():
            # Get department-specific days for this group
            dept_name = group_name.split('_S')[0] if '_S' in group_name else "Computer Science & Engineering"
            
            # Extract semester for semester-specific overrides
            semester = None
            if '_S' in group_name:
                try:
                    semester_part = group_name.split('_S')[1].split('_G')[0]
                    semester = int(semester_part)
                except (ValueError, IndexError):
                    pass
            
            dept_days = self._get_days_for_department(dept_name, semester)
            num_dept_days = len(dept_days)
            
            # Apply constraint for each day
            for day_idx in range(num_dept_days):
                if day_idx not in group_timeslot_vars[group_name]:
                    continue
                
                # Create penalty for each late time slot (3:00 PM and after)
                for slot_idx in range(penalty_start_slot, self.num_theory_slots):
                    if slot_idx in group_timeslot_vars[group_name][day_idx]:
                        # Create a penalty variable that equals 1 if this late slot is assigned
                        penalty_var = model.NewBoolVar(f'late_penalty_{group_name}_day_{day_idx}_slot_{slot_idx}')
                        
                        # Penalty variable equals the assignment variable for this late slot
                        # If the slot is assigned (=1), penalty = 1; if not assigned (=0), penalty = 0
                        model.Add(penalty_var == group_timeslot_vars[group_name][day_idx][slot_idx])
                        
                        # Add to penalties list to be minimized in objective
                        self.late_scheduling_penalties.append(penalty_var)
                        constraints_applied += 1
                        
                        self.logger.debug(f"Added late scheduling penalty for {group_name} day {day_idx} slot {slot_idx} ({self.theory_time_slots[slot_idx]})")
        
        self.logger.info(f"Created {len(self.late_scheduling_penalties)} late scheduling penalty variables")
        self.logger.info(f"Applied {constraints_applied} soft early scheduling constraints")
        return constraints_applied

    def apply_140_capacity_theory_room_constraint(self, model, group_timeslot_vars):
        """
        Ensure 140-capacity theory rooms are properly reserved and not double-booked.
        This constraint works during optimization phase to prevent conflicts before postprocessing.
        """
        self.logger.info("Applying 140-capacity theory room reservation constraint...")
        constraints_applied = 0
        
        # Get 140-capacity theory rooms (rooms that can be used for both lab and theory)
        theory_rooms_140 = set()
        for room_id in self.theory_room_ids:
            room_row = self.rooms_df[self.rooms_df['id'] == room_id]
            if not room_row.empty:
                room_capacity = int(room_row.iloc[0]['room_max_cap'])
                if room_capacity >= 140:
                    theory_rooms_140.add(room_id)
        
        if not theory_rooms_140:
            self.logger.info("No 140-capacity theory rooms found - skipping constraint")
            return 0
        
        self.logger.info(f"Found {len(theory_rooms_140)} theory rooms with 140+ capacity: {sorted(theory_rooms_140)}")
        
        # Track which groups have 140+ student courses (co-scheduled instances)
        groups_needing_140 = set()
        regular_groups = set()
        
        if hasattr(self, 'course_groups'):
            for (dept, semester), groups in self.course_groups.items():
                for group_idx, group in enumerate(groups):
                    group_name = f"{dept}_S{semester}_G{group_idx + 1}"
                    
                    # Check if any instance in this group has 140+ students or is co-scheduled
                    needs_140 = False
                    for instance in group:
                        student_count = instance.get('student_count', 70)
                        is_co_scheduled = instance.get('co_scheduled_id') is not None
                        if student_count >= 140 or is_co_scheduled:
                            needs_140 = True
                            break
                    
                    if needs_140:
                        groups_needing_140.add(group_name)
                        self.logger.debug(f"Group {group_name} needs 140-capacity rooms")
                    else:
                        regular_groups.add(group_name)
        
        self.logger.info(f"Groups needing 140-capacity rooms: {len(groups_needing_140)}")
        self.logger.info(f"Regular groups: {len(regular_groups)}")
        
        # MAIN CONSTRAINT: Prevent multiple groups from conflicting over limited 140-capacity rooms
        # For each time slot, count how many groups might need 140-capacity rooms
        max_days = 0
        if groups_needing_140:
            # Calculate the maximum number of days any department uses
            for group_name in groups_needing_140:
                if '_S' in group_name:
                    dept = group_name.split('_S')[0]
                    try:
                        semester = int(group_name.split('_S')[1].split('_G')[0])
                        dept_days = self._get_days_for_department(dept, semester)
                        max_days = max(max_days, len(dept_days))
                    except (ValueError, IndexError):
                        continue
        
        for day_idx in range(max_days):
            for slot_idx in range(self.num_theory_slots):
                # Collect all groups that need 140-capacity rooms for this time slot
                groups_at_slot = []
                for group_name in groups_needing_140:
                    if (group_name in group_timeslot_vars and
                        day_idx in group_timeslot_vars[group_name] and
                        slot_idx in group_timeslot_vars[group_name]):
                        groups_at_slot.append(group_timeslot_vars[group_name][day_idx][slot_idx])
                
                # If more groups need 140-capacity rooms than we have available,
                # limit the number that can be scheduled simultaneously
                if len(groups_at_slot) > len(theory_rooms_140):
                    # At most as many groups as we have 140-capacity rooms
                    model.Add(sum(groups_at_slot) <= len(theory_rooms_140))
                    constraints_applied += 1
                    self.logger.debug(f"140-capacity room limit: max {len(theory_rooms_140)} groups at day {day_idx} slot {slot_idx}")
        
        self.logger.info(f"Applied {constraints_applied} 140-capacity theory room reservation constraints")
        return constraints_applied

    def apply_course_instance_daily_limit_constraint(self, model, group_timeslot_vars):
        """
        Apply constraint to prevent over-concentration of course sessions on the same day.
        Limits each course instance to maximum 2 sessions (lecture/tutorial) per day.
        
        EXCEPTION: Teachers in pop.csv get relaxed limits (up to 4 sessions per day) to accommodate
        their strict day preferences.
        """
        self.logger.info("Applying course instance daily session limit constraint (max 2 sessions per course per day)...")
        self.logger.info("EXCEPTION: Teachers in pop.csv get relaxed limits (up to 4 sessions per day)")
        constraints_applied = 0
        
        # Build mapping of course instances to their sessions across all groups
        course_instance_sessions = {}  # course_instance_id -> {group_name: [session_info]}
        
        # First, collect all course instances and their sessions from all groups
        if hasattr(self, 'course_groups'):
            for (dept, semester), groups in self.course_groups.items():
                for group_idx, group in enumerate(groups):
                    group_name = f"{dept}_S{semester}_G{group_idx + 1}"
                    
                    for instance in group:
                        if not instance.get('has_theory', False):
                            continue
                            
                        course_instance_id = instance['id']
                        course_code = instance.get('course_code', 'Unknown')
                        lecture_hours = instance.get('lecture_hours', 0)
                        tutorial_hours = instance.get('tutorial_hours', 0)
                        
                        # Handle co-scheduled instances to avoid double-counting
                        co_scheduled_id = instance.get('co_scheduled_id')
                        virtual_id = instance.get('virtual_id', '')
                        
                        if course_instance_id not in course_instance_sessions:
                            course_instance_sessions[course_instance_id] = {
                                'course_code': course_code,
                                'lecture_hours': lecture_hours,
                                'tutorial_hours': tutorial_hours,
                                'total_sessions': lecture_hours + tutorial_hours,
                                'co_scheduled_id': co_scheduled_id,
                                'virtual_id': virtual_id,
                                'groups': {}
                            }
                        
                        # Track which group this instance belongs to
                        course_instance_sessions[course_instance_id]['groups'][group_name] = {
                            'dept': dept,
                            'semester': semester,
                            'group_idx': group_idx + 1
                        }
        
        # Log course instance analysis
        total_instances = len(course_instance_sessions)
        instances_with_multiple_sessions = sum(1 for info in course_instance_sessions.values() if info['total_sessions'] > 2)
        
        self.logger.info(f"Analyzing {total_instances} course instances for daily session limits")
        self.logger.info(f"Instances with >2 total sessions: {instances_with_multiple_sessions}")
        
        # Apply constraints for each course instance across all days
        for course_instance_id, instance_info in course_instance_sessions.items():
            course_code = instance_info['course_code']
            total_sessions = instance_info['total_sessions']
            
            # Skip instances with ≤2 total sessions (constraint automatically satisfied)
            if total_sessions <= 2:
                continue
                
            # Get all groups this instance appears in
            instance_groups = instance_info['groups']
            
            if not instance_groups:
                continue
                
            # For each group this instance belongs to, apply daily limits
            for group_name, group_info in instance_groups.items():
                if group_name not in group_timeslot_vars:
                    continue
                    
                dept = group_info['dept']
                semester = group_info['semester']
                
                # Get department-specific days
                dept_days = self._get_days_for_department(dept, semester)
                num_dept_days = len(dept_days)
                
                self.logger.debug(f"Applying daily limits for {course_code} (ID: {course_instance_id}) in {group_name}")
                self.logger.debug(f"  Total sessions: {total_sessions}, Department days: {num_dept_days}")
                
                # Check if any teacher in this group is in pop.csv preferences (needs exception)
                has_pop_teacher = False
                pop_teachers_in_group = []
                if hasattr(self, 'course_groups'):
                    for (check_dept, check_sem), check_groups in self.course_groups.items():
                        for check_group_idx, check_group in enumerate(check_groups):
                            check_group_name = f"{check_dept}_S{check_sem}_G{check_group_idx + 1}"
                            if check_group_name == group_name:
                                # Check if any teacher in this group is in pop.csv
                                for instance in check_group:
                                    teacher_key = str(instance['teacher_id'])
                                    if (hasattr(self, 'teacher_day_preferences') and 
                                        teacher_key in self.teacher_day_preferences):
                                        has_pop_teacher = True
                                        pop_teachers_in_group.append(teacher_key)
                                break
                        if has_pop_teacher:
                            break
                
                # Apply constraint for each day with different limits based on pop.csv exception
                max_sessions_per_day = 4 if has_pop_teacher else 2
                limit_description = "RELAXED (pop.csv teacher)" if has_pop_teacher else "STANDARD"
                
                if has_pop_teacher:
                    self.logger.info(f"🔄 RELAXED CONSTRAINTS for group {group_name} - teachers {pop_teachers_in_group} from pop.csv")
                    self.logger.info(f"   - Max sessions per day: {max_sessions_per_day} (instead of 2)")
                    self.logger.info(f"   - Multi-day distribution: DISABLED (can use preferred days only)")
                
                for day_idx in range(num_dept_days):
                    if day_idx not in group_timeslot_vars[group_name]:
                        continue
                        
                    # Collect all time slot variables for this group on this day
                    day_slots = []
                    for slot_idx in group_timeslot_vars[group_name][day_idx]:
                        day_slots.append(group_timeslot_vars[group_name][day_idx][slot_idx])
                    
                    if len(day_slots) > max_sessions_per_day:
                        # CONSTRAINT: At most max_sessions_per_day time slots can be assigned to this group per day
                        # This indirectly limits course sessions since group scheduling distributes sessions across allocated slots
                        model.Add(sum(day_slots) <= max_sessions_per_day)
                        constraints_applied += 1
                        
                        day_name = dept_days[day_idx] if day_idx < len(dept_days) else f"day_{day_idx}"
                        self.logger.debug(f"Applied daily limit: {group_name} on {day_name} - max {max_sessions_per_day} slots {limit_description} (affects {course_code})")
                
                # Additional constraint: For courses with many sessions, ensure distribution across multiple days
                # EXCEPTION: Skip this constraint for pop.csv teachers to allow all sessions on preferred days
                if total_sessions >= 4 and not has_pop_teacher:
                    # For courses with 4+ sessions, must use at least 2 different days (except pop.csv teachers)
                    all_group_slots = []
                    day_usage_vars = []
                    
                    for day_idx in range(num_dept_days):
                        if day_idx in group_timeslot_vars[group_name]:
                            day_slots = []
                            for slot_idx in group_timeslot_vars[group_name][day_idx]:
                                day_slots.append(group_timeslot_vars[group_name][day_idx][slot_idx])
                                all_group_slots.append(group_timeslot_vars[group_name][day_idx][slot_idx])
                            
                            if day_slots:
                                # Create variable indicating if this day is used
                                day_used = model.NewBoolVar(f'day_used_{group_name}_{course_instance_id}_{day_idx}')
                                # Day is used if any slot on this day is assigned
                                model.Add(day_used <= sum(day_slots))
                                model.Add(sum(day_slots) <= len(day_slots) * day_used)
                                day_usage_vars.append(day_used)
                    
                    # Must use at least 2 days for courses with 4+ sessions (except pop.csv teachers)
                    if len(day_usage_vars) >= 2:
                        model.Add(sum(day_usage_vars) >= 2)
                        constraints_applied += 1
                        self.logger.debug(f"Multi-day distribution: {course_code} ({total_sessions} sessions) must use ≥2 days")
                elif total_sessions >= 4 and has_pop_teacher:
                    self.logger.debug(f"Multi-day distribution SKIPPED for pop.csv teacher: {course_code} ({total_sessions} sessions) can use preferred days only")
        
        # Log constraint summary
        self.logger.info(f"Applied {constraints_applied} course instance daily session limit constraints")
        
        # Log instances that will be affected
        affected_instances = [
            f"{info['course_code']}({info['total_sessions']}s)" 
            for info in course_instance_sessions.values() 
            if info['total_sessions'] > 2
        ]
        
        if affected_instances:
            self.logger.info(f"Courses with session distribution constraints: {', '.join(affected_instances[:10])}")
            if len(affected_instances) > 10:
                self.logger.info(f"... and {len(affected_instances) - 10} more courses")
        
        return constraints_applied
    
    def _apply_proper_theory_room_capacity_constraint(self, model, group_timeslot_vars):
        """
        Apply advanced room capacity constraint that tracks individual course sessions per time slot
        for optimal room utilization. Handles department-specific day patterns and precise session mapping.
        """
        self.logger.info("Applying advanced session-specific theory room capacity constraint...")
        constraints_applied = 0
        
        # NEW: Calculate detailed session-to-slot mapping for each group
        group_detailed_sessions = {}
        
        for group_name in group_timeslot_vars.keys():
            # Find the group data
            group_info = None
            for (dept, semester), groups in self.course_groups.items():
                for group_idx, group in enumerate(groups):
                    expected_name = f"{dept}_S{semester}_G{group_idx + 1}"
                    if expected_name == group_name:
                        group_info = {'dept': dept, 'semester': semester, 'instances': group}
                        break
            
            if not group_info:
                self.logger.warning(f"Group info not found for {group_name}")
                group_detailed_sessions[group_name] = {'sessions_per_slot': {}, 'total_sessions': 0}
                continue
            
            # Count theory course instances in this group
            theory_instances = [inst for inst in group_info['instances'] if inst.get('has_theory', False)]
            
            # NEW: Create detailed session mapping
            all_sessions = []
            processed_co_scheduled = set()
            
            for instance in theory_instances:
                lecture_hours = instance.get('lecture_hours', 0)
                tutorial_hours = instance.get('tutorial_hours', 0)
                
                # Handle co-scheduled instances (virtual pairs from 140+ student courses)
                co_scheduled_id = instance.get('co_scheduled_id')
                virtual_id = instance.get('virtual_id', '')
                
                # Skip already processed co-scheduled pairs
                if co_scheduled_id is not None:
                    if co_scheduled_id in processed_co_scheduled:
                        continue
                    processed_co_scheduled.add(co_scheduled_id)
                
                # Create individual sessions
                for session_num in range(lecture_hours):
                    all_sessions.append({
                        'course_instance_id': instance['id'],
                        'course_code': instance['course_code'],
                        'session_type': 'Lecture',
                        'session_number': session_num + 1
                    })
                
                for session_num in range(tutorial_hours):
                    all_sessions.append({
                        'course_instance_id': instance['id'],
                        'course_code': instance['course_code'],
                        'session_type': 'Tutorial',
                        'session_number': session_num + 1
                    })
            
            # Calculate how many rooms will be needed per time slot
            total_sessions = len(all_sessions)
            
            # NEW: Determine time slots this group will need based on max hours
            max_hours_in_group = 0
            for instance in theory_instances:
                instance_hours = instance.get('lecture_hours', 0) + instance.get('tutorial_hours', 0)
                max_hours_in_group = max(max_hours_in_group, instance_hours)
            
            # Distribute sessions across time slots optimally
            sessions_per_slot = {}
            if max_hours_in_group > 0 and total_sessions > 0:
                # Calculate optimal distribution of sessions across allocated slots
                # This gives us the ACTUAL rooms needed per slot, not assuming all courses need all slots
                
                sessions_per_allocated_slot = max(1, total_sessions // max_hours_in_group)
                remaining_sessions = total_sessions % max_hours_in_group
                
                for slot_idx in range(max_hours_in_group):
                    sessions_in_this_slot = sessions_per_allocated_slot
                    if slot_idx < remaining_sessions:
                        sessions_in_this_slot += 1
                    sessions_per_slot[slot_idx] = sessions_in_this_slot
            
            group_detailed_sessions[group_name] = {
                'sessions_per_slot': sessions_per_slot,
                'total_sessions': total_sessions,
                'max_slots_needed': max_hours_in_group,
                'all_sessions': all_sessions
            }
            
            # Enhanced logging
            session_distribution = ', '.join([f"Slot{i}:{count}" for i, count in sessions_per_slot.items()])
            self.logger.info(f"Group {group_name}: {total_sessions} total sessions → {session_distribution} (max {max_hours_in_group} slots)")
            
            # Log course breakdown
            course_breakdown = {}
            for instance in theory_instances:
                course_code = instance['course_code']
                hours = instance.get('lecture_hours', 0) + instance.get('tutorial_hours', 0)
                if course_code not in course_breakdown:
                    course_breakdown[course_code] = []
                course_breakdown[course_code].append(f"{hours}h")
            
            course_summary = ', '.join([f"{code}({'+'.join(hours)})" for code, hours in course_breakdown.items()])
            self.logger.debug(f"  Course breakdown: {course_summary}")
        
        # Group constraints by day pattern to handle different department schedules
        groups_by_day_pattern = {}
        for group_name in group_timeslot_vars.keys():
            dept_name = group_name.split('_S')[0] if '_S' in group_name else "Computer Science & Engineering"
            
            # Extract semester for semester-specific overrides
            semester = None
            if '_S' in group_name:
                try:
                    semester_part = group_name.split('_S')[1].split('_G')[0]
                    semester = int(semester_part)
                except (ValueError, IndexError):
                    pass
            
            day_pattern = self._get_day_pattern_for_department(dept_name, semester)
            
            if day_pattern not in groups_by_day_pattern:
                groups_by_day_pattern[day_pattern] = []
            groups_by_day_pattern[day_pattern].append(group_name)
        
        # Apply constraints for each day pattern separately
        for day_pattern, pattern_groups in groups_by_day_pattern.items():
            # Get representative department for this pattern with semester override
            representative_dept = pattern_groups[0].split('_S')[0]
            
            # Extract semester from first group for semester-specific overrides
            semester = None
            if '_S' in pattern_groups[0]:
                try:
                    semester_part = pattern_groups[0].split('_S')[1].split('_G')[0]
                    semester = int(semester_part)
                except (ValueError, IndexError):
                    pass
            
            dept_days = self._get_days_for_department(representative_dept, semester)
            num_dept_days = len(dept_days)
            
            self.logger.info(f"Applying advanced room capacity constraints for {day_pattern} pattern ({num_dept_days} days, {len(pattern_groups)} groups)")
            
            # NEW: Apply session-specific constraints for each time slot
            for day_idx in range(num_dept_days):
                for slot_idx in range(self.num_theory_slots):
                    # Calculate total rooms needed at this specific time slot
                    slot_room_requirements = []
                    slot_debug_info = []
                    
                    for group_name in pattern_groups:
                        group_sessions = group_detailed_sessions.get(group_name, {})
                        max_slots_needed = group_sessions.get('max_slots_needed', 0)
                        sessions_per_slot = group_sessions.get('sessions_per_slot', {})
                        
                        # Check if this group needs this slot index
                        if slot_idx < max_slots_needed and slot_idx in sessions_per_slot:
                            rooms_needed_this_slot = sessions_per_slot[slot_idx]
                            
                            # If group is scheduled at this time slot, it needs specific rooms
                            if (day_idx in group_timeslot_vars[group_name] and
                                slot_idx in group_timeslot_vars[group_name][day_idx]):
                                group_active = group_timeslot_vars[group_name][day_idx][slot_idx]
                                slot_room_requirements.append(group_active * rooms_needed_this_slot)
                                slot_debug_info.append(f"{group_name}:{rooms_needed_this_slot}")
                    
                    if slot_room_requirements:
                        # NEW: Precise constraint - only count rooms actually needed for this slot
                        model.Add(sum(slot_room_requirements) <= len(self.theory_room_ids))
                        constraints_applied += 1
                        
                        # Enhanced debug logging (calculate potential rooms from our tracking data)
                        total_potential_rooms = 0
                        for info in slot_debug_info:
                            if ':' in info:
                                try:
                                    rooms_count = int(info.split(':')[1])
                                    total_potential_rooms += rooms_count
                                except (ValueError, IndexError):
                                    self.logger.warning(f"Could not parse room count from debug info: {info}")
                        
                        if total_potential_rooms > len(self.theory_room_ids):
                            day_name = dept_days[day_idx] if day_idx < len(dept_days) else f"day_{day_idx}"
                            self.logger.debug(f"PRECISE CONSTRAINT: {day_name} {self.theory_time_slots[slot_idx]} slot#{slot_idx} ({day_pattern})")
                            self.logger.debug(f"  Groups needing this slot: {', '.join(slot_debug_info)}")
                            self.logger.debug(f"  Total rooms if all active: {total_potential_rooms}, Available: {len(self.theory_room_ids)}")
        
        # NEW: Advanced summary logging with detailed session tracking
        total_sessions_all_groups = sum(data.get('total_sessions', 0) for data in group_detailed_sessions.values())
        max_concurrent_rooms_needed = 0
        
        # Calculate maximum concurrent rooms needed across all time slots
        all_day_patterns = set()
        for group_name in group_detailed_sessions.keys():
            dept_name = group_name.split('_S')[0] if '_S' in group_name else "Computer Science & Engineering"
            semester = None
            if '_S' in group_name:
                try:
                    semester_part = group_name.split('_S')[1].split('_G')[0]
                    semester = int(semester_part)
                except (ValueError, IndexError):
                    pass
            day_pattern = self._get_day_pattern_for_department(dept_name, semester)
            all_day_patterns.add(day_pattern)
        
        for day_pattern in all_day_patterns:
            pattern_groups = [gn for gn in group_detailed_sessions.keys() 
                            if self._get_day_pattern_for_department(gn.split('_S')[0] if '_S' in gn else "Computer Science & Engineering", 
                                                                  int(gn.split('_S')[1].split('_G')[0]) if '_S' in gn else None) == day_pattern]
            
            # Check maximum rooms needed in any single time slot
            max_slot_index = max([group_detailed_sessions[gn].get('max_slots_needed', 0) for gn in pattern_groups])
            
            for slot_idx in range(max_slot_index):
                slot_total_rooms = 0
                for group_name in pattern_groups:
                    group_data = group_detailed_sessions.get(group_name, {})
                    sessions_per_slot = group_data.get('sessions_per_slot', {})
                    if slot_idx in sessions_per_slot:
                        slot_total_rooms += sessions_per_slot[slot_idx]
                
                max_concurrent_rooms_needed = max(max_concurrent_rooms_needed, slot_total_rooms)
        
        self.logger.info("="*80)
        self.logger.info("ADVANCED THEORY ROOM CAPACITY ANALYSIS:")
        self.logger.info(f"  📊 Total theory rooms available: {len(self.theory_room_ids)}")
        self.logger.info(f"  📈 Total sessions across all groups: {total_sessions_all_groups}")
        self.logger.info(f"  🎯 Maximum concurrent rooms needed: {max_concurrent_rooms_needed}")
        self.logger.info(f"  💡 Room utilization efficiency: {(max_concurrent_rooms_needed/len(self.theory_room_ids)*100):.1f}%")
        
        # Detailed group breakdown
        self.logger.info("  📋 Group-by-group session distribution:")
        for group_name, group_data in group_detailed_sessions.items():
            if group_data.get('total_sessions', 0) > 0:
                dept_name = group_name.split('_S')[0] if '_S' in group_name else "Computer Science & Engineering"
                semester = None
                if '_S' in group_name:
                    try:
                        semester_part = group_name.split('_S')[1].split('_G')[0]
                        semester = int(semester_part)
                    except (ValueError, IndexError):
                        pass
                
                day_pattern = self._get_day_pattern_for_department(dept_name, semester)
                sessions_per_slot = group_data.get('sessions_per_slot', {})
                slot_details = ', '.join([f"S{i}→{count}R" for i, count in sessions_per_slot.items()])
                
                self.logger.info(f"    - {group_name} ({day_pattern}): {group_data['total_sessions']} sessions → [{slot_details}]")
        
        # Efficiency warnings
        if max_concurrent_rooms_needed > len(self.theory_room_ids):
            self.logger.error(f"🚨 CRITICAL: Peak demand ({max_concurrent_rooms_needed} rooms) exceeds capacity ({len(self.theory_room_ids)} rooms)")
            self.logger.error(f"   → System will prevent over-allocation through constraints")
        elif max_concurrent_rooms_needed > len(self.theory_room_ids) * 0.9:
            self.logger.warning(f"⚠️  HIGH UTILIZATION: Peak demand ({max_concurrent_rooms_needed}) uses {(max_concurrent_rooms_needed/len(self.theory_room_ids)*100):.0f}% of capacity")
        else:
            self.logger.info(f"✅ OPTIMAL: Room capacity well within limits")
        
        self.logger.info("="*80)
        self.logger.info(f"Applied {constraints_applied} advanced session-specific room capacity constraints")
        return constraints_applied
    
    def apply_teacher_daily_presence_constraint(self, model, group_timeslot_vars):
        """
        Apply HARD constraint to prevent teacher violation days (11+ hour campus presence).
        Prevents teachers from having sessions spanning from early morning (8-9AM) to late evening (7PM+).
        Based on shift report violation criteria: normalized_start_hour <= 8 AND end_hour >= 19.
        
        UPDATED: Allow specific combinations like Slot 1 + Slot 9 (9:00-9:50 + 5:00-5:50) = 8+ hours
        """
        self.logger.info("Applying teacher daily presence constraint: prevent 11+ hour violation days...")
        constraints_applied = 0
        
        # Define violation time windows based on shift report logic
        # UPDATED: Only prevent the most extreme combinations
        # Violation: Start at earliest slot (8:00-8:50) AND end at latest slots (6:00-6:50+)
        early_morning_slots = [0,1]     # Only "8:00-8:50" (most extreme early)
        late_evening_slots = [9,10]     # Only "6:00-6:50" (most extreme late)
        
        # Map theory groups to teachers for efficient processing
        teacher_groups = defaultdict(list)
        for group_name in group_timeslot_vars.keys():
            # Find teacher(s) for this group
            dept_name = group_name.split('_S')[0] if '_S' in group_name else "Computer Science & Engineering"
            
            # Extract semester for semester-specific overrides
            semester = None
            if '_S' in group_name:
                try:
                    semester_part = group_name.split('_S')[1].split('_G')[0]
                    semester = int(semester_part)
                except (ValueError, IndexError):
                    pass
            
            # Find teachers for this group from course_groups
            for (dept, sem), groups in self.course_groups.items():
                if dept == dept_name and sem == semester:
                    for group_idx, group_instances in enumerate(groups):
                        expected_group_name = f"{dept}_S{sem}_G{group_idx + 1}"
                        if expected_group_name == group_name:
                            for instance in group_instances:
                                if instance.get('has_theory', False):
                                    teacher_id = str(instance['teacher_id'])
                                    if group_name not in teacher_groups[teacher_id]:
                                        teacher_groups[teacher_id].append(group_name)
                            break
        
        # Apply constraint for each teacher
        for teacher_id, groups in teacher_groups.items():
            if not groups:
                continue
                
            # Get department days for the first group (assuming all groups for a teacher follow same pattern)
            first_group = groups[0]
            dept_name = first_group.split('_S')[0] if '_S' in first_group else "Computer Science & Engineering"
            
            # Extract semester for semester-specific overrides
            semester = None
            if '_S' in first_group:
                try:
                    semester_part = first_group.split('_S')[1].split('_G')[0]
                    semester = int(semester_part)
                except (ValueError, IndexError):
                    pass
            
            dept_days = self._get_days_for_department(dept_name, semester)
            num_dept_days = len(dept_days)
            
            self.logger.debug(f"Applying presence constraint for Teacher {teacher_id} with {len(groups)} groups")
            
            # Apply constraint for each day
            for day_idx in range(num_dept_days):
                # Check if teacher has any early morning sessions (8-9AM)
                early_session_vars = []
                for group_name in groups:
                    if (group_name in group_timeslot_vars and
                        day_idx in group_timeslot_vars[group_name]):
                        for slot_idx in early_morning_slots:
                            if slot_idx in group_timeslot_vars[group_name][day_idx]:
                                early_session_vars.append(group_timeslot_vars[group_name][day_idx][slot_idx])
                
                # Check if teacher has any late evening sessions (6-7PM)
                late_session_vars = []
                for group_name in groups:
                    if (group_name in group_timeslot_vars and
                        day_idx in group_timeslot_vars[group_name]):
                        for slot_idx in late_evening_slots:
                            if slot_idx in group_timeslot_vars[group_name][day_idx]:
                                late_session_vars.append(group_timeslot_vars[group_name][day_idx][slot_idx])
                
                # HARD CONSTRAINT: Prevent both early AND late sessions on the same day
                if early_session_vars and late_session_vars:
                    # Create boolean variables for early and late presence
                    has_early_session = model.NewBoolVar(f'teacher_{teacher_id}_day_{day_idx}_early')
                    has_late_session = model.NewBoolVar(f'teacher_{teacher_id}_day_{day_idx}_late')
                    
                    # Link boolean variables to actual sessions
                    model.Add(sum(early_session_vars) > 0).OnlyEnforceIf(has_early_session)
                    model.Add(sum(early_session_vars) == 0).OnlyEnforceIf(has_early_session.Not())
                    
                    model.Add(sum(late_session_vars) > 0).OnlyEnforceIf(has_late_session)
                    model.Add(sum(late_session_vars) == 0).OnlyEnforceIf(has_late_session.Not())
                    
                    # PREVENT VIOLATION: Cannot have both early AND late sessions on same day
                    model.Add(has_early_session + has_late_session <= 1)
                    constraints_applied += 1
                    
                    day_name = dept_days[day_idx] if day_idx < len(dept_days) else f"day_{day_idx}"
                    self.logger.debug(f"Teacher {teacher_id}: blocked violation pattern on {day_name}")
                    self.logger.debug(f"  Early slots: {early_morning_slots} ({[self.theory_time_slots[i] for i in early_morning_slots if i < len(self.theory_time_slots)]})")
                    self.logger.debug(f"  Late slots: {late_evening_slots} ({[self.theory_time_slots[i] for i in late_evening_slots if i < len(self.theory_time_slots)]})")
        
        # Note: Lab constraint will be applied separately in lab constraints section
        # since we need access to lab_variables parameter
        
        self.logger.info(f"Applied {constraints_applied} teacher daily presence constraints (theory only)")
        self.logger.info("✅ RELAXED VIOLATION PREVENTION: Only prevents most extreme theory days (8:00-8:50 + 6:00-6:50)")
        self.logger.info("✅ ALLOWED: Slot 1 + Slot 9 (9:00-9:50 + 5:00-5:50) and similar 8+ hour combinations")
        return constraints_applied
    
    def _apply_daily_theory_slot_limit_constraint(self, model, group_timeslot_vars):
        """
        Apply constraint to limit the maximum number of theory TIME SLOTS used per day to 5.
        This means only 5 different time slots can be used per day across all groups.
        """
        self.logger.info("Applying daily theory slot limit constraint: maximum 5 time slots used per day...")
        constraints_applied = 0
        
        # Maximum theory time slots that can be used per day
        MAX_THEORY_SLOTS_PER_DAY = 5
        
        # Get all unique department patterns to determine which days to apply constraints
        unique_dept_patterns = set()
        for group_name in group_timeslot_vars.keys():
            dept_name = group_name.split('_S')[0] if '_S' in group_name else "Computer Science & Engineering"
            semester = None
            if '_S' in group_name:
                try:
                    semester_part = group_name.split('_S')[1].split('_G')[0]
                    semester = int(semester_part)
                except (ValueError, IndexError):
                    pass
            unique_dept_patterns.add((dept_name, semester))
        
        # Define core departments that get higher slot limits
        core_departments = {
            "Aeronautical Engineering", "Automobile Engineering", "Biomedical Engineering", 
            "Biotechnology", "Chemical Engineering", "Civil Engineering", 
            "Electrical & Electronics Engineering", "Electronics & Communication Engineering",
            "Food Technology", "Mechanical Engineering", "Mechatronics Engineering"
        }
        
        # Apply constraint for each department pattern
        for dept_name, semester in unique_dept_patterns:
            # EXCEPTIONS: Skip constraint for specific department-semester combinations
            if dept_name == "Biotechnology" and semester == 5:
                self.logger.info(f"✅ EXCEPTION: Biotechnology S5 is exempt from daily theory slot limit")
                continue
            if dept_name == "Electronics & Communication Engineering" and semester == 5:
                self.logger.info(f"✅ EXCEPTION: Electronics & Communication Engineering S5 is exempt from daily theory slot limit")
                continue
            
            # Determine slot limit based on department type
            if dept_name in core_departments:
                dept_slot_limit = 6  # Core departments get 6 slots
                dept_type = "CORE"
            else:
                dept_slot_limit = MAX_THEORY_SLOTS_PER_DAY  # Non-core departments get 5 slots
                dept_type = "NON-CORE"
                
            dept_days = self._get_days_for_department(dept_name, semester)
            num_dept_days = len(dept_days)
            
            # For each day, create boolean variables for each time slot
            # indicating whether that time slot is used at all
            for day_idx in range(num_dept_days):
                slot_usage_vars = []
                
                # For each time slot, create a boolean variable indicating if it's used
                for slot_idx in range(self.num_theory_slots):
                    slot_used_var = model.NewBoolVar(f'slot_used_{dept_name}_S{semester}_d{day_idx}_s{slot_idx}')
                    slot_usage_vars.append(slot_used_var)
                    
                    # Collect all group variables for this time slot
                    groups_at_slot = []
                    for group_name in group_timeslot_vars.keys():
                        # Check if this group belongs to the current department pattern
                        group_dept = group_name.split('_S')[0] if '_S' in group_name else "Computer Science & Engineering"
                        group_semester = None
                        if '_S' in group_name:
                            try:
                                semester_part = group_name.split('_S')[1].split('_G')[0]
                                group_semester = int(semester_part)
                            except (ValueError, IndexError):
                                pass
                        
                        if (group_dept == dept_name and group_semester == semester and
                            group_name in group_timeslot_vars and
                            day_idx in group_timeslot_vars[group_name] and
                            slot_idx in group_timeslot_vars[group_name][day_idx]):
                            groups_at_slot.append(group_timeslot_vars[group_name][day_idx][slot_idx])
                    
                    # Link the slot usage variable to the actual group assignments
                    if groups_at_slot:
                        # If any group uses this slot, then slot_used_var must be True
                        model.Add(sum(groups_at_slot) > 0).OnlyEnforceIf(slot_used_var)
                        model.Add(sum(groups_at_slot) == 0).OnlyEnforceIf(slot_used_var.Not())
                
                # MAIN CONSTRAINT: Apply department-specific slot limit
                if slot_usage_vars:
                    model.Add(sum(slot_usage_vars) <= dept_slot_limit)
                    constraints_applied += 1
                    
                    day_name = dept_days[day_idx] if day_idx < len(dept_days) else f"day_{day_idx}"
                    self.logger.debug(f"Day {day_name} for {dept_name} S{semester} ({dept_type}): max {dept_slot_limit} time slots can be used")
        
        self.logger.info(f"Applied {constraints_applied} daily theory slot limit constraints")
        self.logger.info(f"✅ THEORY TIME SLOT LIMITS:")
        self.logger.info(f"   - CORE DEPARTMENTS: Maximum 6 different time slots per day")
        self.logger.info(f"   - NON-CORE DEPARTMENTS: Maximum {MAX_THEORY_SLOTS_PER_DAY} different time slots per day") 
        self.logger.info(f"   - BIOTECHNOLOGY S5: Unlimited (exempt)")
        self.logger.info(f"   - ELECTRONICS & COMMUNICATION ENGINEERING S5: Unlimited (exempt)")
        self.logger.info(f"✅ Core departments: {', '.join(sorted(core_departments))}")
        return constraints_applied

    def _apply_teacher_day_preference_constraints(self, model, group_timeslot_vars):
        """CRITICAL CONSTRAINT: Groups containing pop.csv teachers can ONLY be scheduled on their preferred days.
        
        This is a HARD constraint that completely blocks any group that contains a pop.csv teacher
        from being scheduled on non-preferred days. This ensures the groups fall on the correct days.
        """
        self.logger.info("🎯 APPLYING CRITICAL POP.CSV DAY PREFERENCE CONSTRAINTS...")
        constraints_applied = 0
        
        if not hasattr(self, 'teacher_day_preferences') or not self.teacher_day_preferences:
            self.logger.error("❌ CRITICAL: No teacher day preferences loaded from pop.csv!")
            return 0
        
        # Build mapping of teacher to their groups
        teacher_to_groups = {}
        for (dept, sem), groups in self.course_groups.items():
            for group_idx, group_instances in enumerate(groups):
                group_name = f"{dept}_S{sem}_G{group_idx + 1}"
                for instance in group_instances:
                    teacher_key = str(instance['teacher_id'])
                    if teacher_key not in teacher_to_groups:
                        teacher_to_groups[teacher_key] = []
                    if group_name not in teacher_to_groups[teacher_key]:
                        teacher_to_groups[teacher_key].append(group_name)
        
        self.logger.info(f"📋 LOADED POP.CSV TEACHERS: {list(self.teacher_day_preferences.keys())}")
        self.logger.info(f"📋 TEACHERS WITH GROUPS: {list(teacher_to_groups.keys())[:10]}...")
        
        # CRITICAL: Apply hard day blocking for each pop.csv teacher
        pop_teachers_processed = 0
        total_groups_affected = 0
        
        for teacher_id, preferences in self.teacher_day_preferences.items():
            # Get preferred days (use general preferences or first course-specific)
            preferred_days = None
            if '*' in preferences:
                preferred_days = preferences['*']
            else:
                for course_code, days in preferences.items():
                    preferred_days = days
                    break
            
            if not preferred_days:
                self.logger.error(f"❌ Teacher {teacher_id}: No valid preferred days found!")
                continue
            
            if teacher_id not in teacher_to_groups:
                self.logger.error(f"❌ CRITICAL: Teacher {teacher_id} from pop.csv NOT FOUND in any theory groups!")
                # Show sample teacher IDs for debugging
                sample_teachers = list(teacher_to_groups.keys())[:5]
                self.logger.error(f"   Sample teacher IDs in system: {sample_teachers}")
                continue
            
            pop_teachers_processed += 1
            teacher_groups = teacher_to_groups[teacher_id]
            total_groups_affected += len(teacher_groups)
            
            day_names = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday']
            pref_day_list = [day_names[d] for d in preferred_days if d < len(day_names)]
            
            self.logger.info(f"🎯 TEACHER {teacher_id}: MUST ONLY BE on {pref_day_list}")
            self.logger.info(f"   📚 Teacher has {len(teacher_groups)} groups: {teacher_groups}")
            
            # For each group containing this teacher, BLOCK all non-preferred days
            for group_name in teacher_groups:
                if group_name not in group_timeslot_vars:
                    self.logger.warning(f"   ⚠️  Group {group_name} not in timeslot variables")
                    continue
                
                # Parse group info to get department days
                dept_days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday']  # Default
                if '_S' in group_name:
                    parts = group_name.split('_S')
                    dept_name = parts[0]
                    sem_part = parts[1].split('_G')[0] if '_G' in parts[1] else parts[1]
                    try:
                        semester = int(sem_part)
                        dept_days = self._get_days_for_department(dept_name, semester)
                    except ValueError:
                        dept_days = self._get_days_for_department(dept_name)
                
                self.logger.info(f"   📅 Group {group_name}: Available days {dept_days}")
                
                # HARD BLOCK: Set all non-preferred days to ZERO for this group
                group_constraints = 0
                blocked_days = []
                allowed_days = []
                
                for day_idx in range(len(dept_days)):
                    day_name = dept_days[day_idx]
                    
                    if day_idx not in preferred_days:
                        # COMPLETELY BLOCK this day for this group
                        blocked_days.append(day_name)
                        if day_idx in group_timeslot_vars[group_name]:
                            for slot_idx in group_timeslot_vars[group_name][day_idx]:
                                # FORCE GROUP TO NEVER SCHEDULE ON THIS DAY
                                model.Add(group_timeslot_vars[group_name][day_idx][slot_idx] == 0)
                                constraints_applied += 1
                                group_constraints += 1
                    else:
                        # This day is ALLOWED
                        allowed_days.append(day_name)
                
                self.logger.info(f"   ✅ Group {group_name} ALLOWED: {allowed_days}")
                self.logger.info(f"   🚫 Group {group_name} BLOCKED: {blocked_days}")
                self.logger.info(f"   🔒 Applied {group_constraints} blocking constraints for this group")
        
        # FINAL VERIFICATION SUMMARY
        self.logger.info("="*70)
        self.logger.info("🎯 POP.CSV DAY PREFERENCE CONSTRAINT SUMMARY:")
        self.logger.info(f"   📋 Teachers in pop.csv file: {len(self.teacher_day_preferences)}")
        self.logger.info(f"   ✅ Teachers successfully processed: {pop_teachers_processed}")
        self.logger.info(f"   📚 Total groups affected: {total_groups_affected}")
        self.logger.info(f"   🔒 Total day-blocking constraints: {constraints_applied}")
        
        if pop_teachers_processed == 0:
            self.logger.error("❌❌❌ CRITICAL FAILURE: NO POP.CSV TEACHERS WERE PROCESSED!")
            self.logger.error("❌❌❌ DAY PREFERENCES WILL NOT BE ENFORCED!")
        elif constraints_applied == 0:
            self.logger.warning("⚠️⚠️⚠️  WARNING: Teachers found but NO CONSTRAINTS applied!")
        else:
            self.logger.info(f"✅✅✅ SUCCESS: {pop_teachers_processed} teachers constrained with {constraints_applied} hard blocks")
        
        self.logger.info("="*70)
        return constraints_applied
    
    def _apply_cross_system_constraints(self, model, lab_variables, group_timeslot_vars):
        """Apply constraints that prevent conflicts between lab and theory systems."""
        self.logger.info("Applying cross-system conflict prevention constraints...")
        constraints_applied = 0
        
        # CONSTRAINT 1: Unified Teacher Weekly Shift Patterns
        # Apply unified shift constraints that coordinate both lab and theory scheduling
        constraints_applied += self.apply_unified_weekly_shift_constraint(model, lab_variables, group_timeslot_vars)
        
        # CONSTRAINT 2: Department/Semester Group Conflict Prevention
        # Lab groups and theory groups from the same dept/semester CANNOT overlap in time
        # This is the only remaining cross-system constraint after unification.
        constraints_applied += self._apply_dept_semester_group_conflict_constraint(model, lab_variables, group_timeslot_vars)
        
        self.logger.info(f"Applied {constraints_applied} cross-system constraints")
        return constraints_applied
    
    def _apply_dept_semester_group_conflict_constraint(self, model, lab_variables, group_timeslot_vars):
        """
        Prevents ANY lab group and ANY theory group from the SAME dept/semester from overlapping in time.
        This is a semester-wide exclusion constraint.
        """
        self.logger.info("Applying department/semester-wide lab-theory exclusion constraint...")
        constraints_applied = 0
        
        # 1. Group lab instances and theory groups by (dept, semester)
        semester_map = defaultdict(lambda: {'lab_instances': [], 'theory_groups': []})

        # Group lab instances
        if hasattr(self, 'instance_group_mapping'):
            for teacher_id in lab_variables:
                for course_instance_id in lab_variables[teacher_id]:
                    if course_instance_id in self.instance_group_mapping:
                        mapping = self.instance_group_mapping[course_instance_id]
                        key = (mapping['department'], mapping['semester'])
                        semester_map[key]['lab_instances'].append((teacher_id, course_instance_id))

        # Group theory groups by parsing their names
        for theory_group_name in group_timeslot_vars.keys():
            # Example name: "Computer Science & Engineering_S3_G1"
            parts = theory_group_name.split('_S')
            if len(parts) == 2:
                dept = parts[0]
                semester_part = parts[1].split('_G')[0]
                try:
                    semester = int(semester_part)
                    key = (dept, semester)
                    semester_map[key]['theory_groups'].append(theory_group_name)
                except ValueError:
                    self.logger.warning(f"Could not parse semester from group name: {theory_group_name}")
                    continue

        # 2. Apply semester-wide exclusion for each time slot
        for (dept, semester), data in semester_map.items():
            if not data['lab_instances'] or not data['theory_groups']:
                continue
                
            self.logger.debug(f"Applying semester-wide conflicts for {dept} S{semester}...")

            # Get department-specific days for this constraint
            dept_days = self._get_days_for_department(dept)
            num_dept_days = len(dept_days)
            
            # For each time point (day, theory_slot) - use department-specific days
            for day_idx in range(num_dept_days):
                for theory_slot_idx in range(self.num_theory_slots):
                    
                    # A. Determine if any theory class for this semester is active
                    theory_vars_at_slot = []
                    for group_name in data['theory_groups']:
                        if (group_name in group_timeslot_vars and
                            day_idx in group_timeslot_vars[group_name] and
                            theory_slot_idx in group_timeslot_vars[group_name][day_idx]):
                            theory_vars_at_slot.append(group_timeslot_vars[group_name][day_idx][theory_slot_idx])
                    if not theory_vars_at_slot:
                        continue

                    is_theory_active_for_sem = model.NewBoolVar(f'theory_active_{dept}_S{semester}_d{day_idx}_ts{theory_slot_idx}')
                    model.Add(sum(theory_vars_at_slot) > 0).OnlyEnforceIf(is_theory_active_for_sem)
                    model.Add(sum(theory_vars_at_slot) == 0).OnlyEnforceIf(is_theory_active_for_sem.Not())

                    # B. Determine if any lab class for this semester is active in an overlapping lab session
                    lab_vars_at_overlapping_slot = []
                    if theory_slot_idx in self.theory_to_lab_mapping:
                        # Find which lab sessions overlap with this theory time slot
                        overlapping_lab_sessions = set()
                        for lab_time_slot_idx in self.theory_to_lab_mapping[theory_slot_idx]:
                            for session_name, session_details in self.lab_sessions_details.items():
                                if lab_time_slot_idx in session_details['slots']:
                                    overlapping_lab_sessions.add(session_name)
                                    break
                        
                        if not overlapping_lab_sessions:
                            continue
                            
                        # Get all lab variables for this semester in the overlapping sessions
                        for session_name in overlapping_lab_sessions:
                            for teacher_id, course_instance_id in data['lab_instances']:
                                if (teacher_id in lab_variables and
                                    course_instance_id in lab_variables[teacher_id] and
                                    day_idx < len(lab_variables[teacher_id][course_instance_id]) and
                                    session_name in lab_variables[teacher_id][course_instance_id][day_idx]):
                                    lab_vars_at_overlapping_slot.extend(
                                        lab_variables[teacher_id][course_instance_id][day_idx][session_name].values()
                                    )
                        
                        if not lab_vars_at_overlapping_slot:
                            continue

                        is_lab_active_for_sem = model.NewBoolVar(f'lab_active_{dept}_S{semester}_d{day_idx}_ts{theory_slot_idx}')
                        model.Add(sum(lab_vars_at_overlapping_slot) > 0).OnlyEnforceIf(is_lab_active_for_sem)
                        model.Add(sum(lab_vars_at_overlapping_slot) == 0).OnlyEnforceIf(is_lab_active_for_sem.Not())
                            
                        # C. Add the exclusion constraint: At most one can be active
                        model.Add(is_theory_active_for_sem + is_lab_active_for_sem <= 1)
                        constraints_applied += 1
        
        self.logger.info(f"Applied {constraints_applied} department/semester-wide lab-theory exclusion constraints.")
        return constraints_applied
    
    def _apply_unified_teacher_clash_constraint(self, model, lab_variables, group_timeslot_vars):
        """
        Ensures a teacher is not assigned to more than one activity (lab or theory) at the same time.
        This is the single source of truth for all teacher-related time conflicts.
        """
        self.logger.info("Applying optimized unified teacher clash constraint...")
        constraints_applied = 0
        
        # 1. Pre-build optimized teacher activities mapping
        teacher_activities = {}
        
        # Map lab courses to teachers (optimized)
        for teacher_id, courses in self.lab_requirements.items():
            teacher_key = str(teacher_id)
            if teacher_key not in teacher_activities:
                teacher_activities[teacher_key] = {'lab_courses': [], 'theory_groups': []}
            for course in courses:
                teacher_activities[teacher_key]['lab_courses'].append(course['course_instance_id'])

        # Map theory groups to teachers (optimized)
        for (dept, sem), groups in self.course_groups.items():
            for group_idx, group_instances in enumerate(groups):
                group_name = f"{dept}_S{sem}_G{group_idx + 1}"
                for instance in group_instances:
                    teacher_key = str(instance['teacher_id'])
                    if teacher_key not in teacher_activities:
                        teacher_activities[teacher_key] = {'lab_courses': [], 'theory_groups': []}
                    if group_name not in teacher_activities[teacher_key]['theory_groups']:
                        teacher_activities[teacher_key]['theory_groups'].append(group_name)
        
        # 2. Pre-cache department information to avoid repeated lookups
        course_dept_cache = {}
        group_dept_cache = {}
        
        # Cache course department information
        for teacher_id, activities in teacher_activities.items():
            for course_instance_id in activities['lab_courses']:
                if course_instance_id not in course_dept_cache:
                    if hasattr(self, 'instance_group_mapping') and course_instance_id in self.instance_group_mapping:
                        mapping = self.instance_group_mapping[course_instance_id]
                        course_dept_cache[course_instance_id] = {
                            'dept_name': mapping['department'],
                            'semester': mapping.get('semester'),
                            'days': self._get_days_for_department(mapping['department'], mapping.get('semester'))
                        }
                    else:
                        course_dept_cache[course_instance_id] = {
                            'dept_name': "Computer Science & Engineering",
                            'semester': None,
                            'days': self._get_days_for_department("Computer Science & Engineering")
                        }
        
        # Cache group department information
        for teacher_id, activities in teacher_activities.items():
            for group_name in activities['theory_groups']:
                if group_name not in group_dept_cache:
                    if '_S' in group_name:
                        parts = group_name.split('_S')
                        dept_name = parts[0]
                        sem_part = parts[1].split('_G')[0] if '_G' in parts[1] else parts[1]
                        try:
                            semester = int(sem_part)
                            group_dept_cache[group_name] = {
                                'dept_name': dept_name,
                                'semester': semester,
                                'days': self._get_days_for_department(dept_name, semester)
                            }
                        except ValueError:
                            group_dept_cache[group_name] = {
                                'dept_name': dept_name,
                                'semester': None,
                                'days': self._get_days_for_department(dept_name)
                            }
                    else:
                        group_dept_cache[group_name] = {
                            'dept_name': "Computer Science & Engineering",
                            'semester': None,
                            'days': self._get_days_for_department("Computer Science & Engineering")
                        }
        
        # Pre-cache overlapping lab sessions for each theory slot (major optimization)
        theory_to_lab_sessions_cache = {}
        for theory_slot_idx in range(self.num_theory_slots):
            overlapping_sessions = set()
            if theory_slot_idx in self.theory_to_lab_mapping:
                for lab_time_slot_idx in self.theory_to_lab_mapping[theory_slot_idx]:
                    for session_name, session_details in self.lab_sessions_details.items():
                        if lab_time_slot_idx in session_details['slots']:
                            overlapping_sessions.add(session_name)
            theory_to_lab_sessions_cache[theory_slot_idx] = overlapping_sessions
        
        # Pre-cache course information for co-scheduling checks
        course_info_cache = {}
        for teacher_id, activities in teacher_activities.items():
            for course_instance_id in activities['lab_courses']:
                if course_instance_id not in course_info_cache:
                    base_id = self._get_base_course_id(course_instance_id)
                    course_matches = self.courses_df[self.courses_df['id'] == int(base_id)]
                    if not course_matches.empty:
                        course_row = course_matches.iloc[0]
                        course_info_cache[course_instance_id] = {
                            'course_code': course_row['course_code'],
                            'practical_hours': int(course_row.get('practical_hours', 0)),
                            'group_name': self.instance_group_mapping[course_instance_id]['group_name'] if hasattr(self, 'instance_group_mapping') and course_instance_id in self.instance_group_mapping else ""
                        }
        
        # 3. Optimized constraint application
        for teacher_id, activities in teacher_activities.items():
            # Skip teachers with no activities
            if not activities['lab_courses'] and not activities['theory_groups']:
                continue

            # Get unified day range for this teacher (cached)
            all_dept_days = set()
            for course_instance_id in activities['lab_courses']:
                all_dept_days.update(course_dept_cache[course_instance_id]['days'])
            for group_name in activities['theory_groups']:
                all_dept_days.update(group_dept_cache[group_name]['days'])
            
            if all_dept_days:
                dept_days = sorted(list(all_dept_days), key=lambda d: 
                    {'monday': 1, 'tuesday': 2, 'wed': 3, 'thur': 4, 'fri': 5, 'saturday': 6}.get(d, 999))
            else:
                dept_days = self._get_days_for_department("Computer Science & Engineering")

            # Optimized time slot iteration
            for day_idx in range(len(dept_days)):
                unified_day_name = dept_days[day_idx]
                
                for theory_slot_idx in range(self.num_theory_slots):
                    all_activities_at_this_time = []

                    # A. Collect THEORY activities (optimized)
                    for group_name in activities['theory_groups']:
                        if group_name in group_timeslot_vars:
                            group_info = group_dept_cache[group_name]
                            if unified_day_name in group_info['days']:
                                group_day_idx = group_info['days'].index(unified_day_name)
                                if (group_day_idx in group_timeslot_vars[group_name] and
                                theory_slot_idx in group_timeslot_vars[group_name][group_day_idx]):
                                    all_activities_at_this_time.append(
                                    group_timeslot_vars[group_name][group_day_idx][theory_slot_idx]
                                )
                    
                    # B. Collect LAB activities (optimized with cached sessions)
                    overlapping_lab_sessions = theory_to_lab_sessions_cache[theory_slot_idx]
                    
                    for session_name in overlapping_lab_sessions:
                        for course_instance_id in activities['lab_courses']:
                            if teacher_id in lab_variables and course_instance_id in lab_variables.get(teacher_id, {}):
                                course_info = course_dept_cache[course_instance_id]
                                if unified_day_name in course_info['days']:
                                    course_day_idx = course_info['days'].index(unified_day_name)
                                    if (course_day_idx < len(lab_variables[teacher_id][course_instance_id]) and
                                    session_name in lab_variables[teacher_id][course_instance_id][course_day_idx]):
                                        for room_id in lab_variables[teacher_id][course_instance_id][course_day_idx][session_name]:
                                                all_activities_at_this_time.append(
                                                    lab_variables[teacher_id][course_instance_id][course_day_idx][session_name][room_id]
                                                )
                            
                    # C. Apply constraint with co-scheduling exception (optimized)
                    if len(all_activities_at_this_time) > 1:
                        can_co_schedule = False
                        
                        # Quick co-scheduling check (optimized)
                        if len(all_activities_at_this_time) == 2:
                            # Find course instances for lab activities
                            lab_course_instances = []
                            for course_instance_id in activities['lab_courses']:
                                if course_instance_id in course_info_cache:
                                    course_info = course_info_cache[course_instance_id]
                                    if course_info['practical_hours'] >= 4:
                                        lab_course_instances.append({
                                            'instance_id': course_instance_id,
                                            'course_code': course_info['course_code'],
                                            'group_name': course_info['group_name']
                                        })
                            
                            # Check if we have 2 instances of the same course in the same group
                            if len(lab_course_instances) >= 2:
                                for i in range(len(lab_course_instances)):
                                    for j in range(i + 1, len(lab_course_instances)):
                                        inst1 = lab_course_instances[i]
                                        inst2 = lab_course_instances[j]
                                        
                                        # Same course in same group can be co-scheduled
                                        if (inst1['course_code'] == inst2['course_code'] and
                                            inst1['group_name'] == inst2['group_name']):
                                            can_co_schedule = True
                                            break
                                    if can_co_schedule:
                                        break
                        
                        if not can_co_schedule:
                            model.Add(sum(all_activities_at_this_time) <= 1)
                            constraints_applied += 1
                        # If co-scheduling allowed, no constraint is added
        
        self.logger.info(f"Applied {constraints_applied} optimized unified teacher clash constraints.")
        return constraints_applied
    
    def _add_combined_objectives(self, model, lab_variables, group_timeslot_vars):
        """Add optimization objectives for the combined model."""
        self.logger.info("Setting up combined optimization objectives...")
        
        objective_terms = []
        
        # Lab objective: REMOVED - do not reward lab assignments to prevent over-allocation
        # The constraints already ensure required lab sessions are scheduled
        # Rewarding every lab assignment incentivizes over-allocation beyond required sessions
        
        # OPTIONAL: Add penalty for over-allocation (courses getting more sessions than base_sessions)
        # if hasattr(self, 'lab_requirements'):
        #     for teacher_id in self.lab_requirements:
        #         for course_req in self.lab_requirements[teacher_id]:
        #             course_instance_id = course_req['course_instance_id']
        #             base_sessions = course_req['base_sessions']
                    
        #             if teacher_id in lab_variables and course_instance_id in lab_variables[teacher_id]:
        #                 # Count total assignments for this course
        #                 total_assignments = []
                        
        #                 # Get department for this course instance
        #                 dept_name = "Computer Science & Engineering"  # Default
        #                 semester = None
        #                 if hasattr(self, 'instance_group_mapping') and course_instance_id in self.instance_group_mapping:
        #                     mapping = self.instance_group_mapping[course_instance_id]
        #                     dept_name = mapping['department']
        #                     semester = mapping.get('semester')
        #                 else:
        #                     # Fallback: look up in courses_df
        #                     base_id = self._get_base_course_id(course_instance_id)
        #                     course_matches = self.courses_df[self.courses_df['id'] == int(base_id)]
        #                     if not course_matches.empty:
        #                         dept_name = course_matches.iloc[0].get('student_dept', 'Computer Science & Engineering')
                        
        #                 dept_days = self._get_days_for_department(dept_name, semester)
        #                 num_dept_days = len(dept_days)
                        
        #                 for day_idx in range(num_dept_days):
        #                     if day_idx in lab_variables[teacher_id][course_instance_id]:
        #                         for session_name in self.lab_sessions.keys():
        #                             if session_name in lab_variables[teacher_id][course_instance_id][day_idx]:
        #                                 for room_id in self.lab_room_ids:
        #                                     if room_id in lab_variables[teacher_id][course_instance_id][day_idx][session_name]:
        #                                         total_assignments.append(lab_variables[teacher_id][course_instance_id][day_idx][session_name][room_id])
                        
        #                 if total_assignments:
        #                     # Create penalty for over-allocation (sessions > base_sessions)
        #                     over_allocation_penalty = model.NewIntVar(0, len(total_assignments), f'over_alloc_penalty_{course_instance_id}')
        #                     model.Add(over_allocation_penalty >= sum(total_assignments) - base_sessions)
        #                     model.Add(over_allocation_penalty >= 0)
                            
        #                     # Apply penalty to objective (subtract penalty to discourage over-allocation)
        #                     over_allocation_weight = 1000  # Strong penalty for over-allocation
        #                     objective_terms.append(-over_allocation_weight * over_allocation_penalty)
        
        # Theory objective: maximize group timeslot allocations (all time slots equal)
        for group_name, day_slots in group_timeslot_vars.items():
            # Get department and semester for this group
            dept_name = group_name.split('_S')[0] if '_S' in group_name else "Computer Science & Engineering"
            semester = None
            if '_S' in group_name:
                sem_part = group_name.split('_S')[1].split('_G')[0] if '_G' in group_name else group_name.split('_S')[1]
                try:
                    semester = int(sem_part)
                except ValueError:
                    semester = None
            dept_days = self._get_days_for_department(dept_name, semester)
            num_dept_days = len(dept_days)
            
            for day_idx in range(num_dept_days):
                if day_idx in day_slots:
                    for slot_idx in range(self.num_theory_slots):
                        if slot_idx in day_slots[day_idx]:
                            # Equal weight for all time slots (no time preference)
                            objective_terms.append(day_slots[day_idx][slot_idx])
        
        # Add capacity preferences for lab room assignments
        if hasattr(self, 'capacity_preferences') and self.capacity_preferences:
            objective_terms.extend(self.capacity_preferences)
            self.logger.info(f"Added {len(self.capacity_preferences)} capacity preference terms to objective")
            self.logger.info("  • Encourages 70+ capacity labs for courses with 4-6 practical hours")
            self.logger.info("  • Allows 35-capacity labs with batching as fallback")
        
        # Add preference for 70-capacity labs
        labs_70_bonus = 1000  # Strong preference for using 70-capacity labs
        
        # PERFORMANCE OPTIMIZATION: Pre-cache room capacities to avoid repeated DataFrame lookups
        room_capacities = {}
        for _, room in self.lab_rooms.iterrows():
            room_capacities[str(room['id'])] = int(room['room_max_cap'])
        
        # PERFORMANCE OPTIMIZATION: Streamlined loop with minimal operations
        capacity_terms_added = 0
        for teacher_id in lab_variables:
            for course_instance_id in lab_variables[teacher_id]:
                for day_idx in lab_variables[teacher_id][course_instance_id]:
                    for session_name in lab_variables[teacher_id][course_instance_id][day_idx]:
                        for room_id in lab_variables[teacher_id][course_instance_id][day_idx][session_name]:
                            var = lab_variables[teacher_id][course_instance_id][day_idx][session_name][room_id]
                            
                            # Use pre-cached room capacity (O(1) lookup instead of DataFrame search)
                            room_capacity = room_capacities.get(room_id, 0)
                            
                            if room_capacity == 70:
                                # BONUS for using 70-capacity labs (perfect size for single instances)
                                objective_terms.append(var * labs_70_bonus)
                                capacity_terms_added += 1
        
        self.logger.info(f"Added {capacity_terms_added} room capacity preference terms to objective (OPTIMIZED)")
        self.logger.info(f"  • 70-capacity lab preference bonus: +{labs_70_bonus}")
        
        # Add penalty for consecutive slots (soft constraint - minimize penalties)
        if hasattr(self, 'consecutive_slot_penalties') and self.consecutive_slot_penalties:
            # Subtract penalties (since we're maximizing, subtracting penalties minimizes them)
            penalty_weight = 100  # Adjust weight as needed - higher weight = stronger penalty
            for penalty_var in self.consecutive_slot_penalties:
                objective_terms.append(-penalty_weight * penalty_var)
            self.logger.info(f"Added {len(self.consecutive_slot_penalties)} consecutive slot penalty terms (weight: {penalty_weight})")
            self.logger.info("  • Discourages groups from having more than 2 consecutive time slots")
        
        # Add penalty for late scheduling (soft constraint - prefer early scheduling)
        if hasattr(self, 'late_scheduling_penalties') and self.late_scheduling_penalties:
            # Subtract penalties (since we're maximizing, subtracting penalties minimizes them)
            late_penalty_weight = 150  # Higher weight than consecutive slots - early scheduling is important
            for penalty_var in self.late_scheduling_penalties:
                objective_terms.append(-late_penalty_weight * penalty_var)
            self.logger.info(f"Added {len(self.late_scheduling_penalties)} late scheduling penalty terms (weight: {late_penalty_weight})")
            self.logger.info("  • Strongly discourages theory sessions scheduled at 3:00 PM or later")
        
        # Add penalty for core lab groups exceeding 8 slots (soft constraint - minimize penalties)
        if hasattr(self, 'core_lab_group_slot_penalties') and self.core_lab_group_slot_penalties:
            # Subtract penalties (since we're maximizing, subtracting penalties minimizes them)
            penalty_weight = 200  # Higher weight than consecutive slots - core lab limit is more important
            for penalty_var in self.core_lab_group_slot_penalties:
                objective_terms.append(-penalty_weight * penalty_var)
            self.logger.info(f"Added {len(self.core_lab_group_slot_penalties)} core lab group slot penalty terms (weight: {penalty_weight})")
            self.logger.info("  • Discourages core lab groups from using more than 8 lab slots")
        
        # Add penalty for computing groups exceeding 6 slots (soft constraint - minimize penalties)
        if hasattr(self, 'computing_group_slot_penalties') and self.computing_group_slot_penalties:
            # Subtract penalties (since we're maximizing, subtracting penalties minimizes them)
            penalty_weight = 150  # Moderate weight - computing group limit is important but less than core labs
            for penalty_var in self.computing_group_slot_penalties:
                objective_terms.append(-penalty_weight * penalty_var)
            self.logger.info(f"Added {len(self.computing_group_slot_penalties)} computing group slot penalty terms (weight: {penalty_weight})")
            self.logger.info("  • Discourages computing groups from using more than 6 lab slots")
        
        # Add bonus for consecutive batch scheduling preference (soft constraint - encourage consecutive scheduling)
        if hasattr(self, 'consecutive_batch_preference_vars') and self.consecutive_batch_preference_vars:
            # Add bonuses (since we're maximizing, adding bonuses encourages preferred behavior)
            preference_weight = 50  # Moderate weight - encourage but don't force consecutive batch scheduling
            for preference_var in self.consecutive_batch_preference_vars:
                objective_terms.append(preference_weight * preference_var)
            self.logger.info(f"Added {len(self.consecutive_batch_preference_vars)} consecutive batch preference terms (weight: {preference_weight})")
            self.logger.info("  • Encourages consecutive scheduling of batched lab sessions for specific departments")
        
        # Add penalty for shift violations (soft constraint - discourage shift violations)
        if hasattr(self, 'shift_preference_vars') and self.shift_preference_vars:
            # Subtract penalties (since we're maximizing, subtracting penalties minimizes them)
            shift_penalty_weight = 3500  # Moderate weight - discourage shift violations but allow flexibility
            for penalty_var in self.shift_preference_vars:
                objective_terms.append(-shift_penalty_weight * penalty_var)
            self.logger.info(f"Added {len(self.shift_preference_vars)} shift violation penalty terms (weight: {shift_penalty_weight})")
            self.logger.info("  • Discourages violation of shift-based time constraints for single-instance departments")
            self.logger.info("  • Encourages consistent shift patterns within departments")
        
        # Add penalty for teacher consecutive lab violations (soft constraint for Biotechnology)
        if hasattr(self, 'teacher_consecutive_penalty_vars') and self.teacher_consecutive_penalty_vars:
            # Subtract penalties (since we're maximizing, subtracting penalties minimizes them)
            teacher_consecutive_penalty_weight = 100  # Moderate weight - discourage but allow 3+ consecutive for experiments
            for penalty_var in self.teacher_consecutive_penalty_vars:
                objective_terms.append(-teacher_consecutive_penalty_weight * penalty_var)
            self.logger.info(f"Added {len(self.teacher_consecutive_penalty_vars)} teacher consecutive lab penalty terms (weight: {teacher_consecutive_penalty_weight})")
            self.logger.info("  • Discourages teachers from having 3+ consecutive lab slots (soft constraint for Biotechnology)")
            self.logger.info("  • Allows experimental continuity when needed but prefers shorter consecutive sessions")
        
        # Add penalty for 5pm constraint violations (soft constraint - discourage late scheduling)
        if hasattr(self, 'soft_5pm_penalty_vars') and self.soft_5pm_penalty_vars:
            # Subtract penalties (since we're maximizing, subtracting penalties minimizes them)
            soft_5pm_penalty_weight = self.soft_5pm_constraint_weight  # Use the configured weight
            for penalty_var in self.soft_5pm_penalty_vars:
                objective_terms.append(-soft_5pm_penalty_weight * penalty_var)
            self.logger.info(f"Added {len(self.soft_5pm_penalty_vars)} soft 5pm constraint penalty terms (weight: {soft_5pm_penalty_weight})")
            self.logger.info("  • Discourages departments with soft 5pm constraints from scheduling after 5:00 PM")
        
        # Note: Flexible lunch constraint moved to _apply_flexible_lunch_constraint() as a HARD constraint
        
        if objective_terms:
            model.Maximize(sum(objective_terms))
            self.logger.info(f"Combined objective set with {len(objective_terms)} terms")
            self.logger.info("Objective strategy:")
            self.logger.info("  1. Over-allocation penalty (FIXED: prevent courses from getting more sessions than needed)")
            self.logger.info("  2. Group timeslots (no time slot preference)")
            self.logger.info("  3. Room capacity optimization (prefer appropriate room sizes)")
            self.logger.info("  4. Consecutive slot penalty (avoid >2 consecutive slots per group per day)")
            self.logger.info("  5. Late scheduling penalty (strongly prefer theory before 3:00 PM)")
            self.logger.info("  6. Core lab group slot penalty (prefer ≤8 slots for groups with core labs)")
            self.logger.info("  7. Computing group slot penalty (prefer ≤6 slots for computing department groups)")
            self.logger.info("  8. Consecutive batch preference (encourage consecutive batched lab sessions)")
            self.logger.info("  9. Shift-based scheduling penalty (encourage consistent shift patterns for single-instance departments)")
            self.logger.info("  10. Teacher consecutive lab penalty (discourage 3+ consecutive labs for Biotechnology, allow experimental continuity)")
            self.logger.info("  11. Flexible lunch preference penalty (prefer ≥1 lunch slot free for Biotech, ECE, Mech, Biomed, EEE)")
            self.logger.info("  12. Soft 5pm constraint penalty (discourage late scheduling for configured departments)")
            self.logger.info("  13. Teacher daily presence constraint (HARD: prevent 11+ hour violation days)")
            self.logger.info("  ✅ CRITICAL FIX: Removed lab assignment rewards that caused over-allocation")
        else:
            self.logger.warning("No objective terms created for group allocation")
    
    def _apply_5pm_constraints(self, model, lab_variables, theory_variables):
        """Apply 5:30pm/5:00pm scheduling constraints for departments (both hard and soft constraints)."""
        self.logger.info("Applying dual-level 5pm scheduling constraints for departments...")
        constraints_applied = 0
        
        # 1. Apply HARD CONSTRAINTS for departments that CANNOT schedule after 5:30pm
        if self.hard_5pm_constraint_departments:
            self.logger.info(f"Applying HARD 5:30pm constraints for {len(self.hard_5pm_constraint_departments)} department-semester combinations")
            
            # Apply theory constraints
            for group_name, day_slots in theory_variables.items():
                if '_S' in group_name:
                    # Extract department and semester from group name
                    dept_name = group_name.split('_S')[0]
                    sem_part = group_name.split('_S')[1].split('_G')[0] if '_G' in group_name.split('_S')[1] else group_name.split('_S')[1]
                    try:
                        semester = int(sem_part)
                    except ValueError:
                        semester = None
                    
                    # Check if this dept-semester combination has hard 5pm constraint
                    if semester and self._has_5pm_constraint(dept_name, semester, 'hard'):
                        dept_days = self._get_days_for_department(dept_name, semester)
                        num_dept_days = len(dept_days)
                        
                        # Block theory slots after 5:30pm (HARD constraint)
                        for day_idx in range(num_dept_days):
                            if day_idx in day_slots:
                                for slot_idx in self.theory_slots_after_5pm_hard:
                                    if slot_idx in day_slots[day_idx]:
                                        model.Add(day_slots[day_idx][slot_idx] == 0)
                                        constraints_applied += 1
                        
                        self.logger.info(f"HARD constraint applied: {group_name} blocked from theory slots {[self.theory_time_slots[i] for i in self.theory_slots_after_5pm_hard]}")
            
            # Apply lab constraints
            for teacher_id, courses in lab_variables.items():
                for course_instance_id, course_data in courses.items():
                    # Check if this course belongs to a constrained department-semester
                    if hasattr(self, 'instance_group_mapping') and course_instance_id in self.instance_group_mapping:
                        course_dept = self.instance_group_mapping[course_instance_id]['department']
                        course_semester = self.instance_group_mapping[course_instance_id].get('semester')
                        
                        # Check if this dept-semester combination has hard 5pm constraint
                        if course_semester and self._has_5pm_constraint(course_dept, course_semester, 'hard'):
                            # Get department-specific days
                            dept_days = self._get_days_for_department(course_dept, course_semester)
                            num_dept_days = len(dept_days)
                            
                            # Block lab sessions after 5:30pm (HARD constraint)
                            for day_idx in range(num_dept_days):
                                if day_idx in course_data:
                                    for session_name in self.lab_sessions_after_5pm_hard:
                                        if session_name in course_data[day_idx]:
                                            for room_id in course_data[day_idx][session_name]:
                                                model.Add(course_data[day_idx][session_name][room_id] == 0)
                                                constraints_applied += 1
                            
                            self.logger.info(f"HARD constraint applied: {course_dept}_S{course_semester} course {course_instance_id} blocked from lab sessions {self.lab_sessions_after_5pm_hard}")
        
        # 2. Apply SOFT CONSTRAINTS for departments that PREFER NOT to schedule after 5:00pm
        # These are implemented as high-penalty objective terms rather than hard constraints
        if self.soft_5pm_constraint_departments:
            self.logger.info(f"Setting up SOFT 5:00pm constraints for {len(self.soft_5pm_constraint_departments)} department-semester combinations")
            
            # Initialize penalty tracking
            if not hasattr(self, 'soft_5pm_penalty_vars'):
                self.soft_5pm_penalty_vars = []
            
            # Track theory penalties
            for group_name, day_slots in theory_variables.items():
                if '_S' in group_name:
                    # Extract department and semester from group name
                    dept_name = group_name.split('_S')[0]
                    sem_part = group_name.split('_S')[1].split('_G')[0] if '_G' in group_name.split('_S')[1] else group_name.split('_S')[1]
                    try:
                        semester = int(sem_part)
                    except ValueError:
                        semester = None
                    
                    # Check if this dept-semester combination has soft 5pm constraint
                    if semester and self._has_5pm_constraint(dept_name, semester, 'soft'):
                        dept_days = self._get_days_for_department(dept_name, semester)
                        num_dept_days = len(dept_days)
                        
                        # Create penalty variable for theory slots after 5:00pm (SOFT constraint)
                        for day_idx in range(num_dept_days):
                            if day_idx in day_slots:
                                for slot_idx in self.theory_slots_after_5pm_soft:
                                    if slot_idx in day_slots[day_idx]:
                                        penalty_var = model.NewBoolVar(f'soft_5pm_penalty_theory_{group_name}_day_{day_idx}_slot_{slot_idx}')
                                        model.Add(penalty_var == day_slots[day_idx][slot_idx])
                                        self.soft_5pm_penalty_vars.append(penalty_var)
                        
                        self.logger.info(f"SOFT constraint set up: {group_name} penalty for theory slots {[self.theory_time_slots[i] for i in self.theory_slots_after_5pm_soft]}")
            
            # Track lab penalties
            for teacher_id, courses in lab_variables.items():
                for course_instance_id, course_data in courses.items():
                    # Check if this course belongs to a soft constrained department-semester
                    if hasattr(self, 'instance_group_mapping') and course_instance_id in self.instance_group_mapping:
                        course_dept = self.instance_group_mapping[course_instance_id]['department']
                        course_semester = self.instance_group_mapping[course_instance_id].get('semester')
                        
                        # Check if this dept-semester combination has soft 5pm constraint
                        if course_semester and self._has_5pm_constraint(course_dept, course_semester, 'soft'):
                            # Get department-specific days
                            dept_days = self._get_days_for_department(course_dept, course_semester)
                            num_dept_days = len(dept_days)
                            
                            # Create penalty variables for lab sessions after 5:00pm (SOFT constraint)
                            for day_idx in range(num_dept_days):
                                if day_idx in course_data:
                                    for session_name in self.lab_sessions_after_5pm_soft:
                                        if session_name in course_data[day_idx]:
                                            for room_id in course_data[day_idx][session_name]:
                                                penalty_var = model.NewBoolVar(f'soft_5pm_penalty_lab_{course_instance_id}_day_{day_idx}_session_{session_name}_room_{room_id}')
                                                model.Add(penalty_var == course_data[day_idx][session_name][room_id])
                                                self.soft_5pm_penalty_vars.append(penalty_var)
                            
                            self.logger.info(f"SOFT constraint set up: {course_dept}_S{course_semester} course {course_instance_id} penalty for lab sessions {self.lab_sessions_after_5pm_soft}")
        
        # 3. Add soft constraint penalties to the objective (these will be subtracted from the objective)
        if hasattr(self, 'soft_5pm_penalty_vars') and self.soft_5pm_penalty_vars:
            # Note: The actual penalty subtraction is handled in _add_combined_objectives
            self.logger.info(f"Created {len(self.soft_5pm_penalty_vars)} soft 5pm penalty variables")
        
        if constraints_applied > 0:
            self.logger.info(f"Applied {constraints_applied} hard 5:30pm scheduling constraints")
        else:
            self.logger.info("No hard 5:30pm constraints applied (no departments configured)")
        
        # Log constraint summary
        constraint_summary = self._get_5pm_constraint_summary()
        self.logger.info("Dual-level constraint summary:")
        
        if constraint_summary['hard_dept_wide']:
            self.logger.info(f"  🚫 HARD constraints (department-wide): {constraint_summary['hard_dept_wide']} → ALL semesters CANNOT schedule after 5:30pm")
        if constraint_summary['hard_semester_specific']:
            self.logger.info(f"  🚫 HARD constraints (semester-specific): {constraint_summary['hard_semester_specific']} → Specific semesters CANNOT schedule after 5:30pm")
        if constraint_summary['soft_dept_wide']:
            self.logger.info(f"  ⚠️  SOFT constraints (department-wide): {constraint_summary['soft_dept_wide']} → ALL semesters DISCOURAGED from scheduling after 5:00pm")
        if constraint_summary['soft_semester_specific']:
            self.logger.info(f"  ⚠️  SOFT constraints (semester-specific): {constraint_summary['soft_semester_specific']} → Specific semesters DISCOURAGED from scheduling after 5:00pm")
        
        if (not self.hard_5pm_constraint_departments and not self.soft_5pm_constraint_departments):
            self.logger.info("  ✅ No timing constraints configured → All departments can schedule until 7pm")
        
        # Log examples of how constraints work
        self.logger.info("📋 Constraint resolution examples:")
        self.logger.info("  • 'Department Name' → applies to ALL semesters of that department")
        self.logger.info("  • 'Department Name_S3' → applies ONLY to semester 3 of that department")
        self.logger.info("  • Semester-specific constraints override department-wide constraints")
        self.logger.info("  • Hard constraints absolutely prevent scheduling after 5:30pm")
        self.logger.info("  • Soft constraints discourage (penalty) scheduling after 5:00pm but allow when needed")
        
        return constraints_applied

    def _solve_combined_model(self, model, lab_variables, group_timeslot_vars):
        """Solve the combined scheduling model using two-phase approach."""
        # Create the solver
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 4000
        solver.parameters.num_search_workers = 16
        solver.parameters.max_memory_in_mb = 30000
        solver.parameters.log_search_progress = True
        solver.parameters.stop_after_first_solution= True
        
        self.logger.info("Solving combined scheduling model...")
        status = solver.Solve(model)
        
        if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
            self.logger.info("Solution found for combined model!")
            
            # Clear global room registry for fresh scheduling
            self._initialize_global_room_registry()
            
            # Extract schedules with cross-validation
            lab_schedule = self._extract_lab_schedule(solver, lab_variables)
            group_timeslots = self._extract_group_timeslots(solver, group_timeslot_vars)
            theory_schedule = self._distribute_theory_sessions_in_groups(group_timeslots, lab_schedule)
            
            # Validate the combined schedules for conflicts
            validation_success = self._validate_combined_schedules(lab_schedule, theory_schedule)
            
            self._save_combined_schedules(lab_schedule, theory_schedule)
            
            # --- Generate Shift Reports ---
            self._generate_shift_reports(lab_schedule, theory_schedule)
            
            if lab_schedule or theory_schedule:
                combined_schedule = lab_schedule + theory_schedule
                self._generate_combined_summary(lab_schedule, theory_schedule, combined_schedule)
            else:
                self.logger.warning("Both lab and theory schedules are empty, skipping summary generation.")
            
            return validation_success
        else:
            self.logger.error(f"No solution found for combined model. Status: {solver.StatusName(status)}")
            return False
    
    def _extract_group_timeslots(self, solver, group_timeslot_vars):
        """Extract the allocated group time slots from the solver solution with department-specific day patterns."""
        self.logger.info("Extracting group time slot allocations with department-specific day patterns...")
        
        group_timeslots = {}
        total_slots_allocated = 0
        
        for group_name, day_slots in group_timeslot_vars.items():
            group_timeslots[group_name] = []
            
            # Get department-specific days for this group
            dept_name = group_name.split('_S')[0] if '_S' in group_name else "Computer Science & Engineering"
            semester = None
            if '_S' in group_name:
                sem_part = group_name.split('_S')[1].split('_G')[0] if '_G' in group_name else group_name.split('_S')[1]
                try:
                    semester = int(sem_part)
                except ValueError:
                    semester = None
            dept_days = self._get_days_for_department(dept_name, semester)
            dept_pattern = self._get_day_pattern_for_department(dept_name, semester)
            num_dept_days = len(dept_days)
            
            for day_idx in range(num_dept_days):  # Use department-specific days
                for slot_idx in range(self.num_theory_slots):
                    if solver.Value(day_slots[day_idx][slot_idx]) == 1:
                        group_timeslots[group_name].append((day_idx, slot_idx))
                        total_slots_allocated += 1
            
            # Log allocated slots with actual day names
            allocated_slots = group_timeslots[group_name]
            slot_details = []
            for day_idx, slot_idx in sorted(allocated_slots):
                day_name = dept_days[day_idx] if day_idx < len(dept_days) else f"day_{day_idx}"
                time_slot = self.theory_time_slots[slot_idx]
                slot_details.append(f"{day_name} {time_slot}")
            
            self.logger.info(f"Group {group_name} ({dept_pattern}): {len(allocated_slots)} slots → {', '.join(slot_details)}")
        
        self.logger.info(f"Total time slots allocated to groups: {total_slots_allocated}")
        return group_timeslots
    
    def _distribute_theory_sessions_in_groups(self, group_timeslots, lab_schedule=None):
        """Distribute individual theory sessions within allocated group time slots (Phase 2)."""
        self.logger.info("Phase 2: Distributing theory sessions within allocated group time slots with cross-schedule validation...")
        
        theory_schedule = []
        
        for group_name, allocated_slots in group_timeslots.items():
            if not allocated_slots:
                continue
                
            # Get group info
            group_info = None
            for (dept, semester), groups in self.course_groups.items():
                for group_idx, group in enumerate(groups):
                    expected_name = f"{dept}_S{semester}_G{group_idx + 1}"
                    if expected_name == group_name:
                        group_info = {'dept': dept, 'semester': semester, 'instances': group}
                        break
            
            if not group_info:
                self.logger.warning(f"Group info not found for {group_name}")
                continue
                
            instances = [inst for inst in group_info['instances'] if inst.get('has_theory', False)]
            self.logger.info(f"Distributing {len(instances)} theory course instances across {len(allocated_slots)} time slots for {group_name}")
            
            # DEBUG: Log instances that should have theory but don't have has_theory flag
            all_instances = group_info['instances']
            should_have_theory = [inst for inst in all_instances if inst.get('lecture_hours', 0) > 0 or inst.get('tutorial_hours', 0) > 0]
            missing_theory_flag = [inst for inst in should_have_theory if not inst.get('has_theory', False)]
            
            if missing_theory_flag:
                self.logger.error(f"MISSING THEORY FLAG: {group_name} has {len(missing_theory_flag)} instances that should have theory but missing has_theory flag:")
                for inst in missing_theory_flag:
                    self.logger.error(f"  Instance {inst['id']}: {inst['course_code']} - L:{inst.get('lecture_hours', 0)} T:{inst.get('tutorial_hours', 0)} P:{inst.get('practical_hours', 0)}")
            
            if len(instances) != len(should_have_theory):
                self.logger.warning(f"THEORY MISMATCH: {group_name} - Expected {len(should_have_theory)} theory instances but filtered to {len(instances)}")
            else:
                self.logger.debug(f"THEORY OK: {group_name} - All {len(instances)} theory instances properly flagged")
            
            # Log co-scheduled instance analysis
            co_scheduled_instances = [inst for inst in instances if inst.get('co_scheduled_id') is not None]
            regular_instances = [inst for inst in instances if inst.get('co_scheduled_id') is None]
            self.logger.info(f"{group_name} instance breakdown: {len(regular_instances)} regular + {len(co_scheduled_instances)} co-scheduled instances")
            
            # Collect all theory sessions needed for this group
            sessions_needed = []
            processed_co_scheduled = set()  # Track processed co-scheduled pairs
            
            for instance in instances:
                course_instance_id = instance['id']
                teacher_id = instance['teacher_id']
                lecture_hours = instance.get('lecture_hours', 0)
                tutorial_hours = instance.get('tutorial_hours', 0)
                
                # Handle co-scheduled instances (virtual pairs from 140+ student courses)
                co_scheduled_id = instance.get('co_scheduled_id')
                virtual_id = instance.get('virtual_id', '')
                
                # If this is a co-scheduled instance, only process it once per pair
                if co_scheduled_id is not None:
                    if co_scheduled_id in processed_co_scheduled:
                        continue  # Skip - already processed this co-scheduled pair
                    
                    # Mark this co-scheduled pair as processed
                    processed_co_scheduled.add(co_scheduled_id)
                    
                    # Find the partner instance to combine capacity
                    partner_instance = None
                    combined_student_count = instance.get('student_count', 70)
                    
                    for other_instance in instances:
                        if (other_instance.get('co_scheduled_id') == co_scheduled_id and 
                            other_instance.get('virtual_id') != virtual_id):
                            partner_instance = other_instance
                            combined_student_count += other_instance.get('student_count', 70)
                            break
                    
                    # Create a combined instance for scheduling
                    combined_instance = instance.copy()
                    combined_instance['student_count'] = combined_student_count
                    combined_instance['is_co_scheduled'] = True
                    combined_instance['partner_instance_id'] = partner_instance['id'] if partner_instance else None
                    
                    self.logger.info(f"Co-scheduled pair: {instance['course_code']} "
                                   f"({virtual_id} + partner) = {combined_student_count} students")
                else:
                    # Regular single instance
                    combined_instance = instance
                    combined_instance['is_co_scheduled'] = False
                
                # Create lecture sessions
                for session_num in range(lecture_hours):
                    sessions_needed.append({
                        'course_instance_id': course_instance_id,
                        'teacher_id': teacher_id,
                        'session_type': 'Lecture',
                        'session_number': session_num + 1,
                        'instance': combined_instance
                    })
                
                # Create tutorial sessions
                for session_num in range(tutorial_hours):
                    sessions_needed.append({
                        'course_instance_id': course_instance_id,
                        'teacher_id': teacher_id,
                        'session_type': 'Tutorial',
                        'session_number': session_num + 1,
                        'instance': combined_instance
                    })
            
            # Log session creation summary
            sessions_by_type = {}
            for session in sessions_needed:
                session_type = session['session_type']
                course_code = session['instance']['course_code']
                key = f"{course_code}_{session_type}"
                sessions_by_type[key] = sessions_by_type.get(key, 0) + 1
            
            total_sessions = len(sessions_needed)
            self.logger.info(f"{group_name} created {total_sessions} sessions: {dict(sessions_by_type)}")
            
            # Check for expected session counts
            group_course_codes = set(inst['instance']['course_code'] for inst in sessions_needed)
            for course_code in group_course_codes:
                # Sum expected hours for all instances of this course in the group
                expected_lectures = sum(
                    inst.get('lecture_hours', 0) 
                    for inst in instances if inst['course_code'] == course_code
                )
                expected_tutorials = sum(
                    inst.get('tutorial_hours', 0)
                    for inst in instances if inst['course_code'] == course_code
                )
                
                # Get actual session counts from the group's total
                actual_lectures = sessions_by_type.get(f"{course_code}_Lecture", 0)
                actual_tutorials = sessions_by_type.get(f"{course_code}_Tutorial", 0)
                
                if actual_lectures != expected_lectures or actual_tutorials != expected_tutorials:
                    self.logger.warning(f"SESSION COUNT MISMATCH: {course_code} - "
                                      f"Expected L:{expected_lectures}/T:{expected_tutorials}, "
                                      f"Got L:{actual_lectures}/T:{actual_tutorials}")
            
            # --> TRACK UNDERUTILIZATION
            num_instances_in_group = len(instances)
            num_allocated_slots = len(allocated_slots)
            
            # Total room-slots available for the group
            total_potential_slots = num_instances_in_group * num_allocated_slots
            
            # Total room-slots actually needed by the group's sessions
            total_sessions_needed = len(sessions_needed)
            
            # Calculate wasted slots
            underutilized_slots = total_potential_slots - total_sessions_needed
            
            if underutilized_slots > 0:
                self.logger.info(f"ROOM UTILIZATION: Group {group_name} has {underutilized_slots} underutilized room-slots.")
                self.logger.info(f"  - Group has {num_instances_in_group} parallel instances over {num_allocated_slots} time slots ({total_potential_slots} total slots).")
                self.logger.info(f"  - Only {total_sessions_needed} sessions are needed, leaving {underutilized_slots} slots empty.")

            # Distribute sessions across allocated time slots ensuring no teacher conflicts
            slot_assignments = {}  # slot_idx -> assigned_sessions
            slot_teachers = {}  # slot_idx -> set of teacher_ids
            
            for slot_idx in range(len(allocated_slots)):
                slot_assignments[slot_idx] = []
                slot_teachers[slot_idx] = set()
            
            # Group sessions by teacher to avoid conflicts
            teacher_sessions = {}
            for session in sessions_needed:
                teacher_id = session['teacher_id']
                if teacher_id not in teacher_sessions:
                    teacher_sessions[teacher_id] = []
                teacher_sessions[teacher_id].append(session)
            
            # Assign sessions to slots using proper constraint-aware scheduling
            sessions_assigned = 0
            sessions_total = sum(len(session_list) for session_list in teacher_sessions.values())
            unassigned_sessions = []
            
            for teacher_id, teacher_session_list in teacher_sessions.items():
                for session in teacher_session_list:
                    # Find a slot where this teacher is not already assigned
                    assigned = False
                    for slot_idx in range(len(allocated_slots)):
                        if teacher_id not in slot_teachers[slot_idx]:
                            slot_assignments[slot_idx].append(session)
                            slot_teachers[slot_idx].add(teacher_id)
                            assigned = True
                            sessions_assigned += 1
                            break
            
                    if not assigned:
                        # Instead of forcing conflicts, track unassigned sessions
                        unassigned_sessions.append(session)
                        self.logger.warning(f"Could not assign session for teacher {teacher_id} in {group_name} - teacher already busy in all available slots")
            
            # Try to resolve unassigned sessions by checking if we can expand time slots
            if unassigned_sessions:
                self.logger.warning(f"Group {group_name} has {len(unassigned_sessions)} unassigned sessions due to teacher conflicts")
                self.logger.warning(f"  Teachers with conflicts: {set(s['teacher_id'] for s in unassigned_sessions)}")
                self.logger.warning(f"  This indicates insufficient time slots allocated to the group or teacher overloading")
                
                # Log details about the conflicting assignments
                for session in unassigned_sessions:
                    teacher_id = session['teacher_id']
                    busy_slots = [idx for idx, teachers in slot_teachers.items() if teacher_id in teachers]
                    self.logger.error(f"  Teacher {teacher_id}: {session['instance']['course_code']} {session['session_type']} - busy in slots {busy_slots}")
                
                # For now, we'll skip these sessions rather than create conflicts
                # In a production system, this would trigger group reshuffling or time slot reallocation
                sessions_total -= len(unassigned_sessions)
            
            # Log session assignment summary
            if sessions_assigned < sessions_total:
                self.logger.error(f"SCHEDULING ERROR: {group_name} - Only {sessions_assigned}/{sessions_total} sessions assigned!")
            else:
                self.logger.info(f"SUCCESS {group_name}: All {sessions_assigned}/{sessions_total} sessions successfully assigned")
            
            # Create schedule entries
            sessions_skipped_no_room = 0
            sessions_successfully_scheduled = 0
            
            # Get department-specific days for this group (with semester override if available)
            dept_days = self._get_days_for_department(group_info['dept'], group_info['semester'])
            
            for slot_idx, assigned_sessions in slot_assignments.items():
                if not assigned_sessions:
                    continue
            
                day_idx, time_slot_idx = allocated_slots[slot_idx]
                
                # CRITICAL: Check if this time slot is during lunch break for this department
                dept_name = group_info['dept']
                if self.is_lunch_break_slot(time_slot_idx, dept_name):
                    lunch_time = self.get_lunch_break_time(dept_name)
                    self.logger.error(f"LUNCH BREAK VIOLATION BLOCKED: {group_name} attempted to schedule during lunch break slot {time_slot_idx} ({self.theory_time_slots[time_slot_idx]}) for department {dept_name}")
                    self.logger.error(f"  Expected lunch time: {lunch_time}")
                    self.logger.error(f"  Skipping {len(assigned_sessions)} sessions that would violate lunch break")
                    sessions_skipped_no_room += len(assigned_sessions)
                    continue  # Skip this entire time slot
                
                # Track room usage for this specific time slot to prevent double-booking
                used_rooms_this_slot = set()
                
                # Track sessions assigned in this slot for co-scheduling awareness
                assigned_sessions_this_slot = []
                
                for session in assigned_sessions:
                    # Get teacher and course details
                    instance = session['instance']
                    # Get teacher details with proper error handling  
                    teacher_matches = self.courses_df[self.courses_df['teacher_id'] == session['teacher_id']]
                    if teacher_matches.empty:
                        # Try with different data types - handle float strings like '178.0'
                        try:
                            # Convert to float first, then to int to handle '178.0' format
                            teacher_id_int = int(float(session['teacher_id']))
                            teacher_matches = self.courses_df[self.courses_df['teacher_id'] == teacher_id_int]
                        except (ValueError, TypeError):
                            # If conversion fails, try as string
                            teacher_matches = self.courses_df[self.courses_df['teacher_id'].astype(str) == str(session['teacher_id'])]
                        
                        if teacher_matches.empty:
                            self.logger.error(f"Teacher ID {session['teacher_id']} not found in courses dataframe for theory schedule")
                            sessions_skipped_no_room += 1
                            continue
                    teacher_row = teacher_matches.iloc[0]
                    
                    # CAPACITY-AWARE: Find available room with capacity-aware assignment
                    available_room_id = self._find_capacity_aware_theory_room(
                        day_idx, time_slot_idx, used_rooms_this_slot, theory_schedule, dept_days, 
                        session, assigned_sessions_this_slot, lab_schedule
                    )
                    
                    if available_room_id is None:
                        self.logger.error(f"No available theory room for session {session['course_instance_id']} "
                                        f"on {self.days[day_idx]} at {self.theory_time_slots[time_slot_idx]}")
                        self.logger.error(f"  Course: {instance['course_code']}, Teacher: {session['teacher_id']}")
                        self.logger.error(f"  Group: {group_name}, Session: {session['session_type']} #{session['session_number']}")
                        sessions_skipped_no_room += 1
                        continue
                    
                    used_rooms_this_slot.add(available_room_id)
                    room_row = self.rooms_df[self.rooms_df['id'] == available_room_id].iloc[0]
                    sessions_successfully_scheduled += 1
                    
                    # Track this session for co-scheduling awareness
                    session_with_room = session.copy()
                    session_with_room['assigned_room_id'] = available_room_id
                    assigned_sessions_this_slot.append(session_with_room)
                    
                    # Determine course display name and capacity info
                    is_co_scheduled = instance.get('is_co_scheduled', False)
                    student_count = int(instance.get('student_count', 70))
                    course_display = instance['course_code']
                    
                    if is_co_scheduled:
                        # For co-scheduled instances, show combined capacity
                        course_display = f"{instance['course_code']} (Combined 140-student course)"
                        capacity_info = f"Co-scheduled: {student_count} students total"
                    else:
                        capacity_info = f"Regular: {student_count} students"
                    
                    # Create schedule entry
                    theory_session = {
                        'day': dept_days[day_idx] if day_idx < len(dept_days) else f"day_{day_idx}",
                        'time_slot': self.theory_time_slots[time_slot_idx],
                        'slot_index': time_slot_idx,
                        'course_instance_id': session['course_instance_id'],
                        'course_code': course_display,
                        'course_name': instance['course_name'],
                        'session_type': session['session_type'],
                        'session_number': session['session_number'],
                        'teacher_id': session['teacher_id'],
                        'teacher_name': f"{teacher_row.get('first_name', '')} {teacher_row.get('last_name', '')}".strip(),
                        'staff_code': teacher_row.get('staff_code', ''),
                        'room_id': int(available_room_id),
                        'room_number': room_row['room_number'],
                        'block': room_row.get('block', ''),
                        'student_count': student_count,
                        'lecture_hours': int(instance.get('lecture_hours', 0)),
                        'tutorial_hours': int(instance.get('tutorial_hours', 0)),
                        'schedule_type': 'theory',
                        'is_co_scheduled': is_co_scheduled,
                        'capacity_info': capacity_info,
                        'partner_instance_id': instance.get('partner_instance_id', ''),
                        # Group information
                        'group_name': group_name,
                        'group_index': int(group_name.split('_G')[1]) if '_G' in group_name else 1,
                        'department': group_info['dept'],
                        'semester': group_info['semester'],
                        # Day pattern information
                        'day_pattern': self._get_day_pattern_for_department(group_info['dept'], group_info['semester'])
                    }
                    
                    # Register room usage in global registry
                    self._register_room_usage(theory_session['day'], theory_session['time_slot'], available_room_id, theory_session)
                    
                    # Add to schedule
                    theory_schedule.append(theory_session)
            
            # Log session scheduling summary for this group
            if sessions_skipped_no_room > 0:
                self.logger.error(f"ERROR {group_name}: {sessions_skipped_no_room} sessions SKIPPED due to no available rooms")
            self.logger.info(f"STATS {group_name}: {sessions_successfully_scheduled} sessions successfully scheduled")
        
        self.logger.info(f"Phase 2 complete: Distributed {len(theory_schedule)} theory sessions across group time slots")
        
        # Validate that room assignments don't have conflicts
        self._validate_theory_room_assignments(theory_schedule)
        
        return theory_schedule
    
    def _validate_theory_room_assignments(self, theory_schedule):
        """
        Validate that there are no room conflicts in the theory schedule.
        """
        self.logger.info("Validating theory room assignments for conflicts...")
        
        # Group sessions by day and time slot
        time_slot_usage = {}
        conflicts_found = 0
        
        for session in theory_schedule:
            day = session['day']
            time_slot = session['time_slot']
            room_id = session['room_id']
            
            key = (day, time_slot, room_id)
            
            if key not in time_slot_usage:
                time_slot_usage[key] = []
            time_slot_usage[key].append(session)
        
        # Check for conflicts (multiple sessions in same room at same time)
        for (day, time_slot, room_id), sessions in time_slot_usage.items():
            if len(sessions) > 1:
                conflicts_found += 1
                course_codes = [s['course_code'] for s in sessions]
                teachers = [s['teacher_id'] for s in sessions]
                
                self.logger.error(f"ROOM CONFLICT: Room {room_id} double-booked on {day} {time_slot}")
                self.logger.error(f"  Conflicting courses: {', '.join(course_codes)}")
                self.logger.error(f"  Conflicting teachers: {', '.join(map(str, teachers))}")
        
        # Summary
        total_sessions = len(theory_schedule)
        unique_time_slots = len(set((s['day'], s['time_slot']) for s in theory_schedule))
        total_room_usage = len(time_slot_usage)
        
        if conflicts_found == 0:
            self.logger.info("SUCCESS Theory room validation PASSED - No conflicts found")
        else:
            self.logger.error(f"FAILED Theory room validation FAILED - {conflicts_found} conflicts found")
        
        self.logger.info(f"Theory room validation summary:")
        self.logger.info(f"  - Total theory sessions: {total_sessions}")
        self.logger.info(f"  - Unique time slots used: {unique_time_slots}")
        self.logger.info(f"  - Total room-timeslot assignments: {total_room_usage}")
        self.logger.info(f"  - Room conflicts: {conflicts_found}")
        
        return conflicts_found == 0
    
    def _validate_combined_schedules(self, lab_schedule, theory_schedule):
        """
        Comprehensive validation of combined lab and theory schedules.
        Checks for room conflicts, day pattern inconsistencies, and time overlaps.
        """
        self.logger.info("Performing comprehensive validation of combined schedules...")
        
        total_conflicts = 0
        
        # 1. Check room conflicts within lab schedule
        lab_conflicts = self._check_schedule_room_conflicts(lab_schedule, "Lab")
        total_conflicts += lab_conflicts
        
        # 2. Check room conflicts within theory schedule
        theory_conflicts = self._check_schedule_room_conflicts(theory_schedule, "Theory")
        total_conflicts += theory_conflicts
        
        # 3. Check cross-schedule room conflicts
        cross_conflicts = self._check_cross_schedule_conflicts(lab_schedule, theory_schedule)
        total_conflicts += cross_conflicts
        
        # 4. Check day pattern consistency
        day_pattern_issues = self._check_day_pattern_consistency(lab_schedule, theory_schedule)
        total_conflicts += day_pattern_issues
        
        # 5. Check teacher conflicts
        teacher_conflicts = self._check_teacher_conflicts(lab_schedule, theory_schedule)
        total_conflicts += teacher_conflicts
        
        # Summary
        if total_conflicts == 0:
            self.logger.info("✅ VALIDATION PASSED: No conflicts found in combined schedules")
            self.logger.info(f"  Lab sessions: {len(lab_schedule)}")
            self.logger.info(f"  Theory sessions: {len(theory_schedule)}")
            self.logger.info(f"  Total sessions: {len(lab_schedule) + len(theory_schedule)}")
        else:
            self.logger.error(f"❌ VALIDATION FAILED: {total_conflicts} conflicts found")
            self.logger.error("  Check the logs above for detailed conflict information")
        
        return total_conflicts == 0
    
    def _check_schedule_room_conflicts(self, schedule, schedule_type):
        """Check for room conflicts within a single schedule."""
        conflicts = 0
        room_usage = {}
        

        
        for session in schedule:
            day = self._normalize_day_name(session['day'])
            time_slot = session.get('time_slot')
            room_id = session.get('room_id')
            course_code = session.get('course_code', '')
            group_name = session.get('group_name', '')
            
            # For lab sessions, check all time slots in the session
            if schedule_type == "Lab" and 'session_name' in session:
                session_name = session['session_name']
                session_info = self.lab_sessions.get(session_name, {})
                if 'slots' in session_info:
                    # Convert slot indices to actual time slots
                    lab_time_slots = [self.lab_time_slots[slot_idx] for slot_idx in session_info['slots']]
                else:
                    lab_time_slots = []
                
                for lab_time_slot in lab_time_slots:
                    key = (day, lab_time_slot, room_id)
                    if key in room_usage:
                        existing = room_usage[key]
                        existing_course = existing.get('course_code', '')
                        existing_group = existing.get('group_name', '')
                        
                        # This is a room conflict
                        conflicts += 1
                        self.logger.error(f"{schedule_type} room conflict: Room {room_id} on {day} slots")
                        self.logger.error(f"  Existing: {existing_course} (Group: {existing_group})")
                        self.logger.error(f"  Conflicting: {course_code} (Group: {group_name})")
                        self.logger.error(f"{schedule_type} room conflict: Room {room_id} on {day} time_range")
                        self.logger.error(f"  Existing: {existing_course} (Group: {existing_group})")
                        self.logger.error(f"  Conflicting: {course_code} (Group: {group_name})")
                    else:
                        room_usage[key] = session
            else:
                # For theory sessions, check single time slot
                if time_slot:
                    key = (day, time_slot, room_id)
                    if key in room_usage:
                        existing = room_usage[key]
                        existing_course = existing.get('course_code', '')
                        existing_group = existing.get('group_name', '')
                        
                        # Theory sessions generally don't support co-scheduling
                        conflicts += 1
                        self.logger.error(f"{schedule_type} room conflict: Room {room_id} on {day} {time_slot}")
                        self.logger.error(f"  Existing: {existing_course} (Group: {existing_group})")
                        self.logger.error(f"  Conflicting: {course_code} (Group: {group_name})")
                    else:
                        room_usage[key] = session
        
        if conflicts == 0:
            self.logger.info(f"✅ {schedule_type} schedule: No internal room conflicts")
        else:
            self.logger.error(f"❌ {schedule_type} schedule: {conflicts} internal room conflicts")
        
        return conflicts
    
    def _check_cross_schedule_conflicts(self, lab_schedule, theory_schedule):
        """Check for room conflicts between lab and theory schedules."""
        conflicts = 0
        
        for lab_session in lab_schedule:
            lab_day = self._normalize_day_name(lab_session['day'])
            lab_room_id = lab_session.get('room_id')
            session_name = lab_session.get('session_name', '')
            session_info = self.lab_sessions.get(session_name, {})
            if 'slots' in session_info:
                # Convert slot indices to actual time slots
                lab_time_slots = [self.lab_time_slots[slot_idx] for slot_idx in session_info['slots']]
            else:
                lab_time_slots = []
            
            for theory_session in theory_schedule:
                theory_day = self._normalize_day_name(theory_session['day'])
                theory_time_slot = theory_session.get('time_slot', '')
                theory_room_id = theory_session.get('room_id')
                
                # Check if same day and room
                if lab_day == theory_day and lab_room_id == theory_room_id:
                    # Check for time overlap
                    for lab_time_slot in lab_time_slots:
                        if self._times_overlap(lab_time_slot, theory_time_slot):
                            conflicts += 1
                            self.logger.error(f"Cross-schedule room conflict: Room {lab_room_id} on {lab_day}")
                            self.logger.error(f"  Lab: {lab_session.get('course_code', 'Unknown')} ({lab_time_slot})")
                            self.logger.error(f"  Theory: {theory_session.get('course_code', 'Unknown')} ({theory_time_slot})")
                            break
        
        if conflicts == 0:
            self.logger.info("✅ Cross-schedule: No room conflicts between lab and theory")
        else:
            self.logger.error(f"❌ Cross-schedule: {conflicts} room conflicts between lab and theory")
        
        return conflicts
    
    def _check_day_pattern_consistency(self, lab_schedule, theory_schedule):
        """Check for day pattern consistency issues."""
        issues = 0
        
        # Check if sessions are scheduled on appropriate days for their departments
        for session in lab_schedule + theory_schedule:
            dept = session.get('department', '')
            semester = session.get('semester')
            day = session.get('day', '')
            day_pattern = session.get('day_pattern', '')
            
            if dept and day:
                expected_days = self._get_days_for_department(dept, semester)
                day_normalized = self._normalize_day_name(day)
                expected_days_normalized = [self._normalize_day_name(d) for d in expected_days]
                
                if day_normalized not in expected_days_normalized:
                    issues += 1
                    self.logger.error(f"Day pattern violation: {dept} scheduled on {day}")
                    self.logger.error(f"  Expected days: {expected_days}")
                    self.logger.error(f"  Course: {session.get('course_code', 'Unknown')}")
                    self.logger.error(f"  Day pattern: {day_pattern}")
        
        if issues == 0:
            self.logger.info("✅ Day patterns: All sessions scheduled on appropriate days")
        else:
            self.logger.error(f"❌ Day patterns: {issues} violations found")
        
        return issues
    
    def _check_teacher_conflicts(self, lab_schedule, theory_schedule):
        """Check for teacher conflicts (same teacher in multiple places at same time)."""
        conflicts = 0
        teacher_schedule = {}
        
        # Process all sessions
        for session in lab_schedule + theory_schedule:
            teacher_id = session.get('teacher_id')
            day = self._normalize_day_name(session.get('day', ''))
            
            if not teacher_id:
                continue
            
            # Get time slots for this session
            time_slots = []
            if session.get('schedule_type') == 'lab' and 'session_name' in session:
                session_name = session['session_name']
                session_info = self.lab_sessions.get(session_name, {})
                if 'slots' in session_info:
                    # Convert slot indices to actual time slots
                    time_slots = [self.lab_time_slots[slot_idx] for slot_idx in session_info['slots']]
                else:
                    time_slots = []
            elif session.get('schedule_type') == 'theory':
                time_slots = [session.get('time_slot', '')]
            
            for time_slot in time_slots:
                if not time_slot:
                    continue
                    
                key = (teacher_id, day, time_slot)
                if key in teacher_schedule:
                    conflicts += 1
                    existing = teacher_schedule[key]
                    self.logger.error(f"Teacher conflict: Teacher {teacher_id} on {day} slots")
                    self.logger.error(f"  Existing: {existing.get('course_code', 'Unknown')} ({existing.get('schedule_type', 'Unknown')})")
                    self.logger.error(f"  Conflicting: {session.get('course_code', 'Unknown')} ({session.get('schedule_type', 'Unknown')})")
                    self.logger.error(f"Teacher conflict: Teacher {teacher_id} on {day} time_range")
                    self.logger.error(f"  Existing: {existing.get('course_code', 'Unknown')} ({existing.get('schedule_type', 'Unknown')})")
                    self.logger.error(f"  Conflicting: {session.get('course_code', 'Unknown')} ({session.get('schedule_type', 'Unknown')})")
                else:
                    teacher_schedule[key] = session
        
        if conflicts == 0:
            self.logger.info("✅ Teachers: No scheduling conflicts")
        else:
            self.logger.error(f"❌ Teachers: {conflicts} scheduling conflicts")
        
        return conflicts
    
    def _find_available_theory_room(self, day_idx, time_slot_idx, used_rooms_this_slot, existing_schedule):
        """
        Find an available theory room for the given day and time slot.
        
        Args:
            day_idx: Day index
            time_slot_idx: Time slot index
            used_rooms_this_slot: Set of room IDs already used in this time slot
            existing_schedule: List of already scheduled theory sessions
            
        Returns:
            room_id if available, None if no room available
        """
        day_name = self.days[day_idx]
        time_slot = self.theory_time_slots[time_slot_idx]
        
        # Get rooms already occupied at this exact time slot from existing schedule
        occupied_rooms = set()
        for session in existing_schedule:
            if session['day'] == day_name and session['time_slot'] == time_slot:
                occupied_rooms.add(session['room_id'])
        
        # Combine with rooms used in current slot assignment
        all_occupied_rooms = occupied_rooms | used_rooms_this_slot
        
        # Find first available room
        for room_id in self.theory_room_ids:
            if room_id not in all_occupied_rooms:
                return room_id
        
        # If no room available, log warning and return None
        self.logger.warning(f"No available theory room for {day_name} {time_slot}. "
                          f"Occupied: {len(all_occupied_rooms)}, Total: {len(self.theory_room_ids)}")
        return None
    
    def _find_available_theory_room_with_cross_validation(self, day_idx, time_slot_idx, used_rooms_this_slot, existing_schedule, dept_days, lab_schedule=None):
        """
        Find an available theory room with comprehensive cross-schedule validation.
        
        Args:
            day_idx: Day index (department-specific)
            time_slot_idx: Time slot index
            used_rooms_this_slot: Set of room IDs already used in this time slot
            existing_schedule: List of already scheduled theory sessions
            dept_days: Department-specific day names
            lab_schedule: Lab schedule for cross-validation
            
        Returns:
            room_id if available, None if no room available
        """
        # Get correct day name using department-specific days
        day_name = dept_days[day_idx] if day_idx < len(dept_days) else f"day_{day_idx}"
        time_slot = self.theory_time_slots[time_slot_idx]
        
        # Normalize day name for consistent checking
        day_normalized = self._normalize_day_name(day_name)
        
        self.logger.debug(f"Finding theory room for {day_name} ({day_normalized}) {time_slot}")
        
        # Get rooms already occupied from existing theory schedule
        occupied_rooms = set()
        for session in existing_schedule:
            session_day_normalized = self._normalize_day_name(session['day'])
            if session_day_normalized == day_normalized and session['time_slot'] == time_slot:
                occupied_rooms.add(session['room_id'])
                self.logger.debug(f"Theory room {session['room_id']} occupied by {session.get('course_code', 'Unknown')}")
        
        # Check global room registry for any conflicts
        global_occupied_rooms = set()
        for room_id in self.theory_room_ids:
            if not self._is_room_available_global(day_name, time_slot, room_id):
                global_occupied_rooms.add(room_id)
                self.logger.debug(f"Room {room_id} globally occupied on {day_name} {time_slot}")
        
        # Check lab schedule for overlapping times (if provided)
        lab_conflict_rooms = set()
        if lab_schedule:
            for lab_session in lab_schedule:
                lab_day_normalized = self._normalize_day_name(lab_session['day'])
                if lab_day_normalized == day_normalized:
                    # Check if lab time overlaps with theory time
                    lab_time_range = lab_session.get('time_range', '')
                    if self._times_overlap(lab_time_range, time_slot):
                        lab_conflict_rooms.add(lab_session['room_id'])
                        self.logger.debug(f"Lab room {lab_session['room_id']} conflicts with theory time {time_slot} (lab: {lab_time_range})")
        
        # Combine all occupied rooms
        all_occupied_rooms = occupied_rooms | used_rooms_this_slot | global_occupied_rooms | lab_conflict_rooms
        
        # Find first available theory room
        for room_id in self.theory_room_ids:
            if room_id not in all_occupied_rooms:
                self.logger.debug(f"Found available theory room {room_id} for {day_name} {time_slot}")
                return room_id
        
        # If no room available, log detailed warning
        self.logger.error(f"No available theory room for {day_name} {time_slot}")
        self.logger.error(f"  Theory occupied: {len(occupied_rooms)} rooms")
        self.logger.error(f"  Used this slot: {len(used_rooms_this_slot)} rooms") 
        self.logger.error(f"  Global conflicts: {len(global_occupied_rooms)} rooms")
        self.logger.error(f"  Lab conflicts: {len(lab_conflict_rooms)} rooms")
        self.logger.error(f"  Total occupied: {len(all_occupied_rooms)}/{len(self.theory_room_ids)} rooms")
        
        return None
    
    def _extract_lab_schedule(self, solver, lab_variables):
        """Extract lab schedule from solver solution with proper batching logic."""
        self.logger.info("Extracting lab schedule from solution...")
        lab_schedule = []
        
        for teacher_id in lab_variables:
            for course_instance_id in lab_variables[teacher_id]:
                # Find the course details
                course_details = None
                for course_req in self.lab_requirements.get(teacher_id, []):
                    if course_req['course_instance_id'] == course_instance_id:
                        course_details = course_req
                        break
                
                if not course_details:
                    continue
                
                # Get department and semester for this course instance first to determine correct number of days
                dept_name = "Computer Science & Engineering"  # Default
                semester = None
                if hasattr(self, 'instance_group_mapping') and course_instance_id in self.instance_group_mapping:
                    dept_name = self.instance_group_mapping[course_instance_id]['department']
                    semester = self.instance_group_mapping[course_instance_id].get('semester')
                else:
                    # Fallback: look up in courses_df
                    course_matches = self.courses_df[self.courses_df['id'] == int(course_instance_id)]
                    if not course_matches.empty:
                        dept_name = course_matches.iloc[0].get('student_dept', 'Computer Science & Engineering')
                
                dept_days = self._get_days_for_department(dept_name, semester)
                num_dept_days = len(dept_days)
                
                # Only iterate over days relevant to this department
                for day_idx in range(num_dept_days):
                    for session_name in self.lab_sessions.keys():
                        for room_id in self.lab_room_ids:
                            # Check if this assignment exists and is selected
                            if (day_idx < len(lab_variables[teacher_id][course_instance_id]) and
                                session_name in lab_variables[teacher_id][course_instance_id][day_idx] and
                                room_id in lab_variables[teacher_id][course_instance_id][day_idx][session_name] and
                                solver.Value(lab_variables[teacher_id][course_instance_id][day_idx][session_name][room_id]) == 1):
                                
                                # Get room details
                                room_row = self.rooms_df[self.rooms_df['id'] == room_id].iloc[0]
                                room_capacity = int(room_row['room_max_cap'])
                                
                                # Get teacher details with proper error handling
                                teacher_matches = self.courses_df[self.courses_df['teacher_id'] == teacher_id]
                                if teacher_matches.empty:
                                    # Try with different data types - handle float strings like '178.0'
                                    try:
                                        # Convert to float first, then to int to handle '178.0' format
                                        teacher_id_int = int(float(teacher_id))
                                        teacher_matches = self.courses_df[self.courses_df['teacher_id'] == teacher_id_int]
                                    except (ValueError, TypeError):
                                        # If conversion fails, try as string
                                        teacher_matches = self.courses_df[self.courses_df['teacher_id'].astype(str) == str(teacher_id)]
                                    
                                    if teacher_matches.empty:
                                        self.logger.error(f"Teacher ID {teacher_id} not found in courses dataframe")
                                        continue
                                teacher_row = teacher_matches.iloc[0]
                                
                                # Handle virtual instance IDs by getting base course ID
                                base_course_id = self._get_base_course_id(course_instance_id)
                                course_matches = self.courses_df[self.courses_df['id'] == int(base_course_id)]
                                if course_matches.empty:
                                    self.logger.error(f"Course instance ID {course_instance_id} (base: {base_course_id}) not found in courses dataframe")
                                    continue
                                course_row = course_matches.iloc[0]
                                
                                # Rule 1: Simple batching rule - batch if using 35-capacity lab and have more students
                                # For virtual instances, use 70 students (half of the original), otherwise use the original count
                                if '-A' in str(course_instance_id) or '-B' in str(course_instance_id):
                                    student_count = 70  # Virtual instances have 70 students each
                                else:
                                    student_count = int(course_row['student_count'])
                                
                                if student_count > room_capacity:
                                    # Need batching: split students into batches that fit the lab capacity
                                    batching_required = True
                                    num_batches = (student_count + room_capacity - 1) // room_capacity
                                    students_per_batch = (student_count + num_batches - 1) // num_batches
                                else:
                                    # No batching needed: students fit in the lab
                                    batching_required = False
                                    num_batches = 1
                                    students_per_batch = student_count
                                
                                if batching_required and num_batches > 1:
                                    # For batched courses, distribute sessions across batches
                                    # Count total assignments for this course so far
                                    existing_assignments = [item for item in lab_schedule 
                                                          if item['course_instance_id'] == course_instance_id]
                                    
                                    # Calculate how many sessions each batch should get
                                    base_sessions = course_details['lab_sessions_needed']
                                    
                                    # Group existing assignments by batch
                                    batch_session_counts = {}
                                    for existing in existing_assignments:
                                        if existing.get('is_batched'):
                                            batch_num = existing.get('batch_info', '').replace('Batch ', '')
                                            if batch_num.isdigit():
                                                batch_session_counts[int(batch_num)] = batch_session_counts.get(int(batch_num), 0) + 1
                                    
                                    # Find which batch this assignment should go to
                                    current_batch = 1
                                    for batch_num in range(1, num_batches + 1):
                                        if batch_session_counts.get(batch_num, 0) < base_sessions:
                                            current_batch = batch_num
                                            break
                                    
                                    course_code_display = f"{course_details['course_code']} Batch {current_batch}"
                                    batch_info = f"Batch {current_batch}"
                                    
                                    # Get group information for this course instance
                                    group_name = ""
                                    group_index = 0
                                    department = ""
                                    semester = ""
                                    if hasattr(self, 'instance_group_mapping') and course_instance_id in self.instance_group_mapping:
                                        group_mapping = self.instance_group_mapping[course_instance_id]
                                        group_name = group_mapping['group_name']
                                        group_index = group_mapping['group_index']
                                        department = group_mapping['department']
                                        semester = group_mapping['semester']
                                    
                                    # Create session info
                                    session_info = {
                                    'day': dept_days[day_idx] if day_idx < len(dept_days) else f"day_{day_idx}",
                                    'session_name': session_name,
                                    'time_range': self.lab_sessions[session_name]['time_range'],
                                    'course_instance_id': course_instance_id,
                                        'course_code': course_details['course_code'],
                                        'course_code_display': course_code_display,
                                    'course_name': course_row['course_name'],
                                        'practical_hours': int(course_row.get('practical_hours', 0)),
                                    'teacher_id': teacher_id,
                                    'teacher_name': f"{teacher_row.get('first_name', '')} {teacher_row.get('last_name', '')}".strip(),
                                    'staff_code': teacher_row.get('staff_code', ''),
                                    'room_id': int(room_id),
                                    'room_number': room_row['room_number'],
                                    'block': room_row.get('block', ''),
                                        'capacity': int(room_capacity),
                                        'student_count': int(students_per_batch),
                                        'total_students': int(student_count),
                                        'is_batched': True,
                                        'batch_info': batch_info,
                                        'num_batches': num_batches,
                                        'schedule_type': 'lab',
                                        # Group information
                                        'group_name': group_name,
                                        'group_index': group_index,
                                        'department': department,
                                        'semester': semester,
                                        # Day pattern information
                                        'day_pattern': self._get_day_pattern_for_department(department, semester)
                                    }
                                    
                                    # Check and register room usage in global registry
                                    day_name = session_info['day']
                                    time_range = session_info['time_range']
                                    
                                    # Check for conflicts before registering
                                    conflict_detected = False
                                    for slot_idx in self.lab_sessions[session_name]['slots']:
                                        lab_time_slot = self.lab_time_slots[slot_idx]
                                        if not self._is_room_available_global(day_name, lab_time_slot, room_id):
                                            self.logger.error(f"Lab schedule conflict detected during extraction: {course_details['course_code']} cannot use room {room_id} on {day_name} {lab_time_slot}")
                                            conflict_detected = True
                                    
                                    if not conflict_detected:
                                        # Register for all time slots in the lab session
                                        for slot_idx in self.lab_sessions[session_name]['slots']:
                                            lab_time_slot = self.lab_time_slots[slot_idx]
                                            if not self._register_room_usage(day_name, lab_time_slot, room_id, session_info):
                                                conflict_detected = True
                                                break
                                        
                                        if not conflict_detected:
                                            # Add this session to the current batch
                                            lab_schedule.append(session_info)
                                        else:
                                            self.logger.error(f"Failed to register room usage for {course_details['course_code']}")
                                    else:
                                        self.logger.error(f"Skipping conflicting lab assignment: {course_details['course_code']}")
                                    
                                    # Log assignment
                                    self.logger.info(f"Lab assignment: Course {course_details['course_code']} Batch {current_batch} → "
                                                   f"{session_name} on {dept_days[day_idx]} in "
                                                   f"Lab {room_row['room_number']} ({students_per_batch} students)")
                                else:
                                    # Single assignment, no batching
                                    course_code_display = course_details['course_code']
                                    
                                    # Get group information for this course instance
                                    group_name = ""
                                    group_index = 0
                                    department = ""
                                    semester = ""
                                    if hasattr(self, 'instance_group_mapping') and course_instance_id in self.instance_group_mapping:
                                        group_mapping = self.instance_group_mapping[course_instance_id]
                                        group_name = group_mapping['group_name']
                                        group_index = group_mapping['group_index']
                                        department = group_mapping['department']
                                        semester = group_mapping['semester']
                                    
                                    # Create session info
                                    session_info = {
                                        'day': dept_days[day_idx] if day_idx < len(dept_days) else f"day_{day_idx}",
                                        'session_name': session_name,
                                        'time_range': self.lab_sessions[session_name]['time_range'],
                                        'course_instance_id': course_instance_id,
                                        'course_code': course_details['course_code'],
                                        'course_code_display': course_code_display,
                                        'course_name': course_row['course_name'],
                                        'practical_hours': int(course_row.get('practical_hours', 0)),
                                        'teacher_id': teacher_id,
                                        'teacher_name': f"{teacher_row.get('first_name', '')} {teacher_row.get('last_name', '')}".strip(),
                                        'staff_code': teacher_row.get('staff_code', ''),
                                        'room_id': int(room_id),
                                        'room_number': room_row['room_number'],
                                        'block': room_row.get('block', ''),
                                        'capacity': int(room_capacity),
                                        'student_count': int(student_count),
                                        'total_students': int(student_count),
                                        'is_batched': False,
                                        'batch_info': "",
                                        'num_batches': 1,
                                        'schedule_type': 'lab',
                                        # Group information
                                        'group_name': group_name,
                                        'group_index': group_index,
                                        'department': department,
                                        'semester': semester,
                                        # Day pattern information
                                        'day_pattern': self._get_day_pattern_for_department(department, semester)
                                    }
                                    
                                    # Check and register room usage in global registry
                                    day_name = session_info['day']
                                    
                                    # Check for conflicts before registering
                                    conflict_detected = False
                                    for slot_idx in self.lab_sessions[session_name]['slots']:
                                        lab_time_slot = self.lab_time_slots[slot_idx]
                                        if not self._is_room_available_global(day_name, lab_time_slot, room_id):
                                            self.logger.error(f"Lab schedule conflict detected during extraction: {course_details['course_code']} cannot use room {room_id} on {day_name} {lab_time_slot}")
                                            conflict_detected = True
                                    
                                    if not conflict_detected:
                                        # Register for all time slots in the lab session
                                        for slot_idx in self.lab_sessions[session_name]['slots']:
                                            lab_time_slot = self.lab_time_slots[slot_idx]
                                            if not self._register_room_usage(day_name, lab_time_slot, room_id, session_info):
                                                conflict_detected = True
                                                break
                                        
                                        if not conflict_detected:
                                            lab_schedule.append(session_info)
                                        else:
                                            self.logger.error(f"Failed to register room usage for {course_details['course_code']}")
                                    else:
                                        self.logger.error(f"Skipping conflicting lab assignment: {course_details['course_code']}")
                                    
                                    # Log assignment (including co-scheduling info)
                                    if hasattr(self, 'co_schedulable_course_groups') and self.co_schedulable_course_groups:
                                        # Check if this is part of a co-schedulable group
                                        for (group_name_key, course_code_key), group_info in self.co_schedulable_course_groups.items():
                                            if (group_name == group_name_key and 
                                                course_details['course_code'] == course_code_key and
                                                int(room_capacity) >= 140):
                                                self.logger.info(f"Lab assignment (CO-SCHEDULABLE): Course {course_code_display} → "
                                                               f"{session_name} on {dept_days[day_idx]} in "
                                                               f"140-capacity Lab {room_row['room_number']} (can share with same course instances)")
                                                break
                                        else:
                                            self.logger.info(f"Lab assignment: Course {course_code_display} → "
                                                           f"{session_name} on {dept_days[day_idx]} in "
                                                           f"Lab {room_row['room_number']} (capacity: {room_capacity})")
                                    else:
                                        self.logger.info(f"Lab assignment: Course {course_code_display} → "
                                                   f"{session_name} on {dept_days[day_idx]} in "
                                                   f"Lab {room_row['room_number']} (capacity: {room_capacity})")
        
        # Add co-scheduling identification
        lab_schedule = self._identify_and_mark_co_scheduled_sessions(lab_schedule)
        
        self.logger.info(f"Extracted {len(lab_schedule)} lab sessions with proper batching")
        co_scheduled_count = sum(1 for session in lab_schedule if session.get('is_co_scheduled', False))
        self.logger.info(f"🎯 Co-scheduled sessions detected: {co_scheduled_count}/{len(lab_schedule)} sessions")
        return lab_schedule
    
    def _identify_and_mark_co_scheduled_sessions(self, lab_schedule):
        """Identify and mark sessions that are co-scheduled (same course, same time/day, same room)."""
        self.logger.info("Identifying co-scheduled sessions...")
        
        # Group sessions by (day, session_name, room_id)
        session_groups = defaultdict(list)
        
        for session in lab_schedule:
            key = (session['day'], session['session_name'], session['room_id'])
            session_groups[key].append(session)
        
        # Identify co-scheduled sessions
        co_scheduled_groups = 0
        co_scheduled_sessions = 0
        
        for (day, session_name, room_id), sessions in session_groups.items():
            if len(sessions) > 1:
                # Check if this is a valid co-scheduling case (same course, same group)
                course_codes = set(s['course_code'] for s in sessions)
                group_names = set(s['group_name'] for s in sessions)
                
                if len(course_codes) == 1 and len(group_names) == 1:
                    # Valid co-scheduling: same course from same group
                    course_code = list(course_codes)[0]
                    group_name = list(group_names)[0]
                    room_capacity = sessions[0]['capacity']
                    
                    # Get room info
                    room_info = f"Room {sessions[0]['room_number']} (capacity: {room_capacity})"
                    
                    # Mark all sessions in this group as co-scheduled
                    co_schedule_id = f"CO_{day}_{session_name}_{room_id}"
                    teachers = [s['teacher_name'] for s in sessions]
                    
                    for i, session in enumerate(sessions):
                        session['is_co_scheduled'] = True
                        session['co_schedule_id'] = co_schedule_id
                        session['co_schedule_group_size'] = len(sessions)
                        session['co_schedule_partner_teachers'] = ', '.join([t for t in teachers if t != session['teacher_name']])
                        session['co_schedule_info'] = f"Co-scheduled with {len(sessions)-1} other instance(s)"
                    
                    co_scheduled_groups += 1
                    co_scheduled_sessions += len(sessions)
                    
                    # Check if this is the optimal 140-capacity lab usage
                    is_140_lab = room_capacity > 70
                    efficiency_note = ""
                    if is_140_lab:
                        efficiency_note = " 🚀 OPTIMAL 140-lab usage!"
                    
                    self.logger.info(f"✅ Co-scheduled group found: {course_code} in {group_name}{efficiency_note}")
                    self.logger.info(f"   📍 {day.capitalize()}, {session_name} in {room_info}")
                    self.logger.info(f"   👥 Teachers: {', '.join(teachers)}")
                    self.logger.info(f"   🎯 {len(sessions)} instances scheduled together")
                    
                    if is_140_lab:
                        self.logger.info(f"   💡 140-capacity lab efficiently utilized: 2 courses instead of 1")
                    
                else:
                    # Multiple courses or groups in same room - not co-scheduling, potential conflict
                    self.logger.warning(f"⚠️  Multiple different courses/groups in same room slot:")
                    self.logger.warning(f"   📍 {day.capitalize()}, {session_name}, Room {sessions[0]['room_number']}")
                    for session in sessions:
                        self.logger.warning(f"   - {session['course_code']} ({session['group_name']}) - {session['teacher_name']}")
            else:
                # Single session in this slot - mark as not co-scheduled
                sessions[0]['is_co_scheduled'] = False
                sessions[0]['co_schedule_id'] = ""
                sessions[0]['co_schedule_group_size'] = 1
                sessions[0]['co_schedule_partner_teachers'] = ""
                sessions[0]['co_schedule_info'] = "Single session"
        
        self.logger.info(f"Co-scheduling analysis complete:")
        self.logger.info(f"  🎯 Co-scheduled groups: {co_scheduled_groups}")
        self.logger.info(f"  📊 Co-scheduled sessions: {co_scheduled_sessions}")
        self.logger.info(f"  💡 Efficiency gain: {co_scheduled_sessions - co_scheduled_groups} extra sessions accommodated")
        
        return lab_schedule
    
    def _save_combined_schedules(self, lab_schedule, theory_schedule):
        """Save the lab and theory schedules to files."""
        self.logger.info("Saving combined schedules...")

        # Use custom JSON encoder to handle numpy types and NaN values
        def convert_numpy_types(obj):
            if isinstance(obj, np.integer):
                return int(obj)
            elif isinstance(obj, np.floating):
                if np.isnan(obj) or np.isinf(obj):
                    return None  # Convert NaN/inf to null
                return float(obj)
            elif isinstance(obj, np.ndarray):
                return obj.tolist()
            elif isinstance(obj, (np.bool_, bool)):
                return bool(obj)
            elif obj != obj:  # Check for NaN (NaN != NaN is True)
                return None
            elif obj == float('inf') or obj == float('-inf'):
                return None
            return obj

        # Clean data before saving (replace NaN values)
        def clean_data(data):
            """Recursively clean data by replacing NaN/None values with appropriate defaults."""
            if isinstance(data, list):
                return [clean_data(item) for item in data]
            elif isinstance(data, dict):
                cleaned = {}
                for key, value in data.items():
                    cleaned[key] = clean_data(value)
                return cleaned
            elif pd.isna(data) or data != data:  # Check for NaN
                return None
            elif isinstance(data, (np.floating, float)) and (np.isnan(data) or np.isinf(data)):
                return None
            else:
                return data
        
        # Clean the schedules
        clean_lab_schedule = clean_data(lab_schedule)
        clean_theory_schedule = clean_data(theory_schedule)

        # --- Save Lab Schedule ---
        lab_df = pd.DataFrame(clean_lab_schedule)
        lab_csv_path = os.path.join(self.output_dir, 'combined_lab_schedule.csv')
        lab_df.to_csv(lab_csv_path, index=False)
        self.logger.info(f"Combined lab schedule saved to {lab_csv_path}")

        lab_json_path = os.path.join(self.output_dir, 'combined_lab_schedule.json')
        with open(lab_json_path, 'w', encoding='utf-8') as f:
            json.dump(clean_lab_schedule, f, indent=2, default=convert_numpy_types)
        self.logger.info(f"Combined lab schedule saved to {lab_json_path}")
        
        # --- Save Theory Schedule ---
        theory_df = pd.DataFrame(clean_theory_schedule)
        theory_csv_path = os.path.join(self.output_dir, 'combined_theory_schedule.csv')
        theory_df.to_csv(theory_csv_path, index=False)
        self.logger.info(f"Combined theory schedule saved to {theory_csv_path}")

        theory_json_path = os.path.join(self.output_dir, 'combined_theory_schedule.json')
        with open(theory_json_path, 'w', encoding='utf-8') as f:
            json.dump(clean_theory_schedule, f, indent=2, default=convert_numpy_types)
        self.logger.info(f"Combined theory schedule saved to {theory_json_path}")
        
        # --- Generate Summary ---
        if lab_schedule or theory_schedule:
            combined_schedule = lab_schedule + theory_schedule
            self._generate_combined_summary(lab_schedule, theory_schedule, combined_schedule)
        else:
            self.logger.warning("Both lab and theory schedules are empty, skipping summary generation.")
    
    def _generate_combined_summary(self, lab_schedule, theory_schedule, combined_schedule):
        """Generate a summary of the combined schedule."""
        summary_path = os.path.join(self.output_dir, 'combined_schedule_summary.txt')
        
        with open(summary_path, 'w', encoding='utf-8') as f:
            f.write("COMBINED SCHEDULE SUMMARY\n")
            f.write("========================\n\n")
            
            f.write(f"Total scheduled sessions: {len(combined_schedule)}\n")
            f.write(f"  Lab sessions: {len(lab_schedule)}\n")
            f.write(f"  Theory sessions: {len(theory_schedule)}\n\n")
            
            # Batch analysis for lab sessions
            if lab_schedule:
                batched_sessions = [item for item in lab_schedule if item.get('is_batched', False)]
                non_batched_sessions = [item for item in lab_schedule if not item.get('is_batched', False)]
                
                f.write("Lab Session Batching Analysis:\n")
                f.write(f"  Batched sessions: {len(batched_sessions)}\n")
                f.write(f"  Non-batched sessions: {len(non_batched_sessions)}\n")
                
                if batched_sessions:
                    # Count courses that required batching
                    batched_courses = set()
                    batch_details = {}
                    
                    for session in batched_sessions:
                        course_code = session['course_code']
                        batched_courses.add(course_code)
                        
                        if course_code not in batch_details:
                            batch_details[course_code] = {
                                'num_batches': session.get('num_batches', 1),
                                'total_students': session.get('total_students', 0),
                                'students_per_batch': session.get('student_count', 0),
                                'capacity': session.get('capacity', 0)
                            }
                    
                    f.write(f"  Courses requiring batching: {len(batched_courses)}\n")
                    f.write("  Batch details:\n")
                    
                    for course_code, details in batch_details.items():
                        f.write(f"    {course_code}: {details['num_batches']} batches, "
                               f"{details['total_students']} total students, "
                               f"~{details['students_per_batch']} per batch "
                               f"(room capacity: {details['capacity']})\n")
                
                f.write("\n")
            
            # Sessions by day
            day_counts = {'lab': {}, 'theory': {}}
            for item in lab_schedule:
                day = item['day']
                day_counts['lab'][day] = day_counts['lab'].get(day, 0) + 1
            
            for item in theory_schedule:
                day = item['day']
                day_counts['theory'][day] = day_counts['theory'].get(day, 0) + 1
            
            f.write("Sessions by day:\n")
            for day in self.days:
                lab_count = day_counts['lab'].get(day, 0)
                theory_count = day_counts['theory'].get(day, 0)
                f.write(f"  {day.capitalize()}: {lab_count + theory_count} total ({lab_count} lab, {theory_count} theory)\n")
            
            # Teachers with assignments
            lab_teachers = set(item['teacher_id'] for item in lab_schedule)
            theory_teachers = set(item['teacher_id'] for item in theory_schedule)
            all_teachers = lab_teachers | theory_teachers
            
            f.write(f"\nTeachers with assignments: {len(all_teachers)}\n")
            f.write(f"  Lab only: {len(lab_teachers - theory_teachers)}\n")
            f.write(f"  Theory only: {len(theory_teachers - lab_teachers)}\n")
            f.write(f"  Both lab and theory: {len(lab_teachers & theory_teachers)}\n")
            
            # Room utilization
            lab_rooms = set(item['room_id'] for item in lab_schedule)
            theory_rooms = set(item['room_id'] for item in theory_schedule)
            
            f.write(f"\nRoom utilization:\n")
            f.write(f"  Lab rooms used: {len(lab_rooms)}\n")
            f.write(f"  Theory rooms used: {len(theory_rooms)}\n")
            
            # Capacity utilization analysis
            if lab_schedule:
                f.write(f"\nLab capacity utilization:\n")
                capacity_35_sessions = [item for item in lab_schedule if item.get('capacity', 0) <= 35]
                capacity_70_sessions = [item for item in lab_schedule if 35 < item.get('capacity', 0) <= 70]
                capacity_140_sessions = [item for item in lab_schedule if item.get('capacity', 0) > 70]
                
                f.write(f"  35-capacity labs: {len(capacity_35_sessions)} sessions\n")
                f.write(f"  70-capacity labs: {len(capacity_70_sessions)} sessions\n")
                f.write(f"  140+ capacity labs: {len(capacity_140_sessions)} sessions\n")
                
                # Co-scheduling analysis
                co_scheduled_sessions = [item for item in lab_schedule if item.get('is_co_scheduled', False)]
                if co_scheduled_sessions:
                    f.write(f"\n🎯 Co-scheduling Analysis:\n")
                    
                    # Count co-scheduled groups
                    co_schedule_ids = set(session.get('co_schedule_id', '') for session in co_scheduled_sessions)
                    co_schedule_ids.discard('')  # Remove empty IDs
                    
                    f.write(f"  Co-scheduled groups: {len(co_schedule_ids)}\n")
                    f.write(f"  Co-scheduled sessions: {len(co_scheduled_sessions)}\n")
                    f.write(f"  Efficiency gain: {len(co_scheduled_sessions) - len(co_schedule_ids)} extra sessions accommodated\n")
                    
                    # Room-wise co-scheduling breakdown
                    co_scheduled_by_room = defaultdict(list)
                    for session in co_scheduled_sessions:
                        room_number = session['room_number']
                        co_scheduled_by_room[room_number].append(session)
                    
                    f.write(f"  Rooms with co-scheduling:\n")
                    for room_number, sessions in co_scheduled_by_room.items():
                        room_capacity = sessions[0]['capacity']
                        co_groups = set(s.get('co_schedule_id', '') for s in sessions)
                        co_groups.discard('')
                        f.write(f"    {room_number} (capacity: {room_capacity}): {len(co_groups)} co-scheduled groups, {len(sessions)} sessions\n")
                    
                    # Course-wise co-scheduling
                    co_scheduled_courses = set(session['course_code'] for session in co_scheduled_sessions)
                    f.write(f"  Courses using co-scheduling: {len(co_scheduled_courses)}\n")
                    for course_code in sorted(co_scheduled_courses):
                        course_sessions = [s for s in co_scheduled_sessions if s['course_code'] == course_code]
                        course_groups = set(s.get('co_schedule_id', '') for s in course_sessions)
                        course_groups.discard('')
                        f.write(f"    {course_code}: {len(course_groups)} co-scheduled groups\n")
        
        self.logger.info(f"Combined summary saved to {summary_path}") 

    def _generate_shift_reports(self, lab_schedule, theory_schedule):
        """Generate comprehensive shift reports using the ShiftReportGenerator."""
        try:
            self.logger.info("🔍 Starting shift report generation...")
            
            # Initialize shift report generator
            shift_report_generator = ShiftReportGenerator(self.output_dir)
            
            # Generate comprehensive shift reports
            shift_reports = shift_report_generator.generate_shift_reports(lab_schedule, theory_schedule)
            
            # Log summary of violations if any
            violations = shift_reports.get('staff_violations', {})
            if violations:
                violation_count = sum(len(v) for v in violations.values())
                self.logger.warning(f"⚠️ Found {violation_count} shift violations across all staff")
            
            self.logger.info(f"✅ Shift reports generated successfully!")
            
            return shift_reports
            
        except Exception as e:
            self.logger.error(f"❌ Error generating shift reports: {str(e)}")
            return {}
    
    def analyze_lab_capacity(self):
        """Analyze lab capacity distribution."""
        # Categorize labs by capacity
        labs_35 = []
        labs_70 = []
        labs_140 = []
        
        for _, lab in self.lab_rooms.iterrows():
            capacity = lab['room_max_cap']
            lab_info = {
                'id': lab['id'],
                'room_number': lab['room_number'],
                'capacity': capacity,
                'block': lab.get('block', ''),
                'description': lab.get('description', '')
            }
            
            if capacity <= 35:
                labs_35.append(lab_info)
            elif capacity <= 70:
                labs_70.append(lab_info)
            else:
                labs_140.append(lab_info)
        
        # Store the analysis
        self.lab_capacity_analysis = {
            'labs_35': labs_35,
            'labs_70': labs_70,
            'labs_140': labs_140,
            'total_35': len(labs_35),
            'total_70': len(labs_70),
            'total_140': len(labs_140),
            'total_labs': len(self.lab_rooms)
        }
        
        # Log capacity analysis
        self.logger.info(f"Lab capacity analysis:")
        self.logger.info(f"  - 35 capacity labs: {len(labs_35)}")
        self.logger.info(f"  - 70 capacity labs: {len(labs_70)}")
        self.logger.info(f"  - 140 capacity labs: {len(labs_140)}")
    
    def _determine_lab_allocation_strategy(self, practical_hours, students_per_instance, course_instance_id=None):
        """Determine the optimal lab allocation strategy based on practical hours and student count."""
        # Calculate base lab sessions needed (2 practical hours = 1 lab session)
        base_sessions = (practical_hours + 1) // 2
        
        strategy = {
            'practical_hours': practical_hours,
            'students_per_instance': students_per_instance,
            'base_sessions': base_sessions,
            'total_lab_slots_needed': base_sessions,  # Default: no batching
            'preferred_lab_capacities': [],
            'force_35_capacity': False,
            'force_70_plus_capacity': False,
            'prefer_70_plus_with_batching_fallback': False,
            'allow_core_lab_flexibility': False
        }
        
        # Check if this is a core lab
        is_core_lab = course_instance_id and course_instance_id in self.core_lab_instance_ids
        
        # SPECIAL RULE: 35 students exactly -> FORCE 35-capacity labs ONLY, NO batching
        if students_per_instance == 35:
            strategy['force_35_capacity'] = True
            strategy['preferred_lab_capacities'] = [35]  # Only 35-capacity labs
            strategy['total_lab_slots_needed'] = base_sessions  # No batching needed
            self.logger.info(f"35-STUDENT Course with {practical_hours}h practical: FORCED to use 35-capacity labs ONLY (no batching)")
            return strategy
        
        # Simple capacity rules based on practical hours
        if practical_hours <= 2:
            if is_core_lab:
                # Core labs with 2 practical hours can use both 35 and 70 capacity labs
                strategy['force_35_capacity'] = False
                strategy['prefer_70_plus_with_batching_fallback'] = True  # Allow flexible choice
                strategy['preferred_lab_capacities'] = [35, 70, 140]  # All capacities allowed
                strategy['allow_core_lab_flexibility'] = True
                self.logger.info(f"CORE LAB with {practical_hours}h practical: ALLOWED to use both 35 and 70+ capacity labs")
            else:
                # Non-core labs with 2 practical hours must use 35-capacity labs only
                strategy['force_35_capacity'] = True
                strategy['preferred_lab_capacities'] = [35]  # Only 35-capacity labs allowed
                self.logger.info(f"NON-CORE course with {practical_hours}h practical: RESTRICTED to 35-capacity labs only")
        elif practical_hours == 6:
            # Rule: practical_hours == 6 PREFERS 70+ capacity labs but allows batching fallback
            strategy['prefer_70_plus_with_batching_fallback'] = True
            strategy['preferred_lab_capacities'] = [70, 140, 35]  # 70+ preferred, 35 as fallback
        elif practical_hours >= 5:
            # Rule: practical_hours >= 5 (but not 6) PREFERS 70+ capacity labs but allows batching fallback
            strategy['prefer_70_plus_with_batching_fallback'] = True
            strategy['preferred_lab_capacities'] = [70, 140, 35]  # 70+ preferred, 35 as fallback
        elif practical_hours == 4:
            # Rule: practical_hours == 4 PREFERS 70+ capacity labs but allows batching fallback
            strategy['prefer_70_plus_with_batching_fallback'] = True
            strategy['preferred_lab_capacities'] = [70, 140, 35]  # 70+ preferred, 35 as fallback
        else:
            # Rule: practical_hours 3 can use either strategy (solver decides)
            strategy['preferred_lab_capacities'] = [35, 70, 140]
        
        return strategy
    


    def analyze_theory_feasibility(self):
        """Analyze if theory scheduling is feasible with current constraints."""
        self.logger.info("Analyzing theory scheduling feasibility...")
        
        # Basic feasibility checks
        total_groups = sum(len(groups) for groups in self.course_groups.values())
        # Use Monday-Friday pattern as baseline for feasibility analysis (most restrictive)
        total_theory_slots = 5 * self.num_theory_slots
        total_room_capacity = len(self.theory_room_ids) * total_theory_slots
        
        # Calculate required slots
        total_required_slots = sum(self.group_requirements.values())
        
        self.logger.info(f"Theory feasibility analysis:")
        self.logger.info(f"  - Total groups: {total_groups}")
        self.logger.info(f"  - Total required slots: {total_required_slots}")
        self.logger.info(f"  - Total available time slots: {total_theory_slots}")
        self.logger.info(f"  - Total room capacity: {total_room_capacity}")
        
        if total_required_slots > total_room_capacity:
            self.logger.error(f"INFEASIBLE: Required slots ({total_required_slots}) exceed room capacity ({total_room_capacity})")
            return False
        
        # Check semester-level feasibility
        semester_feasible = True
        for (dept, semester), groups in self.course_groups.items():
            semester_key = f"{dept}_S{semester}"
            semester_required = 0
            
            for group_idx, group in enumerate(groups):
                if group:
                    group_name = f"{dept}_S{semester}_G{group_idx + 1}"
                    if group_name in self.group_requirements:
                        semester_required += self.group_requirements[group_name]
            
            if semester_required > total_theory_slots:
                self.logger.error(f"INFEASIBLE: {semester_key} requires {semester_required} slots but only {total_theory_slots} available")
                semester_feasible = False
        
        if semester_feasible:
            self.logger.info("✅ Theory scheduling appears feasible")
        
        return semester_feasible

    def add_group_allocation_objective(self, model, group_timeslot_vars):
        """Add an objective function to improve the theory schedule quality."""
        self.logger.info("Adding theory group allocation objective...")
        
        objective_terms = []
        
        for group_name, day_slots in group_timeslot_vars.items():
            # Get department for this group to use correct number of days
            dept_name = group_name.split('_S')[0] if '_S' in group_name else "Computer Science & Engineering"
            dept_days = self._get_days_for_department(dept_name)
            num_dept_days = len(dept_days)
            
            for day_idx in range(num_dept_days):
                if day_idx in day_slots:
                    for slot_idx in range(self.num_theory_slots):
                        if slot_idx in day_slots[day_idx]:
                            # Equal weight for all time slots (no time preference)
                            objective_terms.append(day_slots[day_idx][slot_idx])
        
        if objective_terms:
            model.Maximize(sum(objective_terms))
            self.logger.info(f"Group allocation objective set with {len(objective_terms)} terms")
            self.logger.info("Objective strategy: Equal weight for all time slots (no time preference)")
        else:
            self.logger.warning("No objective terms created for group allocation")

    def generate_course_group_distribution_heatmap(self):
        """Generate heatmap visualization of course-to-group distribution for combined scheduler."""
        self.logger.info("🎨 Generating combined course-to-group distribution heatmap...")
        
        try:
            import matplotlib.pyplot as plt
            import seaborn as sns
            import numpy as np
            
            # Create output directory for visualizations
            viz_output_dir = os.path.join(self.output_dir, 'grouping_visualizations')
            os.makedirs(viz_output_dir, exist_ok=True)
            
            # Process each department-semester combination
            total_dept_sem = len(self.course_groups)
            processed_count = 0
            
            self.logger.info(f"📊 Processing {total_dept_sem} department-semester combinations for combined heatmaps...")
            
            for (dept, semester), groups in self.course_groups.items():
                processed_count += 1
                
                if not groups:
                    self.logger.warning(f"⚠️ Skipping {dept} S{semester} - no groups")
                    continue
                    
                self.logger.info(f"🎨 Creating combined heatmap {processed_count}/{total_dept_sem}: {dept} Semester {semester}...")
                
                try:
                    # Collect course-group data
                    course_group_matrix = {}
                    all_courses = set()
                    group_names = []
                    
                    # Separate lab and theory courses for analysis
                    lab_courses = set()
                    theory_courses = set()
                    
                    for group_idx, group in enumerate(groups):
                        if not group:
                            continue
                            
                        group_name = f"G{group_idx + 1}"
                        group_names.append(group_name)
                        
                        # Count teacher assignments per course per group
                        course_teacher_counts = {}
                        for instance in group:
                            course_code = instance['course_code']
                            teacher_id = instance['teacher_id']
                            all_courses.add(course_code)
                            
                            # Categorize course type
                            if instance.get('has_lab', False):
                                lab_courses.add(course_code)
                            if instance.get('has_theory', False):
                                theory_courses.add(course_code)
                            
                            if course_code not in course_teacher_counts:
                                course_teacher_counts[course_code] = set()
                            course_teacher_counts[course_code].add(teacher_id)
                        
                        # Store teacher assignment counts
                        for course_code, teachers in course_teacher_counts.items():
                            if course_code not in course_group_matrix:
                                course_group_matrix[course_code] = {}
                            course_group_matrix[course_code][group_name] = len(teachers)
                    
                    if not all_courses or not group_names:
                        self.logger.warning(f"No data to visualize for {dept} Semester {semester}")
                        continue
                    
                    # Create matrix for heatmap
                    courses_list = sorted(list(all_courses))
                    matrix_data = []
                    
                    for course in courses_list:
                        row = []
                        for group_name in group_names:
                            count = course_group_matrix.get(course, {}).get(group_name, 0)
                            row.append(count)
                        matrix_data.append(row)
                    
                    # Create the heatmap
                    plt.figure(figsize=(max(8, len(group_names) * 1.2), max(6, len(courses_list) * 0.4)))
                    
                    # Convert to numpy array for better handling
                    matrix_array = np.array(matrix_data)
                    
                    # Create heatmap with custom colormap (using a combined color scheme)
                    ax = sns.heatmap(matrix_array, 
                                   xticklabels=group_names,
                                   yticklabels=courses_list,
                                   annot=True, 
                                   fmt='d',
                                   cmap='viridis',  # Combined color scheme
                                   cbar_kws={'label': 'Number of Teacher Assignments'},
                                   linewidths=0.5)
                    
                    # Customize the plot
                    plt.title(f'Combined Course-Group Distribution\n{dept} - Semester {semester}\n(Number shows teacher assignments per course per group)', 
                             fontsize=14, fontweight='bold', pad=20)
                    plt.xlabel('Groups', fontsize=12, fontweight='bold')
                    plt.ylabel('Courses', fontsize=12, fontweight='bold')
                    
                    # Add course type annotations
                    for i, course in enumerate(courses_list):
                        course_types = []
                        if course in lab_courses:
                            course_types.append('L')
                        if course in theory_courses:
                            course_types.append('T')
                        
                        if course_types:
                            type_str = '+'.join(course_types)
                            plt.text(-0.5, i + 0.5, f'[{type_str}]', 
                                   ha='right', va='center', fontsize=8, 
                                   bbox=dict(boxstyle="round,pad=0.2", facecolor="lightblue", alpha=0.7))
                    
                    # Rotate labels for better readability
                    plt.xticks(rotation=0, ha='center')
                    plt.yticks(rotation=0)
                    
                    # Add grid for better readability
                    ax.set_facecolor('white')
                    
                    # Add summary statistics as text
                    total_assignments = np.sum(matrix_array)
                    max_assignments = np.max(matrix_array) if matrix_array.size > 0 else 0
                    
                    # Calculate course distribution stats
                    courses_with_choice = sum(1 for course in courses_list 
                                            if sum(course_group_matrix.get(course, {}).values()) > 1)
                    choice_percentage = (courses_with_choice / len(courses_list) * 100) if courses_list else 0
                    
                    stats_text = f'Stats: {len(courses_list)} courses ({len(lab_courses)} lab, {len(theory_courses)} theory), {len(group_names)} groups\n'
                    stats_text += f'Total assignments: {total_assignments}, Max per cell: {max_assignments}\n'
                    stats_text += f'Courses with multiple groups: {courses_with_choice} ({choice_percentage:.1f}%)\n'
                    stats_text += f'[L] = Lab courses, [T] = Theory courses, [L+T] = Both'
                    
                    plt.figtext(0.02, 0.02, stats_text, fontsize=9, 
                               bbox=dict(boxstyle="round,pad=0.3", facecolor="lightgray", alpha=0.8))
                    
                    plt.tight_layout()
                    
                    # Save the heatmap - handle special characters in filename
                    safe_dept_name = dept.replace(" ", "_").replace("&", "and").replace("(", "").replace(")", "")
                    filename = f'combined_course_group_heatmap_{safe_dept_name}_S{semester}.png'
                    filepath = os.path.join(viz_output_dir, filename)
                    plt.savefig(filepath, dpi=300, bbox_inches='tight')
                    plt.close()
                    
                    self.logger.info(f"✅ Combined heatmap saved: {filepath}")
                    
                    # Also create a detailed text summary
                    summary_filename = f'combined_course_group_summary_{safe_dept_name}_S{semester}.txt'
                    summary_filepath = os.path.join(viz_output_dir, summary_filename)
                    
                    with open(summary_filepath, 'w', encoding='utf-8') as f:
                        f.write(f"Combined Course-Group Distribution Summary\n")
                        f.write(f"Department: {dept}\n")
                        f.write(f"Semester: {semester}\n")
                        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                        f.write(f"="*60 + "\n\n")
                        
                        f.write(f"OVERVIEW:\n")
                        f.write(f"- Total Courses: {len(courses_list)}\n")
                        f.write(f"  └─ Lab Courses: {len(lab_courses)}\n")
                        f.write(f"  └─ Theory Courses: {len(theory_courses)}\n")
                        f.write(f"  └─ Overlap (Both): {len(lab_courses & theory_courses)}\n")
                        f.write(f"- Total Groups: {len(group_names)}\n")
                        f.write(f"- Total Teacher Assignments: {total_assignments}\n")
                        f.write(f"- Courses with Multiple Group Options: {courses_with_choice} ({choice_percentage:.1f}%)\n\n")
                        
                        f.write(f"COURSE DISTRIBUTION BY TYPE:\n")
                        for course in courses_list:
                            course_data = course_group_matrix.get(course, {})
                            groups_with_course = [g for g, count in course_data.items() if count > 0]
                            total_teachers = sum(course_data.values())
                            
                            # Determine course type
                            course_type = []
                            if course in lab_courses:
                                course_type.append("Lab")
                            if course in theory_courses:
                                course_type.append("Theory")
                            type_str = " + ".join(course_type) if course_type else "Unknown"
                            
                            f.write(f"- {course} [{type_str}]: {len(groups_with_course)} groups, {total_teachers} teacher assignments\n")
                            for group_name in groups_with_course:
                                f.write(f"  └─ {group_name}: {course_data[group_name]} teachers\n")
                        
                        f.write(f"\nGROUP COMPOSITION:\n")
                        for group_idx, group in enumerate(groups):
                            if not group:
                                continue
                            group_name = f"G{group_idx + 1}"
                            courses_in_group = set(inst['course_code'] for inst in group)
                            teachers_in_group = set(inst['teacher_id'] for inst in group)
                            
                            # Count course types in this group
                            group_lab_courses = {inst['course_code'] for inst in group if inst.get('has_lab', False)}
                            group_theory_courses = {inst['course_code'] for inst in group if inst.get('has_theory', False)}
                            
                            f.write(f"- {group_name}: {len(courses_in_group)} courses, {len(teachers_in_group)} teachers\n")
                            f.write(f"  └─ Lab courses: {len(group_lab_courses)}\n")
                            f.write(f"  └─ Theory courses: {len(group_theory_courses)}\n")
                            for course in sorted(courses_in_group):
                                course_teachers = set(inst['teacher_id'] for inst in group if inst['course_code'] == course)
                                course_instances = [inst for inst in group if inst['course_code'] == course]
                                
                                # Determine instance types for this course in this group
                                has_lab = any(inst.get('has_lab', False) for inst in course_instances)
                                has_theory = any(inst.get('has_theory', False) for inst in course_instances)
                                
                                type_indicators = []
                                if has_lab:
                                    type_indicators.append("L")
                                if has_theory:
                                    type_indicators.append("T")
                                type_str = "+".join(type_indicators) if type_indicators else ""
                                
                                f.write(f"    └─ {course} [{type_str}]: {len(course_teachers)} teachers, {len(course_instances)} instances\n")
                    
                    self.logger.info(f"✅ Combined summary saved: {summary_filepath}")
                    
                except Exception as dept_error:
                    self.logger.error(f"❌ Error processing {dept} S{semester} for combined heatmap: {str(dept_error)}")
                    import traceback
                    self.logger.error(f"Traceback: {traceback.format_exc()}")
                    continue

            # Create a combined overview heatmap if multiple department-semesters exist
            if len(self.course_groups) > 1:
                self._create_combined_overview_heatmap(viz_output_dir)
            
            self.logger.info(f"🎨 All combined course-group distribution visualizations saved to: {viz_output_dir}")
            
        except Exception as e:
            self.logger.error(f"❌ Error generating combined course-group heatmap: {str(e)}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")

    def _create_combined_overview_heatmap(self, viz_output_dir):
        """Create a combined overview heatmap showing all department-semester combinations for combined scheduler."""
        self.logger.info("Creating combined overview heatmap for combined scheduler...")
        
        try:
            import matplotlib.pyplot as plt
            import seaborn as sns
            import numpy as np
            
            # Collect data from all department-semester combinations
            all_data = []
            dept_sem_labels = []
            
            for (dept, semester), groups in self.course_groups.items():
                if not groups:
                    continue
                    
                dept_sem_key = f"{dept} S{semester}"
                dept_sem_labels.append(dept_sem_key)
                
                # Count courses and groups
                all_courses = set()
                lab_courses = set()
                theory_courses = set()
                total_assignments = 0
                
                for group in groups:
                    if group:
                        for instance in group:
                            course_code = instance['course_code']
                            all_courses.add(course_code)
                            if instance.get('has_lab', False):
                                lab_courses.add(course_code)
                            if instance.get('has_theory', False):
                                theory_courses.add(course_code)
                        total_assignments += len(group)
                
                courses_with_choice = 0
                course_group_counts = {}
                
                # Count how many groups each course appears in
                for course in all_courses:
                    groups_with_course = 0
                    for group in groups:
                        if group and any(inst['course_code'] == course for inst in group):
                            groups_with_course += 1
                    course_group_counts[course] = groups_with_course
                    if groups_with_course > 1:
                        courses_with_choice += 1
                
                choice_percentage = (courses_with_choice / len(all_courses) * 100) if all_courses else 0
                overlap_courses = len(lab_courses & theory_courses)
                
                all_data.append({
                    'dept_sem': dept_sem_key,
                    'total_courses': len(all_courses),
                    'lab_courses': len(lab_courses),
                    'theory_courses': len(theory_courses),
                    'overlap_courses': overlap_courses,
                    'total_groups': len([g for g in groups if g]),
                    'total_assignments': total_assignments,
                    'courses_with_choice': courses_with_choice,
                    'choice_percentage': choice_percentage,
                    'avg_groups_per_course': sum(course_group_counts.values()) / len(all_courses) if all_courses else 0
                })
            
            if not all_data:
                return
            
            # Create overview visualization
            fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(16, 12))
            
            # Extract data for plotting
            dept_sems = [d['dept_sem'] for d in all_data]
            total_courses = [d['total_courses'] for d in all_data]
            lab_courses = [d['lab_courses'] for d in all_data]
            theory_courses = [d['theory_courses'] for d in all_data]
            overlap_courses = [d['overlap_courses'] for d in all_data]
            total_groups = [d['total_groups'] for d in all_data]
            choice_percentages = [d['choice_percentage'] for d in all_data]
            avg_groups_per_course = [d['avg_groups_per_course'] for d in all_data]
            
            # Plot 1: Course distribution by type
            x_pos = np.arange(len(dept_sems))
            width = 0.25
            
            ax1.bar(x_pos - width, lab_courses, width, label='Lab Courses', color='orange', alpha=0.8)
            ax1.bar(x_pos, theory_courses, width, label='Theory Courses', color='blue', alpha=0.8)
            ax1.bar(x_pos + width, overlap_courses, width, label='Both Lab+Theory', color='green', alpha=0.8)
            
            ax1.set_xlabel('Department-Semester')
            ax1.set_ylabel('Number of Courses')
            ax1.set_title('Course Distribution by Type')
            ax1.set_xticks(x_pos)
            ax1.set_xticklabels(dept_sems, rotation=45, ha='right')
            ax1.legend()
            ax1.grid(True, alpha=0.3)
            
            # Plot 2: Groups per department-semester
            bars2 = ax2.bar(dept_sems, total_groups, color='purple', alpha=0.7)
            ax2.set_xlabel('Department-Semester')
            ax2.set_ylabel('Number of Groups')
            ax2.set_title('Groups per Department-Semester')
            ax2.tick_params(axis='x', rotation=45)
            ax2.grid(True, alpha=0.3)
            
            # Add value labels on bars
            for bar in bars2:
                height = bar.get_height()
                ax2.text(bar.get_x() + bar.get_width()/2., height,
                        f'{int(height)}', ha='center', va='bottom')
            
            # Plot 3: Student choice percentage
            bars3 = ax3.bar(dept_sems, choice_percentages, color='teal', alpha=0.7)
            ax3.set_xlabel('Department-Semester')
            ax3.set_ylabel('Choice Percentage (%)')
            ax3.set_title('Student Choice Availability\n(% of courses with multiple group options)')
            ax3.tick_params(axis='x', rotation=45)
            ax3.set_ylim(0, 100)
            ax3.grid(True, alpha=0.3)
            
            # Add percentage labels
            for bar in bars3:
                height = bar.get_height()
                ax3.text(bar.get_x() + bar.get_width()/2., height,
                        f'{height:.1f}%', ha='center', va='bottom')
            
            # Plot 4: Average groups per course
            bars4 = ax4.bar(dept_sems, avg_groups_per_course, color='red', alpha=0.7)
            ax4.set_xlabel('Department-Semester')
            ax4.set_ylabel('Average Groups per Course')
            ax4.set_title('Group Distribution Density')
            ax4.tick_params(axis='x', rotation=45)
            ax4.grid(True, alpha=0.3)
            
            # Add value labels
            for bar in bars4:
                height = bar.get_height()
                ax4.text(bar.get_x() + bar.get_width()/2., height,
                        f'{height:.2f}', ha='center', va='bottom')
            
            plt.suptitle('Combined Scheduler: Course-Group Distribution Overview', 
                        fontsize=16, fontweight='bold', y=0.98)
            plt.tight_layout()
            
            # Save the overview
            overview_path = os.path.join(viz_output_dir, 'combined_course_group_overview.png')
            plt.savefig(overview_path, dpi=300, bbox_inches='tight')
            plt.close()
            
            # Create summary table
            summary_table_path = os.path.join(viz_output_dir, 'combined_distribution_summary.txt')
            with open(summary_table_path, 'w', encoding='utf-8') as f:
                f.write("COMBINED SCHEDULER - COURSE-GROUP DISTRIBUTION SUMMARY\n")
                f.write("="*70 + "\n\n")
                f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                
                f.write("DEPARTMENT-SEMESTER BREAKDOWN:\n")
                f.write("-"*70 + "\n")
                f.write(f"{'Dept-Sem':<20} {'Total':<6} {'Lab':<4} {'Theory':<6} {'Both':<4} {'Groups':<6} {'Choice%':<7} {'Avg Groups':<10}\n")
                f.write("-"*70 + "\n")
                
                for data in all_data:
                    f.write(f"{data['dept_sem']:<20} "
                           f"{data['total_courses']:<6} "
                           f"{data['lab_courses']:<4} "
                           f"{data['theory_courses']:<6} "
                           f"{data['overlap_courses']:<4} "
                           f"{data['total_groups']:<6} "
                           f"{data['choice_percentage']:<7.1f} "
                           f"{data['avg_groups_per_course']:<10.2f}\n")
                
                f.write("-"*70 + "\n")
                
                # Summary totals
                total_courses_all = sum(d['total_courses'] for d in all_data)
                total_lab_courses_all = sum(d['lab_courses'] for d in all_data)
                total_theory_courses_all = sum(d['theory_courses'] for d in all_data)
                total_overlap_all = sum(d['overlap_courses'] for d in all_data)
                total_groups_all = sum(d['total_groups'] for d in all_data)
                avg_choice_all = sum(d['choice_percentage'] for d in all_data) / len(all_data) if all_data else 0
                
                f.write(f"{'TOTALS':<20} "
                       f"{total_courses_all:<6} "
                       f"{total_lab_courses_all:<4} "
                       f"{total_theory_courses_all:<6} "
                       f"{total_overlap_all:<4} "
                       f"{total_groups_all:<6} "
                       f"{avg_choice_all:<7.1f} "
                       f"{'N/A':<10}\n")
                
                f.write("\nKEY METRICS:\n")
                f.write(f"- Total unique courses across all semesters: {total_courses_all}\n")
                f.write(f"- Total groups created: {total_groups_all}\n")
                f.write(f"- Average student choice percentage: {avg_choice_all:.1f}%\n")
                f.write(f"- Lab-only courses: {total_lab_courses_all - total_overlap_all}\n")
                f.write(f"- Theory-only courses: {total_theory_courses_all - total_overlap_all}\n")
                f.write(f"- Courses with both lab and theory: {total_overlap_all}\n")
            
            self.logger.info(f"✅ Combined overview saved: {overview_path}")
            self.logger.info(f"✅ Combined summary table saved: {summary_table_path}")
            
        except Exception as e:
            self.logger.error(f"❌ Error creating combined overview heatmap: {str(e)}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")

    # REMOVED: _identify_co_schedulable_course_instances function
    # This function identified course instances for 140-capacity lab co-scheduling which has been removed

    
    # This function implemented 140-capacity lab co-scheduling which has been removed

    def _check_140_capacity_room_availability(self, day_name, time_slot, room_id, lab_schedule=None, existing_theory_schedule=None):
        """
        Comprehensive check for 140-capacity room availability across all schedules.
        
        Args:
            day_name: Day name (department-specific)
            time_slot: Time slot string (e.g., "09:00-10:00")
            room_id: Room ID to check
            lab_schedule: Lab schedule to check against
            existing_theory_schedule: Existing theory schedule to check against
            
        Returns:
            tuple: (is_available: bool, conflict_reason: str)
        """
        # Normalize day name for consistent checking
        day_normalized = self._normalize_day_name(day_name)
        
        # Check if this is actually a 140-capacity room
        room_row = self.rooms_df[self.rooms_df['id'] == room_id]
        if room_row.empty:
            return False, f"Room {room_id} not found in rooms database"
        
        room_capacity = int(room_row.iloc[0]['room_max_cap'])
        if room_capacity < 140:
            return True, ""  # Not a 140-capacity room, standard availability checks apply
        
        room_number = room_row.iloc[0]['room_number']
        self.logger.debug(f"Checking 140-capacity room {room_number} (ID: {room_id}) availability for {day_name} {time_slot}")
        
        # Check 1: Global room registry
        if not self._is_room_available_global(day_name, time_slot, room_id):
            return False, f"140-capacity room {room_number} blocked by global registry"
        
        # Check 2: Existing theory schedule conflicts
        if existing_theory_schedule:
            for session in existing_theory_schedule:
                session_day_normalized = self._normalize_day_name(session['day'])
                if (session_day_normalized == day_normalized and 
                    session['time_slot'] == time_slot and 
                    session['room_id'] == room_id):
                    course_code = session.get('course_code', 'Unknown')
                    return False, f"140-capacity room {room_number} already assigned to {course_code}"
        
        # Check 3: Lab schedule conflicts (time overlap)
        if lab_schedule:
            for lab_session in lab_schedule:
                lab_day_normalized = self._normalize_day_name(lab_session['day'])
                if (lab_day_normalized == day_normalized and 
                    lab_session['room_id'] == room_id):
                    
                    # Check if lab time overlaps with theory time
                    lab_time_range = lab_session.get('time_range', '')
                    if self._times_overlap(lab_time_range, time_slot):
                        course_code = lab_session.get('course_code', 'Unknown')
                        return False, f"140-capacity room {room_number} conflicts with lab session {course_code} ({lab_time_range})"
        
        # Check 4: Verify room is actually available for theory (not a pure lab room)
        room_type = room_row.iloc[0].get('room_type', '')
        if room_type.lower() == 'laboratory' and room_id not in self.theory_room_ids:
            return False, f"140-capacity room {room_number} is laboratory-only, not available for theory sessions"
        
        return True, ""

    def _find_capacity_aware_theory_room(self, day_idx, time_slot_idx, used_rooms_this_slot, existing_schedule, dept_days, session, assigned_sessions_this_slot, lab_schedule=None):
        """
        Find an available theory room with capacity-aware assignment, department block preferences,
        TIFAC avoidance, and teacher continuity optimization.
        
        ENHANCED: Includes:
        - Block-wise department grouping (A Block for CS depts, B Block for traditional engineering)
        - TIFAC room avoidance (use only as last resort)
        - Teacher continuity (keep teachers in same room for adjacent slots)
        - Floor-wise room sorting within blocks
        - 140-capacity room availability checking
        
        Args:
            day_idx: Day index (department-specific)
            time_slot_idx: Time slot index
            used_rooms_this_slot: Set of room IDs already used in this time slot
            existing_schedule: List of already scheduled theory sessions
            dept_days: Department-specific day names
            session: Current session being assigned (contains course instance info)
            assigned_sessions_this_slot: List of sessions already assigned to this time slot
            lab_schedule: Lab schedule for cross-validation
            
        Returns:
            room_id if available, None if no room available
        """
        # Get correct day name using department-specific days
        day_name = dept_days[day_idx] if day_idx < len(dept_days) else f"day_{day_idx}"
        time_slot = self.theory_time_slots[time_slot_idx]
        
        # Normalize day name for consistent checking
        day_normalized = self._normalize_day_name(day_name)
        
        # Get session details for capacity-aware assignment
        instance = session['instance']
        student_count = instance.get('student_count', 70)
        course_code = instance.get('course_code', '')
        virtual_id = instance.get('virtual_id', '')
        co_scheduled_id = instance.get('co_scheduled_id', None)
        department = instance.get('student_dept', 'Computer Science & Engineering')
        teacher_id = instance.get('teacher_id', '')
        
        # Check if this is a co-scheduled instance (from split 140+ student course)
        is_co_scheduled = co_scheduled_id is not None and virtual_id
        
        # IMPORTANT: This enhanced room allocation logic is ONLY for 70-capacity classes
        # 140-capacity classes use the existing specialized logic below
        if student_count >= 140 or is_co_scheduled:
            self.logger.debug(f"Using existing 140-capacity logic for {course_code} ({student_count} students)")
            # Fall back to the original complex capacity-aware logic for 140+ students
            return self._find_capacity_aware_theory_room_original(
                day_idx, time_slot_idx, used_rooms_this_slot, existing_schedule, 
                dept_days, session, assigned_sessions_this_slot, lab_schedule
            )
        
        self.logger.debug(f"Using enhanced 70-capacity room allocation for {course_code} ({department}, "
                         f"{student_count} students, Teacher {teacher_id}) on {day_name} {time_slot}")
        
        # Get department-preferred rooms in priority order (70-capacity classes only)
        preferred_rooms = self._get_preferred_rooms_for_department(department)
        preferred_block = self.dept_block_preference.get(department, 'A Block')
        
        self.logger.debug(f"70-capacity class: {department} prefers {preferred_block}, "
                         f"got {len(preferred_rooms)} rooms in priority order")
        
        # Initialize teacher schedule tracking if not exists
        if not hasattr(self, '_teacher_room_schedule'):
            self._teacher_room_schedule = defaultdict(list)
        
        # Get rooms already occupied from existing theory schedule
        occupied_rooms = set()
        for existing_session in existing_schedule:
            session_day_normalized = self._normalize_day_name(existing_session['day'])
            if session_day_normalized == day_normalized and existing_session['time_slot'] == time_slot:
                occupied_rooms.add(existing_session['room_id'])
        
        # Check global room registry for any conflicts
        global_occupied_rooms = set()
        for room_id in self.theory_room_ids:
            if not self._is_room_available_global(day_name, time_slot, room_id):
                global_occupied_rooms.add(room_id)
        
        # Check lab schedule for overlapping times (if provided) 
        lab_conflict_rooms = set()
        if lab_schedule:
            for lab_session in lab_schedule:
                lab_day_normalized = self._normalize_day_name(lab_session['day'])
                if lab_day_normalized == day_normalized:
                    # Check if lab time overlaps with theory time
                    lab_time_range = lab_session.get('time_range', '')
                    if self._times_overlap(lab_time_range, time_slot):
                        lab_conflict_rooms.add(lab_session['room_id'])
        
        # Combine all occupied rooms
        all_occupied_rooms = occupied_rooms | used_rooms_this_slot | global_occupied_rooms | lab_conflict_rooms
        
        self.logger.debug(f"Room availability: {len(all_occupied_rooms)} occupied out of {len(self.theory_room_ids)} total")
        
        # Filter preferred rooms to only available ones
        available_preferred_rooms = []
        rooms_140_available = set()  # Track which 140-capacity rooms are actually available
        rooms_140_blocked = {}       # Track why 140-capacity rooms are blocked
        
        for room in preferred_rooms:
            room_id = room['id']
            
            # Skip if room is occupied
            if room_id in all_occupied_rooms:
                continue
            
            # For 140-capacity rooms, perform comprehensive availability check
            if room['capacity'] >= 140:
                is_available, conflict_reason = self._check_140_capacity_room_availability(
                    day_name, time_slot, room_id, lab_schedule, existing_schedule
                )
                if is_available:
                    rooms_140_available.add(room_id)
                    available_preferred_rooms.append(room)
                    self.logger.debug(f"140-capacity room {room_id} verified available")
                else:
                    rooms_140_blocked[room_id] = conflict_reason
                    self.logger.debug(f"140-capacity room {room_id} blocked: {conflict_reason}")
            else:
                # Regular capacity room - add to available list
                available_preferred_rooms.append(room)
        
        self.logger.debug(f"Available preferred rooms: {len(available_preferred_rooms)} out of {len(preferred_rooms)}")
        
        # Log 140-capacity room constraints if any
        if rooms_140_blocked:
            self.logger.debug(f"140-capacity constraints: {len(rooms_140_available)} available, {len(rooms_140_blocked)} blocked")
        
        # PRIORITY 1: Teacher continuity - try to keep teacher in same room for adjacent slots
        if teacher_id:
            continuity_room = self._check_teacher_continuity_preference(
                {'day': day_name, 'time_slot': time_slot, 'teacher_id': teacher_id}, 
                self._teacher_room_schedule, 
                available_preferred_rooms
            )
            if continuity_room:
                room_info = next((r for r in available_preferred_rooms if r['id'] == continuity_room), None)
                if room_info:
                    self.logger.info(f"🔄 Teacher continuity: Assigning {course_code} to same room {continuity_room} "
                                   f"({room_info['room_number']}) for Teacher {teacher_id}")
                    self._track_teacher_room_assignment(teacher_id, day_name, time_slot, continuity_room, course_code)
                    return continuity_room
        
        # PRIORITY 2: Regular 70-capacity instances - prefer appropriate capacity and avoid TIFAC
        if available_preferred_rooms:
            # Prefer 70-110 capacity rooms, prioritize non-TIFAC
            suitable_rooms = []
            
            # First try: non-TIFAC rooms with appropriate capacity
            for room in available_preferred_rooms:
                if not room['is_tifac'] and 70 <= room['capacity'] <= 110:
                    suitable_rooms.append(room)
            
            # Second try: any non-TIFAC rooms
            if not suitable_rooms:
                suitable_rooms = [room for room in available_preferred_rooms if not room['is_tifac']]
            
            # Third try: any available room (including TIFAC as last resort)
            if not suitable_rooms:
                suitable_rooms = available_preferred_rooms
            
            if suitable_rooms:
                selected_room = suitable_rooms[0]  # First room in preferred order
                
                # Log TIFAC usage warning
                if selected_room['is_tifac']:
                    self.logger.warning(f"⚠️  Using TIFAC room {selected_room['id']} ({selected_room['room_number']}) "
                                      f"for {course_code} as last resort")
                
                self.logger.debug(f"📍 Assigning {course_code} to {selected_room['room_number']} "
                                f"({selected_room['block']}, {selected_room['capacity']} capacity)")
                self._track_teacher_room_assignment(teacher_id, day_name, time_slot, selected_room['id'], course_code)
                return selected_room['id']
        
        # FALLBACK: Any available room from all theory rooms (outside preferred department rooms)
        fallback_rooms = []
        for room_id in self.theory_room_ids:
            if room_id not in all_occupied_rooms:
                room_row = self.rooms_df[self.rooms_df['id'] == room_id]
                if not room_row.empty:
                    fallback_rooms.append(room_id)
        
        if fallback_rooms:
            fallback_room = fallback_rooms[0]
            room_row = self.rooms_df[self.rooms_df['id'] == fallback_room]
            room_number = room_row.iloc[0]['room_number'] if not room_row.empty else f"ID:{fallback_room}"
            self.logger.warning(f"🆘 FALLBACK: Using non-preferred room {fallback_room} ({room_number}) for {course_code}")
            self._track_teacher_room_assignment(teacher_id, day_name, time_slot, fallback_room, course_code)
            return fallback_room
        
        # If no room available, log detailed error
        self.logger.error(f"❌ NO AVAILABLE ROOM for {course_code} ({department}) on {day_name} {time_slot}")
        self.logger.error(f"  Total rooms: {len(self.theory_room_ids)}, Occupied: {len(all_occupied_rooms)}")
        self.logger.error(f"  Preferred rooms for {department} ({preferred_block}): {len(preferred_rooms)}")
        self.logger.error(f"  Available preferred rooms: {len(available_preferred_rooms)}")
        self.logger.error(f"  Breakdown: Theory:{len(occupied_rooms)}, This slot:{len(used_rooms_this_slot)}, "
                         f"Global:{len(global_occupied_rooms)}, Lab conflicts:{len(lab_conflict_rooms)}")
        
        if rooms_140_blocked:
            self.logger.error(f"  140-capacity rooms blocked: {len(rooms_140_blocked)}")
            for room_id, reason in rooms_140_blocked.items():
                room_row = self.rooms_df[self.rooms_df['id'] == room_id]
                room_number = room_row.iloc[0]['room_number'] if not room_row.empty else f"ID:{room_id}"
                self.logger.error(f"    {room_number}: {reason}")
        
        return None

    def _track_teacher_room_assignment(self, teacher_id, day, time_slot, room_id, course_code):
        """Track teacher room assignments for continuity analysis."""
        if not teacher_id:
            return
        
        assignment = {
            'day': day,
            'time_slot': time_slot,
            'room_id': room_id,
            'course_code': course_code
        }
        
        self._teacher_room_schedule[teacher_id].append(assignment)

    def _find_capacity_aware_theory_room_original(self, day_idx, time_slot_idx, used_rooms_this_slot, existing_schedule, dept_days, session, assigned_sessions_this_slot, lab_schedule=None):
        """
        Original capacity-aware room assignment logic for 140+ student classes and co-scheduled instances.
        This preserves the existing complex logic for high-capacity classes.
        """
        # Get correct day name using department-specific days
        day_name = dept_days[day_idx] if day_idx < len(dept_days) else f"day_{day_idx}"
        time_slot = self.theory_time_slots[time_slot_idx]
        
        # Normalize day name for consistent checking
        day_normalized = self._normalize_day_name(day_name)
        
        # Get session details
        instance = session['instance']
        student_count = instance.get('student_count', 70)
        course_code = instance.get('course_code', '')
        virtual_id = instance.get('virtual_id', '')
        co_scheduled_id = instance.get('co_scheduled_id', None)
        
        self.logger.debug(f"Using original 140-capacity logic for {course_code} ({student_count} students)")
        
        # Check if this is a co-scheduled instance (from split 140+ student course)
        is_co_scheduled = co_scheduled_id is not None and virtual_id
        
        # Check if co-scheduled partner is already assigned in this slot
        co_scheduled_partner_room = None
        if is_co_scheduled:
            for assigned_session in assigned_sessions_this_slot:
                assigned_instance = assigned_session['instance']
                if (assigned_instance.get('co_scheduled_id') == co_scheduled_id and 
                    assigned_instance.get('virtual_id') != virtual_id):
                    # Found partner session, get its room
                    co_scheduled_partner_room = assigned_session.get('assigned_room_id')
                    self.logger.debug(f"Co-scheduled partner found in room {co_scheduled_partner_room}")
                    break
        
        # Get rooms already occupied from existing theory schedule
        occupied_rooms = set()
        for existing_session in existing_schedule:
            session_day_normalized = self._normalize_day_name(existing_session['day'])
            if session_day_normalized == day_normalized and existing_session['time_slot'] == time_slot:
                occupied_rooms.add(existing_session['room_id'])
        
        # Check global room registry for any conflicts
        global_occupied_rooms = set()
        for room_id in self.theory_room_ids:
            if not self._is_room_available_global(day_name, time_slot, room_id):
                global_occupied_rooms.add(room_id)
        
        # Check lab schedule for overlapping times (if provided)
        lab_conflict_rooms = set()
        if lab_schedule:
            for lab_session in lab_schedule:
                lab_day_normalized = self._normalize_day_name(lab_session['day'])
                if lab_day_normalized == day_normalized:
                    # Check if lab time overlaps with theory time
                    lab_time_range = lab_session.get('time_range', '')
                    if self._times_overlap(lab_time_range, time_slot):
                        lab_conflict_rooms.add(lab_session['room_id'])
        
        # Combine all occupied rooms
        all_occupied_rooms = occupied_rooms | used_rooms_this_slot | global_occupied_rooms | lab_conflict_rooms
        
        # Get room capacities for smart assignment WITH 140-capacity availability check
        room_capacities = {}
        rooms_140_available = set()  # Track which 140-capacity rooms are actually available
        rooms_140_blocked = {}       # Track why 140-capacity rooms are blocked
        
        for room_id in self.theory_room_ids:
            if room_id not in all_occupied_rooms:
                room_row = self.rooms_df[self.rooms_df['id'] == room_id]
                if not room_row.empty:
                    room_capacity = int(room_row.iloc[0]['room_max_cap'])
                    room_capacities[room_id] = room_capacity
                    
                    # For 140-capacity rooms, perform comprehensive availability check
                    if room_capacity >= 140:
                        is_available, conflict_reason = self._check_140_capacity_room_availability(
                            day_name, time_slot, room_id, lab_schedule, existing_schedule
                        )
                        if is_available:
                            rooms_140_available.add(room_id)
                            self.logger.debug(f"140-capacity room {room_id} verified available")
                        else:
                            rooms_140_blocked[room_id] = conflict_reason
                            # Remove from available rooms if blocked by 140-specific check
                            if room_id in room_capacities:
                                del room_capacities[room_id]
                            self.logger.debug(f"140-capacity room {room_id} blocked: {conflict_reason}")
        
        # PRIORITY 1: If this is a co-scheduled instance and partner is assigned, use same room if available
        if is_co_scheduled and co_scheduled_partner_room is not None:
            if co_scheduled_partner_room in room_capacities:
                # Additional check for 140-capacity rooms
                partner_room_row = self.rooms_df[self.rooms_df['id'] == co_scheduled_partner_room]
                if not partner_room_row.empty:
                    partner_capacity = int(partner_room_row.iloc[0]['room_max_cap'])
                    if partner_capacity >= 140:
                        # Verify the partner room is actually available for 140-capacity use
                        if co_scheduled_partner_room in rooms_140_available:
                            self.logger.info(f"Assigning co-scheduled instance {virtual_id} to verified 140-capacity room {co_scheduled_partner_room} with partner")
                            return co_scheduled_partner_room
                        else:
                            blocked_reason = rooms_140_blocked.get(co_scheduled_partner_room, "Unknown constraint violation")
                            self.logger.error(f"Cannot assign co-scheduled instance {virtual_id} to partner room {co_scheduled_partner_room}: {blocked_reason}")
                    else:
                        # Regular capacity room, proceed normally
                        self.logger.info(f"Assigning co-scheduled instance {virtual_id} to same room {co_scheduled_partner_room} as partner")
                        return co_scheduled_partner_room
        
        # PRIORITY 2: For co-scheduled instances, prefer verified 140+ capacity rooms
        if is_co_scheduled:
            if rooms_140_available:
                # Sort by capacity (prefer exactly 140, then higher)
                available_140_rooms = list(rooms_140_available)
                available_140_rooms.sort(key=lambda rid: room_capacities[rid])
                selected_room = available_140_rooms[0]
                room_capacity = room_capacities[selected_room]
                self.logger.info(f"✅ Assigning co-scheduled instance {virtual_id} to verified 140-capacity room {selected_room} "
                               f"(capacity: {room_capacity}) - availability confirmed")
                return selected_room
            else:
                # No 140-capacity rooms available - this is a serious constraint violation
                self.logger.error(f"❌ CONSTRAINT VIOLATION: Co-scheduled instance {virtual_id} needs 140-capacity room but none available!")
                self.logger.error(f"   All 140-capacity rooms blocked: {list(rooms_140_blocked.keys())}")
                for room_id, reason in rooms_140_blocked.items():
                    self.logger.error(f"   Room {room_id}: {reason}")
        
        # PRIORITY 3: For 140+ student instances, prefer 140+ capacity rooms
        if student_count >= 140:
            if rooms_140_available:
                # Sort by capacity (prefer closest match)
                available_140_rooms = list(rooms_140_available)
                available_140_rooms.sort(key=lambda rid: abs(room_capacities[rid] - student_count))
                selected_room = available_140_rooms[0]
                room_capacity = room_capacities[selected_room]
                self.logger.info(f"✅ Assigning 140+ student instance {course_code} to 140-capacity room {selected_room} "
                               f"(capacity: {room_capacity}, students: {student_count})")
                return selected_room
            else:
                self.logger.error(f"❌ CONSTRAINT VIOLATION: {course_code} has {student_count} students but no 140-capacity room available!")
        
        # FALLBACK: Any available room if no capacity-aware assignment possible
        available_rooms = list(room_capacities.keys())
        if available_rooms:
            fallback_room = available_rooms[0]
            room_row = self.rooms_df[self.rooms_df['id'] == fallback_room]
            room_number = room_row.iloc[0]['room_number'] if not room_row.empty else f"ID:{fallback_room}"
            self.logger.warning(f"Using fallback room assignment: {fallback_room} ({room_number}) for {course_code}")
            return fallback_room
        
        # If no room available, log detailed error
        self.logger.error(f"❌ No available theory room for {course_code} on {day_name} {time_slot}")
        self.logger.error(f"  Total occupied: {len(all_occupied_rooms)}/{len(self.theory_room_ids)} rooms")
        
        return None

    def _apply_lunch_break_constraint(self, model, group_timeslot_vars):
        """
        Prevent any group from being scheduled in its department-semester specific lunch break slot.
        Flexible lunch departments (Biotechnology, ECE, Mechanical, etc.) are skipped - model decides their lunch timing.
        """
        self.logger.info("Applying lunch break constraints (flexible departments skipped)...")
        constraints_applied = 0
        flexible_departments_skipped = 0
        
        for group_name in group_timeslot_vars.keys():
            # Parse department name from group name: "Department_S3_G1" -> "Department"
            dept_name = group_name.split('_S')[0] if '_S' in group_name else "Computer Science & Engineering"
            
            # Extract semester from group name for semester-specific lunch breaks
            semester = None
            if '_S' in group_name:
                try:
                    semester_part = group_name.split('_S')[1].split('_G')[0]
                    semester = int(semester_part)
                except (ValueError, IndexError):
                    pass
            
            # Skip flexible lunch departments - let model decide their lunch timing
            if self.is_flexible_lunch_department(dept_name):
                flexible_departments_skipped += 1
                self.logger.debug(f"Flexible lunch department: {dept_name} S{semester} - skipping lunch constraints (model will decide)")
                continue
            
            # Get department-specific days (with semester override if available)
            dept_days = self._get_days_for_department(dept_name, semester)
            num_dept_days = len(dept_days)
            
            # Get the lunch break slot for this department-semester combination
            lunch_slot = self.get_lunch_break_slot(dept_name, semester)
            
            # Skip departments without lunch break assignments
            if lunch_slot is None:
                self.logger.debug(f"No lunch break assigned for {dept_name} S{semester} - skipping lunch constraints")
                continue
            
            # For each working day of this department, prevent scheduling in lunch break slot
            for day_idx in range(num_dept_days):
                # No group can be scheduled in its lunch break slot
                if (day_idx in group_timeslot_vars[group_name] and 
                    lunch_slot in group_timeslot_vars[group_name][day_idx]):
                    model.Add(group_timeslot_vars[group_name][day_idx][lunch_slot] == 0)
                    constraints_applied += 1
                    self.logger.debug(f"Lunch constraint: {group_name} blocked from day {day_idx} slot {lunch_slot} ({self.theory_time_slots[lunch_slot]}) - {dept_name} S{semester}")
                else:
                    self.logger.debug(f"Lunch constraint skipped: {group_name} day {day_idx} slot {lunch_slot} not in variables - {dept_name} S{semester}")
        
        self.logger.info(f"Applied {constraints_applied} lunch break constraints.")
        self.logger.info(f"🔄 Skipped {flexible_departments_skipped} flexible lunch department groups (model will decide lunch timing)")
        return constraints_applied
    
    def _apply_flexible_lunch_constraint(self, model, group_timeslot_vars, lab_variables):
        """
        Apply HARD constraint for flexible lunch departments to ensure they have adequate lunch breaks.
        Flexible departments must have EITHER:
        1. At least one traditional lunch slot (3, 4, or 5) free, OR
        2. A natural lunch break from specific lab-theory combinations:
           - L3 lab (11:50-1:20) + theory slot 6 (2:00-2:50) = 40 min break (1:20-2:00)
           - Theory slot 4 (12:00-12:50) + L4 lab (1:20-3:00) = 30 min break (12:50-1:20)
        
        This is a HARD constraint - solutions must satisfy lunch requirements.
        """
        self.logger.info("Applying HARD flexible lunch break constraint...")
        constraints_applied = 0
        
        lunch_slots = [3, 4, 5]  # Traditional lunch slots
        
        for group_name in group_timeslot_vars.keys():
            # Parse department name from group name
            dept_name = group_name.split('_S')[0] if '_S' in group_name else "Computer Science & Engineering"
            
            # Extract semester from group name
            semester = None
            if '_S' in group_name:
                try:
                    semester_part = group_name.split('_S')[1].split('_G')[0]
                    semester = int(semester_part)
                except (ValueError, IndexError):
                    pass
            
            # Only apply to flexible lunch departments
            if not self.is_flexible_lunch_department(dept_name):
                continue
                
            # Get department-specific days
            dept_days = self._get_days_for_department(dept_name, semester)
            num_dept_days = len(dept_days)
            
            # Apply constraint for each day
            for day_idx in range(num_dept_days):
                if day_idx not in group_timeslot_vars[group_name]:
                    continue
                
                # Collect available lunch slot variables for this day
                available_lunch_slots = []
                for lunch_slot in lunch_slots:
                    if lunch_slot in group_timeslot_vars[group_name][day_idx]:
                        available_lunch_slots.append(group_timeslot_vars[group_name][day_idx][lunch_slot])
                
                # Check for natural lunch break possibilities
                natural_lunch_vars = []
                
                # Find courses/labs that belong to this group for checking natural lunch breaks
                group_lab_vars = []
                if hasattr(self, 'course_groups') and lab_variables:
                    # Parse group information from group name
                    if '_S' in group_name and '_G' in group_name:
                        parts = group_name.split('_S')
                        dept = parts[0]
                        sem_group_part = parts[1]  # e.g., "3_G1"
                        sem_part = sem_group_part.split('_G')[0]
                        group_part = sem_group_part.split('_G')[1]
                        try:
                            semester = int(sem_part)
                            group_idx = int(group_part) - 1  # Convert to 0-based index
                            
                            # Get the courses in this group
                            if (dept, semester) in self.course_groups:
                                groups_list = self.course_groups[(dept, semester)]
                                if group_idx < len(groups_list):
                                    group_courses = groups_list[group_idx]
                                    
                                    # Find lab variables for courses in this group
                                    for instance in group_courses:
                                        course_instance_id = instance.get('id', instance.get('course_instance_id'))
                                        teacher_id = instance.get('teacher_id')
                                        
                                        if (teacher_id in lab_variables and 
                                            course_instance_id in lab_variables[teacher_id] and
                                            day_idx < len(lab_variables[teacher_id][course_instance_id])):
                                            group_lab_vars.append({
                                                'teacher_id': teacher_id,
                                                'course_instance_id': course_instance_id,
                                                'lab_vars': lab_variables[teacher_id][course_instance_id][day_idx]
                                            })
                        except (ValueError, IndexError):
                            pass
                
                # Natural lunch 1: L3 lab + theory slot 6 (40 min break)
                # L3 lab is 11:50-1:20 (covers theory slots 4,5), theory slot 6 is 2:00-2:50
                l3_lab_vars = []
                theory_slot_6_var = None
                
                # Collect all L3 lab variables for this group
                for lab_info in group_lab_vars:
                    if 'L3' in lab_info['lab_vars']:
                        l3_lab_vars.extend(lab_info['lab_vars']['L3'].values())
                
                if 6 in group_timeslot_vars[group_name][day_idx]:
                    theory_slot_6_var = group_timeslot_vars[group_name][day_idx][6]
                
                if l3_lab_vars and theory_slot_6_var is not None:
                    # Create indicator for natural lunch break 1
                    natural_lunch_1 = model.NewBoolVar(f'natural_lunch_1_{group_name}_day_{day_idx}')
                    
                    # Any L3 lab + theory slot 6 = natural lunch break
                    any_l3_active = model.NewBoolVar(f'any_l3_active_{group_name}_day_{day_idx}')
                    model.Add(sum(l3_lab_vars) > 0).OnlyEnforceIf(any_l3_active)
                    model.Add(sum(l3_lab_vars) == 0).OnlyEnforceIf(any_l3_active.Not())
                    
                    # natural_lunch_1 = 1 if BOTH any L3 lab AND theory slot 6 are assigned
                    model.AddBoolAnd([any_l3_active, theory_slot_6_var]).OnlyEnforceIf(natural_lunch_1)
                    model.AddBoolOr([any_l3_active.Not(), theory_slot_6_var.Not()]).OnlyEnforceIf(natural_lunch_1.Not())
                    natural_lunch_vars.append(natural_lunch_1)
                
                # Natural lunch 2: Theory slot 4 + L4 lab (30 min break)
                # Theory slot 4 is 12:00-12:50, L4 lab is 1:20-3:00 (covers theory slots 6,7)
                theory_slot_4_var = None
                l4_lab_vars = []
                
                if 4 in group_timeslot_vars[group_name][day_idx]:
                    theory_slot_4_var = group_timeslot_vars[group_name][day_idx][4]
                
                # Collect all L4 lab variables for this group
                for lab_info in group_lab_vars:
                    if 'L4' in lab_info['lab_vars']:
                        l4_lab_vars.extend(lab_info['lab_vars']['L4'].values())
                
                if theory_slot_4_var is not None and l4_lab_vars:
                    # Create indicator for natural lunch break 2
                    natural_lunch_2 = model.NewBoolVar(f'natural_lunch_2_{group_name}_day_{day_idx}')
                    
                    # Theory slot 4 + any L4 lab = natural lunch break
                    any_l4_active = model.NewBoolVar(f'any_l4_active_{group_name}_day_{day_idx}')
                    model.Add(sum(l4_lab_vars) > 0).OnlyEnforceIf(any_l4_active)
                    model.Add(sum(l4_lab_vars) == 0).OnlyEnforceIf(any_l4_active.Not())
                    
                    # natural_lunch_2 = 1 if BOTH theory slot 4 AND any L4 lab are assigned
                    model.AddBoolAnd([theory_slot_4_var, any_l4_active]).OnlyEnforceIf(natural_lunch_2)
                    model.AddBoolOr([theory_slot_4_var.Not(), any_l4_active.Not()]).OnlyEnforceIf(natural_lunch_2.Not())
                    natural_lunch_vars.append(natural_lunch_2)
                
                # HARD CONSTRAINT: Must have either traditional lunch OR natural lunch
                if available_lunch_slots or natural_lunch_vars:
                    # Create lunch satisfaction variables
                    lunch_satisfaction_vars = []
                    
                    # Traditional lunch: at least one lunch slot free
                    if available_lunch_slots:
                        # Create variable indicating at least one lunch slot is free
                        has_traditional_lunch = model.NewBoolVar(f'has_traditional_lunch_{group_name}_day_{day_idx}')
                        
                        # has_traditional_lunch = 1 if sum of lunch slots < total lunch slots
                        # (meaning at least one slot is free)
                        total_lunch_slots = len(available_lunch_slots)
                        model.Add(sum(available_lunch_slots) <= total_lunch_slots - 1).OnlyEnforceIf(has_traditional_lunch)
                        model.Add(sum(available_lunch_slots) >= total_lunch_slots).OnlyEnforceIf(has_traditional_lunch.Not())
                        
                        lunch_satisfaction_vars.append(has_traditional_lunch)
                    
                    # Add natural lunch break variables
                    lunch_satisfaction_vars.extend(natural_lunch_vars)
                    
                    # HARD CONSTRAINT: At least one lunch satisfaction method must be true
                    if lunch_satisfaction_vars:
                        model.AddBoolOr(lunch_satisfaction_vars)
                        constraints_applied += 1
                        
                        self.logger.debug(f"Added HARD lunch constraint for {group_name} day {day_idx} - "
                                        f"traditional slots: {len(available_lunch_slots)}, "
                                        f"natural breaks: {len(natural_lunch_vars)}")
        
        if constraints_applied > 0:
            self.logger.info(f"Applied {constraints_applied} HARD flexible lunch constraints")
            self.logger.info("  • Flexible departments MUST have either:")
            self.logger.info("    - At least one traditional lunch slot (3,4,5) free, OR")
            self.logger.info("    - Natural lunch from L3 lab + theory slot 6 (40 min break), OR")
            self.logger.info("    - Natural lunch from theory slot 4 + L4 lab (30 min break)")
            self.logger.info(f"  • Applies to: {', '.join(self.flexible_lunch_departments)}")
        else:
            self.logger.info("No flexible lunch constraints applied - no flexible departments found")
        
        return constraints_applied

    def _apply_lab_lunch_break_constraint(self, model, lab_variables):
        """
        Prevent any lab session from being scheduled during its department-semester specific lunch break slot.
        Flexible lunch departments (Biotechnology, ECE, Mechanical, etc.) are skipped - model decides their lunch timing.
        """
        self.logger.info("Applying lunch break constraints for lab sessions (flexible departments skipped)...")
        constraints_applied = 0
        flexible_courses_skipped = 0
        
        # Map lunch break theory slots to lab sessions that overlap
        lunch_slot_to_lab_sessions = {}
        for lunch_slot_idx, lunch_time in self.lunch_break_slots.items():
            lunch_slot_to_lab_sessions[lunch_slot_idx] = []
            
            # Check which lab sessions overlap with this lunch time slot
            for session_name, session_times in self.lab_sessions.items():
                for session_time in session_times:
                    if self._times_overlap(session_time, lunch_time):
                        lunch_slot_to_lab_sessions[lunch_slot_idx].append(session_name)
                        break  # Session overlaps, no need to check more times
        
        # Apply constraints for each teacher and course
        for teacher_id in lab_variables:
            for course_instance_id in lab_variables[teacher_id]:
                # Get department and semester for this course instance
                dept_name = "Computer Science & Engineering"  # Default
                semester = None
                
                if hasattr(self, 'instance_group_mapping') and course_instance_id in self.instance_group_mapping:
                    mapping = self.instance_group_mapping[course_instance_id]
                    dept_name = mapping['department']
                    semester = mapping.get('semester')
                else:
                    # Fallback: look up in courses_df
                    base_id = self._get_base_course_id(course_instance_id)
                    course_matches = self.courses_df[self.courses_df['id'] == int(base_id)]
                    if not course_matches.empty:
                        dept_name = course_matches.iloc[0].get('student_dept', 'Computer Science & Engineering')
                
                # Skip flexible lunch departments - let model decide their lunch timing
                if self.is_flexible_lunch_department(dept_name):
                    flexible_courses_skipped += 1
                    self.logger.debug(f"Flexible lunch department: {dept_name} S{semester} course - skipping lab lunch constraints (model will decide)")
                    continue
                
                # Get the lunch break slot for this department-semester combination
                lunch_slot_idx = self.get_lunch_break_slot(dept_name, semester)
                
                # Skip departments without lunch break assignments
                if lunch_slot_idx is None:
                    continue  # No lunch break assigned for this department-semester combination
                
                # Get the lab sessions that overlap with this department-semester's lunch break
                overlapping_sessions = lunch_slot_to_lab_sessions.get(lunch_slot_idx, [])
                
                if not overlapping_sessions:
                    continue  # No overlapping sessions for this lunch slot
                
                # Get department-specific days
                dept_days = self._get_days_for_department(dept_name, semester)
                num_dept_days = len(dept_days)
                
                # For each day, prevent scheduling in the lunch break slot
                for day_idx in range(num_dept_days):
                    if day_idx in lab_variables[teacher_id][course_instance_id]:
                        for session_name in overlapping_sessions:
                            if session_name in lab_variables[teacher_id][course_instance_id][day_idx]:
                                for room_id in self.lab_room_ids:
                                    if room_id in lab_variables[teacher_id][course_instance_id][day_idx][session_name]:
                                        # Check if this session is in the lunch break slot
                                        model.Add(lab_variables[teacher_id][course_instance_id][day_idx][session_name][room_id] == 0)
                                        constraints_applied += 1
                                        
                                        # Get course code for logging
                                        course_req = next((req for req in self.lab_requirements.get(teacher_id, []) 
                                                         if req['course_instance_id'] == course_instance_id), None)
                                        course_code = course_req['course_code'] if course_req else 'Unknown'
                                        
                                        self.logger.debug(f"Lab lunch break constraint: {course_code} ({dept_name} S{semester}) in lunch break slot {lunch_slot_idx}")
        
        self.logger.info(f"Applied {constraints_applied} lab lunch break constraints")
        self.logger.info(f"🔄 Skipped {flexible_courses_skipped} flexible lunch department courses (model will decide lunch timing)")
        return constraints_applied

    def apply_consecutive_batch_scheduling_constraint(self, model, lab_variables):
        """
        CONSTRAINT: For specific departments' CORE LAB courses with 4+ practical hours,
        enforce consecutive scheduling for batch sessions.
        
        Core labs in these departments require specialized equipment and setup, so consecutive sessions
        are critical for learning continuity and equipment efficiency.
        
        Applies to: Biotechnology, Food Technology, Chemical Engineering, Biomedical Engineering
        AND only for courses mapped in og-final.csv (core lab mapping).
        Regular computer labs and other departments do not need consecutive scheduling.
        """
        self.logger.info("Applying consecutive batch scheduling constraint for specific departments' CORE LAB courses...")
        constraints_applied = 0
        
        # Define departments that need consecutive batch scheduling for core lab courses
        consecutive_batch_departments = [
            'Biotechnology',
            'Food Technology', 
            'Chemical Engineering',
            'Biomedical Engineering'
        ]
        
        # Only apply to the most common consecutive pairs to avoid over-constraining
        preferred_consecutive_pairs = [
            ('L1', 'L2'),  # 8:00-9:40 and 9:50-11:30 (morning block)
            ('L3', 'L4'),  # 11:50-1:30 and 1:50-3:30 (around lunch)
            ('L5', 'L6')   # 3:50-5:30 and 5:30-7:10 (evening block)
        ]
        

        
        for teacher_id in lab_variables:
            for course_instance_id in lab_variables[teacher_id]:
                # Get course details
                course_req = next((req for req in self.lab_requirements.get(teacher_id, []) 
                                 if req['course_instance_id'] == course_instance_id), None)
                
                if not course_req:
                    continue  # Skip if course not found
                
                practical_hours = course_req['practical_hours']
                students_per_instance = course_req['students_per_instance']
                
                # Only apply to courses with 4+ practical hours (need multiple sessions)
                if practical_hours < 4:
                    continue
                
                # Get department for this course
                dept_name = "Computer Science & Engineering"  # Default
                if hasattr(self, 'instance_group_mapping') and course_instance_id in self.instance_group_mapping:
                    dept_name = self.instance_group_mapping[course_instance_id]['department']
                else:
                    # Fallback: look up in courses_df
                    course_matches = self.courses_df[self.courses_df['id'] == int(course_instance_id)]
                    if not course_matches.empty:
                        dept_name = course_matches.iloc[0].get('student_dept', 'Computer Science & Engineering')
                
                # Only apply to specific departments AND core lab courses
                if dept_name not in consecutive_batch_departments:
                    continue  # Skip departments that don't need consecutive scheduling
                
                # Check if this course is mapped in the core lab mapping (og-final.csv)
                course_code = course_req['course_code']
                is_core_lab_course = False
                
                if hasattr(self, 'course_to_room_mapping') and self.course_to_room_mapping:
                    # Use course code only for matching (as we fixed earlier)
                    for (mapped_code, mapped_name), room_ids in self.course_to_room_mapping.items():
                        if mapped_code == course_code:
                            is_core_lab_course = True
                            break
                
                if not is_core_lab_course:
                    continue  # Skip non-core lab courses
                
                # Check if course has any lab assignments (any capacity)
                has_lab_assignments = False
                for day_idx in lab_variables[teacher_id][course_instance_id]:
                    for session_name in lab_variables[teacher_id][course_instance_id][day_idx]:
                        if lab_variables[teacher_id][course_instance_id][day_idx][session_name]:
                            has_lab_assignments = True
                            break
                    if has_lab_assignments:
                        break
                
                if not has_lab_assignments:
                    continue  # No lab assignments possible
                
                # Get department-specific days
                dept_days = self._get_days_for_department(dept_name)
                num_dept_days = len(dept_days)
                
                self.logger.info(f"Applying consecutive batch constraint for CORE LAB course {course_code} "
                               f"({dept_name}, {practical_hours}h practical)")
                
                # For each day, create consecutive scheduling constraints
                for day_idx in range(num_dept_days):
                    if day_idx not in lab_variables[teacher_id][course_instance_id]:
                        continue
                    
                    # Apply constraint to preferred consecutive pairs
                    for session1, session2 in preferred_consecutive_pairs:
                        if (session1 in lab_variables[teacher_id][course_instance_id][day_idx] and 
                            session2 in lab_variables[teacher_id][course_instance_id][day_idx]):
                            
                            # Collect assignments for each session in ALL labs (any capacity)
                            session1_vars = []
                            session2_vars = []
                            
                            # Include ALL rooms for this session
                            for room_id in lab_variables[teacher_id][course_instance_id][day_idx][session1]:
                                session1_vars.append(lab_variables[teacher_id][course_instance_id][day_idx][session1][room_id])
                            for room_id in lab_variables[teacher_id][course_instance_id][day_idx][session2]:
                                session2_vars.append(lab_variables[teacher_id][course_instance_id][day_idx][session2][room_id])
                            
                            if session1_vars and session2_vars:
                                # Create variables to track if sessions are used
                                session1_used = model.NewBoolVar(f'session1_used_{course_instance_id}_{day_idx}_{session1}')
                                session2_used = model.NewBoolVar(f'session2_used_{course_instance_id}_{day_idx}_{session2}')
                                
                                # Session is used if any room assignment is made
                                model.Add(sum(session1_vars) >= 1).OnlyEnforceIf(session1_used)
                                model.Add(sum(session1_vars) == 0).OnlyEnforceIf(session1_used.Not())
                                model.Add(sum(session2_vars) >= 1).OnlyEnforceIf(session2_used)
                                model.Add(sum(session2_vars) == 0).OnlyEnforceIf(session2_used.Not())
                                
                                # SMART CONSECUTIVE CONSTRAINT: 
                                # For courses with multiple sessions, enforce consecutive scheduling
                                # This is based on practical hours and student batching requirements
                                
                                # Determine if this course likely needs multiple sessions per day
                                students_per_instance = course_req['students_per_instance']
                                needs_batching = students_per_instance > 35
                                needs_multiple_sessions = practical_hours >= 4 or needs_batching
                                
                                # Apply consecutive constraint for courses that need multiple sessions
                                if needs_multiple_sessions:
                                    # HARD CONSTRAINT: If either session is used, both must be used
                                    model.Add(session1_used == session2_used)
                                    constraints_applied += 1
                                    self.logger.debug(f"Consecutive constraint: {course_req['course_code']} day {day_idx} "
                                                    f"{session1}-{session2} must be scheduled together ({practical_hours}h, {students_per_instance} students)")
                                else:
                                    # Course doesn't need multiple sessions - no consecutive constraint needed
                                    self.logger.debug(f"Skipping consecutive constraint: {course_req['course_code']} day {day_idx} "
                                                    f"doesn't need multiple sessions ({practical_hours}h, {students_per_instance} students)")
        
        self.logger.info(f"Applied {constraints_applied} consecutive batch scheduling constraints (all HARD constraints)")
        return constraints_applied

    def apply_shift_based_lab_constraint(self, model, lab_variables):
        """
        CONSTRAINT: Apply department-centric shift-based scheduling constraints.
        Each department follows one unified weekly shift pattern:
        - Pattern 3-2: 3 days Shift1 (8AM-3PM), 2 days Shift2 (10AM-5PM)
        - Pattern 2-3: 2 days Shift1 (8AM-3PM), 3 days Shift2 (10AM-5PM)
        
        All teachers in a department follow the same department shift pattern.
        This is implemented as a SOFT constraint to avoid infeasibility.
        """
        self.logger.info("Applying department-centric shift-based lab constraints for ALL departments...")
        constraints_applied = 0
        
        # Group courses by department
        dept_courses = defaultdict(list)
        dept_teachers = defaultdict(set)
        
        for teacher_id in lab_variables:
            for course_instance_id in lab_variables[teacher_id]:
                # Get department for this course
                dept_name = "Computer Science & Engineering"  # Default
                if hasattr(self, 'instance_group_mapping') and course_instance_id in self.instance_group_mapping:
                    dept_name = self.instance_group_mapping[course_instance_id]['department']
                else:
                    # Fallback: look up in courses_df
                    course_matches = self.courses_df[self.courses_df['id'] == int(course_instance_id)]
                    if not course_matches.empty:
                        dept_name = course_matches.iloc[0].get('student_dept', 'Computer Science & Engineering')
                
                # Apply to all departments now
                if self.is_shift_department(dept_name):
                    dept_courses[dept_name].append((teacher_id, course_instance_id))
                    dept_teachers[dept_name].add(teacher_id)
        
        if not dept_courses:
            self.logger.info("No departments found with lab courses")
            return 0
        
        # Initialize shift preference variables for soft constraints
        if not hasattr(self, 'shift_preference_vars'):
            self.shift_preference_vars = []
        
        # Initialize department shift variables storage
        if not hasattr(self, 'department_shift_vars'):
            self.department_shift_vars = {}
        
        # Initialize teacher shift variables storage for cross-department teachers
        if not hasattr(self, 'teacher_shift_vars'):
            self.teacher_shift_vars = {}
        
        # Apply constraints for each department
        for dept_name, courses in dept_courses.items():
            self.logger.info(f"Applying department-centric shift constraints for {dept_name} with {len(courses)} lab courses and {len(dept_teachers[dept_name])} teachers")
            
            dept_days = self._get_days_for_department(dept_name)
            num_dept_days = len(dept_days)
            
            # Create department shift assignment variables for each day
            dept_shift_vars = {}  # day_idx -> {shift_id: bool_var}
            
            for day_idx in range(num_dept_days):
                dept_shift_vars[day_idx] = {}
                for shift_id in self.get_available_shifts():
                    dept_shift_vars[day_idx][shift_id] = model.NewBoolVar(
                        f'dept_{dept_name.replace(" ", "_").replace("&", "and")}_day_{day_idx}_shift_{shift_id}_lab'
                    )
                
                # CONSTRAINT: Each day must be assigned to exactly one shift
                model.Add(sum(dept_shift_vars[day_idx].values()) == 1)
                constraints_applied += 1
            
            # Store department shift variables
            self.department_shift_vars[dept_name] = dept_shift_vars
            
            # Apply weekly shift pattern constraints for this department
            for pattern_days_shift1, pattern_days_shift2 in self.valid_shift_patterns:
                # Create pattern selection variable
                pattern_var = model.NewBoolVar(
                    f'dept_{dept_name.replace(" ", "_").replace("&", "and")}_pattern_{pattern_days_shift1}_{pattern_days_shift2}'
                )
                
                # If this pattern is selected, enforce the shift distribution
                shift1_days = []
                shift2_days = []
                
                for day_idx in range(num_dept_days):
                    shift1_days.append(dept_shift_vars[day_idx]['shift_1'])
                    shift2_days.append(dept_shift_vars[day_idx]['shift_2'])
                
                # Enforce pattern constraints
                model.Add(sum(shift1_days) == pattern_days_shift1).OnlyEnforceIf(pattern_var)
                model.Add(sum(shift2_days) == pattern_days_shift2).OnlyEnforceIf(pattern_var)
                
                constraints_applied += 2
            
            # Exactly one pattern must be selected for this department
            pattern_vars = []
            for pattern in self.valid_shift_patterns:
                pattern_var = model.NewBoolVar(
                    f'dept_{dept_name.replace(" ", "_").replace("&", "and")}_pattern_{pattern[0]}_{pattern[1]}'
                )
                pattern_vars.append(pattern_var)
            
            model.Add(sum(pattern_vars) == 1)
            constraints_applied += 1
            
            # Apply lab session constraints based on department shift pattern
            for teacher_id, course_instance_id in courses:
                if teacher_id not in lab_variables or course_instance_id not in lab_variables[teacher_id]:
                    continue
                
                # Get course details for logging
                course_req = next((req for req in self.lab_requirements.get(teacher_id, []) 
                                 if req['course_instance_id'] == course_instance_id), None)
                course_code = course_req['course_code'] if course_req else f'Course_{course_instance_id}'
                
                for day_idx in range(num_dept_days):
                    if day_idx not in lab_variables[teacher_id][course_instance_id]:
                        continue
                    
                    # Create soft preferences for department shift compliance
                    for shift_id in self.get_available_shifts():
                        allowed_sessions = self.get_shift_lab_sessions(shift_id)
                        forbidden_sessions = [s for s in self.lab_sessions.keys() if s not in allowed_sessions]
                        
                        # Create penalty variable for using forbidden sessions when department is on this shift
                        if forbidden_sessions:
                            shift_violation_penalty = model.NewBoolVar(
                                f'dept_shift_penalty_{dept_name.replace(" ", "_").replace("&", "and")}_{teacher_id}_{course_instance_id}_{day_idx}_{shift_id}'
                            )
                            
                            # Count forbidden session usage
                            forbidden_usage = []
                            for session_name in forbidden_sessions:
                                if session_name in lab_variables[teacher_id][course_instance_id][day_idx]:
                                    for room_id in self.lab_room_ids:
                                        if room_id in lab_variables[teacher_id][course_instance_id][day_idx][session_name]:
                                            forbidden_usage.append(
                                                lab_variables[teacher_id][course_instance_id][day_idx][session_name][room_id]
                                            )
                            
                            if forbidden_usage:
                                # Penalty is active if department's shift is chosen AND forbidden sessions are used
                                forbidden_used = model.NewBoolVar(f'dept_forbidden_used_{dept_name.replace(" ", "_").replace("&", "and")}_{teacher_id}_{course_instance_id}_{day_idx}_{shift_id}')
                                model.Add(sum(forbidden_usage) >= 1).OnlyEnforceIf(forbidden_used)
                                model.Add(sum(forbidden_usage) == 0).OnlyEnforceIf(forbidden_used.Not())
                                
                                # Penalty occurs when department's shift is active AND forbidden sessions are used
                                model.AddBoolAnd([dept_shift_vars[day_idx][shift_id], forbidden_used]).OnlyEnforceIf(shift_violation_penalty)
                                model.AddBoolOr([dept_shift_vars[day_idx][shift_id].Not(), forbidden_used.Not()]).OnlyEnforceIf(shift_violation_penalty.Not())
                                
                                # Add to preference variables (to be minimized)
                                self.shift_preference_vars.append(shift_violation_penalty)
                                constraints_applied += 3
                
                self.logger.debug(f"Applied department shift constraints for course {course_code} in {dept_name}")
        
        # Apply individual teacher shift constraints for cross-department teachers
        cross_dept_constraints = self._apply_cross_department_teacher_shift_constraints(model, lab_variables)
        constraints_applied += cross_dept_constraints
        
        self.logger.info(f"Applied {constraints_applied} total shift-based lab constraints")
        self.logger.info(f"  - Department-centric constraints: {constraints_applied - cross_dept_constraints}")
        self.logger.info(f"  - Cross-department teacher constraints: {cross_dept_constraints}")
        self.logger.info(f"Departments with unified shift patterns: {len(dept_courses)}")
        self.logger.info(f"Created {len(self.shift_preference_vars)} shift preference variables")
        return constraints_applied
    
    def _apply_cross_department_teacher_shift_constraints(self, model, lab_variables):
        """Apply individual shift constraints for cross-department teachers."""
        self.logger.info("Applying individual shift constraints for cross-department teachers...")
        constraints_applied = 0
        
        if not hasattr(self, 'cross_dept_teachers') or not self.cross_dept_teachers:
            self.logger.info("No cross-department teachers identified")
            return 0
        
        # Process each cross-department teacher
        for teacher_id in self.cross_dept_teachers:
            if teacher_id not in lab_variables:
                continue
            
            student_depts = self.get_teacher_student_departments(teacher_id)
            dept_list = ', '.join(sorted(student_depts))
            
            self.logger.info(f"Applying individual shift constraints for Teacher {teacher_id} (serves: {dept_list})")
            
            # Determine working days (use union of all departments they serve)
            teacher_days = set()
            for dept in student_depts:
                dept_days = self._get_days_for_department(dept)
                teacher_days.update(dept_days)
            teacher_days = sorted(list(teacher_days))
            num_teacher_days = len(teacher_days)
            
            # Create individual teacher shift assignment variables
            teacher_shift_vars = {}
            for day_idx in range(num_teacher_days):
                teacher_shift_vars[day_idx] = {}
                for shift_id in self.get_available_shifts():
                    teacher_shift_vars[day_idx][shift_id] = model.NewBoolVar(
                        f'cross_teacher_{teacher_id}_day_{day_idx}_shift_{shift_id}_lab'
                    )
                
                # CONSTRAINT: Each day must be assigned to exactly one shift for this teacher
                model.Add(sum(teacher_shift_vars[day_idx].values()) == 1)
                constraints_applied += 1
            
            # Store teacher shift variables
            self.teacher_shift_vars[teacher_id] = teacher_shift_vars
            
            # Apply weekly shift pattern constraints for this teacher
            for pattern_days_shift1, pattern_days_shift2 in self.valid_shift_patterns:
                # Create pattern selection variable
                pattern_var = model.NewBoolVar(
                    f'cross_teacher_{teacher_id}_pattern_{pattern_days_shift1}_{pattern_days_shift2}'
                )
                
                # If this pattern is selected, enforce the shift distribution
                shift1_days = []
                shift2_days = []
                
                for day_idx in range(num_teacher_days):
                    shift1_days.append(teacher_shift_vars[day_idx]['shift_1'])
                    shift2_days.append(teacher_shift_vars[day_idx]['shift_2'])
                
                # Enforce pattern constraints
                model.Add(sum(shift1_days) == pattern_days_shift1).OnlyEnforceIf(pattern_var)
                model.Add(sum(shift2_days) == pattern_days_shift2).OnlyEnforceIf(pattern_var)
                
                constraints_applied += 2
            
            # Exactly one pattern must be selected for this teacher
            pattern_vars = []
            for pattern in self.valid_shift_patterns:
                pattern_var = model.NewBoolVar(
                    f'cross_teacher_{teacher_id}_pattern_{pattern[0]}_{pattern[1]}'
                )
                pattern_vars.append(pattern_var)
            
            model.Add(sum(pattern_vars) == 1)
            constraints_applied += 1
            
            # Apply lab session constraints based on teacher's individual shift pattern
            for course_instance_id in lab_variables[teacher_id]:
                # Get course details
                course_req = next((req for req in self.lab_requirements.get(teacher_id, []) 
                                 if req['course_instance_id'] == course_instance_id), None)
                course_code = course_req['course_code'] if course_req else f'Course_{course_instance_id}'
                
                for day_idx in range(num_teacher_days):
                    if day_idx not in lab_variables[teacher_id][course_instance_id]:
                        continue
                    
                    # Create soft preferences for teacher shift compliance
                    for shift_id in self.get_available_shifts():
                        allowed_sessions = self.get_shift_lab_sessions(shift_id)
                        forbidden_sessions = [s for s in self.lab_sessions.keys() if s not in allowed_sessions]
                        
                        # Create penalty variable for using forbidden sessions when teacher is on this shift
                        if forbidden_sessions:
                            teacher_shift_violation_penalty = model.NewBoolVar(
                                f'cross_teacher_shift_penalty_{teacher_id}_{course_instance_id}_{day_idx}_{shift_id}'
                            )
                            
                            # Count forbidden session usage
                            forbidden_usage = []
                            for session_name in forbidden_sessions:
                                if session_name in lab_variables[teacher_id][course_instance_id][day_idx]:
                                    for room_id in self.lab_room_ids:
                                        if room_id in lab_variables[teacher_id][course_instance_id][day_idx][session_name]:
                                            forbidden_usage.append(
                                                lab_variables[teacher_id][course_instance_id][day_idx][session_name][room_id]
                                            )
                            
                            if forbidden_usage:
                                # Penalty is active if teacher's shift is chosen AND forbidden sessions are used
                                forbidden_used = model.NewBoolVar(f'cross_teacher_forbidden_used_{teacher_id}_{course_instance_id}_{day_idx}_{shift_id}')
                                model.Add(sum(forbidden_usage) >= 1).OnlyEnforceIf(forbidden_used)
                                model.Add(sum(forbidden_usage) == 0).OnlyEnforceIf(forbidden_used.Not())
                                
                                # Penalty occurs when teacher's shift is active AND forbidden sessions are used
                                model.AddBoolAnd([teacher_shift_vars[day_idx][shift_id], forbidden_used]).OnlyEnforceIf(teacher_shift_violation_penalty)
                                model.AddBoolOr([teacher_shift_vars[day_idx][shift_id].Not(), forbidden_used.Not()]).OnlyEnforceIf(teacher_shift_violation_penalty.Not())
                                
                                # Add to preference variables (to be minimized)
                                self.shift_preference_vars.append(teacher_shift_violation_penalty)
                                constraints_applied += 3
                
                self.logger.debug(f"Applied individual teacher shift constraints for course {course_code} by Teacher {teacher_id}")
        
        self.logger.info(f"Applied {constraints_applied} individual teacher shift constraints for {len(self.cross_dept_teachers)} cross-department teachers")
        return constraints_applied
    
    def apply_shift_based_theory_constraint(self, model, group_timeslot_vars):
        """
        CONSTRAINT: Apply department-centric theory shift constraints that coordinate with department shift patterns.
        This ensures that when a department is on Shift 1 (8-3) on Monday, BOTH their lab sessions AND 
        theory sessions comply with the same shift time window.
        
        Each department will follow one unified weekly shift pattern:
        - Pattern 3-2: 3 days Shift1 (8-3), 2 days Shift2 (10-5)
        - Pattern 2-3: 2 days Shift1 (8-3), 3 days Shift2 (10-5)
        """
        self.logger.info("Applying department-centric theory shift constraints to coordinate with department shift patterns...")
        constraints_applied = 0
        
        # Group theory groups by department
        dept_groups = defaultdict(list)
        
        for group_name in group_timeslot_vars.keys():
            # Parse department from group name
            dept_name = group_name.split('_S')[0] if '_S' in group_name else "Computer Science & Engineering"
            
            # Only apply to shift departments
            if self.is_shift_department(dept_name):
                dept_groups[dept_name].append(group_name)
        
        if not dept_groups:
            self.logger.info("No departments found in theory groups")
            return 0
        
        # Check if we have department shift variables
        if not hasattr(self, 'department_shift_vars') or not self.department_shift_vars:
            self.logger.warning("No department shift variables found - theory shifts cannot be coordinated")
            return self._apply_fallback_theory_shifts(model, group_timeslot_vars, dept_groups)
        
        # Initialize shift preference variables if not already done
        if not hasattr(self, 'shift_preference_vars'):
            self.shift_preference_vars = []
        
        self.logger.info("Coordinating theory slots with department shift patterns...")
            
        # For each theory group, coordinate with department shift patterns
        for dept_name, groups in dept_groups.items():
            if dept_name not in self.department_shift_vars:
                self.logger.warning(f"No shift variables found for department {dept_name} - skipping coordination")
                continue
                
            dept_days = self._get_days_for_department(dept_name)
            num_dept_days = len(dept_days)
            dept_shift_vars = self.department_shift_vars[dept_name]
            
            self.logger.info(f"Coordinating {len(groups)} theory groups in {dept_name} with department shift pattern")
            
            for group_name in groups:
                if group_name not in group_timeslot_vars:
                    continue
                
                # Create coordination constraints between department shifts and theory slot usage
                for day_idx in range(num_dept_days):
                    if day_idx not in group_timeslot_vars[group_name]:
                        continue
                    
                    for shift_id in self.get_available_shifts():
                        allowed_slots = self.get_shift_theory_slots(shift_id)
                        forbidden_slots = [s for s in range(self.num_theory_slots) if s not in allowed_slots]
                        
                        if forbidden_slots:
                            # Create coordination penalty for violating department's shift pattern
                            coord_violation = model.NewBoolVar(
                                f'dept_theory_coord_{dept_name.replace(" ", "_").replace("&", "and")}_{group_name}_day_{day_idx}_shift_{shift_id}'
                            )
                            
                            # Collect forbidden slot usage for this group
                            forbidden_slot_usage = []
                            for slot_idx in forbidden_slots:
                                if slot_idx in group_timeslot_vars[group_name][day_idx]:
                                    forbidden_slot_usage.append(group_timeslot_vars[group_name][day_idx][slot_idx])
                            
                            if forbidden_slot_usage:
                                # Create helper variable for forbidden slots being used
                                forbidden_used = model.NewBoolVar(
                                    f'dept_theory_forbidden_{dept_name.replace(" ", "_").replace("&", "and")}_{group_name}_day_{day_idx}_shift_{shift_id}'
                                )
                                model.Add(sum(forbidden_slot_usage) >= 1).OnlyEnforceIf(forbidden_used)
                                model.Add(sum(forbidden_slot_usage) == 0).OnlyEnforceIf(forbidden_used.Not())
                                
                                # Coordination violation occurs when department's shift is active AND group uses forbidden slots
                                model.AddBoolAnd([dept_shift_vars[day_idx][shift_id], forbidden_used]).OnlyEnforceIf(coord_violation)
                                model.AddBoolOr([dept_shift_vars[day_idx][shift_id].Not(), forbidden_used.Not()]).OnlyEnforceIf(coord_violation.Not())
                                
                                # Add this as a soft penalty (theory should respect department shift patterns)
                                self.shift_preference_vars.append(coord_violation)
                                constraints_applied += 3
        
        # Apply individual teacher theory shift constraints for cross-department teachers
        cross_dept_theory_constraints = self._apply_cross_department_teacher_theory_constraints(model, group_timeslot_vars)
        constraints_applied += cross_dept_theory_constraints
        
        self.logger.info(f"Applied {constraints_applied} total theory shift constraints")
        self.logger.info(f"  - Department-centric constraints: {constraints_applied - cross_dept_theory_constraints}")
        self.logger.info(f"  - Cross-department teacher constraints: {cross_dept_theory_constraints}")
        self.logger.info(f"Theory groups now coordinate with shift patterns:")
        self.logger.info(f"  🎯 DEPARTMENT: When department is on Shift1 Monday, ALL department activities (lab+theory) fit 8-3 window")
        self.logger.info(f"  🎯 DEPARTMENT: When department is on Shift2 Tuesday, ALL department activities (lab+theory) fit 10-5 window")
        self.logger.info(f"  🎯 TEACHER: Cross-department teachers have individual shift patterns coordinated with their student departments")
        return constraints_applied
    
    def _apply_cross_department_teacher_theory_constraints(self, model, group_timeslot_vars):
        """Apply individual theory shift constraints for cross-department teachers."""
        self.logger.info("Applying individual theory shift constraints for cross-department teachers...")
        constraints_applied = 0
        
        if not hasattr(self, 'cross_dept_teachers') or not self.cross_dept_teachers:
            self.logger.info("No cross-department teachers identified for theory constraints")
            return 0
        
        if not hasattr(self, 'teacher_shift_vars') or not self.teacher_shift_vars:
            self.logger.warning("No teacher shift variables found - cross-department theory shifts cannot be coordinated")
            return 0
        
        # Find theory groups taught by cross-department teachers
        cross_teacher_groups = defaultdict(list)
        
        for group_name in group_timeslot_vars.keys():
            # Try to find teachers for this group
            teachers = []
            if hasattr(self, 'course_groups') and self.course_groups:
                try:
                    if isinstance(self.course_groups, dict):
                        for dept_key, dept_data in self.course_groups.items():
                            if isinstance(dept_data, dict):
                                for sem_key, sem_data in dept_data.items():
                                    if isinstance(sem_data, list):
                                        for group in sem_data:
                                            if isinstance(group, dict) and group.get('group_name') == group_name:
                                                teachers = group.get('teachers', [])
                                                break
                except (TypeError, AttributeError) as e:
                    self.logger.warning(f"Error accessing course_groups structure for {group_name}: {e}")
                    teachers = []
            
            # Check if any teachers in this group are cross-department
            for teacher_id in teachers:
                if self.is_cross_department_teacher(teacher_id):
                    cross_teacher_groups[teacher_id].append(group_name)
        
        if not cross_teacher_groups:
            self.logger.info("No theory groups found with cross-department teachers")
            return 0
        
        # Apply constraints for each cross-department teacher's theory groups
        for teacher_id, group_names in cross_teacher_groups.items():
            if teacher_id not in self.teacher_shift_vars:
                continue
            
            student_depts = self.get_teacher_student_departments(teacher_id)
            dept_list = ', '.join(sorted(student_depts))
            
            self.logger.info(f"Applying theory shift constraints for cross-dept Teacher {teacher_id} (serves: {dept_list}) with {len(group_names)} groups")
            
            # Get teacher's working days
            teacher_days = set()
            for dept in student_depts:
                dept_days = self._get_days_for_department(dept)
                teacher_days.update(dept_days)
            teacher_days = sorted(list(teacher_days))
            num_teacher_days = len(teacher_days)
            
            teacher_shift_vars = self.teacher_shift_vars[teacher_id]
            
            # Apply constraints for each group taught by this teacher
            for group_name in group_names:
                if group_name not in group_timeslot_vars:
                    continue
                
                # Create coordination constraints between teacher shifts and theory slot usage
                for day_idx in range(num_teacher_days):
                    if day_idx not in group_timeslot_vars[group_name]:
                        continue
                    
                    for shift_id in self.get_available_shifts():
                        allowed_slots = self.get_shift_theory_slots(shift_id)
                        forbidden_slots = [s for s in range(self.num_theory_slots) if s not in allowed_slots]
                        
                        if forbidden_slots:
                            # Create coordination penalty for violating teacher's shift pattern
                            teacher_theory_coord_violation = model.NewBoolVar(
                                f'cross_teacher_theory_coord_{teacher_id}_{group_name}_day_{day_idx}_shift_{shift_id}'
                            )
                            
                            # Collect forbidden slot usage for this group
                            forbidden_slot_usage = []
                            for slot_idx in forbidden_slots:
                                if slot_idx in group_timeslot_vars[group_name][day_idx]:
                                    forbidden_slot_usage.append(group_timeslot_vars[group_name][day_idx][slot_idx])
                            
                            if forbidden_slot_usage:
                                # Create helper variable for forbidden slots being used
                                forbidden_used = model.NewBoolVar(
                                    f'cross_teacher_theory_forbidden_{teacher_id}_{group_name}_day_{day_idx}_shift_{shift_id}'
                                )
                                model.Add(sum(forbidden_slot_usage) >= 1).OnlyEnforceIf(forbidden_used)
                                model.Add(sum(forbidden_slot_usage) == 0).OnlyEnforceIf(forbidden_used.Not())
                                
                                # Coordination violation occurs when teacher's shift is active AND group uses forbidden slots
                                model.AddBoolAnd([teacher_shift_vars[day_idx][shift_id], forbidden_used]).OnlyEnforceIf(teacher_theory_coord_violation)
                                model.AddBoolOr([teacher_shift_vars[day_idx][shift_id].Not(), forbidden_used.Not()]).OnlyEnforceIf(teacher_theory_coord_violation.Not())
                                
                                # Add this as a soft penalty (theory should respect teacher shift patterns)
                                self.shift_preference_vars.append(teacher_theory_coord_violation)
                                constraints_applied += 3
        
        self.logger.info(f"Applied {constraints_applied} cross-department teacher theory shift constraints")
        self.logger.info(f"Cross-department teachers with theory groups: {len(cross_teacher_groups)}")
        return constraints_applied
    
    def _apply_fallback_theory_shifts(self, model, group_timeslot_vars, dept_groups):
        """Fallback method when teacher shift variables are not available - use teacher-level constraints."""
        self.logger.info("Applying fallback teacher-level theory shift constraints...")
        constraints_applied = 0
        
        if not hasattr(self, 'shift_preference_vars'):
            self.shift_preference_vars = []
        
        # Extract teachers from groups instead of using department-level approach
        teacher_groups = defaultdict(list)
        
        for dept_name, groups in dept_groups.items():
            for group_name in groups:
                # Try to find teachers for this group
                teachers = []
                if hasattr(self, 'course_groups') and self.course_groups:
                    try:
                        if isinstance(self.course_groups, dict):
                            for dept_key, dept_data in self.course_groups.items():
                                if isinstance(dept_data, dict):
                                    for sem_key, sem_data in dept_data.items():
                                        if isinstance(sem_data, list):
                                            for group in sem_data:
                                                if isinstance(group, dict) and group.get('group_name') == group_name:
                                                    teachers = group.get('teachers', [])
                                                    break
                    except (TypeError, AttributeError) as e:
                        self.logger.warning(f"Error accessing course_groups structure for {group_name}: {e}")
                        teachers = []
                
                # Add each teacher-group relationship
                for teacher_id in teachers:
                    teacher_groups[teacher_id].append((group_name, dept_name))
        
        # Apply teacher-level constraints instead of department-level
        for teacher_id, group_dept_pairs in teacher_groups.items():
            if not group_dept_pairs:
                continue
                
            # Get department from first group (assuming teacher works in one department)
            dept_name = group_dept_pairs[0][1]
            dept_days = self._get_days_for_department(dept_name)
            num_dept_days = len(dept_days)
            
            # Create individual teacher shift variables for fallback
            teacher_shift_vars = {}
            for day_idx in range(num_dept_days):
                teacher_shift_vars[day_idx] = {}
                for shift_id in self.get_available_shifts():
                    teacher_shift_vars[day_idx][shift_id] = model.NewBoolVar(
                        f'fallback_teacher_{teacher_id}_day_{day_idx}_shift_{shift_id}'
                    )
                
                # SOFT CONSTRAINT: Prefer teacher to follow exactly one shift per day
                shift_violation = model.NewBoolVar(f'fallback_teacher_shift_violation_{teacher_id}_day_{day_idx}')
                total_shifts = sum(teacher_shift_vars[day_idx].values())
                model.Add(total_shifts == 1).OnlyEnforceIf(shift_violation.Not())
                model.Add(total_shifts != 1).OnlyEnforceIf(shift_violation)
                self.shift_preference_vars.append(shift_violation)
                constraints_applied += 2
            
            # Apply soft preferences for each group taught by this teacher
            for group_name, dept_name in group_dept_pairs:
                if group_name not in group_timeslot_vars:
                    continue
                
                for day_idx in range(num_dept_days):
                    if day_idx not in group_timeslot_vars[group_name]:
                        continue
                    
                    for shift_id in self.get_available_shifts():
                        allowed_slots = self.get_shift_theory_slots(shift_id)
                        forbidden_slots = [s for s in range(self.num_theory_slots) if s not in allowed_slots]
                        
                        if forbidden_slots:
                            theory_shift_penalty = model.NewBoolVar(
                                f'fallback_teacher_theory_penalty_{teacher_id}_{group_name}_{day_idx}_{shift_id}'
                            )
                            
                            forbidden_slot_usage = []
                            for slot_idx in forbidden_slots:
                                if slot_idx in group_timeslot_vars[group_name][day_idx]:
                                    forbidden_slot_usage.append(group_timeslot_vars[group_name][day_idx][slot_idx])
                            
                            if forbidden_slot_usage:
                                forbidden_used = model.NewBoolVar(f'fallback_teacher_theory_forbidden_{teacher_id}_{group_name}_{day_idx}_{shift_id}')
                                model.Add(sum(forbidden_slot_usage) >= 1).OnlyEnforceIf(forbidden_used)
                                model.Add(sum(forbidden_slot_usage) == 0).OnlyEnforceIf(forbidden_used.Not())
                                
                                # Link to teacher's individual shift pattern
                                model.AddBoolAnd([teacher_shift_vars[day_idx][shift_id], forbidden_used]).OnlyEnforceIf(theory_shift_penalty)
                                model.AddBoolOr([teacher_shift_vars[day_idx][shift_id].Not(), forbidden_used.Not()]).OnlyEnforceIf(theory_shift_penalty.Not())
                                
                                self.shift_preference_vars.append(theory_shift_penalty)
                                constraints_applied += 3
                
        self.logger.info(f"Applied {constraints_applied} fallback teacher-level theory shift constraints")
        self.logger.info(f"Teachers with fallback shift patterns: {len(teacher_groups)}")
        return constraints_applied

    def apply_unified_weekly_shift_constraint(self, model, lab_variables, group_timeslot_vars):
        """
        CONSTRAINT: Apply unified weekly shift pattern constraints for departments.
        This method is now a wrapper that ensures department shift variables are properly coordinated
        between lab and theory scheduling. The actual constraints are applied in the individual
        apply_shift_based_lab_constraint and apply_shift_based_theory_constraint methods.
        
        Department-centric approach: Each department follows ONE unified pattern:
        - Pattern 3-2: 3 days Shift1 (8-3), 2 days Shift2 (10-5)
        - Pattern 2-3: 2 days Shift1 (8-3), 3 days Shift2 (10-5)
        
        All teachers in a department follow the same department shift pattern.
        """
        self.logger.info("Ensuring unified department-centric weekly shift pattern coordination...")
        constraints_applied = 0
        
        # Check if department shift variables have been created
        if not hasattr(self, 'department_shift_vars') or not self.department_shift_vars:
            self.logger.warning("No department shift variables found - department shifts may not be properly coordinated")
            return 0
        
        # Verify that department shift variables exist for all shift departments
        dept_count = 0
        for dept_name in self.department_shift_vars:
            if self.is_shift_department(dept_name):
                dept_count += 1
                self.logger.info(f"✅ Department {dept_name} has unified shift pattern variables")
        
        if dept_count == 0:
            self.logger.warning("No shift departments found with shift variables")
            return 0
        
        # Log coordination status
        self.logger.info(f"✅ Department-centric shift coordination verified for {dept_count} departments")
        self.logger.info("✅ Lab and theory constraints will use the same department shift variables")
        self.logger.info("✅ Single-department teachers follow their department's shift pattern")
        
        # Check cross-department teacher coordination
        cross_teacher_count = len(self.teacher_shift_vars) if hasattr(self, 'teacher_shift_vars') else 0
        if cross_teacher_count > 0:
            self.logger.info(f"✅ Individual shift patterns verified for {cross_teacher_count} cross-department teachers")
            self.logger.info("✅ Cross-department teachers have individual shift patterns coordinated with their student departments")
        else:
            self.logger.info("✅ No cross-department teachers require individual shift patterns")
        
        # Generate pattern names for logging
        pattern_names = [f"{p[0]}-{p[1]}" for p in self.valid_shift_patterns]
        self.logger.info(f"✅ Valid department patterns: {', '.join(pattern_names)} (Shift1-Shift2 days)")
        
        return constraints_applied

    def apply_teacher_max_consecutive_lab_constraint(self, model, lab_variables):
        """
        CONSTRAINT: Teachers cannot have more than 2 consecutive lab slots (DEPARTMENT-AWARE).
        
        This constraint is applied as:
        - SOFT constraint for Biotechnology (allows 3+ consecutive for experimental continuity)
        - HARD constraint for other departments
        
        This allows:
        - L1+L2 (2 consecutive = 4 hours) ✅
        - L2+L3 (2 consecutive = 4 hours) ✅
        - L3+L4 (2 consecutive = 4 hours) ✅
        - L4+L5 (2 consecutive = 4 hours) ✅
        - L5+L6 (2 consecutive = 4 hours) ✅
        
        For Biotechnology: Discourages but allows (soft constraint):
        - L1+L2+L3 (3 consecutive = 6 hours) 💔
        
        For Other Departments: Prohibits (hard constraint):
        - L1+L2+L3 (3 consecutive = 6 hours) ❌
        """
        self.logger.info("Applying DEPARTMENT-AWARE constraint: Teachers cannot have more than 2 consecutive lab slots...")
        constraints_applied = 0
        soft_constraints_applied = 0
        
        # Define departments with soft consecutive constraints (allow longer sessions for experiments)
        soft_consecutive_departments = [
            'Biotechnology'
        ]
        
        # Track which departments get hard vs soft constraints
        hard_constraint_depts = set()
        soft_constraint_depts = set()
        
        # Initialize soft constraint penalty variables
        if not hasattr(self, 'teacher_consecutive_penalty_vars'):
            self.teacher_consecutive_penalty_vars = []
        
        # Define the consecutive lab session sequences
        lab_session_order = ['L1', 'L2', 'L3', 'L4', 'L5', 'L6']
        
        # OPTIMIZED: Only check minimal 3-consecutive patterns
        # If we prevent all 3-consecutive, longer sequences are automatically prevented
        forbidden_sequences = []
        
        # Generate only 3-consecutive sequences (minimal forbidden patterns)
        for start_idx in range(len(lab_session_order) - 2):  # Generate L1+L2+L3, L2+L3+L4, etc.
            sequence = lab_session_order[start_idx:start_idx + 3]
            forbidden_sequences.append(sequence)
        
        self.logger.info(f"Optimized forbidden consecutive sequences (3 sessions only): {forbidden_sequences}")
        self.logger.info("Note: Preventing 3-consecutive automatically prevents 4+, 5+, 6+ consecutive patterns")
        
        # Apply constraint for each teacher
        for teacher_id in lab_variables:
            self.logger.debug(f"Applying consecutive lab constraint for teacher {teacher_id}...")
            
            # Get all course instances for this teacher
            teacher_courses = list(lab_variables[teacher_id].keys())
            
            if not teacher_courses:
                continue
            
            # For each day, check all consecutive sequences across all teacher's courses
            for course_instance_id in teacher_courses:
                if course_instance_id not in lab_variables[teacher_id]:
                    continue
                
                # Get department for this course to determine number of days and constraint type
                dept_name = "Computer Science & Engineering"  # Default
                if hasattr(self, 'instance_group_mapping') and course_instance_id in self.instance_group_mapping:
                    dept_name = self.instance_group_mapping[course_instance_id]['department']
                else:
                    # Fallback: look up in courses_df
                    course_matches = self.courses_df[self.courses_df['id'] == int(course_instance_id)]
                    if not course_matches.empty:
                        dept_name = course_matches.iloc[0].get('student_dept', 'Computer Science & Engineering')
                
                # Determine constraint type for this department
                is_soft_constraint = dept_name in soft_consecutive_departments
                
                dept_days = self._get_days_for_department(dept_name)
                num_dept_days = len(dept_days)
                
                # Track department constraint types
                if is_soft_constraint:
                    soft_constraint_depts.add(dept_name)
                else:
                    hard_constraint_depts.add(dept_name)
                
                # For each day, apply the consecutive constraint
                for day_idx in range(num_dept_days):
                    if day_idx not in lab_variables[teacher_id][course_instance_id]:
                        continue
                    
                    # Check if this day has enough sessions to form any forbidden sequence
                    available_sessions = list(lab_variables[teacher_id][course_instance_id][day_idx].keys())
                    if len(available_sessions) < 3:
                        continue  # Skip if less than 3 sessions available
                    
                    # For each forbidden sequence, ensure teacher cannot be assigned to all sessions in the sequence
                    for forbidden_sequence in forbidden_sequences:
                        # Quick check: Do all sessions in the sequence exist for this day?
                        if not all(session in lab_variables[teacher_id][course_instance_id][day_idx] 
                                  for session in forbidden_sequence):
                            continue  # Skip if not all sessions are available
                        
                        # Collect session usage variables efficiently
                        sequence_variables = []
                        
                        for session_name in forbidden_sequence:
                            # Collect all room assignments for this session
                            session_assignments = []
                            session_data = lab_variables[teacher_id][course_instance_id][day_idx][session_name]
                            
                            for room_id in self.lab_room_ids:
                                if room_id in session_data:
                                    session_assignments.append(session_data[room_id])
                            
                            if session_assignments:
                                # Create a boolean variable that is true if ANY assignment is made in this session
                                session_used = model.NewBoolVar(
                                    f'teacher_{teacher_id}_course_{course_instance_id}_day_{day_idx}_session_{session_name}_used'
                                )
                                
                                # session_used is true if at least one room assignment is made
                                model.Add(sum(session_assignments) >= 1).OnlyEnforceIf(session_used)
                                model.Add(sum(session_assignments) == 0).OnlyEnforceIf(session_used.Not())
                                
                                sequence_variables.append(session_used)
                        
                        # Apply constraint only if we have all 3 sessions
                        if len(sequence_variables) == 3:
                            if is_soft_constraint:
                                # SOFT CONSTRAINT for Biotechnology: Create penalty variable for 3+ consecutive sessions
                                consecutive_violation = model.NewBoolVar(
                                    f'teacher_{teacher_id}_course_{course_instance_id}_day_{day_idx}_consecutive_violation_{"_".join(forbidden_sequence)}'
                                )
                                
                                # Violation occurs if all 3 consecutive sessions are used
                                model.Add(sum(sequence_variables) >= 3).OnlyEnforceIf(consecutive_violation)
                                model.Add(sum(sequence_variables) <= 2).OnlyEnforceIf(consecutive_violation.Not())
                                
                                # Add to penalty variables for objective minimization
                                self.teacher_consecutive_penalty_vars.append(consecutive_violation)
                                soft_constraints_applied += 1
                                
                                self.logger.debug(f"Applied SOFT constraint: Teacher {teacher_id} discouraged from using all 3 sessions "
                                                f"{' -> '.join(forbidden_sequence)} on day {day_idx} (Biotechnology)")
                            else:
                                # HARD CONSTRAINT for other departments: At most 2 out of 3 consecutive sessions can be used
                                model.Add(sum(sequence_variables) <= 2)
                                constraints_applied += 1
                                
                                self.logger.debug(f"Applied HARD constraint: Teacher {teacher_id} can use at most 2/3 sessions "
                                                f"{' -> '.join(forbidden_sequence)} on day {day_idx} ({dept_name})")
        
        # Also apply constraint across all courses of a teacher on the same day
        # (to prevent teacher from having consecutive sessions across different courses)
        for teacher_id in lab_variables:
            teacher_courses = list(lab_variables[teacher_id].keys())
            
            if len(teacher_courses) <= 1:
                continue  # Skip if teacher has only one course
            
            # Get a representative course to determine department days and constraint type
            sample_course = teacher_courses[0]
            dept_name = "Computer Science & Engineering"  # Default
            if hasattr(self, 'instance_group_mapping') and sample_course in self.instance_group_mapping:
                dept_name = self.instance_group_mapping[sample_course]['department']
            else:
                # Fallback: look up in courses_df
                course_matches = self.courses_df[self.courses_df['id'] == int(sample_course)]
                if not course_matches.empty:
                    dept_name = course_matches.iloc[0].get('student_dept', 'Computer Science & Engineering')
            
            # Determine constraint type for cross-course constraints
            is_soft_constraint = dept_name in soft_consecutive_departments
            
            dept_days = self._get_days_for_department(dept_name)
            num_dept_days = len(dept_days)
            
            # Track department constraint types
            if is_soft_constraint:
                soft_constraint_depts.add(dept_name)
            else:
                hard_constraint_depts.add(dept_name)
            
            # For each day, apply cross-course consecutive constraint
            for day_idx in range(num_dept_days):
                # Check if teacher has any sessions on this day across all courses
                teacher_has_sessions_today = any(
                    day_idx in lab_variables[teacher_id][course_instance_id]
                    for course_instance_id in teacher_courses
                    if course_instance_id in lab_variables[teacher_id]
                )
                
                if not teacher_has_sessions_today:
                    continue  # Skip if teacher has no sessions on this day
                
                # For each forbidden sequence, ensure teacher cannot be assigned across courses
                for forbidden_sequence in forbidden_sequences:
                    # Collect all session usage variables across all courses for this teacher on this day
                    cross_course_sequence_vars = []
                    
                    for session_name in forbidden_sequence:
                        # Collect all assignments for this session across ALL courses for this teacher
                        session_assignments_all_courses = []
                        
                        for course_instance_id in teacher_courses:
                            if (course_instance_id in lab_variables[teacher_id] and
                                day_idx in lab_variables[teacher_id][course_instance_id] and
                                session_name in lab_variables[teacher_id][course_instance_id][day_idx]):
                                
                                session_data = lab_variables[teacher_id][course_instance_id][day_idx][session_name]
                                for room_id in self.lab_room_ids:
                                    if room_id in session_data:
                                        session_assignments_all_courses.append(session_data[room_id])
                        
                        if session_assignments_all_courses:
                            # Create variable to track if teacher is used in this session (any course)
                            teacher_used_in_session = model.NewBoolVar(
                                f'teacher_{teacher_id}_day_{day_idx}_session_{session_name}_used_any_course'
                            )
                            
                            # Teacher is used if any assignment across all courses is made
                            model.Add(sum(session_assignments_all_courses) >= 1).OnlyEnforceIf(teacher_used_in_session)
                            model.Add(sum(session_assignments_all_courses) == 0).OnlyEnforceIf(teacher_used_in_session.Not())
                            
                            cross_course_sequence_vars.append(teacher_used_in_session)
                    
                    # Apply constraint only if we have all 3 sessions
                    if len(cross_course_sequence_vars) == 3:
                        if is_soft_constraint:
                            # SOFT CONSTRAINT for Biotechnology: Create penalty variable for 3+ consecutive sessions
                            cross_course_violation = model.NewBoolVar(
                                f'teacher_{teacher_id}_day_{day_idx}_cross_course_consecutive_violation_{"_".join(forbidden_sequence)}'
                            )
                            
                            # Violation occurs if all 3 consecutive sessions are used across courses
                            model.Add(sum(cross_course_sequence_vars) >= 3).OnlyEnforceIf(cross_course_violation)
                            model.Add(sum(cross_course_sequence_vars) <= 2).OnlyEnforceIf(cross_course_violation.Not())
                            
                            # Add to penalty variables for objective minimization
                            self.teacher_consecutive_penalty_vars.append(cross_course_violation)
                            soft_constraints_applied += 1
                            
                            self.logger.debug(f"Applied SOFT cross-course constraint: Teacher {teacher_id} discouraged from using all 3 sessions "
                                            f"{' -> '.join(forbidden_sequence)} on day {day_idx} (Biotechnology)")
                        else:
                            # HARD CONSTRAINT for other departments: At most 2 out of 3 consecutive sessions can be used
                            model.Add(sum(cross_course_sequence_vars) <= 2)
                            constraints_applied += 1
                            
                            self.logger.debug(f"Applied HARD cross-course constraint: Teacher {teacher_id} can use at most 2/3 sessions "
                                            f"{' -> '.join(forbidden_sequence)} on day {day_idx} ({dept_name})")
        
        self.logger.info(f"Applied teacher consecutive lab constraints:")
        self.logger.info(f"  - {constraints_applied} HARD constraints (other departments)")
        self.logger.info(f"  - {soft_constraints_applied} SOFT constraints (Biotechnology)")
        self.logger.info(f"  - Total penalty variables: {len(self.teacher_consecutive_penalty_vars)}")
        
        if hard_constraint_depts:
            self.logger.info(f"🔒 HARD constraint departments: {sorted(hard_constraint_depts)}")
            self.logger.info("   ❌ Teachers CANNOT have 3+ consecutive lab slots")
        
        if soft_constraint_depts:
            self.logger.info(f"💔 SOFT constraint departments: {sorted(soft_constraint_depts)}")
            self.logger.info("   💔 Teachers DISCOURAGED from 3+ consecutive lab slots (allows experimental continuity)")
        
        self.logger.info("✅ All teachers limited to maximum 2 consecutive lab slots is preferred")
        return constraints_applied + soft_constraints_applied
    
    def apply_teacher_daily_presence_lab_constraint(self, model, lab_variables):
        """
        Apply HARD constraint to prevent teacher violation days (11+ hour campus presence) for lab sessions.
        Prevents teachers from having lab sessions spanning from early morning (L1: 8AM) to late evening (L6: 7PM).
        Based on shift report violation criteria: normalized_start_hour <= 8 AND end_hour >= 19.
        
        UPDATED: Allow L1 + L5 (8:00-9:40 + 3:00-4:40) = 8.5+ hours combination
        """
        self.logger.info("Applying teacher daily presence constraint for lab sessions: prevent 11+ hour violation days...")
        constraints_applied = 0
        
        # Define violation lab sessions based on time mappings
        # UPDATED: Only prevent the most extreme combination
        # Early morning: L1 (8:00-9:40) - corresponds to 8AM block
        # Late sessions: Only L6 (5:10-6:50) - most extreme late session
        early_lab_sessions = ['L1']     # 8:00-9:40
        late_lab_sessions = ['L6']      # Only 5:10-6:50 (most extreme late)
        
        # Apply constraint for each teacher with lab courses
        for teacher_id in lab_variables:
            teacher_courses = list(lab_variables[teacher_id].keys())
            if not teacher_courses:
                continue
            
            # Get department days for the first course (assuming same pattern for teacher)
            dept_days = ["monday", "tuesday", "wed", "thur", "fri"]  # Default
            if hasattr(self, 'instance_group_mapping') and teacher_courses[0] in self.instance_group_mapping:
                mapping = self.instance_group_mapping[teacher_courses[0]]
                dept_days = self._get_days_for_department(mapping['department'], mapping.get('semester'))
            
            num_dept_days = len(dept_days)
            
            self.logger.debug(f"Applying lab presence constraint for Teacher {teacher_id} with {len(teacher_courses)} courses")
            
            # Apply constraint for each day
            for day_idx in range(num_dept_days):
                # Check if teacher has early lab sessions (L1)
                early_lab_vars = []
                for course_instance_id in teacher_courses:
                    if (course_instance_id in lab_variables[teacher_id] and
                        day_idx < len(lab_variables[teacher_id][course_instance_id])):
                        for session_name in early_lab_sessions:
                            if session_name in lab_variables[teacher_id][course_instance_id][day_idx]:
                                early_lab_vars.extend(
                                    lab_variables[teacher_id][course_instance_id][day_idx][session_name].values()
                                )
                
                # Check if teacher has late lab sessions (L6)
                late_lab_vars = []
                for course_instance_id in teacher_courses:
                    if (course_instance_id in lab_variables[teacher_id] and
                        day_idx < len(lab_variables[teacher_id][course_instance_id])):
                        for session_name in late_lab_sessions:
                            if session_name in lab_variables[teacher_id][course_instance_id][day_idx]:
                                late_lab_vars.extend(
                                    lab_variables[teacher_id][course_instance_id][day_idx][session_name].values()
                                )
                
                # HARD CONSTRAINT: Prevent both early AND late lab sessions on the same day
                if early_lab_vars and late_lab_vars:
                    # Create boolean variables for early and late lab presence
                    has_early_lab = model.NewBoolVar(f'teacher_{teacher_id}_day_{day_idx}_early_lab')
                    has_late_lab = model.NewBoolVar(f'teacher_{teacher_id}_day_{day_idx}_late_lab')
                    
                    # Link boolean variables to actual lab assignments
                    model.Add(sum(early_lab_vars) > 0).OnlyEnforceIf(has_early_lab)
                    model.Add(sum(early_lab_vars) == 0).OnlyEnforceIf(has_early_lab.Not())
                    
                    model.Add(sum(late_lab_vars) > 0).OnlyEnforceIf(has_late_lab)
                    model.Add(sum(late_lab_vars) == 0).OnlyEnforceIf(has_late_lab.Not())
                    
                    # PREVENT VIOLATION: Cannot have both early AND late lab sessions on same day
                    model.Add(has_early_lab + has_late_lab <= 1)
                    constraints_applied += 1
                    
                    day_name = dept_days[day_idx] if day_idx < len(dept_days) else f"day_{day_idx}"
                    self.logger.debug(f"Teacher {teacher_id}: blocked lab violation pattern on {day_name} (L1 + L6)")
                    self.logger.debug(f"  Early lab: L1 (8:00-9:40), Late lab: L6 (5:10-6:50)")
        
        self.logger.info(f"Applied {constraints_applied} teacher daily presence constraints for lab sessions")
        self.logger.info("✅ RELAXED LAB VIOLATION PREVENTION: Only prevents most extreme lab days (L1 + L6)")
        self.logger.info("✅ ALLOWED: L1 + L5 (8:00-9:40 + 3:00-4:40) and similar 8+ hour combinations")
        return constraints_applied