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
        
        # Lab time slots (12 slots per day - Lab timing)
        self.lab_time_slots = [
            "8:00 - 8:50", "8:50 - 9:40", "9:50 - 10:40", "10:40 - 11:30",
            "11:50 - 12:40", "12:40 - 1:30", "1:50 - 2:40", "2:40 - 3:30", 
            "3:50 - 4:40", "4:40 - 5:30", "5:30 - 6:20", "6:20 - 7:10"
        ]
        
        # Define macroblock groups (no shift separation since they are merged)
        self.theory_blocks = ['a1', 'b1', 'c1', 'd1', 'e1', 'f1', 'g1', 'a2', 'b2', 'c2', 'd2', 'e2', 'f2', 'g2']
        
        # Tutorial blocks for 3rd lecture hour (ta1, tb1, tc1 etc. are used as 3rd hour for 3-lecture courses)
        self.tutorial_blocks = ['ta1', 'tb1', 'tc1', 'td1', 'te1', 'tf1', 'tg1', 
                               'ta2', 'tb2', 'tc2', 'td2', 'te2', 'tf2', 'tg2',
                               'taa1', 'taa2', 'tbb1', 'tbb2', 'tcc1', 'tcc2', 'v1', 'v2']
        
        # Lab groups
        self.lab_groups = ['l1', 'l2', 'l3', 'l4', 'l5', 'l6']
        
        if not self.schedule_df.empty:
            # Create color map for courses
            self.courses = self.schedule_df['course_code'].unique()
            colors = plt.cm.tab20(np.linspace(0, 1, len(self.courses)))
            self.course_colors = {course: mcolors.rgb2hex(color) for course, color in zip(self.courses, colors)}
            
            # Create color map for theory macroblocks
            all_theory_blocks = self.theory_blocks + self.tutorial_blocks
            block_colors = plt.cm.Set3(np.linspace(0, 1, len(all_theory_blocks)))
            self.theory_block_colors = {block: mcolors.rgb2hex(color) for block, color in zip(all_theory_blocks, block_colors)}
            
            # Create color map for lab groups
            lab_colors = plt.cm.Pastel1(np.linspace(0, 1, len(self.lab_groups)))
            self.lab_group_colors = {group: mcolors.rgb2hex(color) for group, color in zip(self.lab_groups, lab_colors)}
            
            # Pre-compute filtered data for efficiency
            self.theory_data = self.schedule_df[self.schedule_df['slot_type'].isin(['Lecture', 'Tutorial'])].copy()
            self.lab_data = self.schedule_df[self.schedule_df['slot_type'] == 'Practical'].copy()
            
            # Pre-compute unique lists for efficiency
            self.teachers = self.schedule_df['teacher_id'].unique()
            self.rooms = self.schedule_df['room_id'].unique()
        else:
            self.courses = []
            self.course_colors = {}
            self.theory_block_colors = {}
            self.lab_group_colors = {}
            self.theory_data = pd.DataFrame()
            self.lab_data = pd.DataFrame()
            self.teachers = []
            self.rooms = []
    
    def generate_all_visualizations(self):
        """Generate all timetable visualizations."""
        if self.schedule_df.empty:
            print("No schedule data available for visualization")
            return
        
        # Generate separate master schedules
        self.generate_master_theory_schedule()
        self.generate_master_lab_schedule()
        self.generate_combined_master_schedule()
        
        # Generate individual schedules
        self.generate_teacher_schedules()
        self.generate_room_schedules()
        self.generate_macroblock_analysis()
    
    def generate_master_theory_schedule(self):
        """Generate a master theory/tutorial schedule visualization."""
        if self.theory_data.empty:
            print("No theory data available for visualization")
            return
            
        fig, ax = plt.subplots(figsize=(24, 12), constrained_layout=True)
        self._plot_theory_schedule(ax, self.theory_data)
        ax.set_title('Master Theory/Tutorial Schedule with Macroblocks\n(Theory Time Slots: 50-minute classes with 10-minute breaks)', fontsize=16)
        
        # Add legend for theory blocks
        self._add_theory_legend(ax)
        
        fig.savefig(os.path.join(self.output_dir, 'master_theory_schedule.png'), 
                   dpi=300, bbox_inches='tight')
        plt.close(fig)
        print(f"Theory schedule saved to: master_theory_schedule.png")
    
    def generate_master_lab_schedule(self):
        """Generate a master lab schedule visualization."""
        if self.lab_data.empty:
            print("No lab data available for visualization")
            return
            
        fig, ax = plt.subplots(figsize=(24, 12), constrained_layout=True)
        self._plot_lab_schedule(ax, self.lab_data)
        ax.set_title('Master Lab/Practical Schedule\n(Lab Time Slots: l1=8:00-9:40, l2=9:50-11:30, l3=11:50-1:30, l4=1:50-3:30, l5=3:50-5:30, l6=5:30-7:10)', fontsize=16)
        
        # Add legend for lab groups
        self._add_lab_legend(ax)
        
        fig.savefig(os.path.join(self.output_dir, 'master_lab_schedule.png'), 
                   dpi=300, bbox_inches='tight')
        plt.close(fig)
        print(f"Lab schedule saved to: master_lab_schedule.png")
    
    def generate_combined_master_schedule(self):
        """Generate a combined master schedule showing both theory and lab."""
        fig = plt.figure(figsize=(24, 18), constrained_layout=True)
        
        # Create subplots
        gs = GridSpec(3, 1, height_ratios=[2, 2, 1], figure=fig, hspace=0.2)
        
        # Theory schedule
        ax_theory = fig.add_subplot(gs[0])
        if not self.theory_data.empty:
            self._plot_theory_schedule(ax_theory, self.theory_data)
            ax_theory.set_title('Theory/Tutorial Schedule (50-minute slots)', fontsize=14, fontweight='bold')
        else:
            ax_theory.text(0.5, 0.5, 'No Theory Classes Scheduled', 
                          ha='center', va='center', transform=ax_theory.transAxes, fontsize=16)
        
        # Lab schedule
        ax_lab = fig.add_subplot(gs[1])
        if not self.lab_data.empty:
            self._plot_lab_schedule(ax_lab, self.lab_data)
            ax_lab.set_title('Lab/Practical Schedule (100-minute lab groups)', fontsize=14, fontweight='bold')
        else:
            ax_lab.text(0.5, 0.5, 'No Lab Classes Scheduled', 
                       ha='center', va='center', transform=ax_lab.transAxes, fontsize=16)
        
        # Statistics summary
        ax_stats = fig.add_subplot(gs[2])
        self._plot_schedule_statistics(ax_stats)
        
        plt.suptitle('Complete Master Timetable - Theory and Lab Schedules', fontsize=18, fontweight='bold')
        fig.savefig(os.path.join(self.output_dir, 'complete_master_schedule.png'), 
                   dpi=300, bbox_inches='tight')
        plt.close(fig)
        print(f"Combined schedule saved to: complete_master_schedule.png")
    
    def _plot_theory_schedule(self, ax, theory_df):
        """Plot the theory/tutorial schedule."""
        # Create a grid for days and time slots
        grid = np.empty((len(self.days), len(self.time_slots)), dtype=object)
        macroblock_grid = np.empty((len(self.days), len(self.time_slots)), dtype=object)
        
        for _, row in theory_df.iterrows():
            day = row['day']
            slot_index = row['slot_index']
            
            if day in self.days and 0 <= slot_index < len(self.time_slots):
                day_idx = self.days.index(day)
                course_code = row['course_code']
                macroblock = row.get('macroblock', 'Unknown')
                teacher_id = row['teacher_id']
                room_number = row['room_number']
                slot_type = row['slot_type']
                
                # Create display text
                display_text = f"{course_code}\n{slot_type}\nT:{teacher_id}\nR:{room_number}"
                grid[day_idx, slot_index] = display_text
                macroblock_grid[day_idx, slot_index] = macroblock
        
        # Plot the grid
        for i, day in enumerate(self.days):
            for j, time_slot in enumerate(self.time_slots):
                if grid[i, j] is not None:
                    macroblock = macroblock_grid[i, j]
                    color = self.theory_block_colors.get(macroblock, '#FFFFFF')
                    
                    # Create rectangle
                    rect = plt.Rectangle((j, len(self.days) - i - 1), 1, 1, 
                                       facecolor=color, edgecolor='black', linewidth=0.8)
                    ax.add_patch(rect)
                    
                    # Add text
                    ax.text(j + 0.5, len(self.days) - i - 0.5, grid[i, j],
                           ha='center', va='center', fontsize=7, weight='bold')
                    
                    # Add macroblock label in corner
                    ax.text(j + 0.05, len(self.days) - i - 0.05, macroblock,
                           ha='left', va='top', fontsize=8, weight='bold',
                           bbox=dict(boxstyle="round,pad=0.1", facecolor='yellow', alpha=0.8))
        
        # Set axes properties
        ax.set_xlim(0, len(self.time_slots))
        ax.set_ylim(0, len(self.days))
        ax.set_xticks(range(len(self.time_slots)))
        ax.set_xticklabels([f"T{i+1}\n{slot}" for i, slot in enumerate(self.time_slots)], 
                          rotation=45, ha='right', fontsize=10)
        ax.set_yticks(range(len(self.days)))
        ax.set_yticklabels([day.capitalize() for day in reversed(self.days)], fontsize=12)
        ax.grid(True, alpha=0.3)
        ax.set_xlabel('Theory Time Slots (50-minute classes)', fontsize=12, fontweight='bold')
        ax.set_ylabel('Days', fontsize=12, fontweight='bold')
    
    def _plot_lab_schedule(self, ax, lab_df):
        """Plot the lab/practical schedule."""
        # Create a grid for days and lab time slots
        grid = np.empty((len(self.days), len(self.lab_time_slots)), dtype=object)
        lab_group_grid = np.empty((len(self.days), len(self.lab_time_slots)), dtype=object)
        
        for _, row in lab_df.iterrows():
            day = row['day']
            slot_index = row['slot_index']
            
            if day in self.days and 0 <= slot_index < len(self.lab_time_slots):
                day_idx = self.days.index(day)
                course_code = row['course_code']
                lab_group = row.get('macroblock', 'Unknown')  # Lab group (l1, l2, etc.)
                teacher_id = row['teacher_id']
                room_number = row['room_number']
                
                # Create display text
                display_text = f"{course_code}\nPractical\nT:{teacher_id}\nR:{room_number}"
                grid[day_idx, slot_index] = display_text
                lab_group_grid[day_idx, slot_index] = lab_group
        
        # Plot the grid
        for i, day in enumerate(self.days):
            for j, lab_time_slot in enumerate(self.lab_time_slots):
                if grid[i, j] is not None:
                    lab_group = lab_group_grid[i, j]
                    color = self.lab_group_colors.get(lab_group, '#FFEEEE')
                    
                    # Create rectangle
                    rect = plt.Rectangle((j, len(self.days) - i - 1), 1, 1, 
                                       facecolor=color, edgecolor='darkred', linewidth=1.0)
                    ax.add_patch(rect)
                    
                    # Add text
                    ax.text(j + 0.5, len(self.days) - i - 0.5, grid[i, j],
                           ha='center', va='center', fontsize=7, weight='bold')
                    
                    # Add lab group label in corner
                    ax.text(j + 0.05, len(self.days) - i - 0.05, lab_group,
                           ha='left', va='top', fontsize=9, weight='bold',
                           bbox=dict(boxstyle="round,pad=0.1", facecolor='orange', alpha=0.9))
        
        # Set axes properties
        ax.set_xlim(0, len(self.lab_time_slots))
        ax.set_ylim(0, len(self.days))
        ax.set_xticks(range(len(self.lab_time_slots)))
        ax.set_xticklabels([f"L{i+1}\n{slot}" for i, slot in enumerate(self.lab_time_slots)], 
                          rotation=45, ha='right', fontsize=10)
        ax.set_yticks(range(len(self.days)))
        ax.set_yticklabels([day.capitalize() for day in reversed(self.days)], fontsize=12)
        ax.grid(True, alpha=0.3)
        ax.set_xlabel('Lab Time Slots (50-minute periods, grouped into 100-minute lab sessions)', fontsize=12, fontweight='bold')
        ax.set_ylabel('Days', fontsize=12, fontweight='bold')
    
    def _add_theory_legend(self, ax):
        """Add legend for theory macroblocks."""
        # Create legend elements for theory blocks
        legend_elements = []
        for block in self.theory_blocks + self.tutorial_blocks:
            if block in self.theory_block_colors:
                legend_elements.append(plt.Rectangle((0, 0), 1, 1, 
                                     facecolor=self.theory_block_colors[block], 
                                     edgecolor='black', label=block))
        
        if legend_elements:
            ax.legend(handles=legend_elements, bbox_to_anchor=(1.02, 1), loc='upper left', 
                     title='Theory Macroblocks', ncol=2, fontsize=8)
    
    def _add_lab_legend(self, ax):
        """Add legend for lab groups."""
        # Create legend elements for lab groups
        legend_elements = []
        lab_group_descriptions = {
            'l1': 'l1 (8:00-9:40)',
            'l2': 'l2 (9:50-11:30)', 
            'l3': 'l3 (11:50-1:30)',
            'l4': 'l4 (1:50-3:30)',
            'l5': 'l5 (3:50-5:30)',
            'l6': 'l6 (5:30-7:10)'
        }
        
        for group in self.lab_groups:
            if group in self.lab_group_colors:
                legend_elements.append(plt.Rectangle((0, 0), 1, 1, 
                                     facecolor=self.lab_group_colors[group], 
                                     edgecolor='darkred', 
                                     label=lab_group_descriptions.get(group, group)))
        
        if legend_elements:
            ax.legend(handles=legend_elements, bbox_to_anchor=(1.02, 1), loc='upper left', 
                     title='Lab Groups (100-min sessions)', ncol=1, fontsize=8)
    
    def _plot_schedule_statistics(self, ax):
        """Plot schedule statistics summary."""
        ax.axis('off')
        
        # Calculate statistics
        total_classes = len(self.schedule_df)
        theory_classes = len(self.theory_data)
        lab_classes = len(self.lab_data)
        total_teachers = len(self.teachers)
        total_rooms = len(self.rooms)
        
        # Create statistics text
        stats_text = f"""
        Schedule Statistics:
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        Total Classes Scheduled: {total_classes}
        Theory/Tutorial Classes: {theory_classes}
        Lab/Practical Classes: {lab_classes}
        
        Teachers Involved: {total_teachers}
        Rooms Utilized: {total_rooms}
        
        Theory Time Slots: 12 per day (50-minute classes)
        Lab Time Slots: 12 per day (grouped into 6 lab sessions)
        Days: Tuesday to Saturday (5 days)
        """
        
        ax.text(0.1, 0.5, stats_text, transform=ax.transAxes, fontsize=12, 
               verticalalignment='center', fontfamily='monospace',
               bbox=dict(boxstyle="round,pad=0.5", facecolor='lightblue', alpha=0.8))
    
    def generate_teacher_schedules(self):
        """Generate separate theory and lab schedule visualizations for each teacher."""
        for teacher in self.teachers:
            teacher_df = self.schedule_df[self.schedule_df['teacher_id'] == teacher]
            if not teacher_df.empty:
                self._create_teacher_combined_schedule(teacher, teacher_df)
    
    def generate_room_schedules(self):
        """Generate schedule visualizations for each room."""
        for room in self.rooms:
            room_df = self.schedule_df[self.schedule_df['room_id'] == room]
            if not room_df.empty:
                room_number = room_df.iloc[0]['room_number']
                room_type = room_df.iloc[0]['room_type']
                self._create_room_schedule(room, room_number, room_type, room_df)
    
    def _create_teacher_combined_schedule(self, teacher_id, teacher_df):
        """Create a combined schedule visualization for a specific teacher."""
        # Get teacher information
        teacher_info = teacher_df.iloc[0]
        teacher_first_name = teacher_info.get('first_name', '')
        teacher_last_name = teacher_info.get('last_name', '')
        teacher_name = f"{teacher_first_name} {teacher_last_name}".strip()
        if not teacher_name:
            teacher_name = teacher_info.get('staff_code', f'Teacher {teacher_id}')
        
        # Split data into theory and lab
        teacher_theory_df = teacher_df[teacher_df['slot_type'].isin(['Lecture', 'Tutorial'])]
        teacher_lab_df = teacher_df[teacher_df['slot_type'] == 'Practical']
        
        # Create figure
        fig = plt.figure(figsize=(24, 16), constrained_layout=True)
        
        if not teacher_theory_df.empty and not teacher_lab_df.empty:
            # Both theory and lab
            gs = GridSpec(2, 1, height_ratios=[1, 1], figure=fig, hspace=0.2)
            
            # Theory schedule
            ax_theory = fig.add_subplot(gs[0])
            self._plot_teacher_theory_schedule(ax_theory, teacher_theory_df)
            ax_theory.set_title(f'{teacher_name} (ID: {teacher_id}) - Theory/Tutorial Schedule', fontsize=14, fontweight='bold')
            
            # Lab schedule
            ax_lab = fig.add_subplot(gs[1])
            self._plot_teacher_lab_schedule(ax_lab, teacher_lab_df)
            ax_lab.set_title(f'{teacher_name} (ID: {teacher_id}) - Lab/Practical Schedule', fontsize=14, fontweight='bold')
            
        elif not teacher_theory_df.empty:
            # Only theory
            ax = fig.add_subplot(111)
            self._plot_teacher_theory_schedule(ax, teacher_theory_df)
            ax.set_title(f'{teacher_name} (ID: {teacher_id}) - Theory/Tutorial Schedule', fontsize=16, fontweight='bold')
            
        elif not teacher_lab_df.empty:
            # Only lab
            ax = fig.add_subplot(111)
            self._plot_teacher_lab_schedule(ax, teacher_lab_df)
            ax.set_title(f'{teacher_name} (ID: {teacher_id}) - Lab/Practical Schedule', fontsize=16, fontweight='bold')
        
        plt.suptitle(f'Complete Schedule for {teacher_name}', fontsize=18, fontweight='bold')
        fig.savefig(os.path.join(self.output_dir, f'teacher_{teacher_id}_{teacher_name.replace(" ", "_")}_complete_schedule.png'), 
                   dpi=300, bbox_inches='tight')
        plt.close(fig)
    
    def _plot_teacher_theory_schedule(self, ax, teacher_theory_df):
        """Plot theory schedule for a specific teacher."""
        # Similar to _plot_theory_schedule but for individual teacher
        grid = np.empty((len(self.days), len(self.time_slots)), dtype=object)
        macroblock_grid = np.empty((len(self.days), len(self.time_slots)), dtype=object)
        
        for _, row in teacher_theory_df.iterrows():
            day = row['day']
            slot_index = row['slot_index']
            
            if day in self.days and 0 <= slot_index < len(self.time_slots):
                day_idx = self.days.index(day)
                course_code = row['course_code']
                macroblock = row.get('macroblock', 'Unknown')
                room_number = row['room_number']
                slot_type = row['slot_type']
                
                display_text = f"{course_code}\n{slot_type}\n{room_number}"
                grid[day_idx, slot_index] = display_text
                macroblock_grid[day_idx, slot_index] = macroblock
        
        # Plot the grid
        for i, day in enumerate(self.days):
            for j, time_slot in enumerate(self.time_slots):
                if grid[i, j] is not None:
                    macroblock = macroblock_grid[i, j]
                    color = self.theory_block_colors.get(macroblock, '#FFFFFF')
                    
                    rect = plt.Rectangle((j, len(self.days) - i - 1), 1, 1, 
                                       facecolor=color, edgecolor='black', linewidth=0.8)
                    ax.add_patch(rect)
                    
                    ax.text(j + 0.5, len(self.days) - i - 0.5, grid[i, j],
                           ha='center', va='center', fontsize=8, weight='bold')
                    
                    ax.text(j + 0.05, len(self.days) - i - 0.05, macroblock,
                           ha='left', va='top', fontsize=8, weight='bold',
                           bbox=dict(boxstyle="round,pad=0.1", facecolor='yellow', alpha=0.8))
        
        # Set axes properties
        ax.set_xlim(0, len(self.time_slots))
        ax.set_ylim(0, len(self.days))
        ax.set_xticks(range(len(self.time_slots)))
        ax.set_xticklabels([f"T{i+1}\n{slot}" for i, slot in enumerate(self.time_slots)], 
                          rotation=45, ha='right')
        ax.set_yticks(range(len(self.days)))
        ax.set_yticklabels([day.capitalize() for day in reversed(self.days)])
        ax.grid(True, alpha=0.3)
        ax.set_xlabel('Theory Time Slots', fontweight='bold')
        ax.set_ylabel('Days', fontweight='bold')
    
    def _plot_teacher_lab_schedule(self, ax, teacher_lab_df):
        """Plot lab schedule for a specific teacher."""
        grid = np.empty((len(self.days), len(self.lab_time_slots)), dtype=object)
        lab_group_grid = np.empty((len(self.days), len(self.lab_time_slots)), dtype=object)
        
        for _, row in teacher_lab_df.iterrows():
            day = row['day']
            slot_index = row['slot_index']
            
            if day in self.days and 0 <= slot_index < len(self.lab_time_slots):
                day_idx = self.days.index(day)
                course_code = row['course_code']
                lab_group = row.get('macroblock', 'Unknown')
                room_number = row['room_number']
                
                display_text = f"{course_code}\nPractical\n{room_number}"
                grid[day_idx, slot_index] = display_text
                lab_group_grid[day_idx, slot_index] = lab_group
        
        # Plot the grid
        for i, day in enumerate(self.days):
            for j, lab_time_slot in enumerate(self.lab_time_slots):
                if grid[i, j] is not None:
                    lab_group = lab_group_grid[i, j]
                    color = self.lab_group_colors.get(lab_group, '#FFEEEE')
                    
                    rect = plt.Rectangle((j, len(self.days) - i - 1), 1, 1, 
                                       facecolor=color, edgecolor='darkred', linewidth=1.0)
                    ax.add_patch(rect)
                    
                    ax.text(j + 0.5, len(self.days) - i - 0.5, grid[i, j],
                           ha='center', va='center', fontsize=8, weight='bold')
                    
                    ax.text(j + 0.05, len(self.days) - i - 0.05, lab_group,
                           ha='left', va='top', fontsize=9, weight='bold',
                           bbox=dict(boxstyle="round,pad=0.1", facecolor='orange', alpha=0.9))
        
        # Set axes properties
        ax.set_xlim(0, len(self.lab_time_slots))
        ax.set_ylim(0, len(self.days))
        ax.set_xticks(range(len(self.lab_time_slots)))
        ax.set_xticklabels([f"L{i+1}\n{slot}" for i, slot in enumerate(self.lab_time_slots)], 
                          rotation=45, ha='right')
        ax.set_yticks(range(len(self.days)))
        ax.set_yticklabels([day.capitalize() for day in reversed(self.days)])
        ax.grid(True, alpha=0.3)
        ax.set_xlabel('Lab Time Slots', fontweight='bold')
        ax.set_ylabel('Days', fontweight='bold')
    
    def _create_room_schedule(self, room_id, room_number, room_type, room_df):
        """Create a schedule visualization for a specific room."""
        room_info = room_df.iloc[0]
        block = room_info.get('block', '')
        
        room_title = f"{room_type} {room_number}"
        if block:
            room_title += f" ({block})"
        
        # Split data by type
        room_theory_df = room_df[room_df['slot_type'].isin(['Lecture', 'Tutorial'])]
        room_lab_df = room_df[room_df['slot_type'] == 'Practical']
        
        # Create appropriate visualization based on room type and data
        fig = plt.figure(figsize=(20, 12), constrained_layout=True)
        
        if not room_theory_df.empty and not room_lab_df.empty:
            # Both theory and lab in same room (unusual but possible)
            gs = GridSpec(2, 1, height_ratios=[1, 1], figure=fig, hspace=0.2)
            
            ax_theory = fig.add_subplot(gs[0])
            self._plot_room_theory_schedule(ax_theory, room_theory_df)
            ax_theory.set_title(f'{room_title} - Theory/Tutorial Usage', fontweight='bold')
            
            ax_lab = fig.add_subplot(gs[1])
            self._plot_room_lab_schedule(ax_lab, room_lab_df)
            ax_lab.set_title(f'{room_title} - Lab/Practical Usage', fontweight='bold')
            
        elif not room_theory_df.empty:
            # Theory room
            ax = fig.add_subplot(111)
            self._plot_room_theory_schedule(ax, room_theory_df)
            ax.set_title(f'{room_title} - Theory/Tutorial Usage', fontsize=16, fontweight='bold')
            
        elif not room_lab_df.empty:
            # Lab room
            ax = fig.add_subplot(111)
            self._plot_room_lab_schedule(ax, room_lab_df)
            ax.set_title(f'{room_title} - Lab/Practical Usage', fontsize=16, fontweight='bold')
        
        fig.savefig(os.path.join(self.output_dir, f'room_{room_number.replace("/", "_")}_{room_id}_schedule.png'), 
                   dpi=300, bbox_inches='tight')
        plt.close(fig)
    
    def _plot_room_theory_schedule(self, ax, room_theory_df):
        """Plot theory schedule for a specific room."""
        # Similar implementation to teacher theory schedule
        grid = np.empty((len(self.days), len(self.time_slots)), dtype=object)
        macroblock_grid = np.empty((len(self.days), len(self.time_slots)), dtype=object)
        
        for _, row in room_theory_df.iterrows():
            day = row['day']
            slot_index = row['slot_index']
            
            if day in self.days and 0 <= slot_index < len(self.time_slots):
                day_idx = self.days.index(day)
                course_code = row['course_code']
                macroblock = row.get('macroblock', 'Unknown')
                teacher_id = row['teacher_id']
                slot_type = row['slot_type']
                
                display_text = f"{course_code}\n{slot_type}\nT:{teacher_id}"
                grid[day_idx, slot_index] = display_text
                macroblock_grid[day_idx, slot_index] = macroblock
        
        # Plot similar to other theory schedules
        for i, day in enumerate(self.days):
            for j, time_slot in enumerate(self.time_slots):
                if grid[i, j] is not None:
                    macroblock = macroblock_grid[i, j]
                    color = self.theory_block_colors.get(macroblock, '#FFFFFF')
                    
                    rect = plt.Rectangle((j, len(self.days) - i - 1), 1, 1, 
                                       facecolor=color, edgecolor='black', linewidth=0.8)
                    ax.add_patch(rect)
                    
                    ax.text(j + 0.5, len(self.days) - i - 0.5, grid[i, j],
                           ha='center', va='center', fontsize=8, weight='bold')
                    
                    ax.text(j + 0.05, len(self.days) - i - 0.05, macroblock,
                           ha='left', va='top', fontsize=8, weight='bold',
                           bbox=dict(boxstyle="round,pad=0.1", facecolor='yellow', alpha=0.8))
        
        ax.set_xlim(0, len(self.time_slots))
        ax.set_ylim(0, len(self.days))
        ax.set_xticks(range(len(self.time_slots)))
        ax.set_xticklabels([f"T{i+1}\n{slot}" for i, slot in enumerate(self.time_slots)], 
                          rotation=45, ha='right')
        ax.set_yticks(range(len(self.days)))
        ax.set_yticklabels([day.capitalize() for day in reversed(self.days)])
        ax.grid(True, alpha=0.3)
        ax.set_xlabel('Theory Time Slots', fontweight='bold')
        ax.set_ylabel('Days', fontweight='bold')
    
    def _plot_room_lab_schedule(self, ax, room_lab_df):
        """Plot lab schedule for a specific room."""
        grid = np.empty((len(self.days), len(self.lab_time_slots)), dtype=object)
        lab_group_grid = np.empty((len(self.days), len(self.lab_time_slots)), dtype=object)
        
        for _, row in room_lab_df.iterrows():
            day = row['day']
            slot_index = row['slot_index']
            
            if day in self.days and 0 <= slot_index < len(self.lab_time_slots):
                day_idx = self.days.index(day)
                course_code = row['course_code']
                lab_group = row.get('macroblock', 'Unknown')
                teacher_id = row['teacher_id']
                
                display_text = f"{course_code}\nPractical\nT:{teacher_id}"
                grid[day_idx, slot_index] = display_text
                lab_group_grid[day_idx, slot_index] = lab_group
        
        # Plot similar to other lab schedules
        for i, day in enumerate(self.days):
            for j, lab_time_slot in enumerate(self.lab_time_slots):
                if grid[i, j] is not None:
                    lab_group = lab_group_grid[i, j]
                    color = self.lab_group_colors.get(lab_group, '#FFEEEE')
                    
                    rect = plt.Rectangle((j, len(self.days) - i - 1), 1, 1, 
                                       facecolor=color, edgecolor='darkred', linewidth=1.0)
                    ax.add_patch(rect)
                    
                    ax.text(j + 0.5, len(self.days) - i - 0.5, grid[i, j],
                           ha='center', va='center', fontsize=8, weight='bold')
                    
                    ax.text(j + 0.05, len(self.days) - i - 0.05, lab_group,
                           ha='left', va='top', fontsize=9, weight='bold',
                           bbox=dict(boxstyle="round,pad=0.1", facecolor='orange', alpha=0.9))
        
        ax.set_xlim(0, len(self.lab_time_slots))
        ax.set_ylim(0, len(self.days))
        ax.set_xticks(range(len(self.lab_time_slots)))
        ax.set_xticklabels([f"L{i+1}\n{slot}" for i, slot in enumerate(self.lab_time_slots)], 
                          rotation=45, ha='right')
        ax.set_yticks(range(len(self.days)))
        ax.set_yticklabels([day.capitalize() for day in reversed(self.days)])
        ax.grid(True, alpha=0.3)
        ax.set_xlabel('Lab Time Slots', fontweight='bold')
        ax.set_ylabel('Days', fontweight='bold')

    def generate_macroblock_analysis(self):
        """Generate macroblock distribution analysis."""
        if self.schedule_df.empty:
            return
        
        # Create macroblock analysis visualization
        fig = plt.figure(figsize=(20, 12), constrained_layout=True)
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
        fig.savefig(os.path.join(self.output_dir, 'macroblock_analysis.png'), 
                   dpi=300, bbox_inches='tight')
        plt.close(fig)
    
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
            bar.set_color(self.theory_block_colors.get(macroblock, '#CCCCCC'))
    
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
                              color=[self.theory_block_colors.get(block, '#CCCCCC') for block in course_macroblock.columns])
        ax.set_xlabel('Course Code')
        ax.set_ylabel('Number of Assignments')
        ax.set_title('Course Distribution Across Macroblocks')
        ax.legend(title='Macroblock', bbox_to_anchor=(1.05, 1), loc='upper left')
        plt.setp(ax.get_xticklabels(), rotation=45, ha='right') 