import os
import pandas as pd
import numpy as np
from ortools.sat.python import cp_model
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from matplotlib.patches import Patch
import seaborn as sns
import random
from datetime import datetime
import json
import logging
import multiprocessing
from functools import partial
import math # Added for math.ceil
import re

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("scheduler.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Constants
NUM_DAYS = 5  # Monday to Friday
NUM_PERIODS = 10  # 10 periods per day as per the constraints
TIME_SLOTS = NUM_DAYS * NUM_PERIODS

# Shifts based on constraint #13
SHIFTS = {
    'shift1': list(range(0, 8)),  # 8:00-15:50
    'shift2': list(range(2, 10)),  # 10:00-17:50
    'shift3': list(range(4, 10)),  # 12:00-19:50
}

TARGET_SHIFT_DAYS = { # Constraint 13: 2 days in shift1, 1 day in shift2, 2 days in shift3
    'shift1': 2,
    'shift2': 1,
    'shift3': 2,
}

# Time slot mapping
DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
PERIODS = ['8:00-8:50', '9:00-9:50', '10:00-10:50', '11:00-11:50', 
           '12:00-12:50', '2:00-2:50', '3:00-3:50', '4:00-4:50', '5:00-5:50', '6:00-6:50']

# Lab slots (consecutive periods for labs)
LAB_SESSION_HOURS = {
    1: 2,  # 1 credit lab = 2 hours per session (minimum 2 hours)
    2: 2,  # 2 credit lab = 2 hours per session
    3: 3,  # 3 credit lab = 3 hours per session (e.g. a 3-credit practical course with 6 total lab hours might have two 3-hour sessions)
}

# Lab student count thresholds
LAB_STUDENT_THRESHOLDS = {
    'regular': 30,   # Regular lab capacity
    'large': 60,     # Large lab
    'very_large': 120  # Very large lab
}

# Max consecutive teaching hours constraint
MAX_CONSECUTIVE_HOURS = 3

# Max teaching hours per day constraint
MAX_TEACHING_HOURS_PER_DAY = 5

FIXED_LAB_BATCH_CAPACITY = 35  # Fixed lab batch capacity of 35 students

class TimetableScheduler:
    def __init__(self, course_file, room_file):
        self.course_file = course_file
        self.room_file = room_file
        self.output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'timetable')
        
        logger.info(f"Initializing scheduler with course file: {course_file}")
        logger.info(f"Room file: {room_file}")
        logger.info(f"Output directory: {self.output_dir}")
        
        # Create output directory if it doesn't exist
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
            logger.info(f"Created output directory: {self.output_dir}")
        
        # Verify input files exist
        if not os.path.exists(course_file):
            error_msg = f"Course file not found: {course_file}"
            logger.error(error_msg)
            raise FileNotFoundError(error_msg)
        
        if not os.path.exists(room_file):
            error_msg = f"Room file not found: {room_file}"
            logger.error(error_msg)
            raise FileNotFoundError(error_msg)
            
        # Load data
        try:
            self.courses_df = pd.read_csv(course_file)
            logger.info(f"Loaded course data: {len(self.courses_df)} entries")
        except Exception as e:
            logger.error(f"Error loading course data: {str(e)}")
            raise
            
        try:
            self.rooms_df = pd.read_csv(room_file)
            logger.info(f"Loaded room data: {len(self.rooms_df)} entries")
        except Exception as e:
            logger.error(f"Error loading room data: {str(e)}")
            raise
        
        # Clean and prepare data
        try:
            self._prepare_data()
        except Exception as e:
            logger.error(f"Error preparing data: {str(e)}")
            raise
         
    def _prepare_data(self):
        """Clean and prepare the data for scheduling."""
        # Filter rooms based on requirements
        self.classrooms = self.rooms_df[self.rooms_df['is_lab'] == 0]
        self.labs = self.rooms_df[self.rooms_df['is_lab'] == 1]
        
        logger.info(f"Found {len(self.classrooms)} classrooms and {len(self.labs)} labs")
        
        # Create a mapping of teacher to courses
        self.teacher_course_map = {}
        for _, row in self.courses_df.iterrows():
            teacher_id = row['staff_code']
            teacher_name = f"{row['first_name']} {row['last_name']}"
            course_code = row['course_code']
            course_name = row['course_name']
            course_type = str(row['course_type']) # Ensure course_type is string
            student_count = int(row['student_count'])
            course_id = row['id']
            credits_str = row['credits']

            try:
                credits_num = float(credits_str)
            except (ValueError, TypeError):
                logger.warning(f"Invalid credits value: {credits_str} for course {course_code}, defaulting to 1.0 for calculations.")
                credits_num = 1.0
            
            if pd.isna(teacher_id):
                continue
                
            if not course_code.startswith("CS"):
                continue
            
            if teacher_id not in self.teacher_course_map:
                self.teacher_course_map[teacher_id] = {
                    'teacher_name': teacher_name,
                    'courses': []
                }
            
            course_exists = False
            for existing_course in self.teacher_course_map[teacher_id]['courses']:
                if existing_course['course_code'] == course_code and existing_course['course_type'] == course_type:
                    # This check might be too simple if LoT is split and original LoT should not be re-added
                    # Assuming for now that if an LoT is split, the original 'LoT' type won't be processed again for the same teacher/course_code
                    course_exists = True
                    break
            
            if not course_exists:
                is_lab_component = 'L' in course_type
                is_theory_component = 'T' in course_type
                has_practical = 'P' in course_type or 'p' in course_type

                course_entries_to_add = []

                if 'LoT' in course_type:
                    # For combined Lab+Theory courses
                    # Theory part (hours = credits - lab credits)
                    theory_hours = max(int(credits_num - 1), 1) 
                    if theory_hours > 0:
                        course_entries_to_add.append({
                            'course_id': f"{course_id}_T",
                            'course_code': course_code,
                            'course_name': f"{course_name} (Theory)",
                            'course_type': 'T',
                            'student_count': student_count,
                            'credits': credits_num, 
                            'is_lab': False,
                            'hours_per_week': theory_hours,
                            'duration_per_lab_batch': 0,
                            'num_batches': 0
                        })

                    # Lab part - always minimum 2 hours per lab session
                    duration_per_lab_batch_lot = 2 
                    # Calculate number of batches based on student count and fixed capacity of 35
                    if student_count > 0:
                        num_batches_lot = math.ceil(student_count / FIXED_LAB_BATCH_CAPACITY)
                    else:
                        num_batches_lot = 0
                    
                    if num_batches_lot == 0 and student_count > 0: 
                        num_batches_lot = 1
                        
                    # Total teacher lab hours = duration per batch * number of batches
                    total_teacher_hours_lab_lot = duration_per_lab_batch_lot * num_batches_lot

                    if total_teacher_hours_lab_lot > 0:
                        course_entries_to_add.append({
                            'course_id': f"{course_id}_L", 
                            'course_code': course_code,
                            'course_name': f"{course_name} (Lab)",
                            'course_type': 'L', 
                            'student_count': student_count, 
                            'credits': credits_num, 
                            'is_lab': True,
                            'hours_per_week': total_teacher_hours_lab_lot,
                            'duration_per_lab_batch': duration_per_lab_batch_lot,
                            'num_batches': num_batches_lot
                        })
                        logger.info(f"Decomposed LoT {course_code}: Lab part created with {total_teacher_hours_lab_lot} total hours ({num_batches_lot} batches, {duration_per_lab_batch_lot} hrs/batch).")

                elif is_lab_component or has_practical:
                    # For pure lab/practical courses
                    # Extract practical hours from credits or use a default
                    practical_hours = 0
                    # Try to extract P hours from course_type (e.g., "1T2P")
                    p_match = re.search(r'(\d+)[pP]', course_type)
                    if p_match:
                        practical_hours = int(p_match.group(1))
                    else:
                        # Default to credit value if no P specified
                        practical_hours = int(credits_num)
                    
                    # Ensure minimum lab duration is 2 hours
                    duration_per_lab_batch = max(practical_hours, 2)
                    
                    # Calculate number of batches based on student count and fixed capacity
                    if student_count > 0:
                        num_batches = math.ceil(student_count / FIXED_LAB_BATCH_CAPACITY)
                    else:
                        num_batches = 0
                    
                    if num_batches == 0 and student_count > 0:
                        num_batches = 1

                    # Same teacher teaches all batches, so total hours = duration * num_batches
                    total_teacher_hours_lab = duration_per_lab_batch * num_batches
                    
                    if total_teacher_hours_lab > 0:
                        course_entries_to_add.append({
                            'course_id': course_id,
                            'course_code': course_code,
                            'course_name': course_name,
                            'course_type': course_type,
                            'student_count': student_count,
                            'credits': credits_num,
                            'is_lab': True,
                            'hours_per_week': total_teacher_hours_lab,
                            'duration_per_lab_batch': duration_per_lab_batch,
                            'num_batches': num_batches
                        })
                        logger.info(f"Added lab/practical {course_code}: {total_teacher_hours_lab} total hours ({num_batches} batches, {duration_per_lab_batch} hrs/batch).")

                elif is_theory_component: 
                    # Pure theory courses
                    theory_hours = int(credits_num)
                    if theory_hours <= 0: theory_hours = 1
                    if theory_hours > 0:
                        course_entries_to_add.append({
                            'course_id': course_id,
                            'course_code': course_code,
                            'course_name': course_name,
                            'course_type': course_type,
                            'student_count': student_count,
                            'credits': credits_num,
                            'is_lab': False,
                            'hours_per_week': theory_hours,
                            'duration_per_lab_batch': 0,
                            'num_batches': 0
                        })
                else: 
                    # Default case for any other course types
                    default_hours = max(int(credits_num),1)
                    if default_hours > 0:
                        course_entries_to_add.append({
                            'course_id': course_id,
                            'course_code': course_code,
                            'course_name': course_name,
                            'course_type': course_type,
                            'student_count': student_count,
                            'credits': credits_num,
                            'is_lab': False, 
                            'hours_per_week': default_hours,
                            'duration_per_lab_batch': 0,
                            'num_batches': 0
                        })
                        logger.warning(f"Course {course_code} with type {course_type} treated as default theory with {default_hours} hours.")

                for entry in course_entries_to_add:
                    # Final check to ensure this specific entry (e.g. theory part of LoT) isn't already there
                    # This is important if the outer course_exists check wasn't sufficient for split LoT
                    already_present = False
                    for existing_entry in self.teacher_course_map[teacher_id]['courses']:
                        if existing_entry['course_id'] == entry['course_id']:
                            already_present = True
                            logger.warning(f"Skipping duplicate sub-entry: {entry['course_id']} for teacher {teacher_id}")
                            break
                    if not already_present:
                        self.teacher_course_map[teacher_id]['courses'].append(entry)
                        logger.debug(f"Added course entry {entry['course_name']} ({entry['course_id']}) for teacher {teacher_id} with {entry['hours_per_week']} hours per week.")
        
        logger.info(f"Created teacher-course map with {len(self.teacher_course_map)} teachers")
        count = 0
        for tid, tinfo in self.teacher_course_map.items():
            logger.info(f"Teacher: {tinfo['teacher_name']}")
            for c_entry in tinfo['courses']:
                logger.info(f"  Course: {c_entry['course_code']} ({c_entry['course_id']}), Type: {c_entry['course_type']}, Hours: {c_entry['hours_per_week']}, Lab: {c_entry['is_lab']}")
                if c_entry['is_lab']:
                    logger.info(f"    Lab Details: Batches: {c_entry['num_batches']}, Duration/Batch: {c_entry['duration_per_lab_batch']}")
            count += 1
            if count >= 2: 
                break
    
    def generate_timetable(self, use_optimized_constraints=False):
        """Generate the timetable using OR-Tools CP-SAT solver."""
        logger.info("Starting timetable generation...")
        
        try:
            model = cp_model.CpModel()
            
            # Create variables
            # assignment[teacher, course, room, time_slot] = 1 if the teacher is teaching the course in the room at that time
            assignment = {}
            
            # Initialize relaxation variables list
            relax_vars = []
            
            # Collect all valid combinations
            for teacher_id, teacher_info in self.teacher_course_map.items():
                for course in teacher_info['courses']:
                    course_id = course['course_id']
                    is_lab = course['is_lab']
                    
                    # Use appropriate room list
                    room_list = self.labs if is_lab else self.classrooms
                    student_count = course['student_count']
                    
                    # Filter rooms by capacity
                    suitable_rooms = room_list[room_list['room_max_cap'] >= student_count]
                    
                    # If no suitable rooms, try with a relaxed constraint
                    if len(suitable_rooms) == 0:
                        logger.warning(f"No suitable rooms for course {course['course_code']} with {student_count} students. Using all available rooms.")
                        suitable_rooms = room_list
                    
                    # For each suitable room
                    for _, room in suitable_rooms.iterrows():
                        room_id = room['id']
                        
                        # Create assignment variables for each possible time slot
                        for time_slot in range(TIME_SLOTS):
                            # Create a key and ensure it exists in the assignment dictionary
                            key = (teacher_id, course_id, room_id, time_slot)
                            assignment[key] = model.NewBoolVar(f't{teacher_id}_c{course_id}_r{room_id}_s{time_slot}')
            
            logger.info(f"Created {len(assignment)} assignment variables")
            
            # Generate constraints either with the optimized approach or the standard approach
            if use_optimized_constraints:
                constraint_count, relax_vars = self._generate_constraints_optimized(model, assignment)
            else:
                # Constraints
                constraint_count = 0
                
                # 1. Each course must be scheduled for the required number of hours per week
                for teacher_id, teacher_info in self.teacher_course_map.items():
                    for course in teacher_info['courses']:
                        course_id = course['course_id']
                        hours_needed = course['hours_per_week']
                        is_lab = course['is_lab']
                        credits = course['credits']
                        
                        # Lab courses should be scheduled in consecutive slots
                        if is_lab:
                            num_batches = course['num_batches']
                            duration_per_lab_batch = course['duration_per_lab_batch']
                            student_count = course['student_count'] # Still needed for room selection guidance

                            logger.info(f"Processing lab {course['course_code']} for teacher {teacher_id}: {num_batches} batches, {duration_per_lab_batch} hrs/batch.")

                            if num_batches == 0 or duration_per_lab_batch == 0:
                                logger.info(f"Skipping lab {course['course_code']} as it has 0 batches or 0 duration per batch.")
                                continue # No hours to schedule

                            lab_scheduled_successfully = False
                            
                            # Find valid starting slots for a lab batch
                            valid_lab_starts_for_segment = []
                            for day in range(NUM_DAYS):
                                for period in range(NUM_PERIODS - duration_per_lab_batch + 1):
                                    start_slot = day * NUM_PERIODS + period
                                    valid_lab_starts_for_segment.append(start_slot)
                            
                            if not valid_lab_starts_for_segment:
                                logger.warning(f"No valid start times for lab segments of duration {duration_per_lab_batch} for {course['course_code']}. Skipping lab scheduling.")
                                continue

                            # Create variables for potential lab start times for each batch
                            lab_batch_starts = {} # Stores var for each (teacher, course, room, start_slot, batch_idx)
                            
                            for batch_idx in range(num_batches):
                                for start_slot in valid_lab_starts_for_segment:
                                    suitable_lab_rooms = self.labs[self.labs['room_max_cap'] >= FIXED_LAB_BATCH_CAPACITY]
                                    if len(suitable_lab_rooms) == 0:
                                        logger.warning(f"No lab rooms with capacity >= {FIXED_LAB_BATCH_CAPACITY} for {course['course_code']} batch {batch_idx}. Using all labs.")
                                        suitable_lab_rooms = self.labs
                                    
                                    for _, room in suitable_lab_rooms.iterrows():
                                        room_id = room['id']
                                        key = (teacher_id, course_id, room_id, start_slot, batch_idx)
                                        lab_batch_starts[key] = model.NewBoolVar(f'lab_start_t{teacher_id}_c{course_id}_r{room_id}_s{start_slot}_b{batch_idx}')
                            
                            if not lab_batch_starts and num_batches > 0:
                                logger.error(f"CRITICAL: No lab_batch_start variables created for {course['course_code']} (expected {num_batches} batches). Lab cannot be scheduled.")
                                continue

                            # Connect lab batch starts to assignments
                            for lab_start_key, lab_start_var in lab_batch_starts.items():
                                _t, _c, _r, _start_slot, _batch_idx = lab_start_key
                                for offset in range(duration_per_lab_batch):
                                    slot = _start_slot + offset
                                    if slot < TIME_SLOTS and (slot // NUM_PERIODS == _start_slot // NUM_PERIODS): # same day
                                        assign_key = (_t, _c, _r, slot)
                                        if assign_key in assignment:
                                            model.AddImplication(lab_start_var, assignment[assign_key])
                                            constraint_count +=1 

                            # Constraint 3: Exactly one session (room/time) must be chosen for each batch.
                            for batch_idx in range(num_batches):
                                vars_for_this_batch = [
                                    var for key, var in lab_batch_starts.items()
                                    if key[0] == teacher_id and key[1] == course_id and key[4] == batch_idx
                                ]
                                if vars_for_this_batch:
                                    model.Add(sum(vars_for_this_batch) == 1)
                                    constraint_count += 1
                                    lab_scheduled_successfully = True # Mark that basic scheduling for this batch is possible
                                elif num_batches > 0: # Should not happen if lab_batch_starts was populated for this batch
                                    logger.error(f"CRITICAL: No lab_batch_start vars found for {course['course_code']} batch {batch_idx} during per-batch sum constraint.")
                                    lab_scheduled_successfully = False # This batch cannot be scheduled
                                    break # Stop processing this lab course if a batch is unschedulable
                            
                            if not lab_scheduled_successfully and num_batches > 0:
                                logger.warning(f"Failed to set up 'one session per batch' for lab {course['course_code']}. Skipping different-day constraints.")
                                continue # Move to next course if any batch failed basic scheduling

                            # Constraint 4: Batches for the same course must be on different days
                            if num_batches > 1:
                                batch_on_day_vars = {}
                                # For each batch and each day, create a variable indicating if this batch runs on this day.
                                for b_idx in range(num_batches):
                                    for day_idx in range(NUM_DAYS):
                                        key_bod = (course_id, b_idx, day_idx)
                                        batch_on_day_vars[key_bod] = model.NewBoolVar(f'c{course_id}_b{b_idx}_on_d{day_idx}')
                                        
                                        # Collect lab_start_vars for this batch (b_idx) that fall on this day (day_idx)
                                        potential_starts_for_batch_on_this_day = []
                                        for (t, c, r, s, batch_in_key), var in lab_batch_starts.items():
                                            if t == teacher_id and c == course_id and batch_in_key == b_idx:
                                                if (s // NUM_PERIODS) == day_idx:
                                                    potential_starts_for_batch_on_this_day.append(var)
                                        
                                        if potential_starts_for_batch_on_this_day:
                                            # If the batch is on this day, exactly one of its starts on this day must be chosen.
                                            # (Combined with "exactly one start per batch overall", this means THE chosen start is on this day)
                                            model.Add(sum(potential_starts_for_batch_on_this_day) == 1).OnlyEnforceIf(batch_on_day_vars[key_bod])
                                            model.Add(sum(potential_starts_for_batch_on_this_day) == 0).OnlyEnforceIf(batch_on_day_vars[key_bod].Not())
                                            constraint_count += 2
                                        else:
                                            # No possible way for this batch to be on this day
                                            model.Add(batch_on_day_vars[key_bod] == 0)
                                        constraint_count += 1
                                
                                # For each day, at most one batch of this course can be active
                                for day_idx in range(NUM_DAYS):
                                    vars_for_course_on_this_day = []
                                    for b_idx in range(num_batches):
                                        vars_for_course_on_this_day.append(batch_on_day_vars[(course_id, b_idx, day_idx)])
                                    
                                    if vars_for_course_on_this_day:
                                        model.Add(sum(vars_for_course_on_this_day) <= 1)
                                        constraint_count += 1
                            
                            # This replaces the old lab_scheduled_successfully check for the whole block
                            # If we reached here and num_batches > 0, it means per-batch scheduling was attempted.
                            # Individual batch success is handled above.
                        
                        else:  # Regular theory courses
                            # Sum of all assignments for this course should equal the required hours
                            course_hours = []
                            for _, room in self.classrooms.iterrows():
                                room_id = room['id']
                                for time_slot in range(TIME_SLOTS):
                                    if (teacher_id, course_id, room_id, time_slot) in assignment:
                                        course_hours.append(assignment[(teacher_id, course_id, room_id, time_slot)])
                            
                            if course_hours:
                                model.Add(sum(course_hours) == hours_needed)
                                constraint_count += 1
                
                # 2. A teacher cannot teach more than one course at the same time
                for time_slot in range(TIME_SLOTS):
                    for teacher_id in self.teacher_course_map:
                        teacher_slots = []
                        for course in self.teacher_course_map[teacher_id]['courses']:
                            course_id = course['course_id']
                            is_lab = course['is_lab']
                            room_list = self.labs if is_lab else self.classrooms
                            
                            for _, room in room_list.iterrows():
                                room_id = room['id']
                                if (teacher_id, course_id, room_id, time_slot) in assignment:
                                    teacher_slots.append(assignment[(teacher_id, course_id, room_id, time_slot)])
                        
                        if teacher_slots:
                            model.Add(sum(teacher_slots) <= 1)
                            constraint_count += 1
                
                # 3. A room cannot be used for more than one course at the same time
                for time_slot in range(TIME_SLOTS):
                    for _, room in self.rooms_df.iterrows():
                        room_id = room['id']
                        room_slots = []
                        
                        for teacher_id, teacher_info in self.teacher_course_map.items():
                            for course in teacher_info['courses']:
                                course_id = course['course_id']
                                if (teacher_id, course_id, room_id, time_slot) in assignment:
                                    room_slots.append(assignment[(teacher_id, course_id, room_id, time_slot)])
                        
                        if room_slots:
                            model.Add(sum(room_slots) <= 1)
                            constraint_count += 1
                
                # 4. Teachers should have a reasonable daily workload (constraint #2: max 5 periods per day)
                for teacher_id in self.teacher_course_map:
                    for day in range(NUM_DAYS):
                        teacher_day_slots = []
                        for period in range(NUM_PERIODS):
                            time_slot = day * NUM_PERIODS + period
                            for course in self.teacher_course_map[teacher_id]['courses']:
                                course_id = course['course_id']
                                is_lab = course['is_lab']
                                room_list = self.labs if is_lab else self.classrooms
                                
                                for _, room in room_list.iterrows():
                                    room_id = room['id']
                                    if (teacher_id, course_id, room_id, time_slot) in assignment:
                                        teacher_day_slots.append(assignment[(teacher_id, course_id, room_id, time_slot)])
                        
                        if teacher_day_slots:
                            model.Add(sum(teacher_day_slots) <= MAX_TEACHING_HOURS_PER_DAY)  # Max teaching hours per day
                            constraint_count += 1
                
                # 6. Max consecutive teaching hours constraint (#10 in constraints.txt)
                for teacher_id in self.teacher_course_map:
                    for day in range(NUM_DAYS):
                        for start_period in range(NUM_PERIODS - MAX_CONSECUTIVE_HOURS + 1):
                            consecutive_slots = []
                            for offset in range(MAX_CONSECUTIVE_HOURS + 1):  # +1 to check for MAX_CONSECUTIVE_HOURS+1 constraint
                                period = start_period + offset
                                if period < NUM_PERIODS:
                                    time_slot = day * NUM_PERIODS + period
                                    period_slots = []
                                    for course in self.teacher_course_map[teacher_id]['courses']:
                                        course_id = course['course_id']
                                        is_lab = course['is_lab']
                                        room_list = self.labs if is_lab else self.classrooms
                                        
                                        for _, room in room_list.iterrows():
                                            room_id = room['id']
                                            if (teacher_id, course_id, room_id, time_slot) in assignment:
                                                period_slots.append(assignment[(teacher_id, course_id, room_id, time_slot)])
                                    
                                    # Add this period's sum to the consecutive slots list
                                    if period_slots:
                                        consecutive_slots.append(sum(period_slots))
                                    else:
                                        consecutive_slots.append(model.NewConstant(0))
                            
                            # If there are enough consecutive periods to check
                            if len(consecutive_slots) > MAX_CONSECUTIVE_HOURS:
                                # Calculate sum of consecutive hours
                                consecutive_sum = sum(consecutive_slots[:MAX_CONSECUTIVE_HOURS+1])
                                # Ensure no more than MAX_CONSECUTIVE_HOURS are taught in a row
                                model.Add(consecutive_sum <= MAX_CONSECUTIVE_HOURS)
                                constraint_count += 1
                
                # 7. Course distribution across the week (constraint #12) - More flexible version
                course_day_vars = {}
                for teacher_id, teacher_info in self.teacher_course_map.items():
                    for course in teacher_info['courses']:
                        if not course['is_lab'] and course['hours_per_week'] > 2:  # Only for theory courses with more than 2 hours
                            course_id = course['course_id']
                            hours_needed = course['hours_per_week']
                            
                            # Create variables to track which days this course is taught on
                            for day in range(NUM_DAYS):
                                course_day_vars[(teacher_id, course_id, day)] = model.NewBoolVar(
                                    f'course_day_t{teacher_id}_c{course_id}_d{day}')
                                
                                # Get all slots for this course on this day
                                day_slots = []
                                for period in range(NUM_PERIODS):
                                    time_slot = day * NUM_PERIODS + period
                                    for _, room in self.classrooms.iterrows():
                                        room_id = room['id']
                                        if (teacher_id, course_id, room_id, time_slot) in assignment:
                                            day_slots.append(assignment[(teacher_id, course_id, room_id, time_slot)])
                                
                                # If any slot on this day is used, the day is used
                                if day_slots:
                                    model.Add(sum(day_slots) >= 1).OnlyEnforceIf(course_day_vars[(teacher_id, course_id, day)])
                                    model.Add(sum(day_slots) == 0).OnlyEnforceIf(course_day_vars[(teacher_id, course_id, day)].Not())
                                    constraint_count += 2
                                
                            # Count total days used for this course
                            course_days = []
                            for day in range(NUM_DAYS):
                                if (teacher_id, course_id, day) in course_day_vars:
                                    course_days.append(course_day_vars[(teacher_id, course_id, day)])
                                
                            # Make this constraint relaxable for courses with many hours
                            if course_days:
                                min_days_needed = min(2, hours_needed - 1)  # At least 2 days or (hours - 1)
                                
                                # Add a relaxable constraint
                                relax_var = model.NewBoolVar(f'relax_spread_{teacher_id}_{course_id}')
                                relax_vars.append(relax_var)
                                
                                # Either enforce min days or relax the constraint
                                model.Add(sum(course_days) >= min_days_needed).OnlyEnforceIf(relax_var.Not())
                                # When relaxed, at least try to use more than 1 day
                                model.Add(sum(course_days) >= 1).OnlyEnforceIf(relax_var)
                                constraint_count += 2
                                
                                # Also limit hours per day to avoid too many hours in one day
                                for day in range(NUM_DAYS):
                                    day_slots = []
                                    for period in range(NUM_PERIODS):
                                        time_slot = day * NUM_PERIODS + period
                                        for _, room in self.classrooms.iterrows():
                                            room_id = room['id']
                                            if (teacher_id, course_id, room_id, time_slot) in assignment:
                                                day_slots.append(assignment[(teacher_id, course_id, room_id, time_slot)])
                                        
                                        if day_slots:
                                            # Allow at most hours_needed-1 in one day (or 3, whichever is less)
                                            max_per_day = min(hours_needed-1, 3) 
                                            model.Add(sum(day_slots) <= max_per_day)
                                            constraint_count += 1
                
                # 8. Shift distribution constraint (#13)
                for teacher_id in self.teacher_course_map:
                    # Create variables to track which shifts are used on each day
                    shift_day_vars = {}
                    for day in range(NUM_DAYS):
                        for shift_name, shift_periods in SHIFTS.items():
                            # Variable is 1 if teacher teaches in this shift on this day
                            shift_day_vars[(teacher_id, day, shift_name)] = model.NewBoolVar(
                                f'shift_day_t{teacher_id}_d{day}_s{shift_name}')
                            
                            # Collect slots for this shift on this day
                            shift_slots = []
                            for period in shift_periods:
                                if period < NUM_PERIODS:  # Ensure period is valid
                                    time_slot = day * NUM_PERIODS + period
                                    for course in self.teacher_course_map[teacher_id]['courses']:
                                        course_id = course['course_id']
                                        is_lab = course['is_lab']
                                        room_list = self.labs if is_lab else self.classrooms
                                        
                                        for _, room in room_list.iterrows():
                                            room_id = room['id']
                                            if (teacher_id, course_id, room_id, time_slot) in assignment:
                                                shift_slots.append(assignment[(teacher_id, course_id, room_id, time_slot)])
                            
                            # If any slot in this shift is used, the shift is used
                            if shift_slots:
                                model.Add(sum(shift_slots) >= 1).OnlyEnforceIf(shift_day_vars[(teacher_id, day, shift_name)])
                                model.Add(sum(shift_slots) == 0).OnlyEnforceIf(shift_day_vars[(teacher_id, day, shift_name)].Not())
                                constraint_count += 2
                    
                    # Count total days in each shift
                    for shift_name in SHIFTS.keys():
                        shift_days = []
                        for day in range(NUM_DAYS):
                            if (teacher_id, day, shift_name) in shift_day_vars:
                                shift_days.append(shift_day_vars[(teacher_id, day, shift_name)])
                        
                        if shift_days:
                            # Create relaxation variables
                            relax_var = model.NewBoolVar(f'relax_shift_{teacher_id}_{shift_name}')
                            relax_vars.append(relax_var)
                            
                            # Apply relaxable shift distribution
                            target_days = TARGET_SHIFT_DAYS.get(shift_name)
                            if target_days is not None:
                                model.Add(sum(shift_days) == target_days).OnlyEnforceIf(relax_var.Not())
                                # When relaxed, allow any number of days (up to NUM_DAYS)
                                model.Add(sum(shift_days) <= NUM_DAYS).OnlyEnforceIf(relax_var)
                            else: # Fallback for undefined shifts, though all should be defined
                                model.Add(sum(shift_days) <= NUM_DAYS) # No specific target
                            constraint_count += 1
                
            logger.info(f"Added {constraint_count} constraints to the model")
            
            # Add hints for the solver based on a simple greedy approach
            for teacher_id, teacher_info in self.teacher_course_map.items():
                for course in teacher_info['courses']:
                    course_id = course['course_id']
                    hours_needed = course['hours_per_week']
                    
                    # Skip if hours needed is 0
                    if hours_needed == 0:
                        continue
                    
                    is_lab = course['is_lab']
                    room_list = self.labs if is_lab else self.classrooms
                    
                    # Create a list of valid assignments for this course
                    valid_assignments = []
                    for day in range(NUM_DAYS):
                        for period in range(NUM_PERIODS):
                            time_slot = day * NUM_PERIODS + period
                            
                            # For labs, check if there are enough consecutive slots
                            if is_lab:
                                lab_hours = int(course['credits']) * 2
                                if period + lab_hours > NUM_PERIODS:
                                    continue  # Skip if lab would cross day boundaries
                            
                            # Find suitable rooms
                            for _, room in room_list.iterrows():
                                room_id = room['id']
                                if room['room_max_cap'] >= course['student_count']:
                                    key = (teacher_id, course_id, room_id, time_slot)
                                    if key in assignment:
                                        valid_assignments.append(key)
                    
                    # Sort valid assignments by day and period to spread courses across week
                    valid_assignments.sort(key=lambda x: (x[3] // NUM_PERIODS, x[3] % NUM_PERIODS))
                    
                    # Add hints for up to hours_needed slots
                    for i in range(min(hours_needed, len(valid_assignments))):
                        key = valid_assignments[i]
                        model.AddHint(assignment[key], 1)
            
            # Add the objective back right before the model statistics reporting
            # Add objective to minimize relaxation
            if relax_vars:
                model.Minimize(sum(relax_vars))
                logger.info(f"Added {len(relax_vars)} relaxation variables")
            
            # Report simple statistics about the model
            logger.info(f"Model statistics:")
            logger.info(f"- Number of assignment variables: {len(assignment)}")
            logger.info(f"- Number of constraints added: {constraint_count}")
            logger.info(f"- Number of relaxation variables: {len(relax_vars)}")
            
            # Solve the model
            logger.info("Starting solver...")
            solver = cp_model.CpSolver()
            
            # Enable parallelism if multiple cores are available
            num_cores = multiprocessing.cpu_count()
            num_workers = max(1, num_cores - 1)  # Leave one core free for system operations
            logger.info(f"Using {num_workers} worker threads (out of {num_cores} available cores)")
            
            # Configure solver for parallel execution
            solver.parameters.num_search_workers = num_workers
            
            # Set a time limit based on the model size
            # We calculate this based on the number of assignment variables
            if len(assignment) > 100000:
                solver.parameters.max_time_in_seconds = 600  # 10 minutes
            else:
                solver.parameters.max_time_in_seconds = 300  # 5 minutes
                
            # Try with a lower time limit first to quickly find if it's infeasible
            solver.parameters.max_time_in_seconds = 60  # 1 minute to quickly check
            status = solver.Solve(model)
            
            # If it's infeasible or time limit is reached, try with relaxed constraints
            if status in [cp_model.UNKNOWN, cp_model.INFEASIBLE]:
                logger.info("First attempt unsuccessful, trying with relaxed approach...")
                
                # Instead of analyzing conflicts (which may not be supported),
                # just log the status and try with a longer time limit
                logger.info(f"Initial solver status: {solver.StatusName(status)}")
                
                # Try with a more relaxed version and longer time limit
                logger.info("Trying with relaxed constraints and longer time limit...")
                solver.parameters.max_time_in_seconds = 300  # 5 minutes
                status = solver.Solve(model)
            
            logger.info(f"Solver finished with status: {solver.StatusName(status)}")
            
            # If we found a solution and have an objective (relaxation)
            if status in [cp_model.OPTIMAL, cp_model.FEASIBLE] and relax_vars:
                try:
                    objective_value = solver.ObjectiveValue()
                    logger.info(f"Objective value (relaxation count): {objective_value}")
                    if objective_value > 0:
                        logger.warning(f"Solution found but with {objective_value} relaxed constraints")
                except Exception as e:
                    logger.warning(f"Could not get objective value: {str(e)}")
                    
            # Process results
            if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
                logger.info(f"Solution found! Status: {solver.StatusName(status)}")
                
                # Extract the solution with error handling
                solution = {}
                try:
                    for teacher_id, teacher_data in self.teacher_course_map.items():
                        solution[teacher_id] = {
                            'teacher_name': teacher_data['teacher_name'],
                            'schedule': [[None for _ in range(NUM_PERIODS)] for _ in range(NUM_DAYS)]
                        }
                        
                        for course in teacher_data['courses']:
                            course_id = course['course_id']
                            is_lab = course['is_lab']
                            room_list = self.labs if is_lab else self.classrooms
                            
                            for _, room in room_list.iterrows():
                                room_id = room['id']
                                for time_slot in range(TIME_SLOTS):
                                    key = (teacher_id, course_id, room_id, time_slot)
                                    if key in assignment:
                                        try:
                                            if solver.Value(assignment[key]) == 1:
                                                day = time_slot // NUM_PERIODS
                                                period = time_slot % NUM_PERIODS
                                                
                                                solution[teacher_id]['schedule'][day][period] = {
                                                    'course_code': course['course_code'],
                                                    'course_name': course['course_name'],
                                                    'room': f"{room['block']} - {room['room_number']}",
                                                    'room_id': room_id,
                                                    'is_lab': is_lab
                                                }
                                        except Exception as e:
                                            logger.error(f"Error checking assignment value: {str(e)}")
                                            continue
                    
                    logger.info("Generating visualizations...")
                    self.visualize_timetables(solution)
                    
                    logger.info("Saving solution to JSON...")
                    self.save_solution_json(solution)
                    return solution
                except Exception as e:
                    logger.error(f"Error extracting solution: {str(e)}", exc_info=True)
                    return None
            else:
                logger.error(f"No solution found. Status: {solver.StatusName(status)}")
                return None
                
        except Exception as e:
            logger.error(f"Error generating timetable: {str(e)}", exc_info=True)
            raise
    
    def _visualize_teacher_parallel(self, teacher_data, teacher_id, output_dir, course_colors, shifts):
        """Helper method for parallel visualization of a single teacher's timetable."""
        try:
            teacher_name = teacher_data['teacher_name']
            schedule = teacher_data['schedule']
            
            # Create a figure
            fig, ax = plt.subplots(figsize=(14, 8))
            
            # Create a grid for the schedule
            data = np.zeros((NUM_DAYS, NUM_PERIODS))
            
            # Fill in the grid with course information
            for day in range(NUM_DAYS):
                for period in range(NUM_PERIODS):
                    if schedule[day][period] is not None:
                        data[day, period] = 1  # Just to indicate that there's a class
            
            # Create a heatmap
            sns.heatmap(data, cmap='Blues', alpha=0.3, cbar=False, linewidths=.5, ax=ax)
            
            # Add text for each cell
            for day in range(NUM_DAYS):
                for period in range(NUM_PERIODS):
                    if schedule[day][period] is not None:
                        course_info = schedule[day][period]
                        course_code = course_info['course_code']
                        room = course_info['room']
                        is_lab = course_info['is_lab']
                        
                        # Color the cell background based on the course
                        rect = plt.Rectangle((period, day), 1, 1, fill=True, 
                                            color=course_colors.get(course_code, 'gray'),  # Default to gray if color not found
                                            alpha=0.5 if not is_lab else 0.7)
                        ax.add_patch(rect)
                        
                        # Add text
                        text = f"{course_code}\n{room}"
                        if is_lab:
                            text = f"LAB: {text}"
                        ax.text(period + 0.5, day + 0.5, text, ha='center', va='center', fontsize=8, 
                               fontweight='bold' if is_lab else 'normal')
            
            # Set the labels
            ax.set_xticks(np.arange(NUM_PERIODS) + 0.5)
            ax.set_yticks(np.arange(NUM_DAYS) + 0.5)
            ax.set_xticklabels(PERIODS)
            ax.set_yticklabels(DAYS)
            ax.set_xlabel('Periods')
            ax.set_ylabel('Days')
            plt.title(f'Timetable for {teacher_name} ({teacher_id})')
            
            # Add a legend for courses
            handles = []
            # Add shift backgrounds
            shift_colors = {'shift1': 'lightblue', 'shift2': 'lightyellow', 'shift3': 'lightgreen'}
            for shift_name, periods in shifts.items():
                # Add the shift background to the legend
                handles.append(Patch(color=shift_colors[shift_name], alpha=0.3, 
                                    label=f"Shift {shift_name[-1]}: {PERIODS[periods[0]]} - {PERIODS[periods[-1]]}"))
            
            # Add courses
            for course_code, color in course_colors.items():
                # Only add courses that this teacher teaches
                if any(schedule[day][period] is not None and schedule[day][period]['course_code'] == course_code 
                      for day in range(NUM_DAYS) for period in range(NUM_PERIODS)):
                    is_lab = any(schedule[day][period] is not None and 
                                schedule[day][period]['course_code'] == course_code and
                                schedule[day][period]['is_lab']
                                for day in range(NUM_DAYS) for period in range(NUM_PERIODS))
                    handles.append(Patch(color=color, alpha=0.7 if is_lab else 0.5, 
                                        label=f"{'LAB: ' if is_lab else ''}{course_code}"))
            
            plt.legend(handles=handles, title='Shifts & Courses', bbox_to_anchor=(1.05, 1), loc='upper left')
            
            plt.tight_layout()
            
            # Save the figure
            try:
                filename = os.path.join(output_dir, f"{teacher_id}_{teacher_name.replace(' ', '_')}.png")
                plt.savefig(filename, dpi=100, bbox_inches='tight')
                return f"Saved timetable visualization for {teacher_id} to {filename}"
            except Exception as e:
                return f"Error saving visualization for {teacher_id}: {str(e)}"
            finally:
                plt.close()
        except Exception as e:
            plt.close() if 'plt' in locals() else None
            return f"Error creating visualization for teacher {teacher_id}: {str(e)}"
    
    def visualize_timetables(self, solution):
        """Create and save visualizations of timetables for each teacher."""
        try:
            if not solution:
                logger.warning("No solution to visualize")
                return
            
            # Create a colormap for courses
            course_colors = {}
            colors = list(mcolors.TABLEAU_COLORS.values()) + list(mcolors.CSS4_COLORS.values())
            
            # First, gather all unique courses across all teachers
            all_courses = set()
            for teacher_id, teacher_data in solution.items():
                schedule = teacher_data['schedule']
                for day in range(NUM_DAYS):
                    for period in range(NUM_PERIODS):
                        if schedule[day][period] is not None:
                            all_courses.add(schedule[day][period]['course_code'])
            
            logger.info(f"Found {len(all_courses)} unique courses to visualize")
            
            # Assign colors to courses
            for i, course in enumerate(all_courses):
                course_colors[course] = colors[i % len(colors)]
            
            # Use parallel processing for large datasets (more than 20 teachers)
            if len(solution) > 20 and multiprocessing.cpu_count() > 1:
                logger.info(f"Using parallel processing for visualizing {len(solution)} teachers")
                # Create a pool of workers
                num_workers = min(multiprocessing.cpu_count(), 8)  # Limit to 8 workers max
                
                with multiprocessing.Pool(processes=num_workers) as pool:
                    # Create a partial function with fixed parameters
                    visualize_func = partial(
                        self._visualize_teacher_parallel, 
                        output_dir=self.output_dir,
                        course_colors=course_colors,
                        shifts=SHIFTS
                    )
                    
                    # Map the function to the items
                    items = [(teacher_data, teacher_id) for teacher_id, teacher_data in solution.items()]
                    results = pool.starmap(visualize_func, items)
                    
                    # Log results
                    for result in results:
                        if result and "Error" in result:
                            logger.error(result)
                        elif result:
                            logger.info(result)
                
                logger.info(f"Generated timetable visualizations for {len(solution)} teachers using parallel processing")
            else:
                # Use the original sequential approach for smaller datasets
                teacher_count = 0
                for teacher_id, teacher_data in solution.items():
                    try:
                        teacher_name = teacher_data['teacher_name']
                        schedule = teacher_data['schedule']
                        
                        # Create a figure
                        fig, ax = plt.subplots(figsize=(14, 8))
                        
                        # Create a grid for the schedule
                        data = np.zeros((NUM_DAYS, NUM_PERIODS))
                        
                        # Fill in the grid with course information
                        for day in range(NUM_DAYS):
                            for period in range(NUM_PERIODS):
                                if schedule[day][period] is not None:
                                    data[day, period] = 1  # Just to indicate that there's a class
                        
                        # Create a heatmap
                        sns.heatmap(data, cmap='Blues', alpha=0.3, cbar=False, linewidths=.5, ax=ax)
                        
                        # Add text for each cell
                        for day in range(NUM_DAYS):
                            for period in range(NUM_PERIODS):
                                if schedule[day][period] is not None:
                                    course_info = schedule[day][period]
                                    course_code = course_info['course_code']
                                    room = course_info['room']
                                    is_lab = course_info['is_lab']
                                    
                                    # Color the cell background based on the course
                                    rect = plt.Rectangle((period, day), 1, 1, fill=True, 
                                                        color=course_colors[course_code], 
                                                        alpha=0.5 if not is_lab else 0.7)  # Labs are slightly more opaque
                                    ax.add_patch(rect)
                                    
                                    # Add text
                                    text = f"{course_code}\n{room}"
                                    if is_lab:
                                        text = f"LAB: {text}"
                                    ax.text(period + 0.5, day + 0.5, text, ha='center', va='center', fontsize=8, 
                                           fontweight='bold' if is_lab else 'normal')
                        
                        # Set the labels
                        ax.set_xticks(np.arange(NUM_PERIODS) + 0.5)
                        ax.set_yticks(np.arange(NUM_DAYS) + 0.5)
                        ax.set_xticklabels(PERIODS)
                        ax.set_yticklabels(DAYS)
                        ax.set_xlabel('Periods')
                        ax.set_ylabel('Days')
                        plt.title(f'Timetable for {teacher_name} ({teacher_id})')
                        
                        # Add a legend for courses
                        handles = []
                        # Add shift backgrounds
                        shift_colors = {'shift1': 'lightblue', 'shift2': 'lightyellow', 'shift3': 'lightgreen'}
                        for shift_name, periods in SHIFTS.items():
                            # Add the shift background to the legend
                            handles.append(Patch(color=shift_colors[shift_name], alpha=0.3, 
                                                label=f"Shift {shift_name[-1]}: {PERIODS[periods[0]]} - {PERIODS[periods[-1]]}"))
                        
                        # Add courses
                        for course_code, color in course_colors.items():
                            # Only add courses that this teacher teaches
                            if any(schedule[day][period] is not None and schedule[day][period]['course_code'] == course_code 
                                  for day in range(NUM_DAYS) for period in range(NUM_PERIODS)):
                                is_lab = any(schedule[day][period] is not None and 
                                            schedule[day][period]['course_code'] == course_code and
                                            schedule[day][period]['is_lab']
                                            for day in range(NUM_DAYS) for period in range(NUM_PERIODS))
                                handles.append(Patch(color=color, alpha=0.7 if is_lab else 0.5, 
                                                    label=f"{'LAB: ' if is_lab else ''}{course_code}"))
                        
                        plt.legend(handles=handles, title='Shifts & Courses', bbox_to_anchor=(1.05, 1), loc='upper left')
                        
                        plt.tight_layout()
                        
                        # Save the figure
                        try:
                            filename = os.path.join(self.output_dir, f"{teacher_id}_{teacher_name.replace(' ', '_')}.png")
                            plt.savefig(filename, dpi=100, bbox_inches='tight')
                            logger.info(f"Saved timetable visualization to {filename}")
                        except Exception as e:
                            logger.error(f"Error saving visualization for {teacher_id}: {str(e)}")
                        finally:
                            plt.close()
                            
                        teacher_count += 1
                    except Exception as e:
                        logger.error(f"Error creating visualization for teacher {teacher_id}: {str(e)}")
                        plt.close()  # Ensure figure is closed
                        continue
                
                logger.info(f"Generated timetable visualizations for {teacher_count} teachers")
        except Exception as e:
            logger.error(f"Error visualizing timetables: {str(e)}", exc_info=True)
            raise
    
    def save_solution_json(self, solution):
        """Save the solution in a JSON file for later use."""
        try:
            if not solution:
                logger.warning("No solution to save")
                return
            
            # Convert the solution to a more JSON-friendly format
            json_solution = {}
            
            # Calculate shift statistics for each teacher
            teacher_shift_stats = {}
            
            for teacher_id, teacher_data in solution.items():
                try:
                    json_solution[teacher_id] = {
                        'teacher_name': teacher_data['teacher_name'],
                        'schedule': [],
                        'stats': {
                            'total_hours': 0,
                            'shifts': {
                                'shift1': 0,  # Days in shift 1
                                'shift2': 0,  # Days in shift 2
                                'shift3': 0,  # Days in shift 3
                            },
                            'hours_per_day': [0] * NUM_DAYS,
                            'lab_hours': 0,
                            'theory_hours': 0,
                        }
                    }
                    
                    # Track which shifts are used on each day
                    teacher_day_shifts = {day: set() for day in range(NUM_DAYS)}
                    
                    for day in range(NUM_DAYS):
                        for period in range(NUM_PERIODS):
                            if teacher_data['schedule'][day][period] is not None:
                                class_info = teacher_data['schedule'][day][period]
                                
                                # Add to schedule
                                json_solution[teacher_id]['schedule'].append({
                                    'day': DAYS[day],
                                    'day_index': day,
                                    'period': PERIODS[period],
                                    'period_index': period,
                                    'course_code': class_info['course_code'],
                                    'course_name': class_info['course_name'],
                                    'room': class_info['room'],
                                    'room_id': int(class_info['room_id']),
                                    'is_lab': class_info['is_lab']
                                })
                                
                                # Update statistics
                                json_solution[teacher_id]['stats']['total_hours'] += 1
                                json_solution[teacher_id]['stats']['hours_per_day'][day] += 1
                                
                                if class_info['is_lab']:
                                    json_solution[teacher_id]['stats']['lab_hours'] += 1
                                else:
                                    json_solution[teacher_id]['stats']['theory_hours'] += 1
                                
                                # Check which shift this period belongs to
                                for shift_name, shift_periods in SHIFTS.items():
                                    if period in shift_periods:
                                        teacher_day_shifts[day].add(shift_name)
                    
                    # Count days in each shift
                    for day, shifts_used in teacher_day_shifts.items():
                        for shift in shifts_used:
                            json_solution[teacher_id]['stats']['shifts'][shift] += 1
                    
                    # Store shift statistics for summary
                    teacher_shift_stats[teacher_id] = {
                        'teacher_name': teacher_data['teacher_name'],
                        'shifts': json_solution[teacher_id]['stats']['shifts'],
                        'total_hours': json_solution[teacher_id]['stats']['total_hours']
                    }
                except Exception as e:
                    logger.error(f"Error processing teacher {teacher_id} for JSON: {str(e)}")
                    continue
            
            # Also create a summary file with key statistics
            summary = {
                'teacher_count': len(solution),
                'teacher_shift_stats': teacher_shift_stats,
                'constraints_applied': [
                    'Max teaching hours per day: ' + str(MAX_TEACHING_HOURS_PER_DAY),
                    'Max consecutive teaching hours: ' + str(MAX_CONSECUTIVE_HOURS),
                    'Shift distribution constraint (made relaxable)',
                    'Lab duration constraints',
                    'Course spread across week constraint',
                    'No teacher/room double booking constraint'
                ]
            }
            
            # Save to files
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = os.path.join(self.output_dir, f"timetable_solution_{timestamp}.json")
            summary_filename = os.path.join(self.output_dir, f"timetable_summary_{timestamp}.json")
            
            try:
                with open(filename, 'w') as f:
                    json.dump(json_solution, f, indent=4)
                logger.info(f"Solution saved to {filename}")
            except Exception as e:
                logger.error(f"Error saving solution JSON: {str(e)}")
            
            try:
                with open(summary_filename, 'w') as f:
                    json.dump(summary, f, indent=4)
                logger.info(f"Summary saved to {summary_filename}")
            except Exception as e:
                logger.error(f"Error saving summary JSON: {str(e)}")
            
        except Exception as e:
            logger.error(f"Error saving solution: {str(e)}", exc_info=True)
            raise

    def _generate_constraints_optimized(self, model, assignment, constraint_count=0):
        """Generate constraints in an optimized way to improve model performance."""
        
        logger.info("Generating constraints with optimized approach...")
        
        # Dictionary to cache common lookups
        teacher_courses = {}
        room_assignments = {}
        day_periods = {}
        
        # Initialize list for relaxation variables
        relax_vars = []
        
        # Pre-compute lookups for efficiency
        for teacher_id in self.teacher_course_map:
            teacher_courses[teacher_id] = []
            for course in self.teacher_course_map[teacher_id]['courses']:
                course_id = course['course_id']
                teacher_courses[teacher_id].append({
                    'course_id': course_id,
                    'is_lab': course['is_lab'],
                    'hours_needed': course['hours_per_week'],
                    'credits': course['credits'],
                    'student_count': course['student_count'],
                    'course_code': course['course_code']
                })
        
        # Pre-compute day-period combinations
        for day in range(NUM_DAYS):
            day_periods[day] = []
            for period in range(NUM_PERIODS):
                day_periods[day].append(day * NUM_PERIODS + period)
        
        # 0. Each course must be scheduled for the required number of hours per week
        for teacher_id, courses in teacher_courses.items():
            for course in courses:
                course_id = course['course_id']
                hours_needed = course['hours_needed']
                is_lab = course['is_lab']
                
                if hours_needed <= 0:
                    continue  # Skip courses with no hours
                
                if is_lab:
                    num_batches = course['num_batches']
                    duration_per_lab_batch = course['duration_per_lab_batch']
                    student_count = course['student_count'] # Still needed for room selection guidance

                    logger.info(f"Optimized: Processing lab {course['course_code']} for teacher {teacher_id}: {num_batches} batches, {duration_per_lab_batch} hrs/batch.")

                    if num_batches == 0 or duration_per_lab_batch == 0:
                        logger.info(f"Optimized: Skipping lab {course['course_code']} due to 0 batches/duration.")
                        continue

                    lab_scheduled_opt = False

                    valid_lab_starts_for_segment_opt = []
                    for day in range(NUM_DAYS):
                        for period in range(NUM_PERIODS - duration_per_lab_batch + 1):
                            start_slot = day * NUM_PERIODS + period
                            valid_lab_starts_for_segment_opt.append(start_slot)
                    
                    if not valid_lab_starts_for_segment_opt:
                        logger.warning(f"Optimized: No valid start times for lab segments of duration {duration_per_lab_batch} for {course['course_code']}. Skipping.")
                        continue

                    lab_batch_starts_opt = {}
                    for batch_idx in range(num_batches):
                        for start_slot in valid_lab_starts_for_segment_opt:
                            suitable_lab_rooms_opt = self.labs[self.labs['room_max_cap'] >= FIXED_LAB_BATCH_CAPACITY]
                            if len(suitable_lab_rooms_opt) == 0:
                                logger.warning(f"Optimized: No lab rooms with capacity >= {FIXED_LAB_BATCH_CAPACITY} for {course['course_code']} batch {batch_idx}. Using all labs.")
                                suitable_lab_rooms_opt = self.labs
                            
                            for _, room in suitable_lab_rooms_opt.iterrows():
                                room_id = room['id']
                                key = (teacher_id, course_id, room_id, start_slot, batch_idx)
                                lab_batch_starts_opt[key] = model.NewBoolVar(f'opt_lab_start_t{teacher_id}_c{course_id}_r{room_id}_s{start_slot}_b{batch_idx}')
                    
                    if not lab_batch_starts_opt and num_batches > 0:
                        logger.error(f"CRITICAL Optimized: No lab_batch_start variables created for {course['course_code']} (expected {num_batches} batches). Lab cannot be scheduled.")
                        continue

                    # Connect lab batch starts to assignments (Implications)
                    for lab_start_key, lab_start_var in lab_batch_starts_opt.items():
                        _t, _c, _r, _start_slot, _batch_idx = lab_start_key
                        for offset in range(duration_per_lab_batch):
                            slot = _start_slot + offset
                            if slot < TIME_SLOTS and (slot // NUM_PERIODS == _start_slot // NUM_PERIODS):
                                assign_key = (_t, _c, _r, slot)
                                if assign_key in assignment:
                                    model.AddImplication(lab_start_var, assignment[assign_key])
                                    constraint_count += 1
                    
                    # Constraint: Exactly one session must be chosen for each batch (Relaxable)
                    lab_scheduled_opt_successfully_per_batch = True
                    for batch_idx in range(num_batches):
                        vars_for_this_batch_opt = [
                            var for key, var in lab_batch_starts_opt.items()
                            if key[0] == teacher_id and key[1] == course_id and key[4] == batch_idx
                        ]
                        if vars_for_this_batch_opt:
                            relax_var_batch_sched = model.NewBoolVar(f'opt_relax_lab_batch_sched_{teacher_id}_{course_id}_{batch_idx}')
                            relax_vars.append(relax_var_batch_sched)
                            model.Add(sum(vars_for_this_batch_opt) == 1).OnlyEnforceIf(relax_var_batch_sched.Not())
                            model.Add(sum(vars_for_this_batch_opt) <= 1).OnlyEnforceIf(relax_var_batch_sched) # Allow 0 or 1 if relaxed
                            constraint_count += 2
                        elif num_batches > 0:
                            logger.error(f"CRITICAL Optimized: No lab_batch_start_opt vars for {course['course_code']} batch {batch_idx}.")
                            lab_scheduled_opt_successfully_per_batch = False
                            break
                    
                    if not lab_scheduled_opt_successfully_per_batch and num_batches > 0:
                        logger.warning(f"Optimized: Failed 'one session per batch' for lab {course['course_code']}. Skipping different-day constraints.")
                        continue

                    # Constraint: Batches for the same course must be on different days (using intermediate vars)
                    if num_batches > 1:
                        batch_on_day_vars_opt = {}
                        for b_idx in range(num_batches):
                            for day_idx in range(NUM_DAYS):
                                key_bod_opt = (course_id, b_idx, day_idx) # Use course_id for uniqueness
                                batch_on_day_vars_opt[key_bod_opt] = model.NewBoolVar(f'opt_c{course_id}_b{b_idx}_on_d{day_idx}')
                                
                                potential_starts_opt = []
                                for (t, c, r, s, batch_in_key), var in lab_batch_starts_opt.items():
                                    if t == teacher_id and c == course_id and batch_in_key == b_idx:
                                        if (s // NUM_PERIODS) == day_idx:
                                            potential_starts_opt.append(var)
                                
                                if potential_starts_opt:
                                    model.Add(sum(potential_starts_opt) == 1).OnlyEnforceIf(batch_on_day_vars_opt[key_bod_opt])
                                    model.Add(sum(potential_starts_opt) == 0).OnlyEnforceIf(batch_on_day_vars_opt[key_bod_opt].Not())
                                    constraint_count += 2
                                else:
                                    model.Add(batch_on_day_vars_opt[key_bod_opt] == 0)
                                    constraint_count += 1
                        
                        for day_idx in range(NUM_DAYS):
                            vars_for_course_on_day_opt = []
                            for b_idx in range(num_batches):
                                vars_for_course_on_day_opt.append(batch_on_day_vars_opt[(course_id, b_idx, day_idx)])
                            
                            if vars_for_course_on_day_opt:
                                model.Add(sum(vars_for_course_on_day_opt) <= 1)
                                constraint_count += 1
                                    
                else: # Theory courses in optimized path
                    # Sum of all assignments for this course should equal required hours
                    course_hours = []
                    for _, room in self.classrooms.iterrows():
                        room_id = room['id']
                        for time_slot in range(TIME_SLOTS):
                            key = (teacher_id, course_id, room_id, time_slot)
                            if key in assignment:
                                course_hours.append(assignment[key])
                    
                    if course_hours:
                        # Create a relaxation variable for course hours
                        relax_var = model.NewBoolVar(f'relax_hours_{teacher_id}_{course_id}')
                        relax_vars.append(relax_var)
                        
                        # Either enforce exact hours or allow fewer hours (but at least 1)
                        model.Add(sum(course_hours) == hours_needed).OnlyEnforceIf(relax_var.Not())
                        
                        # When relaxed, try to get at least some hours (half of required or at least 1)
                        min_hours = max(1, hours_needed // 2)
                        model.Add(sum(course_hours) >= min_hours).OnlyEnforceIf(relax_var)
                        constraint_count += 2
        
        # 1. Teacher cannot teach more than one course at the same time
        for time_slot in range(TIME_SLOTS):
            for teacher_id, courses in teacher_courses.items():
                teacher_slots = []
                
                for course in courses:
                    course_id = course['course_id']
                    room_list = self.labs if course['is_lab'] else self.classrooms
                    
                    for _, room in room_list.iterrows():
                        room_id = room['id']
                        key = (teacher_id, course_id, room_id, time_slot)
                        if key in assignment:
                            teacher_slots.append(assignment[key])
                
                if teacher_slots:
                    model.Add(sum(teacher_slots) <= 1)
                    constraint_count += 1
        
        # 2. Room cannot be used by more than one course at the same time
        for time_slot in range(TIME_SLOTS):
            # Group by room for efficiency
            room_slots = {}
            
            for teacher_id, courses in teacher_courses.items():
                for course in courses:
                    course_id = course['course_id']
                    is_lab = course['is_lab']
                    room_list = self.labs if is_lab else self.classrooms
                    
                    for _, room in room_list.iterrows():
                        room_id = room['id']
                        key = (teacher_id, course_id, room_id, time_slot)
                        
                        if key in assignment:
                            if room_id not in room_slots:
                                room_slots[room_id] = []
                            room_slots[room_id].append(assignment[key])
            
            # Add constraint for each room
            for room_id, slots in room_slots.items():
                if slots:
                    model.Add(sum(slots) <= 1)
                    constraint_count += 1
        
        # 3. Daily teaching load constraints
        for teacher_id, courses in teacher_courses.items():
            for day in range(NUM_DAYS):
                teacher_day_slots = []
                
                for time_slot in day_periods[day]:
                    for course in courses:
                        course_id = course['course_id']
                        is_lab = course['is_lab']
                        room_list = self.labs if is_lab else self.classrooms
                        
                        for _, room in room_list.iterrows():
                            room_id = room['id']
                            key = (teacher_id, course_id, room_id, time_slot)
                            if key in assignment:
                                teacher_day_slots.append(assignment[key])
                
                if teacher_day_slots:
                    model.Add(sum(teacher_day_slots) <= MAX_TEACHING_HOURS_PER_DAY)
                    constraint_count += 1
        
        logger.info(f"Generated {constraint_count} constraints with optimized approach")
        return constraint_count, relax_vars


if __name__ == "__main__":
    # Path to data files
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    course_file = os.path.join(base_dir, 'data/mapped_data/cs_teacher_course_formatted.csv')
    room_file = os.path.join(base_dir, 'data/mapped_data/rooms.csv')
    
    # Create and run the scheduler
    scheduler = TimetableScheduler(course_file, room_file)
    solution = scheduler.generate_timetable()

