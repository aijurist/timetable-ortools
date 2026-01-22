"""Room eligibility index for pre-filtering rooms before variable creation.

This module provides a centralized service to determine which rooms are eligible
for each course, using the same logic as the core_lab constraint to ensure consistency.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from collections import defaultdict
from typing import Dict, Mapping, Optional, Set, Tuple

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class RoomEligibilityIndex:
    """Pre-computed index mapping course codes to eligible room IDs."""
    
    # Core lab courses: course_code -> specific allowed room IDs
    core_lab_mapping: Dict[str, Set[str]] = field(default_factory=dict)
    
    # Fallback rooms for non-mapped courses
    general_lab_rooms: Set[str] = field(default_factory=set)
    
    # All lab room IDs (for courses without core mapping)
    all_lab_room_ids: Tuple[str, ...] = field(default_factory=tuple)
    
    # Theory room IDs (no filtering for now)
    all_theory_room_ids: Tuple[str, ...] = field(default_factory=tuple)
    
    
    # Theory inventory for filtering
    theory_inventory: Optional['TheoryRoomInventory'] = None
    
    def get_eligible_lab_rooms(self, course_code: str) -> Tuple[str, ...]:
        """Return eligible room IDs for a lab course.
        
        Args:
            course_code: Normalized course code (uppercase, stripped)
            
        Returns:
            Tuple of room IDs eligible for this course
        """
        normalized = _normalize_course_code(course_code)
        
        # Check if course has specific core lab mapping
        if normalized in self.core_lab_mapping:
            rooms = self.core_lab_mapping[normalized]
            if rooms:
                return tuple(rooms)
        
        # Fall back to general lab rooms (laboratory_room_ids)
        if self.general_lab_rooms:
            return tuple(self.general_lab_rooms)
        
        # Ultimate fallback: all lab rooms
        return self.all_lab_room_ids
    
    def get_eligible_theory_rooms(
        self, 
        student_count: int = 0, 
        semester: Optional[int] = None
    ) -> Tuple[str, ...]:
        """Return eligible room IDs for a theory course based on capacity and tier policies.
        
        Args:
            student_count: Number of students (determines capacity needs and tiers)
            semester: Semester number (determines block preferences)
            
        Returns:
            Tuple of room IDs eligible for this course
        """
        if not self.theory_inventory:
            return self.all_theory_room_ids
            
        return self.theory_inventory.get_eligible_rooms(student_count, semester)


@dataclass
class TheoryRoomInventory:
    """Helper to store indexed theory room data for filtering."""
    rooms_by_block: Dict[str, Tuple[str, ...]]
    capacity_lookup: Dict[str, int]
    room_indices: Dict[str, int]  # room_id -> int index (0..N)
    
    # Configuration
    big_threshold: int = 140
    default_blocks: Tuple[str, ...] = ("A Block", "B Block", "C Block")
    senior_blocks: Tuple[str, ...] = ("A Block", "B Block")
    second_year_blocks: Tuple[str, ...] = ("B Block", "C Block")
    
    def get_eligible_rooms(self, student_count: int, semester: Optional[int]) -> Tuple[str, ...]:
        """Apply the same filtering logic as TheoryClassroomAssignmentConstraint."""
        # Resolve allowed blocks
        allowed_blocks = self._resolve_allowed_blocks(semester)
        if not allowed_blocks:
            allowed_blocks = self.default_blocks
            
        # Determine tier
        min_cap_needed = 0
        specific_tier_rooms: Optional[Set[str]] = None
        is_big = student_count >= self.big_threshold
        
        if student_count > 210:
            min_cap_needed = student_count
            specific_tier_rooms = {"225"} # ANEW201
        elif student_count > 165:
            min_cap_needed = student_count
            specific_tier_rooms = {"221", "222"} # ANEW101, ANEW102
        elif student_count > 130:
            min_cap_needed = student_count
            specific_tier_rooms = {"223", "224", "220", "3"} # ANEW103, ANEW104, KSL02, A104/105
        elif student_count >= 100:
            min_cap_needed = 140 # Force large room for 100+ student case
            specific_tier_rooms = {"223", "224", "220", "3"}
            
        # Collect candidate rooms from allowed blocks
        candidate_rooms = []
        for block in allowed_blocks:
            if block in self.rooms_by_block:
                candidate_rooms.extend(self.rooms_by_block[block])
                
        if not candidate_rooms:
            candidate_rooms = list(self.capacity_lookup.keys())
            
        filtered_rooms = []
        
        if min_cap_needed > 0:
            # Strict filtering: ignore block restrictions to find capacity
            all_rooms = list(self.capacity_lookup.keys())
            sized = [
                rid for rid in all_rooms
                if self.capacity_lookup.get(rid, 0) >= min_cap_needed
            ]
            
            if specific_tier_rooms:
                tier_matches = [r for r in sized if r in specific_tier_rooms]
                if tier_matches:
                    filtered_rooms = tier_matches
                else:
                    filtered_rooms = sized
            else:
                filtered_rooms = sized
                
        elif is_big:
            # Legacy big threshold check (restrict to allowed blocks)
            filtered_rooms = [
                rid for rid in candidate_rooms
                if self.capacity_lookup.get(rid, 0) >= self.big_threshold
            ]
            
        else:
            # Small courses: prefer small rooms (< big_threshold)
            small_candidates = [
                rid for rid in candidate_rooms
                if self.capacity_lookup.get(rid, 0) < self.big_threshold
            ]
            
            if small_candidates:
                filtered_rooms = small_candidates
            else:
                # Fallback to any room that fits
                fallback = [
                    rid for rid in self.capacity_lookup.keys()
                    if self.capacity_lookup.get(rid, 0) >= max(student_count, 50)
                ]
                filtered_rooms = fallback
                
        return tuple(filtered_rooms)
        
    def _resolve_allowed_blocks(self, semester: Optional[int]) -> Tuple[str, ...]:
        if semester is None:
            return self.default_blocks
        if semester >= 5:
            return self.senior_blocks or self.default_blocks
        elif semester in (3, 4):
            return self.second_year_blocks or self.default_blocks
        return self.default_blocks


def build_room_eligibility_index(
    core_lab_df: Optional[pd.DataFrame],
    rooms_df: Optional[pd.DataFrame],
    lab_room_ids: Tuple[str, ...],
    theory_room_ids: Tuple[str, ...],
    laboratory_room_ids: Optional[Tuple[str, ...]] = None,
) -> RoomEligibilityIndex:
    """Build room eligibility index from data sources.
    
    Uses the same logic as CoreLabMappingConstraint to ensure consistency.
    """
    index = RoomEligibilityIndex(
        all_lab_room_ids=lab_room_ids,
        all_theory_room_ids=theory_room_ids,
    )
    
    # DEBUG: Log incoming data
    logger.info(
        "Room eligibility init: lab_room_ids=%d, theory_room_ids=%d, laboratory_room_ids=%s",
        len(lab_room_ids),
        len(theory_room_ids),
        len(laboratory_room_ids) if laboratory_room_ids else "None",
    )
    
    # Build Theory Inventory
    if rooms_df is not None and not rooms_df.empty:
        index.theory_inventory = _build_theory_inventory(rooms_df, theory_room_ids)
        logger.info("Built theory room inventory with %d rooms", len(index.theory_inventory.capacity_lookup))
    
    # Set general lab rooms (fallback for non-mapped courses)
    if laboratory_room_ids:
        index.general_lab_rooms = set(str(rid) for rid in laboratory_room_ids)
    else:
        index.general_lab_rooms = set(lab_room_ids)
    
    # Build core lab mapping if data available
    if core_lab_df is not None and rooms_df is not None and not core_lab_df.empty:
        room_lookup = _build_room_lookup(rooms_df)
        index.core_lab_mapping = _build_core_mapping(core_lab_df, room_lookup)
        
        logger.info(
            "Built room eligibility index: %d core mappings, %d general rooms (fallback)",
            len(index.core_lab_mapping),
            len(index.general_lab_rooms),
        )
    else:
        logger.warning(
            "Core lab mapping not available: core_df=%s, rooms_df=%s",
            core_lab_df is not None,
            rooms_df is not None,
        )
    
    return index


def _build_theory_inventory(rooms_df: pd.DataFrame, theory_room_ids: Tuple[str, ...]) -> TheoryRoomInventory:
    """Build the helper inventory for theory room filtering."""
    rooms_by_block = defaultdict(list)
    capacity_lookup = {}
    room_indices = {}
    
    # Filter rooms_df for theory rooms
    # We assume 'id' column matches theory_room_ids
    theory_set = set(str(rid) for rid in theory_room_ids)
    
    for idx, row in rooms_df.iterrows():
        rid = str(row.get('id', ''))
        if rid not in theory_set:
            continue
            
        # Extract Block
        block_raw = row.get('block') or row.get('Block') or row.get('building')
        block = _normalise_block(block_raw)
        
        # Extract Capacity
        cap = 0
        try:
            val = row.get('room_max_cap') or row.get('capacity') or row.get('room_capacity') or row.get('max_capacity')
            if pd.notna(val):
                cap = int(float(val))
        except (ValueError, TypeError):
            cap = 0
            
        if cap <= 0:
            continue
            
        rooms_by_block[block].append(rid)
        capacity_lookup[rid] = cap
        
    # Populate indices based on the passed sorted tuple
    for i, rid in enumerate(theory_room_ids):
        room_indices[rid] = i
        
    return TheoryRoomInventory(
        rooms_by_block=dict(rooms_by_block),
        capacity_lookup=capacity_lookup,
        room_indices=room_indices
    )


def _normalise_block(value: object) -> str:
    if value is None:
        return "Unknown Block"
    text = str(value).strip()
    if not text:
        return "Unknown Block"
    upper = text.upper()
    mapping = {
        "A": "A Block", "A BLOCK": "A Block", "BLOCK A": "A Block",
        "ADMIN": "A Block", "ADMIN BLOCK": "A Block",
        "B": "B Block", "B BLOCK": "B Block", "BLOCK B": "B Block",
        "C": "C Block", "C BLOCK": "C Block", "BLOCK C": "C Block",
    }
    if upper in mapping:
        return mapping[upper]
    if upper.startswith("A"): return "A Block"
    if upper.startswith("B"): return "B Block"
    if upper.startswith("C"): return "C Block"
    return text.title()


def _build_room_lookup(rooms_df: pd.DataFrame) -> Dict[str, str]:
    """Build lookup from room name variations to room ID.
    
    Replicates CoreLabMappingConstraint._build_room_lookup logic.
    """
    lookup: Dict[str, str] = {}
    
    for _, row in rooms_df.iterrows():
        room_id = str(row.get("id", ""))
        if not room_id:
            continue
        
        # Add various name variations
        names = [
            row.get("room_number"),
            row.get("room_name"),
            row.get("description"),
        ]
        block = row.get("block")
        room_number = row.get("room_number")
        
        if room_number and block:
            names.append(f"{room_number}_{block}")
            names.append(f"{room_number} {block}")
        
        for name in names:
            key = _normalize(name)
            if key:
                lookup[key] = room_id
        
        # Also add the room_id itself
        lookup[_normalize(room_id)] = room_id
    
    return lookup


def _build_core_mapping(
    core_df: pd.DataFrame,
    room_lookup: Dict[str, str],
) -> Dict[str, Set[str]]:
    """Build course code to room IDs mapping.
    
    Replicates CoreLabMappingConstraint._build_room_map logic.
    """
    mapping: Dict[str, Set[str]] = {}
    
    for _, row in core_df.iterrows():
        course_code = _normalize_course_code(row.get("course_code"))
        if not course_code:
            continue
        
        room_ids = _extract_room_ids(row, room_lookup)
        if room_ids:
            bucket = mapping.setdefault(course_code, set())
            bucket.update(room_ids)
    
    return mapping


def _extract_room_ids(row: pd.Series, lookup: Dict[str, str]) -> Set[str]:
    """Extract room IDs from a core lab mapping row.
    
    Replicates CoreLabMappingConstraint._extract_room_ids logic.
    """
    resolved: Set[str] = set()
    
    for column, value in row.items():
        if not str(column).lower().startswith("lab_"):
            continue
        if value is None or pd.isna(value):
            continue
        
        column_lower = str(column).lower()
        if column_lower.endswith("_block"):
            continue
        
        # Handle lab_N_room vs lab_N format
        if column_lower.endswith("_room"):
            num_token = column_lower.split("_")[1]
            block_value = row.get(f"lab_{num_token}_block")
            room_id = _resolve_room(str(value), block_value, lookup)
        else:
            room_id = _resolve_room(str(value), None, lookup)
        
        if room_id:
            resolved.add(room_id)
    
    return resolved


def _resolve_room(
    name: Optional[str],
    block: Optional[str],
    lookup: Dict[str, str],
) -> Optional[str]:
    """Resolve room name to room ID.
    
    Replicates CoreLabMappingConstraint._resolve_room logic.
    """
    candidates = [_normalize(name)]
    if block and not pd.isna(block):
        candidates.append(_normalize(f"{name}_{block}"))
        candidates.append(_normalize(f"{name} {block}"))
    
    for key in candidates:
        if key and key in lookup:
            return lookup[key]
    
    return None


def _normalize(value: Optional[str]) -> str:
    """Normalize string for lookup (lowercase alphanumeric only)."""
    if not value or pd.isna(value):
        return ""
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


def _normalize_course_code(value: Optional[str]) -> str:
    """Normalize course code (uppercase, stripped)."""
    if not value or pd.isna(value):
        return ""
    return str(value).strip().upper()
