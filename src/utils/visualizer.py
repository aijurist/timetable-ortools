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
        
        # Fill the grid with course codes, room numbers, batch info, and instance numbers
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
        
        # Plot the grid
        for i in range(len(self.days)):
            for j in range(len(slots)):
                course = grid[i, j]
                room = room_grid[i, j]
                batch = batch_grid[i, j]  # Get batch info
                instance = instance_grid[i, j]  # Get instance number
                
                if course:
                    color = self.course_colors.get(course, 'white')
                    ax.add_patch(plt.Rectangle((j, i), 1, 1, fill=True, color=color, alpha=0.7))
                    
                    # Include batch and instance info in the display if available
                    display_text = f"{course}\n{room}"
                    
                    if instance:
                        # Add instance number first if available
                        display_text += f"\n{instance}"
                    
                    if batch:
                        display_text += f"\n{batch}"
                    
                    ax.text(j + 0.5, i + 0.5, display_text, ha='center', va='center', fontsize=8)
        
        # Set the axes properties
        ax.set_xlim(0, len(slots))
        ax.set_ylim(0, len(self.days))
        ax.set_xticks(np.arange(len(slots)) + 0.5)
        ax.set_yticks(np.arange(len(self.days)) + 0.5)
        ax.set_xticklabels(slots, rotation=45, ha='right')
        ax.set_yticklabels(self.days)
        ax.grid(True, linestyle='-', linewidth=0.5, color='gray')
        
        # Add a colorbar legend
        import matplotlib.patches as mpatches
        handles = [mpatches.Patch(color=color, label=course) 
                   for course, color in self.course_colors.items() if course in df['course_code'].values]
        ax.legend(handles=handles, loc='upper center', bbox_to_anchor=(0.5, -0.15),
                 fancybox=True, shadow=True, ncol=3)
    
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
        
        # Fill the grid with course codes, teacher information, and instance numbers
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
        
        # Plot the grid
        for i in range(len(self.days)):
            for j in range(len(slots)):
                course = grid[i, j]
                teacher_name = teacher_name_grid[i, j]
                batch = batch_grid[i, j]  # Get batch info
                instance = instance_grid[i, j]  # Get instance number
                
                if course:
                    color = self.course_colors.get(course, 'white')
                    ax.add_patch(plt.Rectangle((j, i), 1, 1, fill=True, color=color, alpha=0.7))
                    
                    # Include batch and instance info in the display if available
                    display_text = f"{course}\n{teacher_name}"
                    
                    if instance:
                        # Add instance number first if available
                        display_text += f"\n{instance}"
                        
                    if batch:
                        display_text += f"\n{batch}"
                    
                    ax.text(j + 0.5, i + 0.5, display_text, ha='center', va='center', fontsize=8)
        
        # Set the axes properties
        ax.set_xlim(0, len(slots))
        ax.set_ylim(0, len(self.days))
        ax.set_xticks(np.arange(len(slots)) + 0.5)
        ax.set_yticks(np.arange(len(self.days)) + 0.5)
        ax.set_xticklabels(slots, rotation=45, ha='right')
        ax.set_yticklabels(self.days)
        ax.grid(True, linestyle='-', linewidth=0.5, color='gray')
        
        # Add a colorbar legend
        import matplotlib.patches as mpatches
        handles = [mpatches.Patch(color=color, label=course) 
                   for course, color in self.course_colors.items() if course in df['course_code'].values]
        ax.legend(handles=handles, loc='upper center', bbox_to_anchor=(0.5, -0.15),
                 fancybox=True, shadow=True, ncol=3) 