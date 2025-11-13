"""
Room Utilities Module

Provides helper functions for room data handling:
- Room parsing and validation
- Floor extraction from room IDs
- Capacity categorization
- Room registry management
- Room matching and allocation utilities
"""

import pandas as pd
import logging
import re
from typing import Dict, List, Any, Optional, Set, Tuple
from .data_utils import DataNormalizer, DataValidator, DataExtractor

logger = logging.getLogger(__name__)


class RoomParser:
    """Utilities for parsing and normalizing room data."""
    
    @staticmethod
    def parse_room_id(room_id: Any) -> str:
        """
        Parse and normalize room ID from various formats.
        
        Args:
            room_id: Room ID (can be int, float, or string)
            
        Returns:
            Normalized room ID as string
        """
        if pd.isna(room_id):
            return ""
        
        # Convert to string and extract alphanumeric + common separators
        id_str = str(room_id).strip()
        
        # Clean up common numeric room IDs
        if id_str.replace('.', '').replace('-', '').isdigit():
            # Remove trailing zeros after decimal if present
            try:
                return str(int(float(id_str)))
            except (ValueError, TypeError):
                pass
        
        return id_str
    
    @staticmethod
    def parse_room_capacity(capacity: Any, default: int = 0) -> int:
        """
        Parse room capacity with validation.
        
        Args:
            capacity: Capacity value
            default: Default value if parsing fails
            
        Returns:
            Integer capacity value
        """
        return DataNormalizer.safe_int(capacity, default)
    
    @staticmethod
    def parse_room_block(block: Any) -> str:
        """
        Parse room block/building information.
        
        Args:
            block: Block identifier
            
        Returns:
            Normalized block name
        """
        if pd.isna(block):
            return "Unknown"
        
        block_str = str(block).strip().upper()
        
        # Map common abbreviations
        mappings = {
            'A': 'A Block',
            'B': 'B Block',
            'C': 'C Block',
            'D': 'D Block',
            'E': 'E Block',
            'F': 'F Block',
            'J': 'J Block',
            'K': 'K Block',
            'TECH': 'Techlounge',
            'TIFAC': 'TIFAC',
        }
        
        # Try exact match first
        if block_str in mappings:
            return mappings[block_str]
        
        # Try prefix match
        for key, val in mappings.items():
            if block_str.startswith(key):
                return val
        
        # Return as-is if no match
        return block_str
    
    @staticmethod
    def parse_room_type(room_type: Any) -> str:
        """
        Parse room type (classroom, lab, etc).
        
        Args:
            room_type: Room type identifier
            
        Returns:
            Normalized room type
        """
        if pd.isna(room_type):
            return "Classroom"
        
        type_str = str(room_type).strip().lower()
        
        if 'lab' in type_str or 'laboratory' in type_str:
            return "Lab"
        elif 'class' in type_str or 'classroom' in type_str:
            return "Classroom"
        elif 'seminar' in type_str:
            return "Seminar"
        elif 'conference' in type_str:
            return "Conference"
        else:
            return type_str.title()


class RoomValidator:
    """Utilities for validating room data."""
    
    @staticmethod
    def is_valid_room(room: Dict) -> Tuple[bool, Optional[str]]:
        """
        Validate a room record for completeness.
        
        Args:
            room: Room dictionary
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        errors = []
        
        # Check required fields
        if not room.get('id') or not str(room['id']).strip():
            errors.append("Missing or empty room ID")
        
        if not room.get('capacity') or room['capacity'] <= 0:
            errors.append("Invalid capacity")
        
        if errors:
            return False, "; ".join(errors)
        
        return True, None
    
    @staticmethod
    def validate_room_capacity(capacity: int, min_cap: int = 0, 
                               max_cap: int = 500) -> Tuple[bool, str]:
        """
        Validate room capacity is within reasonable bounds.
        
        Args:
            capacity: Room capacity
            min_cap: Minimum allowed capacity
            max_cap: Maximum allowed capacity
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if capacity < min_cap or capacity > max_cap:
            msg = f"Capacity {capacity} out of range [{min_cap}, {max_cap}]"
            return False, msg
        return True, ""
    
    @staticmethod
    def validate_room_id_format(room_id: str) -> Tuple[bool, str]:
        """
        Validate room ID format.
        
        Args:
            room_id: Room ID to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not room_id or not str(room_id).strip():
            return False, "Empty room ID"
        
        # Room IDs should be alphanumeric
        if not re.match(r'^[A-Za-z0-9\-_\s\.]+$', str(room_id)):
            return False, f"Invalid room ID format: {room_id}"
        
        return True, ""
    
    @staticmethod
    def check_duplicate_room_ids(rooms: List[Dict]) -> List[str]:
        """
        Check for duplicate room IDs.
        
        Args:
            rooms: List of room dictionaries
            
        Returns:
            List of duplicate room IDs
        """
        room_ids = [r.get('id') for r in rooms if r.get('id')]
        duplicates = [rid for rid in set(room_ids) if room_ids.count(rid) > 1]
        
        if duplicates:
            logger.warning(f"Found {len(duplicates)} duplicate room IDs: {duplicates}")
        
        return duplicates


class FloorExtractor:
    """Utilities for extracting floor information from room IDs."""
    
    @staticmethod
    def extract_floor_from_id(room_id: str) -> int:
        """
        Extract floor number from room ID.
        
        Common patterns:
        - "201" -> floor 2
        - "A201" -> floor 2
        - "2-01" -> floor 2
        - "TLFL1" -> floor 1
        
        Args:
            room_id: Room ID string
            
        Returns:
            Floor number (0 if cannot be determined)
        """
        if not room_id or not str(room_id).strip():
            return 0
        
        room_id = str(room_id).strip().upper()
        
        # Try to extract first digit after letters
        match = re.search(r'[A-Z]*([0-9])', room_id)
        if match:
            try:
                first_digit = int(match.group(1))
                # First digit often represents floor for numeric IDs
                if first_digit > 0:
                    return first_digit
            except (ValueError, IndexError):
                pass
        
        # Try 3+ digit pattern where first digit is floor
        numeric_part = re.search(r'([0-9]{2,})', room_id)
        if numeric_part:
            try:
                num = int(numeric_part.group(1))
                if num >= 100:
                    floor = num // 100
                    if 0 <= floor <= 10:
                        return floor
            except ValueError:
                pass
        
        return 0
    
    @staticmethod
    def categorize_floor(floor: int) -> str:
        """
        Categorize floor as Ground, Lower, or Upper.
        
        Args:
            floor: Floor number
            
        Returns:
            Floor category
        """
        if floor == 0:
            return "Ground"
        elif floor <= 2:
            return "Lower"
        else:
            return "Upper"


class CapacityAnalyzer:
    """Utilities for analyzing and categorizing room capacities."""
    
    # Standard capacity categories
    CAPACITY_RANGES = {
        'small': (0, 35),
        'medium': (35, 70),
        'large': (70, 140),
        'xl': (140, 500),
    }
    
    @staticmethod
    def categorize_capacity(capacity: int) -> str:
        """
        Categorize room by capacity.
        
        Args:
            capacity: Room capacity
            
        Returns:
            Capacity category
        """
        for cat, (min_cap, max_cap) in CapacityAnalyzer.CAPACITY_RANGES.items():
            if min_cap <= capacity < max_cap:
                return cat
        return "unknown"
    
    @staticmethod
    def find_suitable_rooms(rooms: List[Dict], required_capacity: int) -> List[Dict]:
        """
        Find rooms suitable for a given capacity requirement.
        
        Args:
            rooms: List of room dictionaries
            required_capacity: Required capacity
            
        Returns:
            List of suitable rooms (capacity >= required), sorted by capacity
        """
        suitable = [r for r in rooms if r.get('capacity', 0) >= required_capacity]
        return sorted(suitable, key=lambda r: r.get('capacity', 0))
    
    @staticmethod
    def get_capacity_statistics(rooms: List[Dict]) -> Dict[str, Any]:
        """
        Get capacity statistics for rooms.
        
        Args:
            rooms: List of room dictionaries
            
        Returns:
            Dictionary with min, max, avg capacity and distribution
        """
        capacities = [r.get('capacity', 0) for r in rooms if r.get('capacity')]
        
        if not capacities:
            return {'min': 0, 'max': 0, 'avg': 0, 'count': 0, 'distribution': {}}
        
        distribution = {}
        for cat in CapacityAnalyzer.CAPACITY_RANGES.keys():
            count = sum(1 for c in capacities 
                       if CapacityAnalyzer.categorize_capacity(c) == cat)
            distribution[cat] = count
        
        return {
            'min': min(capacities),
            'max': max(capacities),
            'avg': sum(capacities) / len(capacities),
            'count': len(capacities),
            'distribution': distribution,
        }


class RoomRegistry:
    """Utilities for building and managing room registries."""
    
    @staticmethod
    def build_registry(rooms: List[Dict], key_field: str = 'id') -> Dict[str, Dict]:
        """
        Build room lookup registry.
        
        Args:
            rooms: List of room dictionaries
            key_field: Field to use as key
            
        Returns:
            Dictionary mapping room IDs to room data
        """
        registry = {}
        for room in rooms:
            key = room.get(key_field)
            if key:
                registry[str(key)] = room
        
        logger.info(f"Built room registry with {len(registry)} rooms using key '{key_field}'")
        return registry
    
    @staticmethod
    def build_block_registry(rooms: List[Dict]) -> Dict[str, List[Dict]]:
        """
        Build room registry grouped by block.
        
        Args:
            rooms: List of room dictionaries
            
        Returns:
            Dictionary mapping block names to lists of rooms
        """
        blocks = {}
        for room in rooms:
            block = room.get('block', 'Unknown')
            if block not in blocks:
                blocks[block] = []
            blocks[block].append(room)
        
        logger.info(f"Built block registry with {len(blocks)} blocks")
        return blocks
    
    @staticmethod
    def build_type_registry(rooms: List[Dict]) -> Dict[str, List[Dict]]:
        """
        Build room registry grouped by type (Lab vs Classroom).
        
        Args:
            rooms: List of room dictionaries
            
        Returns:
            Dictionary mapping room types to lists of rooms
        """
        types = {}
        for room in rooms:
            room_type = room.get('type', 'Unknown')
            if room_type not in types:
                types[room_type] = []
            types[room_type].append(room)
        
        logger.info(f"Built type registry with {len(types)} types")
        return types
    
    @staticmethod
    def build_capacity_registry(rooms: List[Dict]) -> Dict[str, List[Dict]]:
        """
        Build room registry grouped by capacity category.
        
        Args:
            rooms: List of room dictionaries
            
        Returns:
            Dictionary mapping capacity categories to lists of rooms
        """
        categories = {}
        for room in rooms:
            capacity = room.get('capacity', 0)
            cat = CapacityAnalyzer.categorize_capacity(capacity)
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(room)
        
        logger.info(f"Built capacity registry with {len(categories)} categories")
        return categories
    
    @staticmethod
    def lookup_room(registry: Dict[str, Dict], room_id: str) -> Optional[Dict]:
        """
        Look up room from registry.
        
        Args:
            registry: Room registry dictionary
            room_id: Room ID to look up
            
        Returns:
            Room dictionary or None if not found
        """
        return registry.get(str(room_id))
    
    @staticmethod
    def get_available_rooms(registry: Dict[str, Dict]) -> List[Dict]:
        """
        Get list of all available rooms from registry.
        
        Args:
            registry: Room registry dictionary
            
        Returns:
            List of room dictionaries
        """
        return list(registry.values())


class RoomMatcher:
    """Utilities for matching rooms to requirements."""
    
    @staticmethod
    def match_by_capacity(rooms: List[Dict], required_capacity: int) -> List[Dict]:
        """
        Match rooms by minimum capacity requirement.
        
        Args:
            rooms: List of available rooms
            required_capacity: Required capacity
            
        Returns:
            Rooms meeting capacity requirement, sorted by utilization efficiency
        """
        matches = [r for r in rooms if r.get('capacity', 0) >= required_capacity]
        # Sort by how efficiently the capacity is used (closest fit first)
        return sorted(matches, key=lambda r: r.get('capacity', float('inf')))
    
    @staticmethod
    def match_by_block(rooms: List[Dict], preferred_block: str) -> List[Dict]:
        """
        Match rooms by preferred block.
        
        Args:
            rooms: List of available rooms
            preferred_block: Preferred block name
            
        Returns:
            Rooms in preferred block
        """
        return [r for r in rooms if r.get('block', '').upper() == preferred_block.upper()]
    
    @staticmethod
    def match_by_floor(rooms: List[Dict], preferred_floor: int) -> List[Dict]:
        """
        Match rooms by preferred floor.
        
        Args:
            rooms: List of available rooms
            preferred_floor: Preferred floor number
            
        Returns:
            Rooms on preferred floor
        """
        return [r for r in rooms if r.get('floor', 0) == preferred_floor]
    
    @staticmethod
    def match_by_type(rooms: List[Dict], room_type: str) -> List[Dict]:
        """
        Match rooms by type (Lab, Classroom, etc).
        
        Args:
            rooms: List of available rooms
            room_type: Required room type
            
        Returns:
            Rooms of specified type
        """
        return [r for r in rooms if r.get('type', '').lower() == room_type.lower()]
    
    @staticmethod
    def find_best_match(rooms: List[Dict], capacity: int, 
                       preferred_block: Optional[str] = None,
                       preferred_floor: Optional[int] = None) -> Optional[Dict]:
        """
        Find best room match based on multiple criteria.
        
        Priority:
        1. Capacity requirement
        2. Preferred block (if specified)
        3. Preferred floor (if specified)
        
        Args:
            rooms: List of available rooms
            capacity: Required capacity
            preferred_block: Preferred block (optional)
            preferred_floor: Preferred floor (optional)
            
        Returns:
            Best matching room or None
        """
        # Start with capacity matches
        candidates = RoomMatcher.match_by_capacity(rooms, capacity)
        
        if not candidates:
            return None
        
        # Filter by block if specified
        if preferred_block:
            block_matches = RoomMatcher.match_by_block(candidates, preferred_block)
            if block_matches:
                candidates = block_matches
        
        # Filter by floor if specified
        if preferred_floor is not None:
            floor_matches = RoomMatcher.match_by_floor(candidates, preferred_floor)
            if floor_matches:
                candidates = floor_matches
        
        # Return first (best fit by capacity)
        return candidates[0] if candidates else None
