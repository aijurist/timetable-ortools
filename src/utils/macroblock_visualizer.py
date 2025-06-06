import os
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import numpy as np
from matplotlib.gridspec import GridSpec

class TimetableVisualizer:
    def __init__(self, schedule_data, output_dir):
        """Initialize the timetable visualizer."""
        self.schedule_df = pd.DataFrame(schedule_data) if schedule_data else pd.DataFrame()
        self.output_dir = output_dir
        
        # Load teacher shift distribution data if available
        self.teacher_shift_data = self._load_teacher_shift_data()
        
        # Timetable days structure
        self.days = ["tuesday", "wed", "thur", "fri", "sat"]
        
        # Time slots (11 slots per day - Theory timing)
        self.time_slots = [
            "8:00 - 8:50", "9:00 - 9:50", "10:00 - 10:50", "11:00 - 11:50",
            "12:00 - 12:50", "1:00 - 1:50", "2:00 - 2:50", "3:00 - 3:50", 
            "4:00 - 4:50", "5:00 - 5:50", "6:00 - 6:50"
        ]
        
        # Lab sessions (6 sessions per day - 2 hours each)
        self.lab_sessions = {
            'L1': {'slots': [0, 1], 'time_range': '8:00 - 9:40'},
            'L2': {'slots': [2, 3], 'time_range': '9:50 - 11:30'},
            'L3': {'slots': [4, 5], 'time_range': '11:50 - 1:30'},
            'L4': {'slots': [6, 7], 'time_range': '1:50 - 3:30'},
            'L5': {'slots': [8, 9], 'time_range': '3:50 - 5:30'},
            'L6': {'slots': [10, 11], 'time_range': '5:30 - 7:10'}
        }
        
        # Define block groups for color coding
        self.theory_blocks = ['T0', 'T1', 'T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'T8', 'T9', 'T10']
        self.lab_block_names = ['L1', 'L2', 'L3', 'L4', 'L5', 'L6']
        
        if not self.schedule_df.empty:
            # Create color map for courses
            self.courses = self.schedule_df['course_code'].unique()
            colors = plt.cm.tab20(np.linspace(0, 1, len(self.courses)))
            self.course_colors = {course: mcolors.rgb2hex(color) for course, color in zip(self.courses, colors)}
            
            # Create color map for time blocks
            all_blocks = self.theory_blocks + self.lab_block_names
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
    
    def _load_teacher_shift_data(self):
        """Load teacher shift distribution data from saved files."""
        import json
        import os
        
        shift_data = {
            'distributions': {},
            'daily_shifts': {},
            'available': False
        }
        
        try:
            # Load distribution data
            distribution_file = os.path.join(self.output_dir, 'teacher_shift_distributions.json')
            if os.path.exists(distribution_file):
                with open(distribution_file, 'r', encoding='utf-8') as f:
                    shift_data['distributions'] = json.load(f)
                shift_data['available'] = True
            
            # Load daily shifts data
            daily_shifts_file = os.path.join(self.output_dir, 'teacher_daily_shifts.csv')
            if os.path.exists(daily_shifts_file):
                daily_shifts_df = pd.read_csv(daily_shifts_file)
                shift_data['daily_shifts'] = daily_shifts_df
                
        except Exception as e:
            print(f"Warning: Could not load teacher shift data: {e}")
        
        return shift_data
    
    def _analyze_building_blocks(self):
        """Analyze and categorize rooms by building blocks."""
        building_blocks = {
            'A Block': [],
            'B Block': [], 
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
                    building_blocks['A Block'].append(room_entry)
                elif block_info == 'B Block':
                    building_blocks['B Block'].append(room_entry)
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
            'A Block': '#FF6B6B',      # Red tones for A Block (Academic Block 1)
            'B Block': '#4ECDC4',      # Teal tones for B Block (Academic Block 2)
            'Techlounge': '#9B59B6',   # Purple for Techlounge labs
            'J Block': '#F39C12',      # Orange for J Block labs
            'K Block': '#27AE60',      # Green for K Block labs  
            'D Block': '#3498DB',      # Blue for D Block labs
            'Unknown Block': '#95A5A6', # Gray for unknown blocks
            'Lab A Block': '#FF8E8E',   # Light red for A Block labs
            'Lab B Block': '#6BDACF',   # Light teal for B Block labs
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
        self.generate_timetable_analysis()
        self.generate_block_analysis()
    
    def generate_master_schedule(self):
        """Generate a comprehensive master schedule visualization showing both theory and lab schedules."""
        # Create a figure with side-by-side layout for theory and lab schedules
        fig = plt.figure(figsize=(32, 16))
        
        if not self.lab_data.empty:
            # Both theory and lab data available - side by side layout
            gs = GridSpec(1, 2, width_ratios=[1, 1], figure=fig)
            
            # Theory/Tutorial schedule (left side)
            ax_theory = fig.add_subplot(gs[0])
            self._plot_theory_schedule(ax_theory, self.theory_data)
            ax_theory.set_title('Theory/Tutorial Schedule\n(11 Theory Time Slots: 8:00-8:50 to 6:00-6:50)', fontsize=14)
            
            # Lab schedule (right side)
            ax_lab = fig.add_subplot(gs[1])
            self._plot_lab_schedule(ax_lab, self.lab_data)
            ax_lab.set_title('Practical/Lab Schedule\n(6 Lab Sessions: L1-L6, 2 hours each)', fontsize=14)
            
            # Add unified legend
            self._add_unified_legend(fig)
        else:
            # Only theory data - full width
            ax_theory = fig.add_subplot(111)
            self._plot_theory_schedule(ax_theory, self.theory_data)
            ax_theory.set_title('Master Theory/Tutorial Schedule\n(11 Theory Time Slots: 8:00-8:50 to 6:00-6:50)', fontsize=16)
            self._add_block_legend(ax_theory)
        
        plt.suptitle('Master Timetable Schedule - Theory and Lab Assignments', fontsize=18, y=0.95)
        plt.tight_layout()
        fig.savefig(os.path.join(self.output_dir, 'master_timetable_schedule.png'), 
                   dpi=300, bbox_inches='tight')
        plt.close(fig)
    
    def _plot_theory_schedule(self, ax, theory_df):
        """Plot the theory schedule with proper time slot structure."""
        if theory_df.empty:
            ax.text(0.5, 0.5, 'No Theory/Tutorial assignments', 
                   ha='center', va='center', transform=ax.transAxes)
            return
        
        # Create a grid for days and theory time slots
        grid = np.empty((len(self.days), len(self.time_slots)), dtype=object)
        block_grid = np.empty((len(self.days), len(self.time_slots)), dtype=object)
        
        for _, row in theory_df.iterrows():
            day = row['day']
            slot_index = row['slot_index']
            
            if day in self.days and isinstance(slot_index, int) and 0 <= slot_index < len(self.time_slots):
                day_idx = self.days.index(day)
                course_code = row['course_code']
                teacher_id = row['teacher_id']
                room_number = row['room_number']
                room_id = row.get('room_id', '')
                room_type = row.get('room_type', 'Classroom')
                
                # Determine which building block this room belongs to
                room_block = self._get_room_building_block(room_id)
                
                # Create display text with block information
                block_prefix = f"[{room_block.replace(' Block', '')}]" if room_block != 'Unknown Block' else ""
                display_text = f"{block_prefix}{course_code}\n{teacher_id}\n{room_number}"
                grid[day_idx, slot_index] = display_text
                block_grid[day_idx, slot_index] = room_block
        
        self._plot_schedule_grid(ax, grid, block_grid, self.time_slots, 'Theory')
    
    def _plot_lab_schedule(self, ax, lab_df):
        """Plot the lab schedule with proper lab session structure."""
        if lab_df.empty:
            ax.text(0.5, 0.5, 'No Lab/Practical assignments', 
                   ha='center', va='center', transform=ax.transAxes)
            return
        
        # Create a grid for days and lab sessions
        lab_session_names = list(self.lab_sessions.keys())  # ['L1', 'L2', 'L3', 'L4', 'L5', 'L6']
        grid = np.empty((len(self.days), len(lab_session_names)), dtype=object)
        block_grid = np.empty((len(self.days), len(lab_session_names)), dtype=object)
        
        for _, row in lab_df.iterrows():
            day = row['day']
            slot_index = row['slot_index']
            
            # Extract lab session from slot_index (e.g., "Lab_L1" -> "L1")
            if day in self.days and isinstance(slot_index, str) and slot_index.startswith('Lab_'):
                lab_session = slot_index.replace('Lab_', '')
                if lab_session in lab_session_names:
                    day_idx = self.days.index(day)
                    session_idx = lab_session_names.index(lab_session)
                    
                    course_code = row['course_code']
                    teacher_id = row['teacher_id']
                    room_number = row['room_number']
                    room_id = row.get('room_id', '')
                
                # Determine which building block this room belongs to
                    room_block = self._get_room_building_block(room_id)
                    
                    # Create display text with block information
                    block_prefix = f"[{room_block.replace(' Block', '')}]" if room_block != 'Unknown Block' else ""
                    display_text = f"{block_prefix}{course_code}\n{teacher_id}\n{room_number}"
                    grid[day_idx, session_idx] = display_text
                    block_grid[day_idx, session_idx] = room_block
        
        # Create lab time labels
        lab_time_labels = [f"{session}\n{info['time_range']}" for session, info in self.lab_sessions.items()]
        
        self._plot_schedule_grid(ax, grid, block_grid, lab_time_labels, 'Lab')
    
    def _get_room_building_block(self, room_id):
        """Get the building block name for a room."""
        for block_name, rooms in self.building_blocks.items():
            for room in rooms:
                if room['room_id'] == room_id:
                    return block_name
        return 'Unknown Block'
    
    def _plot_schedule_grid(self, ax, grid, block_grid, time_labels, schedule_type):
        """Plot a schedule grid with proper formatting."""
        rows, cols = grid.shape
        
        # Plot the grid
        for i in range(rows):
            for j in range(cols):
                if grid[i, j] is not None:
                    room_block = block_grid[i, j]
                    room_type = 'Lab' if schedule_type == 'Lab' else 'Classroom'
                    
                    # Use block-based background color
                    bg_color = self.block_room_colors.get(room_block, '#FFFFFF')
                    if schedule_type == 'Lab':
                        bg_color = self.block_room_colors.get(f'Lab {room_block}', bg_color)
                    
                    # Create rectangle with block-based background
                    rect = plt.Rectangle((j, rows - i - 1), 1, 1, 
                                       facecolor=bg_color, edgecolor='black', linewidth=1.5, alpha=0.8)
                    ax.add_patch(rect)
                    
                    # Add text
                    ax.text(j + 0.5, rows - i - 0.5, grid[i, j],
                           ha='center', va='center', fontsize=8, weight='bold',
                           bbox=dict(boxstyle="round,pad=0.1", facecolor='white', alpha=0.9))
                    
                    # Add block indicator in corner
                    if room_block != 'Unknown Block':
                        block_short = room_block.replace(' Block', '').replace('Techlounge', 'TL')
                        ax.text(j + 0.1, rows - i - 0.1, block_short,
                               ha='left', va='top', fontsize=7, weight='bold',
                               bbox=dict(boxstyle="round,pad=0.05", facecolor=bg_color, alpha=0.9))
        
        # Set axes properties
        ax.set_xlim(0, cols)
        ax.set_ylim(0, rows)
        ax.set_xticks(range(cols))
        ax.set_xticklabels(time_labels, rotation=45, ha='right', fontsize=9)
        ax.set_yticks(range(rows))
        ax.set_yticklabels([day.capitalize() for day in reversed(self.days)], fontsize=10)
        ax.grid(True, alpha=0.3)
    
    def _add_unified_legend(self, fig):
        """Add a unified legend for the entire figure."""
        from matplotlib.patches import Patch
        
        legend_elements = []
        
        # Add block color legend for both classroom and lab blocks
        for block_name, color in self.block_room_colors.items():
            if any(self.building_blocks.get(block_name.replace('Lab ', ''), [])):
                legend_elements.append(Patch(facecolor=color, edgecolor='black', label=block_name, alpha=0.8))
        
        if legend_elements:
            # Add legend to the figure
            fig.legend(handles=legend_elements, loc='center', bbox_to_anchor=(0.5, 0.02), 
                      ncol=min(len(legend_elements), 6), title='Building Blocks', fontsize=10)
    
    def _add_block_legend(self, ax):
        """Add a legend showing building block color coding."""
        from matplotlib.patches import Patch
        
        legend_elements = []
        
        # Add block color legend
        for block_name, color in self.block_room_colors.items():
            if not block_name.startswith('Lab ') and any(self.building_blocks.get(block_name, [])):
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
    
    def generate_timetable_analysis(self):
        """Generate timetable distribution analysis."""
        if self.schedule_df.empty:
            return
        
        # Create analysis visualization
        fig = plt.figure(figsize=(20, 12))
        gs = GridSpec(2, 2, figure=fig)
        
        # Theory/Lab distribution
        ax1 = fig.add_subplot(gs[0, 0])
        self._plot_type_distribution(ax1)
        
        # Daily usage pattern
        ax2 = fig.add_subplot(gs[0, 1])
        self._plot_daily_usage(ax2)
        
        # Course distribution
        ax3 = fig.add_subplot(gs[1, 0])
        self._plot_course_distribution(ax3)
        
        # Building block usage
        ax4 = fig.add_subplot(gs[1, 1])
        self._plot_building_block_usage(ax4)
        
        plt.suptitle('Timetable Analysis - Theory and Lab Distribution', fontsize=16)
        plt.tight_layout()
        fig.savefig(os.path.join(self.output_dir, 'timetable_analysis.png'), 
                   dpi=300, bbox_inches='tight')
        plt.close(fig)
    
    def _plot_type_distribution(self, ax):
        """Plot distribution of different class types."""
        type_counts = self.schedule_df['slot_type'].value_counts()
        
        colors = ['#FF6B6B', '#4ECDC4', '#45B7D1']
        wedges, texts, autotexts = ax.pie(type_counts.values, labels=type_counts.index, 
                                         colors=colors[:len(type_counts)], autopct='%1.1f%%')
        ax.set_title('Class Type Distribution')
    
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
    
    def _plot_course_distribution(self, ax):
        """Plot course distribution."""
        course_counts = self.schedule_df['course_code'].value_counts().head(10)  # Top 10 courses
        
        bars = ax.bar(range(len(course_counts)), course_counts.values)
        ax.set_xticks(range(len(course_counts)))
        ax.set_xticklabels(course_counts.index, rotation=45, ha='right')
        ax.set_ylabel('Number of Sessions')
        ax.set_title('Top 10 Courses by Session Count')
        
        # Color bars according to course colors
        for i, (course, bar) in enumerate(zip(course_counts.index, bars)):
            bar.set_color(self.course_colors.get(course, '#CCCCCC'))
    
    def _plot_building_block_usage(self, ax):
        """Plot building block usage."""
        block_usage = {}
        for _, row in self.schedule_df.iterrows():
            room_id = row.get('room_id', '')
            room_block = self._get_room_building_block(room_id)
            block_usage[room_block] = block_usage.get(room_block, 0) + 1
        
        if block_usage:
            blocks = list(block_usage.keys())
            counts = list(block_usage.values())
            
            bars = ax.bar(range(len(blocks)), counts)
            ax.set_xticks(range(len(blocks)))
            ax.set_xticklabels([block.replace(' Block', '') for block in blocks], rotation=45)
            ax.set_ylabel('Number of Sessions')
            ax.set_title('Building Block Usage')
            
            # Color bars according to block colors
            for block, bar in zip(blocks, bars):
                color = self.block_room_colors.get(block, '#CCCCCC')
                bar.set_color(color)
    
    def generate_block_analysis(self):
        """Generate building block analysis."""
        # This method would contain the existing block analysis code
        # For now, keeping it similar to the original implementation
        pass
    
    def _create_teacher_schedule(self, teacher_id, teacher_df):
        """Create a comprehensive teacher schedule showing both theory and lab assignments."""
        if teacher_df.empty:
            return
        
        # Get teacher info
        teacher_info = teacher_df.iloc[0]
        teacher_name = f"{teacher_info.get('first_name', '')} {teacher_info.get('last_name', '')}".strip()
        staff_code = teacher_info.get('staff_code', '')
        
        # Separate theory and lab data for this teacher
        theory_data = teacher_df[teacher_df['slot_type'].isin(['Lecture', 'Tutorial'])].copy()
        lab_data = teacher_df[teacher_df['slot_type'] == 'Practical'].copy()
        
        # Create figure
        fig = plt.figure(figsize=(20, 12))
        
        if not lab_data.empty:
            # Both theory and lab data - side by side layout
            gs = GridSpec(2, 2, height_ratios=[1, 0.3], width_ratios=[1, 1], figure=fig)
            
            # Theory schedule (top left)
            ax_theory = fig.add_subplot(gs[0, 0])
            self._plot_teacher_theory_schedule(ax_theory, theory_data, teacher_id)
            ax_theory.set_title(f'Theory/Tutorial Schedule', fontsize=12)
            
            # Lab schedule (top right)
            ax_lab = fig.add_subplot(gs[0, 1])
            self._plot_teacher_lab_schedule(ax_lab, lab_data, teacher_id)
            ax_lab.set_title(f'Lab/Practical Schedule', fontsize=12)
            
            # Summary information (bottom, spanning both columns)
            ax_summary = fig.add_subplot(gs[1, :])
            self._plot_teacher_summary(ax_summary, teacher_df, teacher_id)
            
        else:
            # Only theory data - full width layout
            gs = GridSpec(2, 1, height_ratios=[1, 0.3], figure=fig)
            
            ax_theory = fig.add_subplot(gs[0])
            self._plot_teacher_theory_schedule(ax_theory, theory_data, teacher_id)
            ax_theory.set_title(f'Theory/Tutorial Schedule', fontsize=14)
            
            # Summary information (bottom)
            ax_summary = fig.add_subplot(gs[1])
            self._plot_teacher_summary(ax_summary, teacher_df, teacher_id)
        
        # Main title
        title = f'Teacher Schedule: {teacher_name}'
        if staff_code:
            title += f' ({staff_code})'
        title += f' - ID: {teacher_id}'
        
        plt.suptitle(title, fontsize=16, y=0.95)
        plt.tight_layout()
        
        # Save the teacher schedule
        filename = f'teacher_{teacher_id}_schedule.png'
        filepath = os.path.join(self.output_dir, filename)
        fig.savefig(filepath, dpi=300, bbox_inches='tight')
        plt.close(fig)
    
        print(f"Generated teacher schedule: {filename}")
    
    def _plot_teacher_theory_schedule(self, ax, theory_df, teacher_id):
        """Plot theory schedule for a specific teacher."""
        # Create a grid for days and time slots
        grid = np.empty((len(self.days), len(self.time_slots)), dtype=object)
        block_grid = np.empty((len(self.days), len(self.time_slots)), dtype=object)
        
        for _, row in theory_df.iterrows():
            day = row['day']
            slot_index = row['slot_index']
            
            if day in self.days and isinstance(slot_index, int) and 0 <= slot_index < len(self.time_slots):
                day_idx = self.days.index(day)
                course_code = row['course_code']
                room_number = row['room_number']
                room_id = row.get('room_id', '')
                slot_type = row.get('slot_type', 'Lecture')
                
                # Determine room block
                room_block = self._get_room_building_block(room_id)
                
                # Create display text
                block_prefix = f"[{room_block.replace(' Block', '')}]" if room_block != 'Unknown Block' else ""
                type_indicator = "L" if slot_type == "Lecture" else "T"  # L for Lecture, T for Tutorial
                display_text = f"{block_prefix}{course_code}\n({type_indicator})\n{room_number}"
                grid[day_idx, slot_index] = display_text
                block_grid[day_idx, slot_index] = room_block
        
        self._plot_schedule_grid(ax, grid, block_grid, self.time_slots, 'Theory')
    
    def _plot_teacher_lab_schedule(self, ax, lab_df, teacher_id):
        """Plot lab schedule for a specific teacher."""
        # Create a grid for days and lab sessions
        lab_session_names = list(self.lab_sessions.keys())
        grid = np.empty((len(self.days), len(lab_session_names)), dtype=object)
        block_grid = np.empty((len(self.days), len(lab_session_names)), dtype=object)
        
        for _, row in lab_df.iterrows():
            day = row['day']
            slot_index = row['slot_index']
            
            if day in self.days and isinstance(slot_index, str) and slot_index.startswith('Lab_'):
                lab_session = slot_index.replace('Lab_', '')
                if lab_session in lab_session_names:
                    day_idx = self.days.index(day)
                    session_idx = lab_session_names.index(lab_session)
                    
                    course_code = row['course_code']
                    room_number = row['room_number']
                    room_id = row.get('room_id', '')
                    
                    # Determine room block
                    room_block = self._get_room_building_block(room_id)
                    
                    # Create display text
                    block_prefix = f"[{room_block.replace(' Block', '')}]" if room_block != 'Unknown Block' else ""
                    display_text = f"{block_prefix}{course_code}\n(P)\n{room_number}"  # P for Practical
                    grid[day_idx, session_idx] = display_text
                    block_grid[day_idx, session_idx] = room_block
        
        # Create lab time labels
        lab_time_labels = [f"{session}\n{info['time_range']}" for session, info in self.lab_sessions.items()]
        self._plot_schedule_grid(ax, grid, block_grid, lab_time_labels, 'Lab')
    
    def _plot_teacher_summary(self, ax, teacher_df, teacher_id):
        """Plot summary information for the teacher."""
        ax.axis('off')  # Turn off axes
        
        # Calculate statistics
        total_assignments = len(teacher_df)
        theory_assignments = len(teacher_df[teacher_df['slot_type'].isin(['Lecture', 'Tutorial'])])
        lab_assignments = len(teacher_df[teacher_df['slot_type'] == 'Practical'])
        
        # Calculate weekly hours (theory = 1hr, lab = 2hr per session)
        theory_hours = theory_assignments
        lab_hours = lab_assignments * 2
        total_hours = theory_hours + lab_hours
        
        # Get unique courses
        courses = teacher_df['course_code'].unique()
        course_list = ', '.join(courses)
        
        # Get unique rooms
        rooms = teacher_df['room_number'].unique()
        room_list = ', '.join(rooms)
        
        # Create summary text
        summary_text = f"""
📊 WEEKLY SCHEDULE SUMMARY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 Total Assignments: {total_assignments}
📚 Theory Classes: {theory_assignments} ({theory_hours} hours)
🔬 Lab Sessions: {lab_assignments} ({lab_hours} hours)
⏰ Total Weekly Hours: {total_hours}/21 hours
📖 Courses Taught: {course_list}
🏢 Rooms Used: {room_list}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        """
        
        # Add status indicator
        if total_hours <= 21:
            status = "✅ Within Weekly Hour Limit"
            color = 'green'
        else:
            status = "⚠️ Exceeds Weekly Hour Limit"
            color = 'red'
        
        summary_text += f"🎯 Status: {status}"
        
        # Display the text
        ax.text(0.02, 0.95, summary_text.strip(), transform=ax.transAxes, 
                fontsize=10, verticalalignment='top', fontfamily='monospace',
                bbox=dict(boxstyle="round,pad=0.5", facecolor='lightgray', alpha=0.8))
        
        # Add status indicator with color
        ax.text(0.02, 0.05, f"🎯 Status: {status}", transform=ax.transAxes,
                fontsize=12, weight='bold', color=color, verticalalignment='bottom')
    
    def _create_room_schedule(self, room_id, room_number, room_df):
        """Create a room schedule visualization."""
        if room_df.empty:
            return
        
        # Get room info
        room_info = room_df.iloc[0]
        room_type = room_info.get('room_type', 'Room')
        capacity = room_info.get('capacity', 'Unknown')
        block = room_info.get('block', 'Unknown Block')
        
        # Create figure
        fig = plt.figure(figsize=(16, 10))
        gs = GridSpec(2, 1, height_ratios=[1, 0.3], figure=fig)
        
        # Main schedule
        ax_schedule = fig.add_subplot(gs[0])
        self._plot_room_schedule_grid(ax_schedule, room_df, room_id)
        
        # Summary
        ax_summary = fig.add_subplot(gs[1])
        self._plot_room_summary(ax_summary, room_df, room_id, room_number, room_type, capacity, block)
        
        # Title
        title = f'Room Schedule: {room_number} (ID: {room_id})'
        title += f' - {room_type}, Capacity: {capacity}, {block}'
        plt.suptitle(title, fontsize=14, y=0.95)
        
        plt.tight_layout()
        
        # Save the room schedule
        filename = f'room_{room_id}_schedule.png'
        filepath = os.path.join(self.output_dir, filename)
        fig.savefig(filepath, dpi=300, bbox_inches='tight')
        plt.close(fig)
        
        print(f"Generated room schedule: {filename}")
    
    def _plot_room_schedule_grid(self, ax, room_df, room_id):
        """Plot schedule grid for a specific room."""
        # Determine if this is primarily a lab or classroom based on assignments
        lab_assignments = room_df[room_df['slot_type'] == 'Practical']
        theory_assignments = room_df[room_df['slot_type'].isin(['Lecture', 'Tutorial'])]
        
        if len(lab_assignments) > len(theory_assignments):
            # Primarily lab - use lab session structure
            lab_session_names = list(self.lab_sessions.keys())
            grid = np.empty((len(self.days), len(lab_session_names)), dtype=object)
            
            for _, row in room_df.iterrows():
                day = row['day']
                slot_index = row['slot_index']
                
                if isinstance(slot_index, str) and slot_index.startswith('Lab_'):
                    lab_session = slot_index.replace('Lab_', '')
                    if day in self.days and lab_session in lab_session_names:
                        day_idx = self.days.index(day)
                        session_idx = lab_session_names.index(lab_session)
                        
                        course_code = row['course_code']
                        teacher_id = row['teacher_id']
                        slot_type = row.get('slot_type', 'Practical')
                        
                        display_text = f"{course_code}\n{teacher_id}\n({slot_type})"
                        grid[day_idx, session_idx] = display_text
            
            # Plot with lab session labels
            lab_time_labels = [f"{session}\n{info['time_range']}" for session, info in self.lab_sessions.items()]
            self._plot_simple_grid(ax, grid, lab_time_labels, 'Lab Schedule')
            
        else:
            # Primarily classroom - use theory time slots
            grid = np.empty((len(self.days), len(self.time_slots)), dtype=object)
            
            for _, row in room_df.iterrows():
                day = row['day']
                slot_index = row['slot_index']
                
                if isinstance(slot_index, int) and day in self.days and 0 <= slot_index < len(self.time_slots):
                    day_idx = self.days.index(day)
                    
                    course_code = row['course_code']
                    teacher_id = row['teacher_id']
                    slot_type = row.get('slot_type', 'Lecture')
                    
                    display_text = f"{course_code}\n{teacher_id}\n({slot_type})"
                    grid[day_idx, slot_index] = display_text
            
            # Plot with time slot labels
            self._plot_simple_grid(ax, grid, self.time_slots, 'Theory Schedule')
    
    def _plot_simple_grid(self, ax, grid, time_labels, title):
        """Plot a simple schedule grid without complex formatting."""
        rows, cols = grid.shape
        
        # Plot the grid
        for i in range(rows):
            for j in range(cols):
                if grid[i, j] is not None:
                    # Create rectangle
                    rect = plt.Rectangle((j, rows - i - 1), 1, 1, 
                                       facecolor='lightblue', edgecolor='black', linewidth=1, alpha=0.7)
                    ax.add_patch(rect)
                    
                    # Add text
                    ax.text(j + 0.5, rows - i - 0.5, grid[i, j],
                           ha='center', va='center', fontsize=8, weight='bold')
        
        # Set axes properties
        ax.set_xlim(0, cols)
        ax.set_ylim(0, rows)
        ax.set_xticks(range(cols))
        ax.set_xticklabels(time_labels, rotation=45, ha='right', fontsize=8)
        ax.set_yticks(range(rows))
        ax.set_yticklabels([day.capitalize() for day in reversed(self.days)], fontsize=10)
        ax.grid(True, alpha=0.3)
        ax.set_title(title)
    
    def _plot_room_summary(self, ax, room_df, room_id, room_number, room_type, capacity, block):
        """Plot summary information for the room."""
        ax.axis('off')
        
        # Calculate statistics
        total_assignments = len(room_df)
        unique_teachers = len(room_df['teacher_id'].unique())
        unique_courses = len(room_df['course_code'].unique())
        
        # Get assignment breakdown
        theory_count = len(room_df[room_df['slot_type'].isin(['Lecture', 'Tutorial'])])
        lab_count = len(room_df[room_df['slot_type'] == 'Practical'])
        
        # Calculate utilization
        max_possible_slots = len(self.days) * (len(self.time_slots) if room_type == 'Classroom' else len(self.lab_sessions))
        utilization_percent = (total_assignments / max_possible_slots) * 100 if max_possible_slots > 0 else 0
        
        # Create summary text
        summary_text = f"""
📊 ROOM UTILIZATION SUMMARY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 Total Assignments: {total_assignments}
👥 Teachers Using Room: {unique_teachers}
📚 Courses Scheduled: {unique_courses}
📖 Theory Classes: {theory_count}
🔬 Lab Sessions: {lab_count}
📈 Utilization Rate: {utilization_percent:.1f}%
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        """
        
        ax.text(0.02, 0.95, summary_text.strip(), transform=ax.transAxes,
                fontsize=10, verticalalignment='top', fontfamily='monospace',
                bbox=dict(boxstyle="round,pad=0.5", facecolor='lightgray', alpha=0.8))

# Backward compatibility alias
MacroblockTimetableVisualizer = TimetableVisualizer 