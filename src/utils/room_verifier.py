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
        
        # 4. Print comprehensive verification results
        self._print_verification_results(conflicts, room_usage_stats, timeslot_distribution, schedule_data)
        
        return {
            'conflicts_detected': len(conflicts) > 0,
            'conflict_count': len(conflicts),
            'conflicts': conflicts,
            'room_usage_stats': room_usage_stats,
            'timeslot_distribution': timeslot_distribution,
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
        Get a quick summary of room conflicts for external use.
        
        Args:
            schedule_result: Dictionary containing schedule data
            
        Returns:
            Summary dictionary with conflict information
        """
        verification_result = self.verify_room_distribution_and_overlaps(schedule_result)
        
        return {
            'has_conflicts': verification_result['conflicts_detected'],
            'conflict_count': verification_result['conflict_count'],
            'total_assignments': verification_result['total_assignments'],
            'rooms_used': verification_result['rooms_used'],
            'verification_passed': verification_result['verification_passed'],
            'utilization_efficiency': verification_result['rooms_used'] / max(1, verification_result['total_assignments']) * 100
        } 