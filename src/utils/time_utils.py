"""
Time Utilities Module

Provides helper functions for time and scheduling operations:
- Time parsing and formatting
- Time slot calculations
- Day name normalization
- Schedule conflict detection
- Time range overlap checking
"""

import logging
import re
from typing import Dict, List, Any, Optional, Tuple, Set
from datetime import datetime, time, timedelta
from collections import defaultdict

logger = logging.getLogger(__name__)


class TimeParser:
    """Utilities for parsing time strings and formats."""
    
    @staticmethod
    def parse_time(time_str: str, format: str = '%H:%M') -> Optional[time]:
        """
        Parse time string to time object.
        
        Args:
            time_str: Time string (e.g., "14:30", "2:30 PM")
            format: Expected time format
            
        Returns:
            time object or None if parsing fails
        """
        if not time_str or not isinstance(time_str, str):
            return None
        
        time_str = time_str.strip()
        
        # Try different common formats
        formats = [
            '%H:%M',
            '%H:%M:%S',
            '%I:%M %p',
            '%I:%M%p',
            '%I:%M:%S %p',
        ]
        
        for fmt in formats:
            try:
                dt = datetime.strptime(time_str, fmt)
                return dt.time()
            except ValueError:
                continue
        
        logger.warning(f"Could not parse time string: {time_str}")
        return None
    
    @staticmethod
    def parse_time_range(range_str: str, separator: str = '-') -> Optional[Tuple[time, time]]:
        """
        Parse time range string (e.g., "9:00-10:00", "8:00 AM - 9:00 AM").
        
        Args:
            range_str: Time range string
            separator: Separator between start and end time
            
        Returns:
            Tuple of (start_time, end_time) or None if parsing fails
        """
        if not range_str or separator not in range_str:
            return None
        
        parts = range_str.split(separator)
        if len(parts) != 2:
            return None
        
        start_time = TimeParser.parse_time(parts[0].strip())
        end_time = TimeParser.parse_time(parts[1].strip())
        
        if start_time and end_time:
            return (start_time, end_time)
        
        return None
    
    @staticmethod
    def parse_time_to_minutes(time_str: str) -> Optional[int]:
        """
        Parse time string to minutes since midnight.
        
        Args:
            time_str: Time string (e.g., "14:30")
            
        Returns:
            Minutes since midnight or None
        """
        parsed = TimeParser.parse_time(time_str)
        if parsed:
            return parsed.hour * 60 + parsed.minute
        return None
    
    @staticmethod
    def time_to_string(t: time, format: str = '%H:%M') -> str:
        """
        Convert time object to formatted string.
        
        Args:
            t: time object
            format: Output format
            
        Returns:
            Formatted time string
        """
        if not isinstance(t, time):
            return ""
        return datetime.combine(datetime.today(), t).strftime(format)


class DayNormalizer:
    """Utilities for day name normalization and operations."""
    
    VALID_DAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 
                  'saturday', 'sunday']
    
    DAY_ABBREVIATIONS = {
        'mon': 'monday',
        'mon.': 'monday',
        'tue': 'tuesday',
        'tues': 'tuesday',
        'tue.': 'tuesday',
        'wed': 'wednesday',
        'weds': 'wednesday',
        'wed.': 'wednesday',
        'thu': 'thursday',
        'thur': 'thursday',
        'thurs': 'thursday',
        'thu.': 'thursday',
        'fri': 'friday',
        'fri.': 'friday',
        'sat': 'saturday',
        'sat.': 'saturday',
        'sun': 'sunday',
        'sun.': 'sunday',
    }
    
    DAY_NUMBERS = {
        'monday': 0,
        'tuesday': 1,
        'wednesday': 2,
        'thursday': 3,
        'friday': 4,
        'saturday': 5,
        'sunday': 6,
    }
    
    @staticmethod
    def normalize_day_name(day: str) -> Optional[str]:
        """
        Normalize day name to lowercase full name.
        
        Args:
            day: Day name (e.g., "Monday", "Mon", "MON")
            
        Returns:
            Normalized day name or None
        """
        if not day or not isinstance(day, str):
            return None
        
        day_lower = day.strip().lower()
        sanitized = DayNormalizer._sanitize_token(day_lower)
        
        # Check if already normalized
        if day_lower in DayNormalizer.VALID_DAYS:
            return day_lower
        
        # Check abbreviations
        if day_lower in DayNormalizer.DAY_ABBREVIATIONS:
            return DayNormalizer.DAY_ABBREVIATIONS[day_lower]

        if sanitized in DayNormalizer.VALID_DAYS:
            return sanitized

        if sanitized in DayNormalizer.DAY_ABBREVIATIONS:
            return DayNormalizer.DAY_ABBREVIATIONS[sanitized]

        for valid_day in DayNormalizer.VALID_DAYS:
            if sanitized and valid_day.startswith(sanitized):
                return valid_day
        
        logger.warning(f"Unknown day name: {day}")
        return None

    @staticmethod
    def _sanitize_token(day: str) -> str:
        """Remove punctuation/whitespace characters for more forgiving matching."""

        return re.sub(r"[^a-z]", "", day)
    
    @staticmethod
    def get_day_number(day: str) -> Optional[int]:
        """
        Get day number (0 = Monday, 6 = Sunday).
        
        Args:
            day: Day name
            
        Returns:
            Day number or None
        """
        normalized = DayNormalizer.normalize_day_name(day)
        if normalized:
            return DayNormalizer.DAY_NUMBERS.get(normalized)
        return None
    
    @staticmethod
    def get_day_name(day_num: int) -> Optional[str]:
        """
        Get day name from day number.
        
        Args:
            day_num: Day number (0-6)
            
        Returns:
            Day name or None
        """
        for day, num in DayNormalizer.DAY_NUMBERS.items():
            if num == day_num:
                return day
        return None
    
    @staticmethod
    def is_weekend(day: str) -> bool:
        """
        Check if day is a weekend.
        
        Args:
            day: Day name
            
        Returns:
            True if weekend
        """
        day_num = DayNormalizer.get_day_number(day)
        return day_num in (5, 6) if day_num is not None else False
    
    @staticmethod
    def is_weekday(day: str) -> bool:
        """
        Check if day is a weekday.
        
        Args:
            day: Day name
            
        Returns:
            True if weekday
        """
        return not DayNormalizer.is_weekend(day)


class TimeSlotCalculator:
    """Utilities for time slot calculations and indexing."""
    
    @staticmethod
    def calculate_slot_index(day_idx: int, slot_idx: int, num_slots_per_day: int) -> int:
        """
        Calculate global slot index from day and time slot.
        
        Args:
            day_idx: Day index (0-based)
            slot_idx: Slot index within day (0-based)
            num_slots_per_day: Total slots per day
            
        Returns:
            Global slot index
        """
        return day_idx * num_slots_per_day + slot_idx
    
    @staticmethod
    def reverse_slot_index(global_slot: int, num_slots_per_day: int) -> Tuple[int, int]:
        """
        Convert global slot index back to day and slot indices.
        
        Args:
            global_slot: Global slot index
            num_slots_per_day: Total slots per day
            
        Returns:
            Tuple of (day_idx, slot_idx)
        """
        day_idx = global_slot // num_slots_per_day
        slot_idx = global_slot % num_slots_per_day
        return day_idx, slot_idx
    
    @staticmethod
    def get_adjacent_slots(slot_idx: int, num_slots: int = 11) -> List[int]:
        """
        Get adjacent (previous and next) slots.
        
        Args:
            slot_idx: Current slot index
            num_slots: Total slots per day
            
        Returns:
            List of adjacent slot indices
        """
        adjacent = []
        if slot_idx > 0:
            adjacent.append(slot_idx - 1)
        if slot_idx < num_slots - 1:
            adjacent.append(slot_idx + 1)
        return adjacent
    
    @staticmethod
    def calculate_duration_in_slots(start_time: time, end_time: time, 
                                    slot_duration: int = 60) -> int:
        """
        Calculate number of slots for a time duration.
        
        Args:
            start_time: Start time
            end_time: End time
            slot_duration: Duration of each slot in minutes
            
        Returns:
            Number of slots needed
        """
        start_minutes = start_time.hour * 60 + start_time.minute
        end_minutes = end_time.hour * 60 + end_time.minute
        duration = end_minutes - start_minutes
        
        if duration <= 0:
            return 0
        
        return max(1, (duration + slot_duration - 1) // slot_duration)
    
    @staticmethod
    def get_slots_for_duration(num_slots: int, required_duration: int) -> Optional[List[int]]:
        """
        Get consecutive slot indices for required duration.
        
        Args:
            num_slots: Total available slots
            required_duration: Number of consecutive slots needed
            
        Returns:
            List of valid starting slot indices, or None if impossible
        """
        if required_duration > num_slots:
            return None
        
        return list(range(num_slots - required_duration + 1))


class TimeRangeChecker:
    """Utilities for checking time overlaps and conflicts."""
    
    @staticmethod
    def times_overlap(range1: Tuple[time, time], range2: Tuple[time, time]) -> bool:
        """
        Check if two time ranges overlap.
        
        Args:
            range1: First time range (start, end)
            range2: Second time range (start, end)
            
        Returns:
            True if ranges overlap
        """
        start1, end1 = range1
        start2, end2 = range2
        
        # Overlaps if one starts before the other ends
        return not (end1 <= start2 or end2 <= start1)
    
    @staticmethod
    def slots_overlap(slot1_idx: int, slot1_duration: int,
                      slot2_idx: int, slot2_duration: int) -> bool:
        """
        Check if two slot ranges overlap (same day).
        
        Args:
            slot1_idx: First slot index
            slot1_duration: First slot duration (number of consecutive slots)
            slot2_idx: Second slot index
            slot2_duration: Second slot duration
            
        Returns:
            True if slots overlap
        """
        slot1_range = (slot1_idx, slot1_idx + slot1_duration)
        slot2_range = (slot2_idx, slot2_idx + slot2_duration)
        
        return not (slot1_range[1] <= slot2_range[0] or slot2_range[1] <= slot1_range[0])
    
    @staticmethod
    def find_gaps_in_schedule(scheduled_slots: List[Tuple[int, int]], 
                              total_slots: int) -> List[Tuple[int, int]]:
        """
        Find unscheduled gaps in schedule.
        
        Args:
            scheduled_slots: List of (start, duration) tuples
            total_slots: Total available slots
            
        Returns:
            List of (start, duration) for gaps
        """
        if not scheduled_slots:
            return [(0, total_slots)]
        
        # Merge overlapping slots
        sorted_slots = sorted(scheduled_slots, key=lambda x: x[0])
        merged = []
        for start, duration in sorted_slots:
            if merged and merged[-1][0] + merged[-1][1] >= start:
                # Extend previous slot if overlapping
                prev_start, prev_duration = merged[-1]
                merged[-1] = (prev_start, max(prev_duration, start + duration - prev_start))
            else:
                merged.append((start, duration))
        
        # Find gaps
        gaps = []
        
        # Gap before first scheduled slot
        if merged[0][0] > 0:
            gaps.append((0, merged[0][0]))
        
        # Gaps between slots
        for i in range(len(merged) - 1):
            current_end = merged[i][0] + merged[i][1]
            next_start = merged[i + 1][0]
            if current_end < next_start:
                gaps.append((current_end, next_start - current_end))
        
        # Gap after last scheduled slot
        last_end = merged[-1][0] + merged[-1][1]
        if last_end < total_slots:
            gaps.append((last_end, total_slots - last_end))
        
        return gaps


class ScheduleAnalyzer:
    """Utilities for analyzing schedules."""
    
    @staticmethod
    def get_schedule_density(scheduled_slots: List[Tuple[int, int]], 
                             total_slots: int) -> float:
        """
        Calculate schedule density (0-1, where 1 is fully packed).
        
        Args:
            scheduled_slots: List of (start, duration) tuples
            total_slots: Total available slots
            
        Returns:
            Density as fraction
        """
        if total_slots == 0:
            return 0.0
        
        occupied = sum(duration for _, duration in scheduled_slots)
        return occupied / total_slots
    
    @staticmethod
    def get_utilization_hours(scheduled_slots: List[Tuple[int, int]], 
                              slot_duration_minutes: int = 60) -> float:
        """
        Calculate total scheduled hours.
        
        Args:
            scheduled_slots: List of (start, duration) tuples where duration is in slots
            slot_duration_minutes: Minutes per slot
            
        Returns:
            Total hours scheduled
        """
        total_slot_minutes = sum(duration * slot_duration_minutes for _, duration in scheduled_slots)
        return total_slot_minutes / 60
    
    @staticmethod
    def group_slots_by_day(slots_with_days: List[Tuple[int, int, int]], 
                           slots_per_day: int) -> Dict[int, List[Tuple[int, int]]]:
        """
        Group slots by day.
        
        Args:
            slots_with_days: List of (day_idx, slot_idx, duration) tuples
            slots_per_day: Slots per day
            
        Returns:
            Dictionary mapping day_idx to list of (slot_idx, duration)
        """
        grouped = defaultdict(list)
        for day_idx, slot_idx, duration in slots_with_days:
            grouped[day_idx].append((slot_idx, duration))
        return dict(grouped)


class TimeConfiguration:
    """Utilities for managing time slot configurations."""
    
    @staticmethod
    def create_time_config(start_hour: int, end_hour: int, 
                          slot_duration: int = 60) -> List[str]:
        """
        Generate time slot configuration.
        
        Args:
            start_hour: Starting hour (0-23)
            end_hour: Ending hour (0-23)
            slot_duration: Duration of each slot in minutes
            
        Returns:
            List of time slot strings
        """
        slots = []
        current_hour = start_hour
        current_minute = 0
        
        while current_hour < end_hour:
            end_minute = current_minute + slot_duration
            end_hour_slot = current_hour + (end_minute // 60)
            end_minute = end_minute % 60
            
            if end_hour_slot > end_hour:
                break
            
            slot_str = f"{current_hour:02d}:{current_minute:02d}-{end_hour_slot:02d}:{end_minute:02d}"
            slots.append(slot_str)
            
            current_minute = end_minute
            current_hour = end_hour_slot
        
        return slots
    
    @staticmethod
    def get_default_theory_slots() -> List[str]:
        """
        Get default theory time slots.
        
        Returns:
            List of theory time slot strings
        """
        return [
            "08:00-09:00", "09:00-10:00", "10:00-11:00", "11:00-12:00",
            "12:00-13:00", "13:00-14:00", "14:00-15:00", "15:00-16:00",
            "16:00-17:00", "17:00-18:00", "18:00-19:00"
        ]
    
    @staticmethod
    def get_default_lab_slots() -> List[str]:
        """
        Get default lab time slots.
        
        Returns:
            List of lab time slot strings
        """
        return [
            "08:00-08:50", "08:50-09:40", "09:50-10:40", "10:40-11:30",
            "11:40-12:30", "12:30-13:20", "13:30-14:20", "14:20-15:10",
            "15:10-16:00", "16:00-16:50", "17:00-17:50", "17:50-18:40"
        ]
    
    @staticmethod
    def get_default_working_days() -> List[str]:
        """
        Get default working days (Monday-Friday).
        
        Returns:
            List of day names
        """
        return ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday']
