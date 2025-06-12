"""
Optimized Teacher Overlap Verification System

This module provides comprehensive verification of teacher schedules to detect:
- Teacher double-booking conflicts
- Room allocation conflicts  
- Lab scheduling overlaps
- Cross-schedule conflicts between different schedule types

OPTIMIZED: Improved performance, better code organization, and enhanced reporting.
"""

import pandas as pd
import os
from collections import defaultdict, Counter
from datetime import datetime
from typing import List, Dict, Tuple, Optional, Set
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TimeRange:
    """Utility class for handling time range operations."""
    
    def __init__(self, time_str: str):
        """Initialize with time range string like '11:00 - 11:50'."""
        self.time_str = time_str
        self.start_minutes, self.end_minutes = self._parse_time_range(time_str)
    
    def _parse_time_range(self, time_str: str) -> Tuple[int, int]:
        """Parse time range string to start and end minutes since midnight."""
        try:
            if ' - ' in time_str:
                start_str, end_str = time_str.split(' - ')
                start_minutes = self._time_to_minutes(start_str.strip())
                end_minutes = self._time_to_minutes(end_str.strip())
                return start_minutes, end_minutes
            else:
                # Single time point, assume 50-minute duration
                start_minutes = self._time_to_minutes(time_str.strip())
                return start_minutes, start_minutes + 50
        except (ValueError, AttributeError) as e:
            logger.warning(f"Failed to parse time range '{time_str}': {e}")
            return 0, 0
    
    def _time_to_minutes(self, time_str: str) -> int:
        """Convert time string like '11:00' to minutes since midnight."""
        hours, minutes = map(int, time_str.split(':'))
        return hours * 60 + minutes

    def overlaps_with(self, other: 'TimeRange') -> bool:
        """Check if this time range overlaps with another."""
        return self.start_minutes < other.end_minutes and other.start_minutes < self.end_minutes
    
    def __str__(self) -> str:
        return self.time_str

class ScheduleFile:
    """Utility class for managing schedule file discovery and loading."""
    
    @staticmethod
    def find_latest_schedule_files() -> Dict[str, Optional[str]]:
        """Find the most recent schedule files of different types."""
        output_dir = "output"
        files = {'combined': None, 'theory_only': None, 'lab_only': None}
        
        if not os.path.exists(output_dir):
            return files
        
        try:
            # Find combined schedules (lab + theory)
            lab_folders = [f for f in os.listdir(output_dir) if f.startswith("lab_schedule_")]
            if lab_folders:
                latest_lab_folder = max(lab_folders)
                combined_file = os.path.join(output_dir, latest_lab_folder, "combined_theory_lab_schedule.csv")
                if os.path.exists(combined_file):
                    files['combined'] = combined_file
    
            # Find theory-only schedules
            theory_folders = [f for f in os.listdir(output_dir) if f.startswith("macroblock_schedule_")]
            if theory_folders:
                latest_theory_folder = max(theory_folders)
                theory_file = os.path.join(output_dir, latest_theory_folder, "macroblock_schedule.csv")
                if os.path.exists(theory_file):
                    files['theory_only'] = theory_file
            
            # Find newest schedule (prioritize combined schedules)
            newest_folder = None
            all_folders = [f for f in os.listdir(output_dir) if f.startswith(("schedule_", "lab_schedule_", "macroblock_schedule_"))]
            if all_folders:
                newest_folder = max(all_folders)
                newest_file = os.path.join(output_dir, newest_folder, "schedule.csv")
                if os.path.exists(newest_file):
                    files['newest'] = newest_file
                    
        except Exception as e:
            logger.error(f"Error finding schedule files: {e}")
        
        return files
    
    @staticmethod
    def load_schedule(file_path: str) -> Optional[pd.DataFrame]:
        """Load and validate a schedule file."""
        try:
            if not os.path.exists(file_path):
                logger.error(f"Schedule file not found: {file_path}")
                return None
            
            df = pd.read_csv(file_path)
            
            # Validate required columns
            required_columns = ['teacher_id', 'day', 'slot_index', 'time_interval', 'room_id', 'course_code']
            missing_columns = [col for col in required_columns if col not in df.columns]
            
            if missing_columns:
                logger.error(f"Missing required columns in {file_path}: {missing_columns}")
                return None
            
            if df.empty:
                logger.warning(f"Schedule file is empty: {file_path}")
                return None
            
            logger.info(f"Successfully loaded {len(df)} assignments from {file_path}")
            return df
            
        except Exception as e:
            logger.error(f"Error loading schedule file {file_path}: {e}")
            return None

class ConflictDetector:
    """Optimized conflict detection for teacher and room scheduling."""
    
    def __init__(self, schedule_df: pd.DataFrame):
        """Initialize with schedule data."""
        self.schedule_df = schedule_df
        self.conflicts = {
            'teacher_overlaps': [],
            'room_conflicts': [],
            'lab_overlaps': [],
            'capacity_violations': [],
            'cross_schedule_conflicts': []
        }
        
        # Pre-build efficient lookup structures
        self._build_lookup_structures()
    
    def _build_lookup_structures(self):
        """Build efficient lookup structures for conflict detection."""
        # Teacher schedule lookup: {teacher_id: {(day, slot_index): [assignments]}}
        self.teacher_schedule = defaultdict(lambda: defaultdict(list))
        
        # Room schedule lookup: {room_id: {(day, slot_index): [assignments]}}
        self.room_schedule = defaultdict(lambda: defaultdict(list))
        
        # Time-based lookup for cross-schedule conflicts
        self.time_assignments = defaultdict(list)  # {(day, time_range): [assignments]}
        
        for _, row in self.schedule_df.iterrows():
            teacher_id = row['teacher_id']
            room_id = row['room_id']
            day = row['day']
            slot_index = row['slot_index']
            time_interval = row['time_interval']
            
            # Create assignment info
            assignment = {
                'teacher_id': teacher_id,
                'room_id': room_id,
                'course_code': row['course_code'],
                'course_name': row.get('course_name', ''),
                'room_number': row.get('room_number', ''),
                'slot_type': row.get('slot_type', ''),
                'time_interval': time_interval,
                'course_instance_id': row.get('course_instance_id', ''),
                'lab_session': row.get('lab_session', ''),
                'macroblock': row.get('macroblock', ''),
                'student_count': row.get('student_count', 0),
                'practical_hours': row.get('practical_hours', 0),
                'room_capacity': row.get('room_capacity', 0)
            }
            
            # Build lookup structures
            time_key = (day, slot_index)
            self.teacher_schedule[teacher_id][time_key].append(assignment)
            self.room_schedule[room_id][time_key].append(assignment)
            self.time_assignments[(day, time_interval)].append(assignment)
    
    def detect_teacher_overlaps(self) -> List[Dict]:
        """Detect teacher double-booking conflicts efficiently."""
        logger.info("Detecting teacher overlap conflicts...")
        
        teacher_conflicts = []
        
        for teacher_id, teacher_slots in self.teacher_schedule.items():
            for time_key, assignments in teacher_slots.items():
                if len(assignments) > 1:
                    # Teacher has multiple assignments at the same time
                    day, slot_index = time_key
                    conflict = {
                        'type': 'teacher_overlap',
                        'teacher_id': teacher_id,
                        'day': day,
                        'slot_index': slot_index,
                        'time_interval': assignments[0]['time_interval'],
                        'assignments': assignments,
                        'conflict_count': len(assignments)
                    }
                    teacher_conflicts.append(conflict)
        
        self.conflicts['teacher_overlaps'] = teacher_conflicts
        logger.info(f"Found {len(teacher_conflicts)} teacher overlap conflicts")
        return teacher_conflicts
    
    def detect_room_conflicts(self) -> List[Dict]:
        """Detect room double-booking conflicts efficiently."""
        logger.info("Detecting room allocation conflicts...")
        
        room_conflicts = []
        
        for room_id, room_slots in self.room_schedule.items():
            for time_key, assignments in room_slots.items():
                if len(assignments) > 1:
                    # Check if different teachers are using the same room
                    teachers_in_room = set(assignment['teacher_id'] for assignment in assignments)
                    if len(teachers_in_room) > 1:
                        day, slot_index = time_key
                        conflict = {
                            'type': 'room_conflict',
                            'room_id': room_id,
                            'room_number': assignments[0]['room_number'],
                            'day': day,
                            'slot_index': slot_index,
                            'time_interval': assignments[0]['time_interval'],
                            'assignments': assignments,
                            'teachers': list(teachers_in_room)
                        }
                        room_conflicts.append(conflict)
        
        self.conflicts['room_conflicts'] = room_conflicts
        logger.info(f"Found {len(room_conflicts)} room allocation conflicts")
        return room_conflicts
    
    def detect_lab_overlaps(self) -> List[Dict]:
        """Detect lab-specific conflicts and capacity violations."""
        logger.info("Detecting lab scheduling conflicts...")
        
        lab_assignments = self.schedule_df[self.schedule_df['slot_type'] == 'Practical'].copy() if 'slot_type' in self.schedule_df.columns else pd.DataFrame()
        
        if lab_assignments.empty:
            logger.info("No lab assignments found")
            return []
        
        lab_conflicts = []
        
        # Detect time-based lab overlaps using improved time parsing
        for assignments_list in self.time_assignments.values():
            lab_assigns = [a for a in assignments_list if a['slot_type'] == 'Practical']
            if len(lab_assigns) > 1:
                # Check for teacher overlaps in labs
                teacher_assignments = defaultdict(list)
                for assignment in lab_assigns:
                    teacher_assignments[assignment['teacher_id']].append(assignment)
                
                for teacher, assignments in teacher_assignments.items():
                    if len(assignments) > 1:
                        # Same teacher in multiple labs at same time
                        conflict = {
                            'type': 'lab_teacher_overlap',
                            'teacher_id': teacher,
                            'day': assignments[0].get('day', ''),
                            'time_interval': assignments[0].get('time_interval', ''),
                            'assignments': assignments,
                            'conflict_count': len(assignments)
                        }
                        lab_conflicts.append(conflict)
        
        # Detect capacity constraint violations with improved logic
        capacity_violations = []
        for _, lab in lab_assignments.iterrows():
            practical_hours = lab.get('practical_hours', 0)
            room_capacity = lab.get('capacity', lab.get('room_capacity', 0))
            student_count = lab.get('student_count', 70)
            
            # Convert to numeric if needed
            try:
                practical_hours = float(practical_hours) if practical_hours else 0
                room_capacity = float(room_capacity) if room_capacity else 0
                student_count = float(student_count) if student_count else 70
            except (ValueError, TypeError):
                logger.warning(f"Invalid numeric values in lab assignment: {lab.get('course_code', 'Unknown')}")
                continue
            
            # Hard constraint: courses with <3 practical hours should use ≤35 capacity labs
            if student_count >= 70 and practical_hours < 3 and room_capacity > 35:
                violation = {
                    'type': 'capacity_violation',
                    'course_code': lab.get('course_code', ''),
                    'teacher_id': lab['teacher_id'],
                    'practical_hours': practical_hours,
                    'room_capacity': room_capacity,
                    'student_count': student_count,
                    'room_number': lab.get('room_number', ''),
                    'violation_rule': f"{practical_hours}h course (70 students) in {room_capacity}-capacity lab (should be ≤35)"
                }
                capacity_violations.append(violation)
            
            # Additional check: very high capacity utilization
            if room_capacity > 0:
                utilization = (student_count / room_capacity) * 100
                if utilization > 100:
                    violation = {
                        'type': 'overcapacity_violation',
                        'course_code': lab.get('course_code', ''),
                        'teacher_id': lab['teacher_id'],
                        'student_count': student_count,
                        'room_capacity': room_capacity,
                        'utilization_percent': utilization,
                        'room_number': lab.get('room_number', ''),
                        'violation_rule': f"{student_count} students in {room_capacity}-capacity lab ({utilization:.1f}% utilization)"
                    }
                    capacity_violations.append(violation)
        
        self.conflicts['lab_overlaps'] = lab_conflicts
        self.conflicts['capacity_violations'] = capacity_violations
        
        logger.info(f"Found {len(lab_conflicts)} lab overlaps and {len(capacity_violations)} capacity violations")
        return lab_conflicts + capacity_violations
    
    def detect_cross_schedule_conflicts(self, other_schedule_file: str) -> List[Dict]:
        """Detect conflicts between current schedule and another schedule file."""
        logger.info(f"Detecting cross-schedule conflicts with {other_schedule_file}")
        
        other_df = ScheduleFile.load_schedule(other_schedule_file)
        if other_df is None:
            return []
        
        cross_conflicts = []
        
        # Compare assignments by teacher and time overlap
        for _, assignment1 in self.schedule_df.iterrows():
            teacher_id = assignment1['teacher_id']
            day1 = assignment1['day']
            time1 = TimeRange(assignment1['time_interval'])
            
            # Find overlapping assignments for the same teacher in other schedule
            other_teacher_assigns = other_df[other_df['teacher_id'] == teacher_id]
            
            for _, assignment2 in other_teacher_assigns.iterrows():
                day2 = assignment2['day']
                if day1 == day2:
                    time2 = TimeRange(assignment2['time_interval'])
                    
                    if time1.overlaps_with(time2):
                        conflict = {
                            'type': 'cross_schedule_conflict',
                            'teacher_id': teacher_id,
                            'day': day1,
                            'schedule1_course': assignment1['course_code'],
                            'schedule1_time': str(time1),
                            'schedule1_room': assignment1.get('room_number', ''),
                            'schedule2_course': assignment2['course_code'],
                            'schedule2_time': str(time2),
                            'schedule2_room': assignment2.get('room_number', ''),
                        }
                        cross_conflicts.append(conflict)
        
        self.conflicts['cross_schedule_conflicts'] = cross_conflicts
        logger.info(f"Found {len(cross_conflicts)} cross-schedule conflicts")
        return cross_conflicts
    
    def detect_all_conflicts(self) -> Dict[str, List[Dict]]:
        """Run all conflict detection methods."""
        logger.info("Running comprehensive conflict detection...")
        
        self.detect_teacher_overlaps()
        self.detect_room_conflicts()
        self.detect_lab_overlaps()
        
        return self.conflicts

class ReportGenerator:
    """Generate comprehensive verification reports."""
    
    def __init__(self, conflicts: Dict[str, List[Dict]], schedule_df: pd.DataFrame):
        """Initialize with conflict data and schedule."""
        self.conflicts = conflicts
        self.schedule_df = schedule_df
    
    def generate_summary_report(self) -> str:
        """Generate a summary report of all conflicts."""
        total_conflicts = sum(len(conflicts) for conflicts in self.conflicts.values())
        
        report = []
        report.append("=" * 80)
        report.append("📊 COMPREHENSIVE SCHEDULE VERIFICATION REPORT")
        report.append("=" * 80)
        report.append(f"📅 Analysis timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append(f"📈 Total assignments analyzed: {len(self.schedule_df)}")
        report.append(f"👥 Teachers: {self.schedule_df['teacher_id'].nunique()}")
        report.append(f"🏫 Rooms: {self.schedule_df['room_id'].nunique()}")
        report.append(f"📚 Courses: {self.schedule_df['course_code'].nunique()}")
        
        # Add schedule type breakdown
        if 'slot_type' in self.schedule_df.columns:
            slot_types = self.schedule_df['slot_type'].value_counts()
            report.append(f"📋 Schedule breakdown:")
            for slot_type, count in slot_types.items():
                report.append(f"   {slot_type}: {count} assignments")
        
        report.append("")
        
        # Conflict summary
        report.append("🎯 CONFLICT ANALYSIS RESULTS:")
        report.append(f"   Teacher overlaps: {len(self.conflicts['teacher_overlaps'])}")
        report.append(f"   Room conflicts: {len(self.conflicts['room_conflicts'])}")
        report.append(f"   Lab overlaps: {len(self.conflicts['lab_overlaps'])}")
        report.append(f"   Capacity violations: {len(self.conflicts['capacity_violations'])}")
        report.append(f"   Cross-schedule conflicts: {len(self.conflicts['cross_schedule_conflicts'])}")
        report.append(f"   TOTAL CONFLICTS: {total_conflicts}")
        report.append("")
        
        if total_conflicts == 0:
            report.append("🎉 VERIFICATION PASSED: No conflicts detected!")
            report.append("✅ Schedule is feasible and conflict-free")
        else:
            report.append(f"⚠️  VERIFICATION FAILED: {total_conflicts} conflicts require resolution!")
            
            # Add recommendations based on conflict types
            if self.conflicts['teacher_overlaps']:
                report.append("   📌 Teacher overlaps detected - check constraint logic")
            if self.conflicts['room_conflicts']:
                report.append("   📌 Room conflicts detected - verify room assignment constraints")
            if self.conflicts['capacity_violations']:
                report.append("   📌 Capacity violations detected - review lab allocation rules")
        
        return "\n".join(report)
    
    def generate_detailed_report(self) -> str:
        """Generate detailed conflict reports."""
        report = [self.generate_summary_report()]
        
        # Teacher overlap details
        if self.conflicts['teacher_overlaps']:
            report.append("\n" + "=" * 80)
            report.append("❌ TEACHER OVERLAP CONFLICTS")
            report.append("=" * 80)
            
            for conflict in self.conflicts['teacher_overlaps']:
                report.append(f"\nTeacher {conflict['teacher_id']} - {conflict['day'].capitalize()} - {conflict['time_interval']}")
                report.append(f"   Conflicting assignments ({conflict['conflict_count']}):")
                
                for i, assignment in enumerate(conflict['assignments'], 1):
                    course = assignment['course_code']
                    room = assignment['room_number']
                    slot_type = assignment['slot_type']
                    report.append(f"   {i}. {course} ({slot_type}) in {room}")
        
        # Room conflict details
        if self.conflicts['room_conflicts']:
            report.append("\n" + "=" * 80)
            report.append("❌ ROOM ALLOCATION CONFLICTS")
            report.append("=" * 80)
            
            for conflict in self.conflicts['room_conflicts']:
                room = conflict['room_number']
                day = conflict['day']
                time = conflict['time_interval']
                teachers = ', '.join(map(str, conflict['teachers']))
                
                report.append(f"\nRoom {room} - {day.capitalize()} - {time}")
                report.append(f"   Multiple teachers assigned: {teachers}")
                
                for assignment in conflict['assignments']:
                    teacher = assignment['teacher_id']
                    course = assignment['course_code']
                    report.append(f"   - Teacher {teacher}: {course}")
        
        # Lab conflict details
        if self.conflicts['lab_overlaps']:
            report.append("\n" + "=" * 80)
            report.append("❌ LAB SCHEDULING CONFLICTS")
            report.append("=" * 80)
            
            for conflict in self.conflicts['lab_overlaps']:
                if conflict['type'] == 'lab_teacher_overlap':
                    teacher = conflict['teacher_id']
                    report.append(f"\nTeacher {teacher} - Lab overlap:")
                    for assignment in conflict['assignments']:
                        course = assignment['course_code']
                        room = assignment['room_number']
                        report.append(f"   - {course} in {room}")
        
        # Capacity violation details
        if self.conflicts['capacity_violations']:
            report.append("\n" + "=" * 80)
            report.append("❌ CAPACITY CONSTRAINT VIOLATIONS")
            report.append("=" * 80)
            
            for violation in self.conflicts['capacity_violations']:
                course = violation['course_code']
                teacher = violation['teacher_id']
                rule = violation['violation_rule']
                room = violation['room_number']
                
                report.append(f"\n{course} (Teacher {teacher}) in {room}")
                report.append(f"   Violation: {rule}")
        
        return "\n".join(report)

class OptimizedTeacherOverlapVerifier:
    """Main class for optimized teacher overlap verification."""
    
    def __init__(self):
        """Initialize the verifier."""
        self.schedule_files = ScheduleFile.find_latest_schedule_files()
        self.primary_schedule = None
        self.conflicts_detected = {}
    
    def verify_schedules(self) -> bool:
        """Run comprehensive schedule verification."""
        logger.info("Starting optimized schedule verification...")
        
        # Find and load primary schedule
        primary_file = self._get_primary_schedule_file()
        if not primary_file:
            logger.error("No valid schedule files found for verification")
            return False
        
        self.primary_schedule = ScheduleFile.load_schedule(primary_file)
        if self.primary_schedule is None:
            logger.error(f"Failed to load primary schedule from {primary_file}")
            return False
        
        logger.info(f"Primary schedule loaded: {primary_file}")
        
        # Run conflict detection
        detector = ConflictDetector(self.primary_schedule)
        self.conflicts_detected = detector.detect_all_conflicts()
        
        # Check for cross-schedule conflicts if multiple files exist
        if self.schedule_files['theory_only'] and self.schedule_files['combined']:
            detector.detect_cross_schedule_conflicts(self.schedule_files['theory_only'])
        
        # Generate and display reports
        reporter = ReportGenerator(self.conflicts_detected, self.primary_schedule)
        
        print(reporter.generate_detailed_report())
        
        # Determine verification result
        total_conflicts = sum(len(conflicts) for conflicts in self.conflicts_detected.values())
        success = total_conflicts == 0
        
        if success:
            logger.info("✅ Schedule verification PASSED")
        else:
            logger.warning(f"❌ Schedule verification FAILED - {total_conflicts} conflicts detected")
        
        return success
    
    def _get_primary_schedule_file(self) -> Optional[str]:
        """Get the primary schedule file for verification."""
        # Priority order: newest > combined > theory_only
        for file_type in ['newest', 'combined', 'theory_only']:
            if self.schedule_files.get(file_type):
                return self.schedule_files[file_type]
        return None

def verify_teacher_overlap() -> bool:
    """Main function for teacher overlap verification."""
    try:
        verifier = OptimizedTeacherOverlapVerifier()
        return verifier.verify_schedules()
    except Exception as e:
        logger.error(f"Error during verification: {e}")
        logger.exception("Verification error details")
        return False

def main():
    """Main entry point."""
    # Change to correct directory if needed
    if os.path.exists("timetable_scheduler"):
        os.chdir("timetable_scheduler")
    
    print("🔍 OPTIMIZED TEACHER OVERLAP VERIFICATION SYSTEM")
    print("=" * 60)
    
    success = verify_teacher_overlap()
    
    if success:
        print("\n✅ Teacher overlap verification completed successfully!")
    else:
        print("\n❌ Teacher overlap verification found conflicts!")
    
    return success

if __name__ == "__main__":
    main() 