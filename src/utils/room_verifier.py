import logging
from typing import Dict, List, Any, Tuple

class RoomVerifier:
    """
    Room allocation verification module for timetable scheduling.
    
    Provides comprehensive verification of room assignments including:
    - Conflict detection (multiple courses in same room at same time)
    - Room utilization statistics
    - Time slot distribution analysis
    - Constraint compliance verification
    """
    
    def __init__(self, logger=None):
        """Initialize the room verifier."""
        self.logger = logger or logging.getLogger(__name__)
    
    def verify_room_distribution_and_overlaps(self, schedule_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Verify room distribution and check for overlapping room assignments.
        
        Args:
            schedule_result: Dictionary containing schedule data and metadata
            
        Returns:
            Dictionary with verification results including conflicts, statistics, and compliance status
            
        Checks:
        1. No multiple course instances in the same room at the same time slot
        2. Room utilization statistics
        3. Detection of any constraint violations
        4. Room capacity constraint verification (which slots hit capacity limit)
        """
        schedule_data = schedule_result['schedule_data']
        
        self.logger.info("=" * 60)
        self.logger.info("ROOM DISTRIBUTION AND OVERLAP VERIFICATION")
        self.logger.info("=" * 60)
        
        # 1. Check for room conflicts at same time slots
        conflicts = self._detect_room_conflicts(schedule_data)
        
        # 2. Generate room utilization statistics
        room_usage_stats = self._calculate_room_utilization(schedule_data)
        
        # 3. Analyze time slot distribution
        timeslot_distribution = self._analyze_timeslot_distribution(schedule_data)
        
        # 4. Verify room capacity constraints
        room_capacity_verification = self._verify_room_capacity_constraints(schedule_data)
        
        # 5. Print comprehensive verification results
        self._print_verification_results(conflicts, room_usage_stats, timeslot_distribution, schedule_data)
        
        # 6. Print room capacity verification results
        self._print_room_capacity_verification(room_capacity_verification)
        
        return {
            'conflicts_detected': len(conflicts) > 0,
            'conflict_count': len(conflicts),
            'conflicts': conflicts,
            'room_usage_stats': room_usage_stats,
            'timeslot_distribution': timeslot_distribution,
            'room_capacity_verification': room_capacity_verification,
            'total_assignments': len(schedule_data),
            'rooms_used': len(room_usage_stats),
            'verification_passed': len(conflicts) == 0
        }
    
    def _detect_room_conflicts(self, schedule_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Detect room conflicts where multiple courses are assigned to same room at same time.
        
        Args:
            schedule_data: List of schedule assignments
            
        Returns:
            List of detected conflicts with details
        """
        conflicts = []
        room_usage_by_timeslot = {}
        
        # Group assignments by timeslot and room
        for item in schedule_data:
            day = item['day']
            slot_index = item['slot_index']
            room_id = item['room_id']
            teacher_id = item['teacher_id']
            course_code = item['course_code']
            time_interval = item['time_interval']
            
            # Create unique key for day + slot
            timeslot_key = f"{day}_slot_{slot_index}_{time_interval}"
            
            if timeslot_key not in room_usage_by_timeslot:
                room_usage_by_timeslot[timeslot_key] = {}
            
            if room_id not in room_usage_by_timeslot[timeslot_key]:
                room_usage_by_timeslot[timeslot_key][room_id] = []
            
            room_usage_by_timeslot[timeslot_key][room_id].append({
                'teacher_id': teacher_id,
                'course_code': course_code,
                'course_instance_id': item['course_instance_id'],
                'room_number': item['room_number']
            })
        
        # Detect conflicts (multiple assignments to same room at same time)
        for timeslot_key, rooms in room_usage_by_timeslot.items():
            for room_id, assignments in rooms.items():
                if len(assignments) > 1:
                    conflicts.append({
                        'timeslot': timeslot_key,
                        'room_id': room_id,
                        'room_number': assignments[0]['room_number'],
                        'conflicting_assignments': assignments,
                        'conflict_count': len(assignments)
                    })
        
        return conflicts
    
    def _calculate_room_utilization(self, schedule_data: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """
        Calculate room utilization statistics.
        
        Args:
            schedule_data: List of schedule assignments
            
        Returns:
            Dictionary with room usage statistics
        """
        room_usage_count = {}
        
        for item in schedule_data:
            room_id = item['room_id']
            room_number = item['room_number']
            
            if room_id not in room_usage_count:
                room_usage_count[room_id] = {
                    'room_number': room_number,
                    'usage_count': 0,
                    'time_slots': [],
                    'courses': set(),
                    'teachers': set(),
                    'capacity': item.get('capacity', 0),
                    'room_type': item.get('room_type', 'Unknown')
                }
            
            room_usage_count[room_id]['usage_count'] += 1
            room_usage_count[room_id]['time_slots'].append(f"{item['day']} {item['time_interval']}")
            room_usage_count[room_id]['courses'].add(item['course_code'])
            room_usage_count[room_id]['teachers'].add(item['teacher_id'])
        
        # Convert sets to counts for JSON serialization
        for room_id in room_usage_count:
            room_usage_count[room_id]['unique_courses'] = len(room_usage_count[room_id]['courses'])
            room_usage_count[room_id]['unique_teachers'] = len(room_usage_count[room_id]['teachers'])
            room_usage_count[room_id]['courses'] = list(room_usage_count[room_id]['courses'])
            room_usage_count[room_id]['teachers'] = list(room_usage_count[room_id]['teachers'])
        
        return room_usage_count
    
    def _analyze_timeslot_distribution(self, schedule_data: List[Dict[str, Any]]) -> Dict[str, int]:
        """
        Analyze distribution of assignments across time slots.
        
        Args:
            schedule_data: List of schedule assignments
            
        Returns:
            Dictionary with timeslot usage counts
        """
        timeslot_usage = {}
        
        for item in schedule_data:
            day = item['day']
            slot_index = item['slot_index']
            time_interval = item['time_interval']
            timeslot_key = f"{day}_slot_{slot_index}_{time_interval}"
            
            timeslot_usage[timeslot_key] = timeslot_usage.get(timeslot_key, 0) + 1
        
        return timeslot_usage
    
    def _print_verification_results(self, conflicts: List[Dict[str, Any]], 
                                  room_usage_stats: Dict[str, Dict[str, Any]], 
                                  timeslot_distribution: Dict[str, int],
                                  schedule_data: List[Dict[str, Any]]) -> None:
        """
        Print comprehensive verification results.
        
        Args:
            conflicts: List of detected conflicts
            room_usage_stats: Room utilization statistics
            timeslot_distribution: Time slot distribution data
            schedule_data: Original schedule data
        """
        total_assignments = len(schedule_data)
        
        # Basic statistics
        self.logger.info(f"TOTAL ROOM ASSIGNMENTS: {total_assignments}")
        self.logger.info(f"UNIQUE ROOMS USED: {len(room_usage_stats)}")
        
        # Conflict reporting
        if conflicts:
            self.logger.error(f"❌ ROOM CONFLICTS DETECTED: {len(conflicts)} conflicts found!")
            for i, conflict in enumerate(conflicts[:5], 1):  # Show first 5 conflicts
                self.logger.error(f"  Conflict {i}: Room {conflict['room_number']} (ID: {conflict['room_id']}) at {conflict['timeslot']}")
                for assignment in conflict['conflicting_assignments']:
                    self.logger.error(f"    - Teacher {assignment['teacher_id']}: {assignment['course_code']} (Instance {assignment['course_instance_id']})")
            
            if len(conflicts) > 5:
                self.logger.error(f"    ... and {len(conflicts) - 5} more conflicts")
        else:
            self.logger.info("✅ NO ROOM CONFLICTS DETECTED - All constraints satisfied!")
        
        # Room utilization breakdown
        self._print_room_utilization(room_usage_stats, total_assignments)
        
        # Time slot distribution
        self._print_timeslot_distribution(timeslot_distribution)
        
        # Summary
        self._print_verification_summary(conflicts, room_usage_stats, total_assignments)
    
    def _print_room_utilization(self, room_usage_stats: Dict[str, Dict[str, Any]], total_assignments: int) -> None:
        """Print detailed room utilization breakdown."""
        self.logger.info("\nROOM UTILIZATION BREAKDOWN:")
        self.logger.info("-" * 40)
        
        sorted_rooms = sorted(room_usage_stats.items(), key=lambda x: x[1]['usage_count'], reverse=True)
        
        for room_id, usage_info in sorted_rooms[:10]:  # Show top 10 most used rooms
            usage_count = usage_info['usage_count']
            room_number = usage_info['room_number']
            unique_courses = usage_info['unique_courses']
            unique_teachers = usage_info['unique_teachers']
            capacity = usage_info['capacity']
            utilization_percentage = (usage_count / total_assignments) * 100
            
            self.logger.info(f"  Room {room_number} (ID: {room_id}): {usage_count} assignments ({utilization_percentage:.1f}%)")
            self.logger.info(f"    └─ {unique_courses} courses, {unique_teachers} teachers, Capacity: {capacity}")
        
        if len(sorted_rooms) > 10:
            self.logger.info(f"    ... and {len(sorted_rooms) - 10} more rooms")
    
    def _print_timeslot_distribution(self, timeslot_distribution: Dict[str, int]) -> None:
        """Print time slot distribution analysis."""
        self.logger.info("\nTIME SLOT DISTRIBUTION CHECK:")
        self.logger.info("-" * 35)
        
        for timeslot_key in sorted(timeslot_distribution.keys()):
            assignments_count = timeslot_distribution[timeslot_key]
            self.logger.info(f"  {timeslot_key}: {assignments_count} room assignments")
    
    def _print_verification_summary(self, conflicts: List[Dict[str, Any]], 
                                  room_usage_stats: Dict[str, Dict[str, Any]], 
                                  total_assignments: int) -> None:
        """Print final verification summary."""
        self.logger.info("=" * 60)
        self.logger.info("VERIFICATION SUMMARY:")
        self.logger.info(f"  ✅ Room Constraint Status: {'SATISFIED' if not conflicts else 'VIOLATED'}")
        self.logger.info(f"  📊 Total Assignments: {total_assignments}")
        self.logger.info(f"  🏢 Rooms Used: {len(room_usage_stats)}")
        self.logger.info(f"  ⚠️  Conflicts Found: {len(conflicts)}")
        self.logger.info(f"  📈 Room Utilization: {len(room_usage_stats)} rooms for {total_assignments} assignments")
        
        if conflicts:
            self.logger.info(f"  🚨 ACTION REQUIRED: Fix {len(conflicts)} room conflicts")
        else:
            self.logger.info(f"  🎯 SUCCESS: All room constraints satisfied")
        
        self.logger.info("=" * 60)
    
    def generate_room_verification_report(self, schedule_result: Dict[str, Any], output_path: str) -> None:
        """
        Generate a detailed room verification report and save to file.
        
        Args:
            schedule_result: Dictionary containing schedule data
            output_path: Path to save the verification report
        """
        verification_result = self.verify_room_distribution_and_overlaps(schedule_result)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("Room Allocation Verification Report\n")
            f.write("=" * 50 + "\n\n")
            
            # Summary
            f.write(f"Total Assignments: {verification_result['total_assignments']}\n")
            f.write(f"Rooms Used: {verification_result['rooms_used']}\n")
            f.write(f"Conflicts Detected: {verification_result['conflict_count']}\n")
            f.write(f"Verification Status: {'PASSED' if verification_result['verification_passed'] else 'FAILED'}\n\n")
            
            # Conflicts details
            if verification_result['conflicts']:
                f.write("CONFLICTS DETECTED:\n")
                f.write("-" * 20 + "\n")
                for conflict in verification_result['conflicts']:
                    f.write(f"Room {conflict['room_number']} at {conflict['timeslot']}:\n")
                    for assignment in conflict['conflicting_assignments']:
                        f.write(f"  - {assignment['course_code']} (Teacher {assignment['teacher_id']})\n")
                    f.write("\n")
            else:
                f.write("✅ NO CONFLICTS DETECTED - All constraints satisfied!\n\n")
            
            # Room capacity constraint verification
            f.write("ROOM CAPACITY CONSTRAINT VERIFICATION:\n")
            f.write("-" * 40 + "\n")
            
            room_capacity = verification_result['room_capacity_verification']
            total_rooms = room_capacity['total_rooms_available']
            max_groups = room_capacity['max_groups_in_any_timeslot']
            max_rooms = room_capacity['max_rooms_in_any_timeslot']
            capacity_ratio = room_capacity['capacity_hit_ratio']
            
            f.write(f"Total unique rooms available: {total_rooms}\n")
            f.write(f"Maximum groups in any timeslot: {max_groups}\n")
            f.write(f"Maximum rooms used in any timeslot: {max_rooms} ({capacity_ratio:.1%} of capacity)\n\n")
            
            # Timeslots that hit capacity
            capacity_hit_slots = room_capacity['capacity_hit_slots']
            if capacity_hit_slots:
                f.write("TIMESLOTS THAT HIT ROOM CAPACITY LIMIT:\n")
                for slot in capacity_hit_slots:
                    detection_method = slot.get('detection_method', 'unknown')
                    group_count = slot.get('group_count', 0)
                    room_count = slot.get('room_count', 0)
                    f.write(f"  {slot['timeslot']}: {room_count} rooms used, {group_count} groups scheduled\n")
                    f.write(f"    (100% of {slot['total_rooms']} rooms - detected by {detection_method})\n")
                
                # Show which day had the most capacity hits
                day_counts = {}
                for slot in capacity_hit_slots:
                    day = slot['timeslot'].split('_')[0]  # Extract day from timeslot key
                    day_counts[day] = day_counts.get(day, 0) + 1
                
                if day_counts:
                    max_day = max(day_counts.items(), key=lambda x: x[1])
                    f.write(f"\n  Most constrained day: {max_day[0]} with {max_day[1]} capacity-hitting timeslots\n")
                
                f.write("\n  ➡️ Room capacity constraint was ACTIVELY LIMITING the schedule\n\n")
            else:
                f.write("✅ NO TIMESLOTS HIT ROOM CAPACITY LIMIT\n\n")
            
            # Timeslots near capacity
            near_capacity_slots = room_capacity['near_capacity_slots']
            if near_capacity_slots:
                f.write("TIMESLOTS APPROACHING ROOM CAPACITY (≥80%):\n")
                for slot in near_capacity_slots:
                    detection_method = slot.get('detection_method', 'unknown')
                    group_count = slot.get('group_count', 0)
                    room_count = slot.get('room_count', 0)
                    effective_ratio = slot.get('effective_ratio', slot.get('room_ratio', 0))
                    f.write(f"  {slot['timeslot']}: {room_count} rooms used, {group_count} groups scheduled\n")
                    f.write(f"    ({effective_ratio:.1%} of {slot['total_rooms']} rooms - detected by {detection_method})\n")
                f.write("\n")
            
            # Constraint effectiveness summary
            if capacity_hit_slots:
                f.write("⚠️ ROOM CAPACITY CONSTRAINT WAS LIMITING: Some timeslots used all available rooms\n\n")
            elif near_capacity_slots:
                f.write("⚠️ ROOM CAPACITY CONSTRAINT NEARLY LIMITING: Some timeslots approached room capacity\n\n")
            else:
                f.write("✅ ROOM CAPACITY CONSTRAINT NOT LIMITING: All timeslots had sufficient room capacity\n\n")
            
            # Room utilization
            f.write("ROOM UTILIZATION:\n")
            f.write("-" * 20 + "\n")
            sorted_rooms = sorted(verification_result['room_usage_stats'].items(), 
                                key=lambda x: x[1]['usage_count'], reverse=True)
            
            for room_id, usage_info in sorted_rooms:
                utilization_pct = (usage_info['usage_count'] / verification_result['total_assignments']) * 100
                f.write(f"Room {usage_info['room_number']}: {usage_info['usage_count']} assignments ({utilization_pct:.1f}%)\n")
                f.write(f"  Courses: {usage_info['unique_courses']}, Teachers: {usage_info['unique_teachers']}\n")
                f.write(f"  Capacity: {usage_info['capacity']}, Type: {usage_info['room_type']}\n\n")
        
        self.logger.info(f"Room verification report saved to: {output_path}")
    
    def get_room_conflicts_summary(self, schedule_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get a quick summary of room conflicts and capacity constraints for external use.
        
        Args:
            schedule_result: Dictionary containing schedule data
            
        Returns:
            Summary dictionary with conflict and capacity information
        """
        verification_result = self.verify_room_distribution_and_overlaps(schedule_result)
        
        # Extract room capacity constraint information
        room_capacity = verification_result['room_capacity_verification']
        capacity_hit_slots = room_capacity.get('capacity_hit_slots', [])
        near_capacity_slots = room_capacity.get('near_capacity_slots', [])
        
        return {
            'has_conflicts': verification_result['conflicts_detected'],
            'conflict_count': verification_result['conflict_count'],
            'total_assignments': verification_result['total_assignments'],
            'rooms_used': verification_result['rooms_used'],
            'verification_passed': verification_result['verification_passed'],
            'utilization_efficiency': verification_result['rooms_used'] / max(1, verification_result['total_assignments']) * 100,
            # Room capacity constraint information
            'room_capacity': {
                'total_rooms_available': room_capacity['total_rooms_available'],
                'max_groups_in_any_timeslot': room_capacity['max_groups_in_any_timeslot'],
                'capacity_hit_ratio': room_capacity['capacity_hit_ratio'],
                'capacity_hit_slots_count': len(capacity_hit_slots),
                'near_capacity_slots_count': len(near_capacity_slots),
                'constraint_was_limiting': room_capacity['constraint_active'],
                'constraint_nearly_limiting': room_capacity['constraint_nearly_active']
            }
        }
    
    def _verify_room_capacity_constraints(self, schedule_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Verify room capacity constraints to check which timeslots hit or approach room capacity limits.
        
        This analysis checks for timeslots where the number of concurrent groups approaches
        or hits the maximum available room capacity, helping identify when the global room
        capacity constraint is actually limiting the schedule.
        
        Args:
            schedule_data: List of schedule assignments
            
        Returns:
            Dictionary with room capacity verification results
        """
        # First, count unique rooms in the schedule to determine total available rooms
        all_unique_rooms = set(item['room_id'] for item in schedule_data)
        total_rooms_available = len(all_unique_rooms)
        
        # Two tracking approaches:
        # 1. Track by groups per timeslot (for group-based constraint)
        timeslot_group_counts = {}
        timeslot_to_groups = {}
        
        # 2. Track by actual room usage per timeslot (for actual utilization)
        timeslot_room_usage = {}
        
        # Count both groups and room usage per timeslot
        for item in schedule_data:
            day = item['day']
            slot_index = item['slot_index']
            time_interval = item['time_interval']
            group_name = item.get('group_name', 'Unassigned')
            room_id = item['room_id']
            
            # Handle only integer slot indexes (theory slots)
            if not isinstance(slot_index, int):
                continue
                
            # Create unique key for day + slot
            timeslot_key = f"{day}_slot_{slot_index}_{time_interval}"
            
            # Track groups per timeslot
            if timeslot_key not in timeslot_to_groups:
                timeslot_to_groups[timeslot_key] = set()
            timeslot_to_groups[timeslot_key].add(group_name)
            
            # Track room usage per timeslot (actual utilization)
            if timeslot_key not in timeslot_room_usage:
                timeslot_room_usage[timeslot_key] = set()
            timeslot_room_usage[timeslot_key].add(room_id)
        
        # Count groups per timeslot
        for timeslot, groups in timeslot_to_groups.items():
            group_count = len(groups)
            timeslot_group_counts[timeslot] = group_count
        
        # Find timeslots that hit or approach capacity
        capacity_hit_slots = []
        near_capacity_slots = []
        low_usage_slots = []
        
        # Track room usage-based capacity (actual room usage)
        room_usage_capacity_hits = []
        
        # First check actual room usage (more accurate measure of capacity)
        for timeslot, used_rooms in timeslot_room_usage.items():
            room_count = len(used_rooms)
            room_capacity_ratio = room_count / total_rooms_available
            
            # If all rooms are used in a timeslot
            if room_count == total_rooms_available:
                room_usage_capacity_hits.append({
                    'timeslot': timeslot,
                    'room_count': room_count,
                    'total_rooms': total_rooms_available,
                    'usage_ratio': 1.0,
                    'detection_method': 'room_usage'
                })
        
        # Then check group-based capacity (theoretical constraint limit)
        for timeslot, group_count in timeslot_group_counts.items():
            capacity_ratio = group_count / total_rooms_available
            
            # Also get the actual room count for this timeslot
            room_count = len(timeslot_room_usage.get(timeslot, set()))
            room_ratio = room_count / total_rooms_available
            
            # Use the higher ratio for detection (more restrictive of the two)
            effective_ratio = max(capacity_ratio, room_ratio)
            effective_count = max(group_count, room_count)
            
            detection_info = {
                'timeslot': timeslot,
                'group_count': group_count,
                'room_count': room_count,
                'total_rooms': total_rooms_available,
                'group_ratio': capacity_ratio,
                'room_ratio': room_ratio,
                'effective_ratio': effective_ratio,
                'detection_method': 'room_usage' if room_ratio > capacity_ratio else 'group_count'
            }
            
            if effective_count == total_rooms_available:
                capacity_hit_slots.append(detection_info)
            elif effective_ratio >= 0.8:
                near_capacity_slots.append(detection_info)
            elif effective_ratio <= 0.2:
                low_usage_slots.append(detection_info)
        
        # Add any room usage hits that weren't caught by the group approach
        for hit in room_usage_capacity_hits:
            if not any(slot['timeslot'] == hit['timeslot'] for slot in capacity_hit_slots):
                capacity_hit_slots.append(hit)
        
        # Sort results by room/group count (descending)
        capacity_hit_slots.sort(key=lambda x: x.get('room_count', 0), reverse=True)
        near_capacity_slots.sort(key=lambda x: x.get('room_count', 0), reverse=True)
        low_usage_slots.sort(key=lambda x: x.get('room_count', 0), reverse=True)
        
        # Get the overall maximum utilization in any timeslot
        max_groups_in_any_timeslot = max(timeslot_group_counts.values()) if timeslot_group_counts else 0
        max_rooms_in_any_timeslot = max(len(rooms) for rooms in timeslot_room_usage.values()) if timeslot_room_usage else 0
        max_utilization = max(max_groups_in_any_timeslot, max_rooms_in_any_timeslot)
        
        return {
            'total_rooms_available': total_rooms_available,
            'max_groups_in_any_timeslot': max_groups_in_any_timeslot,
            'max_rooms_in_any_timeslot': max_rooms_in_any_timeslot,
            'max_utilization': max_utilization,
            'capacity_hit_ratio': max_utilization / total_rooms_available if total_rooms_available > 0 else 0,
            'capacity_hit_slots': capacity_hit_slots,
            'near_capacity_slots': near_capacity_slots,
            'low_usage_slots': low_usage_slots,
            'all_timeslot_group_counts': timeslot_group_counts,
            'all_timeslot_room_usage': {k: len(v) for k, v in timeslot_room_usage.items()},
            'constraint_active': len(capacity_hit_slots) > 0,
            'constraint_nearly_active': len(near_capacity_slots) > 0
        }
    
    def _print_room_capacity_verification(self, room_capacity_verification: Dict[str, Any]) -> None:
        """
        Print room capacity verification results.
        
        Args:
            room_capacity_verification: Results from _verify_room_capacity_constraints
        """
        self.logger.info("\nROOM CAPACITY CONSTRAINT VERIFICATION:")
        self.logger.info("=" * 45)
        
        total_rooms = room_capacity_verification['total_rooms_available']
        max_groups = room_capacity_verification['max_groups_in_any_timeslot']
        max_rooms = room_capacity_verification['max_rooms_in_any_timeslot']
        capacity_ratio = room_capacity_verification['capacity_hit_ratio']
        
        self.logger.info(f"Total unique rooms available: {total_rooms}")
        self.logger.info(f"Maximum groups in any timeslot: {max_groups}")
        self.logger.info(f"Maximum rooms used in any timeslot: {max_rooms} ({capacity_ratio:.1%} of capacity)")
        
        # Report timeslots that hit capacity
        capacity_hit_slots = room_capacity_verification['capacity_hit_slots']
        if capacity_hit_slots:
            self.logger.info("\n🔴 TIMESLOTS THAT HIT ROOM CAPACITY LIMIT:")
            for slot in capacity_hit_slots[:5]:  # Show top 5
                detection_method = slot.get('detection_method', 'unknown')
                group_count = slot.get('group_count', 0)
                room_count = slot.get('room_count', 0)
                self.logger.info(f"  {slot['timeslot']}: {room_count} rooms used, {group_count} groups scheduled")
                self.logger.info(f"    (100% of {slot['total_rooms']} rooms - detected by {detection_method})")
            
            if len(capacity_hit_slots) > 5:
                self.logger.info(f"  ... and {len(capacity_hit_slots) - 5} more slots at capacity")
                
            self.logger.info(f"  ➡️ Room capacity constraint was ACTIVELY LIMITING the schedule")
        else:
            self.logger.info("\n✅ NO TIMESLOTS HIT ROOM CAPACITY LIMIT")
        
        # Report timeslots near capacity
        near_capacity_slots = room_capacity_verification['near_capacity_slots']
        if near_capacity_slots:
            self.logger.info("\n🟠 TIMESLOTS APPROACHING ROOM CAPACITY (≥80%):")
            for slot in near_capacity_slots[:5]:  # Show top 5
                detection_method = slot.get('detection_method', 'unknown')
                group_count = slot.get('group_count', 0)
                room_count = slot.get('room_count', 0)
                effective_ratio = slot.get('effective_ratio', slot.get('room_ratio', 0))
                self.logger.info(f"  {slot['timeslot']}: {room_count} rooms used, {group_count} groups scheduled")
                self.logger.info(f"    ({effective_ratio:.1%} of {slot['total_rooms']} rooms - detected by {detection_method})")
            
            if len(near_capacity_slots) > 5:
                self.logger.info(f"  ... and {len(near_capacity_slots) - 5} more slots approaching capacity")
        else:
            self.logger.info("\n✅ NO TIMESLOTS APPROACHING ROOM CAPACITY")
        
        # Report low usage timeslots
        low_usage_slots = room_capacity_verification['low_usage_slots']
        if low_usage_slots:
            self.logger.info("\n🟢 TIMESLOTS WITH LOW ROOM USAGE (≤20%):")
            for slot in low_usage_slots[:5]:  # Show top 5
                group_count = slot.get('group_count', 0)
                room_count = slot.get('room_count', 0)
                effective_ratio = slot.get('effective_ratio', slot.get('room_ratio', 0))
                self.logger.info(f"  {slot['timeslot']}: {room_count} rooms used ({effective_ratio:.1%} of {slot['total_rooms']} rooms)")
            
            if len(low_usage_slots) > 5:
                self.logger.info(f"  ... and {len(low_usage_slots) - 5} more slots with low usage")
        
        # Constraint effectiveness summary
        if capacity_hit_slots:
            self.logger.info("\n⚠️ ROOM CAPACITY CONSTRAINT WAS LIMITING: Some timeslots used all available rooms")
            # Show which day had the most capacity hits
            day_counts = {}
            for slot in capacity_hit_slots:
                day = slot['timeslot'].split('_')[0]  # Extract day from timeslot key
                day_counts[day] = day_counts.get(day, 0) + 1
            
            if day_counts:
                max_day = max(day_counts.items(), key=lambda x: x[1])
                self.logger.info(f"   Most constrained day: {max_day[0]} with {max_day[1]} capacity-hitting timeslots")
        elif near_capacity_slots:
            self.logger.info("\n⚠️ ROOM CAPACITY CONSTRAINT NEARLY LIMITING: Some timeslots approached room capacity")
        else:
            self.logger.info("\n✅ ROOM CAPACITY CONSTRAINT NOT LIMITING: All timeslots had sufficient room capacity") 