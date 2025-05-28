import os
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import numpy as np
import seaborn as sns
from matplotlib.gridspec import GridSpec
from typing import Dict, List, Any, Optional
import logging

class RoomVisualizer:
    """
    Room visualization module for timetable scheduling.
    
    Provides comprehensive visualization of room allocations including:
    - Room utilization charts
    - Time slot occupancy heatmaps
    - Room conflict visualization
    - Capacity vs usage analysis
    - Room efficiency metrics
    """
    
    def __init__(self, schedule_data: List[Dict[str, Any]], output_dir: str, logger=None):
        """
        Initialize the room visualizer.
        
        Args:
            schedule_data: List of schedule assignments
            output_dir: Directory to save visualization outputs
            logger: Optional logger instance
        """
        self.schedule_df = pd.DataFrame(schedule_data) if schedule_data else pd.DataFrame()
        self.output_dir = output_dir
        self.logger = logger or logging.getLogger(__name__)
        
        # Time configuration
        self.days = ["tuesday", "wed", "thur", "fri", "sat"]
        self.time_slots = [
            "8:00 - 8:50", "9:00 - 9:50", "10:00 - 10:50", "11:00 - 11:50",
            "12:00 - 12:50", "1:00 - 1:50", "2:00 - 2:50", "3:00 - 3:50", 
            "4:00 - 4:50", "5:00 - 5:50", "6:00 - 6:50"
        ]
        
        if not self.schedule_df.empty:
            # Extract unique rooms and create color mappings
            self.rooms = self.schedule_df['room_id'].unique()
            self.room_numbers = self.schedule_df.drop_duplicates('room_id')[['room_id', 'room_number']].set_index('room_id')['room_number'].to_dict()
            
            # Create color maps for rooms
            colors = plt.cm.Set3(np.linspace(0, 1, len(self.rooms)))
            self.room_colors = {room: mcolors.rgb2hex(color) for room, color in zip(self.rooms, colors)}
            
            # Course colors
            courses = self.schedule_df['course_code'].unique()
            course_colors = plt.cm.tab20(np.linspace(0, 1, len(courses)))
            self.course_colors = {course: mcolors.rgb2hex(color) for course, color in zip(courses, course_colors)}
        else:
            self.rooms = []
            self.room_numbers = {}
            self.room_colors = {}
            self.course_colors = {}
    
    def generate_all_room_visualizations(self) -> None:
        """Generate all room-related visualizations."""
        if self.schedule_df.empty:
            self.logger.warning("No schedule data available for room visualization")
            return
        
        self.logger.info("Generating room utilization visualizations...")
        
        try:
            # Generate individual visualizations
            self.generate_room_utilization_chart()
            self.generate_room_occupancy_heatmap()
            self.generate_room_efficiency_analysis()
            self.generate_room_capacity_analysis()
            self.generate_daily_room_usage()
            self.generate_room_conflict_visualization()
            
            # Generate comprehensive dashboard
            self.generate_room_dashboard()
            
            self.logger.info("Room visualizations generated successfully")
            
        except Exception as e:
            self.logger.error(f"Error generating room visualizations: {e}")
            self.logger.exception("Room visualization error details")
    
    def generate_room_utilization_chart(self) -> None:
        """Generate room utilization bar chart."""
        if self.schedule_df.empty:
            return
            
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 8))
        
        # Room usage count
        room_usage = self.schedule_df.groupby(['room_id', 'room_number']).size().reset_index(name='usage_count')
        room_usage = room_usage.sort_values('usage_count', ascending=False)
        
        bars1 = ax1.bar(range(len(room_usage)), room_usage['usage_count'])
        ax1.set_xticks(range(len(room_usage)))
        ax1.set_xticklabels([f"{row['room_number']}\n(ID: {row['room_id']})" for _, row in room_usage.iterrows()], 
                           rotation=45, ha='right')
        ax1.set_ylabel('Number of Assignments')
        ax1.set_title('Room Utilization - Assignment Count')
        ax1.grid(True, alpha=0.3)
        
        # Color bars according to room colors
        for i, (_, row) in enumerate(room_usage.iterrows()):
            bars1[i].set_color(self.room_colors.get(row['room_id'], '#CCCCCC'))
        
        # Room utilization percentage
        total_assignments = len(self.schedule_df)
        room_usage['percentage'] = (room_usage['usage_count'] / total_assignments) * 100
        
        bars2 = ax2.bar(range(len(room_usage)), room_usage['percentage'])
        ax2.set_xticks(range(len(room_usage)))
        ax2.set_xticklabels([f"{row['room_number']}\n(ID: {row['room_id']})" for _, row in room_usage.iterrows()], 
                           rotation=45, ha='right')
        ax2.set_ylabel('Percentage of Total Assignments (%)')
        ax2.set_title('Room Utilization - Percentage Distribution')
        ax2.grid(True, alpha=0.3)
        
        # Color bars according to room colors
        for i, (_, row) in enumerate(room_usage.iterrows()):
            bars2[i].set_color(self.room_colors.get(row['room_id'], '#CCCCCC'))
        
        # Add value labels on bars
        for i, (_, row) in enumerate(room_usage.iterrows()):
            ax1.text(i, row['usage_count'] + 0.5, str(row['usage_count']), 
                    ha='center', va='bottom', fontweight='bold')
            ax2.text(i, row['percentage'] + 0.5, f"{row['percentage']:.1f}%", 
                    ha='center', va='bottom', fontweight='bold')
        
        plt.tight_layout()
        plt.savefig(os.path.join(self.output_dir, 'room_utilization_chart.png'), 
                   dpi=300, bbox_inches='tight')
        plt.close(fig)
    
    def generate_room_occupancy_heatmap(self) -> None:
        """Generate room occupancy heatmap across time slots."""
        if self.schedule_df.empty:
            return
            
        # Create occupancy matrix
        occupancy_matrix = np.zeros((len(self.rooms), len(self.days) * len(self.time_slots)))
        room_labels = []
        time_labels = []
        
        # Prepare labels
        for room_id in self.rooms:
            room_labels.append(f"{self.room_numbers.get(room_id, room_id)}")
        
        for day in self.days:
            for slot in self.time_slots:
                time_labels.append(f"{day[:3].title()}\n{slot}")
        
        # Fill occupancy matrix
        for _, row in self.schedule_df.iterrows():
            room_idx = list(self.rooms).index(row['room_id'])
            day_idx = self.days.index(row['day'])
            slot_idx = row['slot_index']
            time_idx = day_idx * len(self.time_slots) + slot_idx
            
            if time_idx < len(time_labels):
                occupancy_matrix[room_idx, time_idx] = 1
        
        # Create heatmap
        fig, ax = plt.subplots(figsize=(20, 8))
        
        im = ax.imshow(occupancy_matrix, cmap='RdYlGn', aspect='auto', vmin=0, vmax=1)
        
        # Set ticks and labels
        ax.set_xticks(range(0, len(time_labels), 2))  # Show every 2nd time slot
        ax.set_xticklabels([time_labels[i] for i in range(0, len(time_labels), 2)], 
                          rotation=45, ha='right', fontsize=8)
        ax.set_yticks(range(len(room_labels)))
        ax.set_yticklabels(room_labels)
        
        # Add colorbar
        cbar = plt.colorbar(im, ax=ax)
        cbar.set_label('Room Occupied (1) / Free (0)')
        
        # Add grid
        ax.set_xticks(np.arange(-0.5, len(time_labels), 1), minor=True)
        ax.set_yticks(np.arange(-0.5, len(room_labels), 1), minor=True)
        ax.grid(which='minor', color='white', linestyle='-', linewidth=0.5)
        
        ax.set_title('Room Occupancy Heatmap - Time Slots vs Rooms')
        ax.set_xlabel('Time Slots (Day - Time)')
        ax.set_ylabel('Rooms')
        
        plt.tight_layout()
        plt.savefig(os.path.join(self.output_dir, 'room_occupancy_heatmap.png'), 
                   dpi=300, bbox_inches='tight')
        plt.close(fig)
    
    def generate_room_efficiency_analysis(self) -> None:
        """Generate room efficiency analysis charts."""
        if self.schedule_df.empty:
            return
            
        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(16, 12))
        
        # 1. Courses per room
        courses_per_room = self.schedule_df.groupby(['room_id', 'room_number'])['course_code'].nunique().reset_index()
        courses_per_room.columns = ['room_id', 'room_number', 'unique_courses']
        courses_per_room = courses_per_room.sort_values('unique_courses', ascending=False)
        
        bars1 = ax1.bar(range(len(courses_per_room)), courses_per_room['unique_courses'])
        ax1.set_xticks(range(len(courses_per_room)))
        ax1.set_xticklabels([row['room_number'] for _, row in courses_per_room.iterrows()], 
                           rotation=45, ha='right')
        ax1.set_ylabel('Number of Unique Courses')
        ax1.set_title('Course Diversity per Room')
        ax1.grid(True, alpha=0.3)
        
        for i, (_, row) in enumerate(courses_per_room.iterrows()):
            bars1[i].set_color(self.room_colors.get(row['room_id'], '#CCCCCC'))
            ax1.text(i, row['unique_courses'] + 0.1, str(row['unique_courses']), 
                    ha='center', va='bottom', fontweight='bold')
        
        # 2. Teachers per room
        teachers_per_room = self.schedule_df.groupby(['room_id', 'room_number'])['teacher_id'].nunique().reset_index()
        teachers_per_room.columns = ['room_id', 'room_number', 'unique_teachers']
        teachers_per_room = teachers_per_room.sort_values('unique_teachers', ascending=False)
        
        bars2 = ax2.bar(range(len(teachers_per_room)), teachers_per_room['unique_teachers'])
        ax2.set_xticks(range(len(teachers_per_room)))
        ax2.set_xticklabels([row['room_number'] for _, row in teachers_per_room.iterrows()], 
                           rotation=45, ha='right')
        ax2.set_ylabel('Number of Unique Teachers')
        ax2.set_title('Teacher Diversity per Room')
        ax2.grid(True, alpha=0.3)
        
        for i, (_, row) in enumerate(teachers_per_room.iterrows()):
            bars2[i].set_color(self.room_colors.get(row['room_id'], '#CCCCCC'))
            ax2.text(i, row['unique_teachers'] + 0.1, str(row['unique_teachers']), 
                    ha='center', va='bottom', fontweight='bold')
        
        # 3. Daily usage pattern
        daily_usage = self.schedule_df.groupby(['day', 'room_number']).size().unstack(fill_value=0)
        daily_usage.plot(kind='bar', stacked=True, ax=ax3, colormap='Set3')
        ax3.set_title('Daily Room Usage Pattern')
        ax3.set_xlabel('Day')
        ax3.set_ylabel('Number of Assignments')
        ax3.legend(title='Rooms', bbox_to_anchor=(1.05, 1), loc='upper left')
        ax3.tick_params(axis='x', rotation=45)
        
        # 4. Time slot efficiency
        hourly_usage = self.schedule_df.groupby('slot_index').size()
        ax4.bar(range(len(self.time_slots)), [hourly_usage.get(i, 0) for i in range(len(self.time_slots))])
        ax4.set_xticks(range(len(self.time_slots)))
        ax4.set_xticklabels([f"Slot {i}\n{slot}" for i, slot in enumerate(self.time_slots)], 
                           rotation=45, ha='right', fontsize=8)
        ax4.set_ylabel('Total Room Assignments')
        ax4.set_title('Time Slot Efficiency')
        ax4.grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.savefig(os.path.join(self.output_dir, 'room_efficiency_analysis.png'), 
                   dpi=300, bbox_inches='tight')
        plt.close(fig)
    
    def generate_room_capacity_analysis(self) -> None:
        """Generate room capacity vs usage analysis."""
        if self.schedule_df.empty or 'capacity' not in self.schedule_df.columns:
            return
            
        # Calculate capacity utilization
        room_capacity_data = self.schedule_df.groupby(['room_id', 'room_number', 'capacity']).agg({
            'student_count': 'mean',  # Average class size in this room
            'course_code': 'count'    # Number of assignments
        }).reset_index()
        room_capacity_data.columns = ['room_id', 'room_number', 'capacity', 'avg_class_size', 'assignments']
        
        # Calculate efficiency metrics
        room_capacity_data['capacity_utilization'] = (room_capacity_data['avg_class_size'] / room_capacity_data['capacity']) * 100
        room_capacity_data['capacity_utilization'] = room_capacity_data['capacity_utilization'].clip(0, 100)
        
        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(16, 12))
        
        # 1. Capacity vs Average Class Size
        ax1.scatter(room_capacity_data['capacity'], room_capacity_data['avg_class_size'], 
                   s=room_capacity_data['assignments']*5, alpha=0.6, 
                   c=[self.room_colors.get(room_id, '#CCCCCC') for room_id in room_capacity_data['room_id']])
        
        # Add diagonal line for 100% utilization
        max_capacity = room_capacity_data['capacity'].max()
        ax1.plot([0, max_capacity], [0, max_capacity], 'r--', alpha=0.5, label='100% Capacity')
        
        ax1.set_xlabel('Room Capacity')
        ax1.set_ylabel('Average Class Size')
        ax1.set_title('Room Capacity vs Average Class Size\n(Bubble size = Number of assignments)')
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        
        # Add room labels
        for _, row in room_capacity_data.iterrows():
            ax1.annotate(row['room_number'], 
                        (row['capacity'], row['avg_class_size']),
                        xytext=(5, 5), textcoords='offset points', fontsize=8)
        
        # 2. Capacity Utilization
        bars = ax2.bar(range(len(room_capacity_data)), room_capacity_data['capacity_utilization'])
        ax2.set_xticks(range(len(room_capacity_data)))
        ax2.set_xticklabels([row['room_number'] for _, row in room_capacity_data.iterrows()], 
                           rotation=45, ha='right')
        ax2.set_ylabel('Capacity Utilization (%)')
        ax2.set_title('Room Capacity Utilization')
        ax2.axhline(y=100, color='r', linestyle='--', alpha=0.5, label='100% Capacity')
        ax2.axhline(y=80, color='orange', linestyle='--', alpha=0.5, label='80% Efficient')
        ax2.legend()
        ax2.grid(True, alpha=0.3)
        
        # Color code bars based on utilization
        for i, util in enumerate(room_capacity_data['capacity_utilization']):
            if util > 100:
                bars[i].set_color('red')
            elif util > 80:
                bars[i].set_color('orange')
            elif util > 60:
                bars[i].set_color('yellow')
            else:
                bars[i].set_color('lightblue')
        
        # 3. Room Size Distribution
        ax3.hist(room_capacity_data['capacity'], bins=10, alpha=0.7, color='skyblue', edgecolor='black')
        ax3.set_xlabel('Room Capacity')
        ax3.set_ylabel('Number of Rooms')
        ax3.set_title('Room Size Distribution')
        ax3.grid(True, alpha=0.3)
        
        # 4. Efficiency Score
        room_capacity_data['efficiency_score'] = (
            (room_capacity_data['capacity_utilization'] / 100) * 0.6 +  # 60% weight to utilization
            (room_capacity_data['assignments'] / room_capacity_data['assignments'].max()) * 0.4  # 40% weight to usage frequency
        ) * 100
        
        bars4 = ax4.bar(range(len(room_capacity_data)), room_capacity_data['efficiency_score'])
        ax4.set_xticks(range(len(room_capacity_data)))
        ax4.set_xticklabels([row['room_number'] for _, row in room_capacity_data.iterrows()], 
                           rotation=45, ha='right')
        ax4.set_ylabel('Efficiency Score (%)')
        ax4.set_title('Overall Room Efficiency Score\n(60% utilization + 40% usage frequency)')
        ax4.grid(True, alpha=0.3)
        
        # Color bars based on efficiency score
        for i, score in enumerate(room_capacity_data['efficiency_score']):
            if score >= 80:
                bars4[i].set_color('green')
            elif score >= 60:
                bars4[i].set_color('yellow')
            else:
                bars4[i].set_color('red')
        
        plt.tight_layout()
        plt.savefig(os.path.join(self.output_dir, 'room_capacity_analysis.png'), 
                   dpi=300, bbox_inches='tight')
        plt.close(fig)
    
    def generate_daily_room_usage(self) -> None:
        """Generate daily room usage patterns."""
        if self.schedule_df.empty:
            return
            
        fig, axes = plt.subplots(len(self.days), 1, figsize=(16, 3*len(self.days)))
        
        if len(self.days) == 1:
            axes = [axes]
        
        for day_idx, day in enumerate(self.days):
            day_data = self.schedule_df[self.schedule_df['day'] == day]
            
            if day_data.empty:
                axes[day_idx].text(0.5, 0.5, f'No assignments for {day.title()}', 
                                  ha='center', va='center', transform=axes[day_idx].transAxes)
                axes[day_idx].set_title(f'{day.title()} - Room Usage')
                continue
            
            # Create usage matrix for this day
            room_slot_matrix = np.zeros((len(self.rooms), len(self.time_slots)))
            
            for _, row in day_data.iterrows():
                room_idx = list(self.rooms).index(row['room_id'])
                slot_idx = row['slot_index']
                if slot_idx < len(self.time_slots):
                    room_slot_matrix[room_idx, slot_idx] = 1
            
            # Plot heatmap for this day
            im = axes[day_idx].imshow(room_slot_matrix, cmap='RdYlGn', aspect='auto', vmin=0, vmax=1)
            
            axes[day_idx].set_xticks(range(len(self.time_slots)))
            axes[day_idx].set_xticklabels([f"Slot {i}\n{slot}" for i, slot in enumerate(self.time_slots)], 
                                         rotation=45, ha='right', fontsize=8)
            axes[day_idx].set_yticks(range(len(self.rooms)))
            axes[day_idx].set_yticklabels([self.room_numbers.get(room, room) for room in self.rooms])
            axes[day_idx].set_title(f'{day.title()} - Room Usage Pattern')
            
            # Add grid
            axes[day_idx].set_xticks(np.arange(-0.5, len(self.time_slots), 1), minor=True)
            axes[day_idx].set_yticks(np.arange(-0.5, len(self.rooms), 1), minor=True)
            axes[day_idx].grid(which='minor', color='white', linestyle='-', linewidth=0.5)
        
        plt.tight_layout()
        plt.savefig(os.path.join(self.output_dir, 'daily_room_usage.png'), 
                   dpi=300, bbox_inches='tight')
        plt.close(fig)
    
    def generate_room_conflict_visualization(self) -> None:
        """Generate visualization for potential room conflicts."""
        if self.schedule_df.empty:
            return
            
        # Find potential conflicts (same room, same time slot)
        conflicts = []
        grouped = self.schedule_df.groupby(['day', 'slot_index', 'room_id'])
        
        for (day, slot_idx, room_id), group in grouped:
            if len(group) > 1:
                conflicts.append({
                    'day': day,
                    'slot_index': slot_idx,
                    'room_id': room_id,
                    'room_number': group.iloc[0]['room_number'],
                    'conflicts': len(group),
                    'courses': list(group['course_code'])
                })
        
        if not conflicts:
            # No conflicts - create a success visualization
            fig, ax = plt.subplots(figsize=(12, 8))
            ax.text(0.5, 0.5, '✅ NO ROOM CONFLICTS DETECTED\n\nAll room assignments are properly scheduled\nwithout overlapping conflicts!', 
                   ha='center', va='center', transform=ax.transAxes, 
                   fontsize=20, fontweight='bold', color='green',
                   bbox=dict(boxstyle="round,pad=0.5", facecolor='lightgreen', alpha=0.7))
            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)
            ax.axis('off')
            ax.set_title('Room Conflict Analysis', fontsize=16, fontweight='bold')
            
            plt.tight_layout()
            plt.savefig(os.path.join(self.output_dir, 'room_conflict_visualization.png'), 
                       dpi=300, bbox_inches='tight')
            plt.close(fig)
            return
        
        # Visualize conflicts
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 8))
        
        # Conflict count by room
        conflict_rooms = {}
        for conflict in conflicts:
            room_number = conflict['room_number']
            conflict_rooms[room_number] = conflict_rooms.get(room_number, 0) + conflict['conflicts']
        
        bars1 = ax1.bar(range(len(conflict_rooms)), list(conflict_rooms.values()), color='red', alpha=0.7)
        ax1.set_xticks(range(len(conflict_rooms)))
        ax1.set_xticklabels(list(conflict_rooms.keys()), rotation=45, ha='right')
        ax1.set_ylabel('Number of Conflicts')
        ax1.set_title('Room Conflicts by Room')
        ax1.grid(True, alpha=0.3)
        
        for i, (room, count) in enumerate(conflict_rooms.items()):
            ax1.text(i, count + 0.1, str(count), ha='center', va='bottom', fontweight='bold')
        
        # Conflict timeline
        conflict_timeline = {}
        for conflict in conflicts:
            time_key = f"{conflict['day']}_slot_{conflict['slot_index']}"
            conflict_timeline[time_key] = conflict_timeline.get(time_key, 0) + conflict['conflicts']
        
        ax2.bar(range(len(conflict_timeline)), list(conflict_timeline.values()), color='orange', alpha=0.7)
        ax2.set_xticks(range(len(conflict_timeline)))
        ax2.set_xticklabels(list(conflict_timeline.keys()), rotation=45, ha='right')
        ax2.set_ylabel('Number of Conflicts')
        ax2.set_title('Room Conflicts by Time Slot')
        ax2.grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.savefig(os.path.join(self.output_dir, 'room_conflict_visualization.png'), 
                   dpi=300, bbox_inches='tight')
        plt.close(fig)
    
    def generate_room_dashboard(self) -> None:
        """Generate comprehensive room analysis dashboard."""
        if self.schedule_df.empty:
            return
            
        fig = plt.figure(figsize=(20, 24))
        gs = GridSpec(6, 2, figure=fig, hspace=0.3, wspace=0.3)
        
        # Title
        fig.suptitle('Comprehensive Room Analysis Dashboard', fontsize=20, fontweight='bold', y=0.98)
        
        # 1. Room utilization summary
        ax1 = fig.add_subplot(gs[0, :])
        room_usage = self.schedule_df.groupby(['room_id', 'room_number']).size().reset_index(name='usage_count')
        room_usage = room_usage.sort_values('usage_count', ascending=True)
        
        bars = ax1.barh(range(len(room_usage)), room_usage['usage_count'])
        ax1.set_yticks(range(len(room_usage)))
        ax1.set_yticklabels([f"{row['room_number']} (ID: {row['room_id']})" for _, row in room_usage.iterrows()])
        ax1.set_xlabel('Number of Assignments')
        ax1.set_title('Room Utilization Overview', fontweight='bold')
        ax1.grid(True, alpha=0.3)
        
        for i, (_, row) in enumerate(room_usage.iterrows()):
            bars[i].set_color(self.room_colors.get(row['room_id'], '#CCCCCC'))
            ax1.text(row['usage_count'] + 0.5, i, str(row['usage_count']), 
                    va='center', fontweight='bold')
        
        # 2. Daily distribution
        ax2 = fig.add_subplot(gs[1, 0])
        daily_counts = self.schedule_df['day'].value_counts()
        daily_counts = daily_counts.reindex(self.days, fill_value=0)
        
        ax2.pie(daily_counts.values, labels=[day.title() for day in daily_counts.index], 
               autopct='%1.1f%%', startangle=90)
        ax2.set_title('Daily Assignment Distribution', fontweight='bold')
        
        # 3. Time slot efficiency
        ax3 = fig.add_subplot(gs[1, 1])
        hourly_usage = self.schedule_df.groupby('slot_index').size()
        ax3.bar(range(len(self.time_slots)), [hourly_usage.get(i, 0) for i in range(len(self.time_slots))])
        ax3.set_xticks(range(len(self.time_slots)))
        ax3.set_xticklabels([f"S{i}" for i in range(len(self.time_slots))], rotation=45)
        ax3.set_ylabel('Assignments')
        ax3.set_title('Time Slot Efficiency', fontweight='bold')
        ax3.grid(True, alpha=0.3)
        
        # 4. Course diversity
        ax4 = fig.add_subplot(gs[2, 0])
        courses_per_room = self.schedule_df.groupby(['room_id', 'room_number'])['course_code'].nunique().reset_index()
        courses_per_room.columns = ['room_id', 'room_number', 'unique_courses']
        courses_per_room = courses_per_room.sort_values('unique_courses', ascending=False)
        
        bars4 = ax4.bar(range(len(courses_per_room)), courses_per_room['unique_courses'])
        ax4.set_xticks(range(len(courses_per_room)))
        ax4.set_xticklabels([row['room_number'] for _, row in courses_per_room.iterrows()], 
                           rotation=45, ha='right')
        ax4.set_ylabel('Unique Courses')
        ax4.set_title('Course Diversity per Room', fontweight='bold')
        ax4.grid(True, alpha=0.3)
        
        # 5. Teacher diversity
        ax5 = fig.add_subplot(gs[2, 1])
        teachers_per_room = self.schedule_df.groupby(['room_id', 'room_number'])['teacher_id'].nunique().reset_index()
        teachers_per_room.columns = ['room_id', 'room_number', 'unique_teachers']
        teachers_per_room = teachers_per_room.sort_values('unique_teachers', ascending=False)
        
        bars5 = ax5.bar(range(len(teachers_per_room)), teachers_per_room['unique_teachers'])
        ax5.set_xticks(range(len(teachers_per_room)))
        ax5.set_xticklabels([row['room_number'] for _, row in teachers_per_room.iterrows()], 
                           rotation=45, ha='right')
        ax5.set_ylabel('Unique Teachers')
        ax5.set_title('Teacher Diversity per Room', fontweight='bold')
        ax5.grid(True, alpha=0.3)
        
        # 6. Room occupancy heatmap (simplified)
        ax6 = fig.add_subplot(gs[3:5, :])
        
        # Create simplified occupancy matrix (room x day)
        room_day_matrix = np.zeros((len(self.rooms), len(self.days)))
        room_labels = [self.room_numbers.get(room, room) for room in self.rooms]
        
        for _, row in self.schedule_df.iterrows():
            room_idx = list(self.rooms).index(row['room_id'])
            day_idx = self.days.index(row['day'])
            room_day_matrix[room_idx, day_idx] += 1
        
        im = ax6.imshow(room_day_matrix, cmap='YlOrRd', aspect='auto')
        ax6.set_xticks(range(len(self.days)))
        ax6.set_xticklabels([day.title() for day in self.days])
        ax6.set_yticks(range(len(room_labels)))
        ax6.set_yticklabels(room_labels)
        ax6.set_title('Room Usage Intensity by Day', fontweight='bold')
        
        # Add colorbar
        cbar = plt.colorbar(im, ax=ax6)
        cbar.set_label('Number of Assignments')
        
        # Add text annotations
        for i in range(len(self.rooms)):
            for j in range(len(self.days)):
                if room_day_matrix[i, j] > 0:
                    ax6.text(j, i, int(room_day_matrix[i, j]), 
                            ha='center', va='center', fontweight='bold', 
                            color='white' if room_day_matrix[i, j] > room_day_matrix.max()/2 else 'black')
        
        # 7. Summary statistics
        ax7 = fig.add_subplot(gs[5, :])
        ax7.axis('off')
        
        # Calculate summary stats
        total_assignments = len(self.schedule_df)
        total_rooms = len(self.rooms)
        avg_assignments_per_room = total_assignments / total_rooms if total_rooms > 0 else 0
        most_used_room = room_usage.iloc[-1]['room_number'] if not room_usage.empty else 'N/A'
        least_used_room = room_usage.iloc[0]['room_number'] if not room_usage.empty else 'N/A'
        
        summary_text = f"""
        SUMMARY STATISTICS:
        • Total Assignments: {total_assignments}
        • Total Rooms Used: {total_rooms}
        • Average Assignments per Room: {avg_assignments_per_room:.1f}
        • Most Used Room: {most_used_room} ({room_usage.iloc[-1]['usage_count'] if not room_usage.empty else 0} assignments)
        • Least Used Room: {least_used_room} ({room_usage.iloc[0]['usage_count'] if not room_usage.empty else 0} assignments)
        • Room Utilization Efficiency: {(total_rooms / 90 * 100):.1f}% (using {total_rooms} out of 90 available rooms)
        """
        
        ax7.text(0.05, 0.5, summary_text, transform=ax7.transAxes, fontsize=12, 
                verticalalignment='center', bbox=dict(boxstyle="round,pad=0.5", facecolor='lightblue', alpha=0.7))
        
        plt.savefig(os.path.join(self.output_dir, 'room_analysis_dashboard.png'), 
                   dpi=300, bbox_inches='tight')
        plt.close(fig) 