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
        
        # Time slots (11 slots per day - Theory timing with proper breaks)
        # Covers 8:00-19:00 as requested (11 slots: 8:00-8:50 to 6:00-6:50 PM)
        self.time_slots = [
            "8:00 - 8:50", "9:00 - 9:50", "10:00 - 10:50", "11:00 - 11:50",
            "12:00 - 12:50", "1:00 - 1:50", "2:00 - 2:50", "3:00 - 3:50", 
            "4:00 - 4:50", "5:00 - 5:50", "6:00 - 6:50"
        ]
        
        # Define macroblock groups (no shift separation since they are merged)
        self.theory_blocks = ['a1', 'b1', 'c1', 'd1', 'e1', 'f1', 'g1', 'a2', 'b2', 'c2', 'd2', 'e2', 'f2', 'g2']
        
        # Tutorial blocks for 3rd lecture hour (ta1, tb1, tc1 etc. are used as 3rd hour for 3-lecture courses)
        # v1 and v2 are excluded as they are not assigned to any courses
        self.tutorial_blocks = ['ta1', 'tb1', 'tc1', 'td1', 'te1', 'tf1', 'tg1', 
                               'ta2', 'tb2', 'tc2', 'td2', 'te2', 'tf2', 'tg2',
                               'taa1', 'taa2', 'tbb1', 'tbb2', 'tcc1', 'tcc2']
        
        if not self.schedule_df.empty:
            # Create color map for courses
            self.courses = self.schedule_df['course_code'].unique()
            colors = plt.cm.tab20(np.linspace(0, 1, len(self.courses)))
            self.course_colors = {course: mcolors.rgb2hex(color) for course, color in zip(self.courses, colors)}
            
            # Create color map for macroblocks
            all_blocks = self.theory_blocks + self.tutorial_blocks
            
            block_colors = plt.cm.Set3(np.linspace(0, 1, len(all_blocks)))
            self.block_colors = {block: mcolors.rgb2hex(color) for block, color in zip(all_blocks, block_colors)}
            
            # Create block-based color mapping for rooms/buildings
            self.building_blocks = self._analyze_building_blocks()
            self.block_room_colors = self._create_block_room_colors()
            
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
            self.building_blocks = {}
            self.block_room_colors = {}
            self.theory_data = pd.DataFrame()
            self.lab_data = pd.DataFrame()
            self.teachers = []
            self.rooms = []
    
    def _analyze_building_blocks(self):
        """Analyze and categorize rooms by building blocks."""
        building_blocks = {
            'Block 1': [],
            'Block 2': [], 
            'Techlounge': [],
            'J Block': [],
            'K Block': [],
            'D Block': [],
            'Unknown Block': []
        }
        
        if not self.schedule_df.empty:
            for _, row in self.schedule_df.iterrows():
                room_id = row.get('room_id', '')
                room_number = row.get('room_number', '')
                room_type = row.get('room_type', 'Room')
                block_info = str(row.get('block', '')).strip()
                
                # Categorize based on block information from the room data
                room_entry = {
                    'room_id': room_id,
                    'room_number': room_number,
                    'room_type': room_type,
                    'block_info': block_info
                }
                
                # Map blocks based on the actual block field values
                if block_info == 'A Block':
                    building_blocks['Block 1'].append(room_entry)
                elif block_info == 'B Block':
                    building_blocks['Block 2'].append(room_entry)
                elif block_info == 'Techlounge':
                    building_blocks['Techlounge'].append(room_entry)
                elif block_info == 'J Block':
                    building_blocks['J Block'].append(room_entry)
                elif block_info == 'K Block':
                    building_blocks['K Block'].append(room_entry)
                elif block_info == 'D Block':
                    building_blocks['D Block'].append(room_entry)
                else:
                    building_blocks['Unknown Block'].append(room_entry)
        
        # Remove duplicates while preserving room information
        for block_name, rooms in building_blocks.items():
            unique_rooms = []
            seen_room_ids = set()
            for room in rooms:
                if room['room_id'] not in seen_room_ids:
                    unique_rooms.append(room)
                    seen_room_ids.add(room['room_id'])
            building_blocks[block_name] = unique_rooms
        
        return building_blocks
    
    def _create_block_room_colors(self):
        """Create color mapping for different building blocks."""
        block_room_colors = {
            'Block 1': '#FF6B6B',      # Red tones for A Block (Academic Block 1)
            'Block 2': '#4ECDC4',      # Teal tones for B Block (Academic Block 2)
            'Techlounge': '#9B59B6',   # Purple for Techlounge labs
            'J Block': '#F39C12',      # Orange for J Block labs
            'K Block': '#27AE60',      # Green for K Block labs  
            'D Block': '#3498DB',      # Blue for D Block labs
            'Unknown Block': '#95A5A6', # Gray for unknown blocks
            'Lab Block 1': '#FF8E8E',   # Light red for Block 1 labs
            'Lab Block 2': '#6BDACF',   # Light teal for Block 2 labs
            'Lab Techlounge': '#C39BD3', # Light purple for Techlounge labs
            'Lab J Block': '#F8C471',   # Light orange for J Block labs
            'Lab K Block': '#58D68D',   # Light green for K Block labs
            'Lab D Block': '#5DADE2',   # Light blue for D Block labs
        }
        return block_room_colors
    
    def _get_room_block_color(self, room_id, room_type='Room'):
        """Get the color for a room based on its block."""
        # Find which block this room belongs to
        for block_name, rooms in self.building_blocks.items():
            for room in rooms:
                if room['room_id'] == room_id:
                    if room_type == 'Lab':
                        return self.block_room_colors.get(f'Lab {block_name}', self.block_room_colors.get(block_name, '#CCCCCC'))
                    else:
                        return self.block_room_colors.get(block_name, '#CCCCCC')
        return '#CCCCCC'  # Default gray
    
    def generate_all_visualizations(self):
        """Generate all timetable visualizations."""
        if self.schedule_df.empty:
            print("No schedule data available for visualization")
            return
        
        self.generate_master_schedule()
        self.generate_teacher_schedules()
        self.generate_room_schedules()
        self.generate_macroblock_analysis()
        self.generate_block_analysis()  # New block-specific analysis
    
    def generate_master_schedule(self):
        """Generate a master schedule visualization with block identification."""
        # Create a figure focusing on theory/tutorial schedule only
        fig = plt.figure(figsize=(24, 16))  # Increased height for block information
        
        # Theory/Tutorial schedule (main focus)
        ax_theory = fig.add_subplot(111)
        self._plot_macroblock_schedule(ax_theory, 'Theory/Tutorial', self.theory_data)
        ax_theory.set_title('Master Theory/Tutorial Schedule with Macroblocks & Building Blocks\n(Theory Time Slots: 8:00-8:50, 9:00-9:50, 10:00-10:50, etc.)', fontsize=16)
        
        # Add block legend
        self._add_block_legend(ax_theory)
        
        # Only show practical schedule if there's actual practical data
        if not self.lab_data.empty:
            # If there are labs, create a subplot layout
            fig.clear()
            gs = GridSpec(2, 1, height_ratios=[3, 2], figure=fig)
            
            # Theory/Tutorial schedule
            ax_theory = fig.add_subplot(gs[0])
            self._plot_macroblock_schedule(ax_theory, 'Theory/Tutorial', self.theory_data)
            ax_theory.set_title('Master Theory/Tutorial Schedule with Macroblocks & Building Blocks\n(Theory Time Slots)', fontsize=16)
            self._add_block_legend(ax_theory)
            
            # Lab schedule
            ax_lab = fig.add_subplot(gs[1])
            self._plot_macroblock_schedule(ax_lab, 'Practical', self.lab_data)
            ax_lab.set_title('Master Practical Schedule with Building Blocks\n(Lab Time Slots)', fontsize=16)
        
        plt.tight_layout()
        fig.savefig(os.path.join(self.output_dir, 'macroblock_master_schedule.png'), 
                   dpi=300, bbox_inches='tight')
        plt.close(fig)
    
    def _add_block_legend(self, ax):
        """Add a legend showing building block color coding."""
        from matplotlib.patches import Patch
        
        legend_elements = []
        
        # Add block color legend
        for block_name, color in self.block_room_colors.items():
            if any(self.building_blocks.get(block_name.replace('Lab ', ''), [])):  # Only show blocks that have rooms
                legend_elements.append(Patch(facecolor=color, edgecolor='black', label=block_name))
        
        if legend_elements:
            ax.legend(handles=legend_elements, loc='upper left', bbox_to_anchor=(1.02, 1), 
                     title='Building Blocks', fontsize=10)
    
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
        """Plot the macroblock schedule for a given type with block identification."""
        if df.empty:
            ax.text(0.5, 0.5, f'No {schedule_type} assignments', 
                   ha='center', va='center', transform=ax.transAxes)
            return
        
        # Create a grid for days and time slots
        grid = np.empty((len(self.days), len(self.time_slots)), dtype=object)
        macroblock_grid = np.empty((len(self.days), len(self.time_slots)), dtype=object)
        block_grid = np.empty((len(self.days), len(self.time_slots)), dtype=object)
        
        for _, row in df.iterrows():
            day = row['day']
            slot_index = row['slot_index']
            
            if day in self.days and 0 <= slot_index < len(self.time_slots):
                day_idx = self.days.index(day)
                course_code = row['course_code']
                macroblock = row.get('macroblock', 'Unknown')
                teacher_id = row['teacher_id']
                room_number = row['room_number']
                room_id = row.get('room_id', '')
                room_type = row.get('room_type', 'Room')
                
                # Determine which building block this room belongs to
                room_block = 'Unknown'
                for block_name, rooms in self.building_blocks.items():
                    for room_info in rooms:
                        if room_info['room_id'] == room_id:
                            room_block = block_name
                            break
                    if room_block != 'Unknown':
                        break
                
                # Create display text with block information
                block_prefix = ""
                if room_block != 'Unknown':
                    block_prefix = f"[{room_block.replace(' ', '')}] "
                
                display_text = f"{block_prefix}{course_code}\n{teacher_id}\n{room_number}"
                grid[day_idx, slot_index] = display_text
                macroblock_grid[day_idx, slot_index] = macroblock
                block_grid[day_idx, slot_index] = room_block
        
        # Plot the grid
        for i, day in enumerate(self.days):
            for j, time_slot in enumerate(self.time_slots):
                if grid[i, j] is not None:
                    macroblock = macroblock_grid[i, j]
                    room_block = block_grid[i, j]
                    room_type = 'Lab' if 'Lab' in str(grid[i, j]) else 'Room'
                    
                    # Use block-based background color with macroblock border
                    bg_color = self._get_room_block_color('', room_type) if room_block == 'Unknown' else self.block_room_colors.get(room_block, '#FFFFFF')
                    border_color = self.block_colors.get(macroblock, 'black')
                    
                    # Create rectangle with block-based background
                    rect = plt.Rectangle((j, len(self.days) - i - 1), 1, 1, 
                                       facecolor=bg_color, edgecolor=border_color, linewidth=2)
                    ax.add_patch(rect)
                    
                    # Add text with adjusted formatting for block info
                    ax.text(j + 0.5, len(self.days) - i - 0.5, grid[i, j],
                           ha='center', va='center', fontsize=7, weight='bold',
                           bbox=dict(boxstyle="round,pad=0.1", facecolor='white', alpha=0.8))
                    
                    # Add macroblock label in corner
                    ax.text(j + 0.9, len(self.days) - i - 0.1, macroblock,
                           ha='right', va='top', fontsize=6, 
                           bbox=dict(boxstyle="round,pad=0.05", facecolor=border_color, alpha=0.7))
                    
                    # Add block indicator in bottom corner
                    if room_block != 'Unknown':
                        block_short = room_block.replace('Block ', 'B')
                        ax.text(j + 0.1, len(self.days) - i - 0.9, block_short,
                               ha='left', va='bottom', fontsize=8, weight='bold',
                               bbox=dict(boxstyle="round,pad=0.05", facecolor=bg_color, alpha=0.9))
        
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
        """Plot the macroblock schedule for a specific teacher with block identification."""
        # Create a grid for days and time slots
        grid = np.empty((len(self.days), len(self.time_slots)), dtype=object)
        macroblock_grid = np.empty((len(self.days), len(self.time_slots)), dtype=object)
        block_grid = np.empty((len(self.days), len(self.time_slots)), dtype=object)
        
        for _, row in teacher_df.iterrows():
            day = row['day']
            slot_index = row['slot_index']
            
            if day in self.days and 0 <= slot_index < len(self.time_slots):
                day_idx = self.days.index(day)
                course_code = row['course_code']
                macroblock = row.get('macroblock', 'Unknown')
                room_number = row['room_number']
                room_id = row.get('room_id', '')
                slot_type = row['slot_type']
                
                # Determine which building block this room belongs to
                room_block = 'Unknown'
                for block_name, rooms in self.building_blocks.items():
                    for room_info in rooms:
                        if room_info['room_id'] == room_id:
                            room_block = block_name
                            break
                    if room_block != 'Unknown':
                        break
                
                # Create display text with block and type information
                block_prefix = ""
                if room_block != 'Unknown':
                    block_prefix = f"[{room_block.replace(' ', '')}] "
                
                display_text = f"{block_prefix}{course_code}\n{slot_type}\n{room_number}"
                grid[day_idx, slot_index] = display_text
                macroblock_grid[day_idx, slot_index] = macroblock
                block_grid[day_idx, slot_index] = room_block
        
        # Plot the grid
        for i, day in enumerate(self.days):
            for j, time_slot in enumerate(self.time_slots):
                if grid[i, j] is not None:
                    macroblock = macroblock_grid[i, j]
                    room_block = block_grid[i, j]
                    room_type = 'Lab' if 'Practical' in str(grid[i, j]) else 'Room'
                    
                    # Use block-based background color
                    bg_color = self._get_room_block_color('', room_type) if room_block == 'Unknown' else self.block_room_colors.get(room_block, '#FFFFFF')
                    border_color = self.block_colors.get(macroblock, 'black')
                    
                    # Create rectangle
                    rect = plt.Rectangle((j, len(self.days) - i - 1), 1, 1, 
                                       facecolor=bg_color, edgecolor=border_color, linewidth=2)
                    ax.add_patch(rect)
                    
                    # Add text
                    ax.text(j + 0.5, len(self.days) - i - 0.5, grid[i, j],
                           ha='center', va='center', fontsize=7, weight='bold',
                           bbox=dict(boxstyle="round,pad=0.1", facecolor='white', alpha=0.8))
                    
                    # Add macroblock label
                    ax.text(j + 0.9, len(self.days) - i - 0.1, macroblock,
                           ha='right', va='top', fontsize=6, 
                           bbox=dict(boxstyle="round,pad=0.05", facecolor=border_color, alpha=0.7))
                    
                    # Add block indicator
                    if room_block != 'Unknown':
                        block_short = room_block.replace('Block ', 'B')
                        ax.text(j + 0.1, len(self.days) - i - 0.9, block_short,
                               ha='left', va='bottom', fontsize=8, weight='bold',
                               bbox=dict(boxstyle="round,pad=0.05", facecolor=bg_color, alpha=0.9))
        
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
        """Plot the macroblock schedule for a specific room with block identification."""
        # Similar implementation to teacher schedule but focused on room utilization
        grid = np.empty((len(self.days), len(self.time_slots)), dtype=object)
        macroblock_grid = np.empty((len(self.days), len(self.time_slots)), dtype=object)
        block_grid = np.empty((len(self.days), len(self.time_slots)), dtype=object)
        
        # Determine which block this room belongs to
        room_block = 'Unknown'
        for block_name, rooms in self.building_blocks.items():
            for room_info in rooms:
                if room_info['room_id'] == room_id:
                    room_block = block_name
                    break
            if room_block != 'Unknown':
                break
        
        for _, row in room_df.iterrows():
            day = row['day']
            slot_index = row['slot_index']
            
            if day in self.days and 0 <= slot_index < len(self.time_slots):
                day_idx = self.days.index(day)
                course_code = row['course_code']
                macroblock = row.get('macroblock', 'Unknown')
                teacher_id = row['teacher_id']
                slot_type = row['slot_type']
                
                # Create display text with block information
                block_prefix = f"[{room_block.replace(' ', '')}] " if room_block != 'Unknown' else ""
                display_text = f"{block_prefix}{course_code}\n{slot_type}\nT:{teacher_id}"
                grid[day_idx, slot_index] = display_text
                macroblock_grid[day_idx, slot_index] = macroblock
                block_grid[day_idx, slot_index] = room_block
        
        # Plot the grid (similar to teacher schedule)
        for i, day in enumerate(self.days):
            for j, time_slot in enumerate(self.time_slots):
                if grid[i, j] is not None:
                    macroblock = macroblock_grid[i, j]
                    room_block = block_grid[i, j]
                    room_type = 'Lab' if 'Practical' in str(grid[i, j]) else 'Room'
                    
                    # Use block-based background color
                    bg_color = self._get_room_block_color('', room_type) if room_block == 'Unknown' else self.block_room_colors.get(room_block, '#FFFFFF')
                    border_color = self.block_colors.get(macroblock, 'black')
                    
                    # Create rectangle
                    rect = plt.Rectangle((j, len(self.days) - i - 1), 1, 1, 
                                       facecolor=bg_color, edgecolor=border_color, linewidth=2)
                    ax.add_patch(rect)
                    
                    ax.text(j + 0.5, len(self.days) - i - 0.5, grid[i, j],
                           ha='center', va='center', fontsize=8, weight='bold',
                           bbox=dict(boxstyle="round,pad=0.1", facecolor='white', alpha=0.8))
                    
                    ax.text(j + 0.9, len(self.days) - i - 0.1, macroblock,
                           ha='right', va='top', fontsize=6, 
                           bbox=dict(boxstyle="round,pad=0.05", facecolor=border_color, alpha=0.7))
                    
                    # Add block indicator
                    if room_block != 'Unknown':
                        block_short = room_block.replace('Block ', 'B')
                        ax.text(j + 0.1, len(self.days) - i - 0.9, block_short,
                               ha='left', va='bottom', fontsize=8, weight='bold',
                               bbox=dict(boxstyle="round,pad=0.05", facecolor=bg_color, alpha=0.9))
        
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
    
    def generate_block_analysis(self):
        """Generate block-specific analysis and visualizations."""
        if self.schedule_df.empty:
            return
        
        fig = plt.figure(figsize=(20, 16))
        gs = GridSpec(3, 2, figure=fig)
        
        # Block distribution
        ax1 = fig.add_subplot(gs[0, 0])
        self._plot_block_distribution(ax1)
        
        # Block utilization by day
        ax2 = fig.add_subplot(gs[0, 1])
        self._plot_block_daily_usage(ax2)
        
        # Room utilization by block
        ax3 = fig.add_subplot(gs[1, 0])
        self._plot_room_utilization_by_block(ax3)
        
        # Teacher-block distribution
        ax4 = fig.add_subplot(gs[1, 1])
        self._plot_teacher_block_distribution(ax4)
        
        # Block capacity analysis
        ax5 = fig.add_subplot(gs[2, :])
        self._plot_block_capacity_analysis(ax5)
        
        plt.suptitle('Building Block Analysis (Block 1 vs Block 2)', fontsize=16)
        plt.tight_layout()
        fig.savefig(os.path.join(self.output_dir, 'building_block_analysis.png'), 
                   dpi=300, bbox_inches='tight')
        plt.close(fig)
    
    def _plot_block_distribution(self, ax):
        """Plot distribution of classes across building blocks."""
        if not self.building_blocks:
            ax.text(0.5, 0.5, 'No building block data available', ha='center', va='center', transform=ax.transAxes)
            return
        
        # Count assignments per block
        block_assignment_counts = {}
        for block_name, rooms in self.building_blocks.items():
            if rooms:  # Only count blocks that have rooms
                room_ids = [room['room_id'] for room in rooms]
                assignments = self.schedule_df[self.schedule_df['room_id'].isin(room_ids)]
                block_assignment_counts[block_name] = len(assignments)
        
        # Filter out blocks with no assignments for cleaner visualization
        block_assignment_counts = {k: v for k, v in block_assignment_counts.items() if v > 0}
        
        if not block_assignment_counts:
            ax.text(0.5, 0.5, 'No block assignment data available', ha='center', va='center', transform=ax.transAxes)
            return
        
        blocks = list(block_assignment_counts.keys())
        counts = list(block_assignment_counts.values())
        
        bars = ax.bar(range(len(blocks)), counts)
        ax.set_xticks(range(len(blocks)))
        ax.set_xticklabels(blocks, rotation=45, ha='right')
        ax.set_ylabel('Number of Class Assignments')
        ax.set_title('Class Distribution Across Building Blocks')
        
        # Color bars according to block colors
        for i, (block, bar) in enumerate(zip(blocks, bars)):
            color = self.block_room_colors.get(block, '#CCCCCC')
            # Use lab color variation if this is a lab-heavy block
            if any('Lab' in str(room.get('room_type', '')) for room in self.building_blocks.get(block, [])):
                color = self.block_room_colors.get(f'Lab {block}', color)
            bar.set_color(color)
        
        # Add value labels on bars
        for i, (block, count) in enumerate(zip(blocks, counts)):
            ax.text(i, count + max(counts) * 0.01, str(count), ha='center', va='bottom', fontweight='bold')
    
    def _plot_block_daily_usage(self, ax):
        """Plot building block utilization by day."""
        if not self.building_blocks:
            ax.text(0.5, 0.5, 'No building block data available', ha='center', va='center', transform=ax.transAxes)
            return
        
        # Create daily usage data for each block (only blocks with assignments)
        daily_block_usage = {}
        active_blocks = []
        
        for block_name, rooms in self.building_blocks.items():
            if rooms:  # Only count blocks that have rooms
                room_ids = [room['room_id'] for room in rooms]
                block_schedule = self.schedule_df[self.schedule_df['room_id'].isin(room_ids)]
                if len(block_schedule) > 0:  # Only include blocks with assignments
                    daily_counts = block_schedule['day'].value_counts()
                    daily_counts = daily_counts.reindex(self.days, fill_value=0)
                    daily_block_usage[block_name] = daily_counts.values
                    active_blocks.append(block_name)
        
        if not daily_block_usage:
            ax.text(0.5, 0.5, 'No daily usage data available', ha='center', va='center', transform=ax.transAxes)
            return
        
        # Create grouped bar chart
        x = np.arange(len(self.days))
        width = 0.15  # Narrower bars for more blocks
        
        for i, block_name in enumerate(active_blocks):
            usage_data = daily_block_usage[block_name]
            offset = (i - len(active_blocks)/2) * width
            color = self.block_room_colors.get(block_name, '#CCCCCC')
            bars = ax.bar(x + offset, usage_data, width, 
                         label=block_name, color=color)
        
        ax.set_xlabel('Days')
        ax.set_ylabel('Number of Classes')
        ax.set_title('Block Utilization by Day')
        ax.set_xticks(x)
        ax.set_xticklabels([day.capitalize() for day in self.days])
        ax.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
    
    def _plot_room_utilization_by_block(self, ax):
        """Plot room utilization grouped by block."""
        if not self.building_blocks:
            ax.text(0.5, 0.5, 'No building block data available', ha='center', va='center', transform=ax.transAxes)
            return
        
        # Calculate room utilization for each block
        block_room_utilization = {}
        for block_name, rooms in self.building_blocks.items():
            if rooms:  # Only count blocks that have rooms
                room_utilization = []
                for room in rooms:
                    room_id = room['room_id']
                    room_assignments = self.schedule_df[self.schedule_df['room_id'] == room_id]
                    utilization = len(room_assignments)
                    room_utilization.append(utilization)
                if room_utilization:  # Only include blocks with rooms
                    block_room_utilization[block_name] = {
                        'total_rooms': len(rooms),
                        'avg_utilization': np.mean(room_utilization),
                        'max_utilization': max(room_utilization),
                        'min_utilization': min(room_utilization),
                        'total_assignments': sum(room_utilization)
                    }
        
        # Filter out blocks with no assignments
        block_room_utilization = {k: v for k, v in block_room_utilization.items() if v['total_assignments'] > 0}
        
        if not block_room_utilization:
            ax.text(0.5, 0.5, 'No room utilization data available', ha='center', va='center', transform=ax.transAxes)
            return
        
        blocks = list(block_room_utilization.keys())
        avg_utilizations = [block_room_utilization[block]['avg_utilization'] for block in blocks]
        
        bars = ax.bar(range(len(blocks)), avg_utilizations)
        ax.set_xticks(range(len(blocks)))
        ax.set_xticklabels(blocks, rotation=45, ha='right')
        ax.set_ylabel('Average Room Utilization (classes/room)')
        ax.set_title('Average Room Utilization by Block')
        
        # Color bars according to block colors
        for i, (block, bar) in enumerate(zip(blocks, bars)):
            color = self.block_room_colors.get(block, '#CCCCCC')
            bar.set_color(color)
        
        # Add text annotations with room count and total assignments
        for i, (block, bar) in enumerate(zip(blocks, bars)):
            room_count = block_room_utilization[block]['total_rooms']
            total_assignments = block_room_utilization[block]['total_assignments']
            ax.text(i, bar.get_height() + max(avg_utilizations) * 0.02, 
                   f'{room_count} rooms\n{total_assignments} classes', 
                   ha='center', va='bottom', fontsize=8, fontweight='bold')
    
    def _plot_teacher_block_distribution(self, ax):
        """Plot which blocks teachers are primarily assigned to."""
        if not self.building_blocks:
            ax.text(0.5, 0.5, 'No building block data available', ha='center', va='center', transform=ax.transAxes)
            return
        
        # Calculate teacher-block assignments
        teacher_block_counts = {}
        for teacher_id in self.teachers:
            teacher_schedule = self.schedule_df[self.schedule_df['teacher_id'] == teacher_id]
            teacher_block_counts[teacher_id] = {}
            
            for block_name, rooms in self.building_blocks.items():
                if rooms:  # Only count blocks that have rooms
                    room_ids = [room['room_id'] for room in rooms]
                    block_assignments = teacher_schedule[teacher_schedule['room_id'].isin(room_ids)]
                    teacher_block_counts[teacher_id][block_name] = len(block_assignments)
        
        # Count teachers with assignments in each block
        block_teacher_counts = {}
        for block_name in self.building_blocks.keys():
            if self.building_blocks[block_name]:  # Only count blocks that have rooms
                active_teachers = 0
                for teacher_id, blocks in teacher_block_counts.items():
                    if blocks.get(block_name, 0) > 0:  # Teacher has at least one assignment in this block
                        active_teachers += 1
                if active_teachers > 0:  # Only include blocks with active teachers
                    block_teacher_counts[block_name] = active_teachers
        
        if not block_teacher_counts:
            ax.text(0.5, 0.5, 'No teacher-block data available', ha='center', va='center', transform=ax.transAxes)
            return
        
        blocks = list(block_teacher_counts.keys())
        teacher_counts = list(block_teacher_counts.values())
        
        bars = ax.bar(range(len(blocks)), teacher_counts)
        ax.set_xticks(range(len(blocks)))
        ax.set_xticklabels(blocks, rotation=45, ha='right')
        ax.set_ylabel('Number of Teachers')
        ax.set_title('Teachers Assigned to Each Block')
        
        # Color bars according to block colors
        for i, (block, bar) in enumerate(zip(blocks, bars)):
            color = self.block_room_colors.get(block, '#CCCCCC')
            bar.set_color(color)
        
        # Add value labels
        for i, count in enumerate(teacher_counts):
            ax.text(i, count + max(teacher_counts) * 0.02, str(count), 
                   ha='center', va='bottom', fontweight='bold')
    
    def _plot_block_capacity_analysis(self, ax):
        """Plot block capacity and utilization analysis."""
        if not self.building_blocks:
            ax.text(0.5, 0.5, 'No building block data available', ha='center', va='center', transform=ax.transAxes)
            return
        
        # Calculate block statistics
        block_stats = {}
        for block_name, rooms in self.building_blocks.items():
            if rooms:  # Only count blocks that have rooms
                room_ids = [room['room_id'] for room in rooms]
                block_assignments = self.schedule_df[self.schedule_df['room_id'].isin(room_ids)]
                
                # Calculate capacity utilization if available
                total_capacity = 0
                room_types = []
                if 'capacity' in self.schedule_df.columns:
                    for room_id in room_ids:
                        room_data = self.schedule_df[self.schedule_df['room_id'] == room_id]
                        if len(room_data) > 0:
                            room_capacity = room_data['capacity'].iloc[0]
                            total_capacity += room_capacity
                            room_type = room_data.get('room_type', 'Room').iloc[0] if 'room_type' in room_data.columns else 'Room'
                            room_types.append(room_type)
                
                # Only include blocks with assignments for the table
                if len(block_assignments) > 0:
                    # Calculate maximum possible weekly assignments (11 time slots × 5 days = 55 per room)
                    max_weekly_assignments = len(rooms) * 55
                    utilization_rate = len(block_assignments) / max_weekly_assignments if max_weekly_assignments > 0 else 0
                    
                    # Determine primary room type for this block
                    primary_room_type = 'Mixed'
                    if room_types:
                        type_counts = {}
                        for rt in room_types:
                            type_counts[rt] = type_counts.get(rt, 0) + 1
                        primary_room_type = max(type_counts.keys(), key=lambda k: type_counts[k])
                    
                    block_stats[block_name] = {
                        'rooms': len(rooms),
                        'assignments': len(block_assignments),
                        'capacity': total_capacity,
                        'utilization_rate': utilization_rate,
                        'primary_room_type': primary_room_type
                    }
        
        if not block_stats:
            ax.text(0.5, 0.5, 'No block statistics available', ha='center', va='center', transform=ax.transAxes)
            return
        
        # Create a summary table visualization
        ax.axis('tight')
        ax.axis('off')
        
        # Prepare data for table
        table_data = []
        headers = ['Block', 'Rooms', 'Assignments', 'Primary Type', 'Total Capacity', 'Utilization %']
        
        for block_name, stats in block_stats.items():
            table_data.append([
                block_name,
                str(stats['rooms']),
                str(stats['assignments']),
                stats['primary_room_type'],
                str(stats['capacity']) if stats['capacity'] > 0 else 'N/A',
                f"{stats['utilization_rate']:.1%}"
            ])
        
        # Create table
        table = ax.table(cellText=table_data, colLabels=headers, 
                        cellLoc='center', loc='center')
        table.auto_set_font_size(False)
        table.set_fontsize(9)
        table.scale(1.3, 1.8)
        
        # Color code the table rows by block
        for i, (block_name, _) in enumerate(block_stats.items()):
            color = self.block_room_colors.get(block_name, '#CCCCCC')
            for j in range(len(headers)):
                table[(i + 1, j)].set_facecolor(color)
                table[(i + 1, j)].set_alpha(0.3)
        
        ax.set_title('Block Capacity and Utilization Analysis', fontsize=14, pad=20) 