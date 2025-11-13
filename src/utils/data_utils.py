"""
Data Utilities Module

Provides helper functions for data loading, normalization, validation, and transformation.
- Normalizing column names and data types
- Validating data integrity
- Extracting metadata from records
- Formatting and cleaning data
"""

import pandas as pd
import logging
from typing import Dict, List, Any, Optional, Set, Tuple
from collections import defaultdict

logger = logging.getLogger(__name__)


class DataNormalizer:
    """Utilities for normalizing and standardizing data formats."""
    
    @staticmethod
    def normalize_columns(df: pd.DataFrame) -> Dict[str, str]:
        """
        Create a case-insensitive mapping of columns.
        
        Args:
            df: Input DataFrame
            
        Returns:
            Dictionary mapping lowercase column names to original column names
        """
        return {col.lower(): col for col in df.columns}
    
    @staticmethod
    def normalize_dict_keys(record: Dict) -> Dict[str, Any]:
        """
        Normalize all dictionary keys to lowercase.
        
        Args:
            record: Input dictionary
            
        Returns:
            Dictionary with lowercase keys and original values
        """
        return {k.lower(): v for k, v in record.items()}
    
    @staticmethod
    def normalize_string(value: Any) -> str:
        """
        Convert any value to normalized string (lowercase, stripped).
        
        Args:
            value: Input value
            
        Returns:
            Normalized string
        """
        if pd.isna(value):
            return ""
        return str(value).strip().lower()
    
    @staticmethod
    def normalize_identifier(value: Any) -> str:
        """
        Normalize identifier fields (codes, IDs, names).
        Keeps original case but removes leading/trailing whitespace.
        
        Args:
            value: Input value
            
        Returns:
            Normalized identifier
        """
        if pd.isna(value):
            return ""
        return str(value).strip()
    
    @staticmethod
    def safe_int(value: Any, default: int = 0) -> int:
        """
        Safely convert value to integer with default fallback.
        
        Args:
            value: Input value
            default: Default value if conversion fails
            
        Returns:
            Integer value or default
        """
        if pd.isna(value) or value == '':
            return default
        try:
            return int(value)
        except (ValueError, TypeError):
            logger.warning(f"Could not convert '{value}' to int, using default {default}")
            return default
    
    @staticmethod
    def safe_float(value: Any, default: float = 0.0) -> float:
        """
        Safely convert value to float with default fallback.
        
        Args:
            value: Input value
            default: Default value if conversion fails
            
        Returns:
            Float value or default
        """
        if pd.isna(value) or value == '':
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            logger.warning(f"Could not convert '{value}' to float, using default {default}")
            return default


class DataValidator:
    """Utilities for validating data integrity and consistency."""
    
    @staticmethod
    def validate_required_fields(record: Dict, required_fields: List[str], 
                                  record_name: str = "record") -> Tuple[bool, List[str]]:
        """
        Validate that all required fields are present and non-empty.
        
        Args:
            record: Dictionary to validate
            required_fields: List of required field names
            record_name: Name for logging
            
        Returns:
            Tuple of (is_valid, list_of_missing_fields)
        """
        missing = []
        for field in required_fields:
            value = record.get(field)
            if pd.isna(value) or (isinstance(value, str) and not value.strip()):
                missing.append(field)
        
        if missing:
            logger.warning(f"{record_name} missing required fields: {missing}")
        
        return len(missing) == 0, missing
    
    @staticmethod
    def check_duplicates(items: List[Any], item_type: str = "item") -> List[Any]:
        """
        Find duplicate items in a list.
        
        Args:
            items: List to check
            item_type: Name of item type for logging
            
        Returns:
            List of duplicate items
        """
        seen = set()
        duplicates = []
        for item in items:
            if item in seen and item not in duplicates:
                duplicates.append(item)
            seen.add(item)
        
        if duplicates:
            logger.warning(f"Found {len(duplicates)} duplicate {item_type}(s): {duplicates}")
        
        return duplicates
    
    @staticmethod
    def validate_numeric_range(value: Any, min_val: float, max_val: float,
                               field_name: str = "value") -> Tuple[bool, str]:
        """
        Validate that a value is within a numeric range.
        
        Args:
            value: Value to check
            min_val: Minimum allowed value (inclusive)
            max_val: Maximum allowed value (inclusive)
            field_name: Name of field for logging
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            num = float(value)
            if num < min_val or num > max_val:
                msg = f"{field_name} {num} out of range [{min_val}, {max_val}]"
                logger.warning(msg)
                return False, msg
            return True, ""
        except (ValueError, TypeError):
            msg = f"{field_name} cannot be converted to number"
            logger.warning(msg)
            return False, msg
    
    @staticmethod
    def validate_enum(value: Any, allowed_values: Set[str], 
                      field_name: str = "field") -> Tuple[bool, str]:
        """
        Validate that a value is in an allowed set.
        
        Args:
            value: Value to check
            allowed_values: Set of allowed values
            field_name: Name of field for logging
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        str_val = str(value).strip().lower()
        if str_val not in {v.lower() for v in allowed_values}:
            msg = f"{field_name} '{value}' not in allowed values: {allowed_values}"
            logger.warning(msg)
            return False, msg
        return True, ""


class DataExtractor:
    """Utilities for extracting metadata and summarizing data."""
    
    @staticmethod
    def extract_unique_values(records: List[Dict], field_name: str) -> Set[str]:
        """
        Extract unique values of a field across records.
        
        Args:
            records: List of dictionaries
            field_name: Field to extract
            
        Returns:
            Set of unique values
        """
        values = set()
        for record in records:
            val = record.get(field_name)
            if val and (not isinstance(val, float) or not pd.isna(val)):
                values.add(str(val).strip())
        return values
    
    @staticmethod
    def group_by_field(records: List[Dict], field_name: str) -> Dict[str, List[Dict]]:
        """
        Group records by a field value.
        
        Args:
            records: List of dictionaries
            field_name: Field to group by
            
        Returns:
            Dictionary mapping field values to lists of records
        """
        groups = defaultdict(list)
        for record in records:
            key = record.get(field_name)
            if key:
                groups[key].append(record)
        return dict(groups)
    
    @staticmethod
    def count_by_field(records: List[Dict], field_name: str) -> Dict[str, int]:
        """
        Count occurrences of each value in a field.
        
        Args:
            records: List of dictionaries
            field_name: Field to count
            
        Returns:
            Dictionary mapping field values to counts
        """
        counts = defaultdict(int)
        for record in records:
            key = record.get(field_name)
            if key:
                counts[key] += 1
        return dict(counts)
    
    @staticmethod
    def create_lookup_dict(records: List[Dict], key_field: str, 
                           value_field: Optional[str] = None) -> Dict[str, Any]:
        """
        Create a lookup dictionary from records.
        
        Args:
            records: List of dictionaries
            key_field: Field to use as key
            value_field: Field to use as value (if None, entire record is used)
            
        Returns:
            Dictionary mapping key values to value fields (or full records)
        """
        lookup = {}
        for record in records:
            key = record.get(key_field)
            if key:
                if value_field:
                    lookup[key] = record.get(value_field)
                else:
                    lookup[key] = record
        return lookup
    
    @staticmethod
    def get_statistics(records: List[Dict], numeric_field: str) -> Dict[str, float]:
        """
        Calculate statistics for a numeric field across records.
        
        Args:
            records: List of dictionaries
            numeric_field: Numeric field to analyze
            
        Returns:
            Dictionary with 'min', 'max', 'avg', 'count' statistics
        """
        values = []
        for record in records:
            val = record.get(numeric_field)
            if val is not None and not pd.isna(val):
                try:
                    values.append(float(val))
                except (ValueError, TypeError):
                    pass
        
        if not values:
            return {'min': 0, 'max': 0, 'avg': 0, 'count': 0}
        
        return {
            'min': min(values),
            'max': max(values),
            'avg': sum(values) / len(values),
            'count': len(values),
        }


class DataTransformer:
    """Utilities for transforming and formatting data."""
    
    @staticmethod
    def flatten_dict(nested: Dict, parent_key: str = '', sep: str = '_') -> Dict:
        """
        Flatten a nested dictionary.
        
        Args:
            nested: Nested dictionary
            parent_key: Prefix for keys
            sep: Separator for nested keys
            
        Returns:
            Flattened dictionary
        """
        items = []
        for k, v in nested.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.extend(DataTransformer.flatten_dict(v, new_key, sep).items())
            elif isinstance(v, list):
                for i, item in enumerate(v):
                    if isinstance(item, dict):
                        items.extend(DataTransformer.flatten_dict(item, f"{new_key}[{i}]", sep).items())
                    else:
                        items.append((f"{new_key}[{i}]", item))
            else:
                items.append((new_key, v))
        return dict(items)
    
    @staticmethod
    def merge_records(records: List[Dict], merge_field: str) -> Dict[str, Dict]:
        """
        Merge records by a field (last value wins on duplicates).
        
        Args:
            records: List of records to merge
            merge_field: Field to use as merge key
            
        Returns:
            Dictionary mapping merge_field values to merged records
        """
        merged = {}
        for record in records:
            key = record.get(merge_field)
            if key:
                if key in merged:
                    merged[key].update(record)
                else:
                    merged[key] = dict(record)
        return merged
    
    @staticmethod
    def filter_records(records: List[Dict], filter_func) -> List[Dict]:
        """
        Filter records based on a condition function.
        
        Args:
            records: List of records
            filter_func: Function that takes a record and returns bool
            
        Returns:
            Filtered list of records
        """
        return [r for r in records if filter_func(r)]
    
    @staticmethod
    def map_records(records: List[Dict], map_func) -> List[Dict]:
        """
        Transform records using a mapping function.
        
        Args:
            records: List of records
            map_func: Function that takes a record and returns transformed record
            
        Returns:
            List of transformed records
        """
        return [map_func(r) for r in records]


class DataSummary:
    """Utilities for summarizing and reporting on data."""
    
    @staticmethod
    def generate_summary(data: Dict[str, Any]) -> str:
        """
        Generate a human-readable summary of loaded data.
        
        Args:
            data: Data dictionary from DataLoader
            
        Returns:
            Formatted summary string
        """
        lines = []
        lines.append("=" * 80)
        lines.append("DATA SUMMARY")
        lines.append("=" * 80)
        
        if 'courses' in data:
            lines.append(f"Courses: {len(data['courses'])}")
        if 'rooms' in data:
            lines.append(f"Rooms: {len(data['rooms'])}")
        if 'teachers' in data:
            lines.append(f"Teachers: {len(data['teachers'])}")
        if 'departments' in data:
            lines.append(f"Departments: {len(data['departments'])}")
        if 'time_slots' in data:
            ts = data['time_slots']
            if 'theory' in ts:
                lines.append(f"Theory Time Slots: {len(ts['theory'])}")
            if 'lab' in ts:
                lines.append(f"Lab Time Slots: {len(ts['lab'])}")
        if 'days' in data:
            lines.append(f"Working Days: {', '.join(data['days'])}")
        if 'horizon' in data:
            lines.append(f"Total Horizon (slots × days): {data['horizon']}")
        
        lines.append("=" * 80)
        return "\n".join(lines)
    
    @staticmethod
    def validate_data_completeness(data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Check completeness of loaded data.
        
        Args:
            data: Data dictionary from DataLoader
            
        Returns:
            Dictionary with completeness report
        """
        report = {
            'has_courses': bool(data.get('courses')),
            'has_rooms': bool(data.get('rooms')),
            'has_teachers': bool(data.get('teachers')),
            'has_departments': bool(data.get('departments')),
            'has_time_slots': bool(data.get('time_slots')),
            'has_days': bool(data.get('days')),
            'is_complete': False,
        }
        
        report['is_complete'] = all([
            report['has_courses'],
            report['has_rooms'],
            report['has_teachers'],
            report['has_departments'],
            report['has_time_slots'],
            report['has_days'],
        ])
        
        return report
