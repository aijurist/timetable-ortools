#!/usr/bin/env python3
"""
Visualize Theory and Lab Group Distributions

This script generates timetable visualizations showing where each theory and lab group
is scheduled throughout the week, organized by department and semester.
"""

import os
import json
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from matplotlib.patches import Patch
import glob
from collections import defaultdict

# Constants for visualization - supports multiple day patterns
DAY_PATTERNS = {
    'Monday-Friday': ["monday", "tuesday", "wed", "thur", "fri"],
    'Tuesday-Saturday': ["tuesday", "wed", "thur", "fri", "saturday"],
    'Monday-Saturday': ["monday", "tuesday", "wed", "thur", "fri", "saturday"]
}

# Default day pattern (maintained for backward compatibility)
DAYS = ["tuesday", "wed", "thur", "fri", "saturday"]  # Default to Tuesday-Saturday

THEORY_SLOTS = [
    "8:00 - 8:50", "9:00 - 9:50", "10:00 - 10:50", "11:00 - 11:50",
    "12:00 - 12:50", "1:00 - 1:50", "2:00 - 2:50", "3:00 - 3:50", 
    "4:00 - 4:50", "5:00 - 5:50", "6:00 - 6:50"
]
LAB_SESSIONS = {
    'L1': {'slots': [0, 1], 'time_range': '8:00 - 9:40'},
    'L2': {'slots': [2, 3], 'time_range': '10:00 - 11:40'},
    'L3': {'slots': [4, 5], 'time_range': '11:50 - 1:20'},
    'L4': {'slots': [6, 7], 'time_range': '1:20 - 3:00'},
    'L5': {'slots': [8, 9], 'time_range': '3:00 - 4:40'},
    'L6': {'slots': [10, 11], 'time_range': '5:10 - 6:50'}
}

LAB_SLOTS = list(LAB_SESSIONS.keys())  # ['L1', 'L2', 'L3', 'L4', 'L5', 'L6']

# Create consistent colors for groups
def generate_colors(num_groups):
    """Generate a list of distinct colors for groups."""
    base_colors = list(plt.cm.Set3.colors) + list(plt.cm.Pastel1.colors) + list(plt.cm.Pastel2.colors)
    return base_colors[:num_groups]

def find_schedule_files():
    """Find the most recent theory and lab schedule files."""
    # Find the most recent combined schedule directory
    combined_dirs = sorted(glob.glob('output/combined_schedule_*'), reverse=True)
    
    theory_file = None
    lab_file = None

    if combined_dirs:
        combined_dir = combined_dirs[0]
        print(f"Looking in directory: {combined_dir}")
        
        # Look for CSV files first (combined scheduler output)
        theory_csv = os.path.join(combined_dir, 'combined_theory_schedule.csv')
        lab_csv = os.path.join(combined_dir, 'combined_lab_schedule.csv')
        
        if os.path.exists(theory_csv):
            theory_file = theory_csv
            print(f"Found theory CSV: {theory_csv}")
        if os.path.exists(lab_csv):
            lab_file = lab_csv
            print(f"Found lab CSV: {lab_csv}")
        
        # Fallback to JSON files if CSV not found
        if not theory_file:
            theory_json = os.path.join(combined_dir, 'combined_theory_schedule.json')
            if os.path.exists(theory_json):
                theory_file = theory_json
                print(f"Found theory JSON: {theory_json}")
        
        if not lab_file:
            lab_json = os.path.join(combined_dir, 'combined_lab_schedule.json')
            if os.path.exists(lab_json):
                lab_file = lab_json
                print(f"Found lab JSON: {lab_json}")
    
    # If not found in combined dir, look for individual schedule dirs
    if not theory_file:
        theory_dirs = sorted(glob.glob('output/theory_schedule_*'), reverse=True)
        if theory_dirs:
            theory_file = os.path.join(theory_dirs[0], 'theory_schedule.json')
            if not os.path.exists(theory_file):
                theory_file = None
    
    if not lab_file:
        lab_dirs = sorted(glob.glob('output/lab_schedule_*'), reverse=True)
        if lab_dirs:
            lab_file = os.path.join(lab_dirs[0], 'lab_schedule.json')
            if not os.path.exists(lab_file):
                lab_file = None
    
    return theory_file, lab_file

def load_schedule_data(file_path):
    """Load schedule data from a JSON or CSV file."""
    if not file_path or not os.path.exists(file_path):
        print(f"Schedule file not found: {file_path}")
        return None
    
    try:
        if file_path.endswith('.csv'):
            # Load CSV file and convert to list of dictionaries
            import pandas as pd
            df = pd.read_csv(file_path)
            print(f"Loaded CSV with {len(df)} rows and columns: {list(df.columns)}")
            return df.to_dict('records')
        else:
            # Load JSON file
            with open(file_path, 'r') as f:
                data = json.load(f)
                print(f"Loaded JSON with {len(data)} entries")
                return data
    except Exception as e:
        print(f"Error loading schedule data from {file_path}: {e}")
        return None

def get_day_pattern_from_schedule(schedule_data):
    """Determine the day pattern from schedule data."""
    if not schedule_data:
        return 'Tuesday-Saturday'  # Default fallback
    
    # Check if day_pattern is explicitly provided in the data
    for session in schedule_data:
        day_pattern = session.get('day_pattern')
        if day_pattern and day_pattern in DAY_PATTERNS:
            return day_pattern
    
    # Infer from the days actually used in the schedule
    days_used = set()
    for session in schedule_data:
        day = session.get('day', '').lower()
        if day:
            days_used.add(day)
    
    # Match against known patterns
    for pattern_name, pattern_days in DAY_PATTERNS.items():
        if days_used.issubset(set(pattern_days)):
            return pattern_name
    
    # Fallback based on which days are present
    if 'monday' in days_used and 'saturday' in days_used:
        return 'Monday-Saturday'
    elif 'monday' in days_used and 'saturday' not in days_used:
        return 'Monday-Friday'
    else:
        return 'Tuesday-Saturday'

def group_sessions_by_dept_semester(schedule_data, is_theory=True):
    """Group sessions by department and semester, including day pattern information."""
    dept_sem_groups = defaultdict(lambda: defaultdict(list))
    dept_sem_patterns = {}
    
    for session in schedule_data:
        dept = session.get('department', 'Unknown')
        semester = session.get('semester', 0)
        group_index = session.get('group_index', 0)
        
        # Create unique key for the group
        group_key = f"{dept}_S{semester}_G{group_index}"
        
        # Track day pattern for this dept/semester
        dept_sem_key = (dept, semester)
        if dept_sem_key not in dept_sem_patterns:
            # Try to get pattern from the session
            day_pattern = session.get('day_pattern')
            if day_pattern and day_pattern in DAY_PATTERNS:
                dept_sem_patterns[dept_sem_key] = day_pattern
            else:
                dept_sem_patterns[dept_sem_key] = None  # Will be inferred later
        
        # Add to the appropriate dept/semester collection
        dept_sem_groups[dept_sem_key][group_key].append(session)
    
    # Infer missing day patterns
    for dept_sem_key in dept_sem_patterns:
        if dept_sem_patterns[dept_sem_key] is None:
            # Get all sessions for this dept/semester
            all_sessions = []
            for group_sessions in dept_sem_groups[dept_sem_key].values():
                all_sessions.extend(group_sessions)
            dept_sem_patterns[dept_sem_key] = get_day_pattern_from_schedule(all_sessions)
    
    return dept_sem_groups, dept_sem_patterns

def create_group_timetable_matrix(groups, day_pattern='Tuesday-Saturday', is_theory=True):
    """Create a matrix showing which groups are scheduled in each time slot."""
    # Get the appropriate days for this pattern
    pattern_days = DAY_PATTERNS.get(day_pattern, DAYS)
    num_days = len(pattern_days)
    num_slots = len(THEORY_SLOTS) if is_theory else len(LAB_SLOTS)
    
    # Initialize matrix: [days, slots, group_present]
    # For each day and slot, we'll store which groups are present
    timetable = [[set() for _ in range(num_slots)] for _ in range(num_days)]
    
    for group_key, sessions in groups.items():
        for session in sessions:
            day = session.get('day', '').lower()
            
            if is_theory:
                # For theory, use the time_slot field
                time_slot = session.get('time_slot', '')
                if day in pattern_days and time_slot in THEORY_SLOTS:
                    day_idx = pattern_days.index(day)
                    slot_idx = THEORY_SLOTS.index(time_slot)
                    timetable[day_idx][slot_idx].add(group_key)
            else:
                # For lab, use the session_name field (L1, L2, etc.)
                session_name = session.get('session_name', '')
                if day in pattern_days and session_name in LAB_SLOTS:
                    day_idx = pattern_days.index(day)
                    slot_idx = LAB_SLOTS.index(session_name)
                    timetable[day_idx][slot_idx].add(group_key)
    
    return timetable, pattern_days

def visualize_group_timetable(timetable, groups, title, filename, pattern_days, is_theory=True):
    """Create a visualization of the group timetable."""
    num_days = len(pattern_days)
    num_slots = len(THEORY_SLOTS) if is_theory else len(LAB_SLOTS)
    
    # Create a new figure
    plt.figure(figsize=(15, 10))  # Increased height for the summary
    
    # Generate group colors
    group_keys = sorted(groups.keys())
    colors = generate_colors(len(group_keys))
    group_colors = {group: colors[i % len(colors)] for i, group in enumerate(group_keys)}
    
    # Create a matrix for visualization
    viz_matrix = np.zeros((num_slots, num_days, 4))  # RGBA values
    
    # Track occupancy stats
    group_slot_counts = {group: 0 for group in group_keys}
    day_counts = {day: 0 for day in pattern_days}
    slot_counts = {slot_idx: 0 for slot_idx in range(num_slots)}
    total_sessions = 0
    
    # Fill the matrix with group colors
    for day_idx in range(num_days):
        for slot_idx in range(num_slots):
            present_groups = timetable[day_idx][slot_idx]
            
            if present_groups:
                # Count occupancy
                total_sessions += len(present_groups)
                day_counts[pattern_days[day_idx]] += len(present_groups)
                slot_counts[slot_idx] += len(present_groups)
                for group in present_groups:
                    group_slot_counts[group] += 1
               
                # If multiple groups in this slot, blend their colors
                if len(present_groups) > 1:
                    # Create a hatched pattern or blend of colors
                    # For simplicity, we'll just use the first group's color with higher alpha
                    group = next(iter(present_groups))
                    color = list(group_colors[group])
                    # Ensure color has 4 elements (RGBA), add alpha if not present
                    if len(color) == 3:
                        color.append(0.7)  # Add alpha
                    else:
                        color[3] = 0.7  # Set alpha
                    viz_matrix[slot_idx, day_idx] = color
                else:
                    # Just one group, use its color
                    group = next(iter(present_groups))
                    color = list(group_colors[group])
                    # Ensure color has alpha channel
                    if len(color) == 3:
                        color.append(0.5)  # Add alpha
                    viz_matrix[slot_idx, day_idx] = color
    
    # Create subplot for the timetable
    gs = plt.GridSpec(3, 1, height_ratios=[6, 1, 3])
    ax1 = plt.subplot(gs[0])
    
    # Plot the matrix
    im = ax1.imshow(viz_matrix, aspect='auto')
    
    # Configure the plot
    ax1.set_title(title, fontsize=16, fontweight='bold')
    ax1.set_xlabel("Day", fontsize=12)
    ax1.set_ylabel("Time Slot", fontsize=12)
    
    # Set x-axis labels (days)
    ax1.set_xticks(range(num_days))
    ax1.set_xticklabels([day.capitalize() for day in pattern_days], rotation=0)
    
    # Set y-axis labels (time slots)
    if is_theory:
        ax1.set_yticks(range(num_slots))
        ax1.set_yticklabels(THEORY_SLOTS)
    else:
        ax1.set_yticks(range(num_slots))
        ax1.set_yticklabels([f"{slot} ({LAB_SESSIONS[slot]['time_range']})" for slot in LAB_SLOTS])
    
    # Add grid lines
    ax1.grid(True, color='gray', linestyle='-', linewidth=0.5, alpha=0.3)
    
    # Add annotations for multiple groups
    for day_idx in range(num_days):
        for slot_idx in range(num_slots):
            present_groups = timetable[day_idx][slot_idx]
            if len(present_groups) > 0:
                ax1.text(day_idx, slot_idx, f"{len(present_groups)}", 
                        ha='center', va='center', fontsize=10, fontweight='bold',
                        color='black' if len(present_groups) == 1 else 'white')
    
    # Create legend for groups
    legend_elements = [
        Patch(facecolor=group_colors[group], edgecolor='black', alpha=0.5, 
             label=f"{group} ({group_slot_counts[group]} slots)")
        for group in group_keys
    ]
    ax1.legend(handles=legend_elements, title="Groups", loc="upper right", 
              bbox_to_anchor=(1.15, 1))
    
    # Add utilization bar chart
    ax2 = plt.subplot(gs[1])
    
    # Day utilization
    day_labels = [day.capitalize() for day in pattern_days]
    ax2.bar(day_labels, [day_counts[day] for day in pattern_days], color='skyblue')
    ax2.set_title("Sessions per Day", fontsize=12)
    ax2.set_ylim(0, max(day_counts.values()) + 1)
    
    # Add text summary
    ax3 = plt.subplot(gs[2])
    ax3.axis('off')
    
    # Create summary text
    summary_text = f"Summary for {title}\n\n"
    summary_text += f"Total Groups: {len(group_keys)}\n"
    summary_text += f"Total Sessions: {total_sessions}\n\n"
    
    # Time slot utilization
    summary_text += "Time Slot Utilization:\n"
    for slot_idx in range(num_slots):
        if is_theory:
            slot_name = THEORY_SLOTS[slot_idx]
        else:
            slot_name = f"{LAB_SLOTS[slot_idx]} ({LAB_SESSIONS[LAB_SLOTS[slot_idx]]['time_range']})"
        summary_text += f"  {slot_name}: {slot_counts[slot_idx]} sessions\n"
    
    # Group summary
    summary_text += "\nGroup Summary:\n"
    for group in group_keys:
        summary_text += f"  {group}: {group_slot_counts[group]} sessions\n"
        
    # Utilization percentage
    max_possible = num_days * num_slots * len(group_keys)
    utilization = total_sessions / max_possible * 100 if max_possible > 0 else 0
    summary_text += f"\nOverall Timetable Utilization: {utilization:.1f}%"
    
    ax3.text(0, 1, summary_text, va='top', fontsize=10, linespacing=1.5)
    
    # Adjust layout
    plt.tight_layout()
    
    # Save the figure
    plt.savefig(filename, dpi=150, bbox_inches='tight')
    print(f"Saved visualization to {filename}")
    plt.close()

def generate_group_distribution_visualizations():
    """Generate visualizations for theory and lab group distributions."""
    # Find schedule files
    theory_file, lab_file = find_schedule_files()
    
    # Create output directory
    output_dir = "group_visualizations"
    os.makedirs(output_dir, exist_ok=True)
    
    # Process theory schedule
    if theory_file:
        theory_data = load_schedule_data(theory_file)
        if theory_data:
            # Group by department and semester
            theory_groups, theory_patterns = group_sessions_by_dept_semester(theory_data, is_theory=True)
            
            # Generate visualizations for each department and semester
            for (dept, semester), groups in theory_groups.items():
                if not groups:
                    continue
                
                # Get day pattern for this department/semester
                day_pattern = theory_patterns.get((dept, semester), 'Tuesday-Saturday')
                
                # Create timetable matrix
                timetable, pattern_days = create_group_timetable_matrix(groups, day_pattern, is_theory=True)
                
                # Generate title and filename
                title = f"Theory Group Distribution - {dept} Semester {semester} ({day_pattern})"
                safe_dept = dept.replace(' ', '_').replace('&', 'and')
                filename = os.path.join(output_dir, f"theory_groups_{safe_dept}_S{semester}.png")
                
                # Create visualization
                visualize_group_timetable(timetable, groups, title, filename, pattern_days, is_theory=True)
    
    # Process lab schedule
    if lab_file:
        lab_data = load_schedule_data(lab_file)
        if lab_data:
            # Group by department and semester
            lab_groups, lab_patterns = group_sessions_by_dept_semester(lab_data, is_theory=False)
            
            # Generate visualizations for each department and semester
            for (dept, semester), groups in lab_groups.items():
                if not groups:
                    continue
                
                # Get day pattern for this department/semester
                day_pattern = lab_patterns.get((dept, semester), 'Tuesday-Saturday')
                
                # Create timetable matrix
                timetable, pattern_days = create_group_timetable_matrix(groups, day_pattern, is_theory=False)
                
                # Generate title and filename
                title = f"Lab Group Distribution - {dept} Semester {semester} ({day_pattern})"
                safe_dept = dept.replace(' ', '_').replace('&', 'and')
                filename = os.path.join(output_dir, f"lab_groups_{safe_dept}_S{semester}.png")
                
                # Create visualization
                visualize_group_timetable(timetable, groups, title, filename, pattern_days, is_theory=False)
    
    # Generate combined visualization for each department and semester
    if theory_file and lab_file:
        theory_data = load_schedule_data(theory_file)
        lab_data = load_schedule_data(lab_file)
        
        if theory_data and lab_data:
            theory_groups, theory_patterns = group_sessions_by_dept_semester(theory_data, is_theory=True)
            lab_groups, lab_patterns = group_sessions_by_dept_semester(lab_data, is_theory=False)
            
            # Find common department/semesters
            common_dept_sems = set(theory_groups.keys()) & set(lab_groups.keys())
            
            for dept_sem in common_dept_sems:
                dept, semester = dept_sem
                
                # Get day pattern (use theory pattern, fallback to lab pattern)
                day_pattern = theory_patterns.get(dept_sem) or lab_patterns.get(dept_sem, 'Tuesday-Saturday')
                
                # Create combined visualization
                fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(15, 18))  # Increased height
                
                # Theory timetable
                theory_timetable, theory_pattern_days = create_group_timetable_matrix(theory_groups[dept_sem], day_pattern, is_theory=True)
                
                # Lab timetable
                lab_timetable, lab_pattern_days = create_group_timetable_matrix(lab_groups[dept_sem], day_pattern, is_theory=False)
                
                # Generate group colors
                all_groups = set(theory_groups[dept_sem].keys()) | set(lab_groups[dept_sem].keys())
                all_groups = sorted(all_groups)
                colors = generate_colors(len(all_groups))
                group_colors = {group: colors[i % len(colors)] for i, group in enumerate(all_groups)}
                
                # Track statistics  
                theory_stats = {
                    'total_sessions': 0,
                    'day_counts': {day: 0 for day in theory_pattern_days},
                    'slot_counts': {slot_idx: 0 for slot_idx in range(len(THEORY_SLOTS))},
                    'group_counts': {group: 0 for group in theory_groups[dept_sem].keys()}
                }
                
                lab_stats = {
                    'total_sessions': 0,
                    'day_counts': {day: 0 for day in lab_pattern_days},
                    'slot_counts': {slot_idx: 0 for slot_idx in range(len(LAB_SLOTS))},
                    'group_counts': {group: 0 for group in lab_groups[dept_sem].keys()}
                }
                
                # Create theory visualization
                viz_theory_matrix = np.zeros((len(THEORY_SLOTS), len(theory_pattern_days), 4))  # RGBA values
                for day_idx in range(len(theory_pattern_days)):
                    for slot_idx in range(len(THEORY_SLOTS)):
                        present_groups = theory_timetable[day_idx][slot_idx]
                        if present_groups:
                            # Count stats
                            theory_stats['total_sessions'] += len(present_groups)
                            theory_stats['day_counts'][theory_pattern_days[day_idx]] += len(present_groups)
                            theory_stats['slot_counts'][slot_idx] += len(present_groups)
                            for group in present_groups:
                                theory_stats['group_counts'][group] += 1
                                
                            # Use the first group's color
                            group = next(iter(present_groups))
                            color = list(group_colors[group])
                            if len(color) == 3:
                                color.append(0.5)  # Add alpha
                            viz_theory_matrix[slot_idx, day_idx] = color
                
                # Create lab visualization
                viz_lab_matrix = np.zeros((len(LAB_SLOTS), len(lab_pattern_days), 4))  # RGBA values
                for day_idx in range(len(lab_pattern_days)):
                    for slot_idx in range(len(LAB_SLOTS)):
                        present_groups = lab_timetable[day_idx][slot_idx]
                        if present_groups:
                            # Count stats
                            lab_stats['total_sessions'] += len(present_groups)
                            lab_stats['day_counts'][lab_pattern_days[day_idx]] += len(present_groups)
                            lab_stats['slot_counts'][slot_idx] += len(present_groups)
                            for group in present_groups:
                                lab_stats['group_counts'][group] += 1
                                
                            # Use the first group's color
                            group = next(iter(present_groups))
                            color = list(group_colors[group])
                            if len(color) == 3:
                                color.append(0.5)  # Add alpha
                            viz_lab_matrix[slot_idx, day_idx] = color
                
                # Plot theory matrix
                ax1.imshow(viz_theory_matrix, aspect='auto')
                ax1.set_title(f"Theory Group Distribution - {dept} Semester {semester} ({day_pattern})", fontsize=14)
                ax1.set_xlabel("Day", fontsize=12)
                ax1.set_ylabel("Time Slot", fontsize=12)
                ax1.set_xticks(range(len(theory_pattern_days)))
                ax1.set_xticklabels([day.capitalize() for day in theory_pattern_days], rotation=0)
                ax1.set_yticks(range(len(THEORY_SLOTS)))
                ax1.set_yticklabels(THEORY_SLOTS)
                ax1.grid(True, color='gray', linestyle='-', linewidth=0.5, alpha=0.3)
                
                # Add annotations to theory matrix
                for day_idx in range(len(theory_pattern_days)):
                    for slot_idx in range(len(THEORY_SLOTS)):
                        present_groups = theory_timetable[day_idx][slot_idx]
                        if len(present_groups) > 0:
                            ax1.text(day_idx, slot_idx, f"{len(present_groups)}", 
                                    ha='center', va='center', fontsize=10, fontweight='bold',
                                    color='black' if len(present_groups) == 1 else 'white')
                
                # Plot lab matrix
                ax2.imshow(viz_lab_matrix, aspect='auto')
                ax2.set_title(f"Lab Group Distribution - {dept} Semester {semester} ({day_pattern})", fontsize=14)
                ax2.set_xlabel("Day", fontsize=12)
                ax2.set_ylabel("Lab Session", fontsize=12)
                ax2.set_xticks(range(len(lab_pattern_days)))
                ax2.set_xticklabels([day.capitalize() for day in lab_pattern_days], rotation=0)
                ax2.set_yticks(range(len(LAB_SLOTS)))
                ax2.set_yticklabels([f"{slot} ({LAB_SESSIONS[slot]['time_range']})" for slot in LAB_SLOTS])
                ax2.grid(True, color='gray', linestyle='-', linewidth=0.5, alpha=0.3)
                
                # Add annotations to lab matrix
                for day_idx in range(len(lab_pattern_days)):
                    for slot_idx in range(len(LAB_SLOTS)):
                        present_groups = lab_timetable[day_idx][slot_idx]
                        if len(present_groups) > 0:
                            ax2.text(day_idx, slot_idx, f"{len(present_groups)}", 
                                    ha='center', va='center', fontsize=10, fontweight='bold',
                                    color='black' if len(present_groups) == 1 else 'white')
                
                # Create legend for groups
                legend_elements = [
                    Patch(facecolor=group_colors[group], edgecolor='black', alpha=0.5, 
                         label=f"{group}")
                    for group in all_groups
                ]
                fig.legend(handles=legend_elements, title="Groups", loc="upper right", 
                          bbox_to_anchor=(1.0, 0.98))
                
                # Add text summary
                ax_text = fig.add_axes([0.1, 0.01, 0.8, 0.15])  # [left, bottom, width, height]
                ax_text.axis('off')
                
                # Create summary text
                summary_text = f"COMBINED SUMMARY - {dept} SEMESTER {semester} ({day_pattern})\n\n"
                summary_text += f"Total Groups: {len(all_groups)}\n"
                summary_text += f"Theory Groups: {len(theory_groups[dept_sem])}, Lab Groups: {len(lab_groups[dept_sem])}\n"
                summary_text += f"Theory Sessions: {theory_stats['total_sessions']}, Lab Sessions: {lab_stats['total_sessions']}\n\n"
                
                # Compute overlap between theory and lab groups
                theory_group_set = set(theory_groups[dept_sem].keys())
                lab_group_set = set(lab_groups[dept_sem].keys())
                overlap_groups = theory_group_set & lab_group_set
                
                summary_text += f"Groups with both Theory & Lab: {len(overlap_groups)}\n"
                if overlap_groups:
                    summary_text += "Overlapping Groups: " + ", ".join(sorted(overlap_groups)) + "\n\n"
                else:
                    summary_text += "\n"
                
                # Theory time slot stats
                summary_text += "Theory Time Slot Utilization:\n"
                for slot_idx, slot in enumerate(THEORY_SLOTS):
                    if theory_stats['slot_counts'][slot_idx] > 0:
                        summary_text += f"  {slot}: {theory_stats['slot_counts'][slot_idx]} sessions\n"
                
                # Lab time slot stats
                summary_text += "\nLab Session Utilization:\n"
                for slot_idx, slot in enumerate(LAB_SLOTS):
                    if lab_stats['slot_counts'][slot_idx] > 0:
                        summary_text += f"  {slot} ({LAB_SESSIONS[slot]['time_range']}): {lab_stats['slot_counts'][slot_idx]} sessions\n"
                
                ax_text.text(0, 1, summary_text, va='top', fontsize=10, linespacing=1.5)
                
                # Adjust layout
                plt.tight_layout(rect=[0, 0.15, 1, 1])  # Leave space for the text at the bottom
                
                # Save the figure
                safe_dept = dept.replace(' ', '_').replace('&', 'and')
                filename = os.path.join(output_dir, f"combined_groups_{safe_dept}_S{semester}.png")
                plt.savefig(filename, dpi=150, bbox_inches='tight')
                print(f"Saved combined visualization to {filename}")
                plt.close()

if __name__ == "__main__":
    generate_group_distribution_visualizations()
    print("Group distribution visualizations complete. Check the 'group_visualizations' directory.") 