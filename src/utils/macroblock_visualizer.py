import os
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import numpy as np
from matplotlib.gridspec import GridSpec

class MacroblockTimetableVisualizer:
    def __init__(self, schedule_data, output_dir):
        """Initialize the macroblock timetable visualizer."""
        self.schedule_df = pd.DataFrame(schedule_data) if schedule_data else pd.DataFrame()
        self.output_dir = output_dir
        
        # Macroblock days structure
        self.days = ["tuesday", "wed", "thur", "fri", "sat"]
        
        # Time slots (12 slots per day - Theory timing with proper breaks)
        self.time_slots = [
            "8:00 - 8:50", "9:00 - 9:50", "10:00 - 10:50", "11:00 - 11:50",
            "12:00 - 12:50", "1:00 - 1:50", "2:00 - 2:50", "3:00 - 3:50", 
            "4:00 - 4:50", "5:00 - 5:50", "6:00 - 6:50", "7:00 - 7:50"
        ]
        
        # Define macroblock groups (no shift separation since they are merged)
        self.theory_blocks = ['a1', 'b1', 'c1', 'd1', 'e1', 'f1', 'g1', 'a2', 'b2', 'c2', 'd2', 'e2', 'f2', 'g2']
        
        # Tutorial blocks for 3rd lecture hour (ta1, tb1, tc1 etc. are used as 3rd hour for 3-lecture courses)
        self.tutorial_blocks = ['ta1', 'tb1', 'tc1', 'td1', 'te1', 'tf1', 'tg1', 
                               'ta2', 'tb2', 'tc2', 'td2', 'te2', 'tf2', 'tg2',
                               'taa1', 'taa2', 'tbb1', 'tbb2', 'tcc1', 'tcc2', 'v1', 'v2']
        
        if not self.schedule_df.empty:
            # Create color map for courses
            self.courses = self.schedule_df['course_code'].unique()
            colors = plt.cm.tab20(np.linspace(0, 1, len(self.courses)))
            self.course_colors = {course: mcolors.rgb2hex(color) for course, color in zip(self.courses, colors)}
            
            # Create color map for macroblocks
            all_blocks = self.theory_blocks + self.tutorial_blocks
            
            block_colors = plt.cm.Set3(np.linspace(0, 1, len(all_blocks)))
            self.block_colors = {block: mcolors.rgb2hex(color) for block, color in zip(all_blocks, block_colors)}
            
            # Pre-compute filtered data for efficiency
            self.theory_data = self.schedule_df[self.schedule_df['slot_type'].isin(['Lecture', 'Tutorial'])].copy()
            self.lab_data = self.schedule_df[self.schedule_df['slot_type'] == 'Practical'].copy()
            
            # Pre-compute unique lists for efficiency
            self.teachers = self.schedule_df['teacher_id'].unique()
            self.rooms = self.schedule_df['room_id'].unique()
        else:
            self.courses = []
            self.course_colors = {}
            self.block_colors = {}
            self.theory_data = pd.DataFrame()
            self.lab_data = pd.DataFrame()
            self.teachers = []
            self.rooms = []
    
    def generate_all_visualizations(self):
        """Generate all timetable visualizations."""
        if self.schedule_df.empty:
            print("No schedule data available for visualization")
            return
        
        self.generate_master_schedule()
        self.generate_teacher_schedules()
        self.generate_room_schedules()
        self.generate_macroblock_analysis()
    
    def generate_master_schedule(self):
        """Generate a master schedule visualization."""
        # Create a figure focusing on theory/tutorial schedule only
        fig = plt.figure(figsize=(24, 12))
        
        # Theory/Tutorial schedule (main focus)
        ax_theory = fig.add_subplot(111)
        self._plot_macroblock_schedule(ax_theory, 'Theory/Tutorial', self.theory_data)
        ax_theory.set_title('Master Theory/Tutorial Schedule with Macroblocks\n(Theory Time Slots: 8:00-8:50, 9:00-9:50, 10:00-10:50, etc.)', fontsize=16)
        
        # Only show practical schedule if there's actual practical data
        if not self.lab_data.empty:
            # If there are labs, create a subplot layout
            fig.clear()
            gs = GridSpec(2, 1, height_ratios=[3, 2], figure=fig)
            
            # Theory/Tutorial schedule
            ax_theory = fig.add_subplot(gs[0])
            self._plot_macroblock_schedule(ax_theory, 'Theory/Tutorial', self.theory_data)
            ax_theory.set_title('Master Theory/Tutorial Schedule with Macroblocks\n(Theory Time Slots)', fontsize=16)
            
            # Lab schedule
            ax_lab = fig.add_subplot(gs[1])
            self._plot_macroblock_schedule(ax_lab, 'Practical', self.lab_data)
            ax_lab.set_title('Master Practical Schedule\n(Lab Time Slots)', fontsize=16)
        
        plt.tight_layout()
        fig.savefig(os.path.join(self.output_dir, 'macroblock_master_schedule.png'), 
                   dpi=300, bbox_inches='tight')
        plt.close(fig)
    
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
    
    def generate_macroblock_analysis(self):
        """Generate macroblock distribution analysis."""
        if self.schedule_df.empty:
            return
        
        # Create macroblock analysis visualization
        fig = plt.figure(figsize=(20, 12))
        gs = GridSpec(2, 2, figure=fig)
        
        # Macroblock distribution
        ax1 = fig.add_subplot(gs[0, 0])
        self._plot_macroblock_distribution(ax1)
        
        # Daily usage pattern
        ax2 = fig.add_subplot(gs[0, 1])
        self._plot_daily_usage(ax2)
        
        # Course distribution across macroblocks
        ax3 = fig.add_subplot(gs[1, 0])
        self._plot_course_macroblock_distribution(ax3)
        
        plt.suptitle('Macroblock Timetable Analysis', fontsize=16)
        plt.tight_layout()
        fig.savefig(os.path.join(self.output_dir, 'macroblock_analysis.png'), 
                   dpi=300, bbox_inches='tight')
        plt.close(fig)
    
    def _plot_macroblock_schedule(self, ax, schedule_type, df):
        """Plot the macroblock schedule for a given type."""
        if df.empty:
            ax.text(0.5, 0.5, f'No {schedule_type} assignments', 
                   ha='center', va='center', transform=ax.transAxes)
            return
        
        # Create a grid for days and time slots
        grid = np.empty((len(self.days), len(self.time_slots)), dtype=object)
        macroblock_grid = np.empty((len(self.days), len(self.time_slots)), dtype=object)
        
        for _, row in df.iterrows():
            day = row['day']
            slot_index = row['slot_index']
            
            if day in self.days and 0 <= slot_index < len(self.time_slots):
                day_idx = self.days.index(day)
                course_code = row['course_code']
                macroblock = row.get('macroblock', 'Unknown')
                teacher_id = row['teacher_id']
                room_number = row['room_number']
                
                # Create display text
                display_text = f"{course_code}\n{teacher_id}\n{room_number}"
                grid[day_idx, slot_index] = display_text
                macroblock_grid[day_idx, slot_index] = macroblock
        
        # Plot the grid
        for i, day in enumerate(self.days):
            for j, time_slot in enumerate(self.time_slots):
                if grid[i, j] is not None:
                    macroblock = macroblock_grid[i, j]
                    color = self.block_colors.get(macroblock, '#FFFFFF')
                    
                    # Create rectangle
                    rect = plt.Rectangle((j, len(self.days) - i - 1), 1, 1, 
                                       facecolor=color, edgecolor='black', linewidth=0.5)
                    ax.add_patch(rect)
                    
                    # Add text
                    ax.text(j + 0.5, len(self.days) - i - 0.5, grid[i, j],
                           ha='center', va='center', fontsize=8, weight='bold')
                    
                    # Add macroblock label in corner
                    ax.text(j + 0.1, len(self.days) - i - 0.1, macroblock,
                           ha='left', va='top', fontsize=6, 
                           bbox=dict(boxstyle="round,pad=0.1", facecolor='white', alpha=0.7))
        
        # Set axes properties
        ax.set_xlim(0, len(self.time_slots))
        ax.set_ylim(0, len(self.days))
        ax.set_xticks(range(len(self.time_slots)))
        
        # Show timing clearly as theory slots
        timing_label = "Theory" if schedule_type == 'Theory/Tutorial' else "Lab"
        ax.set_xticklabels([f"{timing_label} Slot {i}\n{slot}" for i, slot in enumerate(self.time_slots)], 
                          rotation=45, ha='right')
        ax.set_yticks(range(len(self.days)))
        ax.set_yticklabels([day.capitalize() for day in reversed(self.days)])
        ax.grid(True, alpha=0.3)
    
    def _create_teacher_schedule(self, teacher_id, teacher_df):
        """Create a schedule visualization for a specific teacher."""
        # Create a figure
        fig = plt.figure(figsize=(20, 10))
        
        # Get teacher information
        teacher_info = teacher_df.iloc[0]
        teacher_first_name = teacher_info.get('first_name', '')
        teacher_last_name = teacher_info.get('last_name', '')
        teacher_name = f"{teacher_first_name} {teacher_last_name}".strip()
        if not teacher_name:
            teacher_name = teacher_info.get('staff_code', f'Teacher {teacher_id}')
        
        # Get teacher shift information
        teacher_shift = teacher_info.get('teacher_shift', 'Unknown')
        shift_display = teacher_shift.replace('shift', 'Shift ') if teacher_shift != 'Unknown' else 'Unknown Shift'
        
        # Plot schedule
        ax = fig.add_subplot(111)
        self._plot_teacher_macroblock_schedule(ax, teacher_id, teacher_df)
        ax.set_title(f'Macroblock Schedule for {teacher_name} (ID: {teacher_id}) - {shift_display}\n(Theory Time Slots)', fontsize=16)
        
        plt.tight_layout()
        fig.savefig(os.path.join(self.output_dir, f'teacher_{teacher_id}_{teacher_name.replace(" ", "_")}_macroblock_schedule.png'), 
                   dpi=300, bbox_inches='tight')
        plt.close(fig)
    
    def _create_room_schedule(self, room_id, room_number, room_df):
        """Create a schedule visualization for a specific room."""
        # Get room information
        room_info = room_df.iloc[0]
        room_type = room_info.get('room_type', 'Room')
        block = room_info.get('block', '')
        
        room_title = f"{room_type} {room_number}"
        if block:
            room_title += f" ({block})"
        
        fig = plt.figure(figsize=(20, 10))
        ax = fig.add_subplot(111)
        
        self._plot_room_macroblock_schedule(ax, room_id, room_df)
        ax.set_title(f'Macroblock Schedule for {room_title}\n(Theory Time Slots)', fontsize=16)
        
        plt.tight_layout()
        fig.savefig(os.path.join(self.output_dir, f'room_{room_number.replace("/", "_")}_{room_id}_macroblock_schedule.png'), 
                   dpi=300, bbox_inches='tight')
        plt.close(fig)
    
    def _plot_teacher_macroblock_schedule(self, ax, teacher_id, teacher_df):
        """Plot the macroblock schedule for a specific teacher."""
        # Create a grid for days and time slots
        grid = np.empty((len(self.days), len(self.time_slots)), dtype=object)
        macroblock_grid = np.empty((len(self.days), len(self.time_slots)), dtype=object)
        
        for _, row in teacher_df.iterrows():
            day = row['day']
            slot_index = row['slot_index']
            
            if day in self.days and 0 <= slot_index < len(self.time_slots):
                day_idx = self.days.index(day)
                course_code = row['course_code']
                macroblock = row.get('macroblock', 'Unknown')
                room_number = row['room_number']
                slot_type = row['slot_type']
                
                # Create display text
                display_text = f"{course_code}\n{slot_type}\n{room_number}"
                grid[day_idx, slot_index] = display_text
                macroblock_grid[day_idx, slot_index] = macroblock
        
        # Plot the grid
        for i, day in enumerate(self.days):
            for j, time_slot in enumerate(self.time_slots):
                if grid[i, j] is not None:
                    macroblock = macroblock_grid[i, j]
                    color = self.block_colors.get(macroblock, '#FFFFFF')
                    
                    # Create rectangle
                    rect = plt.Rectangle((j, len(self.days) - i - 1), 1, 1, 
                                       facecolor=color, edgecolor='black', linewidth=0.5)
                    ax.add_patch(rect)
                    
                    # Add text
                    ax.text(j + 0.5, len(self.days) - i - 0.5, grid[i, j],
                           ha='center', va='center', fontsize=8, weight='bold')
                    
                    # Add macroblock label
                    ax.text(j + 0.1, len(self.days) - i - 0.1, macroblock,
                           ha='left', va='top', fontsize=7, 
                           bbox=dict(boxstyle="round,pad=0.1", facecolor='white', alpha=0.8))
        
        # Set axes properties
        ax.set_xlim(0, len(self.time_slots))
        ax.set_ylim(0, len(self.days))
        ax.set_xticks(range(len(self.time_slots)))
        ax.set_xticklabels([f"Theory Slot {i}\n{slot}" for i, slot in enumerate(self.time_slots)], 
                          rotation=45, ha='right')
        ax.set_yticks(range(len(self.days)))
        ax.set_yticklabels([day.capitalize() for day in reversed(self.days)])
        ax.grid(True, alpha=0.3)
    
    def _plot_room_macroblock_schedule(self, ax, room_id, room_df):
        """Plot the macroblock schedule for a specific room."""
        # Similar implementation to teacher schedule but focused on room utilization
        grid = np.empty((len(self.days), len(self.time_slots)), dtype=object)
        macroblock_grid = np.empty((len(self.days), len(self.time_slots)), dtype=object)
        
        for _, row in room_df.iterrows():
            day = row['day']
            slot_index = row['slot_index']
            
            if day in self.days and 0 <= slot_index < len(self.time_slots):
                day_idx = self.days.index(day)
                course_code = row['course_code']
                macroblock = row.get('macroblock', 'Unknown')
                teacher_id = row['teacher_id']
                slot_type = row['slot_type']
                
                # Create display text
                display_text = f"{course_code}\n{slot_type}\nT:{teacher_id}"
                grid[day_idx, slot_index] = display_text
                macroblock_grid[day_idx, slot_index] = macroblock
        
        # Plot the grid (similar to teacher schedule)
        for i, day in enumerate(self.days):
            for j, time_slot in enumerate(self.time_slots):
                if grid[i, j] is not None:
                    macroblock = macroblock_grid[i, j]
                    color = self.block_colors.get(macroblock, '#FFFFFF')
                    
                    # Create rectangle
                    rect = plt.Rectangle((j, len(self.days) - i - 1), 1, 1, 
                                       facecolor=color, edgecolor='black', linewidth=0.5)
                    ax.add_patch(rect)
                    
                    ax.text(j + 0.5, len(self.days) - i - 0.5, grid[i, j],
                           ha='center', va='center', fontsize=8, weight='bold')
                    
                    ax.text(j + 0.1, len(self.days) - i - 0.1, macroblock,
                           ha='left', va='top', fontsize=7, 
                           bbox=dict(boxstyle="round,pad=0.1", facecolor='white', alpha=0.8))
        
        # Set axes properties
        ax.set_xlim(0, len(self.time_slots))
        ax.set_ylim(0, len(self.days))
        ax.set_xticks(range(len(self.time_slots)))
        ax.set_xticklabels([f"Theory Slot {i}\n{slot}" for i, slot in enumerate(self.time_slots)], 
                          rotation=45, ha='right')
        ax.set_yticks(range(len(self.days)))
        ax.set_yticklabels([day.capitalize() for day in reversed(self.days)])
        ax.grid(True, alpha=0.3)
    
    def _plot_macroblock_distribution(self, ax):
        """Plot macroblock distribution."""
        if self.theory_data.empty:
            ax.text(0.5, 0.5, 'No theory data available', ha='center', va='center', transform=ax.transAxes)
            return
        
        macroblock_counts = self.theory_data['macroblock'].value_counts()
        
        bars = ax.bar(range(len(macroblock_counts)), macroblock_counts.values)
        ax.set_xticks(range(len(macroblock_counts)))
        ax.set_xticklabels(macroblock_counts.index, rotation=45)
        ax.set_ylabel('Number of Assignments')
        ax.set_title('Macroblock Distribution')
        
        # Color bars according to macroblock colors
        for i, (macroblock, bar) in enumerate(zip(macroblock_counts.index, bars)):
            bar.set_color(self.block_colors.get(macroblock, '#CCCCCC'))
    
    def _plot_daily_usage(self, ax):
        """Plot daily usage pattern."""
        daily_counts = self.schedule_df['day'].value_counts()
        daily_counts = daily_counts.reindex(self.days, fill_value=0)
        
        bars = ax.bar(range(len(self.days)), daily_counts.values)
        ax.set_xticks(range(len(self.days)))
        ax.set_xticklabels([day.capitalize() for day in self.days], rotation=45)
        ax.set_ylabel('Number of Classes')
        ax.set_title('Daily Class Distribution')
        
        # Color bars with gradient
        colors = plt.cm.viridis(np.linspace(0, 1, len(self.days)))
        for bar, color in zip(bars, colors):
            bar.set_color(color)
    
    def _plot_course_macroblock_distribution(self, ax):
        """Plot course distribution across macroblocks."""
        if self.theory_data.empty:
            ax.text(0.5, 0.5, 'No theory data available', ha='center', va='center', transform=ax.transAxes)
            return
        
        # Create a pivot table
        course_macroblock = self.theory_data.groupby(['course_code', 'macroblock']).size().unstack(fill_value=0)
        
        if course_macroblock.empty:
            ax.text(0.5, 0.5, 'No course-macroblock data', ha='center', va='center', transform=ax.transAxes)
            return
        
        # Create stacked bar chart
        course_macroblock.plot(kind='bar', stacked=True, ax=ax, 
                              color=[self.block_colors.get(block, '#CCCCCC') for block in course_macroblock.columns])
        ax.set_xlabel('Course Code')
        ax.set_ylabel('Number of Assignments')
        ax.set_title('Course Distribution Across Macroblocks')
        ax.legend(title='Macroblock', bbox_to_anchor=(1.05, 1), loc='upper left')
        plt.setp(ax.get_xticklabels(), rotation=45, ha='right') 