import pandas as pd
import logging
from typing import Dict, List, Tuple, Any
import random

class ShiftVerifier:
    """
    Utility class to verify teacher shift constraints and analyze shift patterns.
    Ensures that teachers stay within single shifts per day and provides detailed reporting.
    """
    
    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger(__name__)
        
        # Define shift boundaries (same as in constraints.py)
        self.teacher_shifts = {
            'shift1': {'name': 'Shift 1 (8:00-3:00)', 'start_slot': 0, 'end_slot': 6},   # slots 0-6
            'shift2': {'name': 'Shift 2 (10:00-5:00)', 'start_slot': 2, 'end_slot': 8},  # slots 2-8
            'shift3': {'name': 'Shift 3 (12:00-7:00)', 'start_slot': 4, 'end_slot': 10}  # slots 4-10
        }
        
        self.days = ["tuesday", "wed", "thur", "fri", "sat"]
        
        # Updated to equal distribution patterns (33% per shift)
        self.weekly_distribution_patterns = [
            [1, 2, 2],  # Pattern 1: 1 day Shift 1, 2 days Shift 2, 2 days Shift 3 
            [2, 1, 2],  # Pattern 2: 2 days Shift 1, 1 day Shift 2, 2 days Shift 3
            [2, 2, 1],  # Pattern 3: 2 days Shift 1, 2 days Shift 2, 1 day Shift 3
        ]
        
        # Equal distribution preferred pattern
        self.preferred_pattern = [1, 2, 2]
        
        # Track department distributions
        self.department_distributions = {}
        
        # Store teacher target patterns
        self.teacher_target_patterns = {}
    
    def verify_shift_constraints(self, schedule_data: List[Dict]) -> Dict[str, Any]:
        """
        Comprehensive verification of teacher shift constraints.
        
        Returns:
            Dictionary containing:
            - violations: List of shift violations
            - teacher_shifts: Teacher shift assignments per day
            - summary: Overall compliance summary
        """
        self.logger.info("Starting comprehensive shift constraint verification...")
        
        violations = []
        teacher_daily_shifts = {}
        teacher_shift_patterns = {}
        
        # Group schedule data by teacher and day
        teacher_day_assignments = self._group_assignments_by_teacher_day(schedule_data)
        
        # Analyze each teacher's assignments
        for teacher_id, daily_assignments in teacher_day_assignments.items():
            teacher_daily_shifts[teacher_id] = {}
            
            for day, assignments in daily_assignments.items():
                if not assignments:
                    continue
                
                # Get all slots used by this teacher on this day
                slots_used = [assignment['slot_index'] for assignment in assignments]
                
                # Determine the shift for this day
                shift_result = self._determine_teacher_shift_for_day(teacher_id, day, slots_used)
                teacher_daily_shifts[teacher_id][day] = shift_result
                
                # Check for violations
                if shift_result['status'] == 'violation':
                    violations.append({
                        'teacher_id': teacher_id,
                        'day': day,
                        'slots_used': slots_used,
                        'violation_type': shift_result['violation_type'],
                        'details': shift_result['details'],
                        'assignments': assignments
                    })
            
            # Create weekly shift pattern for this teacher
            teacher_shift_patterns[teacher_id] = self._create_shift_pattern(teacher_daily_shifts[teacher_id])
        
        # Generate summary
        summary = self._generate_verification_summary(violations, teacher_daily_shifts, teacher_shift_patterns)
        
        return {
            'violations': violations,
            'teacher_daily_shifts': teacher_daily_shifts,
            'teacher_shift_patterns': teacher_shift_patterns,
            'summary': summary
        }
    
    def _group_assignments_by_teacher_day(self, schedule_data: List[Dict]) -> Dict[str, Dict[str, List[Dict]]]:
        """
        Group schedule assignments by teacher and day.
        Returns: {teacher_id: {day: [assignments]}}
        """
        teacher_day_assignments = {}
        
        for assignment in schedule_data:
            teacher_id = assignment.get('teacher_id')
            day = assignment.get('day')
            
            if teacher_id is None or day is None:
                continue
            
            if teacher_id not in teacher_day_assignments:
                teacher_day_assignments[teacher_id] = {}
            
            if day not in teacher_day_assignments[teacher_id]:
                teacher_day_assignments[teacher_id][day] = []
            
            teacher_day_assignments[teacher_id][day].append(assignment)
        
        return teacher_day_assignments
    
    def _determine_teacher_shift_for_day(self, teacher_id: str, day: str, slots_used: List[int]) -> Dict[str, Any]:
        """
        Determine which shift a teacher is using on a specific day and check for violations.
        """
        if not slots_used:
            return {
                'shift': None,
                'status': 'no_assignments',
                'slots_range': None,
                'compatible_shifts': []
            }
        
        min_slot = min(slots_used)
        max_slot = max(slots_used)
        
        # Check which shifts can accommodate all slots
        compatible_shifts = []
        for shift_name, shift_info in self.teacher_shifts.items():
            start_slot = shift_info['start_slot']
            end_slot = shift_info['end_slot']
            
            if min_slot >= start_slot and max_slot <= end_slot:
                compatible_shifts.append(shift_name)
        
        result = {
            'slots_used': slots_used,
            'slots_range': f"{min_slot}-{max_slot}",
            'compatible_shifts': compatible_shifts
        }
        
        if len(compatible_shifts) == 0:
            # Violation: spans multiple shifts
            result.update({
                'shift': 'invalid',
                'status': 'violation',
                'violation_type': 'cross_shift_spanning',
                'details': f"Teacher {teacher_id} on {day} uses slots {min_slot}-{max_slot} which spans multiple shifts"
            })
        elif len(compatible_shifts) == 1:
            # Perfect: fits exactly in one shift
            result.update({
                'shift': compatible_shifts[0],
                'status': 'valid',
                'details': f"Teacher {teacher_id} on {day} uses {self.teacher_shifts[compatible_shifts[0]]['name']}"
            })
        else:
            # Multiple compatible shifts - choose the most restrictive one
            shift_sizes = {shift: self.teacher_shifts[shift]['end_slot'] - self.teacher_shifts[shift]['start_slot'] 
                          for shift in compatible_shifts}
            chosen_shift = min(shift_sizes.keys(), key=lambda x: shift_sizes[x])
            
            result.update({
                'shift': chosen_shift,
                'status': 'valid',
                'details': f"Teacher {teacher_id} on {day} uses {self.teacher_shifts[chosen_shift]['name']} (most restrictive choice)"
            })
        
        return result
    
    def _create_shift_pattern(self, daily_shifts: Dict[str, Dict]) -> str:
        """Create a visual pattern string showing the weekly shift distribution."""
        pattern_parts = []
        
        for day in self.days:
            if day in daily_shifts:
                shift_info = daily_shifts[day]
                shift = shift_info.get('shift')
                
                if shift == 'shift1':
                    pattern_parts.append('S1')
                elif shift == 'shift2':
                    pattern_parts.append('S2')
                elif shift == 'shift3':
                    pattern_parts.append('S3')
                elif shift == 'no_classes':
                    # Show recommended shift for days with no classes
                    recommended = shift_info.get('recommended_shift', 'shift1')
                    if recommended == 'shift1':
                        pattern_parts.append('[S1]')
                    elif recommended == 'shift2':
                        pattern_parts.append('[S2]')
                    elif recommended == 'shift3':
                        pattern_parts.append('[S3]')
                    else:
                        pattern_parts.append('--')
                else:
                    pattern_parts.append('XX')  # Violation or unknown
            else:
                pattern_parts.append('--')
        
        return '->'.join(pattern_parts)
    
    def _generate_verification_summary(self, violations: List[Dict], teacher_daily_shifts: Dict, 
                                     teacher_shift_patterns: Dict) -> Dict[str, Any]:
        """Generate a comprehensive summary of shift constraint verification."""
        total_teachers = len(teacher_daily_shifts)
        teachers_with_violations = len(set(v['teacher_id'] for v in violations))
        total_violations = len(violations)
        
        # Count teachers by shift compliance
        compliant_teachers = total_teachers - teachers_with_violations
        
        # Analyze shift distribution
        shift_usage = {shift: 0 for shift in self.teacher_shifts.keys()}
        for teacher_id, daily_shifts in teacher_daily_shifts.items():
            for day, shift_info in daily_shifts.items():
                if shift_info['shift'] and shift_info['shift'] != 'invalid':
                    shift_usage[shift_info['shift']] += 1
        
        return {
            'total_teachers': total_teachers,
            'compliant_teachers': compliant_teachers,
            'teachers_with_violations': teachers_with_violations,
            'total_violations': total_violations,
            'compliance_rate': (compliant_teachers / total_teachers) * 100 if total_teachers > 0 else 0,
            'shift_usage_distribution': shift_usage,
            'status': 'PASS' if total_violations == 0 else 'FAIL'
        }
    
    def print_verification_report(self, verification_result: Dict[str, Any]) -> None:
        """Print a detailed verification report to the logger."""
        violations = verification_result['violations']
        summary = verification_result['summary']
        teacher_shift_patterns = verification_result['teacher_shift_patterns']
        
        self.logger.info("=" * 80)
        self.logger.info("TEACHER SHIFT CONSTRAINT VERIFICATION REPORT")
        self.logger.info("=" * 80)
        
        # Summary
        self.logger.info(f"OVERALL STATUS: {summary['status']}")
        self.logger.info(f"Total Teachers: {summary['total_teachers']}")
        self.logger.info(f"Compliant Teachers: {summary['compliant_teachers']}")
        self.logger.info(f"Teachers with Violations: {summary['teachers_with_violations']}")
        self.logger.info(f"Total Violations: {summary['total_violations']}")
        self.logger.info(f"Compliance Rate: {summary['compliance_rate']:.1f}%")
        
        # Shift usage distribution
        self.logger.info("\nSHIFT USAGE DISTRIBUTION:")
        for shift_name, count in summary['shift_usage_distribution'].items():
            shift_display = self.teacher_shifts[shift_name]['name']
            self.logger.info(f"  {shift_display}: {count} teacher-day assignments")
        
        # Violations (if any)
        if violations:
            self.logger.info(f"\nSHIFT VIOLATIONS DETECTED ({len(violations)}):")
            self.logger.info("-" * 60)
            
            for i, violation in enumerate(violations, 1):
                self.logger.info(f"{i}. Teacher {violation['teacher_id']} on {violation['day']}:")
                self.logger.info(f"   Slots used: {violation['slots_used']}")
                self.logger.info(f"   Violation: {violation['violation_type']}")
                self.logger.info(f"   Details: {violation['details']}")
                
                # Show specific assignments
                self.logger.info("   Assignments:")
                for assignment in violation['assignments']:
                    course_code = assignment.get('course_code', 'Unknown')
                    slot_index = assignment['slot_index']
                    time_interval = assignment.get('time_interval', 'Unknown')
                    macroblock = assignment.get('macroblock', 'Unknown')
                    self.logger.info(f"     - Slot {slot_index} ({time_interval}): {course_code} [{macroblock}]")
                self.logger.info("")
        else:
            self.logger.info(f"\n[OK] NO SHIFT VIOLATIONS DETECTED - All constraints satisfied!")
        
        # Teacher shift patterns
        self.logger.info("\nTEACHER WEEKLY SHIFT PATTERNS:")
        self.logger.info("-" * 60)
        self.logger.info("Pattern Format: Tue->Wed->Thu->Fri->Sat")
        self.logger.info("S1=Shift1, S2=Shift2, S3=Shift3, --=No classes, XX=Violation, [S1]=Recommended shift")
        
        for teacher_id, pattern in sorted(teacher_shift_patterns.items()):
            self.logger.info(f"Teacher {teacher_id}: {pattern}")
        
        self.logger.info("=" * 80)
    
    def add_shift_info_to_schedule(self, schedule_data: List[Dict]) -> List[Dict]:
        """
        Add comprehensive shift information to each schedule entry.
        """
        self.logger.info("Adding shift information to schedule data...")
        
        # First verify shifts to get teacher shift patterns
        verification_result = self.verify_shift_constraints(schedule_data)
        teacher_shift_patterns = verification_result['teacher_shift_patterns']
        teacher_daily_shifts = verification_result['teacher_daily_shifts']
        
        # Update each schedule entry with shift information
        updated_schedule = []
        for assignment in schedule_data:
            teacher_id = assignment['teacher_id']
            day = assignment['day']
            
            # Get shift info for this teacher on this day
            if (teacher_id in teacher_daily_shifts and 
                day in teacher_daily_shifts[teacher_id]):
                
                shift_info = teacher_daily_shifts[teacher_id][day]
                daily_shift = shift_info['shift']
                shift_status = shift_info['status']
                
                # Convert shift to display format
                if daily_shift == 'invalid':
                    shift_display = 'invalid_shift'
                elif daily_shift:
                    shift_display = daily_shift
                else:
                    shift_display = 'no_shift'
            else:
                shift_display = 'no_shift'
                shift_status = 'no_assignments'
            
            # Get weekly pattern
            weekly_pattern = teacher_shift_patterns.get(teacher_id, '-->-->-->-->--')
            
            # Create updated assignment with shift info
            updated_assignment = assignment.copy()
            updated_assignment.update({
                'teacher_shift': shift_display,
                'shift_status': shift_status,
                'daily_shift_pattern': weekly_pattern
            })
            
            updated_schedule.append(updated_assignment)
        
        return updated_schedule
    
    def save_verification_report(self, verification_result: Dict[str, Any], output_path: str) -> None:
        """Save verification report to a file."""
        violations = verification_result['violations']
        summary = verification_result['summary']
        teacher_shift_patterns = verification_result['teacher_shift_patterns']
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("TEACHER SHIFT CONSTRAINT VERIFICATION REPORT\n")
            f.write("=" * 60 + "\n\n")
            
            # Summary
            f.write(f"OVERALL STATUS: {summary['status']}\n")
            f.write(f"Total Teachers: {summary['total_teachers']}\n")
            f.write(f"Compliant Teachers: {summary['compliant_teachers']}\n")
            f.write(f"Teachers with Violations: {summary['teachers_with_violations']}\n")
            f.write(f"Total Violations: {summary['total_violations']}\n")
            f.write(f"Compliance Rate: {summary['compliance_rate']:.1f}%\n\n")
            
            # Shift usage
            f.write("SHIFT USAGE DISTRIBUTION:\n")
            for shift_name, count in summary['shift_usage_distribution'].items():
                shift_display = self.teacher_shifts[shift_name]['name']
                f.write(f"  {shift_display}: {count} teacher-day assignments\n")
            f.write("\n")
            
            # Violations
            if violations:
                f.write(f"SHIFT VIOLATIONS DETECTED ({len(violations)}):\n")
                f.write("-" * 50 + "\n")
                
                for i, violation in enumerate(violations, 1):
                    f.write(f"{i}. Teacher {violation['teacher_id']} on {violation['day']}:\n")
                    f.write(f"   Slots used: {violation['slots_used']}\n")
                    f.write(f"   Violation: {violation['violation_type']}\n")
                    f.write(f"   Details: {violation['details']}\n")
                    
                    f.write("   Assignments:\n")
                    for assignment in violation['assignments']:
                        course_code = assignment.get('course_code', 'Unknown')
                        slot_index = assignment['slot_index']
                        time_interval = assignment.get('time_interval', 'Unknown')
                        macroblock = assignment.get('macroblock', 'Unknown')
                        f.write(f"     - Slot {slot_index} ({time_interval}): {course_code} [{macroblock}]\n")
                    f.write("\n")
            else:
                f.write("NO SHIFT VIOLATIONS DETECTED - All constraints satisfied!\n\n")
            
            # Teacher patterns
            f.write("TEACHER WEEKLY SHIFT PATTERNS:\n")
            f.write("-" * 50 + "\n")
            f.write("Pattern Format: Tue->Wed->Thu->Fri->Sat\n")
            f.write("S1=Shift1, S2=Shift2, S3=Shift3, --=No classes, XX=Violation, [S1]=Recommended shift\n\n")
            
            for teacher_id, pattern in sorted(teacher_shift_patterns.items()):
                self.logger.info(f"Teacher {teacher_id}: {pattern}")
    
    def verify_shift_constraints_with_distribution(self, schedule_data: List[Dict]) -> Dict[str, Any]:
        """
        Enhanced verification that applies weekly shift distribution patterns.
        This is the main method that should be used instead of verify_shift_constraints.
        """
        self.logger.info("Starting enhanced shift constraint verification with weekly distribution patterns...")
        
        violations = []
        teacher_daily_shifts = {}
        teacher_shift_patterns = {}
        teacher_distribution_info = {}  # NEW: Store detailed distribution info
        
        # Group schedule data by teacher and day
        teacher_day_assignments = self._group_assignments_by_teacher_day(schedule_data)
        
        # For each teacher, analyze their weekly shift distribution
        for teacher_id, day_assignments in teacher_day_assignments.items():
            daily_shifts = {}
            actual_distribution = {'shift1': 0, 'shift2': 0, 'shift3': 0, 'invalid': 0, 'no_classes': 0}
            days_with_classes = []
            days_without_classes = []
            
            # First pass: Analyze each day for this teacher and process days with classes
            for day in self.days:
                if day in day_assignments and day_assignments[day]:
                    days_with_classes.append(day)
                    # Get all slots used by this teacher on this day
                    slots_used = [item['slot_index'] for item in day_assignments[day]]
                    min_slot = min(slots_used)
                    max_slot = max(slots_used)
                    
                    # Determine compatible shifts
                    compatible_shifts = []
                    for shift_name, shift_info in self.teacher_shifts.items():
                        if min_slot >= shift_info['start_slot'] and max_slot <= shift_info['end_slot']:
                            compatible_shifts.append(shift_name)
                    
                    # Determine best shift using distribution strategy
                    if not compatible_shifts:
                        assigned_shift = 'invalid'
                        actual_distribution['invalid'] += 1
                        violations.append({
                            'teacher_id': teacher_id,
                            'day': day,
                            'issue': 'cross_shift_violation',
                            'slots': slots_used,
                            'slot_range': f"{min_slot}-{max_slot}",
                            'compatible_shifts': []
                        })
                    else:
                        # Apply distribution strategy to choose best shift
                        assigned_shift = self._choose_optimal_shift_with_distribution(
                            teacher_id, day, compatible_shifts, actual_distribution)
                        actual_distribution[assigned_shift] += 1
                    
                    daily_shifts[day] = {
                        'shift': assigned_shift,
                        'slots': slots_used,
                        'slot_range': f"{min_slot}-{max_slot}",
                        'compatible_shifts': compatible_shifts,
                        'assignments': day_assignments[day],
                        'has_classes': True
                    }
                else:
                    days_without_classes.append(day)
                    daily_shifts[day] = {
                        'shift': 'no_classes',
                        'slots': [],
                        'slot_range': 'None',
                        'compatible_shifts': [],
                        'assignments': [],
                        'has_classes': False
                    }
                    actual_distribution['no_classes'] += 1
            
            # Second pass: Fill in days without classes based on target distribution
            # Get target distribution for this teacher
            target_distribution = self._get_target_distribution_for_teacher(teacher_id, schedule_data)
            target_counts = {
                'shift1': target_distribution[0],
                'shift2': target_distribution[1],
                'shift3': target_distribution[2]
            }
            
            # Calculate how many of each shift we still need to assign
            current_counts = {
                'shift1': actual_distribution['shift1'],
                'shift2': actual_distribution['shift2'],
                'shift3': actual_distribution['shift3']
            }
            
            remaining_counts = {
                shift: max(0, target_counts[shift] - current_counts[shift])
                for shift in ['shift1', 'shift2', 'shift3']
            }
            
            # Sort shifts by how many more we need
            shifts_needed = sorted(
                ['shift1', 'shift2', 'shift3'],
                key=lambda s: remaining_counts[s],
                reverse=True  # Most needed first
            )
            
            # Assign recommended shifts to days without classes
            for day in days_without_classes:
                if any(remaining_counts.values()):  # If we still need to assign shifts
                    # Pick the shift we need the most
                    for shift in shifts_needed:
                        if remaining_counts[shift] > 0:
                            recommended_shift = shift
                            remaining_counts[shift] -= 1
                            break
                    else:
                        # If no shifts needed, default to shift1
                        recommended_shift = 'shift1'
                    
                    # Update the day's information with the recommended shift
                    daily_shifts[day].update({
                        'recommended_shift': recommended_shift,
                        'shift': 'no_classes',  # Still no classes, but we have a recommendation
                        'is_recommendation': True
                    })
            
            teacher_daily_shifts[teacher_id] = daily_shifts
            teacher_shift_patterns[teacher_id] = self._create_shift_pattern(daily_shifts)
            
            # Store detailed distribution information
            teacher_distribution_info[teacher_id] = {
                'target_distribution': target_distribution,
                'actual_distribution': actual_distribution,
                'distribution_compliance': self._calculate_distribution_compliance(
                    target_distribution, actual_distribution),
                'weekly_pattern': teacher_shift_patterns[teacher_id],
                'daily_shifts': daily_shifts,
                'recommended_shifts': {
                    day: daily_shifts[day].get('recommended_shift')
                    for day in days_without_classes
                    if 'recommended_shift' in daily_shifts[day]
                }
            }
        
        # Calculate overall statistics
        total_teachers = len(teacher_day_assignments)
        teachers_with_violations = len(set(v['teacher_id'] for v in violations))
        compliance_rate = ((total_teachers - teachers_with_violations) / total_teachers * 100) if total_teachers > 0 else 100
        
        # Prepare comprehensive result
        result = {
            'status': 'PASS' if not violations else 'FAIL',
            'violations': violations,
            'teacher_daily_shifts': teacher_daily_shifts,
            'teacher_shift_patterns': teacher_shift_patterns,
            'teacher_distribution_info': teacher_distribution_info,  # NEW: Detailed distribution info
            'summary': {
                'total_teachers': total_teachers,
                'teachers_with_violations': teachers_with_violations,
                'total_violations': len(violations),
                'compliance_rate': compliance_rate,
                'status': 'PASS' if not violations else 'FAIL'
            }
        }
        
        return result
    
    def _choose_optimal_shift_with_distribution(self, teacher_id: str, day: str, compatible_shifts: List[str], actual_distribution: Dict[str, int]) -> str:
        """
        Choose the optimal shift based on current distribution and 33% target.
        
        This method aims to balance shift distribution towards the 33/33/33 target.
        """
        if not compatible_shifts:
            return None
        
        if len(compatible_shifts) == 1:
            return compatible_shifts[0]
        
        # Calculate current distribution percentages
        total_shifts = sum(actual_distribution.get(shift, 0) for shift in ['shift1', 'shift2', 'shift3'])
        
        if total_shifts == 0:
            # No shifts assigned yet, choose the first compatible shift
            return compatible_shifts[0]
        
        # Calculate how far each shift is from the 33.33% target
        target_percentage = 33.33
        shift_percentages = {
            shift: (actual_distribution.get(shift, 0) / total_shifts) * 100
            for shift in ['shift1', 'shift2', 'shift3']
        }
        
        # Calculate deficit for each shift (how far below 33.33%)
        shift_deficits = {
            shift: max(0, target_percentage - percentage)
            for shift, percentage in shift_percentages.items()
        }
        
        # Filter to compatible shifts only
        compatible_deficits = {shift: shift_deficits[shift] for shift in compatible_shifts}
        
        # Choose the shift that's most underrepresented (highest deficit)
        if compatible_deficits:
            best_shift = max(compatible_deficits.items(), key=lambda x: x[1])[0]
            return best_shift
        
        # Fallback to most restrictive shift if no clear winner
        shift_sizes = {
            shift: self.teacher_shifts[shift]['end_slot'] - self.teacher_shifts[shift]['start_slot']
            for shift in compatible_shifts
        }
        return min(shift_sizes.keys(), key=lambda x: shift_sizes[x])
    
    def _get_target_distribution_for_teacher(self, teacher_id: str, schedule_data: List[Dict] = None) -> List[int]:
        """
        Get the target distribution for a teacher based on their department and existing distribution.
        Each department will aim for balanced 33% distribution across all shifts.
        """
        # Get teacher's department from schedule data
        department = "Unknown"
        if schedule_data:
            teacher_records = [item for item in schedule_data if item.get('teacher_id') == teacher_id]
            if teacher_records:
                department = teacher_records[0].get('course_dept', "Unknown")
        
        # Initialize department distribution counters if needed
        if department not in self.department_distributions:
            self.department_distributions[department] = {
                'shift1': 0, 'shift2': 0, 'shift3': 0,
                'teachers': {}
            }
        
        # If teacher already has a pattern assigned, return it
        if teacher_id in self.teacher_target_patterns:
            return self.teacher_target_patterns[teacher_id]
        
        # Calculate current department distribution
        dept_distribution = self.department_distributions[department]
        total_shifts = sum(dept_distribution[shift] for shift in ['shift1', 'shift2', 'shift3'])
        
        if total_shifts == 0:
            # First teacher in department - randomly select
            pattern_index = random.randint(0, len(self.weekly_distribution_patterns) - 1)
            selected_pattern = self.weekly_distribution_patterns[pattern_index]
        else:
            # Calculate percentage of each shift in this department
            shift_percentages = {
                'shift1': (dept_distribution['shift1'] / total_shifts) * 100,
                'shift2': (dept_distribution['shift2'] / total_shifts) * 100,
                'shift3': (dept_distribution['shift3'] / total_shifts) * 100
            }
            
            # Find the shift most underrepresented (farthest below 33%)
            target_percentage = 33.33  # Aiming for equal distribution
            shift_deficits = {
                shift: max(0, target_percentage - percentage) 
                for shift, percentage in shift_percentages.items()
            }
            
            # Choose pattern that favors the most underrepresented shifts
            best_pattern = None
            best_score = -1
            
            for pattern in self.weekly_distribution_patterns:
                pattern_shifts = {'shift1': pattern[0], 'shift2': pattern[1], 'shift3': pattern[2]}
                score = sum(pattern_shifts[shift] * deficit for shift, deficit in shift_deficits.items())
                
                if score > best_score:
                    best_score = score
                    best_pattern = pattern
            
            selected_pattern = best_pattern if best_pattern else self.preferred_pattern
        
        # Update department distribution with this pattern
        self.department_distributions[department]['shift1'] += selected_pattern[0]
        self.department_distributions[department]['shift2'] += selected_pattern[1]
        self.department_distributions[department]['shift3'] += selected_pattern[2]
        self.department_distributions[department]['teachers'][teacher_id] = selected_pattern
        
        # Store the selected pattern for this teacher
        self.teacher_target_patterns[teacher_id] = selected_pattern
        
        return selected_pattern
    
    def _calculate_distribution_compliance(self, target_distribution: List[int], actual_distribution: Dict[str, int]) -> float:
        """
        Calculate the distribution compliance score for a teacher.
        """
        target_shifts = {'shift1': target_distribution[0], 'shift2': target_distribution[1], 'shift3': target_distribution[2]}
        total_target = sum(target_distribution)
        
        if total_target == 0:
            return 100.0
        
        # Calculate how close the actual distribution is to the target
        compliance_score = 0.0
        for shift_name, target_count in target_shifts.items():
            actual_count = actual_distribution.get(shift_name, 0)
            if target_count > 0:
                compliance_score += min(actual_count, target_count) / target_count * (target_count / total_target)
        
        return compliance_score * 100.0
    
    def _analyze_department_distributions(self):
        """
        Analyze shift distribution by department and calculate how close each is to the 33/33/33 target.
        """
        department_stats = {}
        
        for dept, data in self.department_distributions.items():
            if dept == "Unknown" or sum(data[shift] for shift in ['shift1', 'shift2', 'shift3']) == 0:
                continue
                
            total_shifts = sum(data[shift] for shift in ['shift1', 'shift2', 'shift3'])
            percentages = {
                'shift1': (data['shift1'] / total_shifts) * 100,
                'shift2': (data['shift2'] / total_shifts) * 100,
                'shift3': (data['shift3'] / total_shifts) * 100
            }
            
            # Calculate deviation from ideal 33.33% distribution
            target = 33.33
            deviations = {
                shift: abs(percentage - target) for shift, percentage in percentages.items()
            }
            avg_deviation = sum(deviations.values()) / 3
            balance_score = 100 - (avg_deviation * 3)  # Higher score = better balance
            
            department_stats[dept] = {
                'total_shifts': total_shifts,
                'shift1_count': data['shift1'],
                'shift2_count': data['shift2'], 
                'shift3_count': data['shift3'],
                'shift1_pct': percentages['shift1'],
                'shift2_pct': percentages['shift2'],
                'shift3_pct': percentages['shift3'],
                'balance_score': balance_score,
                'teacher_count': len(data['teachers'])
            }
            
        return department_stats

    def print_distribution_verification_report(self, verification_result: Dict[str, Any]):
        """Print enhanced verification report with distribution analysis."""
        violations = verification_result['violations']
        teacher_daily_shifts = verification_result['teacher_daily_shifts']
        teacher_shift_patterns = verification_result['teacher_shift_patterns']
        summary = verification_result['summary']
        
        self.logger.info("\n" + "="*80)
        self.logger.info("ENHANCED SHIFT CONSTRAINT VERIFICATION WITH EQUAL DISTRIBUTION (33% PER SHIFT)")
        self.logger.info("="*80)
        
        # Distribution strategy info
        self.logger.info(f"\nTARGET WEEKLY DISTRIBUTION PATTERNS (OPTIMIZED BY DEPARTMENT):")
        self.logger.info(f"  Shift distribution patterns are optimized to achieve 33% for each shift:")
        self.logger.info(f"  • Pattern 1: {self.weekly_distribution_patterns[0][0]} days S1, {self.weekly_distribution_patterns[0][1]} days S2, {self.weekly_distribution_patterns[0][2]} days S3")
        self.logger.info(f"  • Pattern 2: {self.weekly_distribution_patterns[1][0]} days S1, {self.weekly_distribution_patterns[1][1]} days S2, {self.weekly_distribution_patterns[1][2]} days S3")
        self.logger.info(f"  • Pattern 3: {self.weekly_distribution_patterns[2][0]} days S1, {self.weekly_distribution_patterns[2][1]} days S2, {self.weekly_distribution_patterns[2][2]} days S3")
        self.logger.info(f"  Note: Patterns are assigned to balance department-wide distributions")
        self.logger.info(f"  Note: [S1] = Recommended shift for days with no classes")
        
        # Violations section
        if violations:
            self.logger.info(f"\n[ERROR] SHIFT VIOLATIONS DETECTED ({len(violations)} violations):")
            self.logger.info("-" * 60)
            for violation in violations:
                self.logger.info(f"Teacher {violation['teacher_id']} on {violation['day']}:")
                self.logger.info(f"  Slots used: {violation['slots']}")
                self.logger.info(f"  Violation: {violation['issue']}")
                self.logger.info(f"  Details: {violation['slot_range']}")
        else:
            self.logger.info(f"\n[OK] NO SHIFT VIOLATIONS DETECTED - All constraints satisfied!")
        
        # Distribution analysis
        self.logger.info(f"\nDISTRIBUTION ANALYSIS:")
        self.logger.info("-" * 60)
        
        # Count actual distribution
        actual_distribution = {'shift1': 0, 'shift2': 0, 'shift3': 0, 'no_assignments': 0}
        distribution_quality_scores = []
        
        for teacher_id, daily_shifts in teacher_daily_shifts.items():
            teacher_distribution = {'shift1': 0, 'shift2': 0, 'shift3': 0}
            recommended_distribution = {'shift1': 0, 'shift2': 0, 'shift3': 0}
            forced_days = 0
            optimized_days = 0
            days_with_recommendations = 0
            
            for day, shift_info in daily_shifts.items():
                shift = shift_info.get('shift')
                if shift in teacher_distribution:
                    teacher_distribution[shift] += 1
                    actual_distribution[shift] += 1
                    
                    if shift_info.get('assignment_reason') == 'forced':
                        forced_days += 1
                    elif shift_info.get('assignment_reason') == 'distribution_optimized':
                        optimized_days += 1
                elif shift == 'no_classes' and 'recommended_shift' in shift_info:
                    recommended_shift = shift_info['recommended_shift']
                    recommended_distribution[recommended_shift] += 1
                    days_with_recommendations += 1
                elif shift is None:
                    actual_distribution['no_assignments'] += 1
            
            # Get this teacher's specific target pattern
            target = self.teacher_target_patterns.get(teacher_id, self.preferred_pattern)
            actual = [teacher_distribution['shift1'], teacher_distribution['shift2'], teacher_distribution['shift3']]
            recommended = [recommended_distribution['shift1'], recommended_distribution['shift2'], recommended_distribution['shift3']]
            
            if sum(actual) > 0:  # Only for teachers with assignments
                score = 100 - sum(abs(t - a) for t, a in zip(target, actual)) * 20  # Max penalty 20 per difference
                distribution_quality_scores.append(score)
                
                pattern_desc = f"{target[0]},{target[1]},{target[2]}"
                self.logger.info(f"Teacher {teacher_id}: S1={actual[0]}, S2={actual[1]}, S3={actual[2]} "
                               f"(Target pattern: {pattern_desc}) Score: {score:.1f}% "
                               f"[{forced_days} forced, {optimized_days} optimized]")
                
                if days_with_recommendations > 0:
                    self.logger.info(f"  -> Recommended shifts for days with no classes: S1={recommended[0]}, S2={recommended[1]}, S3={recommended[2]}")
        
        # Overall distribution summary
        total_teacher_days = sum(actual_distribution[shift] for shift in ['shift1', 'shift2', 'shift3'])
        avg_quality_score = sum(distribution_quality_scores) / len(distribution_quality_scores) if distribution_quality_scores else 0
        
        self.logger.info(f"\nOVERALL DISTRIBUTION SUMMARY:")
        self.logger.info(f"  Total teacher-days with assignments: {total_teacher_days}")
        if total_teacher_days > 0:
            s1_pct = (actual_distribution['shift1'] / total_teacher_days) * 100
            s2_pct = (actual_distribution['shift2'] / total_teacher_days) * 100  
            s3_pct = (actual_distribution['shift3'] / total_teacher_days) * 100
            
            self.logger.info(f"  Shift 1: {actual_distribution['shift1']} days ({s1_pct:.1f}%)")
            self.logger.info(f"  Shift 2: {actual_distribution['shift2']} days ({s2_pct:.1f}%)")
            self.logger.info(f"  Shift 3: {actual_distribution['shift3']} days ({s3_pct:.1f}%)")
            self.logger.info(f"  Average distribution quality: {avg_quality_score:.1f}%")
            
            # Calculate overall balance score 
            target = 33.33
            overall_deviation = (abs(s1_pct - target) + abs(s2_pct - target) + abs(s3_pct - target)) / 3
            overall_balance = 100 - overall_deviation
            self.logger.info(f"  Overall shift balance score: {overall_balance:.1f}% (target: 33.3% per shift)")
        
        # Department distribution analysis
        dept_stats = self._analyze_department_distributions()
        if dept_stats:
            self.logger.info(f"\nDEPARTMENT-BASED DISTRIBUTION ANALYSIS:")
            self.logger.info("-" * 60)
            self.logger.info(f"{'Department':<30} {'S1 %':>6} {'S2 %':>6} {'S3 %':>6} {'Balance':>8} {'Teachers':>8}")
            self.logger.info("-" * 70)
            
            for dept, stats in sorted(dept_stats.items(), key=lambda x: x[1]['balance_score'], reverse=True):
                dept_name = dept[:28] + '..' if len(dept) > 30 else dept
                self.logger.info(f"{dept_name:<30} {stats['shift1_pct']:6.1f} {stats['shift2_pct']:6.1f} "
                               f"{stats['shift3_pct']:6.1f} {stats['balance_score']:8.1f} {stats['teacher_count']:8}")
        
        # Teacher shift patterns
        self.logger.info("\nTEACHER WEEKLY SHIFT PATTERNS:")
        self.logger.info("-" * 60)
        self.logger.info("Pattern Format: Tue->Wed->Thu->Fri->Sat")
        self.logger.info("S1=Shift1, S2=Shift2, S3=Shift3, --=No classes, XX=Violation, [S1]=Recommended shift")
        
        for teacher_id, pattern in sorted(teacher_shift_patterns.items()):
            target = self.teacher_target_patterns.get(teacher_id, self.preferred_pattern)
            pattern_desc = f"{target[0]},{target[1]},{target[2]}"
            self.logger.info(f"Teacher {teacher_id}: {pattern} (Target: {pattern_desc})")
        
        # Summary
        if summary['status'] == 'PASS':
            self.logger.info(f"\n[SUCCESS] All shift constraints satisfied! ({summary['compliance_rate']:.1f}% compliance)")
            self.logger.info(f"Distribution quality: {avg_quality_score:.1f}% match to target patterns")
            if dept_stats:
                avg_dept_balance = sum(stats['balance_score'] for stats in dept_stats.values()) / len(dept_stats)
                self.logger.info(f"Department balance: {avg_dept_balance:.1f}% (target: 33.3% per shift per department)")
        else:
            self.logger.info(f"\n[FAILURE] {summary['total_violations']} violations found ({summary['compliance_rate']:.1f}% compliance)")
            
    def save_distribution_verification_report(self, verification_result: Dict[str, Any], filepath: str):
        """Save enhanced verification report with distribution analysis to a file."""
        violations = verification_result['violations']
        teacher_daily_shifts = verification_result['teacher_daily_shifts']
        teacher_shift_patterns = verification_result['teacher_shift_patterns']
        summary = verification_result['summary']
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write("ENHANCED SHIFT CONSTRAINT VERIFICATION WITH EQUAL DISTRIBUTION (33% PER SHIFT)\n")
            f.write("="*80 + "\n\n")
            
            # Distribution strategy info
            f.write(f"TARGET WEEKLY DISTRIBUTION PATTERNS (OPTIMIZED BY DEPARTMENT):\n")
            f.write(f"  Shift distribution patterns are optimized to achieve 33% for each shift:\n")
            f.write(f"  • Pattern 1: {self.weekly_distribution_patterns[0][0]} days S1, {self.weekly_distribution_patterns[0][1]} days S2, {self.weekly_distribution_patterns[0][2]} days S3\n")
            f.write(f"  • Pattern 2: {self.weekly_distribution_patterns[1][0]} days S1, {self.weekly_distribution_patterns[1][1]} days S2, {self.weekly_distribution_patterns[1][2]} days S3\n")
            f.write(f"  • Pattern 3: {self.weekly_distribution_patterns[2][0]} days S1, {self.weekly_distribution_patterns[2][1]} days S2, {self.weekly_distribution_patterns[2][2]} days S3\n")
            f.write(f"  Note: Patterns are assigned to balance department-wide distributions\n")
            f.write(f"  Note: [S1] = Recommended shift for days with no classes\n\n")
            
            # Violations section
            if violations:
                f.write(f"[ERROR] SHIFT VIOLATIONS DETECTED ({len(violations)} violations):\n")
                f.write("-" * 60 + "\n")
                for violation in violations:
                    f.write(f"Teacher {violation['teacher_id']} on {violation['day']}:\n")
                    f.write(f"  Slots used: {violation.get('slots_used', [])}\n")
                    f.write(f"  Violation: {violation.get('violation_type', 'Unknown')}\n")
                    f.write(f"  Details: {violation.get('details', 'No details')}\n\n")
            else:
                f.write(f"[OK] NO SHIFT VIOLATIONS DETECTED - All constraints satisfied!\n\n")
            
            # Distribution analysis  
            f.write(f"DISTRIBUTION ANALYSIS:\n")
            f.write("-" * 60 + "\n")
            
            # Count actual distribution
            actual_distribution = {'shift1': 0, 'shift2': 0, 'shift3': 0, 'no_assignments': 0}
            distribution_quality_scores = []
            
            for teacher_id, daily_shifts in teacher_daily_shifts.items():
                teacher_distribution = {'shift1': 0, 'shift2': 0, 'shift3': 0}
                recommended_distribution = {'shift1': 0, 'shift2': 0, 'shift3': 0}
                forced_days = 0
                optimized_days = 0
                days_with_recommendations = 0
                
                for day, shift_info in daily_shifts.items():
                    shift = shift_info.get('shift')
                    if shift in teacher_distribution:
                        teacher_distribution[shift] += 1
                        actual_distribution[shift] += 1
                        
                        if shift_info.get('assignment_reason') == 'forced':
                            forced_days += 1
                        elif shift_info.get('assignment_reason') == 'distribution_optimized':
                            optimized_days += 1
                    elif shift == 'no_classes' and 'recommended_shift' in shift_info:
                        recommended_shift = shift_info['recommended_shift']
                        recommended_distribution[recommended_shift] += 1
                        days_with_recommendations += 1
                    elif shift is None:
                        actual_distribution['no_assignments'] += 1
                
                # Calculate distribution quality score
                target = self.teacher_target_patterns.get(teacher_id, self.preferred_pattern)
                actual = [teacher_distribution['shift1'], teacher_distribution['shift2'], teacher_distribution['shift3']]
                
                if sum(actual) > 0:
                    score = 100 - sum(abs(t - a) for t, a in zip(target, actual)) * 20
                    distribution_quality_scores.append(score)
                    
                    pattern_desc = f"{target[0]},{target[1]},{target[2]}"
                    f.write(f"Teacher {teacher_id}: S1={actual[0]}, S2={actual[1]}, S3={actual[2]} "
                           f"(Target pattern: {pattern_desc}) Score: {score:.1f}% "
                           f"[{forced_days} forced, {optimized_days} optimized]\n")
                    
                    if days_with_recommendations > 0:
                        recommended = [recommended_distribution['shift1'], recommended_distribution['shift2'], recommended_distribution['shift3']]
                        f.write(f"  -> Recommended shifts for days with no classes: S1={recommended[0]}, S2={recommended[1]}, S3={recommended[2]}\n")
            
            # Overall summary
            total_teacher_days = sum(actual_distribution[shift] for shift in ['shift1', 'shift2', 'shift3'])
            avg_quality_score = sum(distribution_quality_scores) / len(distribution_quality_scores) if distribution_quality_scores else 0
            
            f.write(f"\nOVERALL DISTRIBUTION SUMMARY:\n")
            f.write(f"  Total teacher-days with assignments: {total_teacher_days}\n")
            if total_teacher_days > 0:
                s1_pct = (actual_distribution['shift1'] / total_teacher_days) * 100
                s2_pct = (actual_distribution['shift2'] / total_teacher_days) * 100
                s3_pct = (actual_distribution['shift3'] / total_teacher_days) * 100
                
                f.write(f"  Shift 1: {actual_distribution['shift1']} days ({s1_pct:.1f}%)\n")
                f.write(f"  Shift 2: {actual_distribution['shift2']} days ({s2_pct:.1f}%)\n")  
                f.write(f"  Shift 3: {actual_distribution['shift3']} days ({s3_pct:.1f}%)\n")
                f.write(f"  Average distribution quality: {avg_quality_score:.1f}%\n")
                
                # Calculate overall balance score 
                target = 33.33
                overall_deviation = (abs(s1_pct - target) + abs(s2_pct - target) + abs(s3_pct - target)) / 3
                overall_balance = 100 - overall_deviation
                f.write(f"  Overall shift balance score: {overall_balance:.1f}% (target: 33.3% per shift)\n\n")
            
            # Department distribution analysis
            dept_stats = self._analyze_department_distributions()
            if dept_stats:
                f.write(f"\nDEPARTMENT-BASED DISTRIBUTION ANALYSIS:\n")
                f.write("-" * 60 + "\n")
                f.write(f"{'Department':<30} {'S1 %':>6} {'S2 %':>6} {'S3 %':>6} {'Balance':>8} {'Teachers':>8}\n")
                f.write("-" * 70 + "\n")
                
                for dept, stats in sorted(dept_stats.items(), key=lambda x: x[1]['balance_score'], reverse=True):
                    dept_name = dept[:28] + '..' if len(dept) > 30 else dept
                    f.write(f"{dept_name:<30} {stats['shift1_pct']:6.1f} {stats['shift2_pct']:6.1f} "
                           f"{stats['shift3_pct']:6.1f} {stats['balance_score']:8.1f} {stats['teacher_count']:8}\n")
            
            # Teacher shift patterns
            f.write("\nTEACHER WEEKLY SHIFT PATTERNS:\n")
            f.write("-" * 60 + "\n")
            f.write("Pattern Format: Tue->Wed->Thu->Fri->Sat\n")
            f.write("S1=Shift1, S2=Shift2, S3=Shift3, --=No classes, XX=Violation, [S1]=Recommended shift\n\n")
            
            for teacher_id, pattern in sorted(teacher_shift_patterns.items()):
                target = self.teacher_target_patterns.get(teacher_id, self.preferred_pattern)
                pattern_desc = f"{target[0]},{target[1]},{target[2]}"
                f.write(f"Teacher {teacher_id}: {pattern} (Target: {pattern_desc})\n")
            
            # Summary
            f.write(f"\n")
            if summary['status'] == 'PASS':
                f.write(f"[SUCCESS] All shift constraints satisfied! ({summary['compliance_rate']:.1f}% compliance)\n")
                f.write(f"Distribution quality: {avg_quality_score:.1f}% match to target patterns\n")
                if dept_stats:
                    avg_dept_balance = sum(stats['balance_score'] for stats in dept_stats.values()) / len(dept_stats)
                    f.write(f"Department balance: {avg_dept_balance:.1f}% (target: 33.3% per shift per department)\n")
            else:
                f.write(f"[FAILURE] {summary['total_violations']} violations found ({summary['compliance_rate']:.1f}% compliance)\n")

    def save_teacher_shift_data(self, verification_result: Dict[str, Any], output_dir: str) -> Dict[str, str]:
        """Save teacher shift data to files for use by visualizer."""
        import json
        import os
        import pandas as pd
        
        # Create file paths
        distribution_file = os.path.join(output_dir, 'teacher_shift_distributions.json')
        daily_shifts_file = os.path.join(output_dir, 'teacher_daily_shifts.csv')
        teacher_shifts_file = os.path.join(output_dir, 'teacher_shift_summary.csv')
        
        # Extract and convert teacher distribution information
        teacher_distribution_info = verification_result.get('teacher_distribution_info', {})
        
        # Convert numpy types to Python types for JSON serialization
        def convert_numpy_types(obj):
            """Recursively convert numpy types to Python types for JSON serialization."""
            if isinstance(obj, dict):
                return {str(k): convert_numpy_types(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert_numpy_types(item) for item in obj]
            elif hasattr(obj, 'item'):  # numpy scalar types
                return obj.item()
            else:
                return obj
        
        # Convert the distribution info
        teacher_distribution_info = convert_numpy_types(teacher_distribution_info)
        
        # Save distribution data as JSON
        try:
            with open(distribution_file, 'w', encoding='utf-8') as f:
                json.dump(teacher_distribution_info, f, indent=2, ensure_ascii=False)
            self.logger.info(f"Teacher shift distributions saved to: {distribution_file}")
        except Exception as e:
            self.logger.error(f"Failed to save distribution data: {e}")
        
        # Convert daily shifts data to DataFrame for CSV
        daily_shifts_data = []
        teacher_daily_shifts = verification_result.get('teacher_daily_shifts', {})
        
        for teacher_id, daily_data in teacher_daily_shifts.items():
            for day, shift_info in daily_data.items():
                daily_shifts_data.append({
                    'teacher_id': str(teacher_id),
                    'day': day,
                    'shift': shift_info.get('shift', 'no_classes'),
                    'shift_name': shift_info.get('shift_name', 'No Classes'),
                    'slot_range': shift_info.get('slot_range', 'None'),
                    'min_slot': shift_info.get('min_slot', ''),
                    'max_slot': shift_info.get('max_slot', ''),
                    'recommended_shift': shift_info.get('recommended_shift', '')
                })
        
        # Save daily shifts as CSV
        try:
            if daily_shifts_data:
                daily_shifts_df = pd.DataFrame(daily_shifts_data)
                daily_shifts_df.to_csv(daily_shifts_file, index=False)
                self.logger.info(f"Teacher daily shifts saved to: {daily_shifts_file}")
        except Exception as e:
            self.logger.error(f"Failed to save daily shifts data: {e}")
        
        # Generate comprehensive teacher shift summary CSV
        try:
            teacher_shift_summary = []
            
            # Extract teacher department info from schedule data if available
            teacher_departments = {}
            schedule_data = verification_result.get('schedule_data', [])
            if schedule_data:
                for item in schedule_data:
                    teacher_id = item.get('teacher_id')
                    dept = item.get('course_dept', 'Unknown')
                    if teacher_id:
                        teacher_departments[str(teacher_id)] = dept
            
            for teacher_id, info in teacher_distribution_info.items():
                # Get actual distribution
                actual_dist = info.get('actual_distribution', {})
                target_dist = info.get('target_distribution', [0, 0, 0])
                
                # Get shifts for each day of the week
                daily_shifts = info.get('daily_shifts', {})
                tue_shift = self._get_shift_display(daily_shifts.get('tuesday', {}))
                wed_shift = self._get_shift_display(daily_shifts.get('wed', {}))
                thu_shift = self._get_shift_display(daily_shifts.get('thur', {}))
                fri_shift = self._get_shift_display(daily_shifts.get('fri', {}))
                sat_shift = self._get_shift_display(daily_shifts.get('sat', {}))
                
                # Count recommended shifts
                recommended = {
                    'shift1': 0, 'shift2': 0, 'shift3': 0
                }
                for day, shift_data in daily_shifts.items():
                    if shift_data.get('shift') == 'no_classes' and 'recommended_shift' in shift_data:
                        rec_shift = shift_data['recommended_shift']
                        recommended[rec_shift] = recommended.get(rec_shift, 0) + 1
                
                # Get department info
                department = teacher_departments.get(teacher_id, 'Unknown')
                
                # Create summary record
                teacher_shift_summary.append({
                    'teacher_id': teacher_id,
                    'department': department,
                    'weekly_pattern': info.get('weekly_pattern', ''),
                    'target_s1': target_dist[0],
                    'target_s2': target_dist[1],
                    'target_s3': target_dist[2],
                    'actual_s1': actual_dist.get('shift1', 0),
                    'actual_s2': actual_dist.get('shift2', 0),
                    'actual_s3': actual_dist.get('shift3', 0),
                    'rec_s1': recommended.get('shift1', 0),
                    'rec_s2': recommended.get('shift2', 0),
                    'rec_s3': recommended.get('shift3', 0),
                    'tuesday': tue_shift,
                    'wednesday': wed_shift,
                    'thursday': thu_shift,
                    'friday': fri_shift,
                    'saturday': sat_shift,
                    'compliance': info.get('distribution_compliance', 0),
                    'no_classes': actual_dist.get('no_classes', 0),
                    'invalid_shifts': actual_dist.get('invalid', 0)
                })
            
            # Create and save the summary DataFrame
            if teacher_shift_summary:
                summary_df = pd.DataFrame(teacher_shift_summary)
                summary_df.to_csv(teacher_shifts_file, index=False)
                self.logger.info(f"Comprehensive teacher shift summary saved to: {teacher_shifts_file}")
        except Exception as e:
            self.logger.error(f"Failed to save teacher shift summary: {e}")
        
        return {
            'distributions_file': distribution_file,
            'daily_shifts_file': daily_shifts_file,
            'teacher_shifts_file': teacher_shifts_file
        }
    
    def _get_shift_display(self, shift_info):
        """Get displayable shift information from shift info dictionary."""
        if not shift_info:
            return '--'
            
        shift = shift_info.get('shift')
        
        if shift == 'invalid':
            return 'XX'
        elif shift == 'no_classes' and 'recommended_shift' in shift_info:
            rec_shift = shift_info['recommended_shift'].replace('shift', 'S')
            return f"[{rec_shift}]"
        elif shift and shift != 'no_classes':
            return shift.replace('shift', 'S')
        else:
            return '--' 