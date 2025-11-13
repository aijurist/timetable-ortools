"""
Data Package

Contains all data loading, preprocessing, and optimization modules:
- data_loader: Load and validate raw data from CSV files
- preprocessing: Extend data with intermediate structures (groups, requirements)
- course_group_optimizer: Optimize group distribution using OR-Tools
"""

from .data_loader import DataLoader, load_data
from .preprocessing import DataPreprocessor, preprocess_data, ExtendedDataContainer
from .course_group_optimizer import CourseGroupOptimizer, optimize_groups_for_dept_semester

__all__ = [
    'DataLoader',
    'load_data',
    'DataPreprocessor',
    'preprocess_data',
    'ExtendedDataContainer',
    'CourseGroupOptimizer',
    'optimize_groups_for_dept_semester',
]
