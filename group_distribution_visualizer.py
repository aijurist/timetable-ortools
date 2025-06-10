#!/usr/bin/env python3
"""
Group Distribution Visualizer
Generates timetable format visualizations showing theory and lab group distributions
"""

import os
import json
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np
from collections import defaultdict
from datetime import datetime

class GroupDistributionVisualizer:
    def __init__(self, output_dir='group_distributions'):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        
        # Time slots mapping
        self.theory_time_slots = [
            "8:00 - 8:50", "9:00 - 9:50", "10:00 - 10:50", "11:00 - 11:50",
            "12:00 - 12:50", "1:00 - 1:50", "2:00 - 2:50", "3:00 - 3:50", 
            "4:00 - 4:50", "5:00 - 5:50", "6:00 - 6:50"
        ]
        
        self.lab_sessions = {
            'L1': "8:00 - 9:40",
            'L2': "9:50 - 11:30", 
            'L3': "11:50 - 1:30",
            'L4': "1:50 - 3:30",
            'L5': "3:50 - 5:30",
            'L6': "5:30 - 7:10"
        }
        
        self.days = ["tuesday", "wed", "thur", "fri", "sat"]
        
        # Color schemes for groups
        self.group_colors = {
            1: '#FF6B6B',  # Red
            2: '#4ECDC4',  # Teal
            3: '#45B7D1',  # Blue
            4: '#96CEB4',  # Green
            5: '#FECA57',  # Yellow
            6: '#FF9FF3',  # Pink
            7: '#54A0FF',  # Light Blue
            8: '#5F27CD'   # Purple
        }
        
    def find_latest_schedules(self):
        """Find the most recent theory and lab schedule files."""
        theory_files = []
        lab_files = []
        
        # Search in output directory
        if os.path.exists('output'):
            for item in os.listdir('output'):
                item_path = os.path.join('output', item)
                if os.path.isdir(item_path):
                    # Check for theory schedule
                    theory_json = os.path.join(item_path, 'theory_schedule.json')
                    if os.path.exists(theory_json):
                        theory_files.append(theory_json)
                    
                    # Check for lab schedule
                    lab_json = os.path.join(item_path, 'lab_schedule.json')
                    if os.path.exists(lab_json):
                        lab_files.append(lab_json)
        
        # Get the most recent files
        theory_file = max(theory_files, key=os.path.getmtime) if theory_files else None
        lab_file = max(lab_files, key=os.path.getmtime) if lab_files else None
        
        return theory_file, lab_file
    
    def load_schedule_data(self, file_path):
        """Load schedule data from JSON file."""
        try:
            with open(file_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading {file_path}: {e}")
            return []
    
    def analyze_group_distributions(self, theory_data, lab_data):
        """Analyze group distributions by semester and department."""
        distributions = {}
        
        # Process theory data
        theory_groups = defaultdict(lambda: defaultdict(lambda: defaultdict(set)))
        for session in theory_data:
            dept = session.get('department', 'Unknown')
            semester = session.get('semester', 0)
            group = session.get('group_index', 0)
            day = session.get('day', '')
            time_slot = session.get('time_slot', '')
            
            if day and time_slot:
                theory_groups[dept][semester][group].add((day, time_slot))
        
        # Process lab data
        lab_groups = defaultdict(lambda: defaultdict(lambda: defaultdict(set)))
        for session in lab_data:
            dept = session.get('department', 'Unknown')
            semester = session.get('semester', 0)
            group = session.get('group_index', 0)
            day = session.get('day', '')
            session_name = session.get('session_name', '')
            
            if day and session_name:
                lab_groups[dept][semester][group].add((day, session_name))
        
        # Combine into distributions structure
        for dept in set(list(theory_groups.keys()) + list(lab_groups.keys())):
            distributions[dept] = {}
            semesters = set(list(theory_groups[dept].keys()) + list(lab_groups[dept].keys()))
            
            for semester in semesters:
                distributions[dept][semester] = {
                    'theory_groups': dict(theory_groups[dept][semester]),
                    'lab_groups': dict(lab_groups[dept][semester])
                }
        
        return distributions
    
    def create_timetable_visualization(self, dept, semester, theory_groups, lab_groups):
        """Create a timetable visualization for a specific department and semester."""
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 12))
        fig.suptitle(f'{dept} - Semester {semester}\nGroup Distribution Timetable', fontsize=16, fontweight='bold')
        
        # Theory timetable
        self._plot_theory_timetable(ax1, theory_groups, f'Theory Groups - {dept} S{semester}')
        
        # Lab timetable
        self._plot_lab_timetable(ax2, lab_groups, f'Lab Groups - {dept} S{semester}')
        
        plt.tight_layout()
        return fig
    
    def _plot_theory_timetable(self, ax, theory_groups, title):
        """Plot theory group timetable."""
        ax.set_title(title, fontsize=14, fontweight='bold', pad=20)
        
        # Create grid
        num_days = len(self.days)
        num_slots = len(self.theory_time_slots)
        
        # Set up the grid
        ax.set_xlim(0, num_days)
        ax.set_ylim(0, num_slots)
        
        # Draw grid lines
        for i in range(num_days + 1):
            ax.axvline(x=i, color='black', linewidth=1)
        for i in range(num_slots + 1):
            ax.axhline(y=i, color='black', linewidth=1)
        
        # Fill in group assignments
        for group_num, time_slots in theory_groups.items():
            if group_num == 0:  # Skip invalid groups
                continue
                
            color = self.group_colors.get(group_num, '#CCCCCC')
            
            for day, time_slot in time_slots:
                if day in self.days and time_slot in self.theory_time_slots:
                    day_idx = self.days.index(day)
                    slot_idx = self.theory_time_slots.index(time_slot)
                    
                    # Create rectangle for this group assignment
                    rect = patches.Rectangle((day_idx, num_slots - slot_idx - 1), 1, 1, 
                                           linewidth=1, edgecolor='black', 
                                           facecolor=color, alpha=0.7)
                    ax.add_patch(rect)
                    
                    # Add group label
                    ax.text(day_idx + 0.5, num_slots - slot_idx - 0.5, f'G{group_num}', 
                           ha='center', va='center', fontweight='bold', fontsize=10)
        
        # Set labels
        ax.set_xticks([i + 0.5 for i in range(num_days)])
        ax.set_xticklabels([day.capitalize() for day in self.days])
        ax.set_yticks([i + 0.5 for i in range(num_slots)])
        ax.set_yticklabels([slot for slot in reversed(self.theory_time_slots)])
        
        # Remove tick marks
        ax.tick_params(length=0)
        
        # Add legend for theory groups
        legend_elements = []
        for group_num in sorted(theory_groups.keys()):
            if group_num > 0:
                color = self.group_colors.get(group_num, '#CCCCCC')
                legend_elements.append(patches.Patch(color=color, label=f'Theory Group {group_num}'))
        
        if legend_elements:
            ax.legend(handles=legend_elements, loc='upper left', bbox_to_anchor=(1.02, 1))
    
    def _plot_lab_timetable(self, ax, lab_groups, title):
        """Plot lab group timetable."""
        ax.set_title(title, fontsize=14, fontweight='bold', pad=20)
        
        # Create grid
        num_days = len(self.days)
        num_sessions = len(self.lab_sessions)
        
        # Set up the grid
        ax.set_xlim(0, num_days)
        ax.set_ylim(0, num_sessions)
        
        # Draw grid lines
        for i in range(num_days + 1):
            ax.axvline(x=i, color='black', linewidth=1)
        for i in range(num_sessions + 1):
            ax.axhline(y=i, color='black', linewidth=1)
        
        # Fill in group assignments
        session_names = list(self.lab_sessions.keys())
        
        for group_num, sessions in lab_groups.items():
            if group_num == 0:  # Skip invalid groups
                continue
                
            color = self.group_colors.get(group_num, '#CCCCCC')
            
            for day, session_name in sessions:
                if day in self.days and session_name in session_names:
                    day_idx = self.days.index(day)
                    session_idx = session_names.index(session_name)
                    
                    # Create rectangle for this group assignment
                    rect = patches.Rectangle((day_idx, num_sessions - session_idx - 1), 1, 1, 
                                           linewidth=1, edgecolor='black', 
                                           facecolor=color, alpha=0.7)
                    ax.add_patch(rect)
                    
                    # Add group label
                    ax.text(day_idx + 0.5, num_sessions - session_idx - 0.5, f'G{group_num}', 
                           ha='center', va='center', fontweight='bold', fontsize=10)
        
        # Set labels
        ax.set_xticks([i + 0.5 for i in range(num_days)])
        ax.set_xticklabels([day.capitalize() for day in self.days])
        ax.set_yticks([i + 0.5 for i in range(num_sessions)])
        ax.set_yticklabels([f'{session} ({time})' for session, time in 
                          zip(reversed(session_names), 
                              [self.lab_sessions[s] for s in reversed(session_names)])])
        
        # Remove tick marks
        ax.tick_params(length=0)
        
        # Add legend for lab groups
        legend_elements = []
        for group_num in sorted(lab_groups.keys()):
            if group_num > 0:
                color = self.group_colors.get(group_num, '#CCCCCC')
                legend_elements.append(patches.Patch(color=color, label=f'Lab Group {group_num}'))
        
        if legend_elements:
            ax.legend(handles=legend_elements, loc='upper left', bbox_to_anchor=(1.02, 1))
    
    def create_summary_visualization(self, distributions):
        """Create a summary visualization of all departments and semesters."""
        fig, axes = plt.subplots(2, 2, figsize=(20, 16))
        fig.suptitle('Group Distribution Summary - All Departments & Semesters', fontsize=18, fontweight='bold')
        
        plot_idx = 0
        for dept, semesters in distributions.items():
            for semester, data in semesters.items():
                if plot_idx >= 4:  # Only show first 4 combinations
                    break
                    
                row = plot_idx // 2
                col = plot_idx % 2
                ax = axes[row, col]
                
                self._plot_combined_summary(ax, dept, semester, 
                                          data['theory_groups'], data['lab_groups'])
                plot_idx += 1
        
        # Hide unused subplots
        while plot_idx < 4:
            row = plot_idx // 2
            col = plot_idx % 2
            axes[row, col].set_visible(False)
            plot_idx += 1
        
        plt.tight_layout()
        return fig
    
    def _plot_combined_summary(self, ax, dept, semester, theory_groups, lab_groups):
        """Plot a combined summary for one department-semester."""
        ax.set_title(f'{dept} - Semester {semester}', fontsize=12, fontweight='bold')
        
        # Count sessions per group
        theory_counts = {g: len(slots) for g, slots in theory_groups.items() if g > 0}
        lab_counts = {g: len(sessions) for g, sessions in lab_groups.items() if g > 0}
        
        # Get all group numbers
        all_groups = sorted(set(list(theory_counts.keys()) + list(lab_counts.keys())))
        
        if not all_groups:
            ax.text(0.5, 0.5, 'No group data', ha='center', va='center', transform=ax.transAxes)
            return
        
        # Create bar chart
        x = np.arange(len(all_groups))
        width = 0.35
        
        theory_values = [theory_counts.get(g, 0) for g in all_groups]
        lab_values = [lab_counts.get(g, 0) for g in all_groups]
        
        bars1 = ax.bar(x - width/2, theory_values, width, label='Theory Sessions', alpha=0.8, color='lightblue')
        bars2 = ax.bar(x + width/2, lab_values, width, label='Lab Sessions', alpha=0.8, color='lightcoral')
        
        # Add value labels on bars
        for bars in [bars1, bars2]:
            for bar in bars:
                height = bar.get_height()
                if height > 0:
                    ax.annotate(f'{int(height)}',
                              xy=(bar.get_x() + bar.get_width() / 2, height),
                              xytext=(0, 3),  # 3 points vertical offset
                              textcoords="offset points",
                              ha='center', va='bottom', fontsize=9)
        
        ax.set_xlabel('Group Number')
        ax.set_ylabel('Number of Sessions')
        ax.set_xticks(x)
        ax.set_xticklabels([f'G{g}' for g in all_groups])
        ax.legend()
        ax.grid(True, alpha=0.3)
    
    def generate_all_visualizations(self):
        """Generate all group distribution visualizations."""
        print("🎨 Starting Group Distribution Visualization Generation...")
        
        # Find latest schedule files
        theory_file, lab_file = self.find_latest_schedules()
        
        if not theory_file and not lab_file:
            print("❌ No schedule files found!")
            return
        
        print(f"📊 Theory schedule: {theory_file or 'Not found'}")
        print(f"🧪 Lab schedule: {lab_file or 'Not found'}")
        
        # Load data
        theory_data = self.load_schedule_data(theory_file) if theory_file else []
        lab_data = self.load_schedule_data(lab_file) if lab_file else []
        
        print(f"✅ Loaded {len(theory_data)} theory sessions and {len(lab_data)} lab sessions")
        
        # Analyze distributions
        distributions = self.analyze_group_distributions(theory_data, lab_data)
        
        # Generate individual timetables for each department-semester
        generated_files = []
        
        for dept, semesters in distributions.items():
            for semester, data in semesters.items():
                theory_groups = data['theory_groups']
                lab_groups = data['lab_groups']
                
                if theory_groups or lab_groups:
                    fig = self.create_timetable_visualization(dept, semester, theory_groups, lab_groups)
                    
                    # Save the figure
                    filename = f"group_distribution_{dept.replace(' ', '_')}_S{semester}.png"
                    filepath = os.path.join(self.output_dir, filename)
                    fig.savefig(filepath, dpi=300, bbox_inches='tight')
                    plt.close(fig)
                    
                    generated_files.append(filepath)
                    print(f"📈 Generated: {filename}")
        
        # Generate summary visualization
        if distributions:
            summary_fig = self.create_summary_visualization(distributions)
            summary_path = os.path.join(self.output_dir, "group_distribution_summary.png")
            summary_fig.savefig(summary_path, dpi=300, bbox_inches='tight')
            plt.close(summary_fig)
            generated_files.append(summary_path)
            print(f"📊 Generated summary: group_distribution_summary.png")
        
        # Generate detailed report
        self._generate_distribution_report(distributions)
        
        print(f"\n🎯 Group distribution visualizations complete!")
        print(f"📁 Output directory: {os.path.abspath(self.output_dir)}")
        print(f"📄 Files generated: {len(generated_files)}")
        
        return generated_files
    
    def _generate_distribution_report(self, distributions):
        """Generate a detailed text report of group distributions."""
        report_path = os.path.join(self.output_dir, "group_distribution_report.txt")
        
        with open(report_path, 'w') as f:
            f.write("GROUP DISTRIBUTION ANALYSIS REPORT\n")
            f.write("=" * 50 + "\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            
            for dept, semesters in distributions.items():
                f.write(f"DEPARTMENT: {dept}\n")
                f.write("-" * 30 + "\n")
                
                for semester, data in semesters.items():
                    f.write(f"\nSemester {semester}:\n")
                    
                    # Theory groups
                    theory_groups = data['theory_groups']
                    f.write(f"  Theory Groups: {len(theory_groups)} groups\n")
                    for group_num, time_slots in theory_groups.items():
                        if group_num > 0:
                            f.write(f"    Group {group_num}: {len(time_slots)} time slots\n")
                            for day, time_slot in sorted(time_slots):
                                f.write(f"      {day.capitalize()} {time_slot}\n")
                    
                    # Lab groups
                    lab_groups = data['lab_groups']
                    f.write(f"  Lab Groups: {len(lab_groups)} groups\n")
                    for group_num, sessions in lab_groups.items():
                        if group_num > 0:
                            f.write(f"    Group {group_num}: {len(sessions)} lab sessions\n")
                            for day, session_name in sorted(sessions):
                                f.write(f"      {day.capitalize()} {session_name}\n")
                    
                    f.write("\n")
        
        print(f"📄 Generated report: group_distribution_report.txt")

def main():
    """Main function to generate group distribution visualizations."""
    visualizer = GroupDistributionVisualizer()
    visualizer.generate_all_visualizations()

if __name__ == "__main__":
    main() 