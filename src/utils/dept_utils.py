"""
Department Utilities Module

Provides helper functions for department-related operations:
- Department parsing and normalization
- Department-specific configurations (day patterns, shifts)
- Department grouping and analysis
- Semester and batch handling
"""

import pandas as pd
import logging
import re
from typing import Dict, List, Any, Optional, Set, Tuple
from collections import defaultdict
from .data_utils import DataNormalizer, DataValidator

logger = logging.getLogger(__name__)


class DepartmentNormalizer:
    """Utilities for normalizing department names and codes."""
    
    # Common department abbreviations and mappings
    DEPARTMENT_MAPPINGS = {
        'cse': 'Computer Science & Engineering',
        'ece': 'Electronics & Communication Engineering',
        'me': 'Mechanical Engineering',
        'ce': 'Civil Engineering',
        'ee': 'Electrical Engineering',
        'ae': 'Aeronautical Engineering',
        'csd': 'Computer Science & Design',
        'aiml': 'Artificial Intelligence & Machine Learning',
        'aids': 'Artificial Intelligence & Data Science',
        'auto': 'Automobile Engineering',
        'che': 'Chemical Engineering',
        'bme': 'Biomedical Engineering',
        'bio': 'Biotechnology',
    }
    
    @staticmethod
    def normalize_department_name(dept_name: str) -> str:
        """
        Normalize department name (remove special chars, extra spaces).
        
        Args:
            dept_name: Raw department name
            
        Returns:
            Normalized department name
        """
        if not dept_name or not isinstance(dept_name, str):
            return ""
        
        # Strip and remove extra spaces
        normalized = ' '.join(dept_name.strip().split())
        
        return normalized
    
    @staticmethod
    def expand_department_abbreviation(abbrev: str) -> Optional[str]:
        """
        Expand department abbreviation to full name.
        
        Args:
            abbrev: Department abbreviation
            
        Returns:
            Full department name or None
        """
        if not abbrev or not isinstance(abbrev, str):
            return None
        
        abbrev_lower = abbrev.strip().lower()
        

        if abbrev_lower in DepartmentNormalizer.DEPARTMENT_MAPPINGS:
            return DepartmentNormalizer.DEPARTMENT_MAPPINGS[abbrev_lower]
        
        for key, value in DepartmentNormalizer.DEPARTMENT_MAPPINGS.items():
            if key in abbrev_lower or abbrev_lower in key:
                return value

        return DepartmentNormalizer.normalize_department_name(abbrev)
    
    @staticmethod
    def get_department_code(dept_name: str) -> str:
        """
        Get short code for department (e.g., "CSE" for "Computer Science & Engineering").
        
        Args:
            dept_name: Full department name
            
        Returns:
            Short code
        """
        if not dept_name or not isinstance(dept_name, str):
            return "UNKNOWN"
        
        dept_lower = dept_name.strip().lower()
        

        for code, full_name in DepartmentNormalizer.DEPARTMENT_MAPPINGS.items():
            if full_name.lower() == dept_lower:
                return code.upper()
        
        parts = dept_name.split()
        code = ''.join([p[0].upper() for p in parts if p])
        return code if code else "UNKNOWN"


class DepartmentParser:
    """Utilities for parsing department information from records."""
    
    @staticmethod
    def parse_department_from_course(course: Dict) -> str:
        """
        Extract and normalize department from course record.
        
        Args:
            course: Course dictionary
            
        Returns:
            Normalized department name
        """
        normalized = DataNormalizer.normalize_dict_keys(course)
        
        # Try different possible department column names in order of priority
        dept_names = [
            'teaching_dept',          # Primary: teaching department
            'course_dept',            # Secondary: course department
            'student_dept',           # Tertiary: student department
            'dept',                   # Fallback: generic dept
            'department',             # Generic department
        ]
        
        for field in dept_names:
            if field in normalized:
                value = normalized[field]
                if value and not pd.isna(value):
                    normalized_dept = DepartmentNormalizer.normalize_department_name(str(value))
                    if normalized_dept:
                        return normalized_dept
        
        return ""
    
    @staticmethod
    def parse_semester(record: Dict) -> Optional[int]:
        """
        Extract and validate semester from record.
        
        Args:
            record: Dictionary record
            
        Returns:
            Semester number (1-8) or None
        """
        normalized = DataNormalizer.normalize_dict_keys(record)
        
        sem_fields = ['sem', 'semester', 'seme']
        for field in sem_fields:
            if field in normalized:
                value = normalized[field]
                if value and not pd.isna(value):
                    try:
                        sem = int(value)
                        if 1 <= sem <= 8:
                            return sem
                    except (ValueError, TypeError):
                        pass
        
        return None
    
    @staticmethod
    def extract_student_count(record: Dict) -> int:
        """
        Extract student count from record.
        
        Args:
            record: Dictionary record
            
        Returns:
            Student count
        """
        normalized = DataNormalizer.normalize_dict_keys(record)
        
        count_fields = ['student_count', 'students', 'count', 'strength']
        for field in count_fields:
            if field in normalized:
                value = normalized[field]
                if value and not pd.isna(value):
                    return DataNormalizer.safe_int(value, 0)
        
        return 0


class DepartmentGrouper:
    """Utilities for grouping and analyzing departments."""
    
    @staticmethod
    def group_by_department(records: List[Dict]) -> Dict[str, List[Dict]]:
        """
        Group records by department.
        
        Args:
            records: List of records
            
        Returns:
            Dictionary mapping department names to lists of records
        """
        groups = defaultdict(list)
        for record in records:
            dept = DepartmentParser.parse_department_from_course(record)
            if dept:
                groups[dept].append(record)
        
        logger.info(f"Grouped {len(records)} records into {len(groups)} departments")
        return dict(groups)
    
    @staticmethod
    def group_by_semester(records: List[Dict]) -> Dict[int, List[Dict]]:
        """
        Group records by semester.
        
        Args:
            records: List of records
            
        Returns:
            Dictionary mapping semester numbers to lists of records
        """
        groups = defaultdict(list)
        for record in records:
            sem = DepartmentParser.parse_semester(record)
            if sem is not None:
                groups[sem].append(record)
        
        logger.info(f"Grouped {len(records)} records into {len(groups)} semesters")
        return dict(groups)
    
    @staticmethod
    def group_by_dept_semester(records: List[Dict]) -> Dict[str, Dict[int, List[Dict]]]:
        """
        Group records by (department, semester).
        
        Args:
            records: List of records
            
        Returns:
            Dictionary mapping dept names to {semester -> list of records}
        """
        dept_groups = DepartmentGrouper.group_by_department(records)
        
        result = {}
        for dept, dept_records in dept_groups.items():
            result[dept] = DepartmentGrouper.group_by_semester(dept_records)
        
        logger.info(f"Grouped into {len(result)} departments with semesters")
        return result
    
    @staticmethod
    def get_departments(records: List[Dict]) -> Set[str]:
        """
        Get unique departments.
        
        Args:
            records: List of records
            
        Returns:
            Set of department names
        """
        depts = set()
        for record in records:
            dept = DepartmentParser.parse_department_from_course(record)
            if dept:
                depts.add(dept)
        
        logger.info(f"Found {len(depts)} unique departments")
        return depts
    
    @staticmethod
    def get_semesters(records: List[Dict]) -> Set[int]:
        """
        Get unique semesters.
        
        Args:
            records: List of records
            
        Returns:
            Set of semester numbers
        """
        sems = set()
        for record in records:
            sem = DepartmentParser.parse_semester(record)
            if sem is not None:
                sems.add(sem)
        
        logger.info(f"Found {len(sems)} unique semesters: {sorted(sems)}")
        return sems


class DepartmentConfiguration:
    """Utilities for managing department-specific configurations."""
    
    @staticmethod
    def get_department_day_pattern(dept_name: str, 
                                   day_patterns: Optional[Dict[str, str]] = None) -> str:
        """
        Get working day pattern for department.
        
        Args:
            dept_name: Department name
            day_patterns: Optional dict mapping dept -> pattern
            
        Returns:
            Day pattern (e.g., "M-F", "Tue-Sat")
        """
        if day_patterns and dept_name in day_patterns:
            return day_patterns[dept_name]
        
        # Default Monday-Friday
        return "M-F"
    
    @staticmethod
    def get_department_shift_configuration(dept_name: str) -> Optional[Dict[str, Any]]:
        """
        Get shift configuration for department.
        
        Args:
            dept_name: Department name
            
        Returns:
            Dictionary with shift info or None
        """
        # Default: no shifts
        return None
    
    @staticmethod
    def get_lunch_break_slot(dept_name: str, semester: Optional[int] = None) -> Optional[int]:
        """
        Get lunch break time slot for department/semester.
        
        Args:
            dept_name: Department name
            semester: Semester number (optional)
            
        Returns:
            Slot index for lunch break or None
        """
        # Default: around 12:00-13:00 (slot 4 in standard 11-slot config)
        return 4
    
    @staticmethod
    def is_flexible_lunch(dept_name: str, semester: Optional[int] = None) -> bool:
        """
        Check if department has flexible lunch timing.
        
        Args:
            dept_name: Department name
            semester: Semester number (optional)
            
        Returns:
            True if lunch timing is flexible
        """
        # Default: not flexible
        return False
    
    @staticmethod
    def get_5pm_constraint(dept_name: str, semester: Optional[int] = None) -> Optional[Dict]:
        """
        Get 5 PM end-of-day constraint for department/semester.
        
        Args:
            dept_name: Department name
            semester: Semester number (optional)
            
        Returns:
            Constraint dict or None
        """
        # Default: no 5 PM constraint
        return None


class DepartmentAnalyzer:
    """Utilities for analyzing department statistics."""
    
    @staticmethod
    def get_department_statistics(records: List[Dict], dept_name: str) -> Dict[str, Any]:
        """
        Get statistics for a department.
        
        Args:
            records: List of course records
            dept_name: Department name
            
        Returns:
            Dictionary with statistics
        """
        dept_records = [r for r in records 
                       if DepartmentParser.parse_department_from_course(r) == dept_name]
        
        if not dept_records:
            return {'count': 0}
        
        semesters = DepartmentParser.parse_semester(dept_records[0])
        total_students = sum(DepartmentParser.extract_student_count(r) for r in dept_records)
        
        return {
            'count': len(dept_records),
            'total_students': total_students,
            'avg_students': total_students / len(dept_records) if dept_records else 0,
            'semesters': sorted(set(DepartmentParser.parse_semester(r) for r in dept_records 
                                   if DepartmentParser.parse_semester(r))),
        }
    
    @staticmethod
    def get_all_department_statistics(records: List[Dict]) -> Dict[str, Dict]:
        """
        Get statistics for all departments.
        
        Args:
            records: List of course records
            
        Returns:
            Dictionary mapping dept names to statistics
        """
        depts = DepartmentGrouper.get_departments(records)
        
        stats = {}
        for dept in depts:
            stats[dept] = DepartmentAnalyzer.get_department_statistics(records, dept)
        
        logger.info(f"Generated statistics for {len(stats)} departments")
        return stats
    
    @staticmethod
    def get_student_load_by_semester(records: List[Dict]) -> Dict[int, int]:
        """
        Calculate total student load by semester.
        
        Args:
            records: List of course records
            
        Returns:
            Dictionary mapping semester to total student count
        """
        loads = defaultdict(int)
        for record in records:
            sem = DepartmentParser.parse_semester(record)
            if sem is not None:
                count = DepartmentParser.extract_student_count(record)
                loads[sem] += count
        
        return dict(sorted(loads.items()))
    
    @staticmethod
    def get_course_distribution_by_dept(records: List[Dict]) -> Dict[str, int]:
        """
        Get number of courses per department.
        
        Args:
            records: List of course records
            
        Returns:
            Dictionary mapping dept names to course counts
        """
        distribution = defaultdict(int)
        for record in records:
            dept = DepartmentParser.parse_department_from_course(record)
            if dept:
                distribution[dept] += 1
        
        return dict(sorted(distribution.items(), key=lambda x: x[1], reverse=True))


class DepartmentValidator:
    """Utilities for validating department data."""
    
    @staticmethod
    def validate_department_config(dept_name: str, config: Dict) -> Tuple[bool, List[str]]:
        """
        Validate department configuration.
        
        Args:
            dept_name: Department name
            config: Configuration dictionary
            
        Returns:
            Tuple of (is_valid, list of errors)
        """
        errors = []
        
        if not dept_name:
            errors.append("Department name cannot be empty")
        
        # Check for required configuration keys
        required_keys = ['name']
        for key in required_keys:
            if key not in config:
                errors.append(f"Missing required config key: {key}")
        
        return len(errors) == 0, errors
    
    @staticmethod
    def validate_semester(sem: int) -> Tuple[bool, str]:
        """
        Validate semester number.
        
        Args:
            sem: Semester number
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not isinstance(sem, int) or sem < 1 or sem > 8:
            return False, f"Semester {sem} out of valid range [1-8]"
        return True, ""
    
    @staticmethod
    def validate_student_count(count: int) -> Tuple[bool, str]:
        """
        Validate student count.
        
        Args:
            count: Student count
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if count < 0 or count > 10000:
            return False, f"Student count {count} out of reasonable range [0, 10000]"
        return True, ""
    
    @staticmethod
    def check_department_integrity(records: List[Dict], dept_name: str) -> Dict[str, Any]:
        """
        Check integrity of department data.
        
        Args:
            records: List of records
            dept_name: Department to check
            
        Returns:
            Dictionary with integrity report
        """
        dept_records = [r for r in records 
                       if DepartmentParser.parse_department_from_course(r) == dept_name]
        
        report = {
            'department': dept_name,
            'record_count': len(dept_records),
            'missing_semesters': [],
            'warnings': [],
        }
        
        if not dept_records:
            report['warnings'].append(f"No records found for department: {dept_name}")
            return report
        
        # Check for all semesters
        found_semesters = set(DepartmentParser.parse_semester(r) for r in dept_records 
                             if DepartmentParser.parse_semester(r))
        expected_semesters = set(range(1, 9))
        report['missing_semesters'] = sorted(expected_semesters - found_semesters)
        
        # Check student counts
        for record in dept_records:
            count = DepartmentParser.extract_student_count(record)
            if count == 0:
                report['warnings'].append(f"Zero student count in record: {record.get('code', 'unknown')}")
        
        return report
