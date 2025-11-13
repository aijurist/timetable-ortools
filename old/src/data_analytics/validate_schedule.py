#!/usr/bin/env python3
"""
Comprehensive Lab Schedule Validation Script

This script validates the lab schedule against all group-based constraints
and provides detailed analysis and reporting.
"""

import json
import pandas as pd
import os
import sys
from collections import defaultdict, Counter
from datetime import datetime

class ScheduleValidator:
    def __init__(self, schedule_file):
        self.schedule_file = schedule_file
        self.schedule = self.load_schedule()
        self.violations = []
        self.stats = {
            'total_sessions': len(self.schedule),
            'unique_time_slots': 0,
            'unique_courses': 0,
            'unique_teachers': 0,
            'unique_groups': 0,
            'semesters': set(),
            'departments': set()
        }
        
    def load_schedule(self):
        """Load the lab schedule."""
        try:
            if self.schedule_file.endswith('.json'):
                with open(self.schedule_file, 'r') as f:
                    return json.load(f)
            else:
                df = pd.read_csv(self.schedule_file)
                return df.to_dict('records')
        except Exception as e:
            print(f"Error loading schedule: {e}")
            sys.exit(1)
    
    def analyze_schedule_structure(self):
        """Analyze the basic structure of the schedule."""
        print("\n📊 SCHEDULE STRUCTURE ANALYSIS")
        print("=" * 50)
        
        # Collect statistics
        time_slots = set()
        courses = set()
        teachers = set()
        groups = set()
        
        for entry in self.schedule:
            time_slots.add(f"{entry['day']}_{entry['session_name']}")
            courses.add(entry['course_code'])
            teachers.add(entry['teacher_id'])
            groups.add(f"S{entry['semester']}G{entry['group_index']}")
            self.stats['semesters'].add(entry['semester'])
            self.stats['departments'].add(entry['department'])
        
        self.stats.update({
            'unique_time_slots': len(time_slots),
            'unique_courses': len(courses),
            'unique_teachers': len(teachers),
            'unique_groups': len(groups)
        })
        
        print(f"Total lab sessions: {self.stats['total_sessions']}")
        print(f"Unique time slots: {self.stats['unique_time_slots']}")
        print(f"Unique courses: {self.stats['unique_courses']}")
        print(f"Unique teachers: {self.stats['unique_teachers']}")
        print(f"Unique groups: {self.stats['unique_groups']}")
        print(f"Semesters: {sorted(self.stats['semesters'])}")
        print(f"Departments: {list(self.stats['departments'])}")
        
        # Session distribution
        sessions_per_slot = self.stats['total_sessions'] / self.stats['unique_time_slots']
        print(f"Average sessions per time slot: {sessions_per_slot:.1f}")
    
    def validate_constraint_1(self):
        """Validate: Same group courses CAN overlap."""
        print(f"\n✅ CONSTRAINT 1: Same Group Courses CAN Overlap")
        print(f"   This constraint allows overlaps, so we just report statistics.")
        
        # Count same-group overlaps
        time_slots = defaultdict(list)
        for entry in self.schedule:
            slot_key = f"{entry['day']}_{entry['session_name']}"
            time_slots[slot_key].append(entry)
        
        same_group_overlaps = 0
        for slot, entries in time_slots.items():
            if len(entries) <= 1:
                continue
                
            # Group by group key
            groups_in_slot = defaultdict(list)
            for entry in entries:
                group_key = f"S{entry['semester']}G{entry['group_index']}"
                groups_in_slot[group_key].append(entry)
            
            for group_key, group_entries in groups_in_slot.items():
                if len(group_entries) > 1:
                    same_group_overlaps += 1
                    if same_group_overlaps <= 3:  # Show examples
                        courses = [e['course_code'] for e in group_entries]
                        print(f"   📍 {slot}: {group_key} → {', '.join(courses)}")
        
        print(f"   Found {same_group_overlaps} same-group overlaps (perfectly fine!)")
        return True
    
    def validate_constraint_2(self):
        """Validate: Different groups in same semester CANNOT overlap."""
        print(f"\n❌ CONSTRAINT 2: Different Groups in Same Semester CANNOT Overlap")
        print(f"   This is the critical constraint - violations are serious!")
        
        violations = []
        time_slots = defaultdict(list)
        for entry in self.schedule:
            slot_key = f"{entry['day']}_{entry['session_name']}"
            time_slots[slot_key].append(entry)
        
        for slot, entries in time_slots.items():
            if len(entries) <= 1:
                continue
            
            # Group by semester, then by group within semester
            semester_groups = defaultdict(lambda: defaultdict(list))
            for entry in entries:
                semester = entry['semester']
                group = entry['group_index']
                semester_groups[semester][group].append(entry)
            
            # Check for violations within each semester
            for semester, groups in semester_groups.items():
                if len(groups) > 1:
                    group_ids = sorted(groups.keys())
                    violation = {
                        'slot': slot,
                        'semester': semester,
                        'groups': group_ids,
                        'details': {}
                    }
                    
                    print(f"   🚨 VIOLATION at {slot}: Semester {semester} groups {group_ids} overlap!")
                    
                    for group_id, group_entries in groups.items():
                        courses = [f"{e['course_code']}(T{e['teacher_id']})" for e in group_entries]
                        violation['details'][f"Group{group_id}"] = courses
                        print(f"      Group {group_id}: {', '.join(courses)}")
                    
                    violations.append(violation)
        
        if violations:
            print(f"   ❌ FOUND {len(violations)} CRITICAL VIOLATIONS!")
            self.violations.extend([{'type': 'semester_group_conflict', **v} for v in violations])
            return False
        else:
            print(f"   ✅ No violations found - constraint satisfied!")
            return True
    
    def validate_constraint_3(self):
        """Validate: Different semesters CAN overlap."""
        print(f"\n✅ CONSTRAINT 3: Different Semesters CAN Overlap")
        print(f"   This constraint allows overlaps, so we just report statistics.")
        
        time_slots = defaultdict(list)
        for entry in self.schedule:
            slot_key = f"{entry['day']}_{entry['session_name']}"
            time_slots[slot_key].append(entry)
        
        cross_semester_overlaps = 0
        for slot, entries in time_slots.items():
            if len(entries) <= 1:
                continue
            
            semesters = set(entry['semester'] for entry in entries)
            if len(semesters) > 1:
                cross_semester_overlaps += 1
                if cross_semester_overlaps <= 3:  # Show examples
                    semester_list = sorted(semesters)
                    print(f"   📍 {slot}: Semesters {semester_list} → {len(entries)} sessions")
        
        print(f"   Found {cross_semester_overlaps} cross-semester overlaps (perfectly fine!)")
        return True
    
    def validate_constraint_4(self):
        """Validate: Teachers cannot teach multiple labs simultaneously."""
        print(f"\n❌ CONSTRAINT 4: Teachers Cannot Teach Multiple Labs Simultaneously")
        print(f"   No teacher should be assigned to multiple sessions at the same time.")
        
        violations = []
        time_slots = defaultdict(list)
        for entry in self.schedule:
            slot_key = f"{entry['day']}_{entry['session_name']}"
            time_slots[slot_key].append(entry)
        
        for slot, entries in time_slots.items():
            if len(entries) <= 1:
                continue
            
            # Group by teacher
            teacher_assignments = defaultdict(list)
            for entry in entries:
                teacher_assignments[entry['teacher_id']].append(entry)
            
            # Check for conflicts
            for teacher, assignments in teacher_assignments.items():
                if len(assignments) > 1:
                    courses = [f"{a['course_code']}(S{a['semester']}G{a['group_index']})" for a in assignments]
                    print(f"   🚨 VIOLATION at {slot}: Teacher {teacher} assigned to {len(assignments)} labs!")
                    print(f"      Courses: {', '.join(courses)}")
                    
                    violations.append({
                        'slot': slot,
                        'teacher': teacher,
                        'assignments': len(assignments),
                        'courses': courses
                    })
        
        if violations:
            print(f"   ❌ FOUND {len(violations)} TEACHER CONFLICTS!")
            self.violations.extend([{'type': 'teacher_conflict', **v} for v in violations])
            return False
        else:
            print(f"   ✅ No violations found - constraint satisfied!")
            return True
    
    def generate_summary_report(self):
        """Generate final summary report."""
        print(f"\n" + "="*60)
        print(f"VALIDATION SUMMARY REPORT")
        print("="*60)
        
        # Count violations by type
        semester_violations = len([v for v in self.violations if v['type'] == 'semester_group_conflict'])
        teacher_violations = len([v for v in self.violations if v['type'] == 'teacher_conflict'])
        total_violations = len(self.violations)
        
        print(f"\n📊 CONSTRAINT COMPLIANCE:")
        print(f"   1. Same group overlaps: ✅ ALLOWED ({0} violations)")
        print(f"   2. Same semester different groups: {'❌ FAILED' if semester_violations > 0 else '✅ PASSED'} ({semester_violations} violations)")
        print(f"   3. Different semester overlaps: ✅ ALLOWED ({0} violations)")
        print(f"   4. Teacher conflicts: {'❌ FAILED' if teacher_violations > 0 else '✅ PASSED'} ({teacher_violations} violations)")
        
        print(f"\n🎯 OVERALL VALIDATION RESULT:")
        if total_violations == 0:
            print(f"   ✅ ALL CONSTRAINTS SATISFIED!")
            print(f"   🎉 Group-based lab scheduling is working perfectly!")
            print(f"   📈 Schedule quality: EXCELLENT")
        else:
            print(f"   ❌ {total_violations} CONSTRAINT VIOLATIONS FOUND!")
            print(f"   🔧 Group-based scheduling needs immediate fixes!")
            print(f"   📈 Schedule quality: NEEDS IMPROVEMENT")
        
        # Additional insights
        print(f"\n📋 SCHEDULE INSIGHTS:")
        print(f"   • Utilization: {self.stats['total_sessions']}/{self.stats['unique_time_slots']} sessions/slots")
        print(f"   • Coverage: {self.stats['unique_courses']} courses across {len(self.stats['semesters'])} semesters")
        print(f"   • Teacher workload: {self.stats['total_sessions']}/{self.stats['unique_teachers']} sessions/teacher avg")
        
        return total_violations == 0
    
    def run_validation(self):
        """Run complete validation process."""
        print("🔍 COMPREHENSIVE LAB SCHEDULE VALIDATION")
        print("=" * 50)
        print(f"📁 Validating: {self.schedule_file}")
        
        # Analyze structure
        self.analyze_schedule_structure()
        
        # Validate all constraints
        results = []
        results.append(self.validate_constraint_1())
        results.append(self.validate_constraint_2())
        results.append(self.validate_constraint_3())
        results.append(self.validate_constraint_4())
        
        # Generate summary
        success = self.generate_summary_report()
        
        # Save violations if any
        if self.violations:
            self.save_violations()
        
        return success
    
    def save_violations(self):
        """Save violation details to file."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        violation_file = f"schedule_violations_{timestamp}.json"
        
        report = {
            'timestamp': timestamp,
            'schedule_file': self.schedule_file,
            'stats': self.stats,
            'total_violations': len(self.violations),
            'violations': self.violations
        }
        
        with open(violation_file, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        
        print(f"\n💾 Violation details saved to: {violation_file}")

def find_latest_schedule():
    """Find the most recent schedule file."""
    # Check common output locations
    search_paths = [
        'output',
        '../output',
        './timetable_scheduler/output'
    ]
    
    for base_path in search_paths:
        if os.path.exists(base_path):
            schedule_dirs = [d for d in os.listdir(base_path) if d.startswith('lab_schedule_')]
            if schedule_dirs:
                latest_dir = max(schedule_dirs)
                
                # Try JSON first, then CSV
                json_file = os.path.join(base_path, latest_dir, 'lab_schedule.json')
                csv_file = os.path.join(base_path, latest_dir, 'lab_schedule.csv')
                
                if os.path.exists(json_file):
                    return json_file
                elif os.path.exists(csv_file):
                    return csv_file
    
    return None

def main():
    """Main validation function."""
    # Get file path
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
    else:
        file_path = find_latest_schedule()
        if not file_path:
            print("❌ No lab schedule found!")
            print("Usage: python validate_schedule.py [schedule_file.json/csv]")
            sys.exit(1)
    
    if not os.path.exists(file_path):
        print(f"❌ File not found: {file_path}")
        sys.exit(1)
    
    # Run validation
    validator = ScheduleValidator(file_path)
    success = validator.run_validation()
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main() 