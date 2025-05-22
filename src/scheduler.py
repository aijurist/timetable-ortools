import os
import pandas as pd
import numpy as np
import logging
import json
from datetime import datetime
from ortools.sat.python import cp_model
from src.utils.visualizer import TimetableVisualizer
from src.constraints import TimetableConstraints

class TimetableScheduler:
    def __init__(self, course_file, room_file):
        """Initialize the timetable scheduler with course and room data."""
        self.logger = logging.getLogger(__name__)
        
        # Load the data
        self.courses_df = pd.read_csv(course_file)
        self.rooms_df = pd.read_csv(room_file)
        
        # Setup time slots
        self.days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
        self.num_days = len(self.days)
        
        # Theory slots: 11 slots per day of 50 min each (with 10 min break)
        self.theory_slots = [f"{h}:00-{h}:50" for h in range(8, 19)]
        self.num_theory_slots = len(self.theory_slots)
        
        # Lab slots: 5 slots per day of 1hr:50min each (with 10 min break)
        self.lab_slots = ["8:00-9:50", "10:00-11:50", "12:00-13:50", "14:00-15:50", "16:00-17:50"]
        self.num_lab_slots = len(self.lab_slots)
        
        # Process rooms - separate classrooms and labs
        self.classrooms = self.rooms_df[self.rooms_df['is_lab'] == 0]
        self.labs = self.rooms_df[self.rooms_df['is_lab'] == 1]
        
        # Process teacher-course assignments
        self.process_teacher_courses()
        
        # Create output directory
        self.output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
                                      'output', 
                                      f'schedule_{datetime.now().strftime("%Y%m%d_%H%M%S")}')
        os.makedirs(self.output_dir, exist_ok=True)
    
    def process_teacher_courses(self):
        """Process the teacher-course assignments from the CSV data."""
        # Extract unique teachers
        self.teachers = self.courses_df['teacher_id'].unique()
        self.num_teachers = len(self.teachers)
        
        # Extract unique courses
        self.courses = self.courses_df[['course_id', 'course_code', 'course_name']].drop_duplicates()
        self.num_courses = len(self.courses)
        
        # Create a mapping of teachers to their courses with required hours
        self.teacher_course_assignments = {}
        for _, row in self.courses_df.iterrows():
            teacher_id = row['teacher_id']
            course_id = row['course_id']
            
            if teacher_id not in self.teacher_course_assignments:
                self.teacher_course_assignments[teacher_id] = []
            
            self.teacher_course_assignments[teacher_id].append({
                'course_id': course_id,
                'course_code': row['course_code'],
                'course_name': row['course_name'],
                'course_type': row['course_type'],
                'lecture_hours': int(row['lecture_hours']),
                'tutorial_hours': int(row['tutorial_hours']),
                'practical_hours': int(row['practical_hours']),
                'student_count': int(row['student_count'])
            })
    
    def generate_timetable(self):
        """Generate the timetable using OR-Tools CP-SAT solver."""
        self.logger.info("Starting timetable generation...")
        
        # Create the CP-SAT model
        model = cp_model.CpModel()
        
        # Define variables
        # teacher_theory_assignments[t][d][s][r] = 1 if teacher t is assigned to theory slot s on day d in room r
        teacher_theory_assignments = {}
        for t_idx, teacher in enumerate(self.teachers):
            teacher_theory_assignments[teacher] = {}
            for d in range(self.num_days):
                teacher_theory_assignments[teacher][d] = {}
                for s in range(self.num_theory_slots):
                    teacher_theory_assignments[teacher][d][s] = {}
                    for _, room_row in self.classrooms.iterrows():
                        room_id = room_row['id']
                        teacher_theory_assignments[teacher][d][s][room_id] = model.NewBoolVar(
                            f'teacher_{teacher}_day_{d}_theory_slot_{s}_room_{room_id}')
        
        # teacher_lab_assignments[t][d][s][r] = 1 if teacher t is assigned to lab slot s on day d in room r
        teacher_lab_assignments = {}
        for t_idx, teacher in enumerate(self.teachers):
            teacher_lab_assignments[teacher] = {}
            for d in range(self.num_days):
                teacher_lab_assignments[teacher][d] = {}
                for s in range(self.num_lab_slots):
                    teacher_lab_assignments[teacher][d][s] = {}
                    for _, room_row in self.labs.iterrows():
                        room_id = room_row['id']
                        teacher_lab_assignments[teacher][d][s][room_id] = model.NewBoolVar(
                            f'teacher_{teacher}_day_{d}_lab_slot_{s}_room_{room_id}')
        
        # Initialize constraints handler
        constraints = TimetableConstraints(
            model, 
            self.teachers, 
            self.days, 
            self.theory_slots, 
            self.lab_slots, 
            self.classrooms, 
            self.labs, 
            self.teacher_course_assignments
        )
        
        # Apply all constraints
        constraints.apply_all_constraints(teacher_theory_assignments, teacher_lab_assignments)
        
        # Generate constraint summary for reporting
        constraint_summary = constraints.generate_constraint_summary()
        self.save_constraint_summary(constraint_summary)
        
        # Create the solver and solve the model
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 300  # 5 minutes time limit
        
        self.logger.info("Solving the model...")
        status = solver.Solve(model)
        
        if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
            self.logger.info(f"Solution found with status {status}!")
            
            # Process the solution
            schedule_df = self.process_solution(solver, teacher_theory_assignments, teacher_lab_assignments)
            
            # Generate visualizations
            if not schedule_df.empty:
                self.generate_visualizations(schedule_df)
            
            return True
        else:
            self.logger.warning(f"No solution found. Status: {status}")
            return False
    
    def save_constraint_summary(self, constraint_summary):
        """Save the constraint summary to a JSON file."""
        constraint_summary_path = os.path.join(self.output_dir, 'constraint_summary.json')
        with open(constraint_summary_path, 'w') as f:
            json.dump(constraint_summary, f, indent=4)
        
        # Also generate a human-readable text version
        constraint_summary_txt_path = os.path.join(self.output_dir, 'constraint_summary.txt')
        with open(constraint_summary_txt_path, 'w') as f:
            f.write("Timetable Scheduling Constraints Summary\n")
            f.write("=====================================\n\n")
            
            for constraint_id, constraint_info in constraint_summary.items():
                f.write(f"Constraint: {constraint_info['name']}\n")
                f.write(f"Description: {constraint_info['description']}\n")
                f.write(f"Impact: {constraint_info['impact']}\n")
                
                # Handle the new complexity structure
                complexity = constraint_info['complexity']
                if isinstance(complexity, dict):
                    f.write(f"Computational Complexity: {complexity['formula']}\n")
                    f.write(f"Complexity Level: {complexity['level']}\n")
                    f.write(f"Explanation: {complexity['explanation']}\n")
                    if 'notes' in complexity:
                        f.write(f"Notes: {complexity['notes']}\n")
                else:
                    f.write(f"Computational Complexity: {complexity}\n")
                
                # Include example if available
                if 'example' in constraint_info:
                    f.write(f"\nExample:\n{constraint_info['example']}\n")
                
                f.write("\n" + "-" * 60 + "\n\n")
        
        self.logger.info(f"Constraint summaries saved to {self.output_dir}")
    
    def process_solution(self, solver, teacher_theory_assignments, teacher_lab_assignments):
        """Process the solution and save the results."""
        # Create a dataframe to store the schedule
        schedule_data = []
        
        # Process theory assignments
        for teacher in self.teachers:
            for d in range(self.num_days):
                for s in range(self.num_theory_slots):
                    for _, room_row in self.classrooms.iterrows():
                        room_id = room_row['id']
                        if solver.Value(teacher_theory_assignments[teacher][d][s][room_id]) == 1:
                            # Find which course this teacher is teaching
                            if teacher in self.teacher_course_assignments:
                                for course_info in self.teacher_course_assignments[teacher]:
                                    # We don't know which specific course is assigned to this slot,
                                    # so we'll just pick one that has lecture hours
                                    if course_info['lecture_hours'] > 0:
                                        schedule_data.append({
                                            'day': self.days[d],
                                            'slot_type': 'Theory',
                                            'slot_time': self.theory_slots[s],
                                            'teacher_id': teacher,
                                            'room_id': room_id,
                                            'room_number': room_row['room_number'],
                                            'course_id': course_info['course_id'],
                                            'course_code': course_info['course_code'],
                                            'course_name': course_info['course_name'],
                                        })
                                        break
        
        # Process lab assignments
        for teacher in self.teachers:
            for d in range(self.num_days):
                for s in range(self.num_lab_slots):
                    for _, room_row in self.labs.iterrows():
                        room_id = room_row['id']
                        if solver.Value(teacher_lab_assignments[teacher][d][s][room_id]) == 1:
                            # Find which course this teacher is teaching
                            if teacher in self.teacher_course_assignments:
                                for course_info in self.teacher_course_assignments[teacher]:
                                    # We don't know which specific course is assigned to this slot,
                                    # so we'll just pick one that has practical hours
                                    if course_info['practical_hours'] > 0:
                                        schedule_data.append({
                                            'day': self.days[d],
                                            'slot_type': 'Lab',
                                            'slot_time': self.lab_slots[s],
                                            'teacher_id': teacher,
                                            'room_id': room_id,
                                            'room_number': room_row['room_number'],
                                            'course_id': course_info['course_id'],
                                            'course_code': course_info['course_code'],
                                            'course_name': course_info['course_name'],
                                        })
                                        break
        
        # Create a dataframe from the schedule data
        if schedule_data:
            schedule_df = pd.DataFrame(schedule_data)
            
            # Save the schedule to a CSV file
            schedule_csv_path = os.path.join(self.output_dir, 'schedule.csv')
            schedule_df.to_csv(schedule_csv_path, index=False)
            self.logger.info(f"Schedule saved to {schedule_csv_path}")
            
            # Generate separate schedules for each teacher
            for teacher in self.teachers:
                teacher_schedule = schedule_df[schedule_df['teacher_id'] == teacher]
                if not teacher_schedule.empty:
                    teacher_schedule_path = os.path.join(self.output_dir, f'teacher_{teacher}_schedule.csv')
                    teacher_schedule.to_csv(teacher_schedule_path, index=False)
            
            # Generate separate schedules for each room
            for _, room_row in pd.concat([self.classrooms, self.labs]).iterrows():
                room_id = room_row['id']
                room_schedule = schedule_df[schedule_df['room_id'] == room_id]
                if not room_schedule.empty:
                    room_schedule_path = os.path.join(self.output_dir, f'room_{room_id}_schedule.csv')
                    room_schedule.to_csv(room_schedule_path, index=False)
            
            # Generate a summary
            self.generate_summary(schedule_df)
            
            return schedule_df
        
        return pd.DataFrame()
    
    def generate_visualizations(self, schedule_df):
        """Generate visualizations for the timetable."""
        self.logger.info("Generating visualizations...")
        
        # Create visualizer
        visualizer = TimetableVisualizer(schedule_df, self.output_dir)
        
        # Generate schedules
        visualizer.generate_master_schedule()
        visualizer.generate_teacher_schedules()
        visualizer.generate_room_schedules()
        
        self.logger.info(f"Visualizations saved to {self.output_dir}")
    
    def generate_summary(self, schedule_df):
        """Generate a summary of the schedule."""
        summary_path = os.path.join(self.output_dir, 'summary.txt')
        with open(summary_path, 'w') as f:
            f.write("Timetable Schedule Summary\n")
            f.write("=========================\n\n")
            
            # Count of scheduled classes
            theory_count = len(schedule_df[schedule_df['slot_type'] == 'Theory'])
            lab_count = len(schedule_df[schedule_df['slot_type'] == 'Lab'])
            f.write(f"Total scheduled theory classes: {theory_count}\n")
            f.write(f"Total scheduled lab classes: {lab_count}\n\n")
            
            # Teachers with assignments
            teachers_scheduled = schedule_df['teacher_id'].nunique()
            f.write(f"Total teachers scheduled: {teachers_scheduled} out of {self.num_teachers}\n\n")
            
            # Rooms utilized
            rooms_scheduled = schedule_df['room_id'].nunique()
            total_rooms = len(self.classrooms) + len(self.labs)
            f.write(f"Total rooms utilized: {rooms_scheduled} out of {total_rooms}\n\n")
            
            # Teacher-Course assignments
            f.write("Teacher-Course Assignments:\n")
            for teacher in self.teachers:
                teacher_courses = schedule_df[schedule_df['teacher_id'] == teacher]['course_code'].unique()
                if len(teacher_courses) > 0:
                    f.write(f"Teacher {teacher}: {', '.join(teacher_courses)}\n")
            
            f.write("\n\nSchedule generated on: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        
        self.logger.info(f"Summary saved to {summary_path}") 