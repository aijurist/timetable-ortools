import os
import pandas as pd
import numpy as np
import logging
import json
from datetime import datetime
from ortools.sat.python import cp_model
from collections import defaultdict

# Import the lab constraints module
from src.lab_constraints import LabConstraints, validate_lab_constraints, analyze_constraint_conflicts

# Add import for the lab visualizer
try:
    from src.utils.lab_visualizer import LabScheduleVisualizer
    LAB_VISUALIZER_AVAILABLE = True
except ImportError:
    LAB_VISUALIZER_AVAILABLE = False
    print("Lab visualizer not available - visualizations will be skipped")

class LabScheduler:
    def __init__(self, theory_schedule_path, course_file, room_file):
        """Initialize the lab scheduler with existing theory schedule and course data."""
        self.logger = logging.getLogger(__name__)
        
        # Load existing theory schedule
        self.theory_schedule_df = pd.read_csv(theory_schedule_path)
        self.courses_df = pd.read_csv(course_file)
        self.rooms_df = pd.read_csv(room_file)
        
        # Setup time structure
        self.days = ["tuesday", "wed", "thur", "fri", "sat"]
        self.num_days = len(self.days)
        
        # Lab time slots (L slots - 100-minute sessions with 10-minute breaks)
        self.lab_time_slots = [
            "8:00 - 8:50", "8:50 - 9:40", "9:50 - 10:40", "10:40 - 11:30",
            "11:50 - 12:40", "12:40 - 1:30", "1:50 - 2:40", "2:40 - 3:30", 
            "3:50 - 4:40", "4:40 - 5:30", "5:30 - 6:20", "6:20 - 7:10"
        ]
        
        # Group lab slots into 2-hour sessions (L1, L2, L3, etc.)
        # Each lab session = 2 practical hours = 2 consecutive lab time slots
        self.lab_sessions = {
            'L1': ['8:00 - 8:50', '8:50 - 9:40'],      # 8:00 - 9:40
            'L2': ['9:50 - 10:40', '10:40 - 11:30'],   # 9:50 - 11:30  
            'L3': ['11:50 - 12:40', '12:40 - 1:30'],   # 11:50 - 1:30
            'L4': ['1:50 - 2:40', '2:40 - 3:30'],      # 1:50 - 3:30
            'L5': ['3:50 - 4:40', '4:40 - 5:30'],      # 3:50 - 5:30
            'L6': ['5:30 - 6:20', '6:20 - 7:10']       # 5:30 - 7:10
        }
        
        # Process rooms - separate labs from classrooms
        self.labs = self.rooms_df[self.rooms_df['is_lab'] == 1]
        self.classrooms = self.rooms_df[self.rooms_df['is_lab'] == 0]
        
        # Identify courses needing lab allocation
        self.process_lab_requirements()
        
        # Create output directory
        self.output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 
                                      'output', 
                                      f'lab_schedule_{datetime.now().strftime("%Y%m%d_%H%M%S")}')
        os.makedirs(self.output_dir, exist_ok=True)
        
        # Initialize lab constraints
        self.lab_constraints = LabConstraints(self)
        
        self.logger.info(f"Lab scheduler initialized. Output directory: {self.output_dir}")
    
    def process_lab_requirements(self):
        """Identify courses that need lab allocation and their requirements with capacity-based batching."""
        self.lab_requirements = {}
        
        # Get courses with practical hours > 0
        lab_courses = self.courses_df[self.courses_df['practical_hours'] > 0]
        
        # Analyze lab capacities
        self.lab_capacity_analysis = self._analyze_lab_capacities()
        
        # Track course instances per teacher for differentiation (S1, S2, etc.)
        teacher_course_counts = {}
        
        for _, course_row in lab_courses.iterrows():
            teacher_id = course_row['teacher_id']
            course_instance_id = str(course_row['id'])
            practical_hours = int(course_row['practical_hours'])
            course_code = course_row['course_code']
            
            # Calculate required lab sessions (each session = 2 practical hours)
            required_sessions = max(1, (practical_hours + 1) // 2)  # Round up division
            
            # Exact mapping for clarity
            if practical_hours == 1:
                required_sessions = 1
            elif practical_hours == 2:
                required_sessions = 1
            elif practical_hours == 3:
                required_sessions = 2
            elif practical_hours == 4:
                required_sessions = 2
            elif practical_hours == 5:
                required_sessions = 3
            elif practical_hours == 6:
                required_sessions = 3
            else:
                required_sessions = max(1, (practical_hours + 1) // 2)
            
            # Fixed student count per instance
            students_per_instance = 70
            
            # Determine lab capacity requirements and batching
            lab_allocation_strategy = self._determine_lab_allocation_strategy(practical_hours, students_per_instance)
            
            # Track course instances for this teacher - but don't split batched courses into separate instances
            if teacher_id not in teacher_course_counts:
                teacher_course_counts[teacher_id] = {}
            if course_code not in teacher_course_counts[teacher_id]:
                teacher_course_counts[teacher_id][course_code] = 0
            teacher_course_counts[teacher_id][course_code] += 1
            
            # Create course instance suffix for differentiation
            instance_count = teacher_course_counts[teacher_id][course_code]
            if instance_count > 1:
                course_suffix = f"_S{instance_count}"
                display_code = f"{course_code} S{instance_count}"
            else:
                # Check if there are multiple instances of this course for this teacher
                total_instances = lab_courses[(lab_courses['teacher_id'] == teacher_id) & 
                                            (lab_courses['course_code'] == course_code)].shape[0]
                if total_instances > 1:
                    course_suffix = "_S1"
                    display_code = f"{course_code} S1"
                else:
                    course_suffix = ""
                    display_code = course_code
            
            if teacher_id not in self.lab_requirements:
                self.lab_requirements[teacher_id] = []
            
            # Create lab requirement with capacity-based allocation
            # IMPORTANT: Don't multiply instances for batching - handle batching in allocation
            lab_requirement = {
                'course_instance_id': course_instance_id,
                'course_id': course_row['course_id'],
                'course_code': course_code,
                'display_course_code': display_code,  # This will be modified during allocation for batches
                'course_suffix': course_suffix,
                'course_name': course_row['course_name'],
                'practical_hours': practical_hours,
                'students_per_instance': students_per_instance,
                'required_sessions': required_sessions,
                'semester': course_row.get('semester', 5),
                'course_dept': course_row.get('course_dept', 'Computer Science & Engineering'),
                
                # Capacity-based allocation details
                'allocation_strategy': lab_allocation_strategy,
                'total_lab_slots_needed': lab_allocation_strategy['total_lab_slots_needed'],
                'batching_required': lab_allocation_strategy['batching_required'],
                'num_batches': lab_allocation_strategy['num_batches'],
                'students_per_batch': lab_allocation_strategy['students_per_batch'],
                'preferred_lab_capacities': lab_allocation_strategy['preferred_lab_capacities'],
                'lab_slots_per_batch': lab_allocation_strategy['lab_slots_per_batch']
            }
            
            self.lab_requirements[teacher_id].append(lab_requirement)
        
        # Log capacity analysis
        self._log_capacity_analysis()
        
        # Log detailed requirements with capacity information
        total_courses = len([course for courses in self.lab_requirements.values() for course in courses])
        total_lab_slots = sum([sum(course['total_lab_slots_needed'] for course in courses) 
                              for courses in self.lab_requirements.values()])
        
        self.logger.info(f"Found {total_courses} courses requiring lab allocation")
        self.logger.info(f"Total lab slots needed (including batching): {total_lab_slots}")
        self.logger.info(f"Available lab rooms by capacity: {self.lab_capacity_analysis['capacity_counts']}")
        
        # Log detailed requirements for debugging
        for teacher, courses in self.lab_requirements.items():
            for course in courses:
                strategy = course['allocation_strategy']
                batching_info = ""
                if course['batching_required']:
                    batching_info = f" -> BATCHED into {course['num_batches']} batches of {course['students_per_batch']} students each"
                
                self.logger.info(f"Course {course['display_course_code']} (ID: {course['course_instance_id']}, Teacher {teacher}): "
                               f"{course['practical_hours']} practical hours -> {course['required_sessions']} base sessions -> "
                               f"{course['total_lab_slots_needed']} total lab slots{batching_info}")
    
    def _analyze_lab_capacities(self):
        """Analyze available lab capacities and categorize them - FORCE ALL LABS TO 35 CAPACITY FOR TESTING."""
        lab_capacity_analysis = {
            'labs_35': [],
            'labs_70': [],
            'labs_140': [],
            'capacity_counts': {'35': 0, '70': 0, '140': 0, 'other': 0},
            'total_capacity_35': 0,
            'total_capacity_70': 0,
            'total_capacity_140': 0
        }
        
        for _, lab_row in self.labs.iterrows():
            lab_id = lab_row['id']
            original_capacity = lab_row.get('room_max_cap', 0)
            
            # CONSTRAINT CHANGE: Force all labs to 35 capacity for batching testing
            forced_capacity = 35
            
            lab_info = {
                'id': lab_id,
                'room_number': lab_row['room_number'],
                'capacity': forced_capacity,  # Use forced capacity instead of original
                'original_capacity': original_capacity,  # Keep track of original for reference
                'block': lab_row.get('block', ''),
                'description': lab_row.get('description', '')
            }
            
            # All labs are now categorized as 35-capacity
            lab_capacity_analysis['labs_35'].append(lab_info)
            lab_capacity_analysis['capacity_counts']['35'] += 1
            lab_capacity_analysis['total_capacity_35'] += forced_capacity
        
        return lab_capacity_analysis
    
    def _determine_lab_allocation_strategy(self, practical_hours, students_per_instance):
        """Determine the optimal lab allocation strategy - ALL COURSES REQUIRE BATCHING DUE TO 35-CAPACITY CONSTRAINT."""
        base_sessions = max(1, (practical_hours + 1) // 2)  # Base lab sessions needed
        
        strategy = {
            'practical_hours': practical_hours,
            'students_per_instance': students_per_instance,
            'base_sessions': base_sessions,
            'batching_required': False,
            'num_batches': 1,
            'students_per_batch': students_per_instance,
            'lab_slots_per_batch': base_sessions,
            'total_lab_slots_needed': base_sessions,
            'preferred_lab_capacities': []
        }
        
        # CONSTRAINT CHANGE: Since all labs are 35-capacity, all 70-student courses MUST be batched
        if students_per_instance == 70:
            # FORCE batching for all 70-student courses
            strategy['batching_required'] = True
            strategy['potential_batching_needed'] = True
            strategy['num_batches'] = 2  # Always 2 batches for 70 students in 35-capacity labs
            strategy['students_per_batch'] = 35  # Each batch = 35 students
            strategy['max_possible_batches'] = 2
            # Each batch needs the base sessions, so total = base_sessions * 2
            strategy['total_lab_slots_needed'] = base_sessions * 2
            strategy['preferred_lab_capacities'] = [35]  # Only 35-capacity labs available
            
            self.logger.info(f"FORCED BATCHING: 70-student course with {practical_hours} practical hours -> "
                           f"{base_sessions} sessions per batch × 2 batches = {strategy['total_lab_slots_needed']} total lab slots")
        elif students_per_instance > 70:
            # For >70 students, calculate required batches
            strategy['batching_required'] = True
            strategy['num_batches'] = (students_per_instance + 34) // 35  # Round up to fit in 35-capacity labs
            strategy['students_per_batch'] = min(35, students_per_instance // strategy['num_batches'])
            strategy['total_lab_slots_needed'] = base_sessions * strategy['num_batches']
            strategy['preferred_lab_capacities'] = [35]
        else:
            # ≤35 students - no batching needed, can fit in single 35-capacity lab
            strategy['preferred_lab_capacities'] = [35]
        
        return strategy
    
    def _log_capacity_analysis(self):
        """Log detailed capacity analysis for debugging - ALL LABS FORCED TO 35 CAPACITY."""
        analysis = self.lab_capacity_analysis
        
        self.logger.info("=" * 60)
        self.logger.info("LAB CAPACITY ANALYSIS (FORCED 35-CAPACITY FOR BATCHING TEST)")
        self.logger.info("=" * 60)
        
        self.logger.info(f"ALL LABS SET TO 35-CAPACITY: {analysis['capacity_counts']['35']} labs")
        for lab in analysis['labs_35']:
            original_cap = lab.get('original_capacity', 'Unknown')
            self.logger.info(f"  - {lab['room_number']} (ID: {lab['id']}, Forced: 35, Original: {original_cap})")
        
        self.logger.info(f"70-capacity labs: {analysis['capacity_counts']['70']} labs (DISABLED)")
        self.logger.info(f"140-capacity labs: {analysis['capacity_counts']['140']} labs (DISABLED)")
        
        total_lab_capacity = analysis['total_capacity_35']
        
        self.logger.info(f"Total effective lab capacity: {total_lab_capacity} students (35 per lab)")
        self.logger.info(f"BATCHING REQUIREMENT: All 70-student courses MUST be split into 2×35-student batches")
        self.logger.info("=" * 60)
    
    def generate_lab_schedule(self):
        """Generate lab schedule using OR-Tools CP-SAT solver."""
        self.logger.info("Starting lab schedule generation...")
        
        # Create the CP-SAT model
        model = cp_model.CpModel()
        
        # Get lab room IDs
        lab_room_ids = self.labs['id'].tolist()
        if not lab_room_ids:
            self.logger.error("No lab rooms found!")
            return False
        
        # Define assignment variables at COURSE LEVEL instead of teacher level
        # lab_assignments[course_instance_id][day][session][room] = 1 if course assigned to lab room in session on day
        lab_assignments = {}
        lab_sessions = list(self.lab_sessions.keys())  # ['L1', 'L2', 'L3', 'L4', 'L5', 'L6']
        
        # Create variables for each course instance that needs labs
        all_course_instances = []
        course_to_teacher = {}
        
        for teacher, courses in self.lab_requirements.items():
            for course in courses:
                course_instance_id = course['course_instance_id']
                all_course_instances.append(course_instance_id)
                course_to_teacher[course_instance_id] = teacher
                
                lab_assignments[course_instance_id] = {}
                for day_idx in range(self.num_days):
                    lab_assignments[course_instance_id][day_idx] = {}
                    for session_idx, session_name in enumerate(lab_sessions):
                        lab_assignments[course_instance_id][day_idx][session_idx] = {}
                        for room_id in lab_room_ids:
                            lab_assignments[course_instance_id][day_idx][session_idx][room_id] = model.NewBoolVar(
                                f'course_{course_instance_id}_day_{day_idx}_session_{session_name}_lab_{room_id}')
        
        # Apply constraints
        self.lab_constraints.apply_all_constraints(model, lab_assignments, lab_room_ids, lab_sessions, course_to_teacher)
        
        # Add optimization objective - minimize total lab usage (more efficient allocation)
        total_lab_usage = []
        for course_instance_id in all_course_instances:
            for day_idx in range(self.num_days):
                for session_idx in range(len(lab_sessions)):
                    for room_id in lab_room_ids:
                        total_lab_usage.append(lab_assignments[course_instance_id][day_idx][session_idx][room_id])
        
        model.Minimize(sum(total_lab_usage))
        
        # Create solver and solve
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 300  # 5 minutes
        solver.parameters.log_search_progress = True
        
        self.logger.info("Solving lab allocation model...")
        status = solver.Solve(model)
        
        if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
            self.logger.info(f"Lab allocation solution found with status {status}!")
            
            # Process solution and create combined schedule
            lab_schedule_data = self.process_lab_solution(solver, lab_assignments, lab_sessions, course_to_teacher)
            combined_schedule = self.combine_theory_and_lab_schedules(lab_schedule_data)
            
            # Save results and generate visualizations
            output_dir = self.save_lab_schedule_results(combined_schedule)
            self.logger.info("Lab schedule generation completed successfully")
            return output_dir
        else:
            self.logger.error(f"No lab allocation solution found. Status: {status}")
            
            # Try with even more relaxed constraints
            self.logger.info("Attempting with relaxed constraints...")
            return self.generate_lab_schedule_relaxed(lab_assignments, lab_room_ids, lab_sessions, model)
    
    def process_lab_solution(self, solver, lab_assignments, lab_sessions, course_to_teacher):
        """Process the lab allocation solution."""
        self.logger.info("Processing lab allocation solution...")
        
        lab_schedule_data = []
        
        # Pre-compute teacher information
        teacher_info_cache = {}
        for teacher in self.lab_requirements.keys():
            teacher_rows = self.courses_df[self.courses_df['teacher_id'] == teacher]
            if not teacher_rows.empty:
                first_row = teacher_rows.iloc[0]
                teacher_info_cache[teacher] = {
                    'first_name': first_row.get('first_name', ''),
                    'last_name': first_row.get('last_name', ''),
                    'staff_code': first_row.get('staff_code', '')
                }
            else:
                teacher_info_cache[teacher] = {
                    'first_name': '', 'last_name': '', 'staff_code': ''
                }
        
        # Pre-compute lab room information
        lab_info = {}
        for _, room_row in self.labs.iterrows():
            room_id = room_row['id']
            lab_info[room_id] = {
                'room_number': room_row['room_number'],
                'block': room_row.get('block', ''),
                'description': room_row.get('description', ''),
                'capacity': room_row.get('room_max_cap', 0)
            }
        
        # Create course info lookup
        course_info_lookup = {}
        for teacher, courses in self.lab_requirements.items():
            for course in courses:
                course_info_lookup[course['course_instance_id']] = course
        
        # Define the mapping from lab sessions to individual time slots
        lab_session_to_slots = {
            'L1': ['8:00 - 8:50', '8:50 - 9:40'],
            'L2': ['9:50 - 10:40', '10:40 - 11:30'],
            'L3': ['11:50 - 12:40', '12:40 - 1:30'],
            'L4': ['1:50 - 2:40', '2:40 - 3:30'],
            'L5': ['3:50 - 4:40', '4:40 - 5:30'],
            'L6': ['5:30 - 6:20', '6:20 - 7:10']
        }
        
        # Create mapping from lab time slots to unique slot indices (separate from theory)
        # Theory uses slot indices 0-10, so lab will use 20+ to avoid conflicts
        lab_slot_index_map = {}
        for time_slot in self.lab_time_slots:
            lab_slot_index_map[time_slot] = 20 + self.lab_time_slots.index(time_slot)
        
        # Process lab assignments for each course
        assignments_found = 0
        course_batch_counters = {}  # Track batch numbers per course instance
        
        for course_instance_id in lab_assignments.keys():
            teacher = course_to_teacher[course_instance_id]
            course_info = course_info_lookup[course_instance_id]
            
            # Initialize batch counter for this course
            course_batch_counters[course_instance_id] = 0
            
            for day_idx, day in enumerate(self.days):
                for session_idx, session_name in enumerate(lab_sessions):
                    for room_id in lab_info.keys():
                        if solver.Value(lab_assignments[course_instance_id][day_idx][session_idx][room_id]) == 1:
                            assignments_found += 1
                            
                            # Increment batch counter for this course instance
                            course_batch_counters[course_instance_id] += 1
                            current_assignment_number = course_batch_counters[course_instance_id]
                            
                            # Found an assignment - expand to individual time slots
                            session_time_slots = lab_session_to_slots[session_name]
                            
                            # Get teacher and lab information
                            teacher_info = teacher_info_cache[teacher]
                            room_details = lab_info[room_id]
                            
                            # DYNAMIC BATCHING: Determine batching based on actual assigned lab capacity
                            room_capacity = room_details['capacity']
                            original_student_count = course_info['students_per_instance']
                            
                            # Check if this assignment requires batching due to capacity mismatch
                            needs_batching = (original_student_count > room_capacity)
                            
                            if needs_batching:
                                # Calculate how many batches are needed based on lab capacity
                                calculated_batches = (original_student_count + room_capacity - 1) // room_capacity  # Round up
                                students_per_batch = min(room_capacity, (original_student_count + calculated_batches - 1) // calculated_batches)
                                
                                # Each course assignment represents one batch
                                # Calculate which batch this assignment represents
                                base_sessions = course_info['required_sessions']
                                batch_number = ((current_assignment_number - 1) // base_sessions) + 1
                                
                                is_batched = True
                                batch_info = f"Batch {batch_number}"
                                display_course_code = f"{course_info.get('display_course_code', course_info['course_code'])} B{batch_number}"
                                student_count_for_assignment = students_per_batch
                            else:
                                # No batching needed - lab capacity can handle full course
                                student_count_for_assignment = min(room_capacity, original_student_count)
                                is_batched = False
                                batch_number = None
                                batch_info = ""
                                display_course_code = course_info.get('display_course_code', course_info['course_code'])
                            
                            # Create entries for each time slot in the session
                            for slot_idx, time_slot in enumerate(session_time_slots):
                                # Use separate lab slot index mapping to avoid conflicts with theory
                                lab_slot_index = lab_slot_index_map[time_slot]
                                
                                lab_schedule_data.append({
                                    'day': day,
                                    'slot_index': lab_slot_index,  # Use separate lab slot indices
                                    'time_interval': time_slot,
                                    'slot_type': 'Practical',
                                    'lab_session': session_name,
                                    'lab_session_slot': slot_idx + 1,  # 1 or 2 within the session
                                    'teacher_id': teacher,
                                    'first_name': teacher_info['first_name'],
                                    'last_name': teacher_info['last_name'],
                                    'staff_code': teacher_info['staff_code'],
                                    'room_id': room_id,
                                    'room_number': room_details['room_number'],
                                    'room_capacity': room_details['capacity'],  # Add room capacity info
                                    'block': room_details['block'],
                                    'room_type': 'Lab',
                                    'capacity': room_details['capacity'],
                                    'course_id': course_info['course_id'],
                                    'course_code': course_info['course_code'],
                                    'display_course_code': display_course_code,  # Include batch info if applicable
                                    'course_name': course_info['course_name'],
                                    'course_instance_id': course_info['course_instance_id'],
                                    'student_count': student_count_for_assignment,  # Capacity-adjusted student count
                                    'total_instance_students': course_info['students_per_instance'],  # Original instance size
                                    'practical_hours': course_info['practical_hours'],
                                    'semester': course_info.get('semester', ''),
                                    'course_dept': course_info.get('course_dept', ''),
                                    'teacher_shift': 'combined_shift',
                                    'daily_shift_pattern': 'Combined→Combined→Combined→Combined→Combined',
                                    
                                    # Capacity and batching information
                                    'is_batched': is_batched,
                                    'batch_number': batch_number if is_batched else None,
                                    'batch_info': batch_info,
                                    'num_batches': course_info['num_batches'],
                                    'students_per_batch': student_count_for_assignment,
                                    'lab_capacity_category': self._categorize_lab_capacity(room_details['capacity']),
                                    'room_utilization_ratio': student_count_for_assignment / room_details['capacity'] if room_details['capacity'] > 0 else 0
                                })
                            
                            # Log assignment with capacity and batching info
                            capacity_info = f"Capacity: {room_details['capacity']}"
                            utilization_ratio = student_count_for_assignment / room_details['capacity'] if room_details['capacity'] > 0 else 0
                            utilization_info = f", Utilization: {utilization_ratio:.1%}"
                            batch_log = f" (Batch {batch_number}, {student_count_for_assignment} students)" if is_batched else f" ({student_count_for_assignment} students)"
                            
                            self.logger.info(f"Lab assignment: Course {display_course_code} (ID: {course_info['course_instance_id']}, Teacher {teacher}) -> "
                                           f"{session_name} ({session_time_slots[0]} to {session_time_slots[1]}) in "
                                           f"Lab {room_details['room_number']} ({capacity_info}{utilization_info}){batch_log}")
        
        self.logger.info(f"Found {assignments_found} lab session assignments")
        self.logger.info(f"Processed {len(lab_schedule_data)} lab time slot assignments")
        return lab_schedule_data
    
    def _categorize_lab_capacity(self, capacity):
        """Categorize lab capacity into standard categories."""
        if capacity <= 35:
            return "35-capacity"
        elif capacity <= 70:
            return "70-capacity"
        elif capacity >= 140:
            return "140-capacity"
        else:
            return f"{capacity}-capacity"
    
    def combine_theory_and_lab_schedules(self, lab_schedule_data):
        """Combine existing theory schedule with new lab schedule."""
        self.logger.info("Combining theory and lab schedules...")
        
        combined_schedule = []
        
        # Add existing theory schedule data
        for _, theory_row in self.theory_schedule_df.iterrows():
            theory_entry = {
                'day': theory_row['day'],
                'slot_index': theory_row['slot_index'],
                'time_interval': theory_row['time_interval'],
                'slot_type': theory_row['slot_type'],
                'macroblock': theory_row.get('macroblock', ''),
                'teacher_id': theory_row['teacher_id'],
                'first_name': theory_row.get('first_name', ''),
                'last_name': theory_row.get('last_name', ''),
                'staff_code': theory_row.get('staff_code', ''),
                'room_id': theory_row['room_id'],
                'room_number': theory_row['room_number'],
                'block': theory_row.get('block', ''),
                'room_type': theory_row.get('room_type', 'Classroom'),
                'capacity': theory_row.get('capacity', 0),
                'course_id': theory_row.get('course_id', ''),
                'course_code': theory_row.get('course_code', ''),
                'course_name': theory_row.get('course_name', ''),
                'course_instance_id': theory_row.get('course_instance_id', ''),
                'student_count': theory_row.get('student_count', 0),
                'semester': theory_row.get('semester', ''),
                'course_dept': theory_row.get('course_dept', ''),
                'teacher_shift': theory_row.get('teacher_shift', 'combined_shift'),
                'daily_shift_pattern': theory_row.get('daily_shift_pattern', 'Combined→Combined→Combined→Combined→Combined'),
                # Lab-specific fields (empty for theory)
                'lab_session': '',
                'lab_session_slot': '',
                'practical_hours': 0
            }
            combined_schedule.append(theory_entry)
        
        # Add lab schedule data with consistent structure
        for lab_entry in lab_schedule_data:
            lab_schedule_entry = {
                'day': lab_entry['day'],
                'slot_index': lab_entry['slot_index'],
                'time_interval': lab_entry['time_interval'],
                'slot_type': lab_entry['slot_type'],
                'macroblock': f"LAB_{lab_entry['lab_session']}_{lab_entry['lab_session_slot']}",
                'teacher_id': lab_entry['teacher_id'],
                'first_name': lab_entry['first_name'],
                'last_name': lab_entry['last_name'],
                'staff_code': lab_entry['staff_code'],
                'room_id': lab_entry['room_id'],
                'room_number': lab_entry['room_number'],
                'room_capacity': lab_entry.get('room_capacity', lab_entry['capacity']),  # Include room capacity
                'block': lab_entry['block'],
                'room_type': lab_entry['room_type'],
                'capacity': lab_entry['capacity'],
                'course_id': lab_entry['course_id'],
                'course_code': lab_entry['course_code'],
                'display_course_code': lab_entry.get('display_course_code', lab_entry['course_code']),  # S1, S2 differentiation
                'course_name': lab_entry['course_name'],
                'course_instance_id': lab_entry['course_instance_id'],
                'student_count': lab_entry['student_count'],  # This now includes capacity-adjusted count
                'total_instance_students': lab_entry.get('total_instance_students', lab_entry['student_count']),  # Original instance size
                'semester': lab_entry['semester'],
                'course_dept': lab_entry['course_dept'],
                'teacher_shift': lab_entry['teacher_shift'],
                'daily_shift_pattern': lab_entry['daily_shift_pattern'],
                # Lab-specific fields
                'lab_session': lab_entry['lab_session'],
                'lab_session_slot': lab_entry['lab_session_slot'],
                'practical_hours': lab_entry['practical_hours'],
                
                # Capacity and batching information (new fields)
                'is_batched': lab_entry.get('is_batched', False),
                'batch_number': lab_entry.get('batch_number', None),
                'batch_info': lab_entry.get('batch_info', ''),
                'num_batches': lab_entry.get('num_batches', 1),
                'students_per_batch': lab_entry.get('students_per_batch', lab_entry['student_count']),
                'lab_capacity_category': lab_entry.get('lab_capacity_category', 'unknown-capacity')
            }
            combined_schedule.append(lab_schedule_entry)
        
        self.logger.info(f"Combined schedule created: {len(self.theory_schedule_df)} theory + {len(lab_schedule_data)} lab = {len(combined_schedule)} total")
        return combined_schedule
    
    def save_lab_schedule_results(self, combined_schedule):
        """Save the combined theory+lab schedule results to files."""
        # Use the existing output directory (self.output_dir) instead of creating a new one
        output_dir = self.output_dir  # Use the directory created in __init__
        
        self.logger.info(f"Saving lab schedule results to: {output_dir}")
        
        # Save combined schedule
        if combined_schedule:
            combined_df = pd.DataFrame(combined_schedule)
            
            # Save main combined schedule
            combined_schedule_path = os.path.join(output_dir, 'combined_theory_lab_schedule.csv')
            combined_df.to_csv(combined_schedule_path, index=False, encoding='utf-8')
            self.logger.info(f"Combined schedule saved to {combined_schedule_path}")
            
            # Save lab-only schedule
            lab_only_df = combined_df[combined_df['slot_type'] == 'Practical']
            if not lab_only_df.empty:
                lab_schedule_path = os.path.join(output_dir, 'lab_schedule.csv')
                lab_only_df.to_csv(lab_schedule_path, index=False, encoding='utf-8')
                self.logger.info(f"Lab schedule saved to {lab_schedule_path}")
            
            # Save individual teacher schedules
            for teacher in combined_df['teacher_id'].unique():
                teacher_schedule = combined_df[combined_df['teacher_id'] == teacher]
                if not teacher_schedule.empty:
                    teacher_schedule_path = os.path.join(output_dir, f'teacher_{teacher}_combined_schedule.csv')
                    teacher_schedule.to_csv(teacher_schedule_path, index=False, encoding='utf-8')
            
            # Save individual lab room schedules
            lab_rooms_df = combined_df[combined_df['room_type'] == 'Lab']
            for room_id in lab_rooms_df['room_id'].unique():
                room_schedule = combined_df[combined_df['room_id'] == room_id]
                if not room_schedule.empty:
                    room_schedule_path = os.path.join(output_dir, f'lab_room_{room_id}_schedule.csv')
                    room_schedule.to_csv(room_schedule_path, index=False, encoding='utf-8')
        
        # Generate lab summary
        self.generate_lab_summary(combined_schedule, output_dir)
        
        # Generate lab visualizations
        self.generate_lab_visualizations(combined_schedule, output_dir)
        
        # Validate lab constraints
        if combined_schedule:
            self.validate_generated_schedule(combined_schedule, output_dir)
        
        return output_dir
    
    def generate_lab_visualizations(self, combined_schedule, output_dir):
        """Generate lab schedule visualizations including individual teacher lab schedules."""
        if not LAB_VISUALIZER_AVAILABLE:
            self.logger.warning("Lab visualizer not available - skipping visualization generation")
            return
        
        if not combined_schedule:
            self.logger.warning("No schedule data available for visualization")
            return
        
        try:
            self.logger.info("Generating lab schedule visualizations...")
            
            # Create lab visualizer with schedule data
            lab_visualizer = LabScheduleVisualizer(combined_schedule, output_dir)
            
            # Generate all lab visualizations
            lab_visualizer.generate_all_lab_visualizations()
            
            self.logger.info("Lab schedule visualizations generated successfully")
            self.logger.info(f"Visualizations saved in: {output_dir}")
            
            # List generated visualization files
            visualization_files = []
            for file in os.listdir(output_dir):
                if file.endswith('.png'):
                    visualization_files.append(file)
            
            if visualization_files:
                self.logger.info(f"Generated {len(visualization_files)} visualization files:")
                for file in sorted(visualization_files):
                    self.logger.info(f"  - {file}")
            
        except ImportError as e:
            self.logger.warning(f"Could not generate lab visualizations due to missing dependencies: {e}")
        except Exception as e:
            self.logger.error(f"Error generating lab visualizations: {e}")
            self.logger.exception("Lab visualization error details")
    
    def generate_lab_summary(self, combined_schedule, output_dir):
        """Generate a summary of the lab schedule."""
        if not combined_schedule:
            self.logger.warning("No schedule data available for summary")
            return
        
        summary_path = os.path.join(output_dir, 'lab_summary.txt')
        
        # Convert to DataFrame for easier analysis
        schedule_df = pd.DataFrame(combined_schedule)
        lab_data = schedule_df[schedule_df['slot_type'] == 'Practical']
        theory_data = schedule_df[schedule_df['slot_type'].isin(['Lecture', 'Tutorial'])]
        
        with open(summary_path, 'w', encoding='utf-8') as f:
            f.write("Lab Schedule Summary\n")
            f.write("===================\n\n")
            
            f.write(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            
            # Overall statistics
            f.write("Overall Statistics:\n")
            f.write(f"Total scheduled entries: {len(schedule_df)}\n")
            f.write(f"Theory/Tutorial classes: {len(theory_data)}\n")
            f.write(f"Practical/Lab classes: {len(lab_data)}\n\n")
            
            if len(lab_data) == 0:
                f.write("No lab classes were scheduled.\n")
                f.write("This could be due to:\n")
                f.write("  - No courses with practical_hours > 0 found\n")
                f.write("  - Insufficient lab rooms available\n")
                f.write("  - Conflicts with existing theory schedule\n")
                self.logger.info("Lab summary saved with no lab allocations")
                return
            
            # Lab allocation statistics
            f.write("Lab Allocation Details:\n")
            
            # Teachers with lab assignments
            lab_teachers = lab_data['teacher_id'].unique()
            f.write(f"Teachers with lab assignments: {len(lab_teachers)}\n")
            
            # Courses with lab assignments
            lab_courses = lab_data['course_code'].unique()
            f.write(f"Courses with lab assignments: {len(lab_courses)}\n")
            
            # Lab rooms utilized
            lab_rooms = lab_data['room_id'].unique()
            f.write(f"Lab rooms utilized: {len(lab_rooms)}\n\n")
            
            # Lab session distribution
            f.write("Lab Session Distribution:\n")
            if 'time_interval' in lab_data.columns:
                session_counts = lab_data['time_interval'].value_counts()
                for session, count in session_counts.items():
                    f.write(f"  {session}: {count} assignments\n")
            f.write("\n")
            
            # Daily lab distribution
            f.write("Daily Lab Distribution:\n")
            daily_counts = lab_data['day'].value_counts()
            for day in ['tuesday', 'wed', 'thur', 'fri', 'sat']:
                count = daily_counts.get(day, 0)
                f.write(f"  {day.capitalize()}: {count} lab sessions\n")
            f.write("\n")
            
            # Course-wise lab allocation
            f.write("Course-wise Lab Allocation:\n")
            course_counts = lab_data['course_code'].value_counts()
            for course, count in course_counts.items():
                f.write(f"  {course}: {count} lab sessions\n")
            f.write("\n")
            
            # Teacher workload analysis
            f.write("Teacher Workload Analysis (Including Labs):\n")
            teacher_workload = {}
            
            for teacher in schedule_df['teacher_id'].unique():
                teacher_assignments = schedule_df[schedule_df['teacher_id'] == teacher]
                theory_hours = len(teacher_assignments[teacher_assignments['slot_type'].isin(['Lecture', 'Tutorial'])])
                lab_hours = len(teacher_assignments[teacher_assignments['slot_type'] == 'Practical']) * 2  # Each lab = 2 hours
                total_hours = theory_hours + lab_hours
                teacher_workload[teacher] = {'theory': theory_hours, 'lab': lab_hours, 'total': total_hours}
            
            for teacher, workload in sorted(teacher_workload.items()):
                f.write(f"  Teacher {teacher}: {workload['theory']} theory + {workload['lab']} lab = {workload['total']} total hours\n")
            
            # Check for overloaded teachers
            overloaded = [t for t, w in teacher_workload.items() if w['total'] > 21]
            if overloaded:
                f.write(f"\nTeachers exceeding 21-hour limit: {len(overloaded)}\n")
                for teacher in overloaded:
                    f.write(f"  Teacher {teacher}: {teacher_workload[teacher]['total']} hours\n")
            else:
                f.write(f"\nAll teachers within 21-hour weekly limit ✓\n")
            
            # Lab room utilization
            f.write("\nLab Room Utilization:\n")
            if 'room_number' in lab_data.columns:
                room_usage = lab_data['room_number'].value_counts()
                for room, count in room_usage.items():
                    f.write(f"  {room}: {count} sessions\n")
            
            f.write(f"\nLab schedule generation completed successfully!\n")
        
        self.logger.info(f"Lab summary saved to {summary_path}")

    def generate_lab_schedule_relaxed(self, lab_assignments, lab_room_ids, lab_sessions, model):
        """Try lab scheduling with more relaxed constraints."""
        self.logger.info("Generating lab schedule with relaxed constraints...")
        
        # Clear the model and start fresh with minimal constraints
        model = cp_model.CpModel()
        
        # Create variables for each course instance that needs labs
        all_course_instances = []
        course_to_teacher = {}
        
        for teacher, courses in self.lab_requirements.items():
            for course in courses:
                course_instance_id = course['course_instance_id']
                all_course_instances.append(course_instance_id)
                course_to_teacher[course_instance_id] = teacher
                
                lab_assignments[course_instance_id] = {}
                for day_idx in range(self.num_days):
                    lab_assignments[course_instance_id][day_idx] = {}
                    for session_idx, session_name in enumerate(lab_sessions):
                        lab_assignments[course_instance_id][day_idx][session_idx] = {}
                        for room_id in lab_room_ids:
                            lab_assignments[course_instance_id][day_idx][session_idx][room_id] = model.NewBoolVar(
                                f'relaxed_course_{course_instance_id}_day_{day_idx}_session_{session_name}_lab_{room_id}')
        
        # Apply relaxed constraints using the LabConstraints class
        self.lab_constraints.apply_relaxed_constraints(model, lab_assignments, lab_room_ids, lab_sessions, course_to_teacher)
        
        # Solve with relaxed constraints
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 180
        status = solver.Solve(model)
        
        if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
            self.logger.info(f"Relaxed lab allocation solution found with status {status}!")
            
            lab_schedule_data = self.process_lab_solution(solver, lab_assignments, lab_sessions, course_to_teacher)
            combined_schedule = self.combine_theory_and_lab_schedules(lab_schedule_data)
            output_dir = self.save_lab_schedule_results(combined_schedule)
            return output_dir
        else:
            self.logger.error(f"Even relaxed lab allocation failed. Status: {status}")
            return False

    def validate_generated_schedule(self, combined_schedule, output_dir):
        """Validate that the generated lab schedule satisfies all constraints."""
        self.logger.info("Validating generated lab schedule against constraints...")
        
        try:
            # Convert to DataFrame for validation
            schedule_df = pd.DataFrame(combined_schedule)
            
            # Validate constraints
            violations = validate_lab_constraints(schedule_df, self.lab_requirements)
            
            # Analyze constraint conflicts
            analysis = analyze_constraint_conflicts(self.lab_requirements, self.theory_schedule_df, self.labs)
            
            # Save validation report
            validation_path = os.path.join(output_dir, 'constraint_validation.txt')
            with open(validation_path, 'w', encoding='utf-8') as f:
                f.write("Lab Schedule Constraint Validation Report\n")
                f.write("=========================================\n\n")
                f.write(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                
                f.write("Constraint Violation Check:\n")
                if violations:
                    f.write(f"❌ Found {len(violations)} constraint violations:\n")
                    for violation in violations:
                        f.write(f"  - {violation}\n")
                else:
                    f.write("✅ All constraints satisfied successfully!\n")
                
                f.write(f"\nCapacity Analysis:\n")
                f.write(f"Total lab sessions needed: {analysis['total_lab_sessions_needed']}\n")
                f.write(f"Total lab capacity per week: {analysis['total_lab_capacity']}\n")
                f.write(f"Capacity utilization: {analysis['total_lab_sessions_needed'] / analysis['total_lab_capacity'] * 100:.1f}%\n")
                
                if analysis['teacher_overloads']:
                    f.write(f"\n⚠️ Teacher workload warnings ({len(analysis['teacher_overloads'])}):\n")
                    for overload in analysis['teacher_overloads']:
                        f.write(f"  - Teacher {overload['teacher']}: {overload['total_hours']} hours "
                               f"({overload['theory_hours']} theory + {overload['lab_hours']} lab)\n")
                else:
                    f.write(f"\n✅ All teachers within workload limits\n")
            
            if violations:
                self.logger.warning(f"Found {len(violations)} constraint violations in generated schedule")
                for violation in violations:
                    self.logger.warning(f"Violation: {violation}")
            else:
                self.logger.info("✅ All lab constraints validated successfully!")
            
            self.logger.info(f"Constraint validation report saved to {validation_path}")
            
        except Exception as e:
            self.logger.error(f"Error during constraint validation: {e}")
            self.logger.exception("Constraint validation error details")

def main():
    """Main function to run the lab scheduler."""
    try:
        print("*" * 80)
        print("Lab Scheduler - Separate Lab Allocation After Theory")
        print("*" * 80)
        print("Lab scheduling features:")
        print("• Lab sessions: L1 (8:00-9:40), L2 (9:50-11:30), L3 (11:50-1:30), etc.")
        print("• Each lab session = 2 practical hours")
        print("• No overlapping with existing theory schedule")
        print("• Allocates labs based on practical_hours in course data")
        print("• Generates individual teacher lab schedule visualizations")
        print("• Continuous lab room assignment: L1 uses same room for both slots")
        print("*" * 80)
        
        # Get the base directory of the project (timetable_scheduler directory)
        base_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Find the most recent theory schedule
        output_base_dir = os.path.join(base_dir, 'output')
        
        if not os.path.exists(output_base_dir):
            print(f"Error: Output directory not found at {output_base_dir}")
            return
        
        # Find theory schedule directories
        theory_schedule_dirs = []
        for item in os.listdir(output_base_dir):
            if item.startswith('macroblock_schedule_') and os.path.isdir(os.path.join(output_base_dir, item)):
                theory_schedule_dirs.append(item)
        
        if not theory_schedule_dirs:
            print("Error: No existing theory schedule found. Please run the main scheduler first.")
            print(f"Expected location: {output_base_dir}/macroblock_schedule_*/macroblock_schedule.csv")
            return
        
        # Get the most recent theory schedule
        latest_theory_dir = sorted(theory_schedule_dirs)[-1]
        theory_schedule_path = os.path.join(output_base_dir, latest_theory_dir, 'macroblock_schedule.csv')
        
        if not os.path.exists(theory_schedule_path):
            print(f"Error: Theory schedule file not found at {theory_schedule_path}")
            return
        
        print(f"✓ Found theory schedule: {theory_schedule_path}")
        
        # Path to data files (same as theory scheduler)
        course_file = os.path.join(base_dir, "data/mapped_data/computer_dept_teacher_courses.csv")
        room_file = os.path.join(base_dir, 'data/block_wise/techlongue.csv')
        
        if not os.path.exists(course_file):
            print(f"Error: Course file not found at {course_file}")
            return
        
        if not os.path.exists(room_file):
            print(f"Error: Room file not found at {room_file}")
            return
        
        print(f"✓ Found course file: {course_file}")
        print(f"✓ Found room file: {room_file}")
        
        # Create and run the lab scheduler
        print("\nCreating lab scheduler...")
        lab_scheduler = LabScheduler(theory_schedule_path, course_file, room_file)
        
        print("Generating lab schedule...")
        output_dir = lab_scheduler.generate_lab_schedule()
        
        if output_dir:
            print("✅ Lab schedule generated successfully!")
            print(f"📁 Lab schedule outputs saved to: {output_dir}")
            print("\n📋 Generated files:")
            print("  - combined_theory_lab_schedule.csv: Complete theory + lab schedule")
            print("  - lab_schedule.csv: Lab-only schedule")
            print("  - teacher_*_lab_schedule.csv: Individual teacher lab schedules")
            print("  - lab_schedule_images/: Teacher lab schedule visualizations")
            print("  - lab_summary.txt: Lab allocation summary")
            print("\n💡 Lab scheduling features implemented:")
            print("  ✓ L1-L6 lab sessions (2 hours each)")
            print("  ✓ No conflicts with existing theory schedule")
            print("  ✓ Continuous room assignment for multi-slot sessions")
            print("  ✓ Individual teacher lab visualizations")
        else:
            print("❌ Failed to generate a feasible lab schedule.")
            print("💡 Try adjusting course requirements or increasing available lab rooms.")
    except Exception as e:
        print(f"❌ Error in lab schedule generation: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main() 