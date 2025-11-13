#!/usr/bin/env python3
"""
Combined Schedule Conflict Analyzer

This script provides detailed conflict analysis for the combined schedule,
focusing on identifying and visualizing different types of conflicts:
1. Teacher-level conflicts
2. Room-level conflicts  
3. Group-level conflicts
4. Time-based conflicts
"""

import os
import sys
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from collections import defaultdict
import json

class CombinedConflictAnalyzer:
    def __init__(self, lab_schedule_path, theory_schedule_path):
        self.lab_schedule = pd.read_csv(lab_schedule_path) if os.path.exists(lab_schedule_path) else None
        self.theory_schedule = pd.read_csv(theory_schedule_path) if os.path.exists(theory_schedule_path) else None
        
        self.days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
        self.conflicts = {
            'teacher_conflicts': [],
            'room_conflicts': [],
            'group_conflicts': [],
            'time_conflicts': []
        }
        
    def analyze_teacher_conflicts(self):
        """Analyze conflicts at the teacher level."""
        print("🔍 Analyzing Teacher Conflicts...")
        
        if self.lab_schedule is None or self.theory_schedule is None:
            print("   ⚠️ Missing schedule data")
            return
        
        # Build teacher schedule map
        teacher_schedules = defaultdict(lambda: defaultdict(list))
        
        # Add lab sessions
        for _, session in self.lab_schedule.iterrows():
            teacher_id = session['teacher_id']
            day = session['day']
            session_name = session.get('session_name', '')
            
            teacher_schedules[teacher_id][day].append({
                'type': 'LAB',
                'course': session['course_code'],
                'session': session_name,
                'time': self._get_lab_session_time(session_name),
                'room': session.get('room_number', f"R{session['room_id']}")
            })
        
        # Add theory sessions
        for _, session in self.theory_schedule.iterrows():
            teacher_id = session['teacher_id']
            day = session['day']
            time_slot = session.get('time_slot', '')
            
            teacher_schedules[teacher_id][day].append({
                'type': 'THEORY',
                'course': session['course_code'],
                'session': session.get('session_type', 'lecture'),
                'time': time_slot,
                'room': session.get('room_number', f"R{session['room_id']}")
            })
        
        # Detect conflicts
        for teacher_id, daily_schedule in teacher_schedules.items():
            for day, sessions in daily_schedule.items():
                conflicts = self._find_time_overlaps(sessions)
                for conflict in conflicts:
                    self.conflicts['teacher_conflicts'].append({
                        'teacher_id': teacher_id,
                        'day': day,
                        'conflict_type': 'TEACHER_DOUBLE_BOOKING',
                        'session1': conflict['session1'],
                        'session2': conflict['session2'],
                        'severity': 'HIGH'
                    })
        
        print(f"   Found {len(self.conflicts['teacher_conflicts'])} teacher conflicts")
    
    def analyze_room_conflicts(self):
        """Analyze conflicts at the room level."""
        print("🔍 Analyzing Room Conflicts...")
        
        if self.lab_schedule is None or self.theory_schedule is None:
            print("   ⚠️ Missing schedule data")
            return
        
        # Build room schedule map
        room_schedules = defaultdict(lambda: defaultdict(list))
        
        # Add lab sessions
        for _, session in self.lab_schedule.iterrows():
            room_id = session['room_id']
            day = session['day']
            session_name = session.get('session_name', '')
            
            room_schedules[room_id][day].append({
                'type': 'LAB',
                'course': session['course_code'],
                'teacher': session['teacher_id'],
                'session': session_name,
                'time': self._get_lab_session_time(session_name)
            })
        
        # Add theory sessions
        for _, session in self.theory_schedule.iterrows():
            room_id = session['room_id']
            day = session['day']
            time_slot = session.get('time_slot', '')
            
            room_schedules[room_id][day].append({
                'type': 'THEORY',
                'course': session['course_code'],
                'teacher': session['teacher_id'],
                'session': session.get('session_type', 'lecture'),
                'time': time_slot
            })
        
        # Detect conflicts
        for room_id, daily_schedule in room_schedules.items():
            for day, sessions in daily_schedule.items():
                conflicts = self._find_time_overlaps(sessions)
                for conflict in conflicts:
                    self.conflicts['room_conflicts'].append({
                        'room_id': room_id,
                        'day': day,
                        'conflict_type': 'ROOM_DOUBLE_BOOKING',
                        'session1': conflict['session1'],
                        'session2': conflict['session2'],
                        'severity': 'HIGH'
                    })
        
        print(f"   Found {len(self.conflicts['room_conflicts'])} room conflicts")
    
    def analyze_group_conflicts(self):
        """Analyze conflicts at the group level (same dept/semester)."""
        print("🔍 Analyzing Group Conflicts...")
        
        if self.lab_schedule is None or self.theory_schedule is None:
            print("   ⚠️ Missing schedule data")
            return
        
        # Group sessions by department and semester
        dept_sem_groups = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
        
        # Add lab sessions
        for _, session in self.lab_schedule.iterrows():
            dept = session.get('department', 'Unknown')
            semester = session.get('semester', 0)
            group_index = session.get('group_index', 0)
            day = session['day']
            
            if dept != 'Unknown' and semester > 0:
                dept_sem_groups[(dept, semester)][group_index][day].append({
                    'type': 'LAB',
                    'course': session['course_code'],
                    'session': session.get('session_name', ''),
                    'time': self._get_lab_session_time(session.get('session_name', ''))
                })
        
        # Add theory sessions
        for _, session in self.theory_schedule.iterrows():
            dept = session.get('department', 'Unknown')
            semester = session.get('semester', 0)
            group_index = session.get('group_index', 0)
            day = session['day']
            
            if dept != 'Unknown' and semester > 0:
                dept_sem_groups[(dept, semester)][group_index][day].append({
                    'type': 'THEORY',
                    'course': session['course_code'],
                    'session': session.get('session_type', 'lecture'),
                    'time': session.get('time_slot', '')
                })
        
        # Detect group conflicts (same group cannot have overlapping sessions)
        for (dept, semester), groups in dept_sem_groups.items():
            for group_index, daily_sessions in groups.items():
                for day, sessions in daily_sessions.items():
                    conflicts = self._find_time_overlaps(sessions)
                    for conflict in conflicts:
                        self.conflicts['group_conflicts'].append({
                            'department': dept,
                            'semester': semester,
                            'group_index': group_index,
                            'day': day,
                            'conflict_type': 'GROUP_OVERLAP',
                            'session1': conflict['session1'],
                            'session2': conflict['session2'],
                            'severity': 'MEDIUM'
                        })
        
        print(f"   Found {len(self.conflicts['group_conflicts'])} group conflicts")
    
    def _get_lab_session_time(self, session_name):
        """Get time range for lab session."""
        lab_times = {
            'L1': '8:00-10:00',
            'L2': '10:00-12:00', 
            'L3': '12:00-14:00',
            'L4': '14:00-16:00',
            'L5': '16:00-18:00',
            'L6': '18:00-20:00'
        }
        return lab_times.get(session_name, 'Unknown')
    
    def _find_time_overlaps(self, sessions):
        """Find overlapping time slots in a list of sessions."""
        conflicts = []
        
        for i in range(len(sessions)):
            for j in range(i + 1, len(sessions)):
                session1 = sessions[i]
                session2 = sessions[j]
                
                if self._sessions_overlap(session1['time'], session2['time']):
                    conflicts.append({
                        'session1': session1,
                        'session2': session2
                    })
        
        return conflicts
    
    def _sessions_overlap(self, time1, time2):
        """Check if two time slots overlap."""
        if not time1 or not time2 or time1 == 'Unknown' or time2 == 'Unknown':
            return False
        
        def parse_time_range(time_str):
            try:
                if '-' in time_str:
                    parts = time_str.split('-')
                    if len(parts) == 2:
                        start = self._time_to_minutes(parts[0].strip())
                        end = self._time_to_minutes(parts[1].strip())
                        return start, end
                else:
                    # Single time slot (theory), assume 50 minutes
                    if ' - ' in time_str:
                        start_str = time_str.split(' - ')[0]
                        start = self._time_to_minutes(start_str)
                        end = start + 50 if start is not None else None
                        return start, end
                    else:
                        start = self._time_to_minutes(time_str)
                        end = start + 50 if start is not None else None
                        return start, end
            except:
                return None, None
            return None, None
        
        start1, end1 = parse_time_range(time1)
        start2, end2 = parse_time_range(time2)
        
        if None in [start1, end1, start2, end2]:
            return False
        
        return start1 < end2 and start2 < end1
    
    def _time_to_minutes(self, time_str):
        """Convert time string to minutes since midnight."""
        try:
            hour, minute = map(int, time_str.split(':'))
            return hour * 60 + minute
        except:
            return None
    
    def generate_conflict_visualizations(self, output_dir="src/data_analytics/combined_analytics/visualizations"):
        """Generate visualizations for detected conflicts."""
        print("📊 Generating Conflict Visualizations...")
        
        os.makedirs(output_dir, exist_ok=True)
        
        # Conflict summary chart
        self._create_conflict_summary_chart(output_dir)
        
        # Teacher conflict heatmap
        self._create_teacher_conflict_heatmap(output_dir)
        
        # Room utilization chart
        self._create_room_utilization_chart(output_dir)
        
        # Timeline conflict view
        self._create_timeline_conflict_view(output_dir)
        
        print(f"✅ Visualizations saved to {output_dir}")
    
    def _create_conflict_summary_chart(self, output_dir):
        """Create a summary chart of all conflicts."""
        conflict_counts = {
            'Teacher Conflicts': len(self.conflicts['teacher_conflicts']),
            'Room Conflicts': len(self.conflicts['room_conflicts']),
            'Group Conflicts': len(self.conflicts['group_conflicts']),
            'Time Conflicts': len(self.conflicts['time_conflicts'])
        }
        
        plt.figure(figsize=(10, 6))
        bars = plt.bar(conflict_counts.keys(), conflict_counts.values(), 
                      color=['red', 'orange', 'yellow', 'blue'])
        
        plt.title('Combined Schedule Conflict Summary', fontsize=16, fontweight='bold')
        plt.ylabel('Number of Conflicts')
        plt.xticks(rotation=45)
        
        # Add value labels on bars
        for bar in bars:
            height = bar.get_height()
            plt.text(bar.get_x() + bar.get_width()/2., height,
                    f'{int(height)}', ha='center', va='bottom')
        
        plt.tight_layout()
        plt.savefig(os.path.join(output_dir, 'conflict_summary.png'), dpi=150, bbox_inches='tight')
        plt.close()
    
    def _create_teacher_conflict_heatmap(self, output_dir):
        """Create a heatmap showing teacher conflicts by day and time."""
        if not self.conflicts['teacher_conflicts']:
            return
        
        # Create conflict matrix
        teachers = set()
        for conflict in self.conflicts['teacher_conflicts']:
            teachers.add(conflict['teacher_id'])
        
        teacher_list = sorted(teachers)
        conflict_matrix = np.zeros((len(teacher_list), len(self.days)))
        
        for conflict in self.conflicts['teacher_conflicts']:
            teacher_idx = teacher_list.index(conflict['teacher_id'])
            day_idx = self.days.index(conflict['day']) if conflict['day'] in self.days else -1
            if day_idx >= 0:
                conflict_matrix[teacher_idx, day_idx] += 1
        
        plt.figure(figsize=(10, max(6, len(teacher_list) * 0.3)))
        sns.heatmap(conflict_matrix, 
                   xticklabels=self.days,
                   yticklabels=[f'T{t}' for t in teacher_list],
                   annot=True, fmt='g', cmap='Reds')
        
        plt.title('Teacher Conflicts by Day', fontsize=14, fontweight='bold')
        plt.xlabel('Day')
        plt.ylabel('Teacher')
        plt.tight_layout()
        plt.savefig(os.path.join(output_dir, 'teacher_conflicts_heatmap.png'), dpi=150, bbox_inches='tight')
        plt.close()
    
    def _create_room_utilization_chart(self, output_dir):
        """Create a chart showing room utilization and conflicts."""
        if self.lab_schedule is None and self.theory_schedule is None:
            return
        
        room_usage = defaultdict(int)
        room_conflicts = defaultdict(int)
        
        # Count room usage
        if self.lab_schedule is not None:
            for _, session in self.lab_schedule.iterrows():
                room_usage[session['room_id']] += 1
        
        if self.theory_schedule is not None:
            for _, session in self.theory_schedule.iterrows():
                room_usage[session['room_id']] += 1
        
        # Count room conflicts
        for conflict in self.conflicts['room_conflicts']:
            room_conflicts[conflict['room_id']] += 1
        
        rooms = sorted(room_usage.keys())
        usage_counts = [room_usage[room] for room in rooms]
        conflict_counts = [room_conflicts[room] for room in rooms]
        
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10))
        
        # Room usage
        ax1.bar(range(len(rooms)), usage_counts, color='lightblue')
        ax1.set_title('Room Usage Distribution', fontsize=14, fontweight='bold')
        ax1.set_xlabel('Room ID')
        ax1.set_ylabel('Number of Sessions')
        ax1.set_xticks(range(len(rooms)))
        ax1.set_xticklabels([f'R{r}' for r in rooms], rotation=45)
        
        # Room conflicts
        ax2.bar(range(len(rooms)), conflict_counts, color='red', alpha=0.7)
        ax2.set_title('Room Conflicts Distribution', fontsize=14, fontweight='bold')
        ax2.set_xlabel('Room ID')
        ax2.set_ylabel('Number of Conflicts')
        ax2.set_xticks(range(len(rooms)))
        ax2.set_xticklabels([f'R{r}' for r in rooms], rotation=45)
        
        plt.tight_layout()
        plt.savefig(os.path.join(output_dir, 'room_utilization_conflicts.png'), dpi=150, bbox_inches='tight')
        plt.close()
    
    def _create_timeline_conflict_view(self, output_dir):
        """Create a timeline view showing conflicts throughout the week."""
        # This would create a detailed timeline visualization
        # For now, create a simple conflict distribution by day
        
        day_conflicts = defaultdict(int)
        
        for conflict_type, conflicts in self.conflicts.items():
            for conflict in conflicts:
                day = conflict.get('day', 'Unknown')
                if day in self.days:
                    day_conflicts[day] += 1
        
        plt.figure(figsize=(10, 6))
        days = list(day_conflicts.keys())
        counts = list(day_conflicts.values())
        
        plt.bar(days, counts, color='coral')
        plt.title('Conflicts Distribution by Day', fontsize=14, fontweight='bold')
        plt.xlabel('Day')
        plt.ylabel('Number of Conflicts')
        plt.xticks(rotation=45)
        
        # Add value labels
        for i, count in enumerate(counts):
            plt.text(i, count, str(count), ha='center', va='bottom')
        
        plt.tight_layout()
        plt.savefig(os.path.join(output_dir, 'conflicts_by_day.png'), dpi=150, bbox_inches='tight')
        plt.close()
    
    def generate_conflict_report(self, output_dir="src/data_analytics/combined_analytics/conflict_analysis"):
        """Generate a comprehensive conflict analysis report."""
        print("📋 Generating Conflict Analysis Report...")
        
        os.makedirs(output_dir, exist_ok=True)
        
        # Run all analyses
        self.analyze_teacher_conflicts()
        self.analyze_room_conflicts()
        self.analyze_group_conflicts()
        
        # Generate visualizations
        self.generate_conflict_visualizations()
        
        # Create detailed report
        report_path = os.path.join(output_dir, "conflict_analysis_report.txt")
        with open(report_path, 'w') as f:
            f.write("COMBINED SCHEDULE CONFLICT ANALYSIS REPORT\n")
            f.write("=" * 60 + "\n")
            f.write(f"Generated: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            
            # Summary
            total_conflicts = sum(len(conflicts) for conflicts in self.conflicts.values())
            f.write(f"SUMMARY:\n")
            f.write(f"Total Conflicts: {total_conflicts}\n")
            f.write(f"- Teacher Conflicts: {len(self.conflicts['teacher_conflicts'])}\n")
            f.write(f"- Room Conflicts: {len(self.conflicts['room_conflicts'])}\n")
            f.write(f"- Group Conflicts: {len(self.conflicts['group_conflicts'])}\n")
            f.write(f"- Time Conflicts: {len(self.conflicts['time_conflicts'])}\n\n")
            
            # Detailed conflicts
            for conflict_type, conflicts in self.conflicts.items():
                if conflicts:
                    f.write(f"{conflict_type.upper().replace('_', ' ')}:\n")
                    f.write("-" * 40 + "\n")
                    for i, conflict in enumerate(conflicts[:10], 1):  # Show first 10
                        f.write(f"{i}. {conflict.get('conflict_type', 'Unknown')}\n")
                        f.write(f"   Details: {str(conflict)}\n\n")
                    if len(conflicts) > 10:
                        f.write(f"   ... and {len(conflicts) - 10} more conflicts\n\n")
        
        # Save conflicts as JSON for further analysis
        json_path = os.path.join(output_dir, "conflicts.json")
        with open(json_path, 'w') as f:
            json.dump(self.conflicts, f, indent=2, default=str)
        
        print(f"✅ Conflict analysis report saved to {report_path}")
        print(f"✅ Conflicts data saved to {json_path}")
        
        return total_conflicts == 0, self.conflicts

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
    
    analyzer = CombinedConflictAnalyzer(lab_path, theory_path)
    success, conflicts = analyzer.generate_conflict_report()
    
    total_conflicts = sum(len(conflict_list) for conflict_list in conflicts.values())
    print(f"\n🎯 Conflict Analysis: {'✅ NO CONFLICTS' if success else '❌ CONFLICTS FOUND'}")
    print(f"Total conflicts: {total_conflicts}")
    
    return 0 if success else 1

if __name__ == "__main__":
    exit(main()) 