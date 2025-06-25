#!/usr/bin/env python3
"""
Comprehensive Schedule Verification Script

This script verifies the generated schedules for:
1. Room double bookings
2. Teacher time conflicts  
3. LTP (Lecture-Tutorial-Practical) requirements verification
4. Cross-schedule conflicts between lab and theory

Updated to understand batching logic from combined_scheduler.py:
- Batched courses split student groups into smaller batches for lab capacity
- Student group overlaps in batched courses are EXPECTED behavior, not conflicts
- Focus on actual conflicts: room double-booking, teacher time conflicts

Usage: python verify_schedule.py [schedule_directory]
"""

import os
import sys
import pandas as pd
import numpy as np
from collections import defaultdict, Counter
import json
from datetime import datetime
import argparse

# Add src to path for imports
sys.path.append('src')

class ScheduleVerifier:
    def __init__(self, schedule_dir):
        """Initialize the schedule verifier."""
        self.schedule_dir = schedule_dir
        self.lab_schedule_path = os.path.join(schedule_dir, 'combined_lab_schedule.csv')
        self.theory_schedule_path = os.path.join(schedule_dir, 'combined_theory_schedule.csv')
        
        # Load schedules
        self.lab_schedule = self._load_schedule(self.lab_schedule_path, 'lab')
        self.theory_schedule = self._load_schedule(self.theory_schedule_path, 'theory')
        
        # Initialize time mapping (from combined_scheduler.py logic)
        self._build_time_mapping()
        
        # Results storage
        self.verification_results = {
            'room_conflicts': [],
            'teacher_conflicts': [],
            'ltp_violations': [],
            'cross_schedule_conflicts': [],
            'summary': {}
        }
        
        print(f"📁 Verifying schedules from: {schedule_dir}")
        print(f"📊 Lab sessions: {len(self.lab_schedule) if self.lab_schedule is not None else 0}")
        print(f"📊 Theory sessions: {len(self.theory_schedule) if self.theory_schedule is not None else 0}")
        
    def _build_time_mapping(self):
        """Build time mapping consistent with combined_scheduler.py"""
        # Lab time slots (L1-L6, each 2 hours) - EXACTLY as in combined_scheduler.py
        self.lab_sessions = {
            'L1': ['8:00 - 8:50', '8:50 - 9:40'],      # 8:00 - 9:40
            'L2': ['10:00 - 10:50', '10:50 - 11:40'],   # 10:00 - 11:40  
            'L3': ['11:50 - 12:30', '12:30 - 1:20'],   # 11:50 - 1:20
            'L4': ['1:20 - 2:10', '2:10 - 3:00'],      # 1:20 - 3:00
            'L5': ['3:00 - 3:50', '3:50 - 4:40'],      # 3:00 - 4:40
            'L6': ['5:10 - 6:00', '6:00 - 6:50']       # 5:10 - 6:50
        }
        
        # Theory time slots (11 slots) - EXACTLY as in combined_scheduler.py
        self.theory_slots = [
            "8:00 - 8:50", "9:00 - 9:50", "10:00 - 10:50", "11:00 - 11:50",
            "12:00 - 12:50", "1:00 - 1:50", "2:00 - 2:50", "3:00 - 3:50",
            "4:00 - 4:50", "5:00 - 5:50", "6:00 - 6:50"
        ]
        
    def _load_schedule(self, file_path, schedule_type):
        """Load schedule from CSV file."""
        if not os.path.exists(file_path):
            print(f"⚠️  {schedule_type.title()} schedule file not found: {file_path}")
            return None
        
        try:
            df = pd.read_csv(file_path)
            print(f"✅ Loaded {schedule_type} schedule: {len(df)} sessions")
            return df
        except Exception as e:
            print(f"❌ Error loading {schedule_type} schedule: {e}")
            return None
    
    def _parse_time_to_minutes(self, time_str):
        """Convert time string to minutes since midnight."""
        try:
            if pd.isna(time_str) or time_str == '':
                return None
            
            time_str = str(time_str).strip()
            
            # Handle range format "HH:MM - HH:MM"
            if ' - ' in time_str:
                start_time = time_str.split(' - ')[0].strip()
            else:
                start_time = time_str
            
            # Parse time
            if ':' in start_time:
                hour, minute = start_time.split(':')
                hour = int(hour)
                minute = int(minute)
            else:
                hour = int(start_time)
                minute = 0
            
            # Convert PM times (1:00-7:00 PM becomes 13:00-19:00)
            if 1 <= hour <= 7:
                hour += 12
            
            return hour * 60 + minute
        except:
            return None
    
    def _times_overlap(self, time_range1, time_range2):
        """Check if two time ranges overlap."""
        def parse_range(time_range):
            if ' - ' not in time_range:
                return None, None
            start_str, end_str = time_range.split(' - ')
            start = self._parse_time_to_minutes(start_str.strip())
            end = self._parse_time_to_minutes(end_str.strip())
            return start, end
        
        start1, end1 = parse_range(time_range1)
        start2, end2 = parse_range(time_range2)
        
        if None in [start1, end1, start2, end2]:
            return False
        
        return not (end1 <= start2 or end2 <= start1)
    
    def verify_room_double_bookings(self):
        """Check for room double bookings within and across schedules."""
        print("\n🏢 Verifying Room Double Bookings...")
        
        room_bookings = defaultdict(list)  # (room_id, day, time) -> [sessions]
        
        # Collect lab room bookings
        if self.lab_schedule is not None:
            for _, session in self.lab_schedule.iterrows():
                session_name = session.get('session_name', '')
                lab_time_slots = self.lab_sessions.get(session_name, [])
                
                for time_slot in lab_time_slots:
                    key = (session['room_id'], session['day'], time_slot)
                    room_bookings[key].append({
                        'type': 'lab',
                        'course': session['course_code'],
                        'teacher': session.get('teacher_id', session.get('teacher_name', 'Unknown')),
                        'dept': session.get('department', session.get('dept_name', 'Unknown')),
                        'semester': session.get('semester', 'Unknown'),
                        'session_name': session_name,
                        'time': time_slot,
                        'batch_info': session.get('batch_info', 'N/A'),
                        'is_batched': session.get('is_batched', False)
                    })
        
        # Collect theory room bookings
        if self.theory_schedule is not None:
            for _, session in self.theory_schedule.iterrows():
                time_slot = session.get('time_slot', session.get('time', ''))
                key = (session['room_id'], session['day'], time_slot)
                room_bookings[key].append({
                    'type': 'theory',
                    'course': session['course_code'],
                    'teacher': session.get('teacher_id', session.get('teacher_name', 'Unknown')),
                    'dept': session.get('department', session.get('dept_name', 'Unknown')),
                    'semester': session.get('semester', 'Unknown'),
                    'time': time_slot,
                    'batch_info': 'N/A',
                    'is_batched': False
                })
        
        # Find actual conflicts (same room, same time, different sessions)
        conflicts = []
        for (room_id, day, time), sessions in room_bookings.items():
            if len(sessions) > 1:
                # Check if this is a legitimate conflict
                # Same course with different batches in same room is OK
                unique_courses = set()
                for session in sessions:
                    course_key = f"{session['course']}_{session['batch_info']}"
                    unique_courses.add(course_key)
                
                # Only report as conflict if different courses/batches are using same room
                if len(unique_courses) > 1:
                    conflicts.append({
                        'room_id': room_id,
                        'day': day,
                        'time': time,
                        'sessions': sessions,
                        'conflict_count': len(sessions)
                    })
        
        self.verification_results['room_conflicts'] = conflicts
        
        if conflicts:
            print(f"❌ Found {len(conflicts)} room double booking conflicts:")
            for i, conflict in enumerate(conflicts[:10], 1):  # Show first 10
                print(f"   {i}. Room {conflict['room_id']} on {conflict['day']} at {conflict['time']}:")
                for session in conflict['sessions']:
                    batch_info = f" ({session['batch_info']})" if session['batch_info'] != 'N/A' else ""
                    print(f"      - {session['type'].upper()}: {session['course']}{batch_info} ({session['dept']} S{session['semester']}) - Teacher {session['teacher']}")
            if len(conflicts) > 10:
                print(f"      ... and {len(conflicts) - 10} more conflicts")
        else:
            print("✅ No room double booking conflicts found")
        
        return len(conflicts) == 0
    
    def verify_teacher_conflicts(self):
        """Check for teacher time conflicts within and across schedules."""
        print("\n👨‍🏫 Verifying Teacher Time Conflicts...")
        
        teacher_schedules = defaultdict(list)  # teacher_id -> [sessions]
        
        # Collect lab teacher schedules
        if self.lab_schedule is not None:
            for _, session in self.lab_schedule.iterrows():
                teacher_id = session.get('teacher_id', session.get('teacher_name', 'Unknown'))
                session_name = session.get('session_name', '')
                lab_time_slots = self.lab_sessions.get(session_name, [])
                
                for time_slot in lab_time_slots:
                    teacher_schedules[teacher_id].append({
                        'type': 'lab',
                        'day': session['day'],
                        'time': time_slot,
                        'course': session['course_code'],
                        'room': session['room_id'],
                        'dept': session.get('department', session.get('dept_name', 'Unknown')),
                        'semester': session.get('semester', 'Unknown'),
                        'session_name': session_name,
                        'batch_info': session.get('batch_info', 'N/A')
                    })
        
        # Collect theory teacher schedules
        if self.theory_schedule is not None:
            for _, session in self.theory_schedule.iterrows():
                teacher_id = session.get('teacher_id', session.get('teacher_name', 'Unknown'))
                time_slot = session.get('time_slot', session.get('time', ''))
                teacher_schedules[teacher_id].append({
                    'type': 'theory',
                    'day': session['day'],
                    'time': time_slot,
                    'course': session['course_code'],
                    'room': session['room_id'],
                    'dept': session.get('department', session.get('dept_name', 'Unknown')),
                    'semester': session.get('semester', 'Unknown'),
                    'batch_info': 'N/A'
                })
        
        # Find teacher conflicts using overlap detection
        conflicts = []
        for teacher_id, sessions in teacher_schedules.items():
            # Group sessions by day
            sessions_by_day = defaultdict(list)
            for session in sessions:
                sessions_by_day[session['day']].append(session)
            
            # Check for overlaps within each day
            for day, day_sessions in sessions_by_day.items():
                for i, session1 in enumerate(day_sessions):
                    for j, session2 in enumerate(day_sessions[i+1:], i+1):
                        # Check if times overlap
                        if self._times_overlap(session1['time'], session2['time']):
                            # Skip if same course with different batches (teacher handles both)
                            if (session1['course'] == session2['course'] and 
                                session1['batch_info'] != session2['batch_info'] and
                                session1['batch_info'] != 'N/A' and session2['batch_info'] != 'N/A'):
                                continue
                            
                            conflicts.append({
                                'teacher_id': teacher_id,
                                'day': day,
                                'session1': session1,
                                'session2': session2,
                                'conflict_type': f"{session1['type']}-{session2['type']}"
                            })
        
        self.verification_results['teacher_conflicts'] = conflicts
        
        if conflicts:
            print(f"❌ Found {len(conflicts)} teacher time conflicts:")
            for i, conflict in enumerate(conflicts[:10], 1):  # Show first 10
                print(f"   {i}. Teacher {conflict['teacher_id']} on {conflict['day']}:")
                s1, s2 = conflict['session1'], conflict['session2']
                batch1 = f" ({s1['batch_info']})" if s1['batch_info'] != 'N/A' else ""
                batch2 = f" ({s2['batch_info']})" if s2['batch_info'] != 'N/A' else ""
                print(f"      - {s1['type'].upper()}: {s1['course']}{batch1} at {s1['time']} (Room {s1['room']})")
                print(f"      - {s2['type'].upper()}: {s2['course']}{batch2} at {s2['time']} (Room {s2['room']})")
            if len(conflicts) > 10:
                print(f"      ... and {len(conflicts) - 10} more conflicts")
        else:
            print("✅ No teacher time conflicts found")
        
        return len(conflicts) == 0
    
    def verify_ltp_requirements(self):
        """Verify LTP (Lecture-Tutorial-Practical) requirements for all courses."""
        print("\n📚 Verifying LTP Requirements...")
        print("ℹ️  Note: Using simplified LTP verification - for detailed analysis use verify_lecture_tutorial_hours.py")
        
        # Load course requirements from the course data
        course_requirements = self._load_course_requirements()
        
        # Collect actual allocations by course instance
        course_allocations = defaultdict(lambda: {'L': 0, 'T': 0, 'P': 0, 'instances': set()})
        
        # Count theory sessions (lectures + tutorials)
        if self.theory_schedule is not None:
            for _, session in self.theory_schedule.iterrows():
                course_code = session['course_code']
                instance_id = session.get('course_instance_id', course_code)
                course_allocations[course_code]['L'] += 1
                course_allocations[course_code]['instances'].add(instance_id)
        
        # Count practical sessions (labs)
        if self.lab_schedule is not None:
            for _, session in self.lab_schedule.iterrows():
                course_code = session['course_code']
                instance_id = session.get('course_instance_id', course_code)
                # Each lab session = 2 hours of practical
                course_allocations[course_code]['P'] += 2
                course_allocations[course_code]['instances'].add(instance_id)
        
        # Basic verification - check if courses have some allocation
        violations = []
        
        for course_code, allocation in course_allocations.items():
            issues = []
            
            # Basic checks
            if allocation['L'] == 0 and allocation['P'] == 0:
                issues.append("No sessions scheduled")
            
            # Check if course appears in requirements but has no practical when expected
            if course_code in course_requirements:
                req = course_requirements[course_code]
                if req.get('practical_hours', 0) > 0 and allocation['P'] == 0:
                    issues.append("Missing practical sessions")
                if req.get('lecture_hours', 0) > 0 and allocation['L'] == 0:
                    issues.append("Missing lecture sessions")
            
            if issues:
                violations.append({
                    'course_code': course_code,
                    'issues': issues,
                    'actual': allocation,
                    'instances': len(allocation['instances'])
                })
        
        self.verification_results['ltp_violations'] = violations
        
        if violations:
            print(f"⚠️  Found {len(violations)} potential LTP issues (use dedicated LTP scripts for detailed analysis):")
            for i, violation in enumerate(violations[:10], 1):  # Show first 10
                course = violation['course_code']
                act = violation['actual']
                print(f"   {i}. {course} ({violation['instances']} instances):")
                print(f"      Scheduled: L={act['L']}, P={act['P']} hours")
                for issue in violation['issues']:
                    print(f"      ⚠️  {issue}")
            if len(violations) > 10:
                print(f"      ... and {len(violations) - 10} more issues")
        else:
            print("✅ Basic LTP requirements check passed")
        
        return len(violations) == 0
    
    def _load_course_requirements(self):
        """Load course LTP requirements from course data."""
        course_requirements = {}
        
        # Try to load from the main course data file
        possible_files = [
            'data/department_data/final_computing.csv',
            'data/courses.csv',
            'data/extracted_courses.csv',
            'data/course_details_by_student_dept_combined.csv'
        ]
        
        for file_path in possible_files:
            if os.path.exists(file_path):
                try:
                    df = pd.read_csv(file_path)
                    print(f"📖 Loading course requirements from: {file_path}")
                    
                    # Look for course requirements columns
                    for _, row in df.iterrows():
                        course_code = str(row.get('course_code', row.get('course_id', '')))
                        if course_code:
                            course_requirements[course_code] = {
                                'lecture_hours': row.get('lecture_hours', 0),
                                'tutorial_hours': row.get('tutorial_hours', 0),
                                'practical_hours': row.get('practical_hours', 0)
                            }
                    
                    if course_requirements:
                        print(f"✅ Loaded requirements for {len(course_requirements)} courses")
                        break
                        
                except Exception as e:
                    continue
        
        return course_requirements
    
    def verify_cross_schedule_conflicts(self):
        """Check for conflicts between lab and theory schedules."""
        print("\n🔄 Verifying Cross-Schedule Conflicts...")
        
        if self.lab_schedule is None or self.theory_schedule is None:
            print("⚠️  Cannot verify cross-schedule conflicts - one schedule missing")
            return True
        
        conflicts = []
        
        # Check for teacher conflicts across schedules
        lab_teacher_times = defaultdict(list)
        theory_teacher_times = defaultdict(list)
        
        # Collect lab teacher times
        for _, session in self.lab_schedule.iterrows():
            teacher_id = session.get('teacher_id', session.get('teacher_name', 'Unknown'))
            session_name = session.get('session_name', '')
            lab_time_slots = self.lab_sessions.get(session_name, [])
            
            for time_slot in lab_time_slots:
                lab_teacher_times[teacher_id].append({
                    'day': session['day'],
                    'time': time_slot,
                    'course': session['course_code'],
                    'type': 'lab'
                })
        
        # Collect theory teacher times
        for _, session in self.theory_schedule.iterrows():
            teacher_id = session.get('teacher_id', session.get('teacher_name', 'Unknown'))
            time_slot = session.get('time_slot', session.get('time', ''))
            theory_teacher_times[teacher_id].append({
                'day': session['day'],
                'time': time_slot,
                'course': session['course_code'],
                'type': 'theory'
            })
        
        # Find overlaps
        for teacher_id in set(lab_teacher_times.keys()) & set(theory_teacher_times.keys()):
            lab_sessions = lab_teacher_times[teacher_id]
            theory_sessions = theory_teacher_times[teacher_id]
            
            for lab_session in lab_sessions:
                for theory_session in theory_sessions:
                    if (lab_session['day'] == theory_session['day'] and 
                        self._times_overlap(lab_session['time'], theory_session['time'])):
                        conflicts.append({
                            'teacher_id': teacher_id,
                            'day': lab_session['day'],
                            'lab_session': lab_session,
                            'theory_session': theory_session
                        })
        
        self.verification_results['cross_schedule_conflicts'] = conflicts
        
        if conflicts:
            print(f"❌ Found {len(conflicts)} cross-schedule teacher conflicts:")
            for i, conflict in enumerate(conflicts[:10], 1):
                print(f"   {i}. Teacher {conflict['teacher_id']} on {conflict['day']}:")
                lab = conflict['lab_session']
                theory = conflict['theory_session']
                print(f"      - LAB: {lab['course']} at {lab['time']}")
                print(f"      - THEORY: {theory['course']} at {theory['time']}")
        else:
            print("✅ No cross-schedule conflicts found")
        
        return len(conflicts) == 0
    
    def generate_verification_report(self):
        """Generate a comprehensive verification report."""
        print("\n📋 Generating Verification Report...")
        print("=" * 60)
        
        # Run all verifications
        room_ok = self.verify_room_double_bookings()
        teacher_ok = self.verify_teacher_conflicts()
        ltp_ok = self.verify_ltp_requirements()
        cross_ok = self.verify_cross_schedule_conflicts()
        
        # Compile summary
        total_issues = (
            len(self.verification_results['room_conflicts']) +
            len(self.verification_results['teacher_conflicts']) +
            len(self.verification_results['ltp_violations']) +
            len(self.verification_results['cross_schedule_conflicts'])
        )
        
        self.verification_results['summary'] = {
            'total_issues': total_issues,
            'room_conflicts': len(self.verification_results['room_conflicts']),
            'teacher_conflicts': len(self.verification_results['teacher_conflicts']),
            'ltp_violations': len(self.verification_results['ltp_violations']),
            'cross_schedule_conflicts': len(self.verification_results['cross_schedule_conflicts']),
            'overall_status': 'PASS' if total_issues == 0 else 'NEEDS_ATTENTION'
        }
        
        # Save detailed report
        report_path = os.path.join(self.schedule_dir, 'verification_report.json')
        with open(report_path, 'w') as f:
            json.dump(self.verification_results, f, indent=2, default=str)
        
        # Save text summary
        summary_path = os.path.join(self.schedule_dir, 'verification_summary.txt')
        with open(summary_path, 'w') as f:
            f.write("SCHEDULE VERIFICATION REPORT\n")
            f.write("=" * 50 + "\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Schedule Directory: {self.schedule_dir}\n\n")
            
            f.write("SUMMARY:\n")
            f.write("-" * 20 + "\n")
            f.write(f"Overall Status: {self.verification_results['summary']['overall_status']}\n")
            f.write(f"Total Issues: {self.verification_results['summary']['total_issues']}\n")
            f.write(f"- Room Conflicts: {self.verification_results['summary']['room_conflicts']}\n")
            f.write(f"- Teacher Conflicts: {self.verification_results['summary']['teacher_conflicts']}\n")
            f.write(f"- LTP Issues: {self.verification_results['summary']['ltp_violations']}\n")
            f.write(f"- Cross-Schedule Conflicts: {self.verification_results['summary']['cross_schedule_conflicts']}\n\n")
            
            f.write("NOTES:\n")
            f.write("- Student group overlaps in batched courses are EXPECTED behavior\n")
            f.write("- For detailed LTP analysis, use verify_lecture_tutorial_hours.py\n")
            f.write("- For practical hours analysis, use verify_ltp_constraints.py\n\n")
            
            # Write details for each conflict type
            if self.verification_results['room_conflicts']:
                f.write("ROOM CONFLICTS:\n")
                f.write("-" * 20 + "\n")
                for conflict in self.verification_results['room_conflicts'][:20]:
                    f.write(f"Room {conflict['room_id']} on {conflict['day']} at {conflict['time']}\n")
                    for session in conflict['sessions']:
                        batch_info = f" ({session['batch_info']})" if session['batch_info'] != 'N/A' else ""
                        f.write(f"  - {session['type']}: {session['course']}{batch_info} (Teacher {session['teacher']})\n")
                    f.write("\n")
            
            if self.verification_results['teacher_conflicts']:
                f.write("TEACHER CONFLICTS:\n")
                f.write("-" * 20 + "\n")
                for conflict in self.verification_results['teacher_conflicts'][:20]:
                    f.write(f"Teacher {conflict['teacher_id']} on {conflict['day']}\n")
                    s1, s2 = conflict['session1'], conflict['session2']
                    f.write(f"  - {s1['type']}: {s1['course']} at {s1['time']}\n")
                    f.write(f"  - {s2['type']}: {s2['course']} at {s2['time']}\n\n")
        
        print(f"✅ Verification report saved to: {report_path}")
        print(f"✅ Summary saved to: {summary_path}")
        
        # Print final status
        print(f"\n🎯 VERIFICATION RESULT: {self.verification_results['summary']['overall_status']}")
        if total_issues > 0:
            print(f"⚠️  Found {total_issues} issues requiring attention")
            print("💡 Note: For comprehensive LTP analysis, run the dedicated verification scripts:")
            print("   - python src/data_analytics/verify_lecture_tutorial_hours.py")
            print("   - python src/data_analytics/verify_ltp_constraints.py")
        else:
            print("✅ All basic verifications passed!")
            print("💡 For detailed LTP compliance verification, run the dedicated scripts above.")
        
        return self.verification_results['summary']['overall_status'] == 'PASS'

def main():
    """Main function for schedule verification."""
    parser = argparse.ArgumentParser(description='Verify schedule for conflicts and requirements')
    parser.add_argument('schedule_dir', nargs='?', 
                       default='output/combined_schedule_20250625_085541',
                       help='Directory containing the schedule files')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.schedule_dir):
        print(f"❌ Schedule directory not found: {args.schedule_dir}")
        
        # Try to find latest schedule directory
        import glob
        schedule_dirs = sorted(glob.glob('output/combined_schedule_*'), reverse=True)
        if schedule_dirs:
            args.schedule_dir = schedule_dirs[0]
            print(f"📁 Using latest schedule directory: {args.schedule_dir}")
        else:
            print("❌ No schedule directories found in output/")
            return 1
    
    # Run verification
    verifier = ScheduleVerifier(args.schedule_dir)
    success = verifier.generate_verification_report()
    
    return 0 if success else 1

if __name__ == "__main__":
    exit(main()) 