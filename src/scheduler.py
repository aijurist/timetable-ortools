import os
import pandas as pd
import numpy as np
import logging
import json
from datetime import datetime
from ortools.sat.python import cp_model
from src.constraints import MacroblockTimetableConstraints
from src.utils.macroblock_visualizer import MacroblockTimetableVisualizer

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
        
        # Time slots (12 slots per day - Theory timing with proper breaks)
        self.time_slots = [
            "8:00 - 8:50", "9:00 - 9:50", "10:00 - 10:50", "11:00 - 11:50",
            "12:00 - 12:50", "1:00 - 1:50", "2:00 - 2:50", "3:00 - 3:50", 
            "4:00 - 4:50", "5:00 - 5:50", "6:00 - 6:50", "7:00 - 7:50"
        ]
        self.num_slots = len(self.time_slots)
        
        # Macroblock structure from update.txt
        self.daily_schedule_structure = {
            "tuesday": ["a1/L1", "f1/L2", "d1/L3", "b1/a2/L4", "g1/f2/L5", "d2/L6", 
                       "b2/a3/L7", "g2/f3/L8", "d3/L9", "b3/L10", "g3/L11", "L12"],
            "wed": ["b1/L12", "g1/L14", "e1/L15", "c1/b2/L24", "ta1/g2/L17", "e1/L18", 
                   "c2/b3/L19", "ta2/g3/L20", "e3/L21", "c3/L22", "ta3/L23", "L24"],
            "thur": ["c1/L25", "a1/L26", "f1/L27", "d1/c2/L28", "tb1/a2/L29", "f2/L30", 
                    "d2/c3/L31", "tb2/a3/L32", "f3/L33", "d3/L34", "tb3/L35", "L36"],
            "fri": ["d1/L37", "b1/L38", "g1/L39", "e1/d2/L40", "tc1/b2/L41", "g2/L42", 
                   "e2/d3/L43", "tc2/b4/L44", "g3/L45", "e3/L46", "tc3/L47", "L46"],
            "sat": ["e1/L49", "c1/L50", "a1/L51", "f1/e2/L52", "td1/c2/L53", "a2/L54", 
                   "f2/e3/L55", "td2/c3/L56", "a3/L57", "f3/L58", "td3/L59", "L60"]
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
        solver.parameters.max_time_in_seconds = 300  # 5 minutes time limit
        
        self.logger.info("Solving the macroblock model...")
        status = solver.Solve(model)
        
        if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
            self.logger.info(f"Solution found with status {status}!")
            
            # Process the solution (skip lab assignments)
            schedule_result = self.process_solution(solver, teacher_theory_assignments, None, constraints)
            
            # Save schedule results
            self.save_schedule_results(schedule_result)
            
            # Generate visualizations
            self.generate_visualizations(schedule_result)
            
            return True
        else:
            self.logger.warning(f"No solution found. Status: {status}")
            return False
    
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
                                    'teacher_shift': self._determine_daily_shift(teacher, day_idx, constraints, solver),
                                    'daily_shift_pattern': self._get_teacher_weekly_shift_pattern(teacher, constraints, solver)
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
            if part in ['a1', 'a2', 'a3', 'b1', 'b2', 'b3', 'c1', 'c2', 'c3', 
                       'd1', 'd2', 'd3', 'e1', 'e2', 'e3', 'f1', 'f2', 'f3', 
                       'g1', 'g2', 'g3', 'ta1', 'ta2', 'ta3', 'tb1', 'tb2', 'tb3',
                       'tc1', 'tc2', 'tc3', 'td1', 'td2', 'td3']:
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
                            if block in ['a1', 'a2', 'a3', 'b1', 'b2', 'b3', 'c1', 'c2', 'c3', 
                                       'd1', 'd2', 'd3', 'e1', 'e2', 'e3', 'f1', 'f2', 'f3', 'g1', 'g2', 'g3']:
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
                            
                            elif block in ['ta1', 'ta2', 'ta3', 'tb1', 'tb2', 'tb3', 'tc1', 'tc2', 'tc3', 'td1', 'td2', 'td3']:
                                # Tutorial block - find parent block
                                parent_block = block[1:]  # Remove 't' prefix
                                if f'{parent_block}_chosen' in macroblock_vars:
                                    if solver.Value(macroblock_vars[f'{parent_block}_chosen']) == 1:
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
                                            'slot_type': 'Tutorial'
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
        """Determine which shift a teacher is assigned to on a specific day."""
        if not hasattr(constraints, 'teacher_daily_shift_vars') or teacher not in constraints.teacher_daily_shift_vars:
            return 'teacher_shift1'  # Default fallback
        
        if day_idx not in constraints.teacher_daily_shift_vars[teacher]:
            return 'teacher_shift1'  # Default fallback
        
        # Check which shift variable is active for this teacher on this day
        for shift_name in ['teacher_shift1', 'teacher_shift2', 'teacher_shift3']:
            if shift_name in constraints.teacher_daily_shift_vars[teacher][day_idx]:
                shift_var = constraints.teacher_daily_shift_vars[teacher][day_idx][shift_name]
                if solver.Value(shift_var) == 1:
                    return shift_name
        
        return 'teacher_shift1'  # Default fallback
    
    def _get_teacher_weekly_shift_pattern(self, teacher, constraints, solver):
        """Get the complete weekly shift pattern for a teacher."""
        if not hasattr(constraints, 'teacher_daily_shift_vars') or teacher not in constraints.teacher_daily_shift_vars:
            return 'Static'  # Fallback for old system
        
        pattern = []
        for day_idx in range(len(self.days)):
            if day_idx in constraints.teacher_daily_shift_vars[teacher]:
                daily_shift = self._determine_daily_shift(teacher, day_idx, constraints, solver)
                # Convert to short form: teacher_shift1 -> S1, teacher_shift2 -> S2, etc.
                short_shift = daily_shift.replace('teacher_shift', 'S')
                pattern.append(short_shift)
            else:
                pattern.append('S1')  # Default
        
        return '→'.join(pattern)  # e.g., "S1→S2→S2→S3→S1"
    
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
            
            # Shift rotation patterns
            f.write("\nTeacher Shift Rotation Patterns:\n")
            shift_patterns = {}
            teacher_patterns = {}
            for item in schedule_data:
                teacher_id = item['teacher_id']
                pattern = item.get('daily_shift_pattern', 'Static')
                teacher_patterns[teacher_id] = pattern
                if pattern not in shift_patterns:
                    shift_patterns[pattern] = 0
                shift_patterns[pattern] += 1
            
            # Count unique patterns
            unique_patterns = len(set(teacher_patterns.values()))
            f.write(f"  Unique shift patterns: {unique_patterns}\n")
            
            # Show most common patterns
            sorted_patterns = sorted(shift_patterns.items(), key=lambda x: x[1], reverse=True)
            f.write("  Most common patterns:\n")
            for pattern, count in sorted_patterns[:5]:  # Top 5 patterns
                if pattern != 'Static':
                    f.write(f"    {pattern}: {count} assignments\n")
            
            # Analyze rotation quality
            adjacent_transitions = 0
            non_adjacent_transitions = 0
            for teacher_id, pattern in teacher_patterns.items():
                if pattern != 'Static' and '→' in pattern:
                    shifts = pattern.split('→')
                    for i in range(len(shifts) - 1):
                        curr_shift = int(shifts[i][1:])  # Extract number from S1, S2, S3
                        next_shift = int(shifts[i + 1][1:])
                        
                        if abs(curr_shift - next_shift) == 1:  # Adjacent transition
                            adjacent_transitions += 1
                        elif abs(curr_shift - next_shift) == 2:  # Non-adjacent transition
                            non_adjacent_transitions += 1
            
            total_transitions = adjacent_transitions + non_adjacent_transitions
            if total_transitions > 0:
                f.write(f"  Adjacent transitions: {adjacent_transitions}/{total_transitions} ({100*adjacent_transitions/total_transitions:.1f}%)\n")
                f.write(f"  Non-adjacent transitions: {non_adjacent_transitions}/{total_transitions} ({100*non_adjacent_transitions/total_transitions:.1f}%)\n")
            
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