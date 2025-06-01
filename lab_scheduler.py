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
        
        # Define shift timings and their corresponding lab sessions
        self.shift_definitions = {
            'shift1': {
                'time_range': '8:00 - 3:00',
                'allowed_lab_sessions': ['L1', 'L2', 'L3'],  # 8:00-9:40, 9:50-11:30, 11:50-1:30, 1:50-3:30
                'description': 'Morning to Early Afternoon Shift'
            },
            'shift2': {
                'time_range': '10:00 - 5:00', 
                'allowed_lab_sessions': ['L2', 'L3', 'L4'],  # 9:50-11:30, 11:50-1:30, 1:50-3:30, 3:50-5:30
                'description': 'Mid-day to Afternoon Shift'
            },
            'shift3': {
                'time_range': '12:00 - 7:00',
                'allowed_lab_sessions': ['L4', 'L5', 'L6'],  # 11:50-1:30, 1:50-3:30, 3:50-5:30, 5:30-7:10
                'description': 'Afternoon to Evening Shift'
            }
        }
        
        # Process rooms - separate labs from classrooms
        self.labs = self.rooms_df[self.rooms_df['is_lab'] == 1]
        self.classrooms = self.rooms_df[self.rooms_df['is_lab'] == 0]
        
        # Load teacher shift data from latest theory schedule
        self.teacher_shift_data = self._load_teacher_shift_data(theory_schedule_path)
        
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
        self.logger.info(f"Loaded shift data for {len(self.teacher_shift_data)} teacher-day combinations")
    
    def _load_teacher_shift_data(self, theory_schedule_path):
        """Load teacher shift data from the latest theory schedule output."""
        teacher_shift_data = {}
        
        # Get the theory schedule directory
        theory_dir = os.path.dirname(theory_schedule_path)
        shift_file_path = os.path.join(theory_dir, 'teacher_daily_shifts.csv')
        
        if os.path.exists(shift_file_path):
            self.logger.info(f"Loading teacher shift data from: {shift_file_path}")
            shift_df = pd.read_csv(shift_file_path)
            
            for _, row in shift_df.iterrows():
                teacher_id = row['teacher_id']
                day = row['day']
                shift = row['shift']
                shift_name = row.get('shift_name', 'No Classes')
                recommended_shift = row.get('recommended_shift', '')
                
                if teacher_id not in teacher_shift_data:
                    teacher_shift_data[teacher_id] = {}
                
                # Use actual shift if available, otherwise use recommended shift
                effective_shift = shift if shift != 'no_classes' else recommended_shift
                
                teacher_shift_data[teacher_id][day] = {
                    'shift': effective_shift,
                    'shift_name': shift_name,
                    'original_shift': shift,
                    'recommended_shift': recommended_shift
                }
            
            self.logger.info(f"Successfully loaded shift data for {len(teacher_shift_data)} teachers")
        else:
            self.logger.warning(f"Teacher shift file not found at: {shift_file_path}")
            self.logger.warning("Lab scheduling will proceed without shift constraints")
        
        return teacher_shift_data
    
    def get_teacher_allowed_lab_sessions(self, teacher_id, day):
        """Get the allowed lab sessions for a teacher on a specific day based on their shift."""
        if (teacher_id in self.teacher_shift_data and 
            day in self.teacher_shift_data[teacher_id]):
            
            shift_info = self.teacher_shift_data[teacher_id][day]
            shift = shift_info['shift']
            
            if shift in self.shift_definitions:
                allowed_sessions = self.shift_definitions[shift]['allowed_lab_sessions']
                self.logger.debug(f"Teacher {teacher_id} on {day}: {shift} -> allowed sessions {allowed_sessions}")
                return allowed_sessions
            else:
                # If no valid shift or shift is 'no_classes', allow all sessions
                self.logger.debug(f"Teacher {teacher_id} on {day}: no valid shift ({shift}) -> allowing all sessions")
                return list(self.lab_sessions.keys())
        else:
            # If no shift data available, allow all sessions
            self.logger.debug(f"Teacher {teacher_id} on {day}: no shift data -> allowing all sessions")
            return list(self.lab_sessions.keys())
    
    def validate_lab_session_against_shift(self, teacher_id, day, lab_session):
        """Validate if a lab session is allowed for a teacher's shift on a specific day."""
        allowed_sessions = self.get_teacher_allowed_lab_sessions(teacher_id, day)
        is_valid = lab_session in allowed_sessions
        
        if not is_valid:
            shift_info = self.teacher_shift_data.get(teacher_id, {}).get(day, {})
            shift = shift_info.get('shift', 'unknown')
            self.logger.warning(f"SHIFT VIOLATION: Teacher {teacher_id} on {day} cannot use lab session {lab_session} "
                              f"(shift: {shift}, allowed: {allowed_sessions})")
        
        return is_valid
    
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
        """Analyze available lab capacities and categorize them - USE ACTUAL CAPACITIES WITH 140->70 MAPPING."""
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
            
            # UPDATED CONSTRAINT: Use actual capacities, but treat 140 as 70
            if original_capacity >= 140:
                effective_capacity = 70  # Treat 140-capacity labs as 70
                category = 'labs_70'
                count_key = '70'
                total_key = 'total_capacity_70'
            elif original_capacity >= 70:
                effective_capacity = 70
                category = 'labs_70'
                count_key = '70'
                total_key = 'total_capacity_70'
            elif original_capacity >= 35:
                effective_capacity = 35
                category = 'labs_35'
                count_key = '35'
                total_key = 'total_capacity_35'
            else:
                effective_capacity = 35  # Default small labs to 35
                category = 'labs_35'
                count_key = '35'
                total_key = 'total_capacity_35'
            
            lab_info = {
                'id': lab_id,
                'room_number': lab_row['room_number'],
                'capacity': effective_capacity,
                'original_capacity': original_capacity,
                'block': lab_row.get('block', ''),
                'description': lab_row.get('description', '')
            }
            
            lab_capacity_analysis[category].append(lab_info)
            lab_capacity_analysis['capacity_counts'][count_key] += 1
            lab_capacity_analysis[total_key] += effective_capacity
        
        return lab_capacity_analysis
    
    def _determine_lab_allocation_strategy(self, practical_hours, students_per_instance):
        """Determine the optimal lab allocation strategy - HARD CONSTRAINT: Only >=3 practical hours can use 70-capacity labs."""
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
        
        # HARD CONSTRAINT: Only courses with practical_hours >= 3 can use 70-capacity labs
        if students_per_instance == 70:
            if practical_hours >= 3:
                # Courses with >=3 practical hours: can use 70-capacity labs (preferred) or 35-capacity labs (with batching)
                strategy['preferred_lab_capacities'] = [70, 35]  # Prefer 70, allow 35 as fallback
                
                self.logger.info(f"70-student course with {practical_hours} practical hours -> "
                               f"CAN use 70-capacity labs (>=3 practical hours), prefer {strategy['preferred_lab_capacities']}")
            else:
                # Courses with <3 practical hours: MUST use 35-capacity labs only (forced batching)
                strategy['preferred_lab_capacities'] = [35]  # Only 35-capacity labs allowed
                strategy['can_use_70_capacity'] = False
                strategy['batching_required'] = True  # Force batching since only 35-capacity allowed
                strategy['num_batches'] = 2
                strategy['students_per_batch'] = 35
                strategy['total_lab_slots_needed'] = base_sessions * 2  # Double slots for batching
                
                self.logger.info(f"70-student course with {practical_hours} practical hours -> "
                               f"CANNOT use 70-capacity labs (<3 practical hours), forced to 35-capacity with batching")
            
            # Prepare for potential batching if 35-capacity labs are assigned
            strategy['potential_batching_needed'] = True
            strategy['max_possible_batches'] = 2
            
        elif students_per_instance > 70:
            # For >70 students, always prefer 70-capacity but check practical hours constraint
            if practical_hours >= 3:
                strategy['preferred_lab_capacities'] = [70, 35]
                strategy['can_use_70_capacity'] = True
            else:
                strategy['preferred_lab_capacities'] = [35]  # Only 35-capacity allowed
                strategy['can_use_70_capacity'] = False
            
            strategy['potential_batching_needed'] = True
            strategy['max_possible_batches'] = (students_per_instance + 69) // 70  # Round up
        else:
            # ≤35 students - can use any capacity, prefer 35 for efficiency
            # But still respect the practical hours constraint for 70-capacity labs
            if practical_hours >= 3:
                strategy['preferred_lab_capacities'] = [35, 70]
                strategy['can_use_70_capacity'] = True
            else:
                strategy['preferred_lab_capacities'] = [35]  # Only 35-capacity allowed
                strategy['can_use_70_capacity'] = False
        
        return strategy
    
    def _log_capacity_analysis(self):
        """Log detailed capacity analysis for debugging - HARD CONSTRAINT: >=3 practical hours for 70-capacity labs."""
        analysis = self.lab_capacity_analysis
        
        self.logger.info("=" * 60)
        self.logger.info("LAB CAPACITY ANALYSIS (HARD CONSTRAINT: >=3 PRACTICAL HOURS FOR 70-CAPACITY)")
        self.logger.info("=" * 60)
        
        self.logger.info(f"35-capacity labs: {analysis['capacity_counts']['35']} labs")
        for lab in analysis['labs_35']:
            original_cap = lab.get('original_capacity', 'Unknown')
            effective_cap = lab['capacity']
            if original_cap != effective_cap:
                self.logger.info(f"  - {lab['room_number']} (ID: {lab['id']}, Effective: {effective_cap}, Original: {original_cap})")
            else:
                self.logger.info(f"  - {lab['room_number']} (ID: {lab['id']}, Capacity: {effective_cap})")
        
        self.logger.info(f"70-capacity labs: {analysis['capacity_counts']['70']} labs")
        for lab in analysis['labs_70']:
            original_cap = lab.get('original_capacity', 'Unknown')
            effective_cap = lab['capacity']
            if original_cap != effective_cap:
                self.logger.info(f"  - {lab['room_number']} (ID: {lab['id']}, Effective: {effective_cap}, Original: {original_cap})")
            else:
                self.logger.info(f"  - {lab['room_number']} (ID: {lab['id']}, Capacity: {effective_cap})")
        
        if analysis['capacity_counts']['140'] > 0:
            self.logger.info(f"140-capacity labs (treated as 70): {analysis['capacity_counts']['140']} labs")
        
        total_lab_capacity = analysis['total_capacity_35'] + analysis['total_capacity_70']
        
        self.logger.info(f"Total lab capacity: {total_lab_capacity} students")
        self.logger.info(f"  - 35-capacity: {analysis['total_capacity_35']} students")
        self.logger.info(f"  - 70-capacity: {analysis['total_capacity_70']} students")
        self.logger.info("HARD CONSTRAINT RULES:")
        self.logger.info("  - Courses with practical_hours >= 3: CAN use 70-capacity labs")
        self.logger.info("  - Courses with practical_hours < 3: MUST use 35-capacity labs only")
        self.logger.info("  - 70-student courses in 35-capacity labs: automatic batching (B1, B2)")
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
        
        # Add optimization objective - minimize total lab usage with capacity preferences
        total_lab_usage = []
        capacity_preference_penalties = []
        shift_preference_penalties = []
        
        # Get lab rooms categorized by capacity for preference weighting
        labs_by_capacity = {
            35: [lab['id'] for lab in self.lab_capacity_analysis['labs_35']],
            70: [lab['id'] for lab in self.lab_capacity_analysis['labs_70']],
            140: [lab['id'] for lab in self.lab_capacity_analysis['labs_140']]
        }
        
        for course_instance_id in all_course_instances:
            # Get course information for preference weighting
            teacher = course_to_teacher[course_instance_id]
            course_info = None
            for course in self.lab_requirements[teacher]:
                if course['course_instance_id'] == course_instance_id:
                    course_info = course
                    break
            
            for day_idx in range(self.num_days):
                day = self.days[day_idx]
                # Get allowed sessions for this teacher on this day
                allowed_sessions = self.get_teacher_allowed_lab_sessions(teacher, day)
                
                for session_idx in range(len(lab_sessions)):
                    session_name = lab_sessions[session_idx]
                    
                    for room_id in lab_room_ids:
                        assignment_var = lab_assignments[course_instance_id][day_idx][session_idx][room_id]
                        total_lab_usage.append(assignment_var)
                        
                        # Add shift preference penalties
                        if session_name not in allowed_sessions:
                            # Heavy penalty for assignments outside teacher's shift
                            shift_preference_penalties.extend([assignment_var] * 100)
                        else:
                            # Light penalty for assignments within shift (to minimize total usage)
                            shift_preference_penalties.extend([assignment_var] * 1)
                        
                        # Add capacity preference penalties for 70-student courses
                        if course_info and course_info['students_per_instance'] == 70:
                            practical_hours = course_info['practical_hours']
                            
                            # Strong preference for 70-capacity labs for courses with >2 practical hours
                            if practical_hours > 2:
                                if room_id in labs_by_capacity.get(35, []):
                                    # Heavy penalty for using 35-capacity labs for high practical hour courses
                                    capacity_preference_penalties.extend([assignment_var] * 10)
                                elif room_id in labs_by_capacity.get(70, []):
                                    # Light penalty for 70-capacity labs (preferred)
                                    capacity_preference_penalties.extend([assignment_var] * 1)
                            else:
                                # Light preference for 70-capacity labs for ≤2 practical hour courses
                                if room_id in labs_by_capacity.get(35, []):
                                    # Light penalty for 35-capacity labs
                                    capacity_preference_penalties.extend([assignment_var] * 3)
                                elif room_id in labs_by_capacity.get(70, []):
                                    # Very light penalty for 70-capacity labs
                                    capacity_preference_penalties.extend([assignment_var] * 1)
        
        # Objective: Minimize total usage + capacity preference penalties + shift preference penalties
        model.Minimize(sum(total_lab_usage) + sum(capacity_preference_penalties) + sum(shift_preference_penalties))
        
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
                            
                            # NEW LOGIC: Check if this assignment requires batching based on capacity match
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
                                
                                self.logger.info(f"BATCHING: 70-student course assigned to {room_capacity}-capacity lab -> "
                                               f"Creating batch {batch_number} with {student_count_for_assignment} students")
                            else:
                                # No batching needed - lab capacity can handle full course
                                student_count_for_assignment = min(room_capacity, original_student_count)
                                is_batched = False
                                batch_number = None
                                batch_info = ""
                                display_course_code = course_info.get('display_course_code', course_info['course_code'])
                                
                                self.logger.info(f"NO BATCHING: {original_student_count}-student course fits in {room_capacity}-capacity lab")
                            
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
            
            # Add shift compliance analysis
            if hasattr(self, 'teacher_shift_data') and self.teacher_shift_data and not lab_data.empty:
                f.write(f"\nShift Compliance Analysis:\n")
                shift_compliance_stats = self._analyze_shift_compliance(lab_data)
                
                f.write(f"Total lab assignments: {shift_compliance_stats['total_assignments']}\n")
                f.write(f"Shift-compliant assignments: {shift_compliance_stats['compliant_assignments']}\n")
                f.write(f"Overall shift compliance rate: {shift_compliance_stats['compliance_rate']:.1f}%\n\n")
                
                f.write(f"Compliance by Shift Type:\n")
                for shift, stats in shift_compliance_stats['by_shift'].items():
                    if stats['total'] > 0:
                        f.write(f"  {shift}: {stats['compliant']}/{stats['total']} ({stats['rate']:.1f}%)\n")
                
                # Explain shift definitions
                f.write(f"\nShift Definitions:\n")
                for shift_name, shift_info in self.shift_definitions.items():
                    f.write(f"  {shift_name}: {shift_info['time_range']} -> Lab sessions {', '.join(shift_info['allowed_lab_sessions'])}\n")
                
                # Identify non-compliant assignments
                violations = self._validate_shift_constraints(schedule_df)
                if violations:
                    f.write(f"\nShift Violations Found ({len(violations)}):\n")
                    for violation in violations[:10]:  # Show first 10 violations
                        f.write(f"  - {violation}\n")
                    if len(violations) > 10:
                        f.write(f"  ... and {len(violations) - 10} more violations\n")
                else:
                    f.write(f"\n✅ No shift violations detected!\n")
            elif not hasattr(self, 'teacher_shift_data') or not self.teacher_shift_data:
                f.write(f"\nShift Compliance Analysis: Not available (no shift data loaded)\n")
        
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
        
        # Create relaxed objective function with shift preferences
        total_lab_usage = []
        shift_penalty_terms = []
        
        for course_instance_id in all_course_instances:
            teacher = course_to_teacher[course_instance_id]
            
            for day_idx in range(self.num_days):
                day = self.days[day_idx]
                allowed_sessions = self.get_teacher_allowed_lab_sessions(teacher, day)
                
                for session_idx in range(len(lab_sessions)):
                    session_name = lab_sessions[session_idx]
                    
                    for room_id in lab_room_ids:
                        assignment_var = lab_assignments[course_instance_id][day_idx][session_idx][room_id]
                        total_lab_usage.append(assignment_var)
                        
                        # Add shift penalty (lighter than full constraints)
                        if session_name not in allowed_sessions:
                            shift_penalty_terms.extend([assignment_var] * 50)  # Lighter penalty than full constraint
        
        # Include any penalty variables created by relaxed constraints
        additional_penalties = []
        if hasattr(self, 'shift_penalty_vars'):
            additional_penalties.extend(self.shift_penalty_vars)
        
        # Relaxed objective: minimize usage + shift penalties
        objective_terms = total_lab_usage + shift_penalty_terms + additional_penalties
        model.Minimize(sum(objective_terms))
        
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
            
            # Validate shift constraints
            shift_violations = self._validate_shift_constraints(schedule_df)
            violations.extend(shift_violations)
            
            # Validate macroblock constraints
            macroblock_violations = self._validate_macroblock_constraints(schedule_df)
            violations.extend(macroblock_violations)
            
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
                
                # Separate shift violation reporting
                if shift_violations:
                    f.write(f"\nShift Constraint Violations ({len(shift_violations)}):\n")
                    for violation in shift_violations:
                        f.write(f"  - {violation}\n")
                else:
                    f.write(f"\n✅ All shift constraints satisfied!\n")
                
                # Separate macroblock violation reporting
                if macroblock_violations:
                    f.write(f"\nMacroblock Constraint Violations ({len(macroblock_violations)}):\n")
                    for violation in macroblock_violations:
                        f.write(f"  - {violation}\n")
                else:
                    f.write(f"\n✅ All macroblock constraints satisfied!\n")
                
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
                
                # Add shift compliance summary
                if hasattr(self, 'teacher_shift_data') and self.teacher_shift_data:
                    f.write(f"\nShift Compliance Summary:\n")
                    lab_data = schedule_df[schedule_df['slot_type'] == 'Practical']
                    shift_compliance_stats = self._analyze_shift_compliance(lab_data)
                    
                    f.write(f"Total lab assignments: {shift_compliance_stats['total_assignments']}\n")
                    f.write(f"Shift-compliant assignments: {shift_compliance_stats['compliant_assignments']}\n")
                    f.write(f"Shift compliance rate: {shift_compliance_stats['compliance_rate']:.1f}%\n")
                    
                    for shift, stats in shift_compliance_stats['by_shift'].items():
                        f.write(f"  - {shift}: {stats['compliant']}/{stats['total']} ({stats['rate']:.1f}%)\n")
                
                # Add macroblock compliance summary
                f.write(f"\nMacroblock Compliance Summary:\n")
                macroblock_compliance_stats = self._analyze_macroblock_compliance(schedule_df)
                f.write(f"Total lab assignments: {macroblock_compliance_stats['total_assignments']}\n")
                f.write(f"Macroblock-compliant assignments: {macroblock_compliance_stats['compliant_assignments']}\n")
                f.write(f"Macroblock compliance rate: {macroblock_compliance_stats['compliance_rate']:.1f}%\n")
                f.write(f"Macroblock grouping violations: {macroblock_compliance_stats['grouping_violations']}\n")
                f.write(f"Macroblock grouping compliance rate: {macroblock_compliance_stats['grouping_compliance_rate']:.1f}%\n")
                f.write(f"Macroblock constraint rules:\n")
                f.write(f"  - Theory blocks a1-g1 (morning) → Lab sessions L4-L6 (afternoon)\n")
                f.write(f"  - Theory blocks a2-g2 (afternoon) → Lab sessions L1-L3 (morning)\n")
                f.write(f"Macroblock grouping rules:\n")
                f.write(f"  ✓ Courses within same macroblock CAN overlap in lab sessions\n")
                f.write(f"  ✓ Courses from different semesters CAN overlap in lab sessions\n")
                f.write(f"  ❌ Courses from different macroblocks CANNOT overlap in lab sessions\n")
            
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

    def _validate_shift_constraints(self, schedule_df):
        """Validate that lab assignments comply with teacher shift constraints."""
        violations = []
        
        if not hasattr(self, 'teacher_shift_data') or not self.teacher_shift_data:
            return violations
        
        lab_data = schedule_df[schedule_df['slot_type'] == 'Practical']
        
        for _, row in lab_data.iterrows():
            teacher_id = row['teacher_id']
            day = row['day']
            time_interval = row['time_interval']
            
            # Map time interval to lab session
            lab_session = self._map_time_to_lab_session(time_interval)
            
            # Check if this assignment violates shift constraints
            if not self.validate_lab_session_against_shift(teacher_id, day, lab_session):
                course_code = row.get('display_course_code', row.get('course_code', 'Unknown'))
                shift_info = self.teacher_shift_data.get(teacher_id, {}).get(day, {})
                shift = shift_info.get('shift', 'unknown')
                
                violations.append(f"Teacher {teacher_id} assigned to {lab_session} ({time_interval}) on {day} "
                                f"violates {shift} constraint for course {course_code}")
        
        return violations

    def _map_time_to_lab_session(self, time_interval):
        """Map a time interval to the corresponding lab session."""
        # Map based on exact time intervals
        time_to_session_map = {
            '8:00 - 8:50': 'L1',
            '8:50 - 9:40': 'L1',
            '9:50 - 10:40': 'L2', 
            '10:40 - 11:30': 'L2',
            '11:50 - 12:40': 'L3',
            '12:40 - 1:30': 'L3',
            '1:50 - 2:40': 'L4',
            '2:40 - 3:30': 'L4',
            '3:50 - 4:40': 'L5',
            '4:40 - 5:30': 'L5',
            '5:30 - 6:20': 'L6',
            '6:20 - 7:10': 'L6'
        }
        
        return time_to_session_map.get(time_interval, 'L1')  # Default to L1 if not found

    def _analyze_shift_compliance(self, lab_data):
        """Analyze shift compliance statistics."""
        stats = {
            'total_assignments': len(lab_data),
            'compliant_assignments': 0,
            'compliance_rate': 0.0,
            'by_shift': {}
        }
        
        shift_stats = {
            'shift1': {'total': 0, 'compliant': 0, 'rate': 0.0},
            'shift2': {'total': 0, 'compliant': 0, 'rate': 0.0},
            'shift3': {'total': 0, 'compliant': 0, 'rate': 0.0},
            'unknown': {'total': 0, 'compliant': 0, 'rate': 0.0}
        }
        
        for _, row in lab_data.iterrows():
            teacher_id = row['teacher_id']
            day = row['day']
            time_interval = row['time_interval']
            
            lab_session = self._map_time_to_lab_session(time_interval)
            is_compliant = self.validate_lab_session_against_shift(teacher_id, day, lab_session)
            
            # Get teacher's shift for this day
            shift_info = self.teacher_shift_data.get(teacher_id, {}).get(day, {})
            shift = shift_info.get('shift', 'unknown')
            
            if shift not in shift_stats:
                shift = 'unknown'
            
            shift_stats[shift]['total'] += 1
            if is_compliant:
                stats['compliant_assignments'] += 1
                shift_stats[shift]['compliant'] += 1
        
        # Calculate rates
        if stats['total_assignments'] > 0:
            stats['compliance_rate'] = (stats['compliant_assignments'] / stats['total_assignments']) * 100
        
        for shift, data in shift_stats.items():
            if data['total'] > 0:
                data['rate'] = (data['compliant'] / data['total']) * 100
        
        stats['by_shift'] = shift_stats
        return stats

    def _validate_macroblock_constraints(self, schedule_df):
        """Validate that lab assignments comply with macroblock constraints."""
        violations = []
        
        lab_data = schedule_df[schedule_df['slot_type'] == 'Practical']
        
        # Define macroblock to lab session mapping (same as in constraints)
        macroblock_to_lab_sessions = {
            # Morning theory blocks (a1-g1) -> Afternoon lab sessions (L4-L6)
            'a1': ['L4', 'L5', 'L6'], 'b1': ['L4', 'L5', 'L6'], 'c1': ['L4', 'L5', 'L6'],
            'd1': ['L4', 'L5', 'L6'], 'e1': ['L4', 'L5', 'L6'], 'f1': ['L4', 'L5', 'L6'], 'g1': ['L4', 'L5', 'L6'],
            
            # Afternoon theory blocks (a2-g2) -> Morning lab sessions (L1-L3)
            'a2': ['L1', 'L2', 'L3'], 'b2': ['L1', 'L2', 'L3'], 'c2': ['L1', 'L2', 'L3'],
            'd2': ['L1', 'L2', 'L3'], 'e2': ['L1', 'L2', 'L3'], 'f2': ['L1', 'L2', 'L3'], 'g2': ['L1', 'L2', 'L3']
        }
        
        # 1. Validate basic macroblock allocation (time slot constraints)
        for _, row in lab_data.iterrows():
            teacher_id = row['teacher_id']
            day = row['day']
            time_interval = row['time_interval']
            course_code = row.get('display_course_code', row.get('course_code', 'Unknown'))
            
            # Map time interval to lab session
            lab_session = self._map_time_to_lab_session(time_interval)
            
            # Get teacher's theory schedule to determine their macroblocks
            teacher_theory = self.theory_schedule_df[self.theory_schedule_df['teacher_id'] == teacher_id]
            
            if teacher_theory.empty:
                continue  # No theory schedule, no constraint to validate
            
            # Determine teacher's macroblocks from theory schedule
            teacher_macroblocks = set()
            for _, theory_row in teacher_theory.iterrows():
                macroblock = theory_row.get('macroblock', '')
                if macroblock:
                    teacher_macroblocks.add(macroblock.lower())
            
            if not teacher_macroblocks:
                continue  # No macroblocks found, no constraint to validate
            
            # Determine allowed lab sessions based on teacher's macroblocks
            allowed_lab_sessions = set()
            for macroblock in teacher_macroblocks:
                if macroblock in macroblock_to_lab_sessions:
                    allowed_lab_sessions.update(macroblock_to_lab_sessions[macroblock])
            
            # Check if this lab session violates macroblock constraints
            if allowed_lab_sessions and lab_session not in allowed_lab_sessions:
                violations.append(f"Teacher {teacher_id} assigned to lab session {lab_session} ({time_interval}) on {day} "
                                f"violates macroblock constraint for course {course_code} "
                                f"(teacher macroblocks: {teacher_macroblocks}, allowed lab sessions: {allowed_lab_sessions})")
        
        # 2. Validate macroblock grouping constraints (overlap constraints)
        grouping_violations = self._validate_macroblock_grouping_constraints(lab_data, macroblock_to_lab_sessions)
        violations.extend(grouping_violations)
        
        return violations

    def _validate_macroblock_grouping_constraints(self, lab_data, macroblock_to_lab_sessions):
        """Validate that courses from different macroblock groups don't overlap in lab sessions."""
        violations = []
        
        # Group lab assignments by day, session, and room
        lab_slot_usage = {}
        
        for _, row in lab_data.iterrows():
            teacher_id = row['teacher_id']
            day = row['day']
            time_interval = row['time_interval']
            room_id = row['room_id']
            course_code = row.get('display_course_code', row.get('course_code', 'Unknown'))
            
            # Map time interval to lab session
            lab_session = self._map_time_to_lab_session(time_interval)
            
            # Get teacher's macroblocks
            teacher_theory = self.theory_schedule_df[self.theory_schedule_df['teacher_id'] == teacher_id]
            teacher_macroblocks = set()
            
            if not teacher_theory.empty:
                for _, theory_row in teacher_theory.iterrows():
                    macroblock = theory_row.get('macroblock', '')
                    if macroblock:
                        teacher_macroblocks.add(macroblock.lower())
            
            if not teacher_macroblocks:
                continue  # No macroblocks, no grouping constraint
            
            # Create slot key
            slot_key = (day, lab_session, room_id)
            
            if slot_key not in lab_slot_usage:
                lab_slot_usage[slot_key] = []
            
            # Store assignment with macroblock information
            lab_slot_usage[slot_key].append({
                'teacher_id': teacher_id,
                'course_code': course_code,
                'macroblocks': teacher_macroblocks,
                'time_interval': time_interval
            })
        
        # Check for violations: different macroblock groups in same lab slot
        for slot_key, assignments in lab_slot_usage.items():
            if len(assignments) > 1:  # Multiple assignments in same slot
                day, lab_session, room_id = slot_key
                
                # Check if assignments are from different macroblock groups
                macroblocks_in_slot = set()
                for assignment in assignments:
                    macroblocks_in_slot.update(assignment['macroblocks'])
                
                # Check if any two different macroblocks are using the same lab session type
                macroblock_types = set()
                for macroblock in macroblocks_in_slot:
                    if macroblock in macroblock_to_lab_sessions:
                        allowed_sessions = macroblock_to_lab_sessions[macroblock]
                        if lab_session in allowed_sessions:
                            macroblock_types.add(macroblock)
                
                if len(macroblock_types) > 1:
                    # Violation: different macroblock groups are sharing the same lab slot
                    course_details = []
                    for assignment in assignments:
                        course_details.append(f"{assignment['course_code']} (Teacher {assignment['teacher_id']}, macroblocks: {assignment['macroblocks']})")
                    
                    violations.append(f"Macroblock grouping violation in {lab_session} on {day} in room {room_id}: "
                                    f"Different macroblock groups sharing same lab slot - {'; '.join(course_details)}")
        
        return violations

    def _analyze_macroblock_compliance(self, schedule_df):
        """Analyze macroblock compliance statistics."""
        stats = {
            'total_assignments': 0,
            'compliant_assignments': 0,
            'compliance_rate': 0.0,
            'grouping_violations': 0,
            'grouping_compliance_rate': 0.0,
            'by_macroblock_type': {
                'morning_theory': {'total': 0, 'compliant': 0, 'rate': 0.0},
                'afternoon_theory': {'total': 0, 'compliant': 0, 'rate': 0.0},
                'no_theory': {'total': 0, 'compliant': 0, 'rate': 0.0}
            }
        }
        
        lab_data = schedule_df[schedule_df['slot_type'] == 'Practical']
        stats['total_assignments'] = len(lab_data)
        
        if stats['total_assignments'] == 0:
            return stats
        
        # Define macroblock to lab session mapping
        macroblock_to_lab_sessions = {
            'a1': ['L4', 'L5', 'L6'], 'b1': ['L4', 'L5', 'L6'], 'c1': ['L4', 'L5', 'L6'],
            'd1': ['L4', 'L5', 'L6'], 'e1': ['L4', 'L5', 'L6'], 'f1': ['L4', 'L5', 'L6'], 'g1': ['L4', 'L5', 'L6'],
            'a2': ['L1', 'L2', 'L3'], 'b2': ['L1', 'L2', 'L3'], 'c2': ['L1', 'L2', 'L3'],
            'd2': ['L1', 'L2', 'L3'], 'e2': ['L1', 'L2', 'L3'], 'f2': ['L1', 'L2', 'L3'], 'g2': ['L1', 'L2', 'L3']
        }
        
        # 1. Analyze basic macroblock compliance (time slot constraints)
        for _, row in lab_data.iterrows():
            teacher_id = row['teacher_id']
            time_interval = row['time_interval']
            
            # Map time interval to lab session
            lab_session = self._map_time_to_lab_session(time_interval)
            
            # Get teacher's theory schedule to determine their macroblocks
            teacher_theory = self.theory_schedule_df[self.theory_schedule_df['teacher_id'] == teacher_id]
            
            if teacher_theory.empty:
                # No theory schedule - count as compliant (no constraint to violate)
                stats['compliant_assignments'] += 1
                stats['by_macroblock_type']['no_theory']['total'] += 1
                stats['by_macroblock_type']['no_theory']['compliant'] += 1
                continue
            
            # Determine teacher's macroblocks from theory schedule
            teacher_macroblocks = set()
            for _, theory_row in teacher_theory.iterrows():
                macroblock = theory_row.get('macroblock', '')
                if macroblock:
                    teacher_macroblocks.add(macroblock.lower())
            
            if not teacher_macroblocks:
                # No macroblocks found - count as compliant
                stats['compliant_assignments'] += 1
                stats['by_macroblock_type']['no_theory']['total'] += 1
                stats['by_macroblock_type']['no_theory']['compliant'] += 1
                continue
            
            # Determine macroblock type and allowed lab sessions
            allowed_lab_sessions = set()
            macroblock_type = 'no_theory'
            
            for macroblock in teacher_macroblocks:
                if macroblock in macroblock_to_lab_sessions:
                    allowed_lab_sessions.update(macroblock_to_lab_sessions[macroblock])
                    if macroblock.endswith('1'):
                        macroblock_type = 'morning_theory'
                    elif macroblock.endswith('2'):
                        macroblock_type = 'afternoon_theory'
            
            # Check compliance
            is_compliant = not allowed_lab_sessions or lab_session in allowed_lab_sessions
            
            if is_compliant:
                stats['compliant_assignments'] += 1
                stats['by_macroblock_type'][macroblock_type]['compliant'] += 1
            
            stats['by_macroblock_type'][macroblock_type]['total'] += 1
        
        # 2. Analyze macroblock grouping compliance
        grouping_violations = self._validate_macroblock_grouping_constraints(lab_data, macroblock_to_lab_sessions)
        stats['grouping_violations'] = len(grouping_violations)
        
        # Calculate rates
        if stats['total_assignments'] > 0:
            stats['compliance_rate'] = (stats['compliant_assignments'] / stats['total_assignments']) * 100
            
            # Calculate grouping compliance rate
            total_possible_conflicts = stats['total_assignments']  # Simplified calculation
            if total_possible_conflicts > 0:
                stats['grouping_compliance_rate'] = ((total_possible_conflicts - stats['grouping_violations']) / total_possible_conflicts) * 100
        
        for macroblock_type, data in stats['by_macroblock_type'].items():
            if data['total'] > 0:
                data['rate'] = (data['compliant'] / data['total']) * 100
        
        return stats

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
        print("• Macroblock-based allocation: a1-g1 theory → L4-L6 labs, a2-g2 theory → L1-L3 labs")
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
            print("  ✓ Macroblock-based allocation prevents theory-lab conflicts")
            print("    - Teachers with a1-g1 theory blocks → L4-L6 lab sessions only")
            print("    - Teachers with a2-g2 theory blocks → L1-L3 lab sessions only")
        else:
            print("❌ Failed to generate a feasible lab schedule.")
            print("💡 Try adjusting course requirements or increasing available lab rooms.")
    except Exception as e:
        print(f"❌ Error in lab schedule generation: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main() 