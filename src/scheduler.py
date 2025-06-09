import os
import sys
import pandas as pd
import numpy as np
import logging
import json
from datetime import datetime
from ortools.sat.python import cp_model

# Fix import issues when running from different locations
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

# Try to import constraints in different ways based on how the script is run
try:
    from constraints import TimetableConstraints
except ImportError:
    try:
        from src.constraints import TimetableConstraints
    except ImportError:
        from timetable_scheduler.src.constraints import TimetableConstraints

class TimetableScheduler:
    def __init__(self, course_file, room_file):
        """Initialize the timetable scheduler with course and room data."""
        self.logger = logging.getLogger(__name__)
        
        # Load the data
        self.courses_df = pd.read_csv(course_file)
        self.rooms_df = pd.read_csv(room_file)
        
        # Setup time slots
        self.days = ["tuesday", "wed", "thur", "fri", "sat"]  # Excluding Monday
        self.num_days = len(self.days)
        
        # Pre-compute room IDs for efficiency
        self.classroom_ids = None  # Will be initialized after classrooms are processed
        
        # Time slots (11 slots per day - Theory timing)
        self.time_slots = [
            "8:00 - 8:50", "9:00 - 9:50", "10:00 - 10:50", "11:00 - 11:50",
            "12:00 - 12:50", "1:00 - 1:50", "2:00 - 2:50", "3:00 - 3:50", 
            "4:00 - 4:50", "5:00 - 5:50", "6:00 - 6:50"
        ]
        self.num_slots = len(self.time_slots)
        
        # Lab time slots (12 slots per day - Lab timing structure)
        self.lab_time_slots = [
            "8:00 - 8:50", "8:50 - 9:40", "9:50 - 10:40", "10:40 - 11:30",
            "11:50 - 12:40", "12:40 - 1:30", "1:50 - 2:40", "2:40 - 3:30", 
            "3:50 - 4:40", "4:40 - 5:30", "5:30 - 6:20", "6:20 - 7:10"
        ]
        self.num_lab_slots = len(self.lab_time_slots)
        
        # Group lab slots into 2-hour sessions
        self.lab_sessions = {
            'L1': {'slots': [0, 1], 'time_range': '8:00 - 9:40'},
            'L2': {'slots': [2, 3], 'time_range': '9:50 - 11:30'},
            'L3': {'slots': [4, 5], 'time_range': '11:50 - 1:30'},
            'L4': {'slots': [6, 7], 'time_range': '1:50 - 3:30'},
            'L5': {'slots': [8, 9], 'time_range': '3:50 - 5:30'},
            'L6': {'slots': [10, 11], 'time_range': '5:30 - 7:10'}
        }
        self.num_lab_sessions = len(self.lab_sessions)
        
        # Process rooms - separate classrooms and labs
        self.classrooms = self.rooms_df[self.rooms_df['is_lab'] == 0]
        self.labs = self.rooms_df[self.rooms_df['is_lab'] == 1]
        
        # Initialize room IDs
        if not self.classrooms.empty:
            self.classroom_ids = self.classrooms['id'].tolist()
        else:
            self.classroom_ids = []
            
        # Process teacher-course assignments
        self.process_teacher_courses()
    
    def process_teacher_courses(self):
        """Process the teacher-course assignments from the CSV data."""
        # Extract unique teachers
        self.teachers = self.courses_df['teacher_id'].unique()
        self.num_teachers = len(self.teachers)
        self.logger.info(f"Processing {self.num_teachers} teachers")
        
        # Extract unique courses
        self.courses = self.courses_df[['course_id', 'course_code', 'course_name']].drop_duplicates()
        self.num_courses = len(self.courses)
        self.logger.info(f"Processing {self.num_courses} unique courses")
        
        # Create a mapping of teachers to their courses with required hours
        self.teacher_course_assignments = {}
        for _, row in self.courses_df.iterrows():
            teacher_id = row['teacher_id']
            course_id = row['course_id']
            
            if teacher_id not in self.teacher_course_assignments:
                self.teacher_course_assignments[teacher_id] = []
            
            # Create a unique identifier for each course instance
            course_instance_id = str(row['id'])
            
            self.teacher_course_assignments[teacher_id].append({
                'id': course_instance_id,
                'course_id': course_id,
                'course_code': row['course_code'],
                'course_name': row['course_name'],
                'course_type': row['course_type'],
                'lecture_hours': int(row['lecture_hours']),
                'tutorial_hours': int(row['tutorial_hours']),
                'practical_hours': int(row['practical_hours']),
                'student_count': int(row['student_count']),
                'semester': row.get('semester', 1),
                'course_dept': row.get('course_dept', 'Computer Science & Engineering')
            })
    
    def generate_timetable(self):
        """Generate the timetable using OR-Tools CP-SAT solver."""
        self.logger.info("Starting timetable generation...")
        
        # Create the CP-SAT model
        model = cp_model.CpModel()
        
        # Define assignment variables
        # teacher_theory_assignments[t][d][s][r] = 1 if teacher t is assigned to classroom r in slot s on day d
        teacher_theory_assignments = {}
        for teacher in self.teachers:
            teacher_theory_assignments[teacher] = {}
            for d in range(self.num_days):
                teacher_theory_assignments[teacher][d] = {}
                for s in range(self.num_slots):
                    teacher_theory_assignments[teacher][d][s] = {}
                    for room_id in self.classroom_ids:
                        teacher_theory_assignments[teacher][d][s][room_id] = model.NewBoolVar(
                            f'teacher_{teacher}_day_{d}_slot_{s}_classroom_{room_id}')
        
        # Initialize constraints handler
        constraints = TimetableConstraints(
            model, 
            self.teachers, 
            self.teacher_course_assignments,
            self.classrooms, 
            self.labs
        )
        
        # Apply all constraints
        constraints.apply_all_constraints(teacher_theory_assignments)
        
        # Create the solver and solve the model
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 300  # 5 minutes time limit
        
        self.logger.info("Solving the scheduling model...")
        status = solver.Solve(model)
        
        if status == cp_model.OPTIMAL:
            self.logger.info("Optimal solution found!")
            return True
        elif status == cp_model.FEASIBLE:
            self.logger.info("Feasible solution found!")
            return True
        elif status == cp_model.INFEASIBLE:
            self.logger.error("Problem is infeasible - no solution possible with current constraints")
            return False
        else:
            self.logger.warning(f"No solution found. Status: {status}")
            return False
