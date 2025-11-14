"""Public interface for the data package with eager imports for key helpers."""

from __future__ import annotations

from .course_group_optimizer import CourseGroupOptimizer, optimize_course_groups as optimize_groups_for_dept_semester
from .data_loader import DataLoader, load_data
from .preprocessing import DataPreprocessor, ExtendedDataContainer, preprocess_data

__all__ = [
    "DataLoader",
    "load_data",
    "DataPreprocessor",
    "preprocess_data",
    "ExtendedDataContainer",
    "CourseGroupOptimizer",
    "optimize_groups_for_dept_semester",
]
