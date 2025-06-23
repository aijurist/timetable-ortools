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
        self.rooms_df = pd.read_csv(room_file)
        
        # Load day order information
        self.day_order_df = self._load_day_order()
        
        # Set up time configurations based on day order
        self._setup_department_day_patterns()
        
        # Set up lunch break configuration
        self._setup_lunch_break_configuration()
        
        # Set up shift-based constraints for single-instance departments
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
        
        # Group lab slots into 2-hour sessions (L1, L2, L3, etc.) - EXACTLY as in lab_scheduler.py
        self.lab_sessions = {
            'L1': ['8:00 - 8:50', '8:50 - 9:40'],      # 8:00 - 9:40
            'L2': ['9:50 - 10:40', '10:40 - 11:30'],   # 9:50 - 11:30  
            'L3': ['11:50 - 12:40', '12:40 - 1:30'],   # 11:50 - 1:30
            'L4': ['1:50 - 2:40', '2:40 - 3:30'],      # 1:50 - 3:30
            'L5': ['3:50 - 4:40', '4:40 - 5:30'],      # 3:50 - 5:30
            'L6': ['5:30 - 6:20', '6:20 - 7:10']       # 5:30 - 7:10
        }
        self.num_lab_sessions = len(self.lab_sessions)

        # Create detailed lab session info with slot indices for conflict mapping
        self.lab_sessions_details = {}
        lab_time_slot_map = {slot: i for i, slot in enumerate(self.lab_time_slots)}
        for session_name, time_slots in self.lab_sessions.items():
            slot_indices = [lab_time_slot_map[ts] for ts in time_slots if ts in lab_time_slot_map]
            self.lab_sessions_details[session_name] = {'slots': slot_indices}
        
        # THEORY TIME CONFIGURATION - EXACTLY as in theory_scheduler.py
        self.theory_time_slots = [
            "8:00 - 8:50", "9:00 - 9:50", "10:00 - 10:50", "11:00 - 11:50",
            "12:00 - 12:50", "1:00 - 1:50", "2:00 - 2:50", "3:00 - 3:50", 
            "4:00 - 4:50", "5:00 - 5:50", "6:00 - 6:50"
        ]
        self.num_theory_slots = len(self.theory_time_slots)
        
        # Build time slot mapping between lab and theory (now that both are defined)
        self._build_time_mapping()
        
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
        
        # GLOBAL ROOM REGISTRY FOR CROSS-SCHEDULE VALIDATION
        self.global_room_registry = {}  # (day, time_slot, room_id) -> session_info
        self._initialize_global_room_registry()
        
        self.logger.info("Combined Scheduler initialized successfully")
        self.logger.info(f"Theory time slots: {self.num_theory_slots}")
        self.logger.info(f"Lab time slots: {self.num_lab_slots}")
        self.logger.info(f"Lab rooms: {len(self.lab_room_ids)}")
        self.logger.info(f"Theory rooms: {len(self.theory_room_ids)}")
    
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
            ('Biotechnology', 5): {
                'days': ["monday", "tuesday", "wed", "thur", "fri", "saturday"],
                'pattern': 'Monday-Saturday'
            },
            # Electronics & Communication Engineering Monday-Saturday semesters
            # ('Electronics & Communication Engineering', 3): {
            #     'days': ["monday", "tuesday", "wed", "thur", "fri", "saturday"],
            #     'pattern': 'Monday-Saturday'
            # },
            ('Electronics & Communication Engineering', 5): {
                'days': ["monday", "tuesday", "wed", "thur", "fri", "saturday"],
                'pattern': 'Monday-Saturday'
            },
              ('Electrical & Electronics Engineering', 5): {
                'days': ["monday", "tuesday", "wed", "thur", "fri", "saturday"],
                'pattern': 'Monday-Saturday'
            },
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
        """Set up lunch break configuration for departments.
        
        Lunch break is between 11:00 AM to 1:30 PM, affecting theory slots:
        - Slot 3: 11:00 - 11:50
        - Slot 4: 12:00 - 12:50  
        - Slot 5: 1:00 - 1:50
        
        Each department gets assigned one of these slots as their lunch break.
        """
        self.logger.info("Setting up lunch break configuration...")
        
        # Define lunch break time slots (11:00 AM to 1:30 PM)
        self.lunch_break_slots = {
            3: "11:00 - 11:50",  # Slot 3
            4: "12:00 - 12:50",  # Slot 4
            5: "1:00 - 1:50"     # Slot 5
        }
        
        # Department-wise lunch break assignment
        # Each department gets one lunch break slot to ensure consistency
        self.department_lunch_breaks = {
            'Computer Science & Engineering': 4,  # Standard lunch (12:00 - 12:50)
            'Artificial Intelligence & Data Science': 4,
            'Artificial Intelligence & Machine Learning': 4,  # Added missing department
            'Information Technology': 4,
            'Computer Science & Business Systems': 4,
            'Computer Science & Design': 4,
            'Computer Science & Engineering (Cyber Security)': 5,

            # Engineering departments
            # 'Electronics & Communication Engineering': 4,  # Early lunch (11:00 - 11:50)
            # 'Electrical & Electronics Engineering': 3,
            # 'Mechanical Engineering': 3,
            "Food Technology":5,
            "Mechatronics Engineering":5,
            'Civil Engineering': 3,
            "Aeronautical Engineering":5,
            'Chemical Engineering': 3, 
            'Biomedical Engineering': 4, 
            # 'Biotechnology': 4,  # Late lunch (1:00 - 1:50)
            
            # Default for any department not explicitly listed
            # 'default': 4  # Standard lunch
        }
        
        # Create reverse mapping: lunch slot -> departments
        self.lunch_break_to_departments = {}
        for dept, slot_idx in self.department_lunch_breaks.items():
            if slot_idx not in self.lunch_break_to_departments:
                self.lunch_break_to_departments[slot_idx] = []
            self.lunch_break_to_departments[slot_idx].append(dept)
        
        # Log lunch break configuration
        self.logger.info("Lunch break configuration:")
        for slot_idx, time_slot in self.lunch_break_slots.items():
            depts = self.lunch_break_to_departments.get(slot_idx, [])
            self.logger.info(f"  Slot {slot_idx} ({time_slot}): {len(depts)} departments")
        
        self.logger.info(f"Lunch break configuration completed for {len(self.department_lunch_breaks)} departments")

    def get_lunch_break_slot(self, department_name):
        """Get the lunch break slot for a specific department.
        
        Args:
            department_name (str): Name of the department
            
        Returns:
            int or None: Slot index (3, 4, or 5) for the lunch break, or None if no lunch break assigned
        """
        return self.department_lunch_breaks.get(department_name, None)

    def get_lunch_break_time(self, department_name):
        """Get the lunch break time slot string for a specific department.
        
        Args:
            department_name (str): Name of the department
            
        Returns:
            str or None: Time slot string (e.g., "12:00 - 12:50"), or None if no lunch break assigned
        """
        slot_idx = self.get_lunch_break_slot(department_name)
        if slot_idx is None:
            return None
        return self.lunch_break_slots[slot_idx]

    def is_lunch_break_slot(self, slot_idx, department_name):
        """Check if a given slot is a lunch break slot for the department.
        
        Args:
            slot_idx (int): Time slot index to check
            department_name (str): Name of the department
            
        Returns:
            bool: True if this is a lunch break slot for the department
        """
        lunch_slot = self.get_lunch_break_slot(department_name)
        if lunch_slot is None:
            return False  # No lunch break assigned to this department
        return slot_idx == lunch_slot
    
    def _setup_shift_based_constraints(self):
        """Set up shift-based constraints for departments with single course instances."""
        self.logger.info("Setting up shift-based constraints...")
        
        # Define the three shifts in terms of time slots
        # Shift 1: 8AM - 3PM (theory slots 0-6, lab sessions L1-L4)
        # Shift 2: 10AM - 5PM (theory slots 2-8, lab sessions L2-L5)  
        # Shift 3: 12PM - 7PM (theory slots 4-10, lab sessions L3-L6)
        
        self.shift_definitions = {
            'shift_1': {
                'name': 'Shift 1 (8AM-3PM)',
                'theory_slots': list(range(0, 7)),  # slots 0-6 (8:00-2:50)
                'lab_sessions': ['L1', 'L2', 'L3', 'L4'],  # 8:00-3:30
                'start_time': '8:00',
                'end_time': '3:00'
            },
            'shift_2': {
                'name': 'Shift 2 (10AM-5PM)',
                'theory_slots': list(range(2, 9)),  # slots 2-8 (10:00-4:50)
                'lab_sessions': ['L2', 'L3', 'L4', 'L5'],  # 9:50-5:30
                'start_time': '10:00',
                'end_time': '5:00'
            },
            'shift_3': {
                'name': 'Shift 3 (12PM-7PM)',
                'theory_slots': list(range(4, 11)),  # slots 4-10 (12:00-6:50)
                'lab_sessions': ['L3', 'L4', 'L5', 'L6'],  # 11:50-7:10
                'start_time': '12:00',
                'end_time': '7:10'
            }
        }
        
        # Departments that should follow shift-based constraints
        # These are departments with single course instances that need time-bounded scheduling
        self.shift_departments = {
            'Computer Science & Design': {
                'enabled': True,
                'description': 'Single instance department with shift-based scheduling'
            },
            'Computer Science & Engineering (Cyber Security)': {
                'enabled': True,
                'description': 'Single instance department with shift-based scheduling'
            },
            'Aeronautical Engineering': {
                'enabled': True,
                'description': 'Single instance engineering department with shift-based time constraints'
            },
            'Automobile Engineering': {
                'enabled': True,
                'description': 'Single instance engineering department with shift-based time constraints'
            },
            'Food Technology': {
                'enabled': True,
                'description': 'Single instance technology department with shift-based time constraints'
            },
            'Robotics & Automation': {
                'enabled': True,
                'description': 'Single instance engineering department with shift-based time constraints'
            },
            'Mechatronics Engineering': {
                'enabled': True,
                'description': 'Single instance engineering department with shift-based time constraints'
            }
            # Add more departments here as needed
            # 'Other Department Name': {
            #     'enabled': True,
            #     'description': 'Description here'
            # }
        }
        
        self.logger.info(f"Configured shift-based constraints for {len(self.shift_departments)} departments")
        for dept_name, config in self.shift_departments.items():
            if config['enabled']:
                self.logger.info(f"  - {dept_name}: {config['description']}")
        
        # Initialize shift assignment tracking
        self.daily_shift_assignments = {}  # Will store (dept, day) -> shift_id assignments
    
    def is_shift_department(self, dept_name):
        """Check if a department should follow shift-based constraints."""
        return (dept_name in self.shift_departments and 
                self.shift_departments[dept_name]['enabled'])
    
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
        self.global_room_registry = {}
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
            
            # Check if this is valid co-scheduling for 140-capacity labs
            labs_140_ids = set()
            if hasattr(self, 'lab_capacity_analysis') and 'labs_140' in self.lab_capacity_analysis:
                labs_140_ids = {lab['id'] for lab in self.lab_capacity_analysis['labs_140']}
            
            if room_id in labs_140_ids and len(existing) < 2:
                # Check if this is same course code and same group (co-scheduling eligible)
                existing_session = existing[0]
                same_course = (session_info.get('course_code') == existing_session.get('course_code'))
                same_group = (session_info.get('group_name') == existing_session.get('group_name'))
                
                if same_course and same_group:
                    # Valid co-scheduling for 140-capacity lab
                    existing.append(session_info)
                    self.global_room_registry[key] = existing
                    self.logger.info(f"✅ CO-SCHEDULING SUCCESS: {session_info.get('course_code')} in {session_info.get('group_name')} - "
                                   f"Teachers {existing_session.get('teacher_name')} and {session_info.get('teacher_name')} "
                                   f"share 140-lab {room_id} on {day} {time_slot}")
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
        """Check if room is available in global registry, allowing co-scheduling for 140-capacity labs."""
        day_normalized = self._normalize_day_name(day)
        key = (day_normalized, time_slot, room_id)
        
        if key not in self.global_room_registry:
            return True
        
        # Check if this is a 140-capacity lab and allows co-scheduling
        labs_140_ids = set()
        if hasattr(self, 'lab_capacity_analysis') and 'labs_140' in self.lab_capacity_analysis:
            labs_140_ids = {lab['id'] for lab in self.lab_capacity_analysis['labs_140']}
        
        if room_id in labs_140_ids:
            # For 140-capacity labs, check if existing usage allows co-scheduling
            existing_sessions = self.global_room_registry[key]
            if not isinstance(existing_sessions, list):
                existing_sessions = [existing_sessions]
            
            # Allow up to 2 sessions (co-scheduling)
            if len(existing_sessions) < 2:
                return True
        
        return False

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
                'student_dept': row.get('student_dept', 'Computer Science & Engineering'),
                'has_assistant': row['is_assistant'] == 1,
                'assistant_teacher_id': row.get('assist_teacher_id'),
                'assistant_staff_code': row.get('assist_staff_code'),
                'assistant_teacher_name': f"{row.get('assist_first_name', '')} {row.get('assist_last_name', '')}".strip()
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
        self.logger.info("Creating unified course groups using OR-Tools optimization...")
        
        # Use the new OR-Tools based group creation logic
        # This ensures optimal constraint satisfaction and student choice
        self.course_groups = self._create_course_groups_by_dept_semester()
        
        # Create instance-group mapping for both lab and theory
        self.instance_group_mapping = {}
        self._create_instance_group_mapping()
        
        # Filter lab requirements to only include instances present in groups
        self._filter_lab_requirements_by_groups()
        
        # Identify groups that contain core lab instances
        self._identify_core_lab_groups()
        
        self.logger.info("OR-Tools unified course grouping completed successfully")
        self.logger.info("[OK] UNIFIED CONSTRAINTS: Both lab and theory respect same group structure")
        self.logger.info("[OK] OR-TOOLS OPTIMIZATION: Maximized student choice with constraint satisfaction")
    
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
                'has_theory': int(row.get('lecture_hours', 0)) > 0 or int(row.get('tutorial_hours', 0)) > 0,
                'has_assistant': row['is_assistant'] == 1,
                'assistant_teacher_id': str(row.get('assist_teacher_id')),
                'assistant_staff_code': row.get('assist_staff_code'),
                'assistant_teacher_name': f"{row.get('assist_first_name', '')} {row.get('assist_last_name', '')}".strip()
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

                # Assistant teacher
                if instance.get('has_assistant') and pd.notna(instance.get('assistant_teacher_id')):
                    assistant_id = instance.get('assistant_teacher_id')
                    if assistant_id not in teacher_occurrences:
                        teacher_occurrences[assistant_id] = []
                    teacher_occurrences[assistant_id].append({
                        'course_code': instance['course_code'],
                        'instance_id': instance['id'],
                        'role': 'Assistant'
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
        constraints_applied += self._apply_theory_constraints(model, theory_variables)
        
        # 3. Cross-system constraints (now only for dept/semester group conflicts)
        constraints_applied += self._apply_cross_system_constraints(model, lab_variables, theory_variables)

        # 4. UNIFIED Teacher Clash Constraint (NEW)
        constraints_applied += self._apply_unified_teacher_clash_constraint(model, lab_variables, theory_variables)
        
        self.logger.info(f"Applied {constraints_applied} unified constraints")
    
    def _apply_lab_constraints(self, model, lab_variables):
        """Apply lab-specific constraints."""
        self.logger.info("Applying lab-specific constraints...")
        constraints_applied = 0
        
        # Run lab capacity analysis first
        self.analyze_lab_capacity()
        
        # Apply CORE lab constraints (optimized - removed redundancies)
        constraints_applied += self.apply_course_lab_requirements_constraint(model, lab_variables)
        constraints_applied += self.apply_lab_room_single_assignment_constraint(model, lab_variables)
        # REMOVED: apply_teacher_clash_constraint - handled by unified constraint
        # REMOVED: apply_capacity_constraint - redundant with course_lab_requirements_constraint
        constraints_applied += self.apply_group_based_scheduling_constraint(model, lab_variables)
        constraints_applied += self.apply_core_lab_mapping_constraint(model, lab_variables)
        # NEW: Apply core lab group slot limit constraint (8 slots max for groups containing core labs)
        constraints_applied += self.apply_core_lab_group_slot_limit_constraint(model, lab_variables)
        # NEW: Apply computing group slot limit constraint (6 slots max for computing department groups)
        constraints_applied += self.apply_computing_group_slot_limit_constraint(model, lab_variables)
        # REMOVED: apply_theory_lab_group_conflict_constraint - redundant with cross-system constraints
        # REMOVED: This constraint was too restrictive and prevented the full scheduling of required practical hours.
        constraints_applied += self.apply_semester_lab_slot_limit_constraint(model, lab_variables)
        
        # Apply 140-capacity lab co-scheduling constraints for same course instances
        constraints_applied += self.apply_140_lab_co_scheduling_constraint(model, lab_variables)
        # REMOVED: apply_lab_efficiency_constraints - too restrictive and redundant with other constraints
        
        # Apply lunch break constraint for lab sessions
        constraints_applied += self._apply_lab_lunch_break_constraint(model, lab_variables)
        
        # Apply consecutive batch scheduling constraint for specific departments
        constraints_applied += self.apply_consecutive_batch_scheduling_constraint(model, lab_variables)
        
        # Apply shift-based constraints for departments with single course instances
        constraints_applied += self.apply_shift_based_lab_constraint(model, lab_variables)
        
        self.logger.info(f"Applied {constraints_applied} lab-specific constraints (optimized)")
        return constraints_applied

    def apply_course_lab_requirements_constraint(self, model, lab_variables):
        """CONSTRAINT: Each course must be scheduled for its required number of lab sessions."""
        self.logger.info("Applying course lab requirements constraint...")
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
                        course_matches = self.courses_df[self.courses_df['id'] == int(course_instance_id)]
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
                    
                    # Create conditional constraint based on lab capacity assignment
                    if student_count > 35:
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
                            max_batched_sessions = min(sessions_with_batching, 3)
                            max_unbatched_sessions = min(base_sessions, 1)
                            absolute_max_sessions = 3  # Hard limit for 2 hour courses
                            priority_level = 3  # Lower priority
                        
                        # CRITICAL FIX: 2-hour courses CANNOT use 70+ capacity labs (EXCEPT core labs)
                        if practical_hours <= 2:
                            # Check if this is a core lab that should be exempted from the 35-capacity restriction
                            is_core_lab = course_instance_id in self.core_lab_instance_ids
                            
                            if is_core_lab:
                                # Core labs with 2 practical hours can use both 35 and 70 capacity labs
                                # Allow the same flexible strategy as other courses
                                use_35_cap_strategy = model.NewBoolVar(f'course_{course_instance_id}_use_35_cap_strategy')
                                
                                # Constraint 1: If using 35-cap strategy, ALL sessions must be in 35-cap labs
                                if assignments_in_35_cap and assignments_in_70_plus_cap:
                                    model.Add(total_35_assignments == sum(total_assignments)).OnlyEnforceIf(use_35_cap_strategy)
                                    model.Add(total_70_plus_assignments == 0).OnlyEnforceIf(use_35_cap_strategy)
                                    
                                    # Constraint 2: If using 70+ cap strategy, ALL sessions must be in 70+ cap labs  
                                    model.Add(total_70_plus_assignments == sum(total_assignments)).OnlyEnforceIf(use_35_cap_strategy.Not())
                                    model.Add(total_35_assignments == 0).OnlyEnforceIf(use_35_cap_strategy.Not())
                            
                                    # Constraint 3: Session count depends on chosen strategy
                                    model.Add(sum(total_assignments) == max_batched_sessions).OnlyEnforceIf(use_35_cap_strategy)
                                    model.Add(sum(total_assignments) == max_unbatched_sessions).OnlyEnforceIf(use_35_cap_strategy.Not())
                                    
                                    # Neutral preference for core labs with 2 hours (let solver decide)
                                    constraints_applied += 6
                                    self.logger.info(f"CORE LAB {course_req['course_code']} ({practical_hours}h): ALLOWED to use BOTH 35-cap ({max_batched_sessions} sessions) OR 70+ cap ({max_unbatched_sessions} sessions)")
                                else:
                                    # Fallback assignment for core labs
                                    required_sessions = min(max_batched_sessions, len(total_assignments), absolute_max_sessions)
                                    model.Add(sum(total_assignments) == required_sessions)
                                    constraints_applied += 1
                                    self.logger.info(f"CORE LAB {course_req['course_code']} ({practical_hours}h): fallback assignment with {required_sessions} sessions")
                            else:
                                # FORCE 35-capacity labs ONLY for non-core 2-hour courses
                                if assignments_in_35_cap:
                                    model.Add(total_35_assignments == sum(total_assignments))
                                    model.Add(total_70_plus_assignments == 0)
                                    model.Add(sum(total_assignments) == max_batched_sessions)
                                    constraints_applied += 3
                                    self.logger.info(f"NON-CORE Course {course_req['course_code']} ({practical_hours}h): FORCED to use 35-capacity labs only with {max_batched_sessions} sessions")
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
                                
                                # PRIORITY SYSTEM: Add preference for 70+ capacity labs based on practical hours
                                if priority_level == 1:  # 6+ hours: HIGHEST priority for 70+ labs
                                    # Strong preference for 70+ capacity labs (weight = 1000)
                                    self._add_capacity_preference(model, use_35_cap_strategy, 1000, course_req['course_code'], "6+ hours HIGHEST priority")
                                elif priority_level == 2:  # 4+ hours: SECOND priority for 70+ labs
                                    # Medium preference for 70+ capacity labs (weight = 500)
                                    self._add_capacity_preference(model, use_35_cap_strategy, 500, course_req['course_code'], "4+ hours SECOND priority")
                                else:  # 2-3 hours: Lower priority
                                    # Slight preference for 35-capacity labs (weight = 100)
                                    self._add_capacity_preference(model, use_35_cap_strategy, -100, course_req['course_code'], "2-3 hours lower priority")
                                
                                constraints_applied += 6
                                self.logger.info(f"Course {course_req['course_code']} ({practical_hours}h, Priority {priority_level}): EITHER {max_batched_sessions} sessions (35-cap batched) OR {max_unbatched_sessions} sessions (70+ cap unbatched)")
                            else:
                                # Fallback to simple assignment if capacity separation not possible
                                required_sessions = min(max_batched_sessions, len(total_assignments), absolute_max_sessions)
                                model.Add(sum(total_assignments) == required_sessions)
                                constraints_applied += 1
                                self.logger.info(f"Course {course_req['course_code']} ({practical_hours}h): fallback assignment with {required_sessions} sessions (max {absolute_max_sessions} enforced)")
                    else:
                        # Small courses: always base sessions, but apply same absolute limits based on practical hours
                        if practical_hours >= 6:
                            absolute_max_sessions = 6
                        elif practical_hours >= 4:
                            absolute_max_sessions = 4
                        else:
                            absolute_max_sessions = 2
                        
                        max_sessions = min(base_sessions, absolute_max_sessions)
                        model.Add(sum(total_assignments) == max_sessions)
                        constraints_applied += 1
                        self.logger.info(f"Course {course_req['course_code']} ({practical_hours}h): exactly {max_sessions} sessions (max {absolute_max_sessions} slots enforced)")
        
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

    def apply_lab_room_single_assignment_constraint(self, model, lab_variables):
        """Prevent lab room double-booking with comprehensive cross-pattern validation, allowing co-scheduling for 140-capacity labs."""
        self.logger.info("Applying optimized lab room single assignment constraint with 140-lab co-scheduling support...")
        constraints_applied = 0
        
        # Get 140-capacity lab IDs for special handling (cached)
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
                
                course_matches = self.courses_df[self.courses_df['id'] == int(course_instance_id)]
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
                
            # Special handling for 140-capacity labs - ONLY allow co-scheduling
            if room_id in labs_140:
                # Group assignments by (group_name, course_code) - optimized
                same_course_groups = {}
                for assignment in assignments:
                    key = (assignment['group_name'], assignment['course_code'])
                    if key not in same_course_groups:
                        same_course_groups[key] = []
                    same_course_groups[key].append(assignment)
                
                # Check for valid co-scheduling opportunities
                co_schedulable_groups = []
                invalid_vars = []
                
                for (group_name, course_code), group_assignments in same_course_groups.items():
                    if len(group_assignments) >= 2 and group_name and course_code:
                        # Valid co-scheduling group
                        co_schedulable_groups.append((group_name, course_code, group_assignments))
                    else:
                        # Invalid single instances
                        invalid_vars.extend([ga['variable'] for ga in group_assignments])
                
                # Apply co-scheduling constraints
                for group_name, course_code, group_assignments in co_schedulable_groups:
                    group_vars = [ga['variable'] for ga in group_assignments]
                    
                    # STRICT CONSTRAINT: Either 0 instances OR exactly 2 instances
                    total_assignments = sum(group_vars)
                    course_using_140_lab = model.NewBoolVar(f'course_using_140lab_{group_name}_{course_code}_{absolute_day}_{session_name}_{room_id}')
                    
                    model.Add(total_assignments <= 2 * course_using_140_lab)
                    model.Add(total_assignments >= 2 * course_using_140_lab)
                    constraints_applied += 2
                    
                    if constraints_applied % 100 == 0:  # Reduce logging frequency
                        self.logger.debug(f"🎯 140-lab co-scheduling: {course_code} in {group_name}")
                
                # Block invalid single instances
                if invalid_vars:
                    model.Add(sum(invalid_vars) == 0)
                    constraints_applied += 1
                    
                    if constraints_applied % 100 == 0:  # Reduce logging frequency
                        self.logger.debug(f"🚫 Blocked {len(invalid_vars)} single instances from 140-lab")
            else:
                # Standard labs: at most one course can use this room at this session
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
                            # Separate 140-capacity labs from others for flexibility
                            labs_140_vars = [var for room_id, var in day_sessions[session_name].items() if room_id in labs_140]
                            other_vars = [var for room_id, var in day_sessions[session_name].items() if room_id not in labs_140]
                            
                            if labs_140_vars:
                                # Allow flexibility for 140-lab co-scheduling
                                model.Add(sum(labs_140_vars) + sum(other_vars) <= 1)
                            else:
                                # Standard constraint
                                model.Add(sum(room_vars) <= 1)
                            
                            constraints_applied += 1
        
        self.logger.info(f"Applied {constraints_applied} optimized lab room single assignment constraints")
        self.logger.info(f"Processed {len(time_slot_assignments)} unique session-room combinations")
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
                    course_matches = self.courses_df[self.courses_df['id'] == int(course_instance_id)]
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
        constraints_applied = 0
        
        for teacher_id, lab_courses in self.lab_requirements.items():
            for course_req in lab_courses:
                course_code = course_req['course_code']
                course_instance_id = course_req['course_instance_id']
                
                # Get course name from the original courses data
                course_row = self.courses_df[self.courses_df['id'] == int(course_instance_id)]
                if course_row.empty:
                    self.logger.warning(f"Course instance {course_instance_id} not found in courses data")
                    continue
                    
                course_name = course_row.iloc[0]['course_name']
                
                if teacher_id not in lab_variables or course_instance_id not in lab_variables[teacher_id]:
                    continue
                
                if (course_code, course_name) in self.course_to_room_mapping:
                    required_room_ids = self.course_to_room_mapping[(course_code, course_name)]
                    
                    # Ensure all required rooms are valid lab rooms
                    valid_required_rooms = [room_id for room_id in required_room_ids if room_id in self.lab_room_ids]
                    
                    if not valid_required_rooms:
                        self.logger.warning(f"No valid lab rooms found for course {course_code}. Skipping constraint for this course.")
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
                    
                    self.logger.info(f"Core constraint: Course '{course_code}' - '{course_name}' restricted to {len(valid_required_rooms)} specific room(s): {valid_required_rooms}")
                else:
                    # This course is NOT in the core mapping.
                    # Constrain it to rooms of type 'Laboratory'.
                    self.logger.debug(f"Course '{course_code}' not in core mapping. Constraining to 'Laboratory' type rooms.")
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

        self.logger.info(f"Applied {constraints_applied} core lab mapping constraints.")
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
        """SOFT CONSTRAINT: Prefer to limit computing department groups to 6 lab slots with penalty for exceeding."""
        self.logger.info("Applying computing group soft slot limit constraint (prefer 6 slots for computing groups)...")
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
        
        # Initialize penalty variables list if not exists
        if not hasattr(self, 'computing_group_slot_penalties'):
            self.computing_group_slot_penalties = []
        
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
        
        self.logger.info(f"Identified {len(computing_groups)} computing groups for 6-slot limit constraint")
        
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
            
            self.logger.info(f"Applying soft 6-slot limit to computing group: {group_name} ({len(group_lab_instances)} lab instances)")
            
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
            
            # SOFT CONSTRAINT: Create penalty variable for exceeding 6 slots
            total_group_slots_used = sum(slot_used_vars.values())
            excess_slots = model.NewIntVar(0, len(slot_used_vars), f'computing_group_excess_slots_{group_name}')
            
            # excess_slots = max(0, total_group_slots_used - 6)
            model.AddMaxEquality(excess_slots, [total_group_slots_used - 6, 0])
            constraints_applied += 1
            
            # Add penalty to the list (will be minimized in objective)
            self.computing_group_slot_penalties.append(excess_slots)
            
            self.logger.info(f"  - SOFT CONSTRAINT: Computing group {group_name} prefers <= 6 lab slots ({num_dept_days} days pattern)")
        
        self.logger.info(f"Applied {constraints_applied} computing group soft slot limit constraints")
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
    
    def _apply_theory_constraints(self, model, group_timeslot_vars):
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
        
        # CONSTRAINT 4: Soft constraint - avoid more than 2 consecutive time slots per group per day
        constraints_applied += self._apply_consecutive_slots_soft_constraint(model, group_timeslot_vars)
        
        # CONSTRAINT 5: Lunch break constraint - prevent scheduling during department lunch breaks
        constraints_applied += self._apply_lunch_break_constraint(model, group_timeslot_vars)
        
        # CONSTRAINT 6: Shift-based constraints for departments with single course instances
        constraints_applied += self.apply_shift_based_theory_constraint(model, group_timeslot_vars)
        
        # CONSTRAINT 7: Early scheduling constraint - schedule all theory before 3:00 PM
        constraints_applied += self._apply_early_scheduling_constraint(model, group_timeslot_vars)
        
        self.logger.info(f"Applied {constraints_applied} theory-specific constraints with department-specific day patterns")
        return constraints_applied

    def _apply_consecutive_slots_soft_constraint(self, model, group_timeslot_vars):
        """
        Apply soft constraint to discourage groups from having more than 2 consecutive time slots per day.
        This creates penalty variables that will be minimized in the objective function.
        """
        self.logger.info("Applying soft constraint to avoid more than 2 consecutive group time slots...")
        constraints_applied = 0
        
        # Initialize penalty variables list if not exists
        if not hasattr(self, 'consecutive_slot_penalties'):
            self.consecutive_slot_penalties = []
        
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
                
                # Check all possible sequences of 3 consecutive slots
                for start_slot in range(self.num_theory_slots - 2):
                    consecutive_slots = []
                    for offset in range(3):  # Check 3 consecutive slots
                        slot_idx = start_slot + offset
                        if slot_idx in group_timeslot_vars[group_name][day_idx]:
                            consecutive_slots.append(group_timeslot_vars[group_name][day_idx][slot_idx])
                    
                    # If we have 3 consecutive slot variables, create a penalty
                    if len(consecutive_slots) == 3:
                        # Create a penalty variable that equals 1 if all 3 consecutive slots are assigned
                        penalty_var = model.NewBoolVar(f'penalty_{group_name}_day_{day_idx}_slots_{start_slot}_{start_slot+2}')
                        
                        # If all 3 slots are assigned, penalty = 1; otherwise penalty = 0
                        # penalty_var >= sum(consecutive_slots) - 2 (so if sum=3, penalty>=1, forcing penalty=1)
                        # penalty_var <= sum(consecutive_slots) / 3 (so if sum<3, penalty<=0, forcing penalty=0)
                        model.Add(penalty_var >= sum(consecutive_slots) - 2)
                        model.Add(penalty_var * 3 <= sum(consecutive_slots))
                        
                        # Add to penalties list to be minimized in objective
                        self.consecutive_slot_penalties.append(penalty_var)
                        constraints_applied += 2
                        
                        self.logger.debug(f"Added consecutive slot penalty for {group_name} day {day_idx} slots {start_slot}-{start_slot+2}")
        
        self.logger.info(f"Created {len(self.consecutive_slot_penalties)} consecutive slot penalty variables")
        self.logger.info(f"Applied {constraints_applied} consecutive slot soft constraints")
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
    
    def _apply_proper_theory_room_capacity_constraint(self, model, group_timeslot_vars):
        """
        Apply proper room capacity constraint that considers the actual number of course instances
        within each group, not just the number of groups. Now handles department-specific day patterns.
        """
        self.logger.info("Applying proper theory room capacity constraint based on course instances with department-specific day patterns...")
        constraints_applied = 0
        
        # Pre-calculate the number of theory sessions each group will need per time slot
        group_session_counts = {}
        
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
                group_session_counts[group_name] = 0
                continue
            
            # Count theory course instances in this group
            theory_instances = [inst for inst in group_info['instances'] if inst.get('has_theory', False)]
            
            # Calculate total sessions needed per time slot for this group
            # Each theory course instance needs 1 room when the group is active
            total_sessions_per_slot = 0
            
            for instance in theory_instances:
                lecture_hours = instance.get('lecture_hours', 0)
                tutorial_hours = instance.get('tutorial_hours', 0)
                total_theory_sessions = lecture_hours + tutorial_hours
                
                if total_theory_sessions > 0:
                    # FIXED: Each course instance that has theory sessions will need a room
                    # when this group is scheduled - but we need to account for ALL sessions
                    # that will be created (lecture + tutorial), not just the instance count
                    
                    # Each lecture/tutorial session needs its own room slot
                    # But they can be distributed across the group's allocated time slots
                    # So we need to calculate the MAXIMUM concurrent sessions possible
                    
                    # For now, assume each course instance needs 1 room per time slot
                    # (sessions will be distributed across multiple time slots)
                    total_sessions_per_slot += 1
            
            group_session_counts[group_name] = total_sessions_per_slot
            self.logger.debug(f"Group {group_name}: {len(theory_instances)} theory instances = {total_sessions_per_slot} rooms needed per time slot")
        
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
            
            self.logger.info(f"Applying room capacity constraints for {day_pattern} pattern ({num_dept_days} days, {len(pattern_groups)} groups)")
            
            # Now apply the constraint: for each time slot in this pattern, total rooms needed <= available rooms
            for day_idx in range(num_dept_days):
                for slot_idx in range(self.num_theory_slots):
                    # Calculate total rooms needed at this time slot for this day pattern
                    total_rooms_needed = []
                    
                    for group_name in pattern_groups:
                        sessions_count = group_session_counts.get(group_name, 0)
                        if sessions_count > 0:
                            # If group is scheduled at this time slot, it needs 'sessions_count' rooms
                            if (day_idx in group_timeslot_vars[group_name] and
                                slot_idx in group_timeslot_vars[group_name][day_idx]):
                                group_active = group_timeslot_vars[group_name][day_idx][slot_idx]
                                total_rooms_needed.append(group_active * sessions_count)
                    
                    if total_rooms_needed:
                        # Total rooms needed cannot exceed available theory rooms
                        model.Add(sum(total_rooms_needed) <= len(self.theory_room_ids))
                        constraints_applied += 1
                        
                        # Log constraint details for debugging
                        if len(total_rooms_needed) > 0:
                            max_possible_rooms = sum(group_session_counts.get(gn, 0) for gn in pattern_groups)
                            if max_possible_rooms > len(self.theory_room_ids):
                                day_name = dept_days[day_idx] if day_idx < len(dept_days) else f"day_{day_idx}"
                                self.logger.debug(f"Time slot {day_name} {self.theory_time_slots[slot_idx]} ({day_pattern}): "
                                               f"constraint applied - max {max_possible_rooms} rooms possible, "
                                               f"{len(self.theory_room_ids)} available")
        
        # Log summary of group session requirements
        total_max_sessions = sum(group_session_counts.values())
        self.logger.info(f"Theory room capacity constraint applied successfully:")
        self.logger.info(f"  - Total theory rooms available: {len(self.theory_room_ids)}")
        self.logger.info(f"  - Maximum sessions possible if all groups active: {total_max_sessions}")
        
        for group_name, sessions_count in group_session_counts.items():
            if sessions_count > 0:
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
                self.logger.info(f"  - {group_name} ({day_pattern}): {sessions_count} rooms needed when active")
        
        if total_max_sessions > len(self.theory_room_ids):
            self.logger.warning(f"POTENTIAL ISSUE: Maximum possible sessions ({total_max_sessions}) "
                              f"exceeds available rooms ({len(self.theory_room_ids)}) - "
                              f"but constraint system will prevent over-allocation")
        
        self.logger.info(f"Applied {constraints_applied} proper theory room capacity constraints with department-specific day patterns")
        return constraints_applied
    
    def _apply_cross_system_constraints(self, model, lab_variables, group_timeslot_vars):
        """Apply constraints that prevent conflicts between lab and theory systems."""
        self.logger.info("Applying cross-system conflict prevention constraints...")
        constraints_applied = 0
        
        # CONSTRAINT 1: Department/Semester Group Conflict Prevention
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
                    course_matches = self.courses_df[self.courses_df['id'] == int(course_instance_id)]
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
                                        lab_course_instances.append(course_info)
                            
                            # Check if we have 2 instances of the same course in the same group
                            if len(lab_course_instances) >= 2:
                                for i in range(len(lab_course_instances)):
                                    for j in range(i + 1, len(lab_course_instances)):
                                        if (lab_course_instances[i]['course_code'] == lab_course_instances[j]['course_code'] and
                                            lab_course_instances[i]['group_name'] == lab_course_instances[j]['group_name']):
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
        
        # Lab objective: maximize successful lab assignments
        for teacher_id in lab_variables:
            for course_instance_id in lab_variables[teacher_id]:
                # Get department for this course instance
                dept_name = "Computer Science & Engineering"  # Default
                semester = None
                if hasattr(self, 'instance_group_mapping') and course_instance_id in self.instance_group_mapping:
                    mapping = self.instance_group_mapping[course_instance_id]
                    dept_name = mapping['department']
                    semester = mapping.get('semester')
                else:
                    # Fallback: look up in courses_df
                    course_matches = self.courses_df[self.courses_df['id'] == int(course_instance_id)]
                    if not course_matches.empty:
                        dept_name = course_matches.iloc[0].get('student_dept', 'Computer Science & Engineering')
                
                dept_days = self._get_days_for_department(dept_name, semester)
                num_dept_days = len(dept_days)
                
                for day_idx in range(num_dept_days):
                    if day_idx in lab_variables[teacher_id][course_instance_id]:
                        for session_name in self.lab_sessions.keys():
                            if session_name in lab_variables[teacher_id][course_instance_id][day_idx]:
                                for room_id in self.lab_room_ids:
                                    if room_id in lab_variables[teacher_id][course_instance_id][day_idx][session_name]:
                                        objective_terms.append(lab_variables[teacher_id][course_instance_id][day_idx][session_name][room_id])
        
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
            self.logger.info("  • 140-capacity lab RESERVED for co-scheduling ONLY")
        
        # Add STRONG preference for 70-capacity labs over 140-capacity for single instances
        labs_70_bonus = 1000  # Strong preference for using 70-capacity labs
        labs_140_penalty = -3000  # STRONG penalty for single instances trying to use 140-capacity lab
        
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
                            elif room_capacity > 70:  # 140-capacity labs
                                # PENALTY for single instances trying to use 140-capacity lab
                                # (co-scheduling will override this with the +5000 bonus)
                                objective_terms.append(var * labs_140_penalty)
                                capacity_terms_added += 1
        
        self.logger.info(f"Added {capacity_terms_added} room capacity preference terms to objective (OPTIMIZED)")
        self.logger.info(f"  • 70-capacity lab preference bonus: +{labs_70_bonus}")
        self.logger.info(f"  • 140-capacity lab penalty for single instances: {labs_140_penalty}")
        self.logger.info("  • This ensures 140-capacity lab is ONLY used for co-scheduling")
        
        # Add co-scheduling preferences for 140-capacity lab efficiency
        if hasattr(self, 'co_scheduling_vars') and self.co_scheduling_vars:
            co_scheduling_bonus = 5000  # MUCH HIGHER bonus for co-scheduling same course instances
            for key, var_info in self.co_scheduling_vars.items():
                objective_terms.append(var_info['co_sched_var'] * co_scheduling_bonus)
            
            self.logger.info(f"Added {len(self.co_scheduling_vars)} co-scheduling preference terms to objective")
            self.logger.info("  • STRONGLY encourages co-scheduling of same course instances in 140-capacity lab")
            self.logger.info(f"  • Bonus weight: {co_scheduling_bonus} per co-scheduled pair (INCREASED!)")
        
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
            shift_penalty_weight = 75  # Moderate weight - discourage shift violations but allow flexibility
            for penalty_var in self.shift_preference_vars:
                objective_terms.append(-shift_penalty_weight * penalty_var)
            self.logger.info(f"Added {len(self.shift_preference_vars)} shift violation penalty terms (weight: {shift_penalty_weight})")
            self.logger.info("  • Discourages violation of shift-based time constraints for single-instance departments")
            self.logger.info("  • Encourages consistent shift patterns within departments")
        
        if objective_terms:
            model.Maximize(sum(objective_terms))
            self.logger.info(f"Combined objective set with {len(objective_terms)} terms")
            self.logger.info("Objective strategy:")
            self.logger.info("  1. Lab assignments (base priority)")
            self.logger.info("  2. Group timeslots (no time slot preference)")
            self.logger.info("  3. Room capacity optimization (prefer appropriate room sizes)")
            self.logger.info("  4. Consecutive slot penalty (avoid >2 consecutive slots per group per day)")
            self.logger.info("  5. Late scheduling penalty (strongly prefer theory before 3:00 PM)")
            self.logger.info("  6. Core lab group slot penalty (prefer ≤8 slots for groups with core labs)")
            self.logger.info("  7. Computing group slot penalty (prefer ≤6 slots for computing department groups)")
            self.logger.info("  8. Consecutive batch preference (encourage consecutive batched lab sessions)")
            self.logger.info("  9. Shift-based scheduling penalty (encourage consistent shift patterns for single-instance departments)")
        else:
            self.logger.warning("No objective terms created for group allocation")
    
    def _solve_combined_model(self, model, lab_variables, group_timeslot_vars):
        """Solve the combined scheduling model using two-phase approach."""
        # Create the solver
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 1000
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
        """Check for room conflicts within a single schedule, allowing co-scheduling for 140-capacity labs."""
        conflicts = 0
        room_usage = {}
        
        # Get 140-capacity lab IDs for special handling
        labs_140 = [lab['id'] for lab in self.lab_capacity_analysis.get('labs_140', [])]
        
        for session in schedule:
            day = self._normalize_day_name(session['day'])
            time_slot = session.get('time_slot')
            room_id = session.get('room_id')
            course_code = session.get('course_code', '')
            group_name = session.get('group_name', '')
            
            # For lab sessions, check all time slots in the session
            if schedule_type == "Lab" and 'session_name' in session:
                session_name = session['session_name']
                lab_time_slots = self.lab_sessions.get(session_name, [])
                for lab_time_slot in lab_time_slots:
                    key = (day, lab_time_slot, room_id)
                    if key in room_usage:
                        existing = room_usage[key]
                        existing_course = existing.get('course_code', '')
                        existing_group = existing.get('group_name', '')
                        
                        # Check if this is allowed co-scheduling in 140-capacity lab
                        if (room_id in labs_140 and 
                            course_code == existing_course and 
                            group_name == existing_group and
                            group_name and course_code):  # Same course, same group
                            
                            # This is allowed co-scheduling for same course instances
                            self.logger.info(f"✅ Co-scheduling: {course_code} instances in {group_name} sharing 140-capacity lab {room_id}")
                            
                            # Track multiple sessions for this slot
                            if not isinstance(room_usage[key], list):
                                room_usage[key] = [room_usage[key]]
                            room_usage[key].append(session)
                        else:
                            # This is a real conflict
                            conflicts += 1
                            self.logger.error(f"{schedule_type} room conflict: Room {room_id} on {day} {lab_time_slot}")
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
            lab_time_slots = self.lab_sessions.get(session_name, [])
            
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
                time_slots = self.lab_sessions.get(session_name, [])
            elif session.get('schedule_type') == 'theory':
                time_slots = [session.get('time_slot', '')]
            
            for time_slot in time_slots:
                if not time_slot:
                    continue
                    
                key = (teacher_id, day, time_slot)
                if key in teacher_schedule:
                    conflicts += 1
                    existing = teacher_schedule[key]
                    self.logger.error(f"Teacher conflict: Teacher {teacher_id} on {day} {time_slot}")
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
                                
                                course_matches = self.courses_df[self.courses_df['id'] == int(course_instance_id)]
                                if course_matches.empty:
                                    self.logger.error(f"Course instance ID {course_instance_id} not found in courses dataframe")
                                    continue
                                course_row = course_matches.iloc[0]
                                
                                # Rule 1: Simple batching rule - batch if using 35-capacity lab and have more students
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
                                    'time_range': f"{self.lab_sessions[session_name][0]} to {self.lab_sessions[session_name][-1]}",
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
                                    for lab_time_slot in self.lab_sessions[session_name]:
                                        if not self._is_room_available_global(day_name, lab_time_slot, room_id):
                                            self.logger.error(f"Lab schedule conflict detected during extraction: {course_details['course_code']} cannot use room {room_id} on {day_name} {lab_time_slot}")
                                            conflict_detected = True
                                    
                                    if not conflict_detected:
                                        # Register for all time slots in the lab session
                                        for lab_time_slot in self.lab_sessions[session_name]:
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
                                        'time_range': f"{self.lab_sessions[session_name][0]} to {self.lab_sessions[session_name][-1]}",
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
                                    for lab_time_slot in self.lab_sessions[session_name]:
                                        if not self._is_room_available_global(day_name, lab_time_slot, room_id):
                                            self.logger.error(f"Lab schedule conflict detected during extraction: {course_details['course_code']} cannot use room {room_id} on {day_name} {lab_time_slot}")
                                            conflict_detected = True
                                    
                                    if not conflict_detected:
                                        # Register for all time slots in the lab session
                                        for lab_time_slot in self.lab_sessions[session_name]:
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

    def _identify_co_schedulable_course_instances(self):
        """Identify course instances that can be co-scheduled in 140-capacity labs."""
        self.logger.info("Identifying co-schedulable course instances for 140-capacity lab optimization...")
        
        # Pre-cache course information to avoid repeated DataFrame lookups
        course_cache = {}
        for teacher_id, courses in self.lab_requirements.items():
            for course_req in courses:
                course_instance_id = course_req['course_instance_id']
                if course_instance_id not in course_cache:
                    course_matches = self.courses_df[self.courses_df['id'] == int(course_instance_id)]
                    if not course_matches.empty:
                        course_row = course_matches.iloc[0]
                        course_cache[course_instance_id] = {
                            'course_code': course_row['course_code'],
                            'practical_hours': int(course_row.get('practical_hours', 0)),
                            'student_count': int(course_row['student_count'])
                        }
        
        # Group course instances by (group, course_code) - optimized
        co_schedulable_groups = {}
        core_labs_skipped = 0
        
        for teacher_id, courses in self.lab_requirements.items():
            for course_req in courses:
                course_instance_id = course_req['course_instance_id']
                
                # Skip if course info not cached or doesn't meet criteria
                if (course_instance_id not in course_cache or 
                    course_cache[course_instance_id]['practical_hours'] < 4):
                    continue
                
                # OPTIMIZATION: Skip core labs - they don't have 140-capacity rooms
                if hasattr(self, 'core_lab_instance_ids') and course_instance_id in self.core_lab_instance_ids:
                    core_labs_skipped += 1
                    continue  # Core labs cannot use 140-capacity rooms for co-scheduling
                
                # Get group information (optimized)
                if hasattr(self, 'instance_group_mapping') and course_instance_id in self.instance_group_mapping:
                    group_mapping = self.instance_group_mapping[course_instance_id]
                    group_name = group_mapping['group_name']
                    course_info = course_cache[course_instance_id]
                    
                    key = (group_name, course_info['course_code'])
                    
                    if key not in co_schedulable_groups:
                        co_schedulable_groups[key] = []
                    
                    co_schedulable_groups[key].append({
                        'course_instance_id': course_instance_id,
                        'teacher_id': teacher_id,
                        'practical_hours': course_info['practical_hours'],
                        'course_code': course_info['course_code'],
                        'group_name': group_name,
                        'student_count': course_info['student_count']
                    })
        
        # Filter to valid co-schedulable groups (optimized)
        self.co_schedulable_course_groups = {}
        valid_groups_count = 0
        
        for key, instances in co_schedulable_groups.items():
            if len(instances) >= 2:  # Multiple instances of same course in same group
                group_name, course_code = key
                total_students = sum(inst['student_count'] for inst in instances)
                
                # Check if total students can fit in 140-capacity lab
                if total_students <= 140:
                    self.co_schedulable_course_groups[key] = {
                        'instances': instances,
                        'total_students': total_students,
                        'can_co_schedule': True
                    }
                    valid_groups_count += 1
                    
                    # Reduced logging frequency for performance
                    if valid_groups_count <= 5:  # Log only first 5 groups
                        self.logger.info(f"✅ Co-schedulable group found: {course_code} in {group_name}")
                        self.logger.info(f"   → {len(instances)} instances, {total_students} total students")
                    elif valid_groups_count == 6:
                        self.logger.info("   ... (additional co-schedulable groups found, reducing log output)")
        
        self.logger.info(f"Found {len(self.co_schedulable_course_groups)} co-schedulable course groups for 140-capacity lab")
        if core_labs_skipped > 0:
            self.logger.info(f"  • Skipped {core_labs_skipped} core lab instances (no 140-capacity rooms available)")
        return self.co_schedulable_course_groups

    def apply_140_lab_co_scheduling_constraint(self, model, lab_variables):
        """Apply co-scheduling constraints for 140-capacity lab with same course instances."""
        self.logger.info("Applying optimized 140-capacity lab co-scheduling constraints...")
        constraints_applied = 0
        
        # Get 140-capacity lab IDs (cached as set for O(1) lookup)
        labs_140 = set(lab['id'] for lab in self.lab_capacity_analysis['labs_140'])
        
        if not labs_140:
            self.logger.warning("No 140-capacity labs found for co-scheduling")
            return 0
        
        # Identify co-schedulable course instances (cached)
        if not hasattr(self, 'co_schedulable_course_groups'):
            self._identify_co_schedulable_course_instances()
        
        if not self.co_schedulable_course_groups:
            self.logger.info("No co-schedulable course groups found")
            return 0
        
        # Pre-cache department information for all groups
        group_dept_cache = {}
        for (group_name, course_code) in self.co_schedulable_course_groups.keys():
            if group_name not in group_dept_cache:
                dept_name = group_name.split('_S')[0] if '_S' in group_name else "Computer Science & Engineering"
                semester = None
                if '_S' in group_name:
                    sem_part = group_name.split('_S')[1].split('_G')[0]
                    try:
                        semester = int(sem_part)
                    except ValueError:
                        pass
                group_dept_cache[group_name] = {
                    'dept_name': dept_name,
                    'semester': semester,
                    'dept_days': self._get_days_for_department(dept_name, semester)
                }
        
        # Create co-scheduling variables for objective function (optimized)
        self.co_scheduling_vars = {}
        groups_processed = 0
        
        for (group_name, course_code), group_info in self.co_schedulable_course_groups.items():
            instances = group_info['instances']
            
            if len(instances) < 2:
                continue
            
            groups_processed += 1
            
            # Reduced logging frequency for performance
            if groups_processed <= 3:
                self.logger.info(f"🔄 Setting up co-scheduling for {course_code} in {group_name} ({len(instances)} instances)")
            elif groups_processed == 4:
                self.logger.info("   ... (processing additional co-schedulable groups)")
            
            # Use cached department information
            dept_info = group_dept_cache[group_name]
            dept_days = dept_info['dept_days']
            
            # Pre-collect valid instance variables to avoid repeated lookups
            valid_instances = []
            for instance in instances:
                teacher_id = instance['teacher_id']
                course_instance_id = instance['course_instance_id']
                
                # Double-check: ensure no core labs slip through (should already be filtered)
                if (hasattr(self, 'core_lab_instance_ids') and 
                    course_instance_id in self.core_lab_instance_ids):
                    continue  # Extra safety check - core labs should already be filtered
                
                if (teacher_id in lab_variables and 
                    course_instance_id in lab_variables[teacher_id]):
                    valid_instances.append(instance)
            
            if len(valid_instances) < 2:
                continue
            
            # Optimized constraint creation - only for valid combinations
            for day_idx in range(len(dept_days)):
                for session_name in self.lab_sessions.keys():
                    for lab_140_id in labs_140:
                        # Collect assignment variables for these instances in this slot (optimized)
                        instance_vars = []
                        
                        for instance in valid_instances:
                            teacher_id = instance['teacher_id']
                            course_instance_id = instance['course_instance_id']
                            
                            # Direct access with error checking
                            try:
                                if (day_idx in lab_variables[teacher_id][course_instance_id] and
                                    session_name in lab_variables[teacher_id][course_instance_id][day_idx] and
                                    lab_140_id in lab_variables[teacher_id][course_instance_id][day_idx][session_name]):
                                    
                                    instance_var = lab_variables[teacher_id][course_instance_id][day_idx][session_name][lab_140_id]
                                    instance_vars.append((instance_var, instance))
                            except (KeyError, IndexError):
                                continue  # Skip invalid combinations
                        
                        if len(instance_vars) >= 2:
                            # Create simplified co-scheduling detection variable
                            var_name = f'co_schedule_{course_code}_{group_name}_d{day_idx}_s{session_name}_l{lab_140_id}'
                            co_sched_var = model.NewBoolVar(var_name)
                            
                            # Simplified constraint: co-scheduling is active when exactly 2 instances are scheduled
                            vars_sum = sum(var for var, _ in instance_vars)
                            model.Add(vars_sum == 2 * co_sched_var)
                            
                            # Store for objective function (optimized structure)
                            key = (course_code, group_name, day_idx, session_name, lab_140_id)
                            self.co_scheduling_vars[key] = {
                                'co_sched_var': co_sched_var,
                                'instance_vars': [var for var, _ in instance_vars],
                                'total_students': sum(inst['student_count'] for _, inst in instance_vars)
                            }
                            
                            constraints_applied += 1
        
        self.logger.info(f"✅ Applied {constraints_applied} optimized co-scheduling detection constraints for 140-capacity lab")
        self.logger.info(f"  • {len(self.co_schedulable_course_groups)} co-schedulable groups processed")
        self.logger.info(f"  • 140-capacity lab RESERVED for co-scheduling ONLY")
        return constraints_applied

    def _find_capacity_aware_theory_room(self, day_idx, time_slot_idx, used_rooms_this_slot, existing_schedule, dept_days, session, assigned_sessions_this_slot, lab_schedule=None):
        """
        Find an available theory room with capacity-aware assignment prioritizing high-capacity rooms 
        for co-scheduled instances and reserving 140+ capacity rooms from regular 70-student instances.
        
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
        
        self.logger.debug(f"Finding capacity-aware theory room for {course_code} "
                         f"({student_count} students) on {day_name} {time_slot}")
        
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
        
        # Get room capacities for smart assignment
        room_capacities = {}
        for room_id in self.theory_room_ids:
            if room_id not in all_occupied_rooms:
                room_row = self.rooms_df[self.rooms_df['id'] == room_id]
                if not room_row.empty:
                    room_capacities[room_id] = int(room_row.iloc[0]['room_max_cap'])
        
        # PRIORITY 1: If this is a co-scheduled instance and partner is assigned, use same room if available
        if is_co_scheduled and co_scheduled_partner_room is not None:
            if co_scheduled_partner_room in room_capacities:
                self.logger.info(f"Assigning co-scheduled instance {virtual_id} to same room {co_scheduled_partner_room} as partner")
                return co_scheduled_partner_room
        
        # PRIORITY 2: For co-scheduled instances, prefer 140+ capacity rooms
        if is_co_scheduled:
            high_capacity_rooms = [rid for rid, cap in room_capacities.items() if cap >= 140]
            if high_capacity_rooms:
                # Sort by capacity (prefer exactly 140, then higher)
                high_capacity_rooms.sort(key=lambda rid: room_capacities[rid])
                selected_room = high_capacity_rooms[0]
                self.logger.info(f"Assigning co-scheduled instance {virtual_id} to high-capacity room {selected_room} "
                               f"(capacity: {room_capacities[selected_room]})")
                return selected_room
        
        # PRIORITY 3: For regular instances (70 students), prefer 70-110 capacity rooms
        # Avoid 140+ capacity rooms unless no other option
        if not is_co_scheduled:
            # Try 70-110 capacity rooms first
            suitable_rooms = [rid for rid, cap in room_capacities.items() if 70 <= cap <= 110]
            if suitable_rooms:
                # Sort by capacity (prefer closest to student count)
                suitable_rooms.sort(key=lambda rid: abs(room_capacities[rid] - student_count))
                selected_room = suitable_rooms[0]
                self.logger.debug(f"Assigning regular instance {course_code} to suitable room {selected_room} "
                                f"(capacity: {room_capacities[selected_room]}, students: {student_count})")
                return selected_room
            
            # If no suitable rooms, check if any 140+ rooms are available but warn
            high_capacity_rooms = [rid for rid, cap in room_capacities.items() if cap >= 140]
            if high_capacity_rooms:
                # Only use if absolutely necessary
                selected_room = high_capacity_rooms[0]
                self.logger.warning(f"Using high-capacity room {selected_room} for regular instance {course_code} "
                                  f"(capacity: {room_capacities[selected_room]}, students: {student_count}) "
                                  f"- should be reserved for co-scheduled instances")
                return selected_room
        
        # FALLBACK: Any available room if no capacity-aware assignment possible
        available_rooms = list(room_capacities.keys())
        if available_rooms:
            fallback_room = available_rooms[0]
            self.logger.warning(f"Using fallback room assignment: {fallback_room} for {course_code}")
            return fallback_room
        
        # If no room available, log detailed warning
        self.logger.error(f"No available theory room for {course_code} on {day_name} {time_slot}")
        self.logger.error(f"  Theory occupied: {len(occupied_rooms)} rooms")
        self.logger.error(f"  Used this slot: {len(used_rooms_this_slot)} rooms") 
        self.logger.error(f"  Global conflicts: {len(global_occupied_rooms)} rooms")
        self.logger.error(f"  Lab conflicts: {len(lab_conflict_rooms)} rooms")
        self.logger.error(f"  Total occupied: {len(all_occupied_rooms)}/{len(self.theory_room_ids)} rooms")
        
        return None

    def _apply_lunch_break_constraint(self, model, group_timeslot_vars):
        """
        Prevent any group from being scheduled in its department's lunch break slot.
        """
        self.logger.info("Applying lunch break constraint for all departments...")
        constraints_applied = 0
        
        for group_name in group_timeslot_vars.keys():
            # Parse department name from group name: "Department_S3_G1" -> "Department"
            dept_name = group_name.split('_S')[0] if '_S' in group_name else "Computer Science & Engineering"
            
            # Extract semester from group name for semester-specific overrides
            semester = None
            if '_S' in group_name:
                try:
                    semester_part = group_name.split('_S')[1].split('_G')[0]
                    semester = int(semester_part)
                except (ValueError, IndexError):
                    pass
            
            # Get department-specific days (with semester override if available)
            dept_days = self._get_days_for_department(dept_name, semester)
            num_dept_days = len(dept_days)
            
            # Get the lunch break slot for this department
            lunch_slot = self.get_lunch_break_slot(dept_name)
            
            # Skip departments without lunch break assignments
            if lunch_slot is None:
                self.logger.debug(f"No lunch break assigned for department: {dept_name} - skipping lunch constraints")
                continue
            
            # For each working day of this department, prevent scheduling in lunch break slot
            for day_idx in range(num_dept_days):
                # No group can be scheduled in its lunch break slot
                if (day_idx in group_timeslot_vars[group_name] and 
                    lunch_slot in group_timeslot_vars[group_name][day_idx]):
                    model.Add(group_timeslot_vars[group_name][day_idx][lunch_slot] == 0)
                    constraints_applied += 1
                    self.logger.debug(f"Lunch constraint: {group_name} blocked from day {day_idx} slot {lunch_slot} ({self.theory_time_slots[lunch_slot]}) - {dept_name}")
                else:
                    self.logger.debug(f"Lunch constraint skipped: {group_name} day {day_idx} slot {lunch_slot} not in variables - {dept_name}")
        
        self.logger.info(f"Applied {constraints_applied} lunch break constraints.")
        return constraints_applied

    def _apply_lab_lunch_break_constraint(self, model, lab_variables):
        """
        Prevent any lab session from being scheduled during its department's lunch break slot.
        """
        self.logger.info("Applying lunch break constraint for lab sessions...")
        constraints_applied = 0
        
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
                # Get department for this course instance
                dept_name = "Computer Science & Engineering"  # Default
                if hasattr(self, 'instance_group_mapping') and course_instance_id in self.instance_group_mapping:
                    dept_name = self.instance_group_mapping[course_instance_id]['department']
                else:
                    # Fallback: look up in courses_df
                    course_matches = self.courses_df[self.courses_df['id'] == int(course_instance_id)]
                    if not course_matches.empty:
                        dept_name = course_matches.iloc[0].get('student_dept', 'Computer Science & Engineering')
                
                # Get the lunch break slot for this department
                lunch_slot_idx = self.get_lunch_break_slot(dept_name)
                
                # Skip departments without lunch break assignments
                if lunch_slot_idx is None:
                    continue  # No lunch break assigned for this department
                
                # Get the lab sessions that overlap with this department's lunch break
                overlapping_sessions = lunch_slot_to_lab_sessions.get(lunch_slot_idx, [])
                
                if not overlapping_sessions:
                    continue  # No overlapping sessions for this lunch slot
                
                # Get department-specific days
                dept_days = self._get_days_for_department(dept_name)
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
                                        
                                        self.logger.debug(f"Lab lunch break constraint: {course_code} ({dept_name}) in lunch break slot {lunch_slot_idx + 1}")
        
        self.logger.info(f"Applied {constraints_applied} lab lunch break constraints")
        return constraints_applied

    def apply_consecutive_batch_scheduling_constraint(self, model, lab_variables):
        """
        CONSTRAINT: For specific departments with batched 4+ practical hour courses,
        enforce consecutive scheduling for batch sessions.
        
        - HARD constraint for Biotechnology: Must schedule batch sessions consecutively
        - SOFT constraint for other departments: Prefers consecutive scheduling but allows flexibility
        """
        self.logger.info("Applying consecutive batch scheduling constraint for specific departments...")
        constraints_applied = 0
        
        # Define departments with hard consecutive requirements
        hard_consecutive_departments = [
            'Biotechnology',
            'Food Technology',
            'Chemical Engineering',
        ]
        
        # Define departments with soft consecutive preferences
        soft_consecutive_departments = [
                 'Biomedical Engineering'
            # Add more departments as needed
        ]
        
        # All departments that need consecutive batch scheduling
        consecutive_batch_departments = hard_consecutive_departments + soft_consecutive_departments
        
        # Only apply to the most common consecutive pairs to avoid over-constraining
        preferred_consecutive_pairs = [
            ('L1', 'L2'),  # 8:00-9:40 and 9:50-11:30 (morning block)
            ('L3', 'L4'),  # 11:50-1:30 and 1:50-3:30 (around lunch)
            ('L5', 'L6')   # 3:50-5:30 and 5:30-7:10 (evening block)
        ]
        
        # Store consecutive preference variables for objective (soft constraints only)
        consecutive_preference_vars = []
        
        for teacher_id in lab_variables:
            for course_instance_id in lab_variables[teacher_id]:
                # Get course details
                course_req = next((req for req in self.lab_requirements.get(teacher_id, []) 
                                 if req['course_instance_id'] == course_instance_id), None)
                
                if not course_req:
                    continue  # Skip if course not found
                
                practical_hours = course_req['practical_hours']
                students_per_instance = course_req['students_per_instance']
                
                # Only apply to courses with 4+ practical hours that need batching
                if practical_hours < 4 or students_per_instance <= 35:
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
                
                # Only apply to specific departments
                if dept_name not in consecutive_batch_departments:
                    continue
                
                # Get lab capacity categories
                labs_35 = [lab['id'] for lab in self.lab_capacity_analysis['labs_35']]
                
                # Check if course has variables for 35-capacity labs
                has_35_cap_assignments = False
                for day_idx in lab_variables[teacher_id][course_instance_id]:
                    for session_name in lab_variables[teacher_id][course_instance_id][day_idx]:
                        for room_id in lab_variables[teacher_id][course_instance_id][day_idx][session_name]:
                            if room_id in labs_35:
                                has_35_cap_assignments = True
                                break
                        if has_35_cap_assignments:
                            break
                    if has_35_cap_assignments:
                        break
                
                if not has_35_cap_assignments:
                    continue  # No 35-capacity lab assignments possible
                
                # Get department-specific days
                dept_days = self._get_days_for_department(dept_name)
                num_dept_days = len(dept_days)
                
                # Determine if this is a hard or soft constraint
                is_hard_constraint = dept_name in hard_consecutive_departments
                constraint_type = "HARD" if is_hard_constraint else "soft"
                
                self.logger.info(f"Applying {constraint_type} consecutive batch constraint for {course_req['course_code']} "
                               f"({dept_name}, {practical_hours}h, {students_per_instance} students)")
                
                # For each day, create consecutive scheduling constraints
                for day_idx in range(num_dept_days):
                    if day_idx not in lab_variables[teacher_id][course_instance_id]:
                        continue
                    
                    # Apply constraint to preferred consecutive pairs
                    for session1, session2 in preferred_consecutive_pairs:
                        if (session1 in lab_variables[teacher_id][course_instance_id][day_idx] and 
                            session2 in lab_variables[teacher_id][course_instance_id][day_idx]):
                            
                            # Collect assignments for each session in 35-capacity labs
                            session1_vars = []
                            session2_vars = []
                            
                            for room_id in labs_35:
                                if room_id in lab_variables[teacher_id][course_instance_id][day_idx][session1]:
                                    session1_vars.append(lab_variables[teacher_id][course_instance_id][day_idx][session1][room_id])
                                if room_id in lab_variables[teacher_id][course_instance_id][day_idx][session2]:
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
                                
                                if is_hard_constraint:
                                    # HARD CONSTRAINT for Biotechnology:
                                    # If either session is used, both must be used (consecutive scheduling enforced)
                                    # This ensures batch sessions are always consecutive
                                    model.Add(session1_used == session2_used)
                                    
                                    constraints_applied += 1
                                    self.logger.debug(f"HARD consecutive constraint: {course_req['course_code']} day {day_idx} "
                                                    f"{session1}-{session2} MUST be scheduled together or not at all")
                                else:
                                    # SOFT CONSTRAINT for other departments:
                                    # Create preference variable for consecutive scheduling
                                    consecutive_pref = model.NewBoolVar(f'consecutive_pref_{course_instance_id}_{day_idx}_{session1}_{session2}')
                                    
                                    # Preference is satisfied if both sessions are used together OR neither is used
                                    both_used = model.NewBoolVar(f'both_used_{course_instance_id}_{day_idx}_{session1}_{session2}')
                                    model.AddBoolAnd([session1_used, session2_used]).OnlyEnforceIf(both_used)
                                    model.AddBoolOr([session1_used.Not(), session2_used.Not()]).OnlyEnforceIf(both_used.Not())
                                    
                                    neither_used = model.NewBoolVar(f'neither_used_{course_instance_id}_{day_idx}_{session1}_{session2}')
                                    model.AddBoolAnd([session1_used.Not(), session2_used.Not()]).OnlyEnforceIf(neither_used)
                                    model.AddBoolOr([session1_used, session2_used]).OnlyEnforceIf(neither_used.Not())
                                    
                                    # Consecutive preference is satisfied if both are used OR neither is used
                                    model.AddBoolOr([both_used, neither_used]).OnlyEnforceIf(consecutive_pref)
                                    model.AddBoolAnd([both_used.Not(), neither_used.Not()]).OnlyEnforceIf(consecutive_pref.Not())
                                    
                                    # Add to preference variables for objective
                                    consecutive_preference_vars.append(consecutive_pref)
                                    constraints_applied += 1
                                    
                                    self.logger.debug(f"Soft consecutive constraint: {course_req['course_code']} day {day_idx} "
                                                    f"{session1}-{session2} preferred to be scheduled together")
        
        # Store preference variables for use in objective function (soft constraints only)
        if not hasattr(self, 'consecutive_batch_preference_vars'):
            self.consecutive_batch_preference_vars = []
        self.consecutive_batch_preference_vars.extend(consecutive_preference_vars)
        
        # Count hard vs soft constraints
        hard_constraints_count = 0
        soft_constraints_count = len(consecutive_preference_vars)
        
        # Estimate hard constraints applied (we don't track them separately in the loop)
        total_constraints_applied = constraints_applied
        hard_constraints_count = total_constraints_applied - soft_constraints_count
        
        self.logger.info(f"Applied {total_constraints_applied} consecutive batch scheduling constraints:")
        self.logger.info(f"  - {hard_constraints_count} HARD constraints (Biotechnology)")
        self.logger.info(f"  - {soft_constraints_count} soft constraints (other departments)")
        self.logger.info(f"Created {len(consecutive_preference_vars)} consecutive batch preference variables for optimization")
        return constraints_applied

    def apply_shift_based_lab_constraint(self, model, lab_variables):
        """
        CONSTRAINT: Apply shift-based scheduling constraints for departments with single course instances.
        Each day for shift departments can be assigned to one of three shifts:
        - Shift 1: 8AM-3PM (L1, L2, L3, L4)
        - Shift 2: 10AM-5PM (L2, L3, L4, L5)  
        - Shift 3: 12PM-7PM (L3, L4, L5, L6)
        
        All courses from the same department must respect the same shift on the same day.
        This is implemented as a SOFT constraint to avoid infeasibility.
        """
        self.logger.info("Applying soft shift-based lab constraints for single-instance departments...")
        constraints_applied = 0
        
        # Group courses by department
        dept_courses = defaultdict(list)
        
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
                
                # Only apply to shift departments
                if self.is_shift_department(dept_name):
                    dept_courses[dept_name].append((teacher_id, course_instance_id))
        
        if not dept_courses:
            self.logger.info("No shift-based departments found in lab variables")
            return 0
        
        # Initialize shift preference variables for soft constraints
        if not hasattr(self, 'shift_preference_vars'):
            self.shift_preference_vars = []
        
        # Apply constraints for each shift department
        for dept_name, courses in dept_courses.items():
            self.logger.info(f"Applying soft shift constraints for {dept_name} with {len(courses)} lab courses")
            
            # Get department-specific days
            dept_days = self._get_days_for_department(dept_name)
            num_dept_days = len(dept_days)
            
            # For each day, create shift assignment variables (but allow flexibility)
            shift_vars = {}  # day_idx -> {shift_id: bool_var}
            
            for day_idx in range(num_dept_days):
                shift_vars[day_idx] = {}
                for shift_id in self.get_available_shifts():
                    shift_vars[day_idx][shift_id] = model.NewBoolVar(
                        f'dept_{dept_name}_day_{day_idx}_shift_{shift_id}_soft'
                    )
                
                # SOFT CONSTRAINT: Prefer to assign each day to exactly one shift, but allow violations
                # Create penalty variable for not following exactly one shift
                shift_violation = model.NewBoolVar(f'shift_violation_{dept_name}_day_{day_idx}')
                
                # Shift violation occurs if we don't have exactly one shift
                total_shifts = sum(shift_vars[day_idx].values())
                model.Add(total_shifts == 1).OnlyEnforceIf(shift_violation.Not())
                model.Add(total_shifts != 1).OnlyEnforceIf(shift_violation)
                
                # Add penalty to objective (prefer not to violate)
                self.shift_preference_vars.append(shift_violation)
                constraints_applied += 2
            
            # For each course, create soft preferences for shift compliance
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
                    
                    # Create soft preferences for shift compliance instead of hard constraints
                    for shift_id in self.get_available_shifts():
                        allowed_sessions = self.get_shift_lab_sessions(shift_id)
                        forbidden_sessions = [s for s in self.lab_sessions.keys() if s not in allowed_sessions]
                        
                        # Create penalty variable for using forbidden sessions when this shift is active
                        if forbidden_sessions:
                            shift_violation_penalty = model.NewBoolVar(
                                f'shift_penalty_{course_instance_id}_{day_idx}_{shift_id}'
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
                                # Penalty is active if shift is chosen AND forbidden sessions are used
                                forbidden_used = model.NewBoolVar(f'forbidden_used_{course_instance_id}_{day_idx}_{shift_id}')
                                model.Add(sum(forbidden_usage) >= 1).OnlyEnforceIf(forbidden_used)
                                model.Add(sum(forbidden_usage) == 0).OnlyEnforceIf(forbidden_used.Not())
                                
                                # Penalty occurs when both shift is active and forbidden sessions are used
                                model.AddBoolAnd([shift_vars[day_idx][shift_id], forbidden_used]).OnlyEnforceIf(shift_violation_penalty)
                                model.AddBoolOr([shift_vars[day_idx][shift_id].Not(), forbidden_used.Not()]).OnlyEnforceIf(shift_violation_penalty.Not())
                                
                                # Add to preference variables (to be minimized)
                                self.shift_preference_vars.append(shift_violation_penalty)
                                constraints_applied += 3
                
                self.logger.debug(f"Applied soft shift constraints for lab course {course_code} in {dept_name}")
        
        # Store shift variables for cross-system coordination
        if not hasattr(self, 'lab_shift_vars'):
            self.lab_shift_vars = {}
        if dept_courses:
            self.lab_shift_vars.update({dept_name: shift_vars for dept_name, courses in dept_courses.items() 
                                       if dept_name not in self.lab_shift_vars})
        
        self.logger.info(f"Applied {constraints_applied} soft shift-based lab constraints")
        self.logger.info(f"Created {len(self.shift_preference_vars)} shift preference variables")
        return constraints_applied
    
    def apply_shift_based_theory_constraint(self, model, group_timeslot_vars):
        """
        CONSTRAINT: Apply shift-based scheduling constraints for theory sessions in departments with single course instances.
        Each day for shift departments can be assigned to one of three shifts:
        - Shift 1: 8AM-3PM (theory slots 0-6)
        - Shift 2: 10AM-5PM (theory slots 2-8)
        - Shift 3: 12PM-7PM (theory slots 4-10)
        
        All groups from the same department must respect the same shift on the same day.
        This constraint coordinates with lab shift assignments if available.
        This is implemented as a SOFT constraint to avoid infeasibility.
        """
        self.logger.info("Applying soft shift-based theory constraints for single-instance departments...")
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
            self.logger.info("No shift-based departments found in theory groups")
            return 0
        
        # Initialize shift preference variables if not already done
        if not hasattr(self, 'shift_preference_vars'):
            self.shift_preference_vars = []
        
        # Apply constraints for each shift department
        for dept_name, groups in dept_groups.items():
            self.logger.info(f"Applying soft shift constraints for {dept_name} with {len(groups)} theory groups")
            
            # Get department-specific days
            dept_days = self._get_days_for_department(dept_name)
            num_dept_days = len(dept_days)
            
            # Check if we have lab shift variables for coordination
            has_lab_shifts = (hasattr(self, 'lab_shift_vars') and 
                            dept_name in self.lab_shift_vars)
            
            # For each day, create or reuse shift assignment variables
            if has_lab_shifts:
                # Reuse lab shift variables for coordination
                shift_vars = self.lab_shift_vars[dept_name]
                self.logger.info(f"Coordinating theory shifts with existing lab shifts for {dept_name}")
            else:
                # Create new shift variables for theory only (with soft constraints)
                shift_vars = {}
                for day_idx in range(num_dept_days):
                    shift_vars[day_idx] = {}
                    for shift_id in self.get_available_shifts():
                        shift_vars[day_idx][shift_id] = model.NewBoolVar(
                            f'dept_{dept_name}_day_{day_idx}_shift_{shift_id}_theory_soft'
                        )
                    
                    # SOFT CONSTRAINT: Prefer to assign each day to exactly one shift
                    shift_violation = model.NewBoolVar(f'theory_shift_violation_{dept_name}_day_{day_idx}')
                    
                    total_shifts = sum(shift_vars[day_idx].values())
                    model.Add(total_shifts == 1).OnlyEnforceIf(shift_violation.Not())
                    model.Add(total_shifts != 1).OnlyEnforceIf(shift_violation)
                    
                    # Add penalty to objective
                    self.shift_preference_vars.append(shift_violation)
                    constraints_applied += 2
            
            # For each group, create soft preferences for shift compliance
            for group_name in groups:
                if group_name not in group_timeslot_vars:
                    continue
                
                for day_idx in range(num_dept_days):
                    if day_idx not in group_timeslot_vars[group_name]:
                        continue
                    
                    # Create soft preferences for shift compliance instead of hard constraints
                    for shift_id in self.get_available_shifts():
                        allowed_slots = self.get_shift_theory_slots(shift_id)
                        forbidden_slots = [s for s in range(self.num_theory_slots) if s not in allowed_slots]
                        
                        # Create penalty for using forbidden slots when this shift is active
                        if forbidden_slots:
                            theory_shift_penalty = model.NewBoolVar(
                                f'theory_shift_penalty_{group_name}_{day_idx}_{shift_id}'
                            )
                            
                            # Count forbidden slot usage
                            forbidden_slot_usage = []
                            for slot_idx in forbidden_slots:
                                if slot_idx in group_timeslot_vars[group_name][day_idx]:
                                    forbidden_slot_usage.append(group_timeslot_vars[group_name][day_idx][slot_idx])
                            
                            if forbidden_slot_usage:
                                # Penalty is active if shift is chosen AND forbidden slots are used
                                forbidden_used = model.NewBoolVar(f'theory_forbidden_used_{group_name}_{day_idx}_{shift_id}')
                                model.Add(sum(forbidden_slot_usage) >= 1).OnlyEnforceIf(forbidden_used)
                                model.Add(sum(forbidden_slot_usage) == 0).OnlyEnforceIf(forbidden_used.Not())
                                
                                # Penalty occurs when both shift is active and forbidden slots are used
                                model.AddBoolAnd([shift_vars[day_idx][shift_id], forbidden_used]).OnlyEnforceIf(theory_shift_penalty)
                                model.AddBoolOr([shift_vars[day_idx][shift_id].Not(), forbidden_used.Not()]).OnlyEnforceIf(theory_shift_penalty.Not())
                                
                                # Add to preference variables
                                self.shift_preference_vars.append(theory_shift_penalty)
                                constraints_applied += 3
                
                self.logger.debug(f"Applied soft shift constraints for theory group {group_name}")
            
            # Store shift variables if they were newly created
            if not has_lab_shifts:
                if not hasattr(self, 'theory_shift_vars'):
                    self.theory_shift_vars = {}
                self.theory_shift_vars[dept_name] = shift_vars
        
        self.logger.info(f"Applied {constraints_applied} soft shift-based theory constraints")
        self.logger.info(f"Total shift preference variables: {len(self.shift_preference_vars)}")
        return constraints_applied