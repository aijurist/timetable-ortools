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
        
        # Lab slots: 6 slots per day based on provided image
        self.lab_slots = [
            "8:00-9:40",    # L1
            "10:00-11:40",  # L2 
            "11:40-1:20",   # L3
            "1:20-3:00",    # L4
            "3:00-4:40",    # L5
            "5:10-6:50"     # L6
        ]
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
        # Each entry in the data is treated as a separate teaching assignment
        self.teacher_course_assignments = {}
        for _, row in self.courses_df.iterrows():
            teacher_id = row['teacher_id']
            course_id = row['course_id']
            
            if teacher_id not in self.teacher_course_assignments:
                self.teacher_course_assignments[teacher_id] = []
            
            # Create a unique identifier for each course instance
            # This will help us track each instance separately
            course_instance_id = str(row['id'])
            
            self.teacher_course_assignments[teacher_id].append({
                'id': course_instance_id,  # Add the original row ID as a course instance identifier
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
        
        # Create tracking structures for assigned slots per course instance
        instance_tracking = {}
        for teacher_id, courses in self.teacher_course_assignments.items():
            instance_tracking[teacher_id] = {}
            for course in courses:
                instance_id = course['id']
                instance_tracking[teacher_id][instance_id] = {
                    'theory_allocated': 0,
                    'lab_allocated': 0,
                    'batch_tracking': {},  # Track lab batches
                    'required_theory': course['lecture_hours'],
                    'required_lab': course['practical_hours'],
                    'student_count': course['student_count'],
                    'course_info': course,
                    'days_used': set()  # Track which days are used for this instance
                }
                
                # Calculate number of batches needed for this course instance
                if course['student_count'] > 35 and course['practical_hours'] > 0:
                    num_batches = (course['student_count'] + 34) // 35
                    for batch_num in range(1, num_batches+1):
                        instance_tracking[teacher_id][instance_id]['batch_tracking'][batch_num] = {
                            'slots_allocated': 0,
                            'required_slots': (course['practical_hours'] + 1) // 2  # Required lab slots per batch
                        }
        
        # Process theory assignments first
        for teacher in self.teachers:
            for d in range(self.num_days):
                for s in range(self.num_theory_slots):
                    for _, room_row in self.classrooms.iterrows():
                        room_id = room_row['id']
                        if solver.Value(teacher_theory_assignments[teacher][d][s][room_id]) == 1:
                            # Find which course instance to assign this slot to
                            if teacher in self.teacher_course_assignments:
                                # Find course instances that need more theory slots
                                available_instances = []
                                for course_info in self.teacher_course_assignments[teacher]:
                                    instance_id = course_info['id']
                                    tracking = instance_tracking[teacher][instance_id]
                                    if (course_info['lecture_hours'] > 0 and 
                                        tracking['theory_allocated'] < tracking['required_theory']):
                                        available_instances.append({
                                            'instance_id': instance_id,
                                            'remaining': tracking['required_theory'] - tracking['theory_allocated'],
                                            'course_info': course_info
                                        })
                                
                                if available_instances:
                                    # Select the instance with the most remaining required hours
                                    available_instances.sort(key=lambda x: x['remaining'], reverse=True)
                                    selected = available_instances[0]
                                    instance_id = selected['instance_id']
                                    course_info = selected['course_info']
                                    
                                    # Update tracking
                                    instance_tracking[teacher][instance_id]['theory_allocated'] += 1
                                    instance_tracking[teacher][instance_id]['days_used'].add(d)
                                    
                                    # Find teacher information from the original data
                                    teacher_rows = self.courses_df[self.courses_df['teacher_id'] == teacher]
                                    teacher_first_name = ""
                                    teacher_last_name = ""
                                    staff_code = ""
                                    if not teacher_rows.empty:
                                        first_row = teacher_rows.iloc[0]
                                        if 'first_name' in first_row:
                                            teacher_first_name = first_row['first_name']
                                        if 'last_name' in first_row:
                                            teacher_last_name = first_row['last_name']
                                        if 'staff_code' in first_row:
                                            staff_code = first_row['staff_code']
                                    
                                    schedule_data.append({
                                        'day': self.days[d],
                                        'slot_type': 'Theory',
                                        'slot_time': self.theory_slots[s],
                                        'teacher_id': teacher,
                                        'first_name': teacher_first_name,
                                        'last_name': teacher_last_name,
                                        'staff_code': staff_code,
                                        'room_id': room_id,
                                        'room_number': room_row['room_number'],
                                        'block': room_row.get('block', ''),
                                        'description': room_row.get('description', ''),
                                        'course_id': course_info['course_id'],
                                        'course_code': course_info['course_code'],
                                        'course_name': course_info['course_name'],
                                        'course_instance_id': instance_id,
                                        'batch': None  # Theory classes don't have batches
                                    })
        
        # Now process lab assignments, trying to assign batches intelligently
        for teacher in self.teachers:
            for d in range(self.num_days):
                for s in range(self.num_lab_slots):
                    for _, room_row in self.labs.iterrows():
                        room_id = room_row['id']
                        if solver.Value(teacher_lab_assignments[teacher][d][s][room_id]) == 1:
                            # Find which course instance to assign this slot to
                            if teacher in self.teacher_course_assignments:
                                # Find instances with lab hours that need more lab slots
                                available_instances = []
                                
                                # First, prioritize instances that already have theory slots on this day
                                for course_info in self.teacher_course_assignments[teacher]:
                                    instance_id = course_info['id']
                                    tracking = instance_tracking[teacher][instance_id]
                                    
                                    if course_info['practical_hours'] <= 0:
                                        continue  # Skip courses without labs
                                    
                                    # Check if this instance needs more lab slots
                                    total_required_lab_slots = 0
                                    
                                    # For large classes (>35 students), check batch requirements
                                    if course_info['student_count'] > 35:
                                        # Add up required slots for all batches
                                        for batch_num, batch_info in tracking['batch_tracking'].items():
                                            if batch_info['slots_allocated'] < batch_info['required_slots']:
                                                total_required_lab_slots += batch_info['required_slots'] - batch_info['slots_allocated']
                                    else:
                                        # Single batch course
                                        required_lab_slots = (course_info['practical_hours'] + 1) // 2
                                        total_required_lab_slots = required_lab_slots - tracking['lab_allocated']
                                    
                                    if total_required_lab_slots > 0:
                                        # Calculate priority - give higher priority to instances with theory on same day
                                        priority = 10 if d in tracking['days_used'] else 0
                                        
                                        available_instances.append({
                                            'instance_id': instance_id,
                                            'remaining': total_required_lab_slots,
                                            'course_info': course_info,
                                            'priority': priority
                                        })
                                
                                if available_instances:
                                    # Sort by priority first, then by remaining slots
                                    available_instances.sort(key=lambda x: (x['priority'], x['remaining']), reverse=True)
                                    selected = available_instances[0]
                                    instance_id = selected['instance_id']
                                    course_info = selected['course_info']
                                    tracking = instance_tracking[teacher][instance_id]
                                    
                                    # Determine which batch to assign this slot to
                                    batch_num = None
                                    
                                    if course_info['student_count'] > 35:
                                        # For multi-batch courses, find the batch with the most remaining required slots
                                        available_batches = []
                                        for b_num, b_info in tracking['batch_tracking'].items():
                                            if b_info['slots_allocated'] < b_info['required_slots']:
                                                available_batches.append({
                                                    'batch_num': b_num,
                                                    'remaining': b_info['required_slots'] - b_info['slots_allocated']
                                                })
                                        
                                        if available_batches:
                                            available_batches.sort(key=lambda x: x['remaining'], reverse=True)
                                            batch_num = available_batches[0]['batch_num']
                                            # Update batch allocation
                                            tracking['batch_tracking'][batch_num]['slots_allocated'] += 1
                                    else:
                                        # Single batch course
                                        batch_num = 1  # Only one batch for small classes
                                    
                                    # Update overall tracking
                                    tracking['lab_allocated'] += 1
                                    
                                    # Find teacher information from the original data
                                    teacher_rows = self.courses_df[self.courses_df['teacher_id'] == teacher]
                                    teacher_first_name = ""
                                    teacher_last_name = ""
                                    staff_code = ""
                                    if not teacher_rows.empty:
                                        first_row = teacher_rows.iloc[0]
                                        if 'first_name' in first_row:
                                            teacher_first_name = first_row['first_name']
                                        if 'last_name' in first_row:
                                            teacher_last_name = first_row['last_name']
                                        if 'staff_code' in first_row:
                                            staff_code = first_row['staff_code']
                                    
                                    # Calculate student count for this batch
                                    students_in_batch = min(35, course_info['student_count'])
                                    if batch_num and batch_num > 1:
                                        remaining_students = course_info['student_count'] - ((batch_num - 1) * 35)
                                        students_in_batch = min(35, remaining_students)
                                    
                                    schedule_data.append({
                                        'day': self.days[d],
                                        'slot_type': 'Lab',
                                        'slot_time': self.lab_slots[s],
                                        'teacher_id': teacher,
                                        'first_name': teacher_first_name,
                                        'last_name': teacher_last_name,
                                        'staff_code': staff_code,
                                        'room_id': room_id,
                                        'room_number': room_row['room_number'],
                                        'block': room_row.get('block', ''),
                                        'description': room_row.get('description', ''),
                                        'course_id': course_info['course_id'],
                                        'course_code': course_info['course_code'],
                                        'course_name': course_info['course_name'],
                                        'course_instance_id': instance_id,
                                        'batch': batch_num,
                                        'batch_students': students_in_batch
                                    })
        
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
            
            # Teacher-Course assignments with instance details
            f.write("Teacher-Course Assignments:\n")
            for teacher in self.teachers:
                teacher_data = schedule_df[schedule_df['teacher_id'] == teacher]
                if not teacher_data.empty:
                    # Get teacher name for display
                    teacher_row = teacher_data.iloc[0]
                    teacher_name = f"{teacher_row['first_name']} {teacher_row['last_name']}".strip()
                    if not teacher_name:
                        teacher_name = teacher_row.get('staff_code', f'Teacher {teacher}')
                    
                    f.write(f"Teacher {teacher} ({teacher_name}):\n")
                    
                    # Group by course code and instance ID
                    if 'course_instance_id' in teacher_data.columns:
                        course_instances = teacher_data.groupby(['course_code', 'course_instance_id'])
                        
                        # Track courses to organize output
                        courses = {}
                        for (course_code, instance_id), instance_data in course_instances:
                            if course_code not in courses:
                                courses[course_code] = []
                            
                            # Count theory slots
                            theory_data = instance_data[instance_data['slot_type'] == 'Theory']
                            theory_slots = len(theory_data)
                            
                            # Process lab data - group by batch
                            lab_data = instance_data[instance_data['slot_type'] == 'Lab']
                            
                            # Organize lab slots by batch
                            batches = {}
                            for _, row in lab_data.iterrows():
                                batch_num = row.get('batch', 1)  # Default to batch 1 if not specified
                                if batch_num not in batches:
                                    batches[batch_num] = {
                                        'slots': 0,
                                        'student_count': row.get('batch_students', 0)
                                    }
                                batches[batch_num]['slots'] += 1
                            
                            # Add instance info
                            courses[course_code].append({
                                'instance_id': instance_id,
                                'theory_slots': theory_slots,
                                'batches': batches,
                                'course_name': instance_data.iloc[0]['course_name']
                            })
                        
                        # Output each course with its instances
                        for course_code, instances in courses.items():
                            course_name = instances[0]['course_name']
                            f.write(f"  {course_code} ({course_name}):\n")
                            
                            total_theory = 0
                            total_lab = 0
                            
                            for i, instance in enumerate(instances):
                                f.write(f"    Instance {i+1} (ID: {instance['instance_id']}):\n")
                                
                                # Theory slots summary
                                f.write(f"      Theory: {instance['theory_slots']} slots\n")
                                total_theory += instance['theory_slots']
                                
                                # Lab batches summary
                                if instance['batches']:
                                    f.write(f"      Lab:\n")
                                    instance_lab_slots = 0
                                    for batch_num, batch_info in sorted(instance['batches'].items()):
                                        f.write(f"        Batch {batch_num} ({batch_info['student_count']} students): {batch_info['slots']} slots\n")
                                        instance_lab_slots += batch_info['slots']
                                    
                                    f.write(f"      Total Lab: {instance_lab_slots} slots\n")
                                    total_lab += instance_lab_slots
                                else:
                                    f.write(f"      Lab: 0 slots\n")
                            
                            f.write(f"    Total for {course_code}: {total_theory} theory slots, {total_lab} lab slots\n\n")
                    else:
                        # Fallback to old method if instance IDs are not available
                        course_groups = teacher_data.groupby('course_code')
                        for course_code, course_data in course_groups:
                            course_name = course_data.iloc[0]['course_name']
                            theory_slots = len(course_data[course_data['slot_type'] == 'Theory'])
                            lab_slots = len(course_data[course_data['slot_type'] == 'Lab'])
                            
                            f.write(f"  {course_code} ({course_name}): {theory_slots} theory slots, {lab_slots} lab slots\n")
                    
                    f.write("\n")
            
            f.write("\nSchedule generated on: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        
        self.logger.info(f"Summary saved to {summary_path}") 