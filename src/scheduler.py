import os
import pandas as pd
import numpy as np
import logging
import json
from datetime import datetime
from ortools.sat.python import cp_model
from src.constraints import MacroblockTimetableConstraints
from src.utils.macroblock_visualizer import MacroblockTimetableVisualizer
from src.utils.room_verifier import RoomVerifier
from src.utils.room_visualizer import RoomVisualizer
from src.utils.shift_verifier import ShiftVerifier

class MacroblockTimetableScheduler:
    def __init__(self, course_file, room_file):
        """Initialize the macroblock timetable scheduler with course and room data."""
        self.logger = logging.getLogger(__name__)
        
        # Load the data
        self.courses_df = pd.read_csv(course_file)
        self.rooms_df = pd.read_csv(room_file)
        
        # Setup time slots from update.txt structure
        self.days = ["tuesday", "wed", "thur", "fri", "sat"]  # Excluding Monday
        self.num_days = len(self.days)
        
        # Time slots (11 slots per day - Theory timing with proper breaks)
        # Covers 8:00-19:00 as requested (11 slots: 8:00-8:50 to 6:00-6:50 PM)
        self.time_slots = [
            "8:00 - 8:50", "9:00 - 9:50", "10:00 - 10:50", "11:00 - 11:50",
            "12:00 - 12:50", "1:00 - 1:50", "2:00 - 2:50", "3:00 - 3:50", 
            "4:00 - 4:50", "5:00 - 5:50", "6:00 - 6:50"
        ]
        self.num_slots = len(self.time_slots)
        
        # Macroblock structure from new format - 11 slots per day, Tuesday to Saturday
        self.daily_schedule_structure = {
            "tuesday": ["a1/L1", "f1/L2", "d1/L3", "tb1/L4", "tg1/L5", "L6", 
                       "a2/L31", "f2/L32", "d2/L33", "tb2/L34", "tg2/L35"],
            "wed": ["b1/L7", "g1/L8", "e1/L9", "tc1/L10", "taa1/L11", "L12", 
                   "b2/L37", "g2/L38", "e2/L39", "tc2/L40", "taa2/L41"],
            "thur": ["c1/L13", "a1/L14", "f1/L15", "td1/L16", "v2/L17", "L18", 
                    "c2/L43", "a2/L44", "f2/L45", "td2/L46", "tbb2/L47"],
            "fri": ["d1/L19", "b1/L20", "g1/L21", "te1/L22", "tcc1/L23", "L24", 
                   "d2/L49", "b2/L50", "g2/L51", "te2/L52", "tcc2/L53"],
            "sat": ["e1/L25", "c1/L26", "ta1/L27", "tf1/L28", "tdd1/L29", "L30", 
                   "e2/L55", "c2/L56", "ta2/L57", "tf2/L58", "tdd2/L59"]
        }
        
        # Process rooms - separate classrooms and labs
        self.classrooms = self.rooms_df[self.rooms_df['is_lab'] == 0]
        self.labs = self.rooms_df[self.rooms_df['is_lab'] == 1]
        
        # Process teacher-course assignments
        self.process_teacher_courses()
        
        # Create output directory
        self.output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
                                      'output', 
                                      f'macroblock_schedule_{datetime.now().strftime("%Y%m%d_%H%M%S")}')
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
                'academic_year': row.get('academic_year', 3),  # Default to 3 if not present
                'semester': row.get('semester', 5),  # Default to 5 if not present
                'course_dept': row.get('course_dept', 'Computer Science & Engineering')  # Default dept
            })
    
    def generate_timetable(self):
        """Generate the timetable using OR-Tools CP-SAT solver with macroblock structure."""
        self.logger.info("Starting macroblock timetable generation...")
        
        # Create the CP-SAT model
        model = cp_model.CpModel()
        
        # Pre-compute room IDs for efficiency
        classroom_ids = self.classrooms['id'].tolist()
        # Skip lab IDs as we're not allocating labs for now
        
        # Define assignment variables
        # teacher_theory_assignments[t][d][s][r] = 1 if teacher t is assigned to classroom r in slot s on day d
        teacher_theory_assignments = {}
        for teacher in self.teachers:
            teacher_theory_assignments[teacher] = {}
            for d in range(self.num_days):
                teacher_theory_assignments[teacher][d] = {}
                for s in range(self.num_slots):
                    teacher_theory_assignments[teacher][d][s] = {}
                    for room_id in classroom_ids:
                        teacher_theory_assignments[teacher][d][s][room_id] = model.NewBoolVar(
                            f'teacher_{teacher}_day_{d}_slot_{s}_classroom_{room_id}')
        
        # Skip lab assignments as requested
        # teacher_lab_assignments = None  # Not needed for now
        
        # Initialize constraints handler
        constraints = MacroblockTimetableConstraints(
            model, 
            self.teachers, 
            self.teacher_course_assignments,
            self.classrooms, 
            self.labs
        )
        
        # Apply all constraints (skip lab assignments)
        constraints.apply_all_constraints(teacher_theory_assignments, None)
        
        # Create the solver and solve the model
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 600  # 5 minutes time limit
        solver.parameters.max_memory_in_mb = 30000  # 16GB memory limit
        solver.parameters.log_search_progress = True
        solver.parameters.num_search_workers = 12  # 8 threads for parallel search
        
        self.logger.info("Solving the macroblock model...")
        status = solver.Solve(model)
        
        if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
            self.logger.info(f"Solution found with status {status}!")
            
            # First extract base macroblock assignments from CP-SAT solution
            base_assignments = self.extract_base_macroblock_assignments(solver, constraints)
            
            # Post-process to create detailed lecture/tutorial schedule
            schedule_result = self.post_process_detailed_schedule(base_assignments, constraints)
            
            # Save schedule results
            self.save_schedule_results(schedule_result)
            
            # Generate visualizations
            self.generate_visualizations(schedule_result)
            
            # Verify room distribution and check for overlaps using dedicated module
            room_verifier = RoomVerifier(self.logger)
            verification_result = room_verifier.verify_room_distribution_and_overlaps(schedule_result)
            
            # Generate room-specific visualizations
            room_visualizer = RoomVisualizer(schedule_result['schedule_data'], self.output_dir, self.logger)
            room_visualizer.generate_all_room_visualizations()
            
            # Generate detailed room verification report
            verification_report_path = os.path.join(self.output_dir, 'room_verification_report.txt')
            room_verifier.generate_room_verification_report(schedule_result, verification_report_path)
            
            # COMMENTED OUT: Now determine teacher shifts based on actual slot assignments
            # schedule_data = self._finalize_teacher_shifts(schedule_data)
            self.logger.info("Teacher shift finalization DISABLED - focusing on course grouping")
            
            return True
        else:
            self.logger.warning(f"No solution found. Status: {status}")
            return False
    
    def extract_base_macroblock_assignments(self, solver, constraints):
        """Extract base macroblock assignments from CP-SAT solution (SIMPLIFIED APPROACH)."""
        self.logger.info("Extracting base macroblock assignments from CP-SAT solution...")
        
        base_assignments = {}
        
        # Extract which base macroblock each course instance is assigned to
        for teacher in self.teachers:
            if teacher in constraints.macroblock_assignments:
                base_assignments[teacher] = {}
                
                for instance_id, macroblock_vars in constraints.macroblock_assignments[teacher].items():
                    for block_var_name, block_var in macroblock_vars.items():
                        if block_var_name.endswith('_chosen') and solver.Value(block_var) == 1:
                            base_block = block_var_name.replace('_chosen', '')
                            base_assignments[teacher][instance_id] = {
                                'base_macroblock': base_block,
                                'instance_data': constraints.course_instance_mappings[instance_id]
                            }
                            self.logger.info(f"Instance {instance_id} (Teacher {teacher}) -> {base_block}")
                            break
        
        return base_assignments
    
    def post_process_detailed_schedule(self, base_assignments, constraints):
        """Post-process base assignments to create detailed lecture/tutorial schedule."""
        self.logger.info("Post-processing base assignments into detailed schedule...")
        
        schedule_data = []
        
        # Pre-compute teacher and room information (same as before)
        teacher_info_cache = {}
        for teacher in self.teachers:
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
                    'first_name': '',
                    'last_name': '',
                    'staff_code': ''
                }
        
        classroom_info = {}
        for _, room_row in self.classrooms.iterrows():
            room_id = room_row['id']
            classroom_info[room_id] = {
                'room_number': room_row['room_number'],
                'block': room_row.get('block', ''),
                'description': room_row.get('description', ''),
                'capacity': room_row.get('room_max_cap', 0)
            }
        
        # Map base assignments to specific time slots using the 6-case logic
        
        for teacher, teacher_assignments in base_assignments.items():
            for instance_id, assignment_info in teacher_assignments.items():
                base_block = assignment_info['base_macroblock']
                instance_data = assignment_info['instance_data']['instance']
                
                lecture_hours = instance_data['lecture_hours']
                tutorial_hours = instance_data['tutorial_hours']
                
                # Apply the 6-case logic to determine specific slot allocations
                slot_assignments = self._apply_case_logic(
                    base_block, lecture_hours, tutorial_hours, instance_data, teacher)
                
                # Convert slot assignments to schedule entries
                for slot_assignment in slot_assignments:
                    # FIXED: Proper room assignment with conflict checking
                    room_id = self._assign_room_with_constraints(
                        slot_assignment['day'], 
                        slot_assignment['slot_index'], 
                        teacher, 
                        classroom_info,
                        schedule_data
                    )
                    
                    if room_id is None:
                        self.logger.warning(f"Could not assign room for {teacher} on {slot_assignment['day']} slot {slot_assignment['slot_index']}")
                        continue
                    
                    teacher_info = teacher_info_cache[teacher]
                    room_details = classroom_info[room_id]
                    
                    schedule_data.append({
                        'day': slot_assignment['day'],
                        'slot_index': slot_assignment['slot_index'],
                        'time_interval': slot_assignment['time_interval'],
                        'slot_type': slot_assignment['slot_type'],
                        'macroblock': slot_assignment['macroblock'],
                        'teacher_id': teacher,
                        'first_name': teacher_info['first_name'],
                        'last_name': teacher_info['last_name'],
                        'staff_code': teacher_info['staff_code'],
                        'room_id': room_id,
                        'room_number': room_details['room_number'],
                        'block': room_details['block'],
                        'room_type': 'Classroom',
                        'capacity': room_details['capacity'],
                        'course_id': instance_data['course_id'],
                        'course_code': instance_data['course_code'],
                        'course_name': instance_data['course_name'],
                        'course_instance_id': instance_id,
                        'student_count': instance_data['student_count'],
                        'academic_year': instance_data.get('academic_year', ''),
                        'semester': instance_data.get('semester', ''),
                        'course_dept': instance_data.get('course_dept', ''),
                        'teacher_shift': 'disabled',  # DISABLED - focusing on course grouping
                        'daily_shift_pattern': 'disabled'  # DISABLED - focusing on course grouping
                    })
        
        # COMMENTED OUT: Now determine teacher shifts based on actual slot assignments
        # schedule_data = self._finalize_teacher_shifts(schedule_data)
        self.logger.info("Teacher shift finalization DISABLED - focusing on course grouping")
        
        return {
            'schedule_data': schedule_data,
            'daily_schedules': self._create_daily_schedule_structure(schedule_data),
            'time_slot_definitions': {
                'T': self.time_slots,
            },
            # 'shift_verification': verification_result  # COMMENTED OUT
        }
    
    def _apply_case_logic(self, base_block, lecture_hours, tutorial_hours, instance_data, teacher):
        """Apply the 6-case logic to determine specific slot allocations."""
        slot_assignments = []
        
        # Find all slots for this base block across the week
        base_slots = []
        tutorial_slots = []
        extended_tutorial_slots = []
        
        block_letter = base_block[0]  # 'a', 'b', 'c', etc.
        block_number = base_block[1]  # '1' or '2'
        
        for day_idx, day in enumerate(self.days):
            day_schedule = self.daily_schedule_structure[day]
            for slot_idx, slot_content in enumerate(day_schedule):
                theory_blocks = []
                parts = slot_content.split('/')
                for part in parts:
                    if part in ['a1', 'a2', 'b1', 'b2', 'c1', 'c2', 'd1', 'd2', 'e1', 'e2', 'f1', 'f2', 'g1', 'g2',
                               'ta1', 'ta2', 'tb1', 'tb2', 'tc1', 'tc2', 'td1', 'td2', 'te1', 'te2', 'tf1', 'tf2', 'tg1', 'tg2',
                               'taa1', 'taa2', 'tbb1', 'tbb2', 'tcc1', 'tcc2']:
                        # Exclude v1 and v2 as they are not assigned to any courses
                        theory_blocks.append(part)
                
                # Collect slots for base block
                if base_block in theory_blocks:
                    base_slots.append({
                        'day': day, 'day_idx': day_idx, 'slot_idx': slot_idx,
                        'time_interval': self.time_slots[slot_idx]
                    })
                
                # Collect tutorial slots
                tutorial_block = f't{block_letter}{block_number}'
                if tutorial_block in theory_blocks:
                    tutorial_slots.append({
                        'day': day, 'day_idx': day_idx, 'slot_idx': slot_idx,
                        'time_interval': self.time_slots[slot_idx], 'block': tutorial_block
                    })
                
                # Collect extended tutorial slots
                extended_tutorial_block = f't{block_letter}{block_letter}{block_number}'
                if extended_tutorial_block in theory_blocks:
                    extended_tutorial_slots.append({
                        'day': day, 'day_idx': day_idx, 'slot_idx': slot_idx,
                        'time_interval': self.time_slots[slot_idx], 'block': extended_tutorial_block
                    })
        
        # Apply case-specific logic
        self.logger.info(f"Applying case logic: {lecture_hours}L+{tutorial_hours}T for instance {instance_data['id']}")
        
        if lecture_hours == 3 and tutorial_hours == 0:
            # Case 1: 3L+0T → a1 + a1 + ta1 (ta1 as 3rd lecture)
            for i, slot in enumerate(base_slots[:2]):  # Take first 2 base slots as lectures
                slot_assignments.append({
                    'day': slot['day'], 'slot_index': slot['slot_idx'],
                    'time_interval': slot['time_interval'],
                    'slot_type': 'Lecture', 'macroblock': base_block
                })
            
            for slot in tutorial_slots[:1]:  # Take first tutorial slot as 3rd lecture
                slot_assignments.append({
                    'day': slot['day'], 'slot_index': slot['slot_idx'],
                    'time_interval': slot['time_interval'],
                    'slot_type': 'Lecture', 'macroblock': slot['block']
                })
            
        elif lecture_hours == 3 and tutorial_hours == 1:
            # Case 2: 3L+1T → a1 + a1 + ta1 + taa1 (ta1 as 3rd lecture, taa1 as tutorial)
            for i, slot in enumerate(base_slots[:2]):  # Take first 2 base slots as lectures
                slot_assignments.append({
                    'day': slot['day'], 'slot_index': slot['slot_idx'],
                    'time_interval': slot['time_interval'],
                    'slot_type': 'Lecture', 'macroblock': base_block
                })
            
            for slot in tutorial_slots[:1]:  # Take first tutorial slot as 3rd lecture
                slot_assignments.append({
                    'day': slot['day'], 'slot_index': slot['slot_idx'],
                    'time_interval': slot['time_interval'],
                    'slot_type': 'Lecture', 'macroblock': slot['block']
                })
            
            for slot in extended_tutorial_slots[:1]:  # Take first extended tutorial as tutorial
                slot_assignments.append({
                    'day': slot['day'], 'slot_index': slot['slot_idx'],
                    'time_interval': slot['time_interval'],
                    'slot_type': 'Tutorial', 'macroblock': slot['block']
                })
        
        elif lecture_hours == 2 and tutorial_hours == 1:
            # Case 3: 2L+1T → a1 + a1 + ta1 (ta1 as tutorial)
            for i, slot in enumerate(base_slots[:2]):  # Take first 2 base slots as lectures
                slot_assignments.append({
                    'day': slot['day'], 'slot_index': slot['slot_idx'],
                    'time_interval': slot['time_interval'],
                    'slot_type': 'Lecture', 'macroblock': base_block
                })
            
            for slot in tutorial_slots[:1]:  # Take first tutorial slot as tutorial
                slot_assignments.append({
                    'day': slot['day'], 'slot_index': slot['slot_idx'],
                    'time_interval': slot['time_interval'],
                    'slot_type': 'Tutorial', 'macroblock': slot['block']
                })
        
        elif lecture_hours == 1 and tutorial_hours == 1:
            # Case 4: 1L+1T → a1 + ta1 (ta1 as tutorial)
            for slot in base_slots[:1]:  # Take first base slot as lecture
                slot_assignments.append({
                    'day': slot['day'], 'slot_index': slot['slot_idx'],
                    'time_interval': slot['time_interval'],
                    'slot_type': 'Lecture', 'macroblock': base_block
                })
            
            for slot in tutorial_slots[:1]:  # Take first tutorial slot as tutorial
                slot_assignments.append({
                    'day': slot['day'], 'slot_index': slot['slot_idx'],
                    'time_interval': slot['time_interval'],
                    'slot_type': 'Tutorial', 'macroblock': slot['block']
                })
        
        elif lecture_hours == 2 and tutorial_hours == 0:
            # Case 5: 2L+0T → a1 + a1 (2 lectures only)
            for i, slot in enumerate(base_slots[:2]):  # Take first 2 base slots as lectures
                slot_assignments.append({
                    'day': slot['day'], 'slot_index': slot['slot_idx'],
                    'time_interval': slot['time_interval'],
                    'slot_type': 'Lecture', 'macroblock': base_block
                })
        
        elif lecture_hours == 1 and tutorial_hours == 0:
            # Case 6: 1L+0T → a1 (1 lecture only)
            for slot in base_slots[:1]:  # Take first base slot as lecture
                slot_assignments.append({
                    'day': slot['day'], 'slot_index': slot['slot_idx'],
                    'time_interval': slot['time_interval'],
                    'slot_type': 'Lecture', 'macroblock': base_block
                })
        
        elif lecture_hours == 4 and tutorial_hours >= 1:
            # Case 7: 4L+1T or 4L+2T → Use multiple blocks if needed
            # Allocate 4 lecture hours from base blocks and tutorial blocks
            lecture_slots_used = 0
            for i, slot in enumerate(base_slots[:2]):  # Use base slots first
                slot_assignments.append({
                    'day': slot['day'], 'slot_index': slot['slot_idx'],
                    'time_interval': slot['time_interval'],
                    'slot_type': 'Lecture', 'macroblock': base_block
                })
                lecture_slots_used += 1
            
            # Use tutorial slots for additional lectures if needed
            for slot in tutorial_slots[:lecture_hours - lecture_slots_used]:
                slot_assignments.append({
                    'day': slot['day'], 'slot_index': slot['slot_idx'],
                    'time_interval': slot['time_interval'],
                    'slot_type': 'Lecture', 'macroblock': slot['block']
                })
                lecture_slots_used += 1
            
            # Assign actual tutorial hours
            remaining_tutorial_slots = tutorial_slots[lecture_hours - 2:] + extended_tutorial_slots
            for i, slot in enumerate(remaining_tutorial_slots[:tutorial_hours]):
                slot_assignments.append({
                    'day': slot['day'], 'slot_index': slot['slot_idx'],
                    'time_interval': slot['time_interval'],
                    'slot_type': 'Tutorial', 'macroblock': slot['block']
                })
        
        elif lecture_hours == 5 and tutorial_hours >= 1:
            # Case 8: 5L+1T or 5L+2T → Use all available slots
            # This handles courses like EC23511 mentioned in the query
            lecture_slots_used = 0
            
            # Use all base slots for lectures
            for slot in base_slots:
                slot_assignments.append({
                    'day': slot['day'], 'slot_index': slot['slot_idx'],
                    'time_interval': slot['time_interval'],
                    'slot_type': 'Lecture', 'macroblock': base_block
                })
                lecture_slots_used += 1
            
            # Use tutorial slots for additional lectures
            tutorial_slots_for_lectures = lecture_hours - lecture_slots_used
            for slot in tutorial_slots[:tutorial_slots_for_lectures]:
                slot_assignments.append({
                    'day': slot['day'], 'slot_index': slot['slot_idx'],
                    'time_interval': slot['time_interval'],
                    'slot_type': 'Lecture', 'macroblock': slot['block']
                })
                lecture_slots_used += 1
            
            # Assign actual tutorial hours using remaining tutorial and extended tutorial slots
            remaining_tutorial_slots = tutorial_slots[tutorial_slots_for_lectures:] + extended_tutorial_slots
            for i, slot in enumerate(remaining_tutorial_slots[:tutorial_hours]):
                slot_assignments.append({
                    'day': slot['day'], 'slot_index': slot['slot_idx'],
                    'time_interval': slot['time_interval'],
                    'slot_type': 'Tutorial', 'macroblock': slot['block']
                })
                
            self.logger.info(f"Allocated {lecture_hours} lectures and {tutorial_hours} tutorials for 5L+{tutorial_hours}T course")
        
        elif lecture_hours == 2 and tutorial_hours == 2:
            # Case 9: 2L+2T → a1 + a1 + ta1 + taa1 (ta1 as tutorial, taa1 as tutorial)
            for i, slot in enumerate(base_slots[:2]):  # Take first 2 base slots as lectures
                slot_assignments.append({
                    'day': slot['day'], 'slot_index': slot['slot_idx'],
                    'time_interval': slot['time_interval'],
                    'slot_type': 'Lecture', 'macroblock': base_block
                })
            
            for slot in tutorial_slots[:1]:  # Take first tutorial slot as tutorial
                slot_assignments.append({
                    'day': slot['day'], 'slot_index': slot['slot_idx'],
                    'time_interval': slot['time_interval'],
                    'slot_type': 'Tutorial', 'macroblock': slot['block']
                })
            
            for slot in extended_tutorial_slots[:1]:  # Take first extended tutorial as tutorial
                slot_assignments.append({
                    'day': slot['day'], 'slot_index': slot['slot_idx'],
                    'time_interval': slot['time_interval'],
                    'slot_type': 'Tutorial', 'macroblock': slot['block']
                })
        
        else:
            # General case - allocate flexibly for any other combinations
            for i, slot in enumerate(base_slots[:lecture_hours]):
                slot_assignments.append({
                    'day': slot['day'], 'slot_index': slot['slot_idx'],
                    'time_interval': slot['time_interval'],
                    'slot_type': 'Lecture', 'macroblock': base_block
                })
            
            for i, slot in enumerate(tutorial_slots[:tutorial_hours]):
                slot_assignments.append({
                    'day': slot['day'], 'slot_index': slot['slot_idx'],
                    'time_interval': slot['time_interval'],
                    'slot_type': 'Tutorial', 'macroblock': slot['block']
                })
            
            self.logger.info(f"General case: Allocated {len(base_slots[:lecture_hours])} lectures and {len(tutorial_slots[:tutorial_hours])} tutorials")
        
        self.logger.info(f"Case result: {len(slot_assignments)} slot assignments for instance {instance_data['id']}")
        return slot_assignments
    
    def process_solution(self, solver, teacher_theory_assignments, teacher_lab_assignments, constraints):
        """Process the solution and extract the schedule. Skip lab processing."""
        schedule_data = []
        
        # Pre-compute teacher information cache
        teacher_info_cache = {}
        for teacher in self.teachers:
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
                    'first_name': '',
                    'last_name': '',
                    'staff_code': ''
                }
        
        # Pre-compute room information
        classroom_info = {}
        for _, room_row in self.classrooms.iterrows():
            room_id = room_row['id']
            classroom_info[room_id] = {
                'room_number': room_row['room_number'],
                'block': room_row.get('block', ''),
                'description': room_row.get('description', ''),
                'capacity': room_row.get('room_max_cap', 0)
            }
        
        # Skip lab info as we're not processing labs
        
        # Process theory assignments only
        for teacher in self.teachers:
            for day_idx, day in enumerate(self.days):
                for slot_idx in range(self.num_slots):
                    # Check theory assignments
                    for room_id in classroom_info.keys():
                        if solver.Value(teacher_theory_assignments[teacher][day_idx][slot_idx][room_id]) == 1:
                            # Determine which course instance and macroblock this represents
                            course_info = self._determine_assigned_course(
                                teacher, day_idx, slot_idx, constraints, solver, 'theory')
                            
                            if course_info:
                                    teacher_info = teacher_info_cache[teacher]
                                    room_details = classroom_info[room_id]
                                    
                                    schedule_data.append({
                                    'day': day,
                                    'slot_index': slot_idx,
                                    'time_interval': self.time_slots[slot_idx],
                                    'slot_type': course_info['slot_type'],  # 'Lecture' or 'Tutorial'
                                    'macroblock': course_info['macroblock'],
                                        'teacher_id': teacher,
                                        'first_name': teacher_info['first_name'],
                                        'last_name': teacher_info['last_name'],
                                        'staff_code': teacher_info['staff_code'],
                                        'room_id': room_id,
                                        'room_number': room_details['room_number'],
                                        'block': room_details['block'],
                                    'room_type': 'Classroom',
                                    'capacity': room_details['capacity'],
                                        'course_id': course_info['course_id'],
                                        'course_code': course_info['course_code'],
                                        'course_name': course_info['course_name'],
                                    'course_instance_id': course_info['instance_id'],
                                    'student_count': course_info['student_count'],
                                    'academic_year': course_info.get('academic_year', ''),
                                    'semester': course_info.get('semester', ''),
                                    'course_dept': course_info.get('course_dept', ''),
                                    'teacher_shift': 'disabled',  # DISABLED - focusing on course grouping
                                    'daily_shift_pattern': 'disabled'  # DISABLED - focusing on course grouping
                                })
                    
                    # Skip lab assignments processing as requested
        
        return {
            'schedule_data': schedule_data,
            'daily_schedules': self._create_daily_schedule_structure(schedule_data),
            'time_slot_definitions': {
                'T': self.time_slots,  # Theory time slots
                # Skip lab time slots
            }
        }
    
    def _determine_assigned_course(self, teacher, day_idx, slot_idx, constraints, solver, assignment_type):
        """Determine which course instance is assigned to a specific slot."""
        if teacher not in self.teacher_course_assignments:
            return None
        
        # Get the macroblock structure for this day and slot
        day = self.days[day_idx]
        slot_content = self.daily_schedule_structure[day][slot_idx]
        
        # Parse the slot content to identify theory blocks
        parts = slot_content.split('/')
        theory_blocks = []
        for part in parts:
            if part in ['a1', 'a2', 'b1', 'b2', 'c1', 'c2', 
                       'd1', 'd2', 'e1', 'e2', 'f1', 'f2', 
                       'g1', 'g2', 'ta1', 'ta2', 'tb1', 'tb2',
                       'tc1', 'tc2', 'td1', 'td2', 'te1', 'te2',
                       'tf1', 'tf2', 'tg1', 'tg2', 'taa1', 'taa2',
                       'tbb1', 'tbb2', 'tcc1', 'tcc2']:
                # Exclude v1 and v2 as they are not assigned to any courses
                theory_blocks.append(part)
        
        # Check each course instance for this teacher
        for instance in self.teacher_course_assignments[teacher]:
            instance_id = instance['id']
            
            if assignment_type == 'theory':
                # Check macroblock assignments
                if hasattr(constraints, 'macroblock_assignments') and teacher in constraints.macroblock_assignments:
                    if instance_id in constraints.macroblock_assignments[teacher]:
                        macroblock_vars = constraints.macroblock_assignments[teacher][instance_id]
                        
                        for block in theory_blocks:
                            if block in ['a1', 'a2', 'b1', 'b2', 'c1', 'c2', 'd1', 'd2', 'e1', 'e2', 'f1', 'f2', 'g1', 'g2']:
                                if f'{block}_chosen' in macroblock_vars:
                                    if solver.Value(macroblock_vars[f'{block}_chosen']) == 1:
                                        return {
                                            'instance_id': instance_id,
                                            'course_id': instance['course_id'],
                                            'course_code': instance['course_code'],
                                            'course_name': instance['course_name'],
                                            'student_count': instance['student_count'],
                                            'academic_year': instance.get('academic_year', ''),
                                            'semester': instance.get('semester', ''),
                                            'course_dept': instance.get('course_dept', ''),
                                            'macroblock': block,
                                            'slot_type': 'Lecture'
                                        }
                            
                            elif block in ['ta1', 'ta2', 'tb1', 'tb2', 'tc1', 'tc2', 
                                          'td1', 'td2', 'te1', 'te2', 'tf1', 'tf2',
                                          'tg1', 'tg2', 'taa1', 'taa2', 'tbb1', 'tbb2',
                                          'tcc1', 'tcc2']:
                                # Tutorial block - find parent block
                                if block.startswith('taa'):
                                    parent_block = 'a' + block[3:]  # taa1 -> a1, taa2 -> a2
                                elif block.startswith('tbb'):
                                    parent_block = 'b' + block[3:]  # tbb1 -> b1, tbb2 -> b2
                                elif block.startswith('tcc'):
                                    parent_block = 'c' + block[3:]  # tcc1 -> c1, tcc2 -> c2
                                else:
                                    parent_block = block[1:]  # Remove 't' prefix: ta1 -> a1
                                
                                if f'{parent_block}_chosen' in macroblock_vars:
                                    if solver.Value(macroblock_vars[f'{parent_block}_chosen']) == 1:
                                        # Determine slot type based on the specific allocation logic
                                        lecture_hours = instance['lecture_hours']
                                        tutorial_hours = instance['tutorial_hours']
                                        
                                        # Determine if this ta block is used as lecture or tutorial
                                        if block in ['ta1', 'ta2', 'tb1', 'tb2', 'tc1', 'tc2', 'td1', 'td2', 'te1', 'te2', 'tf1', 'tf2', 'tg1', 'tg2']:
                                            # ta1 blocks - usage depends on case
                                            if lecture_hours == 3 and tutorial_hours == 0:
                                                # Case 1: ta1 used as 3rd lecture hour
                                                slot_type = 'Lecture'
                                            elif lecture_hours == 3 and tutorial_hours == 1:
                                                # Case 2: ta1 used as 3rd lecture hour (taa1 will be tutorial)
                                                slot_type = 'Lecture'
                                            elif tutorial_hours > 0:
                                                # Cases 3 & 4: ta1 used as tutorial hour
                                                slot_type = 'Tutorial'
                                            else:
                                                # General case - assume tutorial for ta1 blocks
                                                slot_type = 'Tutorial'
                                        else:
                                            # Extended tutorial blocks (taa1, tbb1, etc.) - always tutorials
                                            slot_type = 'Tutorial'
                                        
                                        return {
                                            'instance_id': instance_id,
                                            'course_id': instance['course_id'],
                                            'course_code': instance['course_code'],
                                            'course_name': instance['course_name'],
                                            'student_count': instance['student_count'],
                                            'academic_year': instance.get('academic_year', ''),
                                            'semester': instance.get('semester', ''),
                                            'course_dept': instance.get('course_dept', ''),
                                            'macroblock': block,
                                            'slot_type': slot_type
                                        }
            
            elif assignment_type == 'lab' and instance['practical_hours'] > 0:
                # For labs, any course with practical hours could be assigned
                return {
                    'instance_id': instance_id,
                    'course_id': instance['course_id'],
                    'course_code': instance['course_code'],
                    'course_name': instance['course_name'],
                    'student_count': instance['student_count'],
                    'macroblock': 'Lab',
                    'slot_type': 'Practical'
                }
        
        return None
    
    def _determine_daily_shift(self, teacher, day_idx, constraints, solver):
        """Determine which shift a teacher is assigned to - simplified since shifts are merged."""
        return 'combined_shift'  # All teachers use combined shift now
    
    def _get_teacher_weekly_shift_pattern(self, teacher, constraints, solver):
        """Get the weekly shift pattern for a teacher - simplified since shifts are merged."""
        return 'Combined->Combined->Combined->Combined->Combined'  # All days use combined shift
    
    def _create_daily_schedule_structure(self, schedule_data):
        """Create the daily schedule structure matching the required format."""
        daily_schedules = {}
        
        for day in self.days:
            daily_schedules[day] = []
            day_data = [item for item in schedule_data if item['day'] == day]
            
            for slot_idx in range(self.num_slots):
                # Get assignments for this slot
                slot_assignments = [item for item in day_data if item['slot_index'] == slot_idx]
                
                # Create content string
                content_parts = []
                
                # Add macroblock assignments
                for assignment in slot_assignments:
                    if assignment['slot_type'] in ['Lecture', 'Tutorial']:
                        content_parts.append(assignment['macroblock'])
                
                # Add lab identifiers from original structure
                original_content = self.daily_schedule_structure[day][slot_idx]
                lab_parts = [part for part in original_content.split('/') if part.startswith('L')]
                content_parts.extend(lab_parts)
                
                # If no assignments, use original content
                if not content_parts:
                    content = original_content
                else:
                    content = '/'.join(content_parts)
                
                daily_schedules[day].append({
                    'content': content,
                    'slot_index': slot_idx,
                    'time_interval': self.time_slots[slot_idx]
                })
        
        return daily_schedules
    
    def save_schedule_results(self, schedule_result):
        """Save the schedule results to files."""
        # Save as CSV
        if schedule_result['schedule_data']:
            schedule_df = pd.DataFrame(schedule_result['schedule_data'])
            
            # Save main schedule
            schedule_csv_path = os.path.join(self.output_dir, 'macroblock_schedule.csv')
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
        
        json_path = os.path.join(self.output_dir, 'macroblock_schedule.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(json_result, f, indent=2, ensure_ascii=False)
        
        self.logger.info(f"JSON schedule saved to {json_path}")
        
        # Generate summary
        self.generate_summary(schedule_result)
    
    def generate_summary(self, schedule_result):
        """Generate a summary of the macroblock schedule."""
        summary_path = os.path.join(self.output_dir, 'macroblock_summary.txt')
        
        schedule_data = schedule_result['schedule_data']
        
        with open(summary_path, 'w', encoding='utf-8') as f:
            f.write("Macroblock Timetable Schedule Summary\n")
            f.write("====================================\n\n")
            
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
            
            # Macroblock distribution
            f.write("Macroblock Distribution:\n")
            macroblock_counts = {}
            for item in schedule_data:
                if item['slot_type'] in ['Lecture', 'Tutorial']:
                    macroblock = item['macroblock']
                    macroblock_counts[macroblock] = macroblock_counts.get(macroblock, 0) + 1
            
            for macroblock, count in sorted(macroblock_counts.items()):
                f.write(f"  {macroblock}: {count} assignments\n")
            
            # Daily shift distribution
            f.write("\nDaily Shift Distribution:\n")
            shift_counts = {}
            for item in schedule_data:
                shift = item.get('teacher_shift', 'Unknown')
                shift_counts[shift] = shift_counts.get(shift, 0) + 1
            
            for shift, count in sorted(shift_counts.items()):
                f.write(f"  {shift}: {count} assignments\n")
            
            # Analyze rotation quality - skip since we use combined shifts now
            self.logger.info("Skipping shift rotation analysis since we use combined shifts")
            
            # Shift rotation patterns
            f.write("\nTeacher Shift Rotation Patterns:\n")
            f.write("  Using combined shift system - no rotation needed\n")
            f.write("  All teachers use unified combined shift\n")
            
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
            
            # Vertical grouping analysis
            f.write("\nVertical Macroblock Grouping Analysis:\n")
            vertical_patterns = {'vertical': 0, 'scattered': 0}
            
            # Analyze macroblock assignment patterns
            dept_blocks = {}
            for item in schedule_data:
                dept = item.get('course_dept', 'Unknown')
                macroblock = item.get('macroblock', 'Unknown')
                if dept not in dept_blocks:
                    dept_blocks[dept] = []
                dept_blocks[dept].append(macroblock)
            
            for dept, blocks in dept_blocks.items():
                # Count vertical vs scattered patterns
                block_letters = [block[0] if len(block) > 0 else '' for block in blocks if block != 'Unknown']
                if len(set(block_letters)) < len(block_letters):  # Some repetition indicates vertical grouping
                    vertical_patterns['vertical'] += 1
                else:
                    vertical_patterns['scattered'] += 1
            
            f.write(f"  Vertical grouping patterns: {vertical_patterns['vertical']}\n")
            f.write(f"  Scattered patterns: {vertical_patterns['scattered']}\n")
            
            f.write(f"\nSchedule generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            f.write(f"\nNew constraints applied:")
            f.write(f"\n  - Vertical Macroblock Grouping: Promotes sequential block assignment")
            f.write(f"\n  - Weekly Working Hour Constraint: 21-hour limit per teacher")
            f.write(f"\n  - Daily Shift Rotation: Teachers work different shifts on different days")
            f.write(f"\n  - Shift Distribution: 33% weekly distribution per department (soft)")
            f.write(f"\n  - Adjacent Shift Transitions: Encourages S1↔S2, S2↔S3 over S1↔S3")
        
        self.logger.info(f"Summary saved to {summary_path}")

    def generate_visualizations(self, schedule_result):
        """Generate schedule visualizations using the macroblock visualizer."""
        try:
            self.logger.info("Generating schedule visualizations...")
            
            # Create visualizer with schedule data
            visualizer = MacroblockTimetableVisualizer(
                schedule_result['schedule_data'], 
                self.output_dir
            )
            
            # Generate all visualizations
            visualizer.generate_all_visualizations()
            
            self.logger.info("Schedule visualizations generated successfully")
            
        except ImportError as e:
            self.logger.warning(f"Could not generate visualizations due to missing dependencies: {e}")
        except Exception as e:
            self.logger.error(f"Error generating visualizations: {e}")
            self.logger.exception("Visualization error details")

    def _assign_room_with_constraints(self, day, slot_index, teacher, classroom_info, schedule_data):
        """
        Simplified room assignment with only time slot conflict checking.
        
        SIMPLIFIED CONSTRAINT: Only prevent room conflicts at the same time slot.
        - A room cannot be used by multiple courses at the same time slot
        - Same room CAN be used by different courses at different time slots
        - No macroblock linking required
        """
        # Get all existing assignments for this specific day and slot
        existing_assignments = [
            item for item in schedule_data 
            if item['day'] == day and item['slot_index'] == slot_index
        ]
        
        # Get rooms already occupied in this specific time slot
        occupied_rooms = {item['room_id'] for item in existing_assignments}
        
        # Find available rooms (not occupied in this specific time slot)
        available_rooms = [
            room_id for room_id in classroom_info.keys() 
            if room_id not in occupied_rooms
        ]
        
        if not available_rooms:
            self.logger.warning(f"No available rooms for {day} slot {slot_index}")
            return None
        
        # Select first available room (simple assignment)
        selected_room = available_rooms[0]
        
        self.logger.debug(f"Assigned room {selected_room} to teacher {teacher} for {day} slot {slot_index}")
        return selected_room
    
    def _determine_daily_shift_from_slots(self, teacher, day, schedule_data):
        """Determine the daily shift for a teacher based on the assigned slots."""
        # Get all slots for this teacher on this specific day
        teacher_slots_on_day = [
            item['slot_index'] for item in schedule_data 
            if item['teacher_id'] == teacher and item['day'] == day
        ]
        
        if not teacher_slots_on_day:
            return 'no_shift'
        
        min_slot = min(teacher_slots_on_day)
        max_slot = max(teacher_slots_on_day)
        
        # Define shift boundaries (same as in constraints.py)
        # Shift 1: slots 0-6 (8:00-3:00)
        # Shift 2: slots 2-8 (10:00-5:00) 
        # Shift 3: slots 4-10 (12:00-7:00)
        
        if min_slot >= 0 and max_slot <= 6:
            return 'shift1'
        elif min_slot >= 2 and max_slot <= 8:
            return 'shift2'
        elif min_slot >= 4 and max_slot <= 10:
            return 'shift3'
        else:
            return 'invalid_shift'  # This should not happen with proper constraints
        
    def _update_teacher_shift_patterns(self, schedule_data):
        """Update the daily shift patterns for all teachers after processing."""
        # Group by teacher
        teacher_daily_shifts = {}
        
        for item in schedule_data:
            teacher_id = item['teacher_id']
            day = item['day']
            teacher_shift = item['teacher_shift']
            
            if teacher_id not in teacher_daily_shifts:
                teacher_daily_shifts[teacher_id] = {}
            
            # Only record one shift per teacher per day
            if day not in teacher_daily_shifts[teacher_id]:
                teacher_daily_shifts[teacher_id][day] = teacher_shift
        
        # Create shift patterns
        teacher_shift_patterns = {}
        for teacher_id, daily_shifts in teacher_daily_shifts.items():
            pattern_parts = []
            for day in self.days:  # tuesday, wed, thur, fri, sat
                shift = daily_shifts.get(day, 'no_shift')
                shift_display = {
                    'shift1': 'S1',
                    'shift2': 'S2', 
                    'shift3': 'S3',
                    'no_shift': '--',
                    'combined_shift': 'CS',
                    'invalid_shift': 'XX'
                }.get(shift, shift)
                pattern_parts.append(shift_display)
            
            teacher_shift_patterns[teacher_id] = '->'.join(pattern_parts)
        
        # Update schedule data with proper shift patterns
        for item in schedule_data:
            teacher_id = item['teacher_id']
            item['daily_shift_pattern'] = teacher_shift_patterns.get(teacher_id, 'Unknown')
        
        return schedule_data
    
    def _finalize_teacher_shifts(self, schedule_data):
        """Determine final teacher shifts based on actual slot assignments."""
        # First pass: determine daily shifts for each teacher
        for item in schedule_data:
            teacher_id = item['teacher_id']
            day = item['day']
            
            # Get all slots for this teacher on this day
            teacher_slots_on_day = [
                x['slot_index'] for x in schedule_data 
                if x['teacher_id'] == teacher_id and x['day'] == day
            ]
            
            if teacher_slots_on_day:
                min_slot = min(teacher_slots_on_day)
                max_slot = max(teacher_slots_on_day)
                
                # Determine shift based on slot range
                if min_slot >= 0 and max_slot <= 6:
                    daily_shift = 'shift1'
                elif min_slot >= 2 and max_slot <= 8:
                    daily_shift = 'shift2'
                elif min_slot >= 4 and max_slot <= 10:
                    daily_shift = 'shift3'
                else:
                    daily_shift = 'invalid_shift'
                
                item['teacher_shift'] = daily_shift
        
        # Second pass: create weekly shift patterns
        schedule_data = self._update_teacher_shift_patterns(schedule_data)
        
        return schedule_data
    
    # NOTE: verify_room_distribution_and_overlaps() function has been moved to 
    # src/utils/room_verifier.py for better modularity and reusability 