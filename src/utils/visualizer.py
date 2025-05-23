import os
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import numpy as np
from matplotlib.gridspec import GridSpec

class TimetableVisualizer:
    def __init__(self, schedule_df, output_dir):
        """Initialize the timetable visualizer."""
        self.schedule_df = schedule_df
        self.output_dir = output_dir
        self.days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
        self.theory_slots = [f"{h}:00-{h}:50" for h in range(8, 19)]
        self.lab_slots = [
            "8:00-9:40",    # L1
            "10:00-11:40",  # L2 
            "11:40-1:20",   # L3
            "1:20-3:00",    # L4
            "3:00-4:40",    # L5
            "5:10-6:50"     # L6
        ]
        
        # Create color map for courses
        self.courses = schedule_df['course_code'].unique()
        colors = plt.cm.tab20(np.linspace(0, 1, len(self.courses)))
        self.course_colors = {course: mcolors.rgb2hex(color) for course, color in zip(self.courses, colors)}
        
        # Pre-compute filtered data for efficiency
        self.theory_data = schedule_df[schedule_df['slot_type'] == 'Theory'].copy()
        self.lab_data = schedule_df[schedule_df['slot_type'] == 'Lab'].copy()
        
        # Pre-compute unique lists for efficiency
        self.teachers = schedule_df['teacher_id'].unique()
        self.rooms = schedule_df['room_id'].unique()
        
        # Create a mapping for course instance numbers
        self._create_instance_mapping()
        
        # Define shift information
        self.shifts = {
            'Shift1 (8:00-15:00)': {
                'name': 'Shift 1',
                'time': '8:00-15:00',
                'theory_slots': [f"{h}:00-{h}:50" for h in range(8, 15)],  # 8:00-14:50
                'lab_slots': ["8:00-9:40", "10:00-11:40", "11:40-1:20"],  # L1, L2, L3
                'color': '#E8F4FD'
            },
            'Shift2 (10:00-17:00)': {
                'name': 'Shift 2', 
                'time': '10:00-17:00',
                'theory_slots': [f"{h}:00-{h}:50" for h in range(10, 17)],  # 10:00-16:50
                'lab_slots': ["10:00-11:40", "11:40-1:20", "1:20-3:00", "3:00-4:40"],  # L2, L3, L4, L5
                'color': '#FFF2CC'
            },
            'Shift3 (12:00-19:00)': {
                'name': 'Shift 3',
                'time': '12:00-19:00', 
                'theory_slots': [f"{h}:00-{h}:50" for h in range(12, 19)],  # 12:00-18:50
                'lab_slots': ["11:40-1:20", "1:20-3:00", "3:00-4:40", "5:10-6:50"],  # L3, L4, L5, L6
                'color': '#E1D5E7'
            }
        }
    
    def _create_instance_mapping(self):
        """Create a mapping for course instances to display instance numbers."""
        self.instance_mapping = {}
        
        # Group by teacher_id and course_code
        for teacher_id in self.schedule_df['teacher_id'].unique():
            teacher_data = self.schedule_df[self.schedule_df['teacher_id'] == teacher_id]
            
            # For each unique course code this teacher teaches
            for course_code in teacher_data['course_code'].unique():
                course_data = teacher_data[teacher_data['course_code'] == course_code]
                
                # If multiple instances exist (by course_instance_id)
                if 'course_instance_id' in course_data.columns:
                    instance_ids = course_data['course_instance_id'].unique()
                    
                    if len(instance_ids) > 1:
                        # Create mapping from instance_id to instance number
                        for i, instance_id in enumerate(sorted(instance_ids), 1):
                            self.instance_mapping[(teacher_id, course_code, instance_id)] = i
    
    def generate_teacher_schedules(self):
        """Generate schedule visualizations for each teacher."""
        for teacher in self.teachers:
            teacher_df = self.schedule_df[self.schedule_df['teacher_id'] == teacher]
            if not teacher_df.empty:
                self._create_teacher_schedule(teacher, teacher_df)
    
    def generate_room_schedules(self):
        """Generate schedule visualizations for each room."""
        for room in self.rooms:
            room_df = self.schedule_df[self.schedule_df['room_id'] == room]
            if not room_df.empty:
                room_number = room_df.iloc[0]['room_number']
                self._create_room_schedule(room, room_number, room_df)
    
    def generate_master_schedule(self):
        """Generate a master schedule visualization."""
        # Create a figure with subplots for theory and lab schedules
        fig = plt.figure(figsize=(20, 16))
        gs = GridSpec(2, 1, height_ratios=[2, 1], figure=fig)
        
        # Theory schedule
        ax_theory = fig.add_subplot(gs[0])
        self._plot_schedule(ax_theory, 'Theory', self.theory_slots)
        ax_theory.set_title('Master Theory Schedule', fontsize=16)
        
        # Lab schedule
        ax_lab = fig.add_subplot(gs[1])
        self._plot_schedule(ax_lab, 'Lab', self.lab_slots)
        ax_lab.set_title('Master Lab Schedule', fontsize=16)
        
        plt.tight_layout()
        fig.savefig(os.path.join(self.output_dir, 'master_schedule.png'), dpi=300, bbox_inches='tight')
        plt.close(fig)
    
    def _create_teacher_schedule(self, teacher_id, teacher_df):
        """Create a schedule visualization for a specific teacher."""
        # Create a figure with subplots for theory and lab schedules
        fig = plt.figure(figsize=(16, 12))
        gs = GridSpec(2, 1, height_ratios=[2, 1], figure=fig)
        
        # Get teacher information
        teacher_info = self.schedule_df[self.schedule_df['teacher_id'] == teacher_id].iloc[0]
        # Extract teacher name from the first row
        teacher_first_name = teacher_info.get('first_name', '')
        teacher_last_name = teacher_info.get('last_name', '')
        teacher_name = f"{teacher_first_name} {teacher_last_name}".strip()
        if not teacher_name:
            # Fallback to staff code if name not available
            teacher_name = teacher_info.get('staff_code', f'Teacher {teacher_id}')
        
        # Theory schedule
        ax_theory = fig.add_subplot(gs[0])
        self._plot_teacher_schedule(ax_theory, teacher_id, teacher_df, 'Theory', self.theory_slots)
        ax_theory.set_title(f'Theory Schedule for {teacher_name}', fontsize=16)
        
        # Lab schedule
        ax_lab = fig.add_subplot(gs[1])
        self._plot_teacher_schedule(ax_lab, teacher_id, teacher_df, 'Lab', self.lab_slots)
        ax_lab.set_title(f'Lab Schedule for {teacher_name}', fontsize=16)
        
        plt.tight_layout()
        # Add teacher name to filename but keep ID for uniqueness
        fig.savefig(os.path.join(self.output_dir, f'teacher_{teacher_id}_{teacher_name.replace(" ", "_")}_schedule.png'), dpi=300, bbox_inches='tight')
        plt.close(fig)
    
    def _create_room_schedule(self, room_id, room_number, room_df):
        """Create a schedule visualization for a specific room."""
        # Determine if this is a classroom or a lab
        is_lab = 'Lab' in room_df['slot_type'].values
        
        # Get additional room information if available
        room_info = room_df.iloc[0]
        block = room_info.get('block', '')
        description = room_info.get('description', '')
        
        # Create a descriptive room name
        room_title = room_number
        if block:
            room_title = f"{room_number}, {block}"
        
        room_subtitle = ""
        if description and description != room_number:
            room_subtitle = f" - {description}"
        
        fig, ax = plt.figure(figsize=(16, 10)), plt.gca()
        
        if is_lab:
            self._plot_room_schedule(ax, room_id, room_df, 'Lab', self.lab_slots)
            ax.set_title(f'Lab Schedule for Room: {room_title}{room_subtitle}', fontsize=16)
        else:
            self._plot_room_schedule(ax, room_id, room_df, 'Theory', self.theory_slots)
            ax.set_title(f'Classroom Schedule for Room: {room_title}{room_subtitle}', fontsize=16)
        
        plt.tight_layout()
        # Use room number in filename instead of just ID
        fig.savefig(os.path.join(self.output_dir, f'room_{room_number.replace("/", "_")}_{room_id}_schedule.png'), dpi=300, bbox_inches='tight')
        plt.close(fig)
    
    def _plot_schedule(self, ax, slot_type, slots):
        """Plot the schedule for a given slot type."""
        # Use pre-computed filtered data instead of filtering again
        df = self.theory_data if slot_type == 'Theory' else self.lab_data
        
        # Create a grid for days and slots using more efficient approach
        grid = self._create_schedule_grid(df, slots)
        batch_grid = self._create_batch_grid(df, slots) if slot_type == 'Lab' else None
        
        # Plot the grid
        self._plot_grid_data(ax, grid, batch_grid, slots)
        
        # Set axes properties
        self._configure_plot_axes(ax, slots)
        
        # Add legend
        self._add_plot_legend(ax, df)
    
    def _create_schedule_grid(self, df, slots):
        """Create schedule grid more efficiently."""
        grid = {}  # Use dict instead of np.array for sparse data
        
        for _, row in df.iterrows():
            day_idx = self.days.index(row['day'])
            slot_idx = slots.index(row['slot_time'])
            grid[(day_idx, slot_idx)] = row['course_code']
        
        return grid
    
    def _create_batch_grid(self, df, slots):
        """Create batch grid for lab slots."""
        batch_grid = {}
        
        for _, row in df.iterrows():
            if 'batch' in row and row['batch'] is not None:
                day_idx = self.days.index(row['day'])
                slot_idx = slots.index(row['slot_time'])
                batch_grid[(day_idx, slot_idx)] = f"B{row['batch']}"
        
        return batch_grid
    
    def _plot_grid_data(self, ax, grid, batch_grid, slots):
        """Plot grid data efficiently."""
        for i in range(len(self.days)):
            for j in range(len(slots)):
                course = grid.get((i, j))
                if course:
                    color = self.course_colors.get(course, 'white')
                    ax.add_patch(plt.Rectangle((j, i), 1, 1, fill=True, color=color, alpha=0.7))
                    
                    # Include batch info in the display if available
                    display_text = course
                    if batch_grid and (i, j) in batch_grid:
                        display_text += f"\n{batch_grid[(i, j)]}"
                    
                    ax.text(j + 0.5, i + 0.5, display_text, ha='center', va='center', fontsize=10)
    
    def _configure_plot_axes(self, ax, slots):
        """Configure plot axes properties."""
        ax.set_xlim(0, len(slots))
        ax.set_ylim(0, len(self.days))
        ax.set_xticks(np.arange(len(slots)) + 0.5)
        ax.set_yticks(np.arange(len(self.days)) + 0.5)
        ax.set_xticklabels(slots, rotation=45, ha='right')
        ax.set_yticklabels(self.days)
        ax.grid(True, linestyle='-', linewidth=0.5, color='gray')
    
    def _add_plot_legend(self, ax, df):
        """Add legend to plot."""
        import matplotlib.patches as mpatches
        relevant_courses = df['course_code'].unique()
        handles = [mpatches.Patch(color=self.course_colors[course], label=course) 
                   for course in relevant_courses if course in self.course_colors]
        ax.legend(handles=handles, loc='upper center', bbox_to_anchor=(0.5, -0.15),
                 fancybox=True, shadow=True, ncol=min(5, len(handles)))
    
    def _plot_teacher_schedule(self, ax, teacher_id, teacher_df, slot_type, slots):
        """Plot the schedule for a specific teacher and slot type."""
        # Filter data for the teacher and slot type
        df = teacher_df[teacher_df['slot_type'] == slot_type]
        
        # Create a grid for days and slots
        grid = np.zeros((len(self.days), len(slots)), dtype=object)
        room_grid = np.zeros((len(self.days), len(slots)), dtype=object)
        batch_grid = np.zeros((len(self.days), len(slots)), dtype=object)  # Add batch tracking
        instance_grid = np.zeros((len(self.days), len(slots)), dtype=object)  # Track instance numbers
        shift_grid = np.zeros((len(self.days), len(slots)), dtype=object)  # Track shift information
        
        # Fill the grid with course codes, room numbers, batch info, instance numbers, and shift info
        for _, row in df.iterrows():
            day_idx = self.days.index(row['day'])
            slot_idx = slots.index(row['slot_time'])
            course_code = row['course_code']
            grid[day_idx, slot_idx] = course_code
            room_grid[day_idx, slot_idx] = row['room_number']
            
            # Add batch information for lab slots if available
            if slot_type == 'Lab' and 'batch' in row and row['batch'] is not None:
                batch_grid[day_idx, slot_idx] = f"B{row['batch']}"
            
            # Add instance number if multiple instances exist and course_instance_id is available
            if 'course_instance_id' in row and (teacher_id, course_code, row['course_instance_id']) in self.instance_mapping:
                instance_num = self.instance_mapping[(teacher_id, course_code, row['course_instance_id'])]
                instance_grid[day_idx, slot_idx] = f"I{instance_num}"
            
            # Add shift information if available
            if 'shift' in row and row['shift'] is not None:
                shift_info = str(row['shift'])
                if 'Shift1' in shift_info:
                    shift_grid[day_idx, slot_idx] = 'S1'
                elif 'Shift2' in shift_info:
                    shift_grid[day_idx, slot_idx] = 'S2'
                elif 'Shift3' in shift_info:
                    shift_grid[day_idx, slot_idx] = 'S3'
                else:
                    shift_grid[day_idx, slot_idx] = 'S?'
        
        # Plot the grid with shift background coloring
        for i in range(len(self.days)):
            for j in range(len(slots)):
                course = grid[i, j]
                room = room_grid[i, j]
                batch = batch_grid[i, j]  # Get batch info
                instance = instance_grid[i, j]  # Get instance number
                shift = shift_grid[i, j]  # Get shift info
                
                if course:
                    # Determine background color based on shift
                    bg_color = 'white'  # Default
                    if shift == 'S1':
                        bg_color = '#E8F4FD'  # Light blue for Shift 1
                    elif shift == 'S2':
                        bg_color = '#FFF2CC'  # Light yellow for Shift 2
                    elif shift == 'S3':
                        bg_color = '#E1D5E7'  # Light purple for Shift 3
                    
                    # Add background rectangle with shift color
                    ax.add_patch(plt.Rectangle((j, i), 1, 1, fill=True, color=bg_color, alpha=0.5))
                    
                    # Add course color overlay
                    course_color = self.course_colors.get(course, 'white')
                    ax.add_patch(plt.Rectangle((j, i), 1, 1, fill=True, color=course_color, alpha=0.7))
                    
                    # Create comprehensive display text
                    display_text = f"{course}\n{room}"
                    
                    # Add shift information prominently
                    if shift:
                        display_text += f"\n[{shift}]"
                    
                    if instance:
                        # Add instance number
                        display_text += f"\n{instance}"
                    
                    if batch:
                        display_text += f"\n{batch}"
                    
                    ax.text(j + 0.5, i + 0.5, display_text, ha='center', va='center', fontsize=8, 
                           fontweight='bold' if shift else 'normal')
        
        # Set the axes properties
        ax.set_xlim(0, len(slots))
        ax.set_ylim(0, len(self.days))
        ax.set_xticks(np.arange(len(slots)) + 0.5)
        ax.set_yticks(np.arange(len(self.days)) + 0.5)
        ax.set_xticklabels(slots, rotation=45, ha='right')
        ax.set_yticklabels(self.days)
        ax.grid(True, linestyle='-', linewidth=0.5, color='gray')
        
        # Add comprehensive legend including course colors and shift colors
        import matplotlib.patches as mpatches
        
        # Course legend
        course_handles = [mpatches.Patch(color=color, label=course, alpha=0.7) 
                         for course, color in self.course_colors.items() if course in df['course_code'].values]
        
        # Shift legend
        shift_handles = [
            mpatches.Patch(color='#E8F4FD', label='Shift 1 (8:00-15:00)', alpha=0.7),
            mpatches.Patch(color='#FFF2CC', label='Shift 2 (10:00-17:00)', alpha=0.7),
            mpatches.Patch(color='#E1D5E7', label='Shift 3 (12:00-19:00)', alpha=0.7)
        ]
        
        # Combine legends
        all_handles = course_handles + shift_handles
        
        # Create legend in two columns if there are many items
        ncol = 2 if len(all_handles) > 6 else 1
        ax.legend(handles=all_handles, loc='upper center', bbox_to_anchor=(0.5, -0.15),
                 fancybox=True, shadow=True, ncol=ncol, fontsize=8)
    
    def _plot_room_schedule(self, ax, room_id, room_df, slot_type, slots):
        """Plot the schedule for a specific room and slot type."""
        # Filter data for the room and slot type
        df = room_df[room_df['slot_type'] == slot_type]
        
        # Create a grid for days and slots
        grid = np.zeros((len(self.days), len(slots)), dtype=object)
        teacher_grid = np.zeros((len(self.days), len(slots)), dtype=object)
        teacher_name_grid = np.zeros((len(self.days), len(slots)), dtype=object)
        batch_grid = np.zeros((len(self.days), len(slots)), dtype=object)  # Add batch tracking
        instance_grid = np.zeros((len(self.days), len(slots)), dtype=object)  # Track instance numbers
        shift_grid = np.zeros((len(self.days), len(slots)), dtype=object)  # Track shift information
        
        # Fill the grid with course codes, teacher information, instance numbers, and shift info
        for _, row in df.iterrows():
            day_idx = self.days.index(row['day'])
            slot_idx = slots.index(row['slot_time'])
            course_code = row['course_code']
            teacher_id = row['teacher_id']
            
            grid[day_idx, slot_idx] = course_code
            teacher_grid[day_idx, slot_idx] = teacher_id
            
            # Get teacher name if available
            teacher_name = ""
            if 'first_name' in row and 'last_name' in row:
                if row['first_name'] and row['last_name']:
                    teacher_name = f"{row['first_name']} {row['last_name']}"
                elif row['staff_code']:
                    teacher_name = row['staff_code']
            elif 'staff_code' in row and row['staff_code']:
                teacher_name = row['staff_code']
            
            if not teacher_name:
                teacher_name = f"Teacher {row['teacher_id']}"
                
            teacher_name_grid[day_idx, slot_idx] = teacher_name
            
            # Add batch information for lab slots if available
            if slot_type == 'Lab' and 'batch' in row and row['batch'] is not None:
                batch_grid[day_idx, slot_idx] = f"B{row['batch']}"
            
            # Add instance number if multiple instances exist and course_instance_id is available
            if 'course_instance_id' in row and (teacher_id, course_code, row['course_instance_id']) in self.instance_mapping:
                instance_num = self.instance_mapping[(teacher_id, course_code, row['course_instance_id'])]
                instance_grid[day_idx, slot_idx] = f"I{instance_num}"
            
            # Add shift information if available
            if 'shift' in row and row['shift'] is not None:
                shift_info = str(row['shift'])
                if 'Shift1' in shift_info:
                    shift_grid[day_idx, slot_idx] = 'S1'
                elif 'Shift2' in shift_info:
                    shift_grid[day_idx, slot_idx] = 'S2'
                elif 'Shift3' in shift_info:
                    shift_grid[day_idx, slot_idx] = 'S3'
                else:
                    shift_grid[day_idx, slot_idx] = 'S?'
        
        # Plot the grid with shift background coloring
        for i in range(len(self.days)):
            for j in range(len(slots)):
                course = grid[i, j]
                teacher_name = teacher_name_grid[i, j]
                batch = batch_grid[i, j]  # Get batch info
                instance = instance_grid[i, j]  # Get instance number
                shift = shift_grid[i, j]  # Get shift info
                
                if course:
                    # Determine background color based on shift
                    bg_color = 'white'  # Default
                    if shift == 'S1':
                        bg_color = '#E8F4FD'  # Light blue for Shift 1
                    elif shift == 'S2':
                        bg_color = '#FFF2CC'  # Light yellow for Shift 2
                    elif shift == 'S3':
                        bg_color = '#E1D5E7'  # Light purple for Shift 3
                    
                    # Add background rectangle with shift color
                    ax.add_patch(plt.Rectangle((j, i), 1, 1, fill=True, color=bg_color, alpha=0.5))
                    
                    # Add course color overlay
                    course_color = self.course_colors.get(course, 'white')
                    ax.add_patch(plt.Rectangle((j, i), 1, 1, fill=True, color=course_color, alpha=0.7))
                    
                    # Create comprehensive display text
                    display_text = f"{course}\n{teacher_name}"
                    
                    # Add shift information prominently
                    if shift:
                        display_text += f"\n[{shift}]"
                    
                    if instance:
                        # Add instance number
                        display_text += f"\n{instance}"
                        
                    if batch:
                        display_text += f"\n{batch}"
                    
                    ax.text(j + 0.5, i + 0.5, display_text, ha='center', va='center', fontsize=8,
                           fontweight='bold' if shift else 'normal')
        
        # Set the axes properties
        ax.set_xlim(0, len(slots))
        ax.set_ylim(0, len(self.days))
        ax.set_xticks(np.arange(len(slots)) + 0.5)
        ax.set_yticks(np.arange(len(self.days)) + 0.5)
        ax.set_xticklabels(slots, rotation=45, ha='right')
        ax.set_yticklabels(self.days)
        ax.grid(True, linestyle='-', linewidth=0.5, color='gray')
        
        # Add comprehensive legend including course colors and shift colors
        import matplotlib.patches as mpatches
        
        # Course legend
        course_handles = [mpatches.Patch(color=color, label=course, alpha=0.7) 
                         for course, color in self.course_colors.items() if course in df['course_code'].values]
        
        # Shift legend
        shift_handles = [
            mpatches.Patch(color='#E8F4FD', label='Shift 1 (8:00-15:00)', alpha=0.7),
            mpatches.Patch(color='#FFF2CC', label='Shift 2 (10:00-17:00)', alpha=0.7),
            mpatches.Patch(color='#E1D5E7', label='Shift 3 (12:00-19:00)', alpha=0.7)
        ]
        
        # Combine legends
        all_handles = course_handles + shift_handles
        
        # Create legend in two columns if there are many items
        ncol = 2 if len(all_handles) > 6 else 1
        ax.legend(handles=all_handles, loc='upper center', bbox_to_anchor=(0.5, -0.15),
                 fancybox=True, shadow=True, ncol=ncol, fontsize=8)
    
    def generate_shift_schedules(self):
        """Generate visualizations for all three shifts."""
        if 'shift' not in self.schedule_df.columns:
            print("Warning: Shift information not found in schedule data. Skipping shift visualizations.")
            return
        
        # Generate individual shift schedules
        self._create_shift_overview()
        self._create_individual_shift_schedules()
        self._create_shift_distribution_analysis()
        self._create_shift_pattern_analysis()
    
    def _create_shift_overview(self):
        """Create an overview of all shifts showing coverage."""
        fig = plt.figure(figsize=(24, 18))
        gs = GridSpec(4, 2, height_ratios=[1, 2, 2, 1], width_ratios=[3, 1], figure=fig)
        
        # Title
        fig.suptitle('3-Shift System Overview', fontsize=20, fontweight='bold')
        
        # Shift coverage timeline (top row)
        ax_timeline = fig.add_subplot(gs[0, :])
        self._plot_shift_timeline(ax_timeline)
        
        # Theory schedule with shift highlights (middle left)
        ax_theory = fig.add_subplot(gs[1, 0])
        self._plot_schedule_with_shifts(ax_theory, 'Theory', self.theory_slots)
        ax_theory.set_title('Theory Schedule with Shift Coverage', fontsize=14)
        
        # Lab schedule with shift highlights (bottom left)
        ax_lab = fig.add_subplot(gs[2, 0])
        self._plot_schedule_with_shifts(ax_lab, 'Lab', self.lab_slots)
        ax_lab.set_title('Lab Schedule with Shift Coverage', fontsize=14)
        
        # Shift statistics (right column)
        ax_stats = fig.add_subplot(gs[1:3, 1])
        self._plot_shift_statistics(ax_stats)
        
        # Shift legend (bottom right)
        ax_legend = fig.add_subplot(gs[3, 1])
        self._plot_shift_legend(ax_legend)
        
        plt.tight_layout()
        fig.savefig(os.path.join(self.output_dir, 'shift_overview.png'), dpi=300, bbox_inches='tight')
        plt.close(fig)
    
    def _plot_shift_timeline(self, ax):
        """Plot a timeline showing shift coverage throughout the day."""
        hours = list(range(8, 20))  # 8 AM to 7 PM
        shift_coverage = np.zeros((len(hours), 3))  # 3 shifts
        
        # Define shift coverage
        shift1_hours = list(range(8, 15))  # 8:00-15:00
        shift2_hours = list(range(10, 17))  # 10:00-17:00
        shift3_hours = list(range(12, 19))  # 12:00-19:00
        
        for i, hour in enumerate(hours):
            if hour in shift1_hours:
                shift_coverage[i, 0] = 1
            if hour in shift2_hours:
                shift_coverage[i, 1] = 1
            if hour in shift3_hours:
                shift_coverage[i, 2] = 1
        
        # Plot coverage
        colors = ['#E8F4FD', '#FFF2CC', '#E1D5E7']
        shift_names = ['Shift 1', 'Shift 2', 'Shift 3']
        
        for i, (color, name) in enumerate(zip(colors, shift_names)):
            ax.barh(i, len(hours), left=0, height=0.8, color=color, alpha=0.3, label=f'{name} Base')
            
            # Highlight active hours
            for j, hour in enumerate(hours):
                if shift_coverage[j, i]:
                    ax.barh(i, 1, left=j, height=0.8, color=color, alpha=0.8)
        
        ax.set_xlim(0, len(hours))
        ax.set_ylim(-0.5, 2.5)
        ax.set_xticks(range(len(hours)))
        ax.set_xticklabels([f'{h}:00' for h in hours], rotation=45)
        ax.set_yticks(range(3))
        ax.set_yticklabels(shift_names)
        ax.set_xlabel('Time of Day')
        ax.set_title('Shift Coverage Timeline', fontsize=12)
        ax.grid(True, alpha=0.3)
    
    def _plot_schedule_with_shifts(self, ax, slot_type, slots):
        """Plot schedule with shift background colors."""
        # Use pre-computed filtered data
        df = self.theory_data if slot_type == 'Theory' else self.lab_data
        
        # Create background for shift coverage
        for i in range(len(self.days)):
            for j, slot in enumerate(slots):
                # Determine which shifts cover this slot
                shift_colors = []
                for shift_name, shift_info in self.shifts.items():
                    if slot in shift_info[f"{slot_type.lower()}_slots"]:
                        shift_colors.append(shift_info['color'])
                
                # Use the first shift color as background if any
                if shift_colors:
                    ax.add_patch(plt.Rectangle((j, i), 1, 1, fill=True, 
                                             color=shift_colors[0], alpha=0.3))
        
        # Create a grid for courses
        grid = self._create_schedule_grid(df, slots)
        batch_grid = self._create_batch_grid(df, slots) if slot_type == 'Lab' else None
        
        # Plot course assignments
        for i in range(len(self.days)):
            for j in range(len(slots)):
                course = grid.get((i, j))
                if course:
                    # Use course color with higher opacity
                    color = self.course_colors.get(course, 'white')
                    ax.add_patch(plt.Rectangle((j, i), 1, 1, fill=True, color=color, alpha=0.8))
                    
                    # Add text
                    display_text = course
                    if batch_grid and (i, j) in batch_grid:
                        display_text += f"\n{batch_grid[(i, j)]}"
                    
                    ax.text(j + 0.5, i + 0.5, display_text, ha='center', va='center', fontsize=8)
        
        # Configure axes
        self._configure_plot_axes(ax, slots)
    
    def _plot_shift_statistics(self, ax):
        """Plot shift distribution statistics."""
        if 'shift' not in self.schedule_df.columns:
            ax.text(0.5, 0.5, 'No shift data available', ha='center', va='center', transform=ax.transAxes)
            return
        
        # Count assignments per shift
        shift_counts = self.schedule_df['shift'].value_counts()
        valid_shifts = [shift for shift in shift_counts.index if shift and 'Shift' in str(shift)]
        
        if not valid_shifts:
            ax.text(0.5, 0.5, 'No valid shift assignments found', ha='center', va='center', transform=ax.transAxes)
            return
        
        # Plot bar chart
        colors = ['#4A90E2', '#F5A623', '#9013FE']
        bars = ax.barh(range(len(valid_shifts)), [shift_counts.get(shift, 0) for shift in valid_shifts], 
                       color=colors[:len(valid_shifts)])
        
        ax.set_yticks(range(len(valid_shifts)))
        ax.set_yticklabels([shift.split('(')[0].strip() for shift in valid_shifts])
        ax.set_xlabel('Number of Assignments')
        ax.set_title('Assignments per Shift', fontsize=12)
        
        # Add value labels on bars
        for i, bar in enumerate(bars):
            width = bar.get_width()
            ax.text(width + 0.1, bar.get_y() + bar.get_height()/2, 
                   f'{int(width)}', ha='left', va='center')
        
        ax.grid(True, alpha=0.3)
    
    def _plot_shift_legend(self, ax):
        """Plot legend for shift colors."""
        import matplotlib.patches as mpatches
        
        # Create legend patches
        shift_patches = []
        for shift_name, shift_info in self.shifts.items():
            patch = mpatches.Patch(color=shift_info['color'], alpha=0.7, 
                                 label=f"{shift_info['name']}\n{shift_info['time']}")
            shift_patches.append(patch)
        
        ax.legend(handles=shift_patches, loc='center', fontsize=10)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis('off')
        ax.set_title('Shift Legend', fontsize=12)
    
    def _create_individual_shift_schedules(self):
        """Create individual schedule views for each shift."""
        if 'shift' not in self.schedule_df.columns:
            return
        
        for shift_name, shift_info in self.shifts.items():
            # Filter data for this shift
            shift_data = self.schedule_df[self.schedule_df['shift'] == shift_name]
            
            if shift_data.empty:
                continue
            
            # Create figure
            fig = plt.figure(figsize=(18, 12))
            gs = GridSpec(2, 1, height_ratios=[2, 1], figure=fig)
            
            fig.suptitle(f'{shift_info["name"]} Schedule ({shift_info["time"]})', 
                        fontsize=16, fontweight='bold')
            
            # Theory schedule
            ax_theory = fig.add_subplot(gs[0])
            self._plot_shift_specific_schedule(ax_theory, shift_data, 'Theory', shift_info)
            ax_theory.set_title(f'{shift_info["name"]} Theory Classes', fontsize=14)
            
            # Lab schedule
            ax_lab = fig.add_subplot(gs[1])
            self._plot_shift_specific_schedule(ax_lab, shift_data, 'Lab', shift_info)
            ax_lab.set_title(f'{shift_info["name"]} Lab Classes', fontsize=14)
            
            plt.tight_layout()
            filename = f'shift_{shift_info["name"].lower().replace(" ", "_")}_schedule.png'
            fig.savefig(os.path.join(self.output_dir, filename), dpi=300, bbox_inches='tight')
            plt.close(fig)
    
    def _plot_shift_specific_schedule(self, ax, shift_data, slot_type, shift_info):
        """Plot schedule for a specific shift."""
        # Filter by slot type
        df = shift_data[shift_data['slot_type'] == slot_type]
        
        # Use shift-specific slots
        slots = shift_info[f"{slot_type.lower()}_slots"]
        
        if df.empty or not slots:
            ax.text(0.5, 0.5, f'No {slot_type} classes in this shift', 
                   ha='center', va='center', transform=ax.transAxes)
            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)
            return
        
        # Create grids
        grid = {}
        batch_grid = {}
        teacher_grid = {}
        
        for _, row in df.iterrows():
            if row['slot_time'] not in slots:
                continue
                
            day_idx = self.days.index(row['day'])
            slot_idx = slots.index(row['slot_time'])
            
            grid[(day_idx, slot_idx)] = row['course_code']
            
            if slot_type == 'Lab' and 'batch' in row and row['batch'] is not None:
                batch_grid[(day_idx, slot_idx)] = f"B{row['batch']}"
            
            # Add teacher info
            teacher_name = f"{row.get('first_name', '')} {row.get('last_name', '')}".strip()
            if not teacher_name:
                teacher_name = row.get('staff_code', f"T{row['teacher_id']}")
            teacher_grid[(day_idx, slot_idx)] = teacher_name
        
        # Plot background with shift color
        for i in range(len(self.days)):
            for j in range(len(slots)):
                ax.add_patch(plt.Rectangle((j, i), 1, 1, fill=True, 
                                         color=shift_info['color'], alpha=0.3))
        
        # Plot assignments
        for i in range(len(self.days)):
            for j in range(len(slots)):
                course = grid.get((i, j))
                if course:
                    color = self.course_colors.get(course, 'white')
                    ax.add_patch(plt.Rectangle((j, i), 1, 1, fill=True, color=color, alpha=0.8))
                    
                    # Create display text
                    display_text = course
                    teacher = teacher_grid.get((i, j), '')
                    if teacher:
                        display_text += f"\n{teacher}"
                    
                    batch = batch_grid.get((i, j), '')
                    if batch:
                        display_text += f"\n{batch}"
                    
                    ax.text(j + 0.5, i + 0.5, display_text, ha='center', va='center', fontsize=8)
        
        # Configure axes
        ax.set_xlim(0, len(slots))
        ax.set_ylim(0, len(self.days))
        ax.set_xticks(np.arange(len(slots)) + 0.5)
        ax.set_yticks(np.arange(len(self.days)) + 0.5)
        ax.set_xticklabels(slots, rotation=45, ha='right')
        ax.set_yticklabels(self.days)
        ax.grid(True, linestyle='-', linewidth=0.5, color='gray')
        
        # Add legend
        self._add_plot_legend(ax, df)
    
    def _create_shift_distribution_analysis(self):
        """Create analysis of teacher distribution across shifts."""
        if 'shift' not in self.schedule_df.columns:
            return
        
        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(16, 12))
        fig.suptitle('Shift Distribution Analysis', fontsize=16, fontweight='bold')
        
        # Teacher workload per shift
        self._plot_teacher_shift_workload(ax1)
        
        # Daily shift distribution
        self._plot_daily_shift_distribution(ax2)
        
        # Course distribution across shifts
        self._plot_course_shift_distribution(ax3)
        
        # Room utilization per shift
        self._plot_room_shift_utilization(ax4)
        
        plt.tight_layout()
        fig.savefig(os.path.join(self.output_dir, 'shift_distribution_analysis.png'), 
                   dpi=300, bbox_inches='tight')
        plt.close(fig)
    
    def _plot_teacher_shift_workload(self, ax):
        """Plot teacher workload distribution across shifts."""
        # Count assignments per teacher per shift
        teacher_shift_counts = self.schedule_df.groupby(['teacher_id', 'shift']).size().unstack(fill_value=0)
        
        # Filter valid shifts
        valid_shift_cols = [col for col in teacher_shift_counts.columns if col and 'Shift' in str(col)]
        if not valid_shift_cols:
            ax.text(0.5, 0.5, 'No valid shift data', ha='center', va='center', transform=ax.transAxes)
            return
        
        teacher_shift_counts = teacher_shift_counts[valid_shift_cols]
        
        # Create stacked bar chart
        teacher_shift_counts.plot(kind='bar', stacked=True, ax=ax, 
                                color=['#4A90E2', '#F5A623', '#9013FE'][:len(valid_shift_cols)])
        
        ax.set_title('Teacher Workload per Shift')
        ax.set_xlabel('Teacher ID')
        ax.set_ylabel('Number of Classes')
        ax.legend(title='Shift', bbox_to_anchor=(1.05, 1), loc='upper left')
        ax.tick_params(axis='x', rotation=45)
    
    def _plot_daily_shift_distribution(self, ax):
        """Plot shift distribution by day of week."""
        daily_shifts = self.schedule_df.groupby(['day', 'shift']).size().unstack(fill_value=0)
        
        # Filter valid shifts and reorder days
        valid_shift_cols = [col for col in daily_shifts.columns if col and 'Shift' in str(col)]
        if not valid_shift_cols:
            ax.text(0.5, 0.5, 'No valid shift data', ha='center', va='center', transform=ax.transAxes)
            return
        
        daily_shifts = daily_shifts[valid_shift_cols]
        daily_shifts = daily_shifts.reindex(self.days)
        
        daily_shifts.plot(kind='bar', ax=ax, color=['#4A90E2', '#F5A623', '#9013FE'][:len(valid_shift_cols)])
        
        ax.set_title('Daily Shift Distribution')
        ax.set_xlabel('Day of Week')
        ax.set_ylabel('Number of Classes')
        ax.legend(title='Shift')
        ax.tick_params(axis='x', rotation=45)
    
    def _plot_course_shift_distribution(self, ax):
        """Plot course distribution across shifts."""
        course_shifts = self.schedule_df.groupby(['course_code', 'shift']).size().unstack(fill_value=0)
        
        # Filter valid shifts
        valid_shift_cols = [col for col in course_shifts.columns if col and 'Shift' in str(col)]
        if not valid_shift_cols:
            ax.text(0.5, 0.5, 'No valid shift data', ha='center', va='center', transform=ax.transAxes)
            return
        
        course_shifts = course_shifts[valid_shift_cols]
        
        # Show only top 10 courses by total assignments
        top_courses = course_shifts.sum(axis=1).nlargest(10).index
        course_shifts_top = course_shifts.loc[top_courses]
        
        course_shifts_top.plot(kind='bar', ax=ax, 
                              color=['#4A90E2', '#F5A623', '#9013FE'][:len(valid_shift_cols)])
        
        ax.set_title('Course Distribution Across Shifts (Top 10)')
        ax.set_xlabel('Course Code')
        ax.set_ylabel('Number of Classes')
        ax.legend(title='Shift')
        ax.tick_params(axis='x', rotation=45)
    
    def _plot_room_shift_utilization(self, ax):
        """Plot room utilization across shifts."""
        room_shifts = self.schedule_df.groupby(['room_number', 'shift']).size().unstack(fill_value=0)
        
        # Filter valid shifts
        valid_shift_cols = [col for col in room_shifts.columns if col and 'Shift' in str(col)]
        if not valid_shift_cols:
            ax.text(0.5, 0.5, 'No valid shift data', ha='center', va='center', transform=ax.transAxes)
            return
        
        room_shifts = room_shifts[valid_shift_cols]
        
        # Show only top 15 rooms by utilization
        top_rooms = room_shifts.sum(axis=1).nlargest(15).index
        room_shifts_top = room_shifts.loc[top_rooms]
        
        room_shifts_top.plot(kind='bar', ax=ax, 
                            color=['#4A90E2', '#F5A623', '#9013FE'][:len(valid_shift_cols)])
        
        ax.set_title('Room Utilization Across Shifts (Top 15)')
        ax.set_xlabel('Room Number')
        ax.set_ylabel('Number of Classes')
        ax.legend(title='Shift')
        ax.tick_params(axis='x', rotation=45)
    
    def _create_shift_pattern_analysis(self):
        """Create analysis of weekly shift patterns for teachers."""
        if 'shift' not in self.schedule_df.columns:
            return
        
        # Analyze weekly patterns for each teacher
        teacher_patterns = {}
        
        for teacher in self.teachers:
            teacher_data = self.schedule_df[self.schedule_df['teacher_id'] == teacher]
            
            # Count shifts per day for this teacher
            daily_shifts = {}
            for day in self.days:
                day_data = teacher_data[teacher_data['day'] == day]
                day_shifts = day_data['shift'].value_counts()
                
                # Determine primary shift for this day (most classes)
                if not day_shifts.empty:
                    primary_shift = day_shifts.index[0]
                    if 'Shift' in str(primary_shift):
                        shift_num = int(primary_shift.split('Shift')[1][0])
                        daily_shifts[day] = shift_num
            
            # Calculate weekly pattern
            if daily_shifts:
                pattern = [0, 0, 0]  # Count for Shift1, Shift2, Shift3
                for shift_num in daily_shifts.values():
                    if 1 <= shift_num <= 3:
                        pattern[shift_num - 1] += 1
                
                teacher_patterns[teacher] = tuple(pattern)
        
        # Create visualization
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 8))
        fig.suptitle('Weekly Shift Pattern Analysis', fontsize=16, fontweight='bold')
        
        # Pattern distribution
        pattern_counts = {}
        for pattern in teacher_patterns.values():
            pattern_key = f"{pattern[0]}-{pattern[1]}-{pattern[2]}"
            pattern_counts[pattern_key] = pattern_counts.get(pattern_key, 0) + 1
        
        if pattern_counts:
            patterns = list(pattern_counts.keys())
            counts = list(pattern_counts.values())
            
            bars = ax1.bar(patterns, counts, color=['#4A90E2', '#F5A623', '#9013FE', '#50E3C2', '#F5A623'])
            ax1.set_title('Teacher Weekly Shift Patterns')
            ax1.set_xlabel('Pattern (Shift1-Shift2-Shift3 days)')
            ax1.set_ylabel('Number of Teachers')
            
            # Add value labels on bars
            for bar in bars:
                height = bar.get_height()
                ax1.text(bar.get_x() + bar.get_width()/2., height + 0.1,
                        f'{int(height)}', ha='center', va='bottom')
        
        # Teacher pattern heatmap
        if teacher_patterns:
            pattern_matrix = []
            teacher_labels = []
            
            for teacher, pattern in list(teacher_patterns.items())[:20]:  # Show first 20 teachers
                pattern_matrix.append(pattern)
                teacher_labels.append(f'T{teacher}')
            
            if pattern_matrix:
                im = ax2.imshow(pattern_matrix, cmap='Blues', aspect='auto')
                ax2.set_title('Teacher Shift Pattern Heatmap (First 20 Teachers)')
                ax2.set_xlabel('Shift (1, 2, 3)')
                ax2.set_ylabel('Teacher')
                ax2.set_xticks([0, 1, 2])
                ax2.set_xticklabels(['Shift 1', 'Shift 2', 'Shift 3'])
                ax2.set_yticks(range(len(teacher_labels)))
                ax2.set_yticklabels(teacher_labels)
                
                # Add colorbar
                plt.colorbar(im, ax=ax2, label='Days per week')
        
        plt.tight_layout()
        fig.savefig(os.path.join(self.output_dir, 'shift_pattern_analysis.png'), 
                   dpi=300, bbox_inches='tight')
        plt.close(fig) 