"""
Data Loader Module

Loads and validates all input data for the scheduler:
- Courses (from CSV)
- Rooms (from techlongue.csv or fallback)
- Time slots configuration (theory and lab)
- Day order and department-specific patterns
- Lunch break and shift configurations

Returns a clean, validated data dictionary with all required structures.
"""

import os
import pandas as pd
import logging
import json
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime
from collections import defaultdict

# Import utility modules (one level up from data folder)
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from utils.data_utils import (
    DataNormalizer,
    DataValidator,
    DataExtractor,
    DataTransformer,
    DataSummary,
)
from utils.room_utils import (
    RoomParser,
    RoomValidator,
    FloorExtractor,
    RoomRegistry,
)
from utils.time_utils import (
    TimeConfiguration,
    DayNormalizer,
)
from utils.dept_utils import (
    DepartmentParser,
    DepartmentGrouper,
)

logger = logging.getLogger(__name__)


class DataValidationError(Exception):
    """Custom exception for data validation failures."""
    pass


class DataLoader:
    """
    Unified data loader for the timetable scheduler.
    
    Responsibilities:
    - Load courses, rooms, time configurations
    - Validate data integrity
    - Normalize formats (day names, room IDs, teacher IDs)
    - Handle missing or inconsistent data with graceful fallbacks
    - Return a clean, structured data dictionary
    """
    
    def __init__(self, 
                 courses_csv: str,
                 rooms_csv: str = None,
                 config_dir: str = 'config',
                 data_dir: str = 'data'):
        """
        Initialize the data loader.
        
        Args:
            courses_csv: Path to courses CSV file
            rooms_csv: Path to rooms CSV file (optional, will use techlongue.csv if exists)
            config_dir: Directory containing config YAML files
            data_dir: Directory containing data files (day_order.csv, etc.)
        """
        self.courses_csv = courses_csv
        self.rooms_csv = rooms_csv
        self.config_dir = config_dir
        self.data_dir = data_dir
        
        logger.info(f"DataLoader initialized with courses={courses_csv}, rooms={rooms_csv}")
    
    def load(self) -> Dict[str, Any]:
        """
        Load and validate all data.
        
        Returns:
            Dictionary with keys:
            - courses: list of course dicts
            - rooms: list of room dicts
            - teachers: set of teacher IDs
            - departments: set of department names
            - time_slots: dict with 'theory' and 'lab' arrays
            - days: list of day names
            - num_days: int
            - day_order: dict mapping dept -> day_pattern
            - room_registry: dict mapping room_id -> room_info
            - groups: dict (initially empty, populated by scheduler)
            - horizon: int (total time slots)
        """
        logger.info("=" * 80)
        logger.info("STARTING DATA LOAD")
        logger.info("=" * 80)

        courses_df = self._load_courses()
        rooms_df = self._load_rooms()
        day_order_df = self._load_day_order()
        
        logger.info(f"Loaded {len(courses_df)} courses, {len(rooms_df)} rooms")
        
        courses = self._parse_courses(courses_df)
        rooms = self._parse_rooms(rooms_df)
        
        teachers = self._extract_teachers(courses)
        departments = self._extract_departments(courses)
        
        time_slots = self._load_time_slots()
        days = self._load_days()
        day_order = self._load_day_order_mapping(day_order_df)
        
        room_registry = self._build_room_registry(rooms)
        
        horizon = len(days) * len(time_slots.get('theory', []))
        
        self._validate_data_integrity(courses, rooms, teachers, departments)
        
        data = {
            'courses': courses,
            'rooms': rooms,
            'teachers': teachers,
            'departments': departments,
            'time_slots': time_slots,
            'days': days,
            'num_days': len(days),
            'day_order': day_order,
            'room_registry': room_registry,
            'groups': {},  # Populated by scheduler
            'horizon': horizon,
            'load_timestamp': datetime.now().isoformat(),
        }
        
        logger.info(f"Data load complete. Stats: {len(courses)} courses, {len(rooms)} rooms, "
                   f"{len(teachers)} teachers, {len(departments)} departments, horizon={horizon}")
        logger.info("=" * 80)
        
        return data
    
    def _load_courses(self) -> pd.DataFrame:
        """Load courses CSV, handle missing file gracefully."""
        if not os.path.exists(self.courses_csv):
            raise FileNotFoundError(f"Courses file not found: {self.courses_csv}")
        
        try:
            df = pd.read_csv(self.courses_csv)
            logger.info(f"Loaded courses from {self.courses_csv}: {len(df)} rows")
            return df
        except Exception as e:
            logger.error(f"Error loading courses CSV: {e}")
            raise DataValidationError(f"Failed to load courses: {e}")
    
    def _load_rooms(self) -> pd.DataFrame:
        """Load rooms CSV with fallback to techlongue.csv."""
        # Try techlongue first
        techlongue_paths = [
            'data/block_wise/techlongue.csv',
            './data/block_wise/techlongue.csv',
            os.path.join(self.data_dir, 'block_wise', 'techlongue.csv'),
        ]
        
        for path in techlongue_paths:
            if os.path.exists(path):
                try:
                    df = pd.read_csv(path)
                    logger.info(f"Loaded rooms from techlongue.csv: {path} ({len(df)} rooms)")
                    return df
                except Exception as e:
                    logger.warning(f"Error loading techlongue: {e}, trying fallback")

        if self.rooms_csv and os.path.exists(self.rooms_csv):
            try:
                df = pd.read_csv(self.rooms_csv)
                logger.info(f"Loaded rooms from fallback: {self.rooms_csv} ({len(df)} rooms)")
                return df
            except Exception as e:
                logger.error(f"Error loading fallback rooms CSV: {e}")
                raise DataValidationError(f"Failed to load rooms: {e}")
        
        raise FileNotFoundError("Could not find rooms CSV (techlongue.csv or provided fallback)")
    
    def _load_day_order(self) -> pd.DataFrame:
        """Load day order configuration."""
        day_order_paths = [
            'data/day_order.csv',
            os.path.join(self.data_dir, 'day_order.csv'),
        ]
        
        for path in day_order_paths:
            if os.path.exists(path):
                try:
                    df = pd.read_csv(path)
                    logger.info(f"Loaded day order from {path}")
                    return df
                except Exception as e:
                    logger.warning(f"Error loading day_order from {path}: {e}")
        
        logger.warning("day_order.csv not found, using default day pattern")
        return None
    
    def _parse_courses(self, df: pd.DataFrame) -> List[Dict]:
        """Parse courses dataframe into list of course dicts."""
        courses = []
        
        for course_dict in df.to_dict('records'):
            # Normalize column names
            normalized = DataNormalizer.normalize_dict_keys(course_dict)
            
            # Extract course code
            course_code = (
                DataNormalizer.normalize_identifier(normalized.get('course_code', '')) or
                DataNormalizer.normalize_identifier(normalized.get('code', ''))
            )
            
            # Extract teacher name
            teacher_first = DataNormalizer.normalize_identifier(normalized.get('first_name', ''))
            teacher_last = DataNormalizer.normalize_identifier(normalized.get('last_name', ''))
            teacher_id = DataNormalizer.normalize_identifier(normalized.get('teacher_id', ''))
            
            if teacher_first and teacher_last:
                teacher_name = f"{teacher_first} {teacher_last}"
            elif teacher_first:
                teacher_name = teacher_first
            elif teacher_last:
                teacher_name = teacher_last
            else:
                teacher_name = str(teacher_id) if teacher_id else ""
            
            course = {
                'code': course_code,
                'name': DataNormalizer.normalize_identifier(normalized.get('course_name', '')),
                'department': DepartmentParser.parse_department_from_course(course_dict),
                'semester': DepartmentParser.parse_semester(course_dict),
                'credits': DataNormalizer.safe_int(
                    normalized.get('credits', normalized.get('credit', 0)), 0
                ),
                'teacher': teacher_name,
                'teacher_id': teacher_id,
                'sessions_lab': DataNormalizer.safe_int(
                    normalized.get('practical_hours', normalized.get('lab_hours', normalized.get('l', 0))), 0
                ),
                'sessions_theory': DataNormalizer.safe_int(
                    normalized.get('lecture_hours', normalized.get('theory_hours', normalized.get('t', 0))), 0
                ),
                'sessions_tutorial': DataNormalizer.safe_int(
                    normalized.get('tutorial_hours', normalized.get('p', 0)), 0
                ),
                'student_count': DepartmentParser.extract_student_count(course_dict),
                'course_type': DataNormalizer.normalize_identifier(normalized.get('course_type', '')),
                'teaching_dept': DepartmentParser.parse_department_from_course(
                    {**course_dict, 'dept': normalized.get('teaching_dept', normalized.get('course_dept', ''))}
                ),
                'core_lab': False,  # Can be overridden if needed
            }
            
            if course['code'] and course['teacher']:
                courses.append(course)
            else:
                if not course['code']:
                    logger.debug(f"Skipping course with missing code: {course}")
                if not course['teacher']:
                    logger.debug(f"Skipping course with missing teacher: {course_code}")
        
        logger.info(f"Parsed {len(courses)} valid courses from {len(df)} rows")
        return courses
    
    def _parse_rooms(self, df: pd.DataFrame) -> List[Dict]:
        """Parse rooms dataframe into list of room dicts."""
        rooms = []
        
        for room_dict in df.to_dict('records'):
            try:
                room_id = RoomParser.parse_room_id(room_dict.get('room_number', room_dict.get('id')))
                capacity = RoomParser.parse_room_capacity(room_dict.get('capacity', room_dict.get('room_max_cap', 0)))
                block = RoomParser.parse_room_block(room_dict.get('block'))
                room_type = RoomParser.parse_room_type(room_dict.get('room_type', room_dict.get('type', '')))
                
                room = {
                    'id': room_id,
                    'capacity': capacity,
                    'floor': FloorExtractor.extract_floor_from_id(room_id),
                    'block': block,
                    'type': room_type,
                    'equipment': str(room_dict.get('equipment', room_dict.get('tech_level', ''))).strip().lower(),
                }
                
                is_valid, error = RoomValidator.is_valid_room(room)
                if is_valid:
                    rooms.append(room)
                else:
                    logger.warning(f"Skipping invalid room: {error}")
            except Exception as e:
                logger.warning(f"Error parsing room record: {e}")
        
        logger.info(f"Parsed {len(rooms)} valid rooms from {len(df)} rows")
        return rooms
    
    def _extract_teachers(self, courses: List[Dict]) -> set:
        """Extract unique teachers from courses."""
        teachers = DataExtractor.extract_unique_values(courses, 'teacher')
        logger.info(f"Found {len(teachers)} unique teachers")
        return teachers
    
    def _extract_departments(self, courses: List[Dict]) -> set:
        """Extract unique departments from courses."""
        departments = DepartmentGrouper.get_departments(courses)
        logger.info(f"Found {len(departments)} unique departments")
        return departments
    
    def _load_time_slots(self) -> Dict[str, List[str]]:
        """Load time slot configurations for theory and lab."""
        time_slots = {
            'theory': TimeConfiguration.get_default_theory_slots(),
            'lab': TimeConfiguration.get_default_lab_slots(),
        }
        
        logger.info(f"Loaded default time slots: {len(time_slots['theory'])} theory, {len(time_slots['lab'])} lab")
        return time_slots
    
    def _load_days(self) -> List[str]:
        """Load working days configuration."""
        days = TimeConfiguration.get_default_working_days()
        logger.info(f"Using default days: {days}")
        return days
    
    def _load_day_order_mapping(self, day_order_df: Optional[pd.DataFrame]) -> Dict[str, str]:
        """Parse day order configuration into department -> day pattern mapping."""
        day_order = {}
        
        if day_order_df is None:
            logger.info("No day_order.csv, using default M-F for all departments")
            return day_order
        
        try:
            for _, row in day_order_df.iterrows():
                dept = str(row.get('department', row.get('dept', ''))).strip()
                pattern = str(row.get('pattern', row.get('days', ''))).strip()
                if dept and pattern:
                    day_order[dept] = pattern
            
            logger.info(f"Loaded day patterns for {len(day_order)} departments")
        except Exception as e:
            logger.warning(f"Error parsing day_order: {e}")
        
        return day_order
    
    def _build_room_registry(self, rooms: List[Dict]) -> Dict[str, Dict]:
        """Build a room lookup registry by room ID."""
        registry = RoomRegistry.build_registry(rooms, key_field='id')
        logger.info(f"Built room registry with {len(registry)} rooms")
        return registry
    
    def _validate_data_integrity(self, 
                                 courses: List[Dict],
                                 rooms: List[Dict],
                                 teachers: set,
                                 departments: set) -> None:
        """Perform basic data integrity checks."""
        errors = []
        warnings = []
        
        if not courses:
            errors.append("No valid courses loaded")
        
        if not rooms:
            errors.append("No valid rooms loaded")
        
        if not teachers:
            warnings.append("No teachers found in courses")
        
        if not departments:
            warnings.append("No departments found in courses")
        
        course_codes = [c['code'] for c in courses]
        duplicates = DataValidator.check_duplicates(course_codes, "course code")
        if duplicates:
            warnings.append(f"Found duplicate course codes: {duplicates}")
        
        room_ids = [r['id'] for r in rooms]
        dup_rooms = DataValidator.check_duplicates(room_ids, "room ID")
        if dup_rooms:
            warnings.append(f"Found duplicate room IDs: {dup_rooms}")
        
        if errors:
            for err in errors:
                logger.error(f"VALIDATION ERROR: {err}")
            raise DataValidationError(f"Data validation failed: {errors}")
        
        if warnings:
            for warn in warnings:
                logger.warning(f"VALIDATION WARNING: {warn}")
        
        logger.info("Data validation passed")

# class DataLoader:
#     def __init__(self, 
#                  courses_csv: str,
#                  rooms_csv: str = None,
#                  config_dir: str = 'config',
#                  data_dir: str = 'data'):
#         """
#         Initialize the data loader.
        
#         Args:
#             courses_csv: Path to courses CSV file
#             rooms_csv: Path to rooms CSV file (optional, will use techlongue.csv if exists)
#             config_dir: Directory containing config YAML files
#             data_dir: Directory containing data files (day_order.csv, etc.)
#         """
#         self.courses_csv = courses_csv
#         self.rooms_csv = rooms_csv
#         self.config_dir = config_dir
#         self.data_dir = data_dir
        
#         logger.info(f"DataLoader initialized with courses={courses_csv}, rooms={rooms_csv}")
    
#     def load(self) -> Dict[str, Any]:
#         """
#         Load and validate all data.
        
#         Returns:
#             Dictionary with keys:
#             - courses: list of course dicts
#             - rooms: list of room dicts
#             - teachers: set of teacher IDs
#             - departments: set of department names
#             - time_slots: dict with 'theory' and 'lab' arrays
#             - days: list of day names
#             - num_days: int
#             - day_order: dict mapping dept -> day_pattern
#             - room_registry: dict mapping room_id -> room_info
#             - groups: dict (initially empty, populated by scheduler)
#             - horizon: int (total time slots)
#         """
#         logger.info("=" * 80)
#         logger.info("STARTING DATA LOAD")
#         logger.info("=" * 80)

#         courses_df = self._load_courses()
#         rooms_df = self._load_rooms()
#         day_order_df = self._load_day_order()
        
#         logger.info(f"Loaded {len(courses_df)} courses, {len(rooms_df)} rooms")

#         print(courses_df.head())

#         courses = self._parse_courses(courses_df)
#         rooms = self._parse_rooms(rooms_df)
        

#         teachers = self._extract_teachers(courses)
#         departments = self._extract_departments(courses)
        

#         time_slots = self._load_time_slots()
#         days = self._load_days()
#         day_order = self._load_day_order_mapping(day_order_df)


#         room_registry = self._build_room_registry(rooms)
        

#         horizon = len(days) * len(time_slots.get('theory', []))
        

#         self._validate_data_integrity(courses, rooms, teachers, departments)
        
#         data = {
#             'courses': courses,
#             'rooms': rooms,
#             'teachers': teachers,
#             'departments': departments,
#             'time_slots': time_slots,
#             'days': days,
#             'num_days': len(days),
#             'day_order': day_order,
#             'room_registry': room_registry,
#             'groups': {},  
#             'horizon': horizon,
#             'load_timestamp': datetime.now().isoformat(),
#         }
        
#         logger.info(f"Data load complete. Stats: {len(courses)} courses, {len(rooms)} rooms, "
#                    f"{len(teachers)} teachers, {len(departments)} departments, horizon={horizon}")
#         logger.info("=" * 80)
        
#         return data
    
#     def _load_courses(self) -> pd.DataFrame:
#         """load course data from Course Data CSV"""

#         if not os.path.exists(self.courses_csv):
#             raise FileNotFoundError(f'The given file path does not exist: {self.courses_csv}')

#         try:
#             df_course = pd.read_csv(self.courses_csv)
#             logger.info(f'Loaded Course from {self.courses_csv}')
#             return df_course
#         except Exception as e:
#             logger.info(f"We encountered error {e}")
#             raise DataValidationError(f'Failed to load Course {e}')
       
#     def _load_rooms(self) -> pd.DataFrame:
#         if not os.path.exists(self.rooms_csv):
#             raise FileNotFoundError(f'The given file path does not exist: {self.courses_csv}')
        
#         try:
#             df_room = pd.read_csv(self.rooms_csv)
#             logger.info(f"Load room data successfully fro {self.rooms_csv}")
       
#             return df_room
#         except Exception as e:
#             logger.info(f"We encountered error {e}")
#             raise DataValidationError(f'Failed to load Course {e}')

#     def _load_day_order(self) -> pd.DataFrame:
#         day_order_paths = [
#             'data/day_order.csv',
#             os.path.join(self.data_dir, 'day_order.csv')
#         ]

#         for path in day_order_paths:
#             if os.path.exists(path):
#                 try:
#                     df_day_order = pd.read_csv(path)
#                     logger.info(f"The day order file is loadded from {path}")
#                     return df_day_order
#                 except Exception as e:
#                     logger.warning(f"Error loading day_order from {path}: {e}")

#         logger.warning("day_order.csv not found, using default day pattern")
#         return None
    
#     def _parse_courses(self) -> List[Dict]:
#         return
    
#     def _parse_rooms(self) -> List[Dict]:
#         return


def load_data(courses_csv: str,
              rooms_csv: str = None,
              config_dir: str = 'config',
              data_dir: str = 'data') -> Dict[str, Any]:
    """
    Convenience function to load data in one call.
    
    Args:
        courses_csv: Path to courses CSV
        rooms_csv: Path to rooms CSV (optional)
        config_dir: Config directory
        data_dir: Data directory
    
    Returns:
        Clean data dictionary
    """
    loader = DataLoader(courses_csv, rooms_csv, config_dir, data_dir)
    return loader.load()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(name)s - %(levelname)s - %(message)s')
    
    try:
        data = load_data(
            courses_csv='../../data/final_v4.csv',
            rooms_csv='../../data/block_wise/techlongue.csv',
        )
        
        print("\n" + "=" * 80)
        print("DATA LOAD SUCCESSFUL")
        print("=" * 80)
        print(f"Courses: {len(data['courses'])}")
        print(f"Rooms: {len(data['rooms'])}")
        print(f"Teachers: {len(data['teachers'])}")
        print(f"Departments: {len(data['departments'])}")
        print(f"Time slots (theory): {len(data['time_slots']['theory'])}")
        print(f"Time slots (lab): {len(data['time_slots']['lab'])}")
        print(f"Days: {data['days']}")
        print(f"Horizon: {data['horizon']}")
        print("=" * 80)
    
    except Exception as e:
        logger.error(f"Failed to load data: {e}")
        import traceback
        traceback.print_exc()
