import os
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import numpy as np
from matplotlib.gridspec import GridSpec

class LabScheduleVisualizer:
    def __init__(self, schedule_data, output_dir):
        """Initialize the lab schedule visualizer."""
        self.schedule_df = pd.DataFrame(schedule_data) if schedule_data else pd.DataFrame()
        self.output_dir = output_dir
        
        # Lab schedule days structure
        self.days = ["tuesday", "wed", "thur", "fri", "sat"]
        
        # Lab time sessions (6 sessions per day - each session = 2 practical hours)
        self.lab_sessions = {
            'L1': '8:00 - 9:40',   # 2 hours
            'L2': '9:50 - 11:30',  # 2 hours  
            'L3': '11:50 - 1:30',  # 2 hours
            'L4': '1:50 - 3:30',   # 2 hours
            'L5': '3:50 - 5:30',   # 2 hours
            'L6': '5:30 - 7:10'    # 2 hours (approximately)
        }
        self.lab_session_names = list(self.lab_sessions.keys())
        
        if not self.schedule_df.empty:
            # Filter for only lab/practical assignments
            self.lab_data = self.schedule_df[self.schedule_df['slot_type'] == 'Practical'].copy()
            
            # Create color map for courses (use display_course_code if available)
            if not self.lab_data.empty:
                # Use display_course_code for differentiation, fallback to course_code
                self.lab_data['display_code'] = self.lab_data.apply(
                    lambda row: row.get('display_course_code', row.get('course_code', 'Unknown')), axis=1)
                
                self.courses = self.lab_data['display_code'].unique()
                colors = plt.cm.tab20(np.linspace(0, 1, len(self.courses)))
                self.course_colors = {course: mcolors.rgb2hex(color) for course, color in zip(self.courses, colors)}
                
                # Create color map for lab sessions
                session_colors = plt.cm.Set3(np.linspace(0, 1, len(self.lab_sessions)))
                self.session_colors = {session: mcolors.rgb2hex(color) for session, color in zip(self.lab_sessions.keys(), session_colors)}
                
                # Pre-compute unique lists for efficiency
                self.teachers = self.lab_data['teacher_id'].unique()
                self.lab_rooms = self.lab_data['room_id'].unique()
            else:
                self.courses = []
                self.course_colors = {}
                self.session_colors = {}
                self.teachers = []
                self.lab_rooms = []
        else:
            self.courses = []
            self.course_colors = {}
            self.session_colors = {}
            self.lab_data = pd.DataFrame()
            self.teachers = []
            self.lab_rooms = []
    
    def generate_all_lab_visualizations(self):
        """Generate all lab schedule visualizations."""
        if self.lab_data.empty:
            print("No lab schedule data available for visualization")
            return
        
        print(f"Generating lab visualizations for {len(self.teachers)} teachers...")
        self.generate_master_lab_schedule()
        self.generate_teacher_lab_schedules()
        self.generate_lab_room_schedules()
        self.generate_lab_analysis()
    
    def generate_master_lab_schedule(self):
        """Generate a master lab schedule visualization."""
        if self.lab_data.empty:
            print("No lab data available for master schedule")
            return
            
        fig = plt.figure(figsize=(24, 12))
        ax = fig.add_subplot(111)
        
        self._plot_lab_schedule(ax, 'Master Lab Schedule', self.lab_data)
        ax.set_title('Master Laboratory Schedule\n(Lab Sessions: L1=8:00-9:40, L2=9:50-11:30, L3=11:50-1:30, etc.)', fontsize=16)
        
        plt.tight_layout()
        fig.savefig(os.path.join(self.output_dir, 'master_lab_schedule.png'), 
                   dpi=300, bbox_inches='tight')
        plt.close(fig)
        print("Master lab schedule visualization saved")
    
    def generate_teacher_lab_schedules(self):
        """Generate lab schedule visualizations for each teacher."""
        for teacher in self.teachers:
            teacher_lab_df = self.lab_data[self.lab_data['teacher_id'] == teacher]
            if not teacher_lab_df.empty:
                self._create_teacher_lab_schedule(teacher, teacher_lab_df)
    
    def generate_lab_room_schedules(self):
        """Generate lab schedule visualizations for each lab room."""
        for room in self.lab_rooms:
            room_lab_df = self.lab_data[self.lab_data['room_id'] == room]
            if not room_lab_df.empty:
                room_number = room_lab_df.iloc[0]['room_number']
                self._create_lab_room_schedule(room, room_number, room_lab_df)
    
    def generate_lab_analysis(self):
        """Generate lab utilization analysis."""
        if self.lab_data.empty:
            return
        
        fig = plt.figure(figsize=(20, 12))
        gs = GridSpec(2, 2, figure=fig)
        
        # Lab session distribution
        ax1 = fig.add_subplot(gs[0, 0])
        self._plot_lab_session_distribution(ax1)
        
        # Daily lab usage pattern
        ax2 = fig.add_subplot(gs[0, 1])
        self._plot_daily_lab_usage(ax2)
        
        # Course lab hour distribution
        ax3 = fig.add_subplot(gs[1, 0])
        self._plot_course_lab_hours(ax3)
        
        # Lab room utilization
        ax4 = fig.add_subplot(gs[1, 1])
        self._plot_lab_room_utilization(ax4)
        
        plt.suptitle('Laboratory Schedule Analysis', fontsize=16)
        plt.tight_layout()
        fig.savefig(os.path.join(self.output_dir, 'lab_analysis.png'), 
                   dpi=300, bbox_inches='tight')
        plt.close(fig)
        print("Lab analysis visualization saved")
    
    def _plot_lab_schedule(self, ax, schedule_type, df):
        """Plot the lab schedule for a given type."""
        if df.empty:
            ax.text(0.5, 0.5, f'No {schedule_type} assignments', 
                   ha='center', va='center', transform=ax.transAxes)
            return
        
        # Create a grid for days and lab sessions with lists to handle multiple assignments
        grid = {}  # Use dict with lists to handle multiple course instances per session
        session_grid = np.empty((len(self.days), len(self.lab_session_names)), dtype=object)
        
        for _, row in df.iterrows():
            day = row['day']
            # Map time interval to lab session
            lab_session = self._map_time_to_lab_session(row['time_interval'])
            
            if day in self.days and lab_session in self.lab_session_names:
                day_idx = self.days.index(day)
                session_idx = self.lab_session_names.index(lab_session)
                
                course_code = row.get('display_course_code', row['course_code'])  # Use display code for S1, S2 differentiation
                teacher_id = row['teacher_id']
                room_number = row['room_number']
                course_instance_id = row.get('course_instance_id', '')
                
                # Create unique key for day-session combination
                grid_key = (day_idx, session_idx)
                
                # Initialize grid entry if not exists
                if grid_key not in grid:
                    grid[grid_key] = []
                    session_grid[day_idx, session_idx] = lab_session
                
                # Add course instance info to the list
                course_info = {
                    'course_code': course_code,
                    'teacher_id': teacher_id,
                    'room_number': room_number,
                    'course_instance_id': course_instance_id,
                    'student_count': row.get('student_count', 70)  # Default to 70 if not present
                }
                
                # Check if this course instance is already added (avoid duplicates)
                existing_instances = [info['course_instance_id'] for info in grid[grid_key]]
                if course_instance_id not in existing_instances:
                    grid[grid_key].append(course_info)
        
        # Plot the grid
        for i, day in enumerate(self.days):
            for j, session_name in enumerate(self.lab_session_names):
                grid_key = (i, j)
                if grid_key in grid and grid[grid_key]:
                    session = session_grid[i, j]
                    color = self.session_colors.get(session, '#FFFFFF')
                    
                    # Create rectangle
                    rect = plt.Rectangle((j, len(self.days) - i - 1), 1, 1, 
                                       facecolor=color, edgecolor='black', linewidth=0.5)
                    ax.add_patch(rect)
                    
                    # Create display text for multiple course instances
                    course_instances = grid[grid_key]
                    if len(course_instances) == 1:
                        # Single course instance
                        course_info = course_instances[0]
                        # Show course code with instance ID
                        instance_id = course_info['course_instance_id']
                        if instance_id:
                            course_display = f"{course_info['course_code']}\n(ID: {instance_id})"
                        else:
                            course_display = course_info['course_code']
                        display_text = f"{course_display}\n{course_info['room_number']}\nStudents: {course_info['student_count']}"
                    else:
                        # Multiple course instances - show all with distinct IDs
                        course_lines = []
                        for idx, course_info in enumerate(course_instances):
                            instance_id = course_info['course_instance_id']
                            if instance_id:
                                course_lines.append(f"{course_info['course_code']} (ID:{instance_id})")
                            else:
                                course_lines.append(f"{course_info['course_code']} ({idx+1})")
                            course_lines.append(f"{course_info['room_number']}")
                        display_text = '\n'.join(course_lines)
                    
                    # Add text
                    ax.text(j + 0.5, len(self.days) - i - 0.5, display_text,
                           ha='center', va='center', fontsize=8, weight='bold')
                    
                    # Add session label in corner
                    ax.text(j + 0.1, len(self.days) - i - 0.1, session,
                           ha='left', va='top', fontsize=7, 
                           bbox=dict(boxstyle="round,pad=0.1", facecolor='white', alpha=0.7))
        
        # Set axes properties
        ax.set_xlim(0, len(self.lab_session_names))
        ax.set_ylim(0, len(self.days))
        ax.set_xticks(range(len(self.lab_session_names)))
        
        # Show lab session timing
        ax.set_xticklabels([f"{session}\n{self.lab_sessions[session]}" 
                           for session in self.lab_session_names], 
                          rotation=45, ha='right')
        ax.set_yticks(range(len(self.days)))
        ax.set_yticklabels([day.capitalize() for day in reversed(self.days)])
        ax.grid(True, alpha=0.3)
    
    def _create_teacher_lab_schedule(self, teacher_id, teacher_lab_df):
        """Create a lab schedule visualization for a specific teacher."""
        # Get teacher information
        teacher_info = teacher_lab_df.iloc[0]
        teacher_first_name = teacher_info.get('first_name', '')
        teacher_last_name = teacher_info.get('last_name', '')
        teacher_name = f"{teacher_first_name} {teacher_last_name}".strip()
        if not teacher_name:
            teacher_name = teacher_info.get('staff_code', f'Teacher {teacher_id}')
        
        fig = plt.figure(figsize=(20, 10))
        ax = fig.add_subplot(111)
        
        self._plot_teacher_lab_schedule(ax, teacher_id, teacher_lab_df)
        ax.set_title(f'Laboratory Schedule for {teacher_name} (ID: {teacher_id})\n(Lab Sessions: Each session = 2 practical hours)', fontsize=16)
        
        plt.tight_layout()
        filename = f'teacher_{teacher_id}_{teacher_name.replace(" ", "_")}_lab_schedule.png'
        fig.savefig(os.path.join(self.output_dir, filename), 
                   dpi=300, bbox_inches='tight')
        plt.close(fig)
        print(f"Lab schedule saved for teacher {teacher_name} (ID: {teacher_id})")
    
    def _create_lab_room_schedule(self, room_id, room_number, room_lab_df):
        """Create a lab schedule visualization for a specific lab room."""
        room_info = room_lab_df.iloc[0]
        room_type = room_info.get('room_type', 'Lab')
        block = room_info.get('block', '')
        
        room_title = f"{room_type} {room_number}"
        if block:
            room_title += f" ({block})"
        
        fig = plt.figure(figsize=(20, 10))
        ax = fig.add_subplot(111)
        
        self._plot_lab_room_schedule(ax, room_id, room_lab_df)
        ax.set_title(f'Laboratory Schedule for {room_title}', fontsize=16)
        
        plt.tight_layout()
        filename = f'lab_room_{room_number.replace("/", "_")}_{room_id}_schedule.png'
        fig.savefig(os.path.join(self.output_dir, filename), 
                   dpi=300, bbox_inches='tight')
        plt.close(fig)
        print(f"Lab room schedule saved for {room_title}")
    
    def _plot_teacher_lab_schedule(self, ax, teacher_id, teacher_lab_df):
        """Plot the lab schedule for a specific teacher."""
        # Create a grid for days and lab sessions with lists to handle multiple assignments
        grid = {}  # Use dict with lists to handle multiple course instances per session
        session_grid = np.empty((len(self.days), len(self.lab_session_names)), dtype=object)
        
        for _, row in teacher_lab_df.iterrows():
            day = row['day']
            lab_session = self._map_time_to_lab_session(row['time_interval'])
            
            if day in self.days and lab_session in self.lab_session_names:
                day_idx = self.days.index(day)
                session_idx = self.lab_session_names.index(lab_session)
                
                course_code = row.get('display_course_code', row['course_code'])  # Use display code for S1, S2 differentiation
                room_number = row['room_number']
                student_count = row.get('student_count', 70)  # Default to 70 if not present
                course_instance_id = row.get('course_instance_id', '')
                
                # Create unique key for day-session combination
                grid_key = (day_idx, session_idx)
                
                # Initialize grid entry if not exists
                if grid_key not in grid:
                    grid[grid_key] = []
                    session_grid[day_idx, session_idx] = lab_session
                
                # Add course instance info to the list
                course_info = {
                    'course_code': course_code,
                    'room_number': room_number,
                    'student_count': student_count,
                    'course_instance_id': course_instance_id
                }
                
                # Check if this course instance is already added (avoid duplicates)
                existing_instances = [info['course_instance_id'] for info in grid[grid_key]]
                if course_instance_id not in existing_instances:
                    grid[grid_key].append(course_info)
        
        # Plot the grid
        for i, day in enumerate(self.days):
            for j, session_name in enumerate(self.lab_session_names):
                grid_key = (i, j)
                if grid_key in grid and grid[grid_key]:
                    session = session_grid[i, j]
                    color = self.session_colors.get(session, '#FFFFFF')
                    
                    # Create rectangle
                    rect = plt.Rectangle((j, len(self.days) - i - 1), 1, 1, 
                                       facecolor=color, edgecolor='black', linewidth=0.5)
                    ax.add_patch(rect)
                    
                    # Create display text for multiple course instances
                    course_instances = grid[grid_key]
                    if len(course_instances) == 1:
                        # Single course instance
                        course_info = course_instances[0]
                        # Show course code with instance ID
                        instance_id = course_info['course_instance_id']
                        if instance_id:
                            course_display = f"{course_info['course_code']}\n(ID: {instance_id})"
                        else:
                            course_display = course_info['course_code']
                        display_text = f"{course_display}\n{course_info['room_number']}\nStudents: {course_info['student_count']}"
                    else:
                        # Multiple course instances - show all with distinct IDs
                        course_lines = []
                        for idx, course_info in enumerate(course_instances):
                            instance_id = course_info['course_instance_id']
                            if instance_id:
                                course_lines.append(f"{course_info['course_code']} (ID:{instance_id})")
                            else:
                                course_lines.append(f"{course_info['course_code']} ({idx+1})")
                            course_lines.append(f"{course_info['room_number']}")
                        display_text = '\n'.join(course_lines)
                    
                    # Add text
                    ax.text(j + 0.5, len(self.days) - i - 0.5, display_text,
                           ha='center', va='center', fontsize=8, weight='bold')
                    
                    # Add session label
                    ax.text(j + 0.1, len(self.days) - i - 0.1, session,
                           ha='left', va='top', fontsize=7, 
                           bbox=dict(boxstyle="round,pad=0.1", facecolor='white', alpha=0.8))
        
        # Set axes properties
        ax.set_xlim(0, len(self.lab_session_names))
        ax.set_ylim(0, len(self.days))
        ax.set_xticks(range(len(self.lab_session_names)))
        ax.set_xticklabels([f"{session}\n{self.lab_sessions[session]}" 
                           for session in self.lab_session_names], 
                          rotation=45, ha='right')
        ax.set_yticks(range(len(self.days)))
        ax.set_yticklabels([day.capitalize() for day in reversed(self.days)])
        ax.grid(True, alpha=0.3)
    
    def _plot_lab_room_schedule(self, ax, room_id, room_lab_df):
        """Plot the lab schedule for a specific room."""
        # Similar implementation to teacher schedule but focused on room utilization
        grid = np.empty((len(self.days), len(self.lab_session_names)), dtype=object)
        session_grid = np.empty((len(self.days), len(self.lab_session_names)), dtype=object)
        
        for _, row in room_lab_df.iterrows():
            day = row['day']
            lab_session = self._map_time_to_lab_session(row['time_interval'])
            
            if day in self.days and lab_session in self.lab_session_names:
                day_idx = self.days.index(day)
                session_idx = self.lab_session_names.index(lab_session)
                
                course_code = row.get('display_course_code', row['course_code'])  # Use display code for S1, S2 differentiation
                teacher_id = row['teacher_id']
                student_count = row.get('student_count', 70)  # Default to 70 if not present
                
                # Create display text
                display_text = f"{course_code}\nT:{teacher_id}\nStudents: {student_count}"
                grid[day_idx, session_idx] = display_text
                session_grid[day_idx, session_idx] = lab_session
        
        # Plot the grid (similar to teacher schedule)
        for i, day in enumerate(self.days):
            for j, session_name in enumerate(self.lab_session_names):
                if grid[i, j] is not None:
                    session = session_grid[i, j]
                    color = self.session_colors.get(session, '#FFFFFF')
                    
                    # Create rectangle
                    rect = plt.Rectangle((j, len(self.days) - i - 1), 1, 1, 
                                       facecolor=color, edgecolor='black', linewidth=0.5)
                    ax.add_patch(rect)
                    
                    ax.text(j + 0.5, len(self.days) - i - 0.5, grid[i, j],
                           ha='center', va='center', fontsize=9, weight='bold')
                    
                    ax.text(j + 0.1, len(self.days) - i - 0.1, session,
                           ha='left', va='top', fontsize=8, 
                           bbox=dict(boxstyle="round,pad=0.1", facecolor='white', alpha=0.8))
        
        # Set axes properties
        ax.set_xlim(0, len(self.lab_session_names))
        ax.set_ylim(0, len(self.days))
        ax.set_xticks(range(len(self.lab_session_names)))
        ax.set_xticklabels([f"{session}\n{self.lab_sessions[session]}" 
                           for session in self.lab_session_names], 
                          rotation=45, ha='right')
        ax.set_yticks(range(len(self.days)))
        ax.set_yticklabels([day.capitalize() for day in reversed(self.days)])
        ax.grid(True, alpha=0.3)
    
    def _map_time_to_lab_session(self, time_interval):
        """Map a time interval to the corresponding lab session."""
        # Map based on exact time intervals to avoid conflicts
        time_to_session_map = {
            '8:00 - 8:50': 'L1',
            '8:50 - 9:40': 'L1',
            '9:50 - 10:40': 'L2', 
            '10:40 - 11:30': 'L2',
            '11:50 - 12:40': 'L3',
            '12:40 - 1:30': 'L3',
            '1:50 - 2:40': 'L4',
            '2:40 - 3:30': 'L4',
            '3:50 - 4:40': 'L5',
            '4:40 - 5:30': 'L5',
            '5:30 - 6:20': 'L6',
            '6:20 - 7:10': 'L6'
        }
        
        # Try exact match first
        if time_interval in time_to_session_map:
            return time_to_session_map[time_interval]
        
        # Fallback to range checking for partial matches
        if '8:00' in time_interval or ('8:50' in time_interval and '9:40' in time_interval):
            return 'L1'
        elif '9:50' in time_interval or ('10:40' in time_interval and '11:30' in time_interval):
            return 'L2'
        elif '11:50' in time_interval or ('12:40' in time_interval and '1:30' in time_interval):
            return 'L3'
        elif '1:50' in time_interval or ('2:40' in time_interval and '3:30' in time_interval):
            return 'L4'
        elif '3:50' in time_interval or ('4:40' in time_interval and '5:30' in time_interval):
            return 'L5'
        elif '5:30' in time_interval and '6:20' in time_interval:
            return 'L6'
        elif '6:20' in time_interval and '7:10' in time_interval:
            return 'L6'
        else:
            # Default mapping - try to extract session from time
            for session, time_range in self.lab_sessions.items():
                if time_interval in time_range or time_range in time_interval:
                    return session
            return 'L1'  # Default
    
    def _plot_lab_session_distribution(self, ax):
        """Plot lab session distribution."""
        if self.lab_data.empty:
            ax.text(0.5, 0.5, 'No lab data available', ha='center', va='center', transform=ax.transAxes)
            return
        
        # Map each assignment to lab session
        lab_sessions_assigned = []
        for _, row in self.lab_data.iterrows():
            session = self._map_time_to_lab_session(row['time_interval'])
            lab_sessions_assigned.append(session)
        
        session_counts = pd.Series(lab_sessions_assigned).value_counts()
        session_counts = session_counts.reindex(self.lab_session_names, fill_value=0)
        
        bars = ax.bar(range(len(self.lab_session_names)), session_counts.values)
        ax.set_xticks(range(len(self.lab_session_names)))
        ax.set_xticklabels(self.lab_session_names)
        ax.set_ylabel('Number of Lab Sessions')
        ax.set_title('Lab Session Distribution')
        
        # Color bars according to session colors
        for i, (session, bar) in enumerate(zip(self.lab_session_names, bars)):
            bar.set_color(self.session_colors.get(session, '#CCCCCC'))
    
    def _plot_daily_lab_usage(self, ax):
        """Plot daily lab usage pattern."""
        daily_counts = self.lab_data['day'].value_counts()
        daily_counts = daily_counts.reindex(self.days, fill_value=0)
        
        bars = ax.bar(range(len(self.days)), daily_counts.values)
        ax.set_xticks(range(len(self.days)))
        ax.set_xticklabels([day.capitalize() for day in self.days])
        ax.set_ylabel('Number of Lab Sessions')
        ax.set_title('Daily Lab Usage Distribution')
        
        # Color bars with gradient
        colors = plt.cm.viridis(np.linspace(0, 1, len(self.days)))
        for bar, color in zip(bars, colors):
            bar.set_color(color)
    
    def _plot_course_lab_hours(self, ax):
        """Plot course lab hour distribution."""
        if self.lab_data.empty:
            ax.text(0.5, 0.5, 'No lab data available', ha='center', va='center', transform=ax.transAxes)
            return
        
        # Use display_code for course differentiation (includes S1, S2 notation)
        course_counts = self.lab_data['display_code'].value_counts()
        
        # Limit to top 15 courses for readability
        top_courses = course_counts.head(15)
        
        bars = ax.bar(range(len(top_courses)), top_courses.values)
        ax.set_xticks(range(len(top_courses)))
        ax.set_xticklabels(top_courses.index, rotation=45, ha='right')
        ax.set_ylabel('Number of Lab Sessions')
        ax.set_title('Course Lab Hour Distribution (Top 15)')
        
        # Color bars according to course colors
        for i, (course, bar) in enumerate(zip(top_courses.index, bars)):
            bar.set_color(self.course_colors.get(course, '#CCCCCC'))
    
    def _plot_lab_room_utilization(self, ax):
        """Plot lab room utilization."""
        if self.lab_data.empty:
            ax.text(0.5, 0.5, 'No lab data available', ha='center', va='center', transform=ax.transAxes)
            return
        
        room_counts = self.lab_data['room_number'].value_counts()
        
        # Limit to top 15 rooms for readability
        top_rooms = room_counts.head(15)
        
        bars = ax.bar(range(len(top_rooms)), top_rooms.values)
        ax.set_xticks(range(len(top_rooms)))
        ax.set_xticklabels(top_rooms.index, rotation=45, ha='right')
        ax.set_ylabel('Number of Lab Sessions')
        ax.set_title('Lab Room Utilization (Top 15)')
        
        # Color bars with different colors
        colors = plt.cm.Set3(np.linspace(0, 1, len(top_rooms)))
        for bar, color in zip(bars, colors):
            bar.set_color(color) 