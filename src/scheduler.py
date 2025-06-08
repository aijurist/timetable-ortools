import os
import pandas as pd
import numpy as np
import logging
import json
from datetime import datetime
from ortools.sat.python import cp_model
from src.constraints import TimetableConstraints
from src.utils.room_verifier import RoomVerifier
from src.utils.room_visualizer import RoomVisualizer

class NumpyEncoder(json.JSONEncoder):
    """Custom JSON encoder to handle numpy types."""
    def default(self, obj):
        if isinstance(obj, (np.integer, np.int64)):
            return int(obj)
        elif isinstance(obj, (np.floating, np.float64)):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, (pd.Timestamp, pd.Timedelta)):
            return str(obj)
        return super(NumpyEncoder, self).default(obj)

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
        
        # Pre-compute room IDs for efficiency (moved here for availability in all methods)
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
        
        # Initialize instance usage tracking for fair distribution
        self.teacher_instance_usage = {}
        # ENHANCED: Track lecture vs tutorial assignment counts per instance
        self.instance_assignment_tracking = {}
        
        for teacher, assignments in self.teacher_course_assignments.items():
            self.teacher_instance_usage[teacher] = {
                'theory_instances': [inst for inst in assignments if inst['lecture_hours'] > 0 or inst['tutorial_hours'] > 0],
                'lab_instances': [inst for inst in assignments if inst['practical_hours'] > 0],
                'theory_index': 0,
                'lab_index': 0
            }
            
            # Track assignment counts for each instance
            for instance in assignments:
                instance_id = instance['id']
                self.instance_assignment_tracking[instance_id] = {
                    'lecture_required': instance['lecture_hours'],
                    'tutorial_required': instance['tutorial_hours'],
                    'lecture_assigned': 0,
                    'tutorial_assigned': 0
                }
        
        # Create output directory
        self.output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
                                      'output', 
                                      f'schedule_{datetime.now().strftime("%Y%m%d_%H%M%S")}')
        os.makedirs(self.output_dir, exist_ok=True)
    
    def process_teacher_courses(self):
        """Process the teacher-course assignments from the CSV data."""
        import random
        
        # Assign random IDs to Unknown teachers
        unknown_teacher_counter = 9000  # Start from 9000 to avoid conflicts
        teacher_id_mapping = {}
        
        # First pass: create mapping for Unknown teachers
        for idx, row in self.courses_df.iterrows():
            if row['teacher_id'] == 'Unknown':
                # Create a unique key based on row characteristics
                unknown_key = f"Unknown_{row.get('course_code', '')}_{row.get('semester', '')}_{idx}"
                if unknown_key not in teacher_id_mapping:
                    teacher_id_mapping[unknown_key] = str(unknown_teacher_counter)
                    unknown_teacher_counter += 1
                    self.logger.info(f"Assigned Teacher ID {teacher_id_mapping[unknown_key]} to Unknown teacher for {row.get('course_code', 'Unknown Course')}")
                
                # Update the dataframe
                self.courses_df.at[idx, 'teacher_id'] = teacher_id_mapping[unknown_key]
                self.courses_df.at[idx, 'first_name'] = f"Unknown"
                self.courses_df.at[idx, 'last_name'] = f"Teacher_{teacher_id_mapping[unknown_key]}"
                self.courses_df.at[idx, 'staff_code'] = f"UNK{teacher_id_mapping[unknown_key]}"
        
        # Now all teachers have valid IDs - process normally
        valid_courses_df = self.courses_df  # No need to filter anymore
        self.logger.info(f"Processing all {len(valid_courses_df)} course assignments (including formerly Unknown teachers)")
        
        if valid_courses_df.empty:
            self.logger.error("No course assignments found")
            raise ValueError("No course assignments available")
        
        # Extract unique teachers (now all have valid IDs)
        self.teachers = valid_courses_df['teacher_id'].unique()
        self.num_teachers = len(self.teachers)
        self.logger.info(f"Processing {self.num_teachers} teachers (including {len(teacher_id_mapping)} formerly Unknown)")
        
        # Extract unique courses
        self.courses = valid_courses_df[['course_id', 'course_code', 'course_name']].drop_duplicates()
        self.num_courses = len(self.courses)
        self.logger.info(f"Processing {self.num_courses} unique courses")
        
        # Analyze departments and create building block assignments
        self.department_analysis = self._analyze_departments(valid_courses_df)
        self._create_building_block_arrays()
        
        # Create a mapping of teachers to their courses with required hours
        self.teacher_course_assignments = {}
        for _, row in valid_courses_df.iterrows():
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
                'academic_year': row.get('academic_year', 3),
                'semester': row.get('semester', 5),
                'course_dept': row.get('course_dept', 'Computer Science & Engineering')
            })
        
        # Log teacher workload summary
        for teacher_id, assignments in self.teacher_course_assignments.items():
            total_theory_hours = sum(a['lecture_hours'] + a['tutorial_hours'] for a in assignments)
            total_practical_hours = sum(a['practical_hours'] for a in assignments)
            dept = assignments[0].get('course_dept', 'Unknown') if assignments else 'Unknown'
            teacher_type = "Unknown Teacher" if int(teacher_id) >= 9000 else "Known Teacher"
            self.logger.info(f"Teacher {teacher_id} ({teacher_type}, {dept}): {total_theory_hours} theory hours, {total_practical_hours} practical hours")
    
    def _analyze_departments(self, courses_df):
        """Analyze departments and their requirements for building block allocation."""
        department_analysis = {}
        
        # Group by department
        for dept in courses_df['course_dept'].unique():
            dept_courses = courses_df[courses_df['course_dept'] == dept]
            
            analysis = {
                'name': dept,
                'total_teachers': len(dept_courses['teacher_id'].unique()),
                'total_courses': len(dept_courses['course_id'].unique()),
                'total_theory_hours': dept_courses['lecture_hours'].sum() + dept_courses['tutorial_hours'].sum(),
                'total_practical_hours': dept_courses['practical_hours'].sum(),
                'avg_student_count': dept_courses['student_count'].mean(),
                'max_student_count': dept_courses['student_count'].max(),
                'total_students': dept_courses['student_count'].sum()
            }
            
            department_analysis[dept] = analysis
            
            self.logger.info(f"Department: {dept}")
            self.logger.info(f"  - Teachers: {analysis['total_teachers']}")
            self.logger.info(f"  - Courses: {analysis['total_courses']}")
            self.logger.info(f"  - Theory Hours: {analysis['total_theory_hours']}")
            self.logger.info(f"  - Practical Hours: {analysis['total_practical_hours']}")
            self.logger.info(f"  - Max Students per Class: {analysis['max_student_count']}")
        
        return department_analysis
    
    def _create_building_block_arrays(self):
        """Create arrays of classrooms organized by building blocks for department allocation."""
        # Initialize building block arrays
        self.building_blocks = {
            'A_Block': [],
            'B_Block': [],
            'Techlounge': [],
            'J_Block': [],
            'K_Block': [],
            'D_Block': [],
            'Unknown_Block': []
        }
        
        # Populate building block arrays with classroom information
        for _, room in self.classrooms.iterrows():
            block = str(room.get('block', 'Unknown Block')).strip()
            room_info = {
                'id': room['id'],
                'room_number': room['room_number'],
                'capacity': room['room_max_cap'],
                'block': block,
                'has_projector': room.get('has_projector', 0),
                'has_ac': room.get('has_ac', 0)
            }
            
            # Map to building block arrays
            if block == 'A Block':
                self.building_blocks['A_Block'].append(room_info)
            elif block == 'B Block':
                self.building_blocks['B_Block'].append(room_info)
            elif block == 'Techlounge':
                self.building_blocks['Techlounge'].append(room_info)
            elif block == 'J Block':
                self.building_blocks['J_Block'].append(room_info)
            elif block == 'K Block':
                self.building_blocks['K_Block'].append(room_info)
            elif block == 'D Block':
                self.building_blocks['D_Block'].append(room_info)
            else:
                self.building_blocks['Unknown_Block'].append(room_info)
        
        # Sort blocks by capacity for better allocation
        for block_name, rooms in self.building_blocks.items():
            rooms.sort(key=lambda x: x['capacity'], reverse=True)
        
        # Log building block distribution
        self.logger.info("Building Block Distribution:")
        total_classrooms = 0
        for block_name, rooms in self.building_blocks.items():
            if rooms:
                min_cap = min(room['capacity'] for room in rooms)
                max_cap = max(room['capacity'] for room in rooms)
                avg_cap = sum(room['capacity'] for room in rooms) / len(rooms)
                total_classrooms += len(rooms)
                
                self.logger.info(f"  {block_name.replace('_', ' ')}: {len(rooms)} classrooms")
                self.logger.info(f"    - Capacity range: {min_cap}-{max_cap} (avg: {avg_cap:.0f})")
                self.logger.info(f"    - Room numbers: {', '.join([r['room_number'] for r in rooms[:5]])}" + 
                               (f" (+{len(rooms)-5} more)" if len(rooms) > 5 else ""))
        
        self.logger.info(f"Total Classrooms Available: {total_classrooms}")
        
        # Create department-to-block allocation strategy
        self._create_department_block_allocation()
    
    def _create_department_block_allocation(self):
        """Create department-specific building block allocation strategy."""
        self.department_block_allocation = {}
        
        for dept, analysis in self.department_analysis.items():
            # Default allocation strategy based on department characteristics
            if 'Computer Science' in dept or 'Information Technology' in dept:
                # CS/IT departments get priority access to A Block and B Block
                allocated_blocks = ['A_Block', 'B_Block']
                primary_block = 'A_Block'  # A Block is primary for CS
            elif 'Electronics' in dept or 'Communication' in dept:
                # ECE gets B Block
                allocated_blocks = ['B_Block']
                primary_block = 'B_Block'
            elif 'Mechanical' in dept or 'Civil' in dept:
                # Mechanical/Civil get B Block
                allocated_blocks = ['B_Block']
                primary_block = 'B_Block'
            else:
                # Default allocation for other departments
                allocated_blocks = ['A_Block', 'B_Block']
                primary_block = 'A_Block'
            
            self.department_block_allocation[dept] = {
                'allocated_blocks': allocated_blocks,
                'primary_block': primary_block,
                'total_classrooms': sum(len(self.building_blocks[block]) for block in allocated_blocks),
                'priority_level': 1 if 'Computer Science' in dept else 2
            }
            
            # Calculate room requirements
            theory_sessions_needed = analysis['total_theory_hours']
            available_rooms = sum(len(self.building_blocks[block]) for block in allocated_blocks)
            
            self.logger.info(f"Department Block Allocation - {dept}:")
            self.logger.info(f"  - Allocated Blocks: {[block.replace('_', ' ') for block in allocated_blocks]}")
            self.logger.info(f"  - Primary Block: {primary_block.replace('_', ' ')}")
            self.logger.info(f"  - Available Classrooms: {available_rooms}")
            self.logger.info(f"  - Theory Sessions Needed: {theory_sessions_needed}")
            self.logger.info(f"  - Room Utilization Estimate: {(theory_sessions_needed / (available_rooms * 55)) * 100:.1f}%" if available_rooms > 0 else "  - Room Utilization: Cannot calculate")
        
        return self.department_block_allocation
    
    def generate_timetable(self):
        """Generate the timetable using OR-Tools CP-SAT solver with group-based scheduling."""
        self.logger.info("Starting timetable generation with GROUP-BASED SCHEDULING...")
        
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
        
        # TEMPORARILY DISABLED: Lab assignments
        # teacher_lab_assignments[t][d][session][r] = 1 if teacher t is assigned to lab r in session on day d
        teacher_lab_assignments = None
        self.logger.info("Lab assignments temporarily disabled as requested")
        
        # Initialize constraints handler
        constraints = TimetableConstraints(
            model, 
            self.teachers, 
            self.teacher_course_assignments,
            self.classrooms, 
            self.labs
        )
        
        # Store reference to constraints for later use in extraction
        self.constraints = constraints
        
        # Apply all constraints (lab_assignments = None will skip lab constraints)
        constraints.apply_all_constraints(teacher_theory_assignments, teacher_lab_assignments)
        
        # Create the solver and solve the model
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 1200  # Increase to 20 minutes time limit
        solver.parameters.max_memory_in_mb = 30000  # 30GB memory limit
        solver.parameters.log_search_progress = True
        solver.parameters.num_search_workers = 12  # 12 threads for parallel search
        
        # Allow partial solutions
        solver.parameters.enumerate_all_solutions = False
        solver.parameters.search_branching = cp_model.PORTFOLIO_SEARCH
        solver.parameters.cp_model_presolve = True
        solver.parameters.cp_model_probing_level = 2
        
        self.logger.info("Solving the scheduling model with GROUP-BASED SCHEDULING...")
        status = solver.Solve(model)
        
        if status == cp_model.OPTIMAL:
            self.logger.info("Optimal solution found!")
            
            # Extract group timeslots from the solution
            course_group_constraint = self.constraints.course_group_constraint
            group_timeslots = course_group_constraint.extract_group_timeslots(solver)
            
            # Run post-processing to distribute course instances across group timeslots
            theory_assignments = self.post_process_group_scheduling(solver, teacher_theory_assignments, group_timeslots)
            lab_assignments = []  # Empty list since lab assignments are disabled
            
            # Create detailed schedule
            schedule_result = self.create_detailed_schedule(theory_assignments, lab_assignments)
            
            # Save schedule results
            self.save_schedule_results(schedule_result)
            
            # Generate visualizations
            self.generate_visualizations(schedule_result)
            
            # Verify room distribution and check for overlaps
            room_verifier = RoomVerifier(self.logger)
            verification_result = room_verifier.verify_room_distribution_and_overlaps(schedule_result)
            
            # Generate room-specific visualizations
            room_visualizer = RoomVisualizer(schedule_result['schedule_data'], self.output_dir, self.logger)
            room_visualizer.generate_all_room_visualizations()
            
            # Generate detailed room verification report
            verification_report_path = os.path.join(self.output_dir, 'room_verification_report.txt')
            room_verifier.generate_room_verification_report(schedule_result, verification_report_path)
            
            return True
        elif status == cp_model.FEASIBLE:
            self.logger.info("Feasible solution found!")
            
            # Extract group timeslots from the solution
            course_group_constraint = self.constraints.course_group_constraint
            group_timeslots = course_group_constraint.extract_group_timeslots(solver)
            
            # Run post-processing to distribute course instances across group timeslots
            theory_assignments = self.post_process_group_scheduling(solver, teacher_theory_assignments, group_timeslots)
            lab_assignments = []  # Empty list since lab assignments are disabled
            
            # Create detailed schedule
            schedule_result = self.create_detailed_schedule(theory_assignments, lab_assignments)
            
            # Save schedule results
            self.save_schedule_results(schedule_result)
            
            # Generate visualizations
            self.generate_visualizations(schedule_result)
            
            # Verify room distribution and check for overlaps
            room_verifier = RoomVerifier(self.logger)
            verification_result = room_verifier.verify_room_distribution_and_overlaps(schedule_result)
            
            # Generate room-specific visualizations
            room_visualizer = RoomVisualizer(schedule_result['schedule_data'], self.output_dir, self.logger)
            room_visualizer.generate_all_room_visualizations()
            
            # Generate detailed room verification report
            verification_report_path = os.path.join(self.output_dir, 'room_verification_report.txt')
            room_verifier.generate_room_verification_report(schedule_result, verification_report_path)
            
            return True
        elif status == cp_model.INFEASIBLE:
            self.logger.error("Problem is infeasible - no solution possible with current constraints")
            return False
        else:
            self.logger.warning(f"No solution found. Status: {status}")
            return False
    
    def extract_theory_assignments(self, solver, teacher_theory_assignments):
        """Extract theory assignments from CP-SAT solution."""
        theory_assignments = []
        
        # Get the course group constraint instance for group information
        course_group_constraint = self.constraints.course_group_constraint
        
        for teacher in self.teachers:
            if teacher in teacher_theory_assignments:
                for day_idx, day in enumerate(self.days):
                    for slot_idx in range(self.num_slots):
                        for room_id in self.classrooms['id'].tolist():
                            if solver.Value(teacher_theory_assignments[teacher][day_idx][slot_idx][room_id]) == 1:
                                # Find the specific course instance by its ID
                                course_info = self._get_course_instance_info(teacher, 'theory')
                                
                                if course_info:
                                    # Get group information if available
                                    group_info = {'group_name': 'Unassigned', 'group_index': 0}
                                    if course_group_constraint and hasattr(course_group_constraint, 'get_group_info_for_course_instance'):
                                        group_info = course_group_constraint.get_group_info_for_course_instance(
                                            teacher, course_info['instance_id']
                                        )
                                    
                                    theory_assignments.append({
                                        'day': day,
                                        'slot_index': slot_idx,
                                        'time_interval': self.time_slots[slot_idx],
                                        'slot_type': course_info['slot_type'],
                                        'teacher_id': teacher,
                                        'first_name': course_info['first_name'],
                                        'last_name': course_info['last_name'],
                                        'staff_code': course_info['staff_code'],
                                        'room_id': room_id,
                                        'room_number': self.classrooms[self.classrooms['id'] == room_id]['room_number'].values[0],
                                        'block': self.classrooms[self.classrooms['id'] == room_id]['block'].values[0],
                                        'room_type': 'Classroom',
                                        'capacity': self.classrooms[self.classrooms['id'] == room_id]['room_max_cap'].values[0],
                                        'course_id': course_info['course_id'],
                                        'course_code': course_info['course_code'],
                                        'course_name': course_info['course_name'],
                                        'course_instance_id': course_info['instance_id'],
                                        'student_count': course_info['student_count'],
                                        'academic_year': course_info.get('academic_year', ''),
                                        'semester': course_info.get('semester', ''),
                                        'course_dept': course_info.get('course_dept', ''),
                                        'group_name': group_info.get('group_name', 'Unassigned'),
                                        'group_index': group_info.get('group_index', 0),
                                        'department_group': group_info.get('department', 'Unknown'),
                                        'semester_group': group_info.get('semester', 0),
                                    })
        
        self.logger.info(f"Extracted {len(theory_assignments)} theory assignments")
        return theory_assignments
    
    def extract_lab_assignments(self, solver, teacher_lab_assignments):
        """Extract lab assignments from CP-SAT solution."""
        lab_assignments = []
        
        # Get the course group constraint instance for group information
        course_group_constraint = self.constraints.course_group_constraint
        
        for teacher in self.teachers:
            if teacher in teacher_lab_assignments:
                for day_idx, day in enumerate(self.days):
                    for session_name, session_info in self.lab_sessions.items():
                        for room_id in self.labs['id'].tolist():
                            if solver.Value(teacher_lab_assignments[teacher][day_idx][session_name][room_id]) == 1:
                                # Find the specific course instance by its ID
                                course_info = self._get_course_instance_info(teacher, 'lab')
                                
                                if course_info:
                                    # Get group information if available
                                    group_info = {'group_name': 'Unassigned', 'group_index': 0}
                                    if course_group_constraint and hasattr(course_group_constraint, 'get_group_info_for_course_instance'):
                                        group_info = course_group_constraint.get_group_info_for_course_instance(
                                            teacher, course_info['instance_id']
                                        )
                                    
                                    lab_assignments.append({
                                        'day': day,
                                        'slot_index': f"Lab_{session_name}",
                                        'time_interval': session_info['time_range'],
                                        'slot_type': course_info['slot_type'],
                                        'teacher_id': teacher,
                                        'first_name': course_info['first_name'],
                                        'last_name': course_info['last_name'],
                                        'staff_code': course_info['staff_code'],
                                        'room_id': room_id,
                                        'room_number': self.labs[self.labs['id'] == room_id]['room_number'].values[0],
                                        'block': self.labs[self.labs['id'] == room_id]['block'].values[0],
                                        'room_type': 'Lab',
                                        'capacity': self.labs[self.labs['id'] == room_id]['room_max_cap'].values[0],
                                        'course_id': course_info['course_id'],
                                        'course_code': course_info['course_code'],
                                        'course_name': course_info['course_name'],
                                        'course_instance_id': course_info['instance_id'],
                                        'student_count': course_info['student_count'],
                                        'academic_year': course_info.get('academic_year', ''),
                                        'semester': course_info.get('semester', ''),
                                        'course_dept': course_info.get('course_dept', ''),
                                        'group_name': group_info.get('group_name', 'Unassigned'),
                                        'group_index': group_info.get('group_index', 0),
                                        'department_group': group_info.get('department', 'Unknown'),
                                        'semester_group': group_info.get('semester', 0),
                                    })
        
        return lab_assignments
    
    def _get_course_instance_info(self, teacher, assignment_type):
        """Get next course instance information by teacher, ensuring each instance gets its required hours."""
        if teacher not in self.teacher_course_assignments:
            return None
        
        teacher_info = self._get_teacher_info(teacher)
        
        # Get the usage tracking for this teacher
        if teacher not in self.teacher_instance_usage:
            return None
        
        usage_info = self.teacher_instance_usage[teacher]
        
        if assignment_type == 'theory':
            theory_instances = usage_info['theory_instances']
            if not theory_instances:
                return None
            
            # ENHANCED: Priority-based assignment to ensure each instance gets required hours
            # Find the instance that needs the most assignments relative to its requirements
            best_instance = None
            best_priority = -1
            
            for instance in theory_instances:
                instance_id = instance['id']
                tracking = self.instance_assignment_tracking[instance_id]
                
                # Calculate remaining requirements
                lecture_remaining = tracking['lecture_required'] - tracking['lecture_assigned']
                tutorial_remaining = tracking['tutorial_required'] - tracking['tutorial_assigned']
                total_remaining = lecture_remaining + tutorial_remaining
                
                # Skip instances that are already satisfied
                if total_remaining <= 0:
                    continue
                
                # Priority = remaining requirements (higher is better)
                # This ensures instances with more remaining requirements get prioritized
                priority = total_remaining
                
                if priority > best_priority:
                    best_priority = priority
                    best_instance = instance
            
            # If no instance needs assignments, return None
            if best_instance is None:
                return None
            
            instance_id = best_instance['id']
            tracking = self.instance_assignment_tracking[instance_id]
            
            # Determine slot type based on what's still needed for this specific instance
            if tracking['lecture_assigned'] < tracking['lecture_required']:
                slot_type = 'Lecture'
                tracking['lecture_assigned'] += 1
            elif tracking['tutorial_assigned'] < tracking['tutorial_required']:
                slot_type = 'Tutorial'
                tracking['tutorial_assigned'] += 1
            else:
                # This shouldn't happen with the priority logic, but fallback
                slot_type = 'Lecture'
            
            self.logger.info(f"Assigning {slot_type} slot to Instance {instance_id} ({best_instance['course_code']}) for Teacher {teacher}")
            self.logger.info(f"  Progress: L:{tracking['lecture_assigned']}/{tracking['lecture_required']} T:{tracking['tutorial_assigned']}/{tracking['tutorial_required']}")
            
            return {
                'instance_id': best_instance['id'],
                'course_id': best_instance['course_id'],
                'course_code': best_instance['course_code'],
                'course_name': best_instance['course_name'],
                'student_count': best_instance['student_count'],
                'academic_year': best_instance.get('academic_year', ''),
                'semester': best_instance.get('semester', ''),
                'course_dept': best_instance.get('course_dept', ''),
                'slot_type': slot_type,
                'first_name': teacher_info['first_name'],
                'last_name': teacher_info['last_name'],
                'staff_code': teacher_info['staff_code']
            }
        
        elif assignment_type == 'lab':
            lab_instances = usage_info['lab_instances']
            if not lab_instances:
                return None
            
            # Get the next instance in round-robin fashion
            current_index = usage_info['lab_index']
            instance = lab_instances[current_index]
            
            # Move to next instance for next call
            usage_info['lab_index'] = (current_index + 1) % len(lab_instances)
            
            return {
                'instance_id': instance['id'],
                'course_id': instance['course_id'],
                'course_code': instance['course_code'],
                'course_name': instance['course_name'],
                'student_count': instance['student_count'],
                'academic_year': instance.get('academic_year', ''),
                'semester': instance.get('semester', ''),
                'course_dept': instance.get('course_dept', ''),
                'slot_type': 'Practical',
                'first_name': teacher_info['first_name'],
                'last_name': teacher_info['last_name'],
                'staff_code': teacher_info['staff_code']
            }
        
        return None
    
    def _get_teacher_info(self, teacher):
        """Get teacher information from the courses dataframe."""
        # Use valid courses only (excluding Unknown teachers)
        valid_courses_df = self.courses_df[self.courses_df['teacher_id'] != 'Unknown']
        teacher_rows = valid_courses_df[valid_courses_df['teacher_id'] == teacher]
        if not teacher_rows.empty:
            first_row = teacher_rows.iloc[0]
            return {
                'first_name': first_row.get('first_name', ''),
                'last_name': first_row.get('last_name', ''),
                'staff_code': first_row.get('staff_code', '')
            }
        else:
            return {
                'first_name': '',
                'last_name': '',
                'staff_code': ''
            }
    
    def create_detailed_schedule(self, theory_assignments, lab_assignments):
        """Create detailed schedule from extracted assignments."""
        schedule_data = theory_assignments + lab_assignments
        
        # Sort schedule by day and slot index with proper handling of mixed types
        def sort_key(x):
            day = x['day']
            slot_index = x['slot_index']
            
            # Convert day to numeric for sorting
            day_order = {"tuesday": 0, "wed": 1, "thur": 2, "fri": 3, "sat": 4}
            day_num = day_order.get(day, 5)
            
            # Handle slot_index - convert strings to high numbers for lab sessions
            if isinstance(slot_index, str):
                # Lab sessions like "Lab_L1" -> sort after all theory slots
                if slot_index.startswith('Lab_'):
                    lab_session = slot_index.replace('Lab_', '')
                    lab_order = {'L1': 100, 'L2': 101, 'L3': 102, 'L4': 103, 'L5': 104, 'L6': 105}
                    slot_num = lab_order.get(lab_session, 110)
                else:
                    slot_num = 110  # Fallback for unknown string slots
            else:
                slot_num = slot_index  # Theory slots are already integers
            
            return (day_num, slot_num)
        
        schedule_data.sort(key=sort_key)
        
        return {
            'schedule_data': schedule_data,
            'daily_schedules': self._create_daily_schedule_structure(schedule_data),
            'time_slot_definitions': {
                'T': self.time_slots,  # Theory time slots
                'L': self.lab_time_slots,  # Lab time slots
                'Lab_Sessions': self.lab_sessions  # Lab session definitions
            },
        }
    
    def _create_daily_schedule_structure(self, schedule_data):
        """Create the daily schedule structure matching the required format."""
        daily_schedules = {}
        
        for day in self.days:
            daily_schedules[day] = {
                'theory_slots': [],
                'lab_sessions': []
            }
            day_data = [item for item in schedule_data if item['day'] == day]
            
            # Process theory slots
            for slot_idx in range(self.num_slots):
                # Get assignments for this theory slot
                slot_assignments = [item for item in day_data 
                                  if (isinstance(item['slot_index'], int) and 
                                      item['slot_index'] == slot_idx)]
                
                # Create content string for theory
                content_parts = []
                
                # Add slot assignments
                for assignment in slot_assignments:
                    if assignment['slot_type'] in ['Lecture', 'Tutorial']:
                        course_code = assignment['course_code']
                        teacher_id = assignment['teacher_id']
                        room_number = assignment['room_number']
                        content_parts.append(f"{course_code} ({teacher_id}) in {room_number}")
                
                if not content_parts:
                    content = "Free"
                else:
                    content = ' | '.join(content_parts)
                
                daily_schedules[day]['theory_slots'].append({
                    'content': content,
                    'slot_index': slot_idx,
                    'time_interval': self.time_slots[slot_idx],
                    'assignments': slot_assignments
                })
            
            # Process lab sessions
            for session_name, session_info in self.lab_sessions.items():
                # Get assignments for this lab session
                lab_assignments = [item for item in day_data 
                                 if (isinstance(item['slot_index'], str) and 
                                     item['slot_index'] == f"Lab_{session_name}")]
                
                daily_schedules[day]['lab_sessions'].append({
                    'session': session_name,
                    'time_range': session_info['time_range'],
                    'assignments': lab_assignments,
                    'assignment_count': len(lab_assignments)
                })
        
        return daily_schedules
    
    def save_schedule_results(self, schedule_result):
        """Save the schedule results to files."""
        # Save as CSV
        if schedule_result['schedule_data']:
            schedule_df = pd.DataFrame(schedule_result['schedule_data'])
            
            # Save main schedule
            schedule_csv_path = os.path.join(self.output_dir, 'schedule.csv')
            schedule_df.to_csv(schedule_csv_path, index=False, encoding='utf-8')
            self.logger.info(f"Schedule saved to {schedule_csv_path}")
            
            # Save individual teacher schedules
            for teacher in self.teachers:
                teacher_schedule = schedule_df[schedule_df['teacher_id'] == teacher]
                if not teacher_schedule.empty:
                    teacher_schedule_path = os.path.join(self.output_dir, f'teacher_{teacher}_schedule.csv')
                    teacher_schedule.to_csv(teacher_schedule_path, index=False, encoding='utf-8')
            
            # Save individual room schedules
            all_rooms = pd.concat([self.classrooms, self.labs])
            for _, room_row in all_rooms.iterrows():
                room_id = room_row['id']
                room_schedule = schedule_df[schedule_df['room_id'] == room_id]
                if not room_schedule.empty:
                    room_schedule_path = os.path.join(self.output_dir, f'room_{room_id}_schedule.csv')
                    room_schedule.to_csv(room_schedule_path, index=False, encoding='utf-8')
            
        # Save as JSON (structured format)
        json_result = {
            'daily_schedules': schedule_result['daily_schedules'],
            'time_slot_definitions': schedule_result['time_slot_definitions']
        }
        
        json_path = os.path.join(self.output_dir, 'schedule.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(json_result, f, indent=2, ensure_ascii=False, cls=NumpyEncoder)
        
        self.logger.info(f"JSON schedule saved to {json_path}")
        
        # Generate summary
        self.generate_summary(schedule_result)
    
    def generate_summary(self, schedule_result):
        """Generate a summary of the schedule."""
        summary_path = os.path.join(self.output_dir, 'schedule_summary.txt')
        
        schedule_data = schedule_result['schedule_data']
        
        with open(summary_path, 'w', encoding='utf-8') as f:
            f.write("Timetable Schedule Summary\n")
            f.write("=========================\n\n")
            
            # Count of scheduled classes by type
            lecture_count = len([item for item in schedule_data if item['slot_type'] == 'Lecture'])
            tutorial_count = len([item for item in schedule_data if item['slot_type'] == 'Tutorial'])
            practical_count = len([item for item in schedule_data if item['slot_type'] == 'Practical'])
            
            f.write(f"Total scheduled lecture classes: {lecture_count}\n")
            f.write(f"Total scheduled tutorial classes: {tutorial_count}\n")
            f.write(f"Total scheduled practical classes: {practical_count}\n\n")
            
            # Teachers with assignments
            teachers_scheduled = len(set(item['teacher_id'] for item in schedule_data))
            f.write(f"Total teachers scheduled: {teachers_scheduled} out of {self.num_teachers}\n\n")
            
            # Rooms utilized
            rooms_scheduled = len(set(item['room_id'] for item in schedule_data))
            total_rooms = len(self.classrooms) + len(self.labs)
            f.write(f"Total rooms utilized: {rooms_scheduled} out of {total_rooms}\n\n")
            
            # Course distribution
            f.write("Course Distribution:\n")
            course_counts = {}
            for item in schedule_data:
                course_code = item['course_code']
                course_counts[course_code] = course_counts.get(course_code, 0) + 1
            
            for course_code, count in sorted(course_counts.items()):
                f.write(f"  {course_code}: {count} assignments\n")
            
            # Weekly working hours analysis
            f.write("\nWeekly Working Hours Analysis:\n")
            teacher_hours = {}
            for item in schedule_data:
                teacher_id = item['teacher_id']
                if teacher_id not in teacher_hours:
                    teacher_hours[teacher_id] = {'theory': 0, 'lab': 0}
                
                if item['slot_type'] in ['Lecture', 'Tutorial']:
                    teacher_hours[teacher_id]['theory'] += 1
                elif item['slot_type'] == 'Practical':
                    teacher_hours[teacher_id]['lab'] += 1
            
            over_limit_teachers = 0
            for teacher_id, hours in teacher_hours.items():
                total_hours = hours['theory'] + (hours['lab'] * 2)  # Lab slots count as 2 hours
                if total_hours > 21:
                    over_limit_teachers += 1
            
            f.write(f"  Teachers within 21-hour limit: {len(teacher_hours) - over_limit_teachers}/{len(teacher_hours)}\n")
            f.write(f"  Teachers exceeding limit: {over_limit_teachers}\n")
            
            f.write(f"\nSchedule generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            f.write(f"\nConstraints applied:")
            f.write(f"\n  - Weekly Working Hour Constraint: 21-hour limit per teacher")
            f.write(f"\n  - No teacher double-booking across slots, rooms, or time conflicts")
            f.write(f"\n  - Room capacity and availability constraints")
            f.write(f"\n  - Schedule structure: Tuesday-Saturday (Monday excluded)")
        
        self.logger.info(f"Summary saved to {summary_path}")

        # Create JSON result for summary file
        json_result = {
            'summary': {
                'lecture_count': lecture_count,
                'tutorial_count': tutorial_count,
                'practical_count': practical_count,
                'teachers_scheduled': teachers_scheduled,
                'total_teachers': self.num_teachers,
                'rooms_utilized': rooms_scheduled,
                'total_rooms': total_rooms,
                'course_distribution': course_counts,
                'teachers_within_limit': len(teacher_hours) - over_limit_teachers,
                'teachers_exceeding_limit': over_limit_teachers
            },
            'schedule_data': schedule_data,
            'timestamp': datetime.now().isoformat()
        }

        # Save JSON result
        json_file = os.path.join(self.output_dir, 'schedule_summary.json')
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(json_result, f, indent=2, ensure_ascii=False, cls=NumpyEncoder)

    def generate_visualizations(self, schedule_result):
        """Generate schedule visualizations."""
        try:
            self.logger.info("Generating schedule visualizations...")
            
            # Create visualizer with schedule data using enhanced TimetableVisualizer
            from src.utils.macroblock_visualizer import TimetableVisualizer
            visualizer = TimetableVisualizer(
                schedule_result['schedule_data'], 
                self.output_dir
            )
            
            # Generate all visualizations
            visualizer.generate_all_visualizations()
            
            self.logger.info("Schedule visualizations generated successfully")
            
        except Exception as e:
            self.logger.error(f"Error generating visualizations: {e}")
            self.logger.exception("Visualization error details")

    def post_process_group_scheduling(self, solver, teacher_theory_assignments, group_timeslots):
        """
        Post-process group-based scheduling by distributing course instances across group timeslots.
        
        Instead of directly scheduling individual course instances in the algorithm, 
        we allocated 4 optimal timeslots to each group. Now we distribute the actual 
        course instances across these timeslots based on their lecture and tutorial hours.
        
        Args:
            solver: The CP-SAT solver with a solution
            teacher_theory_assignments: The theory assignment variables
            group_timeslots: Dictionary mapping group_name to list of (day_idx, slot_idx) tuples
            
        Returns:
            List of theory assignments (same format as extract_theory_assignments)
        """
        self.logger.info("Post-processing group-based scheduling...")
        
        # Get the course group constraint instance for group information
        course_group_constraint = self.constraints.course_group_constraint
        
        # Initialize list for theory assignments
        theory_assignments = []
        
        # Track which course instances have been processed
        processed_instances = set()
        
        # Track usage of group timeslots (to avoid conflicts)
        timeslot_usage = {}  # (day_idx, slot_idx, room_id) -> list of assigned instances
        
        # Process each teacher's course instances
        for teacher in self.teachers:
            if teacher not in self.teacher_course_assignments:
                continue
                
            teacher_info = self._get_teacher_info(teacher)
            teacher_instances = self.teacher_course_assignments[teacher]
            
            # Group instances by group
            instances_by_group = {}
            for instance in teacher_instances:
                instance_id = instance['id']
                
                # Skip if already processed
                if instance_id in processed_instances:
                    continue
                
                # Skip if no theory hours
                if instance['lecture_hours'] == 0 and instance['tutorial_hours'] == 0:
                    continue
                
                # Get group information
                group_info = course_group_constraint.get_group_info_for_course_instance(
                    teacher, instance_id
                )
                group_name = group_info.get('group_name', 'Unassigned')
                
                if group_name not in instances_by_group:
                    instances_by_group[group_name] = []
                
                instances_by_group[group_name].append(instance)
            
            # For each group, distribute instances across the allocated timeslots
            for group_name, instances in instances_by_group.items():
                # Get allocated timeslots for this group
                allocated_timeslots = course_group_constraint.get_group_timeslots(group_name)
                
                if not allocated_timeslots:
                    self.logger.warning(f"No timeslots allocated for group {group_name}, skipping {len(instances)} instances")
                    continue
                
                self.logger.info(f"Distributing {len(instances)} instances for teacher {teacher} in group {group_name}")
                self.logger.info(f"  Group {group_name} has {len(allocated_timeslots)} allocated timeslots")
                
                # Sort instances by total theory hours (descending) for better distribution
                instances.sort(key=lambda x: x['lecture_hours'] + x['tutorial_hours'], reverse=True)
                
                # Distribute instances across timeslots
                for instance in instances:
                    instance_id = instance['id']
                    lecture_hours = instance['lecture_hours']
                    tutorial_hours = instance['tutorial_hours']
                    total_hours = lecture_hours + tutorial_hours
                    
                    # Skip if no theory hours
                    if total_hours == 0:
                        continue
                    
                    # Mark as processed
                    processed_instances.add(instance_id)
                    
                    # Find suitable room based on student count and availability
                    suitable_rooms = [
                        room_id for room_id in self.classroom_ids
                        if self.classrooms[self.classrooms['id'] == room_id]['room_max_cap'].values[0] >= instance['student_count']
                    ]
                    
                    if not suitable_rooms:
                        # If no suitable room, use any room
                        suitable_rooms = self.classroom_ids
                    
                    # Sort rooms by capacity (ascending) to minimize waste
                    suitable_rooms.sort(
                        key=lambda r: self.classrooms[self.classrooms['id'] == r]['room_max_cap'].values[0]
                    )
                    
                    # Try to assign this instance to allocated timeslots
                    hours_assigned = 0
                    lecture_assigned = 0
                    tutorial_assigned = 0
                    
                    self.logger.info(f"  Instance {instance_id} ({instance['course_code']}): {lecture_hours}L + {tutorial_hours}T hours")
                    
                    # Sort allocated timeslots to distribute classes evenly across days
                    # We'll try to use different days to spread out the schedule
                    sorted_timeslots = sorted(allocated_timeslots, key=lambda ts: (ts[0], ts[1]))
                    
                    # Track which timeslots are already used by this teacher
                    teacher_used_timeslots = set()
                    for key, data in timeslot_usage.items():
                        day, slot, _ = key  # Unpack day_idx, slot_idx, room_id
                        if data.get('teacher_id') == teacher:
                            teacher_used_timeslots.add((day, slot))
                    
                    # Try to assign to each allocated timeslot
                    for day_idx, slot_idx in sorted_timeslots:
                        # Skip if we've assigned all hours
                        if hours_assigned >= total_hours:
                            break
                            
                        # Skip if teacher already has an assignment in this timeslot
                        if (day_idx, slot_idx) in teacher_used_timeslots:
                            continue
                        
                        # Find an available room for this timeslot
                        room_assigned = False
                        for room_id in suitable_rooms:
                            timeslot_key = (day_idx, slot_idx, room_id)
                            
                            # Check if this timeslot+room is already used
                            if timeslot_key in timeslot_usage:
                                continue
                            
                            # Determine slot type based on what's still needed
                            if lecture_assigned < lecture_hours:
                                slot_type = 'Lecture'
                                lecture_assigned += 1
                            else:
                                slot_type = 'Tutorial'
                                tutorial_assigned += 1
                                
                            # Add this timeslot to teacher's used timeslots
                            teacher_used_timeslots.add((day_idx, slot_idx))
                            
                            # Create the assignment
                            group_info = course_group_constraint.get_group_info_for_course_instance(
                                teacher, instance_id
                            )
                            
                            theory_assignments.append({
                                'day': self.days[day_idx],
                                'slot_index': slot_idx,
                                'time_interval': self.time_slots[slot_idx],
                                'slot_type': slot_type,
                                'teacher_id': teacher,
                                'first_name': teacher_info['first_name'],
                                'last_name': teacher_info['last_name'],
                                'staff_code': teacher_info['staff_code'],
                                'room_id': room_id,
                                'room_number': self.classrooms[self.classrooms['id'] == room_id]['room_number'].values[0],
                                'block': self.classrooms[self.classrooms['id'] == room_id]['block'].values[0],
                                'room_type': 'Classroom',
                                'capacity': self.classrooms[self.classrooms['id'] == room_id]['room_max_cap'].values[0],
                                'course_id': instance['course_id'],
                                'course_code': instance['course_code'],
                                'course_name': instance['course_name'],
                                'course_instance_id': instance_id,
                                'student_count': instance['student_count'],
                                'academic_year': instance.get('academic_year', ''),
                                'semester': instance.get('semester', ''),
                                'course_dept': instance.get('course_dept', ''),
                                'group_name': group_info.get('group_name', 'Unassigned'),
                                'group_index': group_info.get('group_index', 0),
                                'department_group': group_info.get('department', 'Unknown'),
                                'semester_group': group_info.get('semester', 0),
                            })
                            
                            # Mark this timeslot+room as used
                            timeslot_usage[timeslot_key] = {
                                'instance_id': instance_id,
                                'teacher_id': teacher,
                                'course_code': instance['course_code']
                            }
                            
                            hours_assigned += 1
                            room_assigned = True
                            
                            self.logger.info(f"    Assigned {slot_type} for {instance['course_code']} to {self.days[day_idx]} slot {slot_idx} ({self.time_slots[slot_idx]}) in room {room_id}")
                            break  # Break out of room loop once assigned
                        
                        if not room_assigned:
                            self.logger.warning(f"    Could not find available room for {self.days[day_idx]} slot {slot_idx}")
                    
                    # Log if we couldn't assign all hours
                    if hours_assigned < total_hours:
                        self.logger.warning(f"  Could only assign {hours_assigned}/{total_hours} hours for instance {instance_id}")
        
        self.logger.info(f"Post-processing complete: {len(theory_assignments)} theory assignments created")
        return theory_assignments

# Backward compatibility alias
MacroblockTimetableScheduler = TimetableScheduler 