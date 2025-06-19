#!/usr/bin/env python3
"""
Visualize Lab Group Distributions from CSV

This script generates timetable visualizations showing where each lab group
is scheduled throughout the week, organized by department and semester.
Specifically designed for lab_schedule.csv files.
"""

import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from matplotlib.patches import Patch
import glob
from collections import defaultdict

# Constants for lab visualization
DAYS = ["tuesday", "wed", "thur", "fri", "sat"]  # Excluding Monday
LAB_SESSIONS = {
    'L1': {'time_range': '8:00 - 9:40'},
    'L2': {'time_range': '9:50 - 11:30'},
    'L3': {'time_range': '11:50 - 1:30'},
    'L4': {'time_range': '1:50 - 3:30'},
    'L5': {'time_range': '3:50 - 5:30'},
    'L6': {'time_range': '5:30 - 7:10'}
}

LAB_SLOTS = list(LAB_SESSIONS.keys())  # ['L1', 'L2', 'L3', 'L4', 'L5', 'L6']

def generate_colors(num_groups):
    """Generate a list of distinct colors for groups."""
    base_colors = list(plt.cm.Set3.colors) + list(plt.cm.Pastel1.colors) + list(plt.cm.Pastel2.colors)
    return base_colors[:num_groups]

def find_lab_schedule_file():
    """Find the most recent lab schedule CSV file."""
    # Look for lab schedule files in order of preference
    possible_paths = [
        'output/lab_schedule_*/lab_schedule.csv',
        'output/combined_schedule_*/combined_lab_schedule.csv',
        'lab_schedule.csv',
        'combined_lab_schedule.csv'
    ]
    
    for pattern in possible_paths:
        files = sorted(glob.glob(pattern), reverse=True)
        if files:
            print(f"Found lab schedule file: {files[0]}")
            return files[0]
    
    print("No lab schedule CSV file found!")
    return None

def load_lab_schedule_data(file_path):
    """Load lab schedule data from CSV file."""
    if not file_path or not os.path.exists(file_path):
        print(f"Lab schedule file not found: {file_path}")
        return None
    
    try:
        df = pd.read_csv(file_path)
        print(f"Loaded lab schedule CSV with {len(df)} rows")
        print(f"Columns: {list(df.columns)}")
        return df
    except Exception as e:
        print(f"Error loading lab schedule data from {file_path}: {e}")
        return None

def group_lab_sessions_by_dept_semester(df):
    """Group lab sessions by department and semester."""
    dept_sem_groups = defaultdict(lambda: defaultdict(list))
    
    for _, row in df.iterrows():
        dept = row.get('department', 'Unknown')
        semester = row.get('semester', 0)
        group_name = row.get('group_name', f'{dept}_S{semester}_G0')
        
        # Create session record
        session = {
            'day': row.get('day', ''),
            'session_name': row.get('session_name', ''),
            'course_code': row.get('course_code', ''),
            'teacher_name': row.get('teacher_name', ''),
            'room_number': row.get('room_number', ''),
            'student_count': row.get('student_count', 0),
            'is_batched': row.get('is_batched', False),
            'batch_info': row.get('batch_info', ''),
            'group_name': group_name
        }
        
        # Add to the appropriate dept/semester collection
        dept_sem_groups[(dept, semester)][group_name].append(session)
    
    return dept_sem_groups

def create_lab_timetable_matrix(groups):
    """Create a matrix showing which groups are scheduled in each lab time slot."""
    num_days = len(DAYS)
    num_slots = len(LAB_SLOTS)
    
    # Initialize matrix: [days, slots, group_present]
    # For each day and slot, we'll store which groups are present
    timetable = [[set() for _ in range(num_slots)] for _ in range(num_days)]
    
    for group_name, sessions in groups.items():
        for session in sessions:
            day = session.get('day', '')
            session_name = session.get('session_name', '')
            
            if day in DAYS and session_name in LAB_SLOTS:
                day_idx = DAYS.index(day)
                slot_idx = LAB_SLOTS.index(session_name)
                timetable[day_idx][slot_idx].add(group_name)
    
    return timetable

def visualize_lab_group_timetable(timetable, groups, title, filename):
    """Create a visualization of the lab group timetable."""
    num_days = len(DAYS)
    num_slots = len(LAB_SLOTS)
    
    # Create figure with more space for summary
    fig = plt.figure(figsize=(16, 12))
    gs = plt.GridSpec(3, 2, height_ratios=[5, 1, 2], width_ratios=[3, 1])
    
    # Main timetable plot
    ax_main = plt.subplot(gs[0, :])
    
    # Generate group colors
    group_keys = sorted(groups.keys())
    colors = generate_colors(len(group_keys))
    group_colors = {group: colors[i % len(colors)] for i, group in enumerate(group_keys)}
    
    # Create a matrix for visualization
    viz_matrix = np.zeros((num_slots, num_days, 4))  # RGBA values
    
    # Track statistics
    group_slot_counts = {group: 0 for group in group_keys}
    day_counts = {day: 0 for day in DAYS}
    slot_counts = {slot_idx: 0 for slot_idx in range(num_slots)}
    total_sessions = 0
    conflicts = []  # Track time slots with multiple groups
    
    # Fill the matrix with group colors
    for day_idx in range(num_days):
        for slot_idx in range(num_slots):
            present_groups = timetable[day_idx][slot_idx]
            
            if present_groups:
                # Count statistics
                session_count = len(present_groups)
                total_sessions += session_count
                day_counts[DAYS[day_idx]] += session_count
                slot_counts[slot_idx] += session_count
                
                for group in present_groups:
                    group_slot_counts[group] += 1
                
                # Track conflicts (multiple groups in same slot)
                if session_count > 1:
                    conflicts.append((DAYS[day_idx], LAB_SLOTS[slot_idx], list(present_groups)))
                
                # Color the cell
                if session_count > 1:
                    # Multiple groups - use a mixed color with pattern
                    group = next(iter(present_groups))
                    color = list(group_colors[group])
                    if len(color) == 3:
                        color.append(0.8)  # Higher alpha for conflicts
                    viz_matrix[slot_idx, day_idx] = color
                else:
                    # Single group - use its color
                    group = next(iter(present_groups))
                    color = list(group_colors[group])
                    if len(color) == 3:
                        color.append(0.6)  # Standard alpha
                    viz_matrix[slot_idx, day_idx] = color
    
    # Plot the matrix
    im = ax_main.imshow(viz_matrix, aspect='auto')
    
    # Configure the main plot
    ax_main.set_title(title, fontsize=16, fontweight='bold', pad=20)
    ax_main.set_xlabel("Day", fontsize=12)
    ax_main.set_ylabel("Lab Session", fontsize=12)
    
    # Set x-axis labels (days)
    ax_main.set_xticks(range(num_days))
    ax_main.set_xticklabels([day.capitalize() for day in DAYS], rotation=0)
    
    # Set y-axis labels (lab sessions)
    ax_main.set_yticks(range(num_slots))
    ax_main.set_yticklabels([f"{slot}\n({LAB_SESSIONS[slot]['time_range']})" for slot in LAB_SLOTS])
    
    # Add grid lines
    ax_main.grid(True, color='gray', linestyle='-', linewidth=0.5, alpha=0.3)
    
    # Add annotations showing number of groups in each slot
    for day_idx in range(num_days):
        for slot_idx in range(num_slots):
            present_groups = timetable[day_idx][slot_idx]
            if len(present_groups) > 0:
                ax_main.text(day_idx, slot_idx, f"{len(present_groups)}", 
                           ha='center', va='center', fontsize=12, fontweight='bold',
                           color='white' if len(present_groups) > 1 else 'black',
                           bbox=dict(boxstyle="round,pad=0.3", 
                                   facecolor='red' if len(present_groups) > 1 else 'lightblue',
                                   alpha=0.7))
    
    # Create legend for groups
    legend_elements = [
        Patch(facecolor=group_colors[group], edgecolor='black', alpha=0.6, 
             label=f"{group} ({group_slot_counts[group]} slots)")
        for group in group_keys
    ]
    ax_main.legend(handles=legend_elements, title="Lab Groups", 
                  bbox_to_anchor=(1.05, 1), loc='upper left')
    
    # Add daily utilization bar chart
    ax_daily = plt.subplot(gs[1, 0])
    day_labels = [day.capitalize() for day in DAYS]
    bars = ax_daily.bar(day_labels, [day_counts[day] for day in DAYS], color='skyblue')
    ax_daily.set_title("Sessions per Day", fontsize=12)
    ax_daily.set_ylabel("Number of Sessions")
    
    # Add value labels on bars
    for bar, count in zip(bars, [day_counts[day] for day in DAYS]):
        if count > 0:
            ax_daily.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1,
                         str(count), ha='center', va='bottom', fontweight='bold')
    
    # Add session utilization bar chart
    ax_sessions = plt.subplot(gs[1, 1])
    session_bars = ax_sessions.bar(range(len(LAB_SLOTS)), 
                                  [slot_counts[i] for i in range(len(LAB_SLOTS))], 
                                  color='lightgreen')
    ax_sessions.set_title("Sessions per Time Slot", fontsize=12)
    ax_sessions.set_ylabel("Number of Sessions")
    ax_sessions.set_xticks(range(len(LAB_SLOTS)))
    ax_sessions.set_xticklabels(LAB_SLOTS, rotation=45)
    
    # Add value labels on session bars
    for i, bar in enumerate(session_bars):
        count = slot_counts[i]
        if count > 0:
            ax_sessions.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1,
                           str(count), ha='center', va='bottom', fontweight='bold')
    
    # Add comprehensive summary text
    ax_summary = plt.subplot(gs[2, :])
    ax_summary.axis('off')
    
    # Gather course and teacher statistics
    course_count = defaultdict(int)
    teacher_set = set()
    batch_count = 0
    
    for group_name, sessions in groups.items():
        for session in sessions:
            course_count[session['course_code']] += 1
            teacher_set.add(session['teacher_name'])
            if session.get('is_batched', False):
                batch_count += 1
    
    # Create comprehensive summary
    summary_text = f"LAB SCHEDULE SUMMARY - {title}\n\n"
    summary_text += f"📊 OVERVIEW:\n"
    summary_text += f"   • Total Groups: {len(group_keys)}\n"
    summary_text += f"   • Total Lab Sessions: {total_sessions}\n"
    summary_text += f"   • Unique Courses: {len(course_count)}\n"
    summary_text += f"   • Unique Teachers: {len(teacher_set)}\n"
    summary_text += f"   • Batched Sessions: {batch_count}\n\n"
    
    # Group utilization
    summary_text += f"🎯 GROUP UTILIZATION:\n"
    for group in sorted(group_keys):
        summary_text += f"   • {group}: {group_slot_counts[group]} sessions\n"
    
    # Time slot utilization
    summary_text += f"\n⏰ TIME SLOT UTILIZATION:\n"
    for i, slot in enumerate(LAB_SLOTS):
        if slot_counts[i] > 0:
            summary_text += f"   • {slot} ({LAB_SESSIONS[slot]['time_range']}): {slot_counts[i]} sessions\n"
    
    # Conflicts information
    if conflicts:
        summary_text += f"\n⚠️  SCHEDULING CONFLICTS ({len(conflicts)}):\n"
        for day, slot, groups_list in conflicts[:5]:  # Show first 5 conflicts
            summary_text += f"   • {day.capitalize()} {slot}: {', '.join(groups_list)}\n"
        if len(conflicts) > 5:
            summary_text += f"   • ... and {len(conflicts) - 5} more conflicts\n"
    else:
        summary_text += f"\n✅ NO SCHEDULING CONFLICTS DETECTED\n"
    
    # Utilization percentage
    max_possible_sessions = num_days * num_slots * len(group_keys)
    utilization = (total_sessions / max_possible_sessions * 100) if max_possible_sessions > 0 else 0
    summary_text += f"\n📈 TIMETABLE UTILIZATION: {utilization:.1f}%"
    
    ax_summary.text(0, 1, summary_text, va='top', fontsize=10, linespacing=1.4,
                   fontfamily='monospace')
    
    # Adjust layout
    plt.tight_layout()
    
    # Save the figure
    plt.savefig(filename, dpi=150, bbox_inches='tight')
    print(f"✅ Saved lab group visualization to {filename}")
    plt.close()

def generate_lab_group_visualizations():
    """Generate visualizations for lab group distributions from CSV files."""
    # Find lab schedule file
    lab_file = find_lab_schedule_file()
    
    if not lab_file:
        print("❌ No lab schedule CSV file found!")
        return
    
    # Load lab schedule data
    df = load_lab_schedule_data(lab_file)
    if df is None:
        print("❌ Failed to load lab schedule data!")
        return
    
    # Create output directory
    output_dir = "lab_group_visualizations"
    os.makedirs(output_dir, exist_ok=True)
    print(f"📁 Created output directory: {output_dir}")
    
    # Group sessions by department and semester
    dept_sem_groups = group_lab_sessions_by_dept_semester(df)
    
    if not dept_sem_groups:
        print("❌ No group data found in lab schedule!")
        return
    
    print(f"📊 Found {len(dept_sem_groups)} department-semester combinations")
    
    # Generate visualizations for each department and semester
    for (dept, semester), groups in dept_sem_groups.items():
        if not groups:
            continue
        
        print(f"🎨 Creating visualization for {dept} Semester {semester}...")
        
        # Create timetable matrix
        timetable = create_lab_timetable_matrix(groups)
        
        # Generate title and filename
        title = f"Lab Group Distribution - {dept} Semester {semester}"
        safe_dept_name = dept.replace(" ", "_").replace("&", "and").replace("(", "").replace(")", "")
        filename = os.path.join(output_dir, f"lab_groups_{safe_dept_name}_S{semester}.png")
        
        # Create visualization
        visualize_lab_group_timetable(timetable, groups, title, filename)
    
    # Generate a combined overview if multiple departments exist
    if len(dept_sem_groups) > 1:
        print("🎨 Creating combined overview...")
        
        # Combine all groups for overview
        all_groups = {}
        for (dept, semester), groups in dept_sem_groups.items():
            all_groups.update(groups)
        
        # Create combined timetable
        combined_timetable = create_lab_timetable_matrix(all_groups)
        
        # Generate combined visualization
        title = "Lab Group Distribution - All Departments & Semesters"
        filename = os.path.join(output_dir, "lab_groups_combined_overview.png")
        visualize_lab_group_timetable(combined_timetable, all_groups, title, filename)
    
    print(f"🎉 Lab group visualizations complete! Check the '{output_dir}' directory.")

if __name__ == "__main__":
    print("🚀 Starting Lab Group Visualization...")
    generate_lab_group_visualizations()