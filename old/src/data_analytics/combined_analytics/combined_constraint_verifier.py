#!/usr/bin/env python3
"""
Combined Schedule Constraint Verifier

This script performs detailed constraint verification for the combined schedule.
It checks all the constraints that should be enforced by the combined scheduler:
1. Teacher clash constraints (no teacher in multiple places at once)
2. Room assignment constraints (no double booking)
3. Group conflict constraints (no same semester/dept groups overlapping)
4. Capacity constraints
5. Time allocation constraints
"""

import os
import sys
import pandas as pd
import numpy as np
from collections import defaultdict
from datetime import datetime

class CombinedConstraintVerifier:
    def __init__(self, lab_schedule_path, theory_schedule_path, course_requirements_path=None):
        self.lab_schedule = pd.read_csv(lab_schedule_path) if os.path.exists(lab_schedule_path) else None
        self.theory_schedule = pd.read_csv(theory_schedule_path) if os.path.exists(theory_schedule_path) else None
        self.course_requirements = pd.read_csv(course_requirements_path) if course_requirements_path and os.path.exists(course_requirements_path) else None
        
        self.violations = []
        
        # Time mappings for conflict detection
        self.lab_sessions = {
            'L1': {'time_range': '8:00-10:00', 'start': 480, 'end': 600},  # 8:00-10:00
            'L2': {'time_range': '10:00-12:00', 'start': 600, 'end': 720},  # 10:00-12:00
            'L3': {'time_range': '12:00-14:00', 'start': 720, 'end': 840},  # 12:00-14:00
            'L4': {'time_range': '14:00-16:00', 'start': 840, 'end': 960},  # 14:00-16:00
            'L5': {'time_range': '16:00-18:00', 'start': 960, 'end': 1080}, # 16:00-18:00
            'L6': {'time_range': '18:00-20:00', 'start': 1080, 'end': 1200} # 18:00-20:00
        }
        
    def parse_time_to_minutes(self, time_str):
        """Convert time string to minutes since midnight."""
        try:
            if '-' in time_str:
                # Handle ranges like "8:00-9:00"
                start_time = time_str.split('-')[0]
            else:
                start_time = time_str
            
            hour, minute = map(int, start_time.split(':'))
            return hour * 60 + minute
        except:
            return None
    
    def time_ranges_overlap(self, start1, end1, start2, end2):
        """Check if two time ranges overlap."""
        return start1 < end2 and start2 < end1
    
    def verify_teacher_clash_constraints(self):
        """Verify that no teacher is assigned to multiple sessions at the same time."""
        print("🔍 Verifying Teacher Clash Constraints...")
        violations = []
        
        if self.lab_schedule is None or self.theory_schedule is None:
            print("❌ Missing schedule data for teacher clash verification")
            return violations
        
        # Create combined teacher schedule
        teacher_schedule = defaultdict(lambda: defaultdict(list))
        
        # Add lab sessions
        for _, session in self.lab_schedule.iterrows():
            teacher_id = session['teacher_id']
            day = session['day']
            session_name = session.get('session_name', '')
            
            if session_name in self.lab_sessions:
                time_info = self.lab_sessions[session_name]
                teacher_schedule[teacher_id][day].append({
                    'type': 'LAB',
                    'course': session['course_code'],
                    'time_range': time_info['time_range'],
                    'start': time_info['start'],
                    'end': time_info['end'],
                    'room': session.get('room_number', f"R{session['room_id']}")
                })
        
        # Add theory sessions
        for _, session in self.theory_schedule.iterrows():
            teacher_id = session['teacher_id']
            day = session['day']
            time_slot = session.get('time_slot', '')
            
            # Parse theory time slot
            start_minutes = self.parse_time_to_minutes(time_slot.split(' - ')[0] if ' - ' in time_slot else time_slot)
            if start_minutes is not None:
                end_minutes = start_minutes + 50  # Theory slots are 50 minutes
                
                teacher_schedule[teacher_id][day].append({
                    'type': 'THEORY',
                    'course': session['course_code'],
                    'time_range': time_slot,
                    'start': start_minutes,
                    'end': end_minutes,
                    'room': session.get('room_number', f"R{session['room_id']}")
                })
        
        # Check for conflicts
        for teacher_id, daily_schedule in teacher_schedule.items():
            for day, sessions in daily_schedule.items():
                # Sort sessions by start time
                sessions.sort(key=lambda x: x['start'])
                
                for i in range(len(sessions)):
                    for j in range(i + 1, len(sessions)):
                        session1 = sessions[i]
                        session2 = sessions[j]
                        
                        if self.time_ranges_overlap(session1['start'], session1['end'], 
                                                  session2['start'], session2['end']):
                            violations.append({
                                'type': 'TEACHER_CLASH',
                                'teacher_id': teacher_id,
                                'day': day,
                                'session1': f"{session1['type']} {session1['course']} ({session1['time_range']}) in {session1['room']}",
                                'session2': f"{session2['type']} {session2['course']} ({session2['time_range']}) in {session2['room']}",
                                'description': f"Teacher {teacher_id} has overlapping sessions on {day}"
                            })
        
        print(f"   Found {len(violations)} teacher clash violations")
        return violations
    
    def verify_room_assignment_constraints(self):
        """Verify that no room is double-booked."""
        print("🔍 Verifying Room Assignment Constraints...")
        violations = []
        
        # Check lab room conflicts
        if self.lab_schedule is not None:
            lab_room_usage = defaultdict(list)
            
            for _, session in self.lab_schedule.iterrows():
                room_id = session['room_id']
                day = session['day']
                session_name = session.get('session_name', '')
                
                if session_name in self.lab_sessions:
                    time_info = self.lab_sessions[session_name]
                    key = (room_id, day, time_info['start'], time_info['end'])
                    lab_room_usage[key].append({
                        'course': session['course_code'],
                        'teacher': session['teacher_id'],
                        'session': session_name
                    })
            
            # Check for lab room conflicts
            for (room_id, day, start, end), assignments in lab_room_usage.items():
                if len(assignments) > 1:
                    violations.append({
                        'type': 'LAB_ROOM_CONFLICT',
                        'room_id': room_id,
                        'day': day,
                        'time_range': f"{start//60}:{start%60:02d}-{end//60}:{end%60:02d}",
                        'assignments': assignments,
                        'description': f"Lab room {room_id} double-booked on {day}"
                    })
        
        # Check theory room conflicts
        if self.theory_schedule is not None:
            theory_room_usage = defaultdict(list)
            
            for _, session in self.theory_schedule.iterrows():
                room_id = session['room_id']
                day = session['day']
                time_slot = session.get('time_slot', '')
                
                key = (room_id, day, time_slot)
                theory_room_usage[key].append({
                    'course': session['course_code'],
                    'teacher': session['teacher_id'],
                    'session_type': session.get('session_type', 'lecture')
                })
            
            # Check for theory room conflicts
            for (room_id, day, time_slot), assignments in theory_room_usage.items():
                if len(assignments) > 1:
                    violations.append({
                        'type': 'THEORY_ROOM_CONFLICT',
                        'room_id': room_id,
                        'day': day,
                        'time_slot': time_slot,
                        'assignments': assignments,
                        'description': f"Theory room {room_id} double-booked on {day} at {time_slot}"
                    })
        
        print(f"   Found {len(violations)} room assignment violations")
        return violations
    
    def verify_group_conflict_constraints(self):
        """Verify that groups from same department/semester don't overlap."""
        print("🔍 Verifying Group Conflict Constraints...")
        violations = []
        
        if self.lab_schedule is None or self.theory_schedule is None:
            print("   ⚠️ Missing schedule data for group conflict verification")
            return violations
        
        # Group sessions by department and semester
        dept_sem_sessions = defaultdict(lambda: defaultdict(list))
        
        # Add lab sessions
        for _, session in self.lab_schedule.iterrows():
            dept = session.get('department', 'Unknown')
            semester = session.get('semester', 0)
            if dept != 'Unknown' and semester > 0:
                dept_sem_sessions[(dept, semester)]['lab'].append(session)
        
        # Add theory sessions
        for _, session in self.theory_schedule.iterrows():
            dept = session.get('department', 'Unknown')
            semester = session.get('semester', 0)
            if dept != 'Unknown' and semester > 0:
                dept_sem_sessions[(dept, semester)]['theory'].append(session)
        
        # Check for conflicts within each department-semester
        for (dept, semester), sessions in dept_sem_sessions.items():
            lab_sessions = sessions.get('lab', [])
            theory_sessions = sessions.get('theory', [])
            
            if not lab_sessions or not theory_sessions:
                continue
            
            # Check for time overlaps between lab and theory sessions
            for _, lab_session in enumerate(lab_sessions):
                lab_day = lab_session.get('day')
                lab_session_name = lab_session.get('session_name', '')
                lab_group = lab_session.get('group_index', 0)
                
                if lab_session_name in self.lab_sessions:
                    lab_time_info = self.lab_sessions[lab_session_name]
                    
                    for _, theory_session in enumerate(theory_sessions):
                        theory_day = theory_session.get('day')
                        theory_time_slot = theory_session.get('time_slot', '')
                        theory_group = theory_session.get('group_index', 0)
                        
                        # Only check sessions from same group on same day
                        if (lab_day == theory_day and lab_group == theory_group and 
                            theory_time_slot):
                            
                            # Parse theory time
                            theory_start = self.parse_time_to_minutes(theory_time_slot.split(' - ')[0])
                            if theory_start is not None:
                                theory_end = theory_start + 50
                                
                                # Check for overlap
                                if self.time_ranges_overlap(lab_time_info['start'], lab_time_info['end'],
                                                          theory_start, theory_end):
                                    violations.append({
                                        'type': 'GROUP_CONFLICT',
                                        'department': dept,
                                        'semester': semester,
                                        'group': lab_group,
                                        'day': lab_day,
                                        'lab_session': f"{lab_session['course_code']} ({lab_session_name})",
                                        'theory_session': f"{theory_session['course_code']} ({theory_time_slot})",
                                        'description': f"{dept} S{semester} G{lab_group}: Lab and theory conflict on {lab_day}"
                                    })
        
        print(f"   Found {len(violations)} group conflict violations")
        return violations
    
    def verify_capacity_constraints(self):
        """Verify that room capacities are sufficient for enrolled students."""
        print("🔍 Verifying Capacity Constraints...")
        violations = []
        
        # Check lab capacity constraints
        if self.lab_schedule is not None:
            for _, session in self.lab_schedule.iterrows():
                room_capacity = session.get('room_capacity', session.get('capacity', 0))
                student_count = session.get('student_count', 0)
                
                if student_count > room_capacity:
                    violations.append({
                        'type': 'LAB_CAPACITY_VIOLATION',
                        'course': session['course_code'],
                        'room_id': session['room_id'],
                        'room_capacity': room_capacity,
                        'student_count': student_count,
                        'description': f"Lab {session['course_code']}: {student_count} students > {room_capacity} capacity"
                    })
        
        # Check theory capacity constraints
        if self.theory_schedule is not None:
            for _, session in self.theory_schedule.iterrows():
                room_capacity = session.get('capacity', 0)
                student_count = session.get('student_count', 0)
                
                if student_count > room_capacity:
                    violations.append({
                        'type': 'THEORY_CAPACITY_VIOLATION',
                        'course': session['course_code'],
                        'room_id': session['room_id'],
                        'room_capacity': room_capacity,
                        'student_count': student_count,
                        'description': f"Theory {session['course_code']}: {student_count} students > {room_capacity} capacity"
                    })
        
        print(f"   Found {len(violations)} capacity violations")
        return violations
    
    def verify_workload_constraints(self):
        """Verify that teacher workloads are within reasonable limits."""
        print("🔍 Verifying Workload Constraints...")
        violations = []
        
        teacher_workload = defaultdict(lambda: {'theory_hours': 0, 'lab_hours': 0, 'total_hours': 0})
        
        # Count theory hours
        if self.theory_schedule is not None:
            for _, session in self.theory_schedule.iterrows():
                teacher_id = session['teacher_id']
                teacher_workload[teacher_id]['theory_hours'] += 1  # Each theory slot = 1 hour
        
        # Count lab hours (each lab session = 2 hours)
        if self.lab_schedule is not None:
            lab_sessions_counted = defaultdict(set)
            for _, session in self.lab_schedule.iterrows():
                teacher_id = session['teacher_id']
                day = session['day']
                session_name = session.get('session_name', '')
                course_id = session.get('course_instance_id', '')
                
                # Only count each unique lab session once
                session_key = f"{day}_{session_name}_{course_id}"
                if session_key not in lab_sessions_counted[teacher_id]:
                    lab_sessions_counted[teacher_id].add(session_key)
                    teacher_workload[teacher_id]['lab_hours'] += 2  # Each lab session = 2 hours
        
        # Calculate total hours and check limits
        for teacher_id, workload in teacher_workload.items():
            total_hours = workload['theory_hours'] + workload['lab_hours']
            workload['total_hours'] = total_hours
            
            # Set reasonable limits
            if workload['lab_hours'] > 0 and workload['theory_hours'] == 0:
                # Pure lab teacher
                limit = 40
            elif workload['theory_hours'] > 0 and workload['lab_hours'] == 0:
                # Pure theory teacher
                limit = 25
            else:
                # Mixed teacher
                limit = 35
            
            if total_hours > limit:
                violations.append({
                    'type': 'WORKLOAD_VIOLATION',
                    'teacher_id': teacher_id,
                    'theory_hours': workload['theory_hours'],
                    'lab_hours': workload['lab_hours'],
                    'total_hours': total_hours,
                    'limit': limit,
                    'description': f"Teacher {teacher_id}: {total_hours} hours exceeds {limit} hour limit"
                })
        
        print(f"   Found {len(violations)} workload violations")
        return violations
    
    def generate_constraint_report(self, output_dir="src/data_analytics/combined_analytics/reports"):
        """Generate a comprehensive constraint verification report."""
        print("\n📋 Generating Constraint Verification Report...")
        
        os.makedirs(output_dir, exist_ok=True)
        
        # Run all constraint verifications
        teacher_violations = self.verify_teacher_clash_constraints()
        room_violations = self.verify_room_assignment_constraints()
        group_violations = self.verify_group_conflict_constraints()
        capacity_violations = self.verify_capacity_constraints()
        workload_violations = self.verify_workload_constraints()
        
        all_violations = (teacher_violations + room_violations + group_violations + 
                         capacity_violations + workload_violations)
        
        # Generate report
        report_path = os.path.join(output_dir, "constraint_verification_report.txt")
        with open(report_path, 'w') as f:
            f.write("COMBINED SCHEDULE CONSTRAINT VERIFICATION REPORT\n")
            f.write("=" * 60 + "\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            
            f.write(f"SUMMARY:\n")
            f.write(f"Total Violations: {len(all_violations)}\n")
            f.write(f"- Teacher Clash: {len(teacher_violations)}\n")
            f.write(f"- Room Assignment: {len(room_violations)}\n")
            f.write(f"- Group Conflicts: {len(group_violations)}\n")
            f.write(f"- Capacity: {len(capacity_violations)}\n")
            f.write(f"- Workload: {len(workload_violations)}\n\n")
            
            f.write(f"STATUS: {'✅ PASSED' if len(all_violations) == 0 else '❌ FAILED'}\n\n")
            
            # Detailed violations
            if all_violations:
                f.write("DETAILED VIOLATIONS:\n")
                f.write("-" * 40 + "\n")
                for i, violation in enumerate(all_violations, 1):
                    f.write(f"{i}. {violation['description']}\n")
                    if 'assignments' in violation:
                        for assignment in violation['assignments']:
                            f.write(f"   - {assignment}\n")
                    f.write("\n")
        
        print(f"✅ Constraint verification report saved to {report_path}")
        
        return len(all_violations) == 0, all_violations

def main():
    """Main function for standalone execution."""
    import glob
    
    # Find latest combined schedule
    combined_dirs = sorted(glob.glob('output/combined_schedule_*'), reverse=True)
    if not combined_dirs:
        print("❌ No combined schedule found!")
        return 1
    
    latest_dir = combined_dirs[0]
    lab_path = os.path.join(latest_dir, 'combined_lab_schedule.csv')
    theory_path = os.path.join(latest_dir, 'combined_theory_schedule.csv')
    
    verifier = CombinedConstraintVerifier(lab_path, theory_path)
    success, violations = verifier.generate_constraint_report()
    
    print(f"\n🎯 Constraint Verification: {'✅ PASSED' if success else '❌ FAILED'}")
    print(f"Total violations: {len(violations)}")
    
    return 0 if success else 1

if __name__ == "__main__":
    exit(main()) 