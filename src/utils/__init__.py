"""
Utils Package

Comprehensive utility modules for timetable scheduling:
- data_utils: Data normalization, validation, extraction, transformation
- room_utils: Room parsing, registry, matching, and analysis
- time_utils: Time parsing, slot calculations, schedule analysis
- dept_utils: Department grouping, configuration, and analysis
"""

# Import all utility classes and functions for easy access

# Data utilities
from .data_utils import (
    DataNormalizer,
    DataValidator,
    DataExtractor,
    DataTransformer,
    DataSummary,
)

# Room utilities
from .room_utils import (
    RoomParser,
    RoomValidator,
    FloorExtractor,
    CapacityAnalyzer,
    RoomRegistry,
    RoomMatcher,
)

# Time utilities
from .time_utils import (
    TimeParser,
    DayNormalizer,
    TimeSlotCalculator,
    TimeRangeChecker,
    ScheduleAnalyzer,
    TimeConfiguration,
)

# Department utilities
from .dept_utils import (
    DepartmentNormalizer,
    DepartmentParser,
    DepartmentGrouper,
    DepartmentConfiguration,
    DepartmentAnalyzer,
    DepartmentValidator,
)


__all__ = [

    'DataNormalizer',
    'DataValidator',
    'DataExtractor',
    'DataTransformer',
    'DataSummary',

    'RoomParser',
    'RoomValidator',
    'FloorExtractor',
    'CapacityAnalyzer',
    'RoomRegistry',
    'RoomMatcher',
 
    'TimeParser',
    'DayNormalizer',
    'TimeSlotCalculator',
    'TimeRangeChecker',
    'ScheduleAnalyzer',
    'TimeConfiguration',

    'DepartmentNormalizer',
    'DepartmentParser',
    'DepartmentGrouper',
    'DepartmentConfiguration',
    'DepartmentAnalyzer',
    'DepartmentValidator',
]
