#!/usr/bin/env python3
"""
Shift Report Generator

This module generates comprehensive reports about staff campus presence duration and shift violations.
It analyzes how long each staff member stays on campus each day by combining their theory and lab schedules,
and identifies violations based on predefined and normalized shift patterns.
"""

import os
import json
import pandas as pd
import numpy as np
from datetime import datetime
from collections import defaultdict, Counter
import matplotlib.pyplot as plt
import seaborn as sns
from typing import Dict, List, Tuple, Any

class ShiftReportGenerator:
    """Generates comprehensive shift-related reports based on daily campus presence."""
    
    def __init__(self, output_dir: str):
        """
        Initialize the shift report generator.
        
        Args:
            output_dir: Directory where reports will be saved.
        """
        self.output_dir = output_dir
        self.shift_reports_dir = os.path.join(output_dir, 'shift_reports')
        os.makedirs(self.shift_reports_dir, exist_ok=True)
        
        # Define campus presence categories with descriptions and colors for reports
        self.presence_categories = {
            'optimal': {'description': 'Optimal campus presence (e.g., 8-3, 10-5, 12-7)', 'color': '#2ecc71'},
            'medium': {'description': 'Medium campus presence (e.g., 8-5, 10-7)', 'color': '#f39c12'},
            'violation': {'description': 'Violation: Extended presence (e.g., 8-7)', 'color': '#e74c3c'}
        }
    
    def _parse_time_to_minutes(self, time_str: str) -> int:
        """
        Convert time string (HH:MM) to minutes since midnight.
        Handles 12-hour PM times by converting hours 1-7 to 13-19.
        """
        try:
            if ':' in time_str:
                parts = time_str.split(':')
                hours = int(float(parts[0]))
                if 1 <= hours <= 7:
                    hours += 12
                minutes = int(float(parts[1]))
                return hours * 60 + minutes
            return 0
        except (ValueError, IndexError):
            return 0
    
    def _minutes_to_time(self, minutes: int) -> str:
        """Convert minutes since midnight back to a time string (H:MM)."""
        if minutes is None or not np.isfinite(minutes): return "N/A"
        hours = int(minutes // 60)
        mins = int(minutes % 60)
        return f"{hours}:{mins:02d}"
    
    def _extract_time_from_slot(self, time_slot: str) -> Tuple[int, int]:
        """Extract start and end times from various time slot string formats."""
        try:
            if ' to ' in time_slot:
                parts = time_slot.split(' to ')
                start_part, end_part = parts[0].split(' - ')[0], parts[-1].split(' - ')[-1]
            elif ' - ' in time_slot:
                parts = time_slot.split(' - ')
                start_part, end_part = parts[0], parts[1]
            else:
                return 0, 0
            
            return self._parse_time_to_minutes(start_part.strip()), self._parse_time_to_minutes(end_part.strip())
        except (ValueError, IndexError):
            return 0, 0

    def _normalize_start_hour(self, hour: int) -> int:
        """
        Normalize the actual start hour to a standard shift block for categorization.
        This is the core of the new logic requested by the user.
        """
        if hour <= 9:  # Any start at 8:xx or 9:xx is considered the 8 AM block
            return 8
        if hour <= 11: # Any start at 10:xx or 11:xx is considered the 10 AM block
            return 10
        # Any start at 12:xx or later is considered the 12 PM block
        return 12
    
    def _categorize_campus_presence(self, normalized_start_hour: int, end_hour: int) -> str:
        """Categorize campus presence based on the NORMALIZED start hour."""
        if normalized_start_hour <= 8 and end_hour >= 19:
            return 'violation'
        if (normalized_start_hour <= 8 and end_hour >= 17) or (normalized_start_hour >= 10 and end_hour >= 19):
            return 'medium'
        if (normalized_start_hour >= 8 and end_hour <= 15) or \
           (normalized_start_hour >= 10 and end_hour <= 17) or \
           (normalized_start_hour >= 12 and end_hour <= 19):
            return 'optimal'
        return 'optimal' # Default for short/irregular shifts
    
    def generate_shift_reports(self, lab_schedule: List[Dict], theory_schedule: List[Dict]) -> Dict[str, Any]:
        """Generate comprehensive shift reports by combining lab and theory schedules."""
        print("🔍 Generating shift reports with new normalization logic...")
        combined_schedule = lab_schedule + theory_schedule
        if not combined_schedule:
            print("⚠️ No schedule data provided. Skipping shift report generation.")
            return {}
            
        reports = {}
        reports['daily_campus_presence'] = self._analyze_daily_campus_presence(combined_schedule)
        reports['staff_violations'] = self._analyze_staff_violations(reports['daily_campus_presence'])
        reports['department_patterns'] = self._analyze_department_presence_patterns(reports['daily_campus_presence'], combined_schedule)
        reports['weekly_summary'] = self._analyze_weekly_presence_summary(reports['daily_campus_presence'])
        
        self._save_reports(reports)
        self._generate_shift_visualizations(reports)
        
        print(f"✅ Shift reports generated successfully in: {self.shift_reports_dir}")
        return reports
    
    def _analyze_daily_campus_presence(self, schedule: List[Dict]) -> Dict[str, Any]:
        """Analyze daily campus presence, applying the new start hour normalization rule."""
        print("  📊 Analyzing daily campus presence...")
        staff_daily_presence = defaultdict(lambda: defaultdict(lambda: {
            'earliest_start': float('inf'), 'latest_end': float('-inf'),
            'sessions': [], 'total_sessions': 0
        }))
        
        for session in schedule:
            staff_code = session.get('staff_code')
            if not staff_code or pd.isna(staff_code): continue

            day = session.get('day', 'Unknown').lower()
            time_slot = session.get('time_slot', session.get('time_range', 'Unknown'))
            start_minutes, end_minutes = self._extract_time_from_slot(time_slot)
            if start_minutes == 0 and end_minutes == 0: continue
            
            day_data = staff_daily_presence[staff_code][day]
            day_data['earliest_start'] = min(day_data['earliest_start'], start_minutes)
            day_data['latest_end'] = max(day_data['latest_end'], end_minutes)
            day_data['sessions'].append({'time_slot': time_slot, 'course_code': session.get('course_code', 'N/A')})
            day_data['total_sessions'] += 1
            if 'staff_name' not in day_data:
                day_data['staff_name'] = session.get('teacher_name', 'Unknown')
        
        presence_analysis = {}
        for staff_code, daily_data in staff_daily_presence.items():
            first_day_key = next(iter(daily_data), None)
            staff_analysis = {
                'staff_code': staff_code,
                'staff_name': daily_data[first_day_key].get('staff_name', 'Unknown') if first_day_key else 'Unknown',
                'daily_presence': {},
                'total_days_worked': 0, 'violation_days': 0, 'medium_days': 0, 'optimal_days': 0
            }
            for day, day_data in daily_data.items():
                if day_data['earliest_start'] != float('inf'):
                    earliest_start_min, latest_end_min = day_data['earliest_start'], day_data['latest_end']
                    actual_start_hour = earliest_start_min // 60
                    latest_hour = (latest_end_min + 59) // 60
                    
                    # Apply the new normalization rule
                    normalized_start_hour = self._normalize_start_hour(actual_start_hour)
                    category = self._categorize_campus_presence(normalized_start_hour, latest_hour)
                    
                    staff_analysis['daily_presence'][day] = {
                        'earliest_start': self._minutes_to_time(earliest_start_min),
                        'latest_end': self._minutes_to_time(latest_end_min),
                        'actual_start_hour': actual_start_hour,
                        'latest_hour': latest_hour,
                        'presence_pattern': f"{normalized_start_hour}-{latest_hour}",
                        'category': category,
                        'total_sessions': day_data['total_sessions']
                    }
                    staff_analysis['total_days_worked'] += 1
                    staff_analysis[f"{category}_days"] += 1
            presence_analysis[staff_code] = staff_analysis
        return presence_analysis

    def _analyze_staff_violations(self, daily_presence: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze and summarize staff violations based on the daily presence data."""
        print("  📊 Analyzing staff violations...")
        violations, summary = [], {'total_violation_instances': 0, 'staff_with_violations': 0, 'violation_days': Counter(), 'worst_offenders': []}
        for staff_code, staff_data in daily_presence.items():
            if staff_data['violation_days'] > 0:
                for day, day_data in staff_data['daily_presence'].items():
                    if day_data['category'] == 'violation':
                        violations.append({'staff_code': staff_code, 'staff_name': staff_data['staff_name'], 'day': day, **day_data})
                        summary['violation_days'][day] += 1
                summary['worst_offenders'].append({'staff_code': staff_code, 'staff_name': staff_data['staff_name'], 'violation_count': staff_data['violation_days']})
        
        summary.update({'total_violation_instances': len(violations), 'staff_with_violations': len(summary['worst_offenders'])})
        summary['worst_offenders'].sort(key=lambda x: x['violation_count'], reverse=True)
        summary['violation_days'] = dict(summary['violation_days'])
        return {'violations': violations, 'summary': summary}

    def _analyze_department_presence_patterns(self, daily_presence: Dict[str, Any], schedule: List[Dict]) -> Dict[str, Any]:
        """Analyze presence patterns grouped by department."""
        print("  📊 Analyzing department presence patterns...")
        staff_dept_mapping = {s['staff_code']: s.get('department', 'Unknown') for s in schedule if s.get('staff_code')}
        dept_patterns = defaultdict(lambda: {'staff_count': set(), 'total_violations': 0, 'total_medium': 0, 'total_optimal': 0})
        for staff_code, staff_data in daily_presence.items():
            department = staff_dept_mapping.get(staff_code, 'Unknown')
            dept_patterns[department]['staff_count'].add(staff_code)
            dept_patterns[department]['total_violations'] += staff_data['violation_days']
            dept_patterns[department]['total_medium'] += staff_data['medium_days']
            dept_patterns[department]['total_optimal'] += staff_data['optimal_days']
        return {dept: {**data, 'staff_count': len(data['staff_count'])} for dept, data in dept_patterns.items()}

    def _analyze_weekly_presence_summary(self, daily_presence: Dict[str, Any]) -> Dict[str, Any]:
        """Create a weekly summary of presence across all staff."""
        print("  📊 Analyzing weekly presence summary...")
        stats = {'total_staff': len(daily_presence), 'total_presence_instances': 0, 'category_distribution': Counter()}
        for staff_data in daily_presence.values():
            stats['total_presence_instances'] += staff_data['total_days_worked']
            stats['category_distribution'].update({'optimal': staff_data['optimal_days'], 'medium': staff_data['medium_days'], 'violation': staff_data['violation_days']})
        stats['category_distribution'] = dict(stats['category_distribution'])
        return stats

    def _save_reports(self, reports: Dict[str, Any]):
        """Save all generated reports, creating both timestamped and 'latest' versions."""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        for report_name, report_data in reports.items():
            latest_path = os.path.join(self.shift_reports_dir, f'{report_name}_latest.json')
            with open(latest_path, 'w', encoding='utf-8') as f: json.dump(report_data, f, indent=2, default=str)
        self._generate_teacher_dashboard_data(reports)

    def _generate_teacher_dashboard_data(self, reports: Dict[str, Any]):
        """Generate the specific JSON file needed for the teacher shift dashboard UI."""
        dashboard_data = {}
        for staff_code, staff_data in reports['daily_campus_presence'].items():
            days_worked = staff_data['total_days_worked']
            if days_worked == 0: continue
            
            all_starts = [d['earliest_start'] for d in staff_data['daily_presence'].values()]
            all_ends = [d['latest_end'] for d in staff_data['daily_presence'].values()]
            
            dashboard_data[staff_code] = {
                'staff_code': staff_code, 'staff_name': staff_data['staff_name'],
                'total_sessions': sum(d['total_sessions'] for d in staff_data['daily_presence'].values()),
                'days_worked': days_worked,
                'shift_distribution': {'optimal': staff_data['optimal_days'], 'medium': staff_data['medium_days'], 'violation': staff_data['violation_days']},
                'leave_time_instances': {
                    'leave_3pm': sum(1 for d in staff_data['daily_presence'].values() if d['latest_hour'] <= 15),
                    'leave_5pm': sum(1 for d in staff_data['daily_presence'].values() if 15 < d['latest_hour'] <= 17),
                    'leave_7pm': sum(1 for d in staff_data['daily_presence'].values() if d['latest_hour'] > 17)
                },
                'work_hours': {'earliest_start': min(all_starts) if all_starts else "N/A", 'latest_end': max(all_ends) if all_ends else "N/A"},
                'shift_consistency_score': (staff_data['optimal_days'] / days_worked * 100) if days_worked > 0 else 100
            }
        
        dashboard_file_latest = os.path.join(self.shift_reports_dir, 'teacher_shift_dashboard_latest.json')
        with open(dashboard_file_latest, 'w', encoding='utf-8') as f: json.dump(dashboard_data, f, indent=2, default=str)

    def _generate_shift_visualizations(self, reports: Dict[str, Any]):
        """Generate and save visualizations for the shift analysis."""
        print("  📈 Generating shift visualizations...")
        viz_dir = os.path.join(self.shift_reports_dir, 'visualizations')
        os.makedirs(viz_dir, exist_ok=True)
        
        # Plot 1: Overall Category Distribution
        weekly_data = reports['weekly_summary']['category_distribution']
        if sum(weekly_data.values()) > 0:
            labels = [k.title() for k in weekly_data.keys()]
            sizes = list(weekly_data.values())
            colors = [self.presence_categories[k]['color'] for k in weekly_data.keys()]
            plt.figure(figsize=(8, 8))
            plt.pie(sizes, labels=labels, colors=colors, autopct='%1.1f%%', startangle=90)
            plt.title('Campus Presence Category Distribution', fontsize=16)
            plt.axis('equal')
            plt.savefig(os.path.join(viz_dir, 'category_distribution.png'))
            plt.close()

        # Plot 2: Department Patterns
        dept_data = reports.get('department_patterns')
        if dept_data:
            df = pd.DataFrame(dept_data).T[['total_optimal', 'total_medium', 'total_violations']].rename(columns={
                'total_optimal': 'Optimal', 'total_medium': 'Medium', 'total_violations': 'Violations'
            })
            df.plot(kind='bar', stacked=True, figsize=(12, 7), color=[self.presence_categories[c]['color'] for c in ['optimal', 'medium', 'violation']])
            plt.title('Presence Patterns by Department', fontsize=16)
            plt.ylabel('Number of Person-Days')
            plt.xlabel('Department')
            plt.xticks(rotation=45, ha='right')
            plt.tight_layout()
            plt.savefig(os.path.join(viz_dir, 'department_patterns.png'))
            plt.close()