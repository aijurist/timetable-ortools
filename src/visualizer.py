import os
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import numpy as np
from matplotlib.gridspec import GridSpec

class ScheduleVisualizer:
    """Visualizes timetable schedules, with a focus on lab schedules."""
    
    def __init__(self, schedule_data, output_dir):
        """Initialize the schedule visualizer."""
        self.schedule_df = pd.DataFrame(schedule_data) if schedule_data else pd.DataFrame()
        self.output_dir = output_dir
        
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
        
        if not self.schedule_df.empty:
            # Create color map for courses
            self.courses = self.schedule_df['course_code'].unique()
            colors = plt.cm.tab20(np.linspace(0, 1, len(self.courses)))
            self.course_colors = {course: mcolors.rgb2hex(color) for course, color in zip(self.courses, colors)}
            
            # Create color map for blocks/buildings
            self.building_blocks = self._analyze_building_blocks()
            self.block_colors = self._create_block_colors()
            
            # Pre-compute unique lists for efficiency - include unknown teachers
            if 'teacher_id' in self.schedule_df.columns:
                self.teachers = self.schedule_df['teacher_id'].unique()
                # Ensure unknown teachers are included
                if 'Unknown' in self.teachers:
                    print(f"Including Unknown teachers in visualization")
            else:
                self.teachers = []
            self.rooms = self.schedule_df['room_id'].unique() if 'room_id' in self.schedule_df.columns else []
        else:
            self.courses = []
            self.course_colors = {}
            self.building_blocks = {}
            self.block_colors = {}
            self.teachers = []
            self.rooms = []
    
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
        
        if not self.schedule_df.empty and 'block' in self.schedule_df.columns:
            for _, row in self.schedule_df.iterrows():
                room_id = row.get('room_id', '')
                room_number = row.get('room_number', '')
                room_type = row.get('room_type', 'Room')
                block_info = str(row.get('block', '')).strip()
                
                # Categorize based on block information
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
    
    def _create_block_colors(self):
        """Create color mapping for different building blocks."""
        block_colors = {
            'A Block': '#FF6B6B',      # Red tones
            'B Block': '#4ECDC4',      # Teal tones
            'Techlounge': '#9B59B6',   # Purple
            'J Block': '#F39C12',      # Orange
            'K Block': '#27AE60',      # Green  
            'D Block': '#3498DB',      # Blue
            'Unknown Block': '#95A5A6', # Gray
        }
        return block_colors
    
    def _get_room_block_color(self, room_id):
        """Get the color for a room based on its block."""
        # Find which block this room belongs to
        for block_name, rooms in self.building_blocks.items():
            for room in rooms:
                if room['room_id'] == room_id:
                    return self.block_colors.get(block_name, '#CCCCCC')
        return '#CCCCCC'  # Default gray
    
    def generate_visualizations(self):
        """Generate all schedule visualizations."""
        if self.schedule_df.empty:
            print("No schedule data available for visualization")
            return
        
        self.generate_lab_schedule()
        self.generate_teacher_schedules()
        self.generate_room_schedules()
        self.generate_distribution_analysis()
    
    def generate_lab_schedule(self):
        """Generate a visualization of the lab schedule."""
        if self.schedule_df.empty:
            return
        
        # Create figure
        fig, ax = plt.subplots(figsize=(16, 10))
        
        # Create a grid for days and lab sessions
        lab_session_names = list(self.lab_sessions.keys())
        grid = np.empty((len(self.days), len(lab_session_names)), dtype=object)
        block_grid = np.empty((len(self.days), len(lab_session_names)), dtype=object)
        
        # Determine if session_name is in the dataframe
        session_field = 'session_name' if 'session_name' in self.schedule_df.columns else 'slot_index'
        
        for _, row in self.schedule_df.iterrows():
            day = row['day']
            session = row[session_field]
            
            # Handle both format types (session_name='L1' or slot_index='Lab_L1')
            if isinstance(session, str) and session.startswith('Lab_'):
                session = session.replace('Lab_', '')
                
            if day in self.days and session in lab_session_names:
                day_idx = self.days.index(day)
                session_idx = lab_session_names.index(session)
                
                course_code = row['course_code']
                teacher_id = row['teacher_id']
                room_number = row['room_number']
                room_id = row.get('room_id', '')
                
                # Determine which building block this room belongs to
                block_name = 'Unknown Block'
                for b_name, rooms in self.building_blocks.items():
                    if any(r['room_id'] == room_id for r in rooms):
                        block_name = b_name
                        break
                
                # Get course instance ID and batch information
                course_instance_id = row.get('course_instance_id', '')
                is_batched = row.get('is_batched', False)
                batch_info = row.get('batch_info', '').strip()
                
                # Create display text with block information, course instance ID, and batch details
                block_prefix = f"[{block_name.replace(' Block', '')}]" if block_name != 'Unknown Block' else ""
                
                if is_batched and batch_info:
                    # Show specific batch information
                    display_text = f"{block_prefix}{course_code}\n{batch_info}\n(ID:{course_instance_id})\n{teacher_id}\n{room_number}"
                else:
                    # Regular course without batching
                    display_text = f"{block_prefix}{course_code}\n(ID:{course_instance_id})\n{teacher_id}\n{room_number}"
                
                grid[day_idx, session_idx] = display_text
                block_grid[day_idx, session_idx] = block_name
        
        # Plot the grid
        self._plot_lab_grid(ax, grid, block_grid)
        
        # Set title and save
        plt.suptitle('Lab Schedule', fontsize=16, y=0.95)
        plt.tight_layout()
        fig.savefig(os.path.join(self.output_dir, 'lab_schedule.png'), 
                   dpi=300, bbox_inches='tight')
        plt.close(fig)
    
    def _plot_lab_grid(self, ax, grid, block_grid):
        """Plot the lab schedule grid."""
        rows, cols = grid.shape
        
        # Lab time labels
        lab_time_labels = [f"{session}\n{info['time_range']}" for session, info in self.lab_sessions.items()]
        
        # Plot the grid
        for i in range(rows):
            for j in range(cols):
                if grid[i, j] is not None:
                    room_block = block_grid[i, j]
                    
                    # Use block-based background color
                    bg_color = self.block_colors.get(room_block, '#FFFFFF')
                    
                    # Create rectangle with block-based background
                    rect = plt.Rectangle((j, rows - i - 1), 1, 1, 
                                       facecolor=bg_color, edgecolor='black', linewidth=1.5, alpha=0.8)
                    ax.add_patch(rect)
                    
                    # Add text
                    ax.text(j + 0.5, rows - i - 0.5, grid[i, j],
                           ha='center', va='center', fontsize=8, weight='bold',
                           bbox=dict(boxstyle="round,pad=0.1", facecolor='white', alpha=0.9))
        
        # Set axes properties
        ax.set_xlim(0, cols)
        ax.set_ylim(0, rows)
        ax.set_xticks(range(cols))
        ax.set_xticklabels(lab_time_labels, rotation=45, ha='right', fontsize=9)
        ax.set_yticks(range(rows))
        ax.set_yticklabels([day.capitalize() for day in reversed(self.days)], fontsize=10)
        ax.grid(True, alpha=0.3)
        
        # Add legend
        self._add_block_legend(ax)
    
    def _add_block_legend(self, ax):
        """Add a legend showing building block color coding."""
        from matplotlib.patches import Patch
        
        legend_elements = []
        
        # Add block color legend
        for block_name, color in self.block_colors.items():
            if any(self.building_blocks.get(block_name, [])):
                legend_elements.append(Patch(facecolor=color, edgecolor='black', label=block_name))
        
        if legend_elements:
            ax.legend(handles=legend_elements, loc='upper left', bbox_to_anchor=(1.02, 1), 
                     title='Building Blocks', fontsize=10)
    
    def generate_teacher_schedules(self):
        """Generate detailed schedule visualizations and summaries for each teacher."""
        if 'teacher_id' not in self.schedule_df.columns:
            print("No teacher information available for visualization")
            return
            
        print(f"Generating detailed teacher schedules for {len(self.teachers)} teachers...")
        
        for teacher in self.teachers:
            teacher_df = self.schedule_df[self.schedule_df['teacher_id'] == teacher]
            if not teacher_df.empty:
                self._create_teacher_schedule(teacher, teacher_df)
        
        # Generate overall teacher statistics
        self._generate_teacher_statistics()
    
    def _create_teacher_schedule(self, teacher_id, teacher_df):
        """Create a detailed schedule visualization for a specific teacher with student counts and batch info."""
        if teacher_df.empty:
            return
        
        # Get teacher info
        teacher_info = teacher_df.iloc[0]
        teacher_name = f"{teacher_info.get('first_name', '')} {teacher_info.get('last_name', '')}".strip()
        if not teacher_name and 'teacher_name' in teacher_info:
            teacher_name = teacher_info['teacher_name']
        staff_code = teacher_info.get('staff_code', '')
        
        # Create figure with larger size for detailed information
        fig, ax = plt.subplots(figsize=(20, 12))
        
        # Determine if session_name is in the dataframe
        session_field = 'session_name' if 'session_name' in self.schedule_df.columns else 'slot_index'
        
        # Create a grid for days and lab sessions
        lab_session_names = list(self.lab_sessions.keys())
        grid = np.empty((len(self.days), len(lab_session_names)), dtype=object)
        block_grid = np.empty((len(self.days), len(lab_session_names)), dtype=object)
        
        # Group by session to handle batching properly
        session_groups = teacher_df.groupby(['day', session_field])
        
        for (day, session), group in session_groups:
            # Handle both format types (session_name='L1' or slot_index='Lab_L1')
            if isinstance(session, str) and session.startswith('Lab_'):
                session = session.replace('Lab_', '')
                
            if day in self.days and session in lab_session_names:
                day_idx = self.days.index(day)
                session_idx = lab_session_names.index(session)
                
                # Handle multiple batches in the same session - show each batch separately
                if len(group) > 1 or group.iloc[0].get('is_batched', False):
                    # Multiple entries or batched course - show specific batch details
                    batch_details = []
                    total_students_session = 0
                    
                    for _, batch_row in group.iterrows():
                        batch_info = batch_row.get('batch_info', '').strip()
                        student_count = batch_row.get('student_count', 0)
                        
                        if batch_info:
                            batch_details.append(f"{batch_info}: {student_count} students")
                        else:
                            batch_details.append(f"Students: {student_count}")
                        total_students_session += student_count
                    
                    # Get common information from first row
                    first_row = group.iloc[0]
                    course_code = first_row['course_code']
                    room_number = first_row['room_number']
                    room_id = first_row.get('room_id', '')
                    capacity = first_row.get('capacity', 'N/A')
                    course_instance_id = first_row.get('course_instance_id', '')
                    total_students = first_row.get('total_students', total_students_session)
                    
                    # Determine which building block this room belongs to
                    block_name = 'Unknown Block'
                    for b_name, rooms in self.building_blocks.items():
                        if any(r['room_id'] == room_id for r in rooms):
                            block_name = b_name
                            break
                    
                    # Create detailed display text
                    block_prefix = f"[{block_name.replace(' Block', '')}]" if block_name != 'Unknown Block' else ""
                    
                    display_text = f"{block_prefix}{course_code}\n"
                    display_text += f"(ID:{course_instance_id})\n"
                    display_text += f"Room: {room_number} (Cap: {capacity})\n"
                    display_text += f"Total Students: {total_students}\n"
                    display_text += f"{'; '.join(batch_details)}"
                    
                else:
                    # Single entry, non-batched course
                    first_row = group.iloc[0]
                    course_code = first_row['course_code']
                    room_number = first_row['room_number']
                    room_id = first_row.get('room_id', '')
                    capacity = first_row.get('capacity', 'N/A')
                    course_instance_id = first_row.get('course_instance_id', '')
                    student_count = first_row.get('student_count', 0)
                    total_students = first_row.get('total_students', student_count)
                    
                    # Determine which building block this room belongs to
                    block_name = 'Unknown Block'
                    for b_name, rooms in self.building_blocks.items():
                        if any(r['room_id'] == room_id for r in rooms):
                            block_name = b_name
                            break
                    
                    # Create detailed display text
                    block_prefix = f"[{block_name.replace(' Block', '')}]" if block_name != 'Unknown Block' else ""
                    
                    display_text = f"{block_prefix}{course_code}\n"
                    display_text += f"(ID:{course_instance_id})\n"
                    display_text += f"Room: {room_number} (Cap: {capacity})\n"
                    display_text += f"Students: {student_count}\n"
                    display_text += f"Batching: No"
                
                grid[day_idx, session_idx] = display_text
                block_grid[day_idx, session_idx] = block_name
        
        # Plot the detailed grid
        self._plot_detailed_teacher_grid(ax, grid, block_grid)
        
        # Set title and save
        title = f'Detailed Teacher Lab Schedule: {teacher_name}'
        if staff_code:
            title += f' ({staff_code})'
        title += f' - ID: {teacher_id}'
        
        plt.suptitle(title, fontsize=18, y=0.96)
        plt.tight_layout()
        
        # Save the teacher schedule
        filename = f'teacher_{teacher_id}_detailed_schedule.png'
        filepath = os.path.join(self.output_dir, filename)
        fig.savefig(filepath, dpi=300, bbox_inches='tight')
        plt.close(fig)
        
        print(f"Generated detailed teacher schedule: {filename}")
        
        # Also generate a summary text file for this teacher
        self._generate_teacher_summary(teacher_id, teacher_name, staff_code, teacher_df)
    
    def _plot_detailed_teacher_grid(self, ax, grid, block_grid):
        """Plot the detailed teacher schedule grid with enhanced formatting."""
        rows, cols = grid.shape
        
        # Lab time labels with session names
        lab_time_labels = [f"{session}\n{info['time_range']}" for session, info in self.lab_sessions.items()]
        
        # Plot the grid
        for i in range(rows):
            for j in range(cols):
                if grid[i, j] is not None:
                    room_block = block_grid[i, j]
                    
                    # Use block-based background color
                    bg_color = self.block_colors.get(room_block, '#FFFFFF')
                    
                    # Create rectangle with block-based background
                    rect = plt.Rectangle((j, rows - i - 1), 1, 1, 
                                       facecolor=bg_color, edgecolor='black', linewidth=2, alpha=0.8)
                    ax.add_patch(rect)
                    
                    # Add text with better formatting
                    ax.text(j + 0.5, rows - i - 0.5, grid[i, j],
                           ha='center', va='center', fontsize=9, weight='bold',
                           bbox=dict(boxstyle="round,pad=0.15", facecolor='white', alpha=0.95))
        
        # Set axes properties
        ax.set_xlim(0, cols)
        ax.set_ylim(0, rows)
        ax.set_xticks(range(cols))
        ax.set_xticklabels(lab_time_labels, rotation=45, ha='right', fontsize=11)
        ax.set_yticks(range(rows))
        ax.set_yticklabels([day.capitalize() for day in reversed(self.days)], fontsize=12)
        ax.grid(True, alpha=0.3)
        
        # Add legend
        self._add_detailed_legend(ax)
    
    def _add_detailed_legend(self, ax):
        """Add a detailed legend for teacher schedules."""
        from matplotlib.patches import Patch
        
        legend_elements = []
        
        # Add block color legend
        for block_name, color in self.block_colors.items():
            if any(self.building_blocks.get(block_name, [])):
                legend_elements.append(Patch(facecolor=color, edgecolor='black', label=block_name))
        
        if legend_elements:
            # Add explanation text
            legend_elements.append(Patch(facecolor='white', edgecolor='white', label=''))
            legend_elements.append(Patch(facecolor='white', edgecolor='white', label='Legend:'))
            legend_elements.append(Patch(facecolor='white', edgecolor='white', label='- Batching indicates multiple'))
            legend_elements.append(Patch(facecolor='white', edgecolor='white', label='  student groups per session'))
            legend_elements.append(Patch(facecolor='white', edgecolor='white', label='- Cap = Room Capacity'))
            
            ax.legend(handles=legend_elements, loc='upper left', bbox_to_anchor=(1.02, 1), 
                     title='Building Blocks & Info', fontsize=10, title_fontsize=12)
    
    def _generate_teacher_summary(self, teacher_id, teacher_name, staff_code, teacher_df):
        """Generate a detailed text summary for a teacher's lab schedule."""
        summary_filename = f'teacher_{teacher_id}_lab_summary.txt'
        summary_path = os.path.join(self.output_dir, summary_filename)
        
        with open(summary_path, 'w') as f:
            f.write(f"LAB SCHEDULE SUMMARY\n")
            f.write(f"===================\n\n")
            f.write(f"Teacher: {teacher_name}\n")
            if staff_code:
                f.write(f"Staff Code: {staff_code}\n")
            f.write(f"Teacher ID: {teacher_id}\n\n")
            
            # Calculate statistics
            session_field = 'session_name' if 'session_name' in teacher_df.columns else 'slot_index'
            total_sessions = len(teacher_df.groupby(['day', session_field]))
            total_students = teacher_df['total_students'].sum() if 'total_students' in teacher_df.columns else 0
            unique_courses = teacher_df['course_code'].nunique()
            unique_rooms = teacher_df['room_number'].nunique()
            
            f.write(f"OVERVIEW:\n")
            f.write(f"- Total Lab Sessions: {total_sessions}\n")
            f.write(f"- Total Students (across all sessions): {total_students}\n")
            f.write(f"- Unique Courses: {unique_courses}\n")
            f.write(f"- Unique Rooms Used: {unique_rooms}\n\n")
            
            # Group by course for detailed breakdown
            f.write(f"COURSE BREAKDOWN:\n")
            f.write(f"-" * 50 + "\n")
            
            course_groups = teacher_df.groupby('course_code')
            
            for course_code, course_group in course_groups:
                f.write(f"\nCourse: {course_code}\n")
                
                # Get course details
                first_row = course_group.iloc[0]
                practical_hours = first_row.get('practical_hours', 'N/A')
                total_students_course = first_row.get('total_students', 0)
                is_batched = first_row.get('is_batched', False)
                
                f.write(f"  Practical Hours: {practical_hours}\n")
                f.write(f"  Total Students: {total_students_course}\n")
                f.write(f"  Batched: {'Yes' if is_batched else 'No'}\n")
                
                # List all sessions for this course
                session_groups = course_group.groupby(['day', session_field])
                f.write(f"  Lab Sessions:\n")
                
                for (day, session), session_group in session_groups:
                    session_display = session.replace('Lab_', '') if isinstance(session, str) and session.startswith('Lab_') else session
                    time_range = self.lab_sessions.get(session_display, {}).get('time_range', 'Unknown time')
                    
                    room_info = session_group.iloc[0]
                    room_number = room_info['room_number']
                    room_capacity = room_info.get('capacity', 'N/A')
                    block = room_info.get('block', 'Unknown')
                    
                    f.write(f"    • {day.capitalize()} {session_display} ({time_range})\n")
                    f.write(f"      Room: {room_number} (Capacity: {room_capacity}, {block})\n")
                    
                    if is_batched:
                        # Show detailed batch information
                        batch_details = []
                        for _, batch_row in session_group.iterrows():
                            batch_info = batch_row.get('batch_info', '').strip()
                            student_count = batch_row.get('student_count', 0)
                            if batch_info:
                                batch_details.append(f"{batch_info}: {student_count} students")
                            else:
                                batch_details.append(f"Unnamed batch: {student_count} students")
                        
                        f.write(f"      Batch Details: {'; '.join(batch_details)}\n")
                    else:
                        student_count = session_group.iloc[0].get('student_count', 0)
                        f.write(f"      Students: {student_count}\n")
            
            # Weekly schedule table
            f.write(f"\n\nWEEKLY SCHEDULE TABLE:\n")
            f.write(f"=" * 80 + "\n")
            f.write(f"{'Day':<10} {'Session':<8} {'Time':<15} {'Course':<10} {'Room':<10} {'Batch Info':<20} {'Students':<10}\n")
            f.write(f"-" * 95 + "\n")
            
            # Sort by day and session for clean display
            day_order = {day: i for i, day in enumerate(self.days)}
            session_order = {session: i for i, session in enumerate(self.lab_sessions.keys())}
            
            schedule_rows = []
            session_groups = teacher_df.groupby(['day', session_field])
            
            for (day, session), group in session_groups:
                session_display = session.replace('Lab_', '') if isinstance(session, str) and session.startswith('Lab_') else session
                time_range = self.lab_sessions.get(session_display, {}).get('time_range', 'Unknown')
                
                row_info = group.iloc[0]
                course_code = row_info['course_code']
                room_number = row_info['room_number']
                is_batched = row_info.get('is_batched', False)
                
                if is_batched:
                    # Show specific batch details
                    batch_details = []
                    total_students = 0
                    for _, batch_row in group.iterrows():
                        batch_info = batch_row.get('batch_info', '').strip()
                        student_count = batch_row.get('student_count', 0)
                        if batch_info:
                            batch_details.append(f"{batch_info}({student_count})")
                        else:
                            batch_details.append(f"Batch({student_count})")
                        total_students += student_count
                    
                    batch_display = "; ".join(batch_details)
                    student_display = str(total_students)
                else:
                    student_count = row_info.get('student_count', 0)
                    batch_display = "No batching"
                    student_display = str(student_count)
                
                schedule_rows.append((
                    day_order.get(day, 999),
                    session_order.get(session_display, 999),
                    day, session_display, time_range, course_code, room_number, batch_display, student_display
                ))
            
            # Sort and write rows
            schedule_rows.sort(key=lambda x: (x[0], x[1]))
            for _, _, day, session, time_range, course, room, batch_info, students in schedule_rows:
                f.write(f"{day.capitalize():<10} {session:<8} {time_range:<15} {course:<10} {room:<10} {batch_info:<20} {students:<10}\n")
        
        print(f"Generated teacher summary: {summary_filename}")
    
    def _generate_teacher_statistics(self):
        """Generate overall teacher statistics summary."""
        stats_filename = 'all_teachers_statistics.txt'
        stats_path = os.path.join(self.output_dir, stats_filename)
        
        with open(stats_path, 'w') as f:
            f.write(f"OVERALL TEACHER LAB STATISTICS\n")
            f.write(f"=============================\n\n")
            
            session_field = 'session_name' if 'session_name' in self.schedule_df.columns else 'slot_index'
            
            # Overall statistics
            total_teachers = len(self.teachers)
            total_sessions = len(self.schedule_df.groupby(['teacher_id', 'day', session_field]))
            total_students_all = self.schedule_df['total_students'].sum() if 'total_students' in self.schedule_df.columns else 0
            unique_courses = self.schedule_df['course_code'].nunique()
            unique_rooms = self.schedule_df['room_number'].nunique()
            
            f.write(f"SUMMARY:\n")
            f.write(f"- Total Teachers with Lab Sessions: {total_teachers}\n")
            f.write(f"- Total Lab Sessions Scheduled: {total_sessions}\n")
            f.write(f"- Total Student Enrollments: {total_students_all}\n")
            f.write(f"- Unique Courses with Labs: {unique_courses}\n")
            f.write(f"- Unique Lab Rooms Used: {unique_rooms}\n\n")
            
            # Teacher breakdown
            f.write(f"TEACHER BREAKDOWN:\n")
            f.write(f"-" * 80 + "\n")
            f.write(f"{'Teacher ID':<12} {'Name':<25} {'Sessions':<10} {'Students':<10} {'Courses':<8} {'Rooms':<8}\n")
            f.write(f"-" * 80 + "\n")
            
            teacher_stats = []
            for teacher_id in self.teachers:
                teacher_df = self.schedule_df[self.schedule_df['teacher_id'] == teacher_id]
                
                # Get teacher info
                teacher_info = teacher_df.iloc[0]
                teacher_name = f"{teacher_info.get('first_name', '')} {teacher_info.get('last_name', '')}".strip()
                if not teacher_name and 'teacher_name' in teacher_info:
                    teacher_name = teacher_info['teacher_name']
                if not teacher_name:
                    teacher_name = 'Unknown'
                
                # Calculate stats
                sessions = len(teacher_df.groupby(['day', session_field]))
                students = teacher_df['total_students'].sum() if 'total_students' in teacher_df.columns else 0
                courses = teacher_df['course_code'].nunique()
                rooms = teacher_df['room_number'].nunique()
                
                teacher_stats.append((sessions, students, teacher_id, teacher_name, courses, rooms))
                
                # Truncate name if too long
                display_name = teacher_name[:23] + '..' if len(teacher_name) > 25 else teacher_name
                
                f.write(f"{teacher_id:<12} {display_name:<25} {sessions:<10} {students:<10} {courses:<8} {rooms:<8}\n")
            
            # Sort teachers by number of sessions for additional insights
            teacher_stats.sort(reverse=True)
            
            f.write(f"\n\nTOP TEACHERS BY LAB SESSIONS:\n")
            f.write(f"-" * 50 + "\n")
            for sessions, students, teacher_id, teacher_name, courses, rooms in teacher_stats[:10]:
                f.write(f"{teacher_name} (ID: {teacher_id}): {sessions} sessions, {students} students\n")
            
            # Course distribution
            f.write(f"\n\nCOURSE DISTRIBUTION:\n")
            f.write(f"-" * 50 + "\n")
            course_counts = self.schedule_df['course_code'].value_counts()
            for course, count in course_counts.head(10).items():
                # Get course details
                course_df = self.schedule_df[self.schedule_df['course_code'] == course]
                total_students_course = course_df['total_students'].iloc[0] if 'total_students' in course_df.columns else 0
                practical_hours = course_df['practical_hours'].iloc[0] if 'practical_hours' in course_df.columns else 0
                
                f.write(f"{course}: {count} time slots, {total_students_course} students, {practical_hours}h practical\n")
            
            # Room utilization
            f.write(f"\n\nROOM UTILIZATION:\n")
            f.write(f"-" * 50 + "\n")
            room_counts = self.schedule_df['room_number'].value_counts()
            for room, count in room_counts.head(10).items():
                # Get room details
                room_df = self.schedule_df[self.schedule_df['room_number'] == room]
                capacity = room_df['capacity'].iloc[0] if 'capacity' in room_df.columns else 'N/A'
                block = room_df['block'].iloc[0] if 'block' in room_df.columns else 'Unknown'
                
                f.write(f"{room} ({block}): {count} time slots, capacity {capacity}\n")
        
        print(f"Generated teacher statistics: {stats_filename}")
    
    def generate_room_schedules(self):
        """Generate schedule visualizations for each room."""
        if 'room_id' not in self.schedule_df.columns:
            print("No room information available for visualization")
            return
            
        for room_id in self.rooms:
            room_df = self.schedule_df[self.schedule_df['room_id'] == room_id]
            if not room_df.empty:
                room_number = room_df.iloc[0]['room_number']
                self._create_room_schedule(room_id, room_number, room_df)
    
    def _create_room_schedule(self, room_id, room_number, room_df):
        """Create a schedule visualization for a specific room."""
        if room_df.empty:
            return
        
        # Get room info
        room_info = room_df.iloc[0]
        capacity = room_info.get('capacity', 'Unknown')
        block = room_info.get('block', 'Unknown Block')
        
        # Create figure
        fig, ax = plt.subplots(figsize=(16, 10))
        
        # Determine if session_name is in the dataframe
        session_field = 'session_name' if 'session_name' in self.schedule_df.columns else 'slot_index'
        
        # Create a grid for days and lab sessions
        lab_session_names = list(self.lab_sessions.keys())
        grid = np.empty((len(self.days), len(lab_session_names)), dtype=object)
        
        for _, row in room_df.iterrows():
            day = row['day']
            session = row[session_field]
            
            # Handle both format types (session_name='L1' or slot_index='Lab_L1')
            if isinstance(session, str) and session.startswith('Lab_'):
                session = session.replace('Lab_', '')
                
            if day in self.days and session in lab_session_names:
                day_idx = self.days.index(day)
                session_idx = lab_session_names.index(session)
                
                course_code = row['course_code']
                teacher_id = row['teacher_id']
                course_instance_id = row.get('course_instance_id', '')
                is_batched = row.get('is_batched', False)
                batch_info = row.get('batch_info', '').strip()
                
                # Create display text with course instance ID and batch information
                if is_batched and batch_info:
                    display_text = f"{course_code}\n{batch_info}\n(ID:{course_instance_id})\n{teacher_id}"
                else:
                    display_text = f"{course_code}\n(ID:{course_instance_id})\n{teacher_id}"
                
                grid[day_idx, session_idx] = display_text
        
        # Plot the grid
        lab_time_labels = [f"{session}\n{info['time_range']}" for session, info in self.lab_sessions.items()]
        self._plot_simple_grid(ax, grid, lab_time_labels)
        
        # Set title and save
        title = f'Room Schedule: {room_number} (ID: {room_id})'
        title += f' - Capacity: {capacity}, {block}'
        
        plt.suptitle(title, fontsize=16, y=0.95)
        plt.tight_layout()
        
        # Save the room schedule
        filename = f'room_{room_id}_schedule.png'
        filepath = os.path.join(self.output_dir, filename)
        fig.savefig(filepath, dpi=300, bbox_inches='tight')
        plt.close(fig)
        
        print(f"Generated room schedule: {filename}")
    
    def _plot_simple_grid(self, ax, grid, time_labels):
        """Plot a simple schedule grid."""
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
                           ha='center', va='center', fontsize=9, weight='bold')
        
        # Set axes properties
        ax.set_xlim(0, cols)
        ax.set_ylim(0, rows)
        ax.set_xticks(range(cols))
        ax.set_xticklabels(time_labels, rotation=45, ha='right', fontsize=9)
        ax.set_yticks(range(rows))
        ax.set_yticklabels([day.capitalize() for day in reversed(self.days)], fontsize=10)
        ax.grid(True, alpha=0.3)
    
    def generate_distribution_analysis(self):
        """Generate visualizations showing the distribution of the schedule."""
        if self.schedule_df.empty:
            return
        
        # Create figure with subplots
        fig = plt.figure(figsize=(16, 12))
        gs = GridSpec(2, 2, figure=fig)
        
        # Daily distribution
        ax1 = fig.add_subplot(gs[0, 0])
        self._plot_daily_distribution(ax1)
        
        # Session distribution
        ax2 = fig.add_subplot(gs[0, 1])
        self._plot_session_distribution(ax2)
        
        # Course distribution
        ax3 = fig.add_subplot(gs[1, 0])
        self._plot_course_distribution(ax3)
        
        # Building block distribution
        ax4 = fig.add_subplot(gs[1, 1])
        self._plot_block_distribution(ax4)
        
        plt.suptitle('Lab Schedule Distribution Analysis', fontsize=16, y=0.95)
        plt.tight_layout()
        
        # Save the distribution analysis
        filepath = os.path.join(self.output_dir, 'lab_distribution_analysis.png')
        fig.savefig(filepath, dpi=300, bbox_inches='tight')
        plt.close(fig)
        
        print(f"Generated distribution analysis: {filepath}")
    
    def _plot_daily_distribution(self, ax):
        """Plot the distribution of lab sessions by day."""
        # Count sessions by day
        day_counts = self.schedule_df['day'].value_counts().reindex(self.days, fill_value=0)
        
        # Plot the distribution
        bars = ax.bar(range(len(self.days)), day_counts.values)
        
        # Color the bars with a gradient
        colors = plt.cm.viridis(np.linspace(0, 1, len(self.days)))
        for bar, color in zip(bars, colors):
            bar.set_color(color)
        
        # Add labels and title
        ax.set_xticks(range(len(self.days)))
        ax.set_xticklabels([day.capitalize() for day in self.days], rotation=45)
        ax.set_ylabel('Number of Sessions')
        ax.set_title('Lab Sessions by Day')
    
    def _plot_session_distribution(self, ax):
        """Plot the distribution of lab sessions by time slot."""
        # Determine if session_name is in the dataframe
        session_field = 'session_name' if 'session_name' in self.schedule_df.columns else 'slot_index'
        
        # Process the session names if needed
        if session_field == 'slot_index':
            self.schedule_df['session'] = self.schedule_df[session_field].apply(
                lambda x: x.replace('Lab_', '') if isinstance(x, str) and x.startswith('Lab_') else x
            )
            session_field = 'session'
        
        # Count sessions by time slot
        session_counts = self.schedule_df[session_field].value_counts()
        
        # Ensure all lab sessions are included
        lab_session_names = list(self.lab_sessions.keys())
        for session in lab_session_names:
            if session not in session_counts:
                session_counts[session] = 0
        
        # Sort by lab session order
        session_counts = session_counts.reindex(lab_session_names, fill_value=0)
        
        # Plot the distribution
        bars = ax.bar(range(len(session_counts)), session_counts.values)
        
        # Color the bars with a gradient
        colors = plt.cm.plasma(np.linspace(0, 1, len(session_counts)))
        for bar, color in zip(bars, colors):
            bar.set_color(color)
        
        # Add labels and title
        ax.set_xticks(range(len(session_counts)))
        session_labels = [f"{session}\n{self.lab_sessions[session]['time_range']}" 
                         for session in session_counts.index]
        ax.set_xticklabels(session_labels, rotation=45)
        ax.set_ylabel('Number of Sessions')
        ax.set_title('Lab Sessions by Time Slot')
    
    def _plot_course_distribution(self, ax):
        """Plot the distribution of lab sessions by course."""
        # Count sessions by course
        course_counts = self.schedule_df['course_code'].value_counts().nlargest(10)
        
        # Plot the distribution
        bars = ax.bar(range(len(course_counts)), course_counts.values)
        
        # Color the bars using course colors
        for i, course in enumerate(course_counts.index):
            bars[i].set_color(self.course_colors.get(course, '#CCCCCC'))
        
        # Add labels and title
        ax.set_xticks(range(len(course_counts)))
        ax.set_xticklabels(course_counts.index, rotation=45)
        ax.set_ylabel('Number of Sessions')
        ax.set_title('Top 10 Courses by Lab Sessions')
    
    def _plot_block_distribution(self, ax):
        """Plot the distribution of lab sessions by building block."""
        # Determine the block for each session
        if 'block' in self.schedule_df.columns:
            block_counts = self.schedule_df['block'].value_counts()
            
            # Plot the distribution
            bars = ax.bar(range(len(block_counts)), block_counts.values)
            
            # Color the bars using block colors
            for i, block in enumerate(block_counts.index):
                block_name = block if block in self.block_colors else 'Unknown Block'
                bars[i].set_color(self.block_colors.get(block_name, '#CCCCCC'))
            
            # Add labels and title
            ax.set_xticks(range(len(block_counts)))
            ax.set_xticklabels(block_counts.index, rotation=45)
            ax.set_ylabel('Number of Sessions')
            ax.set_title('Lab Sessions by Building Block')
        else:
            ax.text(0.5, 0.5, 'No building block information available',
                   ha='center', va='center', transform=ax.transAxes)


# Function to visualize a lab schedule from a file
def visualize_lab_schedule(schedule_file, output_dir=None):
    """Visualize a lab schedule from a file."""
    import json
    
    # Determine the file type (CSV or JSON)
    if schedule_file.endswith('.csv'):
        schedule_df = pd.read_csv(schedule_file)
        schedule_data = schedule_df.to_dict('records')
    elif schedule_file.endswith('.json'):
        with open(schedule_file, 'r') as f:
            schedule_data = json.load(f)
    else:
        raise ValueError(f"Unsupported file format: {schedule_file}")
    
    # Determine output directory
    if output_dir is None:
        output_dir = os.path.join(os.path.dirname(schedule_file), 'visualizations')
        os.makedirs(output_dir, exist_ok=True)
    
    # Create the visualizer and generate visualizations
    visualizer = ScheduleVisualizer(schedule_data, output_dir)
    visualizer.generate_visualizations()
    
    return output_dir

class TheoryScheduleVisualizer:
    """Visualizes theory timetable schedules."""
    
    def __init__(self, schedule_data, output_dir):
        """Initialize the theory schedule visualizer."""
        self.schedule_df = pd.DataFrame(schedule_data) if schedule_data else pd.DataFrame()
        self.output_dir = output_dir
        
        # Timetable days structure
        self.days = ["tuesday", "wed", "thur", "fri", "sat"]
        
        # Theory time slots (11 slots per day - 1 hour each)
        self.theory_time_slots = [
            "8:00 - 8:50", "9:00 - 9:50", "10:00 - 10:50", "11:00 - 11:50",
            "12:00 - 12:50", "1:00 - 1:50", "2:00 - 2:50", "3:00 - 3:50", 
            "4:00 - 4:50", "5:00 - 5:50", "6:00 - 6:50"
        ]
        
        if not self.schedule_df.empty:
            # Create color map for courses
            self.courses = self.schedule_df['course_code'].unique()
            colors = plt.cm.Set3(np.linspace(0, 1, len(self.courses)))
            self.course_colors = {course: mcolors.rgb2hex(color) for course, color in zip(self.courses, colors)}
            
            # Create color map for blocks/buildings
            self.building_blocks = self._analyze_building_blocks()
            self.block_colors = self._create_block_colors()
            
            # Pre-compute unique lists for efficiency
            if 'teacher_id' in self.schedule_df.columns:
                self.teachers = self.schedule_df['teacher_id'].unique()
            else:
                self.teachers = []
            self.rooms = self.schedule_df['room_id'].unique() if 'room_id' in self.schedule_df.columns else []
        else:
            self.courses = []
            self.course_colors = {}
            self.building_blocks = {}
            self.block_colors = {}
            self.teachers = []
            self.rooms = []
    
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
        
        if not self.schedule_df.empty and 'block' in self.schedule_df.columns:
            for _, row in self.schedule_df.iterrows():
                room_id = row.get('room_id', '')
                room_number = row.get('room_number', '')
                block_info = str(row.get('block', '')).strip()
                
                # Categorize based on block information
                room_entry = {
                    'room_id': room_id,
                    'room_number': room_number,
                    'room_type': 'Theory Room',
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
    
    def _create_block_colors(self):
        """Create color mapping for different building blocks."""
        block_colors = {
            'A Block': '#FFB3BA',      # Light red tones
            'B Block': '#BAFFC9',      # Light green tones
            'Techlounge': '#D4BAFF',   # Light purple
            'J Block': '#FFFFBA',      # Light yellow
            'K Block': '#BAE1FF',      # Light blue  
            'D Block': '#FFDFBA',      # Light orange
            'Unknown Block': '#E6E6E6', # Light gray
        }
        return block_colors
    
    def _get_room_block_color(self, room_id):
        """Get the color for a room based on its block."""
        # Find which block this room belongs to
        for block_name, rooms in self.building_blocks.items():
            for room in rooms:
                if room['room_id'] == room_id:
                    return self.block_colors.get(block_name, '#CCCCCC')
        return '#CCCCCC'  # Default gray
    
    def generate_visualizations(self):
        """Generate all theory schedule visualizations."""
        if self.schedule_df.empty:
            print("No theory schedule data available for visualization")
            return self.output_dir
        
        self.generate_theory_schedule()
        self.generate_teacher_schedules()
        self.generate_room_schedules()
        self.generate_distribution_analysis()
        return self.output_dir
    
    def generate_theory_schedule(self):
        """Generate a visualization of the theory schedule."""
        if self.schedule_df.empty:
            return
        
        # Create figure
        fig, ax = plt.subplots(figsize=(18, 12))
        
        # Create a grid for days and theory time slots
        grid = np.empty((len(self.days), len(self.theory_time_slots)), dtype=object)
        block_grid = np.empty((len(self.days), len(self.theory_time_slots)), dtype=object)
        
        for _, row in self.schedule_df.iterrows():
            day = row['day']
            slot_idx = row.get('slot_index', 0)
            
            if day in self.days and 0 <= slot_idx < len(self.theory_time_slots):
                day_idx = self.days.index(day)
                
                course_code = row['course_code']
                teacher_id = row['teacher_id']
                room_number = row['room_number']
                room_id = row.get('room_id', '')
                
                # Determine which building block this room belongs to
                block_name = 'Unknown Block'
                for b_name, rooms in self.building_blocks.items():
                    if any(r['room_id'] == room_id for r in rooms):
                        block_name = b_name
                        break
                
                # Create display text with block information
                block_prefix = f"[{block_name.replace(' Block', '')}]" if block_name != 'Unknown Block' else ""
                
                # Get group information for better display
                group_info = row.get('group_name', 'Unknown Group')
                group_display = group_info.split('_')[-1] if '_' in group_info else group_info
                
                display_text = f"{block_prefix} {course_code}\nT{teacher_id} | {room_number}\n{group_display}"
                
                grid[day_idx, slot_idx] = display_text
                block_grid[day_idx, slot_idx] = block_name
        
        # Plot the grid
        self._plot_theory_grid(ax, grid, block_grid)
        
        # Add title and labels
        ax.set_title('Theory Schedule Overview', fontsize=16, fontweight='bold', pad=20)
        ax.set_xlabel('Time Slots', fontsize=12, fontweight='bold')
        ax.set_ylabel('Days', fontsize=12, fontweight='bold')
        
        # Set axis labels
        ax.set_xticks(range(len(self.theory_time_slots)))
        ax.set_xticklabels(self.theory_time_slots, rotation=45, ha='right')
        ax.set_yticks(range(len(self.days)))
        ax.set_yticklabels([day.capitalize() for day in self.days])
        
        # Add block legend
        self._add_block_legend(ax)
        
        # Adjust layout and save
        plt.tight_layout()
        theory_schedule_path = os.path.join(self.output_dir, 'theory_schedule_overview.png')
        plt.savefig(theory_schedule_path, dpi=300, bbox_inches='tight')
        plt.close()
        
        print(f"Theory schedule overview saved to: {theory_schedule_path}")
    
    def _plot_theory_grid(self, ax, grid, block_grid):
        """Plot the theory schedule grid with appropriate colors."""
        for i in range(len(self.days)):
            for j in range(len(self.theory_time_slots)):
                # Get the content and block color
                content = grid[i, j]
                block_name = block_grid[i, j]
                
                if content is not None:
                    # Get background color based on block
                    bg_color = self.block_colors.get(block_name, '#F0F0F0')
                    
                    # Create rectangle with block color
                    rect = plt.Rectangle((j-0.4, i-0.4), 0.8, 0.8, 
                                       facecolor=bg_color, edgecolor='black', linewidth=1)
                    ax.add_patch(rect)
                    
                    # Add text content
                    ax.text(j, i, content, ha='center', va='center', 
                           fontsize=8, fontweight='bold', 
                           bbox=dict(boxstyle="round,pad=0.1", facecolor='white', alpha=0.8))
                else:
                    # Empty slot
                    rect = plt.Rectangle((j-0.4, i-0.4), 0.8, 0.8, 
                                       facecolor='#FFFFFF', edgecolor='lightgray', linewidth=0.5)
                    ax.add_patch(rect)
        
        ax.set_xlim(-0.5, len(self.theory_time_slots) - 0.5)
        ax.set_ylim(-0.5, len(self.days) - 0.5)
        ax.set_aspect('equal')
    
    def _add_block_legend(self, ax):
        """Add legend for building blocks."""
        legend_elements = []
        for block_name, color in self.block_colors.items():
            if any(block_name in str(block_grid) for block_grid in [self.building_blocks]):
                legend_elements.append(plt.Rectangle((0, 0), 1, 1, facecolor=color, label=block_name))
        
        if legend_elements:
            ax.legend(handles=legend_elements, loc='center left', bbox_to_anchor=(1, 0.5), 
                     title="Building Blocks", title_fontsize=10, fontsize=9)
    
    def generate_teacher_schedules(self):
        """Generate individual teacher schedule visualizations."""
        if self.schedule_df.empty or len(self.teachers) == 0:
            return
        
        teacher_stats = []
        
        for teacher_id in self.teachers:
            teacher_df = self.schedule_df[self.schedule_df['teacher_id'] == teacher_id]
            if not teacher_df.empty:
                stats = self._create_theory_teacher_schedule(teacher_id, teacher_df)
                teacher_stats.append(stats)
        
        # Generate overall teacher statistics
        if teacher_stats:
            self._generate_theory_teacher_statistics(teacher_stats)
    
    def _create_theory_teacher_schedule(self, teacher_id, teacher_df):
        """Create individual theory teacher schedule visualization."""
        # Get teacher information
        teacher_name = teacher_df.iloc[0].get('teacher_name', f'Teacher {teacher_id}')
        staff_code = teacher_df.iloc[0].get('staff_code', 'N/A')
        
        # Create figure
        fig, ax = plt.subplots(figsize=(16, 10))
        
        # Create grid for this teacher's schedule
        grid = np.empty((len(self.days), len(self.theory_time_slots)), dtype=object)
        block_grid = np.empty((len(self.days), len(self.theory_time_slots)), dtype=object)
        
        # Fill the grid with teacher's assignments
        total_hours = 0
        courses_taught = set()
        rooms_used = set()
        
        for _, row in teacher_df.iterrows():
            day = row['day']
            slot_idx = row.get('slot_index', 0)
            
            if day in self.days and 0 <= slot_idx < len(self.theory_time_slots):
                day_idx = self.days.index(day)
                
                course_code = row['course_code']
                room_number = row['room_number']
                room_id = row.get('room_id', '')
                theory_hours = row.get('theory_hours', 1)
                student_count = row.get('student_count', 0)
                
                courses_taught.add(course_code)
                rooms_used.add(room_number)
                total_hours += 1  # Each slot is 1 hour for theory
                
                # Determine block
                block_name = 'Unknown Block'
                for b_name, rooms in self.building_blocks.items():
                    if any(r['room_id'] == room_id for r in rooms):
                        block_name = b_name
                        break
                
                # Get group information
                group_info = row.get('group_name', 'Unknown Group')
                group_display = group_info.split('_')[-1] if '_' in group_info else group_info
                
                display_text = f"{course_code}\n{room_number}\n{student_count} students\n{group_display}"
                
                grid[day_idx, slot_idx] = display_text
                block_grid[day_idx, slot_idx] = block_name
        
        # Plot the grid
        self._plot_detailed_theory_teacher_grid(ax, grid, block_grid)
        
        # Add title and labels
        title = f"Theory Schedule - {teacher_name} (ID: {teacher_id})"
        if staff_code != 'N/A':
            title += f" | Staff Code: {staff_code}"
        ax.set_title(title, fontsize=14, fontweight='bold', pad=20)
        
        ax.set_xlabel('Time Slots', fontsize=12, fontweight='bold')
        ax.set_ylabel('Days', fontsize=12, fontweight='bold')
        
        # Set axis labels
        ax.set_xticks(range(len(self.theory_time_slots)))
        ax.set_xticklabels(self.theory_time_slots, rotation=45, ha='right')
        ax.set_yticks(range(len(self.days)))
        ax.set_yticklabels([day.capitalize() for day in self.days])
        
        # Add detailed legend
        self._add_detailed_legend(ax)
        
        # Adjust layout and save
        plt.tight_layout()
        teacher_schedule_path = os.path.join(self.output_dir, f'theory_teacher_{teacher_id}_schedule.png')
        plt.savefig(teacher_schedule_path, dpi=300, bbox_inches='tight')
        plt.close()
        
        # Generate teacher summary
        summary_stats = self._generate_theory_teacher_summary(teacher_id, teacher_name, staff_code, teacher_df, 
                                                            total_hours, courses_taught, rooms_used)
        
        print(f"Theory teacher schedule saved: {teacher_schedule_path}")
        return summary_stats
    
    def _plot_detailed_theory_teacher_grid(self, ax, grid, block_grid):
        """Plot detailed theory teacher schedule grid."""
        for i in range(len(self.days)):
            for j in range(len(self.theory_time_slots)):
                content = grid[i, j]
                block_name = block_grid[i, j]
                
                if content is not None:
                    # Get background color
                    bg_color = self.block_colors.get(block_name, '#F0F0F0')
                    
                    # Create rectangle
                    rect = plt.Rectangle((j-0.45, i-0.45), 0.9, 0.9, 
                                       facecolor=bg_color, edgecolor='black', linewidth=1.5)
                    ax.add_patch(rect)
                    
                    # Add text
                    ax.text(j, i, content, ha='center', va='center', 
                           fontsize=9, fontweight='bold',
                           bbox=dict(boxstyle="round,pad=0.15", facecolor='white', alpha=0.9))
                else:
                    # Empty slot
                    rect = plt.Rectangle((j-0.45, i-0.45), 0.9, 0.9, 
                                       facecolor='#FFFFFF', edgecolor='lightgray', linewidth=0.5)
                    ax.add_patch(rect)
        
        ax.set_xlim(-0.5, len(self.theory_time_slots) - 0.5)
        ax.set_ylim(-0.5, len(self.days) - 0.5)
        ax.set_aspect('equal')
    
    def _add_detailed_legend(self, ax):
        """Add detailed legend for theory schedules."""
        legend_elements = []
        for block_name, color in self.block_colors.items():
            legend_elements.append(plt.Rectangle((0, 0), 1, 1, facecolor=color, label=block_name))
        
        if legend_elements:
            ax.legend(handles=legend_elements, loc='center left', bbox_to_anchor=(1, 0.5), 
                     title="Building Blocks", title_fontsize=11, fontsize=10)
    
    def _generate_theory_teacher_summary(self, teacher_id, teacher_name, staff_code, teacher_df, 
                                       total_hours, courses_taught, rooms_used):
        """Generate theory teacher summary statistics."""
        summary_path = os.path.join(self.output_dir, f'theory_teacher_{teacher_id}_summary.txt')
        
        # Calculate additional statistics
        daily_hours = {}
        course_hours = {}
        group_distribution = {}
        
        for _, row in teacher_df.iterrows():
            day = row['day']
            course = row['course_code']
            group_name = row.get('group_name', 'Unknown')
            
            daily_hours[day] = daily_hours.get(day, 0) + 1
            course_hours[course] = course_hours.get(course, 0) + 1
            group_distribution[group_name] = group_distribution.get(group_name, 0) + 1
        
        with open(summary_path, 'w') as f:
            f.write(f"Theory Schedule Summary - {teacher_name}\n")
            f.write("=" * 50 + "\n\n")
            
            f.write(f"Teacher ID: {teacher_id}\n")
            f.write(f"Teacher Name: {teacher_name}\n")
            f.write(f"Staff Code: {staff_code}\n\n")
            
            f.write(f"WORKLOAD SUMMARY\n")
            f.write("-" * 20 + "\n")
            f.write(f"Total theory hours per week: {total_hours}\n")
            f.write(f"Courses taught: {len(courses_taught)}\n")
            f.write(f"Rooms used: {len(rooms_used)}\n\n")
            
            f.write(f"DAILY BREAKDOWN\n")
            f.write("-" * 20 + "\n")
            for day in self.days:
                hours = daily_hours.get(day, 0)
                f.write(f"{day.capitalize()}: {hours} hours\n")
            f.write("\n")
            
            f.write(f"COURSES TAUGHT\n")
            f.write("-" * 20 + "\n")
            for course, hours in sorted(course_hours.items()):
                f.write(f"{course}: {hours} hours\n")
            f.write("\n")
            
            f.write(f"GROUP DISTRIBUTION\n")
            f.write("-" * 20 + "\n")
            for group, hours in sorted(group_distribution.items()):
                f.write(f"{group}: {hours} hours\n")
            f.write("\n")
            
            f.write(f"ROOMS USED\n")
            f.write("-" * 20 + "\n")
            for room in sorted(rooms_used):
                f.write(f"- {room}\n")
        
        return {
            'teacher_id': teacher_id,
            'teacher_name': teacher_name,
            'total_hours': total_hours,
            'courses_count': len(courses_taught),
            'rooms_count': len(rooms_used),
            'daily_hours': daily_hours,
            'courses_taught': list(courses_taught)
        }
    
    def _generate_theory_teacher_statistics(self, teacher_stats):
        """Generate overall theory teacher statistics."""
        stats_path = os.path.join(self.output_dir, 'theory_teacher_statistics.txt')
        
        # Calculate aggregate statistics
        total_teachers = len(teacher_stats)
        total_workload = sum(stats['total_hours'] for stats in teacher_stats)
        avg_workload = total_workload / total_teachers if total_teachers > 0 else 0
        
        # Workload distribution
        workload_ranges = {'1-5': 0, '6-10': 0, '11-15': 0, '16-20': 0, '20+': 0}
        for stats in teacher_stats:
            hours = stats['total_hours']
            if hours <= 5:
                workload_ranges['1-5'] += 1
            elif hours <= 10:
                workload_ranges['6-10'] += 1
            elif hours <= 15:
                workload_ranges['11-15'] += 1
            elif hours <= 20:
                workload_ranges['16-20'] += 1
            else:
                workload_ranges['20+'] += 1
        
        with open(stats_path, 'w') as f:
            f.write("Theory Teacher Statistics\n")
            f.write("=" * 40 + "\n\n")
            
            f.write(f"OVERALL STATISTICS\n")
            f.write("-" * 20 + "\n")
            f.write(f"Total teachers: {total_teachers}\n")
            f.write(f"Total theory workload: {total_workload} hours\n")
            f.write(f"Average workload per teacher: {avg_workload:.1f} hours\n\n")
            
            f.write(f"WORKLOAD DISTRIBUTION\n")
            f.write("-" * 20 + "\n")
            for range_label, count in workload_ranges.items():
                percentage = (count / total_teachers * 100) if total_teachers > 0 else 0
                f.write(f"{range_label} hours: {count} teachers ({percentage:.1f}%)\n")
            f.write("\n")
            
            f.write(f"INDIVIDUAL TEACHER DETAILS\n")
            f.write("-" * 30 + "\n")
            sorted_stats = sorted(teacher_stats, key=lambda x: x['total_hours'], reverse=True)
            for stats in sorted_stats:
                f.write(f"Teacher {stats['teacher_id']} ({stats['teacher_name']}): "
                       f"{stats['total_hours']} hours, {stats['courses_count']} courses\n")
        
        print(f"Theory teacher statistics saved to: {stats_path}")
    
    def generate_room_schedules(self):
        """Generate individual room schedule visualizations."""
        if self.schedule_df.empty or len(self.rooms) == 0:
            return
        
        for room_id in self.rooms:
            room_df = self.schedule_df[self.schedule_df['room_id'] == room_id]
            if not room_df.empty:
                room_number = room_df.iloc[0]['room_number']
                self._create_theory_room_schedule(room_id, room_number, room_df)
    
    def _create_theory_room_schedule(self, room_id, room_number, room_df):
        """Create individual theory room schedule visualization."""
        # Create figure
        fig, ax = plt.subplots(figsize=(16, 8))
        
        # Create grid for this room's schedule
        grid = np.empty((len(self.days), len(self.theory_time_slots)), dtype=object)
        
        # Get room details
        block_info = room_df.iloc[0].get('block', 'Unknown')
        capacity = room_df.iloc[0].get('capacity', 'Unknown')
        
        # Fill the grid with room's assignments
        total_usage = 0
        teachers_using = set()
        courses_scheduled = set()
        
        for _, row in room_df.iterrows():
            day = row['day']
            slot_idx = row.get('slot_index', 0)
            
            if day in self.days and 0 <= slot_idx < len(self.theory_time_slots):
                day_idx = self.days.index(day)
                
                course_code = row['course_code']
                teacher_id = row['teacher_id']
                student_count = row.get('student_count', 0)
                
                teachers_using.add(teacher_id)
                courses_scheduled.add(course_code)
                total_usage += 1
                
                # Get group information
                group_info = row.get('group_name', 'Unknown Group')
                group_display = group_info.split('_')[-1] if '_' in group_info else group_info
                
                display_text = f"{course_code}\nT{teacher_id}\n{student_count} students\n{group_display}"
                grid[day_idx, slot_idx] = display_text
        
        # Plot the grid
        self._plot_simple_theory_grid(ax, grid, self.theory_time_slots)
        
        # Add title and information
        title = f"Theory Room Schedule - {room_number} (ID: {room_id})"
        subtitle = f"Block: {block_info} | Capacity: {capacity} | Usage: {total_usage} hours/week"
        ax.set_title(f"{title}\n{subtitle}", fontsize=12, fontweight='bold', pad=20)
        
        ax.set_xlabel('Time Slots', fontsize=11, fontweight='bold')
        ax.set_ylabel('Days', fontsize=11, fontweight='bold')
        
        # Set axis labels
        ax.set_xticks(range(len(self.theory_time_slots)))
        ax.set_xticklabels(self.theory_time_slots, rotation=45, ha='right')
        ax.set_yticks(range(len(self.days)))
        ax.set_yticklabels([day.capitalize() for day in self.days])
        
        # Adjust layout and save
        plt.tight_layout()
        room_schedule_path = os.path.join(self.output_dir, f'theory_room_{room_id}_schedule.png')
        plt.savefig(room_schedule_path, dpi=300, bbox_inches='tight')
        plt.close()
        
        print(f"Theory room schedule saved: {room_schedule_path}")
    
    def _plot_simple_theory_grid(self, ax, grid, time_labels):
        """Plot simple theory room schedule grid."""
        for i in range(len(self.days)):
            for j in range(len(time_labels)):
                content = grid[i, j]
                
                if content is not None:
                    # Occupied slot
                    rect = plt.Rectangle((j-0.4, i-0.4), 0.8, 0.8, 
                                       facecolor='lightblue', edgecolor='black', linewidth=1)
                    ax.add_patch(rect)
                    
                    ax.text(j, i, content, ha='center', va='center', 
                           fontsize=8, fontweight='bold')
                else:
                    # Empty slot
                    rect = plt.Rectangle((j-0.4, i-0.4), 0.8, 0.8, 
                                       facecolor='#FFFFFF', edgecolor='lightgray', linewidth=0.5)
                    ax.add_patch(rect)
        
        ax.set_xlim(-0.5, len(time_labels) - 0.5)
        ax.set_ylim(-0.5, len(self.days) - 0.5)
        ax.set_aspect('equal')
    
    def generate_distribution_analysis(self):
        """Generate distribution analysis charts for theory schedules."""
        if self.schedule_df.empty:
            return
        
        # Create subplots for different analyses
        fig = plt.figure(figsize=(20, 12))
        gs = GridSpec(2, 3, figure=fig)
        
        # Daily distribution
        ax1 = fig.add_subplot(gs[0, 0])
        self._plot_theory_daily_distribution(ax1)
        
        # Time slot distribution
        ax2 = fig.add_subplot(gs[0, 1])
        self._plot_theory_slot_distribution(ax2)
        
        # Course distribution
        ax3 = fig.add_subplot(gs[0, 2])
        self._plot_theory_course_distribution(ax3)
        
        # Teacher workload distribution
        ax4 = fig.add_subplot(gs[1, 0])
        self._plot_theory_teacher_distribution(ax4)
        
        # Block distribution
        ax5 = fig.add_subplot(gs[1, 1])
        self._plot_theory_block_distribution(ax5)
        
        # Group distribution
        ax6 = fig.add_subplot(gs[1, 2])
        self._plot_theory_group_distribution(ax6)
        
        plt.suptitle('Theory Schedule Distribution Analysis', fontsize=16, fontweight='bold')
        plt.tight_layout()
        
        analysis_path = os.path.join(self.output_dir, 'theory_distribution_analysis.png')
        plt.savefig(analysis_path, dpi=300, bbox_inches='tight')
        plt.close()
        
        print(f"Theory distribution analysis saved to: {analysis_path}")
    
    def _plot_theory_daily_distribution(self, ax):
        """Plot theory sessions distribution by day."""
        daily_counts = self.schedule_df['day'].value_counts().reindex(self.days, fill_value=0)
        
        bars = ax.bar(range(len(self.days)), daily_counts.values, color='skyblue', alpha=0.7)
        ax.set_title('Theory Sessions by Day', fontweight='bold')
        ax.set_xlabel('Days')
        ax.set_ylabel('Number of Sessions')
        ax.set_xticks(range(len(self.days)))
        ax.set_xticklabels([day.capitalize() for day in self.days])
        
        # Add value labels on bars
        for bar, count in zip(bars, daily_counts.values):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1, 
                   str(count), ha='center', va='bottom', fontweight='bold')
    
    def _plot_theory_slot_distribution(self, ax):
        """Plot theory sessions distribution by time slot."""
        slot_counts = {}
        for _, row in self.schedule_df.iterrows():
            slot_idx = row.get('slot_index', 0)
            if 0 <= slot_idx < len(self.theory_time_slots):
                slot_label = self.theory_time_slots[slot_idx]
                slot_counts[slot_label] = slot_counts.get(slot_label, 0) + 1
        
        slots = list(slot_counts.keys())
        counts = list(slot_counts.values())
        
        bars = ax.bar(range(len(slots)), counts, color='lightgreen', alpha=0.7)
        ax.set_title('Theory Sessions by Time Slot', fontweight='bold')
        ax.set_xlabel('Time Slots')
        ax.set_ylabel('Number of Sessions')
        ax.set_xticks(range(len(slots)))
        ax.set_xticklabels(slots, rotation=45)
        
        # Add value labels on bars
        for bar, count in zip(bars, counts):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1, 
                   str(count), ha='center', va='bottom', fontweight='bold')
    
    def _plot_theory_course_distribution(self, ax):
        """Plot course distribution for theory sessions."""
        course_counts = self.schedule_df['course_code'].value_counts()
        
        # Show top 10 courses
        top_courses = course_counts.head(10)
        bars = ax.bar(range(len(top_courses)), top_courses.values, color='lightcoral', alpha=0.7)
        ax.set_title('Top 10 Courses by Theory Sessions', fontweight='bold')
        ax.set_xlabel('Courses')
        ax.set_ylabel('Number of Sessions')
        ax.set_xticks(range(len(top_courses)))
        ax.set_xticklabels(top_courses.index, rotation=45)
        
        # Add value labels on bars
        for bar, count in zip(bars, top_courses.values):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1, 
                   str(count), ha='center', va='bottom', fontweight='bold')
    
    def _plot_theory_teacher_distribution(self, ax):
        """Plot teacher workload distribution for theory sessions."""
        teacher_counts = self.schedule_df['teacher_id'].value_counts()
        
        # Show distribution by workload ranges
        workload_ranges = {'1-2': 0, '3-5': 0, '6-8': 0, '9-12': 0, '13+': 0}
        for count in teacher_counts.values:
            if count <= 2:
                workload_ranges['1-2'] += 1
            elif count <= 5:
                workload_ranges['3-5'] += 1
            elif count <= 8:
                workload_ranges['6-8'] += 1
            elif count <= 12:
                workload_ranges['9-12'] += 1
            else:
                workload_ranges['13+'] += 1
        
        ranges = list(workload_ranges.keys())
        counts = list(workload_ranges.values())
        
        bars = ax.bar(range(len(ranges)), counts, color='gold', alpha=0.7)
        ax.set_title('Teacher Workload Distribution', fontweight='bold')
        ax.set_xlabel('Theory Hours per Week')
        ax.set_ylabel('Number of Teachers')
        ax.set_xticks(range(len(ranges)))
        ax.set_xticklabels(ranges)
        
        # Add value labels on bars
        for bar, count in zip(bars, counts):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1, 
                   str(count), ha='center', va='bottom', fontweight='bold')
    
    def _plot_theory_block_distribution(self, ax):
        """Plot building block distribution for theory sessions."""
        block_counts = self.schedule_df['block'].value_counts()
        
        bars = ax.bar(range(len(block_counts)), block_counts.values, 
                     color=[self.block_colors.get(block, '#CCCCCC') for block in block_counts.index], 
                     alpha=0.7)
        ax.set_title('Theory Sessions by Building Block', fontweight='bold')
        ax.set_xlabel('Building Blocks')
        ax.set_ylabel('Number of Sessions')
        ax.set_xticks(range(len(block_counts)))
        ax.set_xticklabels(block_counts.index, rotation=45)
        
        # Add value labels on bars
        for bar, count in zip(bars, block_counts.values):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1, 
                   str(count), ha='center', va='bottom', fontweight='bold')
    
    def _plot_theory_group_distribution(self, ax):
        """Plot group distribution for theory sessions."""
        if 'group_name' in self.schedule_df.columns:
            # Extract group info and count
            group_info = []
            for _, row in self.schedule_df.iterrows():
                group_name = row.get('group_name', 'Unknown')
                if '_G' in group_name:
                    group_num = group_name.split('_G')[-1]
                    group_info.append(f"Group {group_num}")
                else:
                    group_info.append('Unknown Group')
            
            group_df = pd.Series(group_info)
            group_counts = group_df.value_counts()
            
            bars = ax.bar(range(len(group_counts)), group_counts.values, color='mediumpurple', alpha=0.7)
            ax.set_title('Theory Sessions by Student Group', fontweight='bold')
            ax.set_xlabel('Student Groups')
            ax.set_ylabel('Number of Sessions')
            ax.set_xticks(range(len(group_counts)))
            ax.set_xticklabels(group_counts.index, rotation=45, ha='right')
            
            # Add value labels on bars
            for bar, count in zip(bars, group_counts.values):
                ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1, 
                       str(count), ha='center', va='bottom', fontweight='bold')
        else:
            ax.text(0.5, 0.5, 'No group information available', 
                   ha='center', va='center', transform=ax.transAxes, fontsize=12)
            ax.set_title('Group Distribution (No Data)', fontweight='bold')


def visualize_theory_schedule(schedule_file, output_dir=None):
    """
    Visualize theory schedule from JSON or CSV file.
    
    Args:
        schedule_file (str): Path to the theory schedule file (JSON or CSV)
        output_dir (str, optional): Output directory for visualizations
    
    Returns:
        str: Path to the output directory containing visualizations
    """
    import json
    
    # Load schedule data
    if schedule_file.endswith('.json'):
        with open(schedule_file, 'r') as f:
            schedule_data = json.load(f)
    elif schedule_file.endswith('.csv'):
        schedule_df = pd.read_csv(schedule_file)
        schedule_data = schedule_df.to_dict('records')
    else:
        raise ValueError("Schedule file must be either JSON or CSV format")
    
    # Set default output directory if not provided
    if output_dir is None:
        output_dir = os.path.join(os.path.dirname(schedule_file), 'theory_visualizations')
    
    # Create output directory
    os.makedirs(output_dir, exist_ok=True)
    
    # Create visualizer and generate visualizations
    visualizer = TheoryScheduleVisualizer(schedule_data, output_dir)
    result_dir = visualizer.generate_visualizations()
    
    print(f"Theory schedule visualizations generated in: {result_dir}")
    return result_dir


class CombinedScheduleVisualizer:
    """Visualizes combined lab and theory timetable schedules."""
    
    def __init__(self, lab_schedule_data=None, theory_schedule_data=None, output_dir=None):
        """Initialize the combined schedule visualizer."""
        self.lab_df = pd.DataFrame(lab_schedule_data) if lab_schedule_data else pd.DataFrame()
        self.theory_df = pd.DataFrame(theory_schedule_data) if theory_schedule_data else pd.DataFrame()
        self.output_dir = output_dir or 'combined_visualizations'
        
        # Timetable days structure
        self.days = ["tuesday", "wed", "thur", "fri", "sat"]
        
        # Time slots (11 slots per day - covers both lab and theory times)
        self.time_slots = [
            "8:00 - 8:50", "9:00 - 9:50", "10:00 - 10:50", "11:00 - 11:50",
            "12:00 - 12:50", "1:00 - 1:50", "2:00 - 2:50", "3:00 - 3:50", 
            "4:00 - 4:50", "5:00 - 5:50", "6:00 - 6:50"
        ]
        
        # Lab sessions mapping to time slots
        self.lab_sessions = {
            'L1': {'slots': [0, 1], 'time_range': '8:00 - 9:40'},
            'L2': {'slots': [2, 3], 'time_range': '9:50 - 11:30'},
            'L3': {'slots': [4, 5], 'time_range': '11:50 - 1:30'},
            'L4': {'slots': [6, 7], 'time_range': '1:50 - 3:30'},
            'L5': {'slots': [8, 9], 'time_range': '3:50 - 5:30'},
            'L6': {'slots': [10, 11], 'time_range': '5:30 - 7:10'}
        }
        
        # Initialize color schemes
        self._setup_color_schemes()
    
    def _setup_color_schemes(self):
        """Setup color schemes for lab and theory schedules."""
        # Lab colors (darker tones)
        self.lab_colors = {
            'A Block': '#FF6B6B',      # Red tones
            'B Block': '#4ECDC4',      # Teal tones
            'Techlounge': '#9B59B6',   # Purple
            'J Block': '#F39C12',      # Orange
            'K Block': '#27AE60',      # Green  
            'D Block': '#3498DB',      # Blue
            'Unknown Block': '#95A5A6', # Gray
        }
        
        # Theory colors (lighter tones)
        self.theory_colors = {
            'A Block': '#FFB3BA',      # Light red tones
            'B Block': '#BAFFC9',      # Light green tones
            'Techlounge': '#D4BAFF',   # Light purple
            'J Block': '#FFFFBA',      # Light yellow
            'K Block': '#BAE1FF',      # Light blue  
            'D Block': '#FFDFBA',      # Light orange
            'Unknown Block': '#E6E6E6', # Light gray
        }
    
    def generate_combined_visualizations(self):
        """Generate combined visualizations for lab and theory schedules."""
        if self.lab_df.empty and self.theory_df.empty:
            print("No schedule data available for combined visualization")
            return self.output_dir
        
        os.makedirs(self.output_dir, exist_ok=True)
        
        self.generate_combined_overview()
        self.generate_teacher_combined_schedules()
        self.generate_combined_analysis()
        
        return self.output_dir
    
    def generate_combined_overview(self):
        """Generate a combined overview showing both lab and theory schedules."""
        # Create figure
        fig, ax = plt.subplots(figsize=(20, 14))
        
        # Create a grid for days and time slots
        grid = np.empty((len(self.days), len(self.time_slots)), dtype=object)
        color_grid = np.empty((len(self.days), len(self.time_slots)), dtype=object)
        
        # First, add lab sessions to the grid
        for _, row in self.lab_df.iterrows():
            day = row['day']
            session_name = row.get('session_name', 'L1')
            
            if day in self.days and session_name in self.lab_sessions:
                day_idx = self.days.index(day)
                time_slots = self.lab_sessions[session_name]['slots']
                
                course_code = row['course_code']
                teacher_id = row['teacher_id']
                room_number = row['room_number']
                block = row.get('block', 'Unknown Block')
                
                # Get display info
                if row.get('is_batched', False):
                    batch_info = row.get('batch_info', '')
                    display_text = f"LAB: {course_code} {batch_info}\nT{teacher_id} | {room_number}"
                else:
                    display_text = f"LAB: {course_code}\nT{teacher_id} | {room_number}"
                
                # Fill both time slots for lab session
                for slot_idx in time_slots:
                    if slot_idx < len(self.time_slots):
                        grid[day_idx, slot_idx] = display_text
                        color_grid[day_idx, slot_idx] = ('lab', block)
        
        # Then, add theory sessions to the grid (only in free slots)
        for _, row in self.theory_df.iterrows():
            day = row['day']
            slot_idx = row.get('slot_index', 0)
            
            if day in self.days and 0 <= slot_idx < len(self.time_slots):
                day_idx = self.days.index(day)
                
                # Only add if slot is free
                if grid[day_idx, slot_idx] is None:
                    course_code = row['course_code']
                    teacher_id = row['teacher_id']
                    room_number = row['room_number']
                    block = row.get('block', 'Unknown Block')
                    
                    display_text = f"THEORY: {course_code}\nT{teacher_id} | {room_number}"
                    grid[day_idx, slot_idx] = display_text
                    color_grid[day_idx, slot_idx] = ('theory', block)
        
        # Plot the combined grid
        self._plot_combined_grid(ax, grid, color_grid)
        
        # Add title and labels
        ax.set_title('Combined Schedule Overview - Lab and Theory Sessions', fontsize=18, fontweight='bold', pad=20)
        ax.set_xlabel('Time Slots', fontsize=14, fontweight='bold')
        ax.set_ylabel('Days', fontsize=14, fontweight='bold')
        
        # Set axis labels
        ax.set_xticks(range(len(self.time_slots)))
        ax.set_xticklabels(self.time_slots, rotation=45, ha='right')
        ax.set_yticks(range(len(self.days)))
        ax.set_yticklabels([day.capitalize() for day in self.days])
        
        # Add combined legend
        self._add_combined_legend(ax)
        
        # Adjust layout and save
        plt.tight_layout()
        combined_overview_path = os.path.join(self.output_dir, 'combined_schedule_overview.png')
        plt.savefig(combined_overview_path, dpi=300, bbox_inches='tight')
        plt.close()
        
        print(f"Combined schedule overview saved to: {combined_overview_path}")
    
    def _plot_combined_grid(self, ax, grid, color_grid):
        """Plot the combined schedule grid with different colors for lab and theory."""
        for i in range(len(self.days)):
            for j in range(len(self.time_slots)):
                content = grid[i, j]
                color_info = color_grid[i, j]
                
                if content is not None and color_info is not None:
                    schedule_type, block = color_info
                    
                    # Get background color based on schedule type and block
                    if schedule_type == 'lab':
                        bg_color = self.lab_colors.get(block, '#F0F0F0')
                        border_color = 'darkred'
                        border_width = 2
                    else:  # theory
                        bg_color = self.theory_colors.get(block, '#F8F8F8')
                        border_color = 'darkblue'
                        border_width = 1.5
                    
                    # Create rectangle
                    rect = plt.Rectangle((j-0.45, i-0.45), 0.9, 0.9, 
                                       facecolor=bg_color, edgecolor=border_color, linewidth=border_width)
                    ax.add_patch(rect)
                    
                    # Add text content
                    ax.text(j, i, content, ha='center', va='center', 
                           fontsize=7, fontweight='bold', 
                           bbox=dict(boxstyle="round,pad=0.1", facecolor='white', alpha=0.9))
                else:
                    # Empty slot
                    rect = plt.Rectangle((j-0.45, i-0.45), 0.9, 0.9, 
                                       facecolor='#FFFFFF', edgecolor='lightgray', linewidth=0.5)
                    ax.add_patch(rect)
        
        ax.set_xlim(-0.5, len(self.time_slots) - 0.5)
        ax.set_ylim(-0.5, len(self.days) - 0.5)
        ax.set_aspect('equal')
    
    def _add_combined_legend(self, ax):
        """Add legend for combined schedule showing both lab and theory."""
        legend_elements = []
        
        # Add lab legend items
        legend_elements.append(plt.Rectangle((0, 0), 1, 1, facecolor='darkred', alpha=0.3, label='Lab Sessions'))
        legend_elements.append(plt.Rectangle((0, 0), 1, 1, facecolor='darkblue', alpha=0.3, label='Theory Sessions'))
        
        # Add block color legend items
        legend_elements.append(plt.Rectangle((0, 0), 1, 1, facecolor='white', alpha=0, label=''))  # Spacer
        
        all_blocks = set()
        if not self.lab_df.empty and 'block' in self.lab_df.columns:
            all_blocks.update(self.lab_df['block'].unique())
        if not self.theory_df.empty and 'block' in self.theory_df.columns:
            all_blocks.update(self.theory_df['block'].unique())
        
        for block in sorted(all_blocks):
            if block in self.lab_colors:
                legend_elements.append(plt.Rectangle((0, 0), 1, 1, facecolor=self.lab_colors[block], alpha=0.7, label=f'{block}'))
        
        if legend_elements:
            ax.legend(handles=legend_elements, loc='center left', bbox_to_anchor=(1, 0.5), 
                     title="Schedule Types & Buildings", title_fontsize=12, fontsize=10)
    
    def generate_teacher_combined_schedules(self):
        """Generate individual teacher schedules showing both lab and theory."""
        # Get all teachers from both schedules
        all_teachers = set()
        if not self.lab_df.empty and 'teacher_id' in self.lab_df.columns:
            all_teachers.update(self.lab_df['teacher_id'].unique())
        if not self.theory_df.empty and 'teacher_id' in self.theory_df.columns:
            all_teachers.update(self.theory_df['teacher_id'].unique())
        
        for teacher_id in all_teachers:
            teacher_lab_df = self.lab_df[self.lab_df['teacher_id'] == teacher_id] if not self.lab_df.empty else pd.DataFrame()
            teacher_theory_df = self.theory_df[self.theory_df['teacher_id'] == teacher_id] if not self.theory_df.empty else pd.DataFrame()
            
            if not teacher_lab_df.empty or not teacher_theory_df.empty:
                self._create_teacher_combined_schedule(teacher_id, teacher_lab_df, teacher_theory_df)
    
    def _create_teacher_combined_schedule(self, teacher_id, teacher_lab_df, teacher_theory_df):
        """Create individual teacher combined schedule visualization."""
        # Get teacher information
        teacher_name = 'Unknown'
        staff_code = 'N/A'
        
        if not teacher_lab_df.empty:
            teacher_name = teacher_lab_df.iloc[0].get('teacher_name', f'Teacher {teacher_id}')
            staff_code = teacher_lab_df.iloc[0].get('staff_code', 'N/A')
        elif not teacher_theory_df.empty:
            teacher_name = teacher_theory_df.iloc[0].get('teacher_name', f'Teacher {teacher_id}')
            staff_code = teacher_theory_df.iloc[0].get('staff_code', 'N/A')
        
        # Create figure
        fig, ax = plt.subplots(figsize=(18, 10))
        
        # Create grid for this teacher's combined schedule
        grid = np.empty((len(self.days), len(self.time_slots)), dtype=object)
        color_grid = np.empty((len(self.days), len(self.time_slots)), dtype=object)
        
        # Fill the grid with teacher's lab assignments
        lab_hours = 0
        theory_hours = 0
        all_courses = set()
        all_rooms = set()
        
        for _, row in teacher_lab_df.iterrows():
            day = row['day']
            session_name = row.get('session_name', 'L1')
            
            if day in self.days and session_name in self.lab_sessions:
                day_idx = self.days.index(day)
                time_slots = self.lab_sessions[session_name]['slots']
                
                course_code = row['course_code']
                room_number = row['room_number']
                block = row.get('block', 'Unknown Block')
                
                all_courses.add(course_code)
                all_rooms.add(room_number)
                lab_hours += 2  # Lab sessions are 2 hours
                
                if row.get('is_batched', False):
                    batch_info = row.get('batch_info', '')
                    display_text = f"LAB: {course_code} {batch_info}\n{room_number}"
                else:
                    display_text = f"LAB: {course_code}\n{room_number}"
                
                for slot_idx in time_slots:
                    if slot_idx < len(self.time_slots):
                        grid[day_idx, slot_idx] = display_text
                        color_grid[day_idx, slot_idx] = ('lab', block)
        
        # Fill the grid with teacher's theory assignments
        for _, row in teacher_theory_df.iterrows():
            day = row['day']
            slot_idx = row.get('slot_index', 0)
            
            if day in self.days and 0 <= slot_idx < len(self.time_slots):
                day_idx = self.days.index(day)
                
                if grid[day_idx, slot_idx] is None:  # Only add if slot is free
                    course_code = row['course_code']
                    room_number = row['room_number']
                    block = row.get('block', 'Unknown Block')
                    
                    all_courses.add(course_code)
                    all_rooms.add(room_number)
                    theory_hours += 1  # Theory sessions are 1 hour
                    
                    display_text = f"THEORY: {course_code}\n{room_number}"
                    grid[day_idx, slot_idx] = display_text
                    color_grid[day_idx, slot_idx] = ('theory', block)
        
        # Plot the grid
        self._plot_combined_grid(ax, grid, color_grid)
        
        # Add title and labels
        title = f"Combined Schedule - {teacher_name} (ID: {teacher_id})"
        if staff_code != 'N/A':
            title += f" | Staff Code: {staff_code}"
        subtitle = f"Lab Hours: {lab_hours} | Theory Hours: {theory_hours} | Total Courses: {len(all_courses)} | Rooms: {len(all_rooms)}"
        ax.set_title(f"{title}\n{subtitle}", fontsize=14, fontweight='bold', pad=20)
        
        ax.set_xlabel('Time Slots', fontsize=12, fontweight='bold')
        ax.set_ylabel('Days', fontsize=12, fontweight='bold')
        
        # Set axis labels
        ax.set_xticks(range(len(self.time_slots)))
        ax.set_xticklabels(self.time_slots, rotation=45, ha='right')
        ax.set_yticks(range(len(self.days)))
        ax.set_yticklabels([day.capitalize() for day in self.days])
        
        # Add combined legend
        self._add_combined_legend(ax)
        
        # Adjust layout and save
        plt.tight_layout()
        teacher_combined_path = os.path.join(self.output_dir, f'combined_teacher_{teacher_id}_schedule.png')
        plt.savefig(teacher_combined_path, dpi=300, bbox_inches='tight')
        plt.close()
        
        print(f"Combined teacher schedule saved: {teacher_combined_path}")
    
    def generate_combined_analysis(self):
        """Generate combined analysis comparing lab and theory schedules."""
        if self.lab_df.empty and self.theory_df.empty:
            return
        
        # Create subplots for combined analysis
        fig = plt.figure(figsize=(20, 12))
        gs = GridSpec(2, 3, figure=fig)
        
        # Daily distribution comparison
        ax1 = fig.add_subplot(gs[0, 0])
        self._plot_combined_daily_distribution(ax1)
        
        # Teacher workload comparison
        ax2 = fig.add_subplot(gs[0, 1])
        self._plot_combined_teacher_workload(ax2)
        
        # Course distribution comparison
        ax3 = fig.add_subplot(gs[0, 2])
        self._plot_combined_course_distribution(ax3)
        
        # Time slot utilization
        ax4 = fig.add_subplot(gs[1, 0])
        self._plot_time_slot_utilization(ax4)
        
        # Block utilization comparison
        ax5 = fig.add_subplot(gs[1, 1])
        self._plot_combined_block_utilization(ax5)
        
        # Overall statistics
        ax6 = fig.add_subplot(gs[1, 2])
        self._plot_overall_statistics(ax6)
        
        plt.suptitle('Combined Schedule Analysis - Lab vs Theory', fontsize=16, fontweight='bold')
        plt.tight_layout()
        
        analysis_path = os.path.join(self.output_dir, 'combined_analysis.png')
        plt.savefig(analysis_path, dpi=300, bbox_inches='tight')
        plt.close()
        
        print(f"Combined analysis saved to: {analysis_path}")
    
    def _plot_combined_daily_distribution(self, ax):
        """Plot daily distribution comparison between lab and theory."""
        lab_daily = self.lab_df['day'].value_counts().reindex(self.days, fill_value=0) if not self.lab_df.empty else pd.Series([0]*len(self.days), index=self.days)
        theory_daily = self.theory_df['day'].value_counts().reindex(self.days, fill_value=0) if not self.theory_df.empty else pd.Series([0]*len(self.days), index=self.days)
        
        x = np.arange(len(self.days))
        width = 0.35
        
        bars1 = ax.bar(x - width/2, lab_daily.values, width, label='Lab Sessions', color='darkred', alpha=0.7)
        bars2 = ax.bar(x + width/2, theory_daily.values, width, label='Theory Sessions', color='darkblue', alpha=0.7)
        
        ax.set_title('Daily Distribution - Lab vs Theory', fontweight='bold')
        ax.set_xlabel('Days')
        ax.set_ylabel('Number of Sessions')
        ax.set_xticks(x)
        ax.set_xticklabels([day.capitalize() for day in self.days])
        ax.legend()
        
        # Add value labels
        for bars in [bars1, bars2]:
            for bar in bars:
                height = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2., height + 0.1,
                       f'{int(height)}', ha='center', va='bottom', fontsize=8)
    
    def _plot_combined_teacher_workload(self, ax):
        """Plot teacher workload comparison between lab and theory."""
        lab_teachers = self.lab_df['teacher_id'].value_counts() if not self.lab_df.empty else pd.Series()
        theory_teachers = self.theory_df['teacher_id'].value_counts() if not self.theory_df.empty else pd.Series()
        
        # Combine and categorize workload
        workload_categories = {'Low (1-5)': 0, 'Medium (6-10)': 0, 'High (11-15)': 0, 'Very High (16+)': 0}
        
        for count in lab_teachers.values:
            sessions = count * 2  # Lab sessions are 2 hours each
            if sessions <= 5:
                workload_categories['Low (1-5)'] += 1
            elif sessions <= 10:
                workload_categories['Medium (6-10)'] += 1
            elif sessions <= 15:
                workload_categories['High (11-15)'] += 1
            else:
                workload_categories['Very High (16+)'] += 1
        
        categories = list(workload_categories.keys())
        values = list(workload_categories.values())
        
        bars = ax.bar(categories, values, color='purple', alpha=0.7)
        ax.set_title('Teacher Workload Distribution', fontweight='bold')
        ax.set_xlabel('Workload Categories (Hours/Week)')
        ax.set_ylabel('Number of Teachers')
        ax.tick_params(axis='x', rotation=45)
        
        # Add value labels
        for bar in bars:
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height + 0.1,
                   f'{int(height)}', ha='center', va='bottom', fontsize=9)
    
    def _plot_combined_course_distribution(self, ax):
        """Plot course distribution comparison."""
        lab_courses = set(self.lab_df['course_code'].unique()) if not self.lab_df.empty else set()
        theory_courses = set(self.theory_df['course_code'].unique()) if not self.theory_df.empty else set()
        
        only_lab = len(lab_courses - theory_courses)
        only_theory = len(theory_courses - lab_courses)
        both = len(lab_courses & theory_courses)
        
        categories = ['Lab Only', 'Theory Only', 'Both Lab & Theory']
        values = [only_lab, only_theory, both]
        colors = ['darkred', 'darkblue', 'purple']
        
        bars = ax.bar(categories, values, color=colors, alpha=0.7)
        ax.set_title('Course Distribution', fontweight='bold')
        ax.set_xlabel('Course Categories')
        ax.set_ylabel('Number of Courses')
        
        # Add value labels
        for bar in bars:
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height + 0.1,
                   f'{int(height)}', ha='center', va='bottom', fontsize=10)
    
    def _plot_time_slot_utilization(self, ax):
        """Plot time slot utilization showing lab and theory overlap."""
        slot_utilization = [0] * len(self.time_slots)
        
        # Count lab sessions
        for _, row in self.lab_df.iterrows():
            session_name = row.get('session_name', 'L1')
            if session_name in self.lab_sessions:
                for slot_idx in self.lab_sessions[session_name]['slots']:
                    if slot_idx < len(self.time_slots):
                        slot_utilization[slot_idx] += 1
        
        # Count theory sessions
        for _, row in self.theory_df.iterrows():
            slot_idx = row.get('slot_index', 0)
            if 0 <= slot_idx < len(self.time_slots):
                slot_utilization[slot_idx] += 1
        
        bars = ax.bar(range(len(self.time_slots)), slot_utilization, color='orange', alpha=0.7)
        ax.set_title('Time Slot Utilization', fontweight='bold')
        ax.set_xlabel('Time Slots')
        ax.set_ylabel('Total Sessions')
        ax.set_xticks(range(len(self.time_slots)))
        ax.set_xticklabels(self.time_slots, rotation=45, ha='right')
        
        # Add value labels
        for bar in bars:
            height = bar.get_height()
            if height > 0:
                ax.text(bar.get_x() + bar.get_width()/2., height + 0.1,
                       f'{int(height)}', ha='center', va='bottom', fontsize=8)
    
    def _plot_combined_block_utilization(self, ax):
        """Plot building block utilization comparison."""
        lab_blocks = self.lab_df['block'].value_counts() if not self.lab_df.empty and 'block' in self.lab_df.columns else pd.Series()
        theory_blocks = self.theory_df['block'].value_counts() if not self.theory_df.empty and 'block' in self.theory_df.columns else pd.Series()
        
        all_blocks = set(lab_blocks.index.tolist() + theory_blocks.index.tolist())
        
        lab_values = [lab_blocks.get(block, 0) for block in all_blocks]
        theory_values = [theory_blocks.get(block, 0) for block in all_blocks]
        
        x = np.arange(len(all_blocks))
        width = 0.35
        
        bars1 = ax.bar(x - width/2, lab_values, width, label='Lab', color='darkred', alpha=0.7)
        bars2 = ax.bar(x + width/2, theory_values, width, label='Theory', color='darkblue', alpha=0.7)
        
        ax.set_title('Building Block Utilization', fontweight='bold')
        ax.set_xlabel('Building Blocks')
        ax.set_ylabel('Number of Sessions')
        ax.set_xticks(x)
        ax.set_xticklabels(list(all_blocks), rotation=45, ha='right')
        ax.legend()
    
    def _plot_overall_statistics(self, ax):
        """Plot overall statistics comparison."""
        lab_stats = {
            'Total Sessions': len(self.lab_df),
            'Unique Teachers': len(self.lab_df['teacher_id'].unique()) if not self.lab_df.empty else 0,
            'Unique Courses': len(self.lab_df['course_code'].unique()) if not self.lab_df.empty else 0,
            'Unique Rooms': len(self.lab_df['room_id'].unique()) if not self.lab_df.empty and 'room_id' in self.lab_df.columns else 0
        }
        
        theory_stats = {
            'Total Sessions': len(self.theory_df),
            'Unique Teachers': len(self.theory_df['teacher_id'].unique()) if not self.theory_df.empty else 0,
            'Unique Courses': len(self.theory_df['course_code'].unique()) if not self.theory_df.empty else 0,
            'Unique Rooms': len(self.theory_df['room_id'].unique()) if not self.theory_df.empty and 'room_id' in self.theory_df.columns else 0
        }
        
        categories = list(lab_stats.keys())
        lab_values = list(lab_stats.values())
        theory_values = list(theory_stats.values())
        
        x = np.arange(len(categories))
        width = 0.35
        
        bars1 = ax.bar(x - width/2, lab_values, width, label='Lab', color='darkred', alpha=0.7)
        bars2 = ax.bar(x + width/2, theory_values, width, label='Theory', color='darkblue', alpha=0.7)
        
        ax.set_title('Overall Statistics Comparison', fontweight='bold')
        ax.set_xlabel('Metrics')
        ax.set_ylabel('Count')
        ax.set_xticks(x)
        ax.set_xticklabels(categories, rotation=45, ha='right')
        ax.legend()
        
        # Add value labels
        for bars in [bars1, bars2]:
            for bar in bars:
                height = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2., height + 0.1,
                       f'{int(height)}', ha='center', va='bottom', fontsize=8)


def visualize_combined_schedule(lab_schedule_file=None, theory_schedule_file=None, output_dir=None):
    """
    Visualize combined lab and theory schedules.
    
    Args:
        lab_schedule_file (str, optional): Path to the lab schedule file (JSON or CSV)
        theory_schedule_file (str, optional): Path to the theory schedule file (JSON or CSV)
        output_dir (str, optional): Output directory for visualizations
    
    Returns:
        str: Path to the output directory containing visualizations
    """
    import json
    
    lab_data = None
    theory_data = None
    
    # Load lab schedule data
    if lab_schedule_file:
        if lab_schedule_file.endswith('.json'):
            with open(lab_schedule_file, 'r') as f:
                lab_data = json.load(f)
        elif lab_schedule_file.endswith('.csv'):
            lab_df = pd.read_csv(lab_schedule_file)
            lab_data = lab_df.to_dict('records')
    
    # Load theory schedule data
    if theory_schedule_file:
        if theory_schedule_file.endswith('.json'):
            with open(theory_schedule_file, 'r') as f:
                theory_data = json.load(f)
        elif theory_schedule_file.endswith('.csv'):
            theory_df = pd.read_csv(theory_schedule_file)
            theory_data = theory_df.to_dict('records')
    
    # Set default output directory if not provided
    if output_dir is None:
        base_dir = os.path.dirname(lab_schedule_file or theory_schedule_file or '.')
        output_dir = os.path.join(base_dir, 'combined_visualizations')
    
    # Create output directory
    os.makedirs(output_dir, exist_ok=True)
    
    # Create visualizer and generate visualizations
    visualizer = CombinedScheduleVisualizer(lab_data, theory_data, output_dir)
    result_dir = visualizer.generate_combined_visualizations()
    
    print(f"Combined schedule visualizations generated in: {result_dir}")
    return result_dir
