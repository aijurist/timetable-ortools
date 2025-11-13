#!/usr/bin/env python3
"""
Selective Timetable Regeneration for Biotechnology 5th Semester

This script regenerates timetables for only Biotechnology 5th semester courses
while respecting existing constraints from other departments and semesters.
"""

import os
import sys
import pandas as pd
import logging
import json
import numpy as np
from datetime import datetime
import shutil
from collections import defaultdict

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))

from combined_scheduler import CombinedScheduler

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("selective_regeneration.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

class SelectiveBiotechS5Regenerator:
    """Selective regenerator for Biotechnology 5th semester timetables."""
    
    def __init__(self, course_file, room_file, existing_lab_timetable, existing_theory_timetable):
        """Initialize the selective regenerator."""
        self.course_file = course_file
        self.room_file = room_file
        self.existing_lab_timetable = existing_lab_timetable
        self.existing_theory_timetable = existing_theory_timetable
        
        # Load and filter data
        self.filtered_course_file = None
        self.existing_constraints = {}
        
        logger.info("Initializing Selective Biotechnology S5 Regenerator...")
        self._prepare_filtered_data()
        self._load_existing_constraints()
    
    def _prepare_filtered_data(self):
        """Filter the course data to include only Biotechnology 5th semester courses."""
        logger.info("Filtering course data for Biotechnology 5th semester...")
        
        # Read the original course file
        courses_df = pd.read_csv(self.course_file)
        logger.info(f"Original course file has {len(courses_df)} entries")
        
        # Filter for Biotechnology 5th semester
        biotech_s5_filter = (
            (courses_df['student_dept'] == 'Biotechnology') & 
            (courses_df['semester'] == 5.0)
        )
        
        biotech_s5_courses = courses_df[biotech_s5_filter].copy()
        logger.info(f"Found {len(biotech_s5_courses)} Biotechnology 5th semester course entries")
        
        if len(biotech_s5_courses) == 0:
            logger.error("No Biotechnology 5th semester courses found in the input data!")
            raise ValueError("No Biotechnology 5th semester courses found")
        
        # Log the courses found
        unique_courses = biotech_s5_courses['course_code'].unique()
        logger.info(f"Biotechnology S5 courses found: {list(unique_courses)}")
        
        # Save filtered data to temporary file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.filtered_course_file = f"temp_biotech_s5_{timestamp}.csv"
        biotech_s5_courses.to_csv(self.filtered_course_file, index=False)
        logger.info(f"Filtered course data saved to: {self.filtered_course_file}")
        
        return biotech_s5_courses
    
    def _load_existing_constraints(self):
        """Load existing timetables to create constraints."""
        logger.info("Loading existing timetables to create constraints...")
        
        # Load existing lab timetable
        try:
            lab_df = pd.read_csv(self.existing_lab_timetable)
            logger.info(f"Total lab entries loaded: {len(lab_df)}")
            
            # Debug: Check unique departments and semesters
            unique_depts = lab_df['department'].unique()
            unique_sems = lab_df['semester'].unique()
            logger.info(f"Unique departments: {unique_depts}")
            logger.info(f"Unique semesters: {unique_sems}")
            
            # Check Biotechnology S5 entries before filtering
            biotech_s5_check = lab_df[
                (lab_df['department'] == 'Biotechnology') & (lab_df['semester'] == 5)
            ]
            logger.info(f"Found {len(biotech_s5_check)} Biotechnology S5 lab entries to remove")
            
            # Filter out Biotechnology S5 entries (we'll regenerate these)
            non_biotech_s5_lab = lab_df[
                ~((lab_df['department'] == 'Biotechnology') & (lab_df['semester'] == 5))
            ]
            self.existing_constraints['lab'] = non_biotech_s5_lab
            logger.info(f"Loaded {len(non_biotech_s5_lab)} existing lab constraint entries")
            logger.info(f"Removed {len(lab_df) - len(non_biotech_s5_lab)} existing Biotechnology S5 lab entries")
        except Exception as e:
            logger.error(f"Failed to load existing lab timetable: {e}")
            self.existing_constraints['lab'] = pd.DataFrame()
        
        # Load existing theory timetable
        try:
            theory_df = pd.read_csv(self.existing_theory_timetable)
            logger.info(f"Total theory entries loaded: {len(theory_df)}")
            
            # Check Biotechnology S5 entries before filtering
            biotech_s5_theory_check = theory_df[
                (theory_df['department'] == 'Biotechnology') & (theory_df['semester'] == 5)
            ]
            logger.info(f"Found {len(biotech_s5_theory_check)} Biotechnology S5 theory entries to remove")
            
            # Filter out Biotechnology S5 entries (we'll regenerate these)
            non_biotech_s5_theory = theory_df[
                ~((theory_df['department'] == 'Biotechnology') & (theory_df['semester'] == 5))
            ]
            self.existing_constraints['theory'] = non_biotech_s5_theory
            logger.info(f"Loaded {len(non_biotech_s5_theory)} existing theory constraint entries")
            logger.info(f"Removed {len(theory_df) - len(non_biotech_s5_theory)} existing Biotechnology S5 theory entries")
        except Exception as e:
            logger.error(f"Failed to load existing theory timetable: {e}")
            self.existing_constraints['theory'] = pd.DataFrame()
    
    def regenerate(self):
        """Regenerate Biotechnology 5th semester timetables."""
        logger.info("="*80)
        logger.info("STARTING SELECTIVE BIOTECHNOLOGY S5 REGENERATION")
        logger.info("="*80)
        
        try:
            # Create modified combined scheduler
            scheduler = CombinedScheduler(self.filtered_course_file, self.room_file)
            
            # Inject existing constraints into the scheduler
            self._inject_existing_constraints(scheduler)
            
            # Generate new schedule for Biotechnology S5
            success = scheduler.generate_combined_schedule()
            
            if success:
                logger.info("✅ Biotechnology S5 regeneration successful!")
                
                # Merge with existing timetables
                merged_success = self._merge_with_existing_timetables(scheduler)
                
                if merged_success:
                    logger.info("✅ Successfully merged new Biotechnology S5 timetables with existing schedules!")
                    return True
                else:
                    logger.error("❌ Failed to merge new timetables with existing schedules")
                    return False
            else:
                logger.error("❌ Biotechnology S5 regeneration failed!")
                return False
                
        except Exception as e:
            logger.error(f"❌ Regeneration failed with error: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
        finally:
            # Clean up temporary file
            if self.filtered_course_file and os.path.exists(self.filtered_course_file):
                os.remove(self.filtered_course_file)
                logger.info(f"Cleaned up temporary file: {self.filtered_course_file}")
    
    def _inject_existing_constraints(self, scheduler):
        """Inject existing timetable constraints into the scheduler."""
        logger.info("Injecting existing timetable constraints...")
        
        # 1. Pre-populate global room registry with existing schedules to prevent double bookings
        self._preload_global_room_registry(scheduler)
        
        # Store existing constraints in the scheduler for use during constraint application
        scheduler.existing_constraints = self.existing_constraints
        
        # Extend the scheduler with constraint application methods
        original_apply_unified_constraints = scheduler._apply_unified_constraints
        
        def enhanced_apply_unified_constraints(model, lab_variables, theory_variables):
            """Enhanced constraint application that includes existing schedule constraints."""
            # Apply original constraints
            constraints_applied = original_apply_unified_constraints(model, lab_variables, theory_variables)
            
            # Apply existing schedule constraints
            existing_constraints_applied = self._apply_existing_schedule_constraints(
                scheduler, model, lab_variables, theory_variables
            )
            
            logger.info(f"Applied {existing_constraints_applied} existing schedule constraints")
            return constraints_applied + existing_constraints_applied
        
        # Replace the method
        scheduler._apply_unified_constraints = enhanced_apply_unified_constraints
        
        logger.info("Existing constraints injected successfully")
    
    def _preload_global_room_registry(self, scheduler):
        """Pre-populate the global room registry with existing schedules to prevent double bookings."""
        logger.info("Pre-loading global room registry with existing schedules...")
        
        # Day name normalization mapping (must match combined_scheduler._normalize_day_name)
        day_normalization = {
            'monday': 'monday', 'tuesday': 'tuesday', 'wed': 'wed', 
            'thur': 'thur', 'fri': 'fri', 'saturday': 'saturday',
            'wednesday': 'wed', 'thursday': 'thur'
        }
        
        rooms_preloaded = 0
        
        # Pre-load existing lab schedules
        if 'lab' in self.existing_constraints and not self.existing_constraints['lab'].empty:
            lab_df = self.existing_constraints['lab']
            for _, row in lab_df.iterrows():
                day = str(row['day']).lower().strip()
                session_name = str(row['session_name']).strip()
                room_id = int(row['room_id'])
                
                # Normalize day name
                normalized_day = day_normalization.get(day, day.upper())
                
                # Convert lab session to time slot for registry
                # Lab sessions map to multiple time slots, so we need to register for all affected slots
                lab_session_mapping = {
                    'L1': ['8:00 - 8:50', '9:00 - 9:50'],
                    'L2': ['10:00 - 10:50', '11:00 - 11:50'], 
                    'L3': ['12:00 - 12:50', '1:00 - 1:50'],
                    'L4': ['2:00 - 2:50', '3:00 - 3:50'],
                    'L5': ['4:00 - 4:50', '5:00 - 5:50'],
                    'L6': ['6:00 - 6:50', '7:00 - 7:50']
                }
                
                if session_name in lab_session_mapping:
                    for time_slot in lab_session_mapping[session_name]:
                        session_info = {
                            'course_code': row.get('course_code', 'EXISTING_LAB'),
                            'schedule_type': 'lab',
                            'department': row.get('department', 'EXISTING'),
                            'from_existing': True
                        }
                        scheduler._register_room_usage(normalized_day, time_slot, room_id, session_info)
                        rooms_preloaded += 1
        
        # Pre-load existing theory schedules  
        if 'theory' in self.existing_constraints and not self.existing_constraints['theory'].empty:
            theory_df = self.existing_constraints['theory']
            for _, row in theory_df.iterrows():
                day = str(row['day']).lower().strip()
                time_slot = str(row['time_slot']).strip()
                room_id = int(row['room_id'])
                
                # Normalize day name
                normalized_day = day_normalization.get(day, day.upper())
                
                session_info = {
                    'course_code': row.get('course_code', 'EXISTING_THEORY'),
                    'schedule_type': 'theory',
                    'department': row.get('department', 'EXISTING'),
                    'from_existing': True
                }
                scheduler._register_room_usage(normalized_day, time_slot, room_id, session_info)
                rooms_preloaded += 1
        
        logger.info(f"Pre-loaded {rooms_preloaded} existing room occupancies into global registry")
        
        # Log sample of what was loaded for debugging
        sample_count = min(10, len(scheduler.global_room_registry))
        if sample_count > 0:
            sample_keys = list(scheduler.global_room_registry.keys())[:sample_count]
            logger.info(f"Sample preloaded room registrations: {sample_keys}")
            
            # Debug: Check if specific conflicting slots are in the registry
            test_slots = [
                ('FRIDAY', '2:00 - 2:50', 1),
                ('FRIDAY', '8:00 - 8:50', 1), 
                ('TUESDAY', '10:00 - 10:50', 1),
                ('THURSDAY', '2:00 - 2:50', 1)
            ]
            for day, time_slot, room_id in test_slots:
                key = (day, time_slot, room_id)
                if key in scheduler.global_room_registry:
                    session = scheduler.global_room_registry[key]
                    logger.info(f"✅ Verified registry entry: {key} -> {session.get('course_code', 'UNKNOWN')}")
                else:
                    logger.warning(f"❌ Missing registry entry: {key}")
        
        # Also verify the day normalization is working correctly
        logger.info(f"Total registry size: {len(scheduler.global_room_registry)} entries")
    
    def _apply_existing_schedule_constraints(self, scheduler, model, lab_variables, theory_variables):
        """Apply constraints based on existing schedules to prevent conflicts."""
        logger.info("Applying existing schedule constraints...")
        constraints_applied = 0
        
        # Apply lab constraints
        if 'lab' in self.existing_constraints and not self.existing_constraints['lab'].empty:
            constraints_applied += self._apply_existing_lab_constraints(
                scheduler, model, lab_variables
            )
        
        # Apply theory constraints
        if 'theory' in self.existing_constraints and not self.existing_constraints['theory'].empty:
            constraints_applied += self._apply_existing_theory_constraints(
                scheduler, model, theory_variables
            )
        
        logger.info(f"Applied {constraints_applied} existing schedule constraints")
        return constraints_applied
    
    def _apply_existing_lab_constraints(self, scheduler, model, lab_variables):
        """Apply robust constraints based on existing lab schedules to prevent double bookings."""
        logger.info("Applying existing lab schedule constraints to prevent room conflicts...")
        constraints_applied = 0
        
        existing_lab_df = self.existing_constraints['lab']
        if existing_lab_df.empty:
            logger.info("No existing lab constraints to apply")
            return 0
        
        # Create comprehensive room-time occupancy mapping
        occupied_slots = set()  # Set of (day_name, session_name, room_id) tuples
        
        # Day name normalization mapping (must match combined_scheduler._normalize_day_name)
        day_normalization = {
            'monday': 'monday', 'tuesday': 'tuesday', 'wed': 'wed', 
            'thur': 'thur', 'fri': 'fri', 'saturday': 'saturday',
            'wednesday': 'wed', 'thursday': 'thur'
        }
        
        # Build set of occupied room-time slots
        for _, row in existing_lab_df.iterrows():
            day = str(row['day']).lower().strip()
            session_name = str(row['session_name']).strip()
            room_id = int(row['room_id'])
            
            # Normalize day name
            normalized_day = day_normalization.get(day, day.lower())
            occupied_slots.add((normalized_day, session_name, room_id))
        
        logger.info(f"Found {len(occupied_slots)} occupied lab room-time slots")
        
        # Apply blocking constraints for each occupied slot
        blocked_assignments = 0
        
        # For debugging: log sample occupied slots
        sample_slots = list(occupied_slots)[:5]
        logger.info(f"Sample occupied slots: {sample_slots}")
        
        for teacher_id in lab_variables:
            for course_instance_id in lab_variables[teacher_id]:
                # Get department info for this course to determine day pattern
                dept_name = "Biotechnology"  # We know we're dealing with Biotechnology S5
                semester = 5
                
                # Get department-specific days for Biotechnology (Tuesday-Saturday pattern)
                dept_days = ['tuesday', 'wed', 'thur', 'fri', 'saturday']
                
                # Check each day for this course
                for day_idx in range(len(dept_days)):
                    if day_idx in lab_variables[teacher_id][course_instance_id]:
                        day_name = dept_days[day_idx]
                        
                        for session_name in lab_variables[teacher_id][course_instance_id][day_idx]:
                            for room_id in lab_variables[teacher_id][course_instance_id][day_idx][session_name]:
                                # Check if this room-time slot is already occupied
                                if (day_name, session_name, room_id) in occupied_slots:
                                    # Block this assignment - room is already occupied
                                    var = lab_variables[teacher_id][course_instance_id][day_idx][session_name][room_id]
                                    model.Add(var == 0)
                                    constraints_applied += 1
                                    blocked_assignments += 1
        
        logger.info(f"Applied {constraints_applied} existing lab room occupancy constraints")
        logger.info(f"Blocked {blocked_assignments} potential conflicting lab assignments")
        return constraints_applied
    
    def _apply_existing_theory_constraints(self, scheduler, model, theory_variables):
        """Apply robust constraints based on existing theory schedules to prevent room conflicts."""
        logger.info("Applying existing theory schedule constraints to prevent room conflicts...")
        constraints_applied = 0
        
        existing_theory_df = self.existing_constraints['theory']
        if existing_theory_df.empty:
            logger.info("No existing theory constraints to apply")
            return 0
        
        # Create comprehensive room-time occupancy mapping for theory
        occupied_room_slots = {}  # Maps (day_name, slot_idx, room_id) -> number of sessions
        
        # Day name normalization mapping (must match combined_scheduler._normalize_day_name)
        day_normalization = {
            'monday': 'monday', 'tuesday': 'tuesday', 'wed': 'wed', 
            'thur': 'thur', 'fri': 'fri', 'saturday': 'saturday',
            'wednesday': 'wed', 'thursday': 'thur'
        }
        
        # Build mapping of occupied room-time slots
        for _, row in existing_theory_df.iterrows():
            day = str(row['day']).lower().strip()
            slot_idx = int(row['slot_index'])
            room_id = int(row['room_id'])
            
            # Normalize day name
            normalized_day = day_normalization.get(day, day.lower())
            
            slot_key = (normalized_day, slot_idx, room_id)
            if slot_key not in occupied_room_slots:
                occupied_room_slots[slot_key] = 0
            occupied_room_slots[slot_key] += 1
        
        logger.info(f"Found {len(occupied_room_slots)} occupied theory room-time slots")
        
        # Calculate room utilization to understand availability
        total_room_usage = 0
        for (day_name, slot_idx, room_id), usage_count in occupied_room_slots.items():
            total_room_usage += usage_count
            if usage_count > 1:
                logger.warning(f"Double booking detected in existing schedule: {day_name} slot {slot_idx} room {room_id} ({usage_count} sessions)")
        
        # Apply constraints to reduce room conflicts
        # Since theory uses group-based variables, we need a different approach
        
        # Method 1: Reduce the effective room capacity in highly utilized slots
        high_utilization_slots = set()
        for (day_name, slot_idx, room_id), usage_count in occupied_room_slots.items():
            high_utilization_slots.add((day_name, slot_idx))
        
        # Method 2: Add constraint to limit concurrent group scheduling in high-usage time slots
        for group_name in theory_variables:
            # Get department info for this group to determine day pattern
            dept_name = group_name.split('_S')[0] if '_S' in group_name else "Computer Science & Engineering"
            semester = None
            if '_S' in group_name:
                try:
                    semester_part = group_name.split('_S')[1].split('_G')[0]
                    semester = int(semester_part)
                except (ValueError, IndexError):
                    pass
            
            # Get department-specific days
            dept_days = scheduler._get_days_for_department(dept_name, semester)
            
            # Apply constraints based on existing room usage
            for day_idx in range(len(dept_days)):
                if day_idx in theory_variables[group_name]:
                    day_name = dept_days[day_idx]
                    
                    for slot_idx in theory_variables[group_name][day_idx]:
                        # Count how many rooms are already used at this time slot
                        rooms_used_in_slot = sum(1 for (d, s, r) in occupied_room_slots.keys() 
                                               if d == day_name and s == slot_idx)
                        
                        total_available_rooms = len(scheduler.theory_room_ids)
                        
                        # If most rooms are already occupied, reduce priority for this slot
                        if rooms_used_in_slot >= total_available_rooms * 0.8:  # 80% utilization threshold
                            # Add penalty constraint - discourage scheduling in highly utilized slots
                            group_var = theory_variables[group_name][day_idx][slot_idx]
                            
                            # This is a soft constraint through the CP-SAT solver's objective function
                            # We can't directly access the objective here, so we use a capacity constraint
                            
                            # For now, we'll use a hard constraint if utilization is at 100%
                            if rooms_used_in_slot >= total_available_rooms:
                                model.Add(group_var == 0)  # Block completely full slots
                                constraints_applied += 1
                                logger.debug(f"Blocked {group_name} from fully occupied slot: {day_name} slot {slot_idx}")
        
        # Method 3: Global room capacity constraint
        # For each time slot, ensure total groups don't exceed available room capacity
        for day_idx in range(5):  # Assuming max 5 days
            day_names = ['monday', 'tuesday', 'wed', 'thur', 'fri']
            if day_idx < len(day_names):
                day_name = day_names[day_idx]
                
                for slot_idx in range(scheduler.num_theory_slots):
                    # Count rooms already used by existing schedules
                    existing_rooms_used = sum(1 for (d, s, r) in occupied_room_slots.keys() 
                                            if d == day_name and s == slot_idx)
                    
                    # Collect all new groups that could use this slot
                    potential_new_groups = []
                    for group_name in theory_variables:
                        group_dept = group_name.split('_S')[0] if '_S' in group_name else "Computer Science & Engineering"
                        group_semester = None
                        if '_S' in group_name:
                            try:
                                semester_part = group_name.split('_S')[1].split('_G')[0]
                                group_semester = int(semester_part)
                            except (ValueError, IndexError):
                                pass
                        
                        group_dept_days = scheduler._get_days_for_department(group_dept, group_semester)
                        
                        if (day_idx < len(group_dept_days) and 
                            day_idx in theory_variables[group_name] and
                            slot_idx in theory_variables[group_name][day_idx]):
                            potential_new_groups.append(theory_variables[group_name][day_idx][slot_idx])
                    
                    if potential_new_groups and existing_rooms_used > 0:
                        # Limit new assignments based on remaining capacity
                        remaining_capacity = max(0, len(scheduler.theory_room_ids) - existing_rooms_used)
                        if remaining_capacity < len(potential_new_groups):
                            model.Add(sum(potential_new_groups) <= remaining_capacity)
                            constraints_applied += 1
                            logger.debug(f"Applied capacity constraint for {day_name} slot {slot_idx}: {remaining_capacity} rooms available for {len(potential_new_groups)} potential groups")
        
        logger.info(f"Applied {constraints_applied} existing theory room occupancy constraints")
        logger.info(f"Total existing theory room usage: {total_room_usage} sessions across {len(occupied_room_slots)} room-time slots")
        return constraints_applied
    
    def _merge_with_existing_timetables(self, scheduler):
        """Merge newly generated Biotechnology S5 timetables with existing timetables."""
        logger.info("Merging new Biotechnology S5 timetables with existing schedules...")
        
        try:
            # Find the generated lab and theory schedules
            lab_csv_path = os.path.join(scheduler.output_dir, 'combined_lab_schedule.csv')
            theory_csv_path = os.path.join(scheduler.output_dir, 'combined_theory_schedule.csv')
            
            if not os.path.exists(lab_csv_path) or not os.path.exists(theory_csv_path):
                logger.error("Generated schedule files not found")
                return False
            
            # Load new schedules
            new_lab_df = pd.read_csv(lab_csv_path)
            new_theory_df = pd.read_csv(theory_csv_path)
            
            logger.info(f"New lab schedule has {len(new_lab_df)} entries")
            logger.info(f"New theory schedule has {len(new_theory_df)} entries")
            
            # Merge with existing schedules
            merged_lab_df = pd.concat([
                self.existing_constraints['lab'],
                new_lab_df
            ], ignore_index=True)
            
            merged_theory_df = pd.concat([
                self.existing_constraints['theory'],
                new_theory_df
            ], ignore_index=True)
            
            # Sort by department and semester for better organization
            merged_lab_df = merged_lab_df.sort_values(['department', 'semester', 'day', 'session_name'])
            merged_theory_df = merged_theory_df.sort_values(['department', 'semester', 'day', 'time_slot'])
            
            # Create backup of original files
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # Backup original lab timetable
            lab_backup = f"{self.existing_lab_timetable}.backup_{timestamp}"
            shutil.copy2(self.existing_lab_timetable, lab_backup)
            logger.info(f"Backed up original lab timetable to: {lab_backup}")
            
            # Backup original theory timetable
            theory_backup = f"{self.existing_theory_timetable}.backup_{timestamp}"
            shutil.copy2(self.existing_theory_timetable, theory_backup)
            logger.info(f"Backed up original theory timetable to: {theory_backup}")
            
            # Write merged timetables
            merged_lab_df.to_csv(self.existing_lab_timetable, index=False)
            merged_theory_df.to_csv(self.existing_theory_timetable, index=False)
            
            logger.info(f"✅ Merged lab timetable written with {len(merged_lab_df)} total entries")
            logger.info(f"✅ Merged theory timetable written with {len(merged_theory_df)} total entries")
            
            # Generate JSON output as well
            self._save_json_output(merged_lab_df, merged_theory_df, timestamp)
            
            # Log statistics
            biotech_s5_lab_count = len(merged_lab_df[
                (merged_lab_df['department'] == 'Biotechnology') & 
                (merged_lab_df['semester'] == 5)
            ])
            biotech_s5_theory_count = len(merged_theory_df[
                (merged_theory_df['department'] == 'Biotechnology') & 
                (merged_theory_df['semester'] == 5)
            ])
            
            logger.info(f"📊 Final Biotechnology S5 entries: {biotech_s5_lab_count} lab, {biotech_s5_theory_count} theory")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to merge timetables: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False

    def _save_json_output(self, merged_lab_df, merged_theory_df, timestamp):
        """Save merged timetables in JSON format similar to combined_scheduler.py."""
        logger.info("Generating JSON output for merged timetables...")
        
        try:
            # Convert DataFrames to list of dictionaries
            lab_schedule = merged_lab_df.to_dict('records')
            theory_schedule = merged_theory_df.to_dict('records')
            
            # Define JSON helper functions
            def convert_numpy_types(obj):
                """Convert numpy types to native Python types for JSON serialization."""
                if isinstance(obj, np.integer):
                    return int(obj)
                elif isinstance(obj, np.floating):
                    if np.isnan(obj) or np.isinf(obj):
                        return None
                    return float(obj)
                elif isinstance(obj, np.ndarray):
                    return obj.tolist()
                elif isinstance(obj, (np.bool_, bool)):
                    return bool(obj)
                elif obj != obj:  # Check for NaN (NaN != NaN is True)
                    return None
                elif obj == float('inf') or obj == float('-inf'):
                    return None
                return obj

            def clean_data(data):
                """Recursively clean data by replacing NaN/None values."""
                if isinstance(data, list):
                    return [clean_data(item) for item in data]
                elif isinstance(data, dict):
                    cleaned = {}
                    for key, value in data.items():
                        cleaned[key] = clean_data(value)
                    return cleaned
                elif pd.isna(data) or data != data:  # Check for NaN
                    return None
                elif isinstance(data, (np.floating, float)) and (np.isnan(data) or np.isinf(data)):
                    return None
                else:
                    return data

            # Clean the schedules
            clean_lab_schedule = clean_data(lab_schedule)
            clean_theory_schedule = clean_data(theory_schedule)

            # Save JSON files
            lab_json_path = self.existing_lab_timetable.replace('.csv', f'_{timestamp}.json')
            with open(lab_json_path, 'w', encoding='utf-8') as f:
                json.dump(clean_lab_schedule, f, indent=2, default=convert_numpy_types)
            logger.info(f"✅ Merged lab schedule JSON saved to: {lab_json_path}")

            theory_json_path = self.existing_theory_timetable.replace('.csv', f'_{timestamp}.json')
            with open(theory_json_path, 'w', encoding='utf-8') as f:
                json.dump(clean_theory_schedule, f, indent=2, default=convert_numpy_types)
            logger.info(f"✅ Merged theory schedule JSON saved to: {theory_json_path}")
            
            # Generate summary report
            self._generate_json_summary(clean_lab_schedule, clean_theory_schedule, timestamp)
            
        except Exception as e:
            logger.error(f"Failed to save JSON output: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")

    def _generate_json_summary(self, lab_schedule, theory_schedule, timestamp):
        """Generate a JSON summary similar to the combined scheduler."""
        logger.info("Generating merged schedule summary...")
        
        try:
            summary_path = self.existing_lab_timetable.replace('.csv', f'_summary_{timestamp}.txt')
            
            with open(summary_path, 'w', encoding='utf-8') as f:
                f.write("MERGED SCHEDULE SUMMARY (After Biotechnology S5 Regeneration)\n")
                f.write("="*70 + "\n\n")
                
                total_sessions = len(lab_schedule) + len(theory_schedule)
                f.write(f"Total scheduled sessions: {total_sessions}\n")
                f.write(f"  Lab sessions: {len(lab_schedule)}\n")
                f.write(f"  Theory sessions: {len(theory_schedule)}\n\n")
                
                # Biotechnology S5 specific analysis
                biotech_s5_lab = [s for s in lab_schedule 
                                 if s.get('department') == 'Biotechnology' and s.get('semester') == 5]
                biotech_s5_theory = [s for s in theory_schedule 
                                   if s.get('department') == 'Biotechnology' and s.get('semester') == 5]
                
                f.write("BIOTECHNOLOGY S5 REGENERATION RESULTS:\n")
                f.write(f"  New Biotechnology S5 lab sessions: {len(biotech_s5_lab)}\n")
                f.write(f"  New Biotechnology S5 theory sessions: {len(biotech_s5_theory)}\n")
                
                if biotech_s5_lab:
                    biotech_courses = set(s.get('course_code', 'Unknown') for s in biotech_s5_lab)
                    f.write(f"  Biotechnology S5 lab courses: {', '.join(sorted(biotech_courses))}\n")
                
                if biotech_s5_theory:
                    biotech_theory_courses = set(s.get('course_code', 'Unknown') for s in biotech_s5_theory)
                    f.write(f"  Biotechnology S5 theory courses: {', '.join(sorted(biotech_theory_courses))}\n")
                
                f.write("\n")
                
                # Overall statistics by department
                dept_counts = defaultdict(lambda: {'lab': 0, 'theory': 0})
                
                for session in lab_schedule:
                    dept = session.get('department', 'Unknown')
                    dept_counts[dept]['lab'] += 1
                
                for session in theory_schedule:
                    dept = session.get('department', 'Unknown')
                    dept_counts[dept]['theory'] += 1
                
                f.write("SESSIONS BY DEPARTMENT:\n")
                for dept in sorted(dept_counts.keys()):
                    lab_count = dept_counts[dept]['lab']
                    theory_count = dept_counts[dept]['theory']
                    total_dept = lab_count + theory_count
                    f.write(f"  {dept}: {total_dept} total ({lab_count} lab, {theory_count} theory)\n")
                
                # Teachers with assignments
                lab_teachers = set(str(s.get('teacher_id', '')) for s in lab_schedule)
                theory_teachers = set(str(s.get('teacher_id', '')) for s in theory_schedule)
                all_teachers = lab_teachers | theory_teachers
                
                f.write(f"\nTeachers with assignments: {len(all_teachers)}\n")
                f.write(f"  Lab only: {len(lab_teachers - theory_teachers)}\n")
                f.write(f"  Theory only: {len(theory_teachers - lab_teachers)}\n")
                f.write(f"  Both lab and theory: {len(lab_teachers & theory_teachers)}\n")
                
                # Room utilization
                lab_rooms = set(str(s.get('room_id', '')) for s in lab_schedule)
                theory_rooms = set(str(s.get('room_id', '')) for s in theory_schedule)
                
                f.write(f"\nRoom utilization:\n")
                f.write(f"  Lab rooms used: {len(lab_rooms)}\n")
                f.write(f"  Theory rooms used: {len(theory_rooms)}\n")
                f.write(f"  Total unique rooms: {len(lab_rooms | theory_rooms)}\n")
            
            logger.info(f"✅ Merged schedule summary saved to: {summary_path}")
            
        except Exception as e:
            logger.error(f"Failed to generate summary: {e}")


def main():
    """Main entry point for selective regeneration."""
    # File paths
    course_file = "data/final_v4.csv"
    room_file = "data/block_wise/techlongue.csv"
    existing_lab_timetable = "data/timetable/combined_schedule_lab.csv"
    existing_theory_timetable = "data/timetable/combined_schedule_theory.csv"
    
    # Verify files exist
    for file_path in [course_file, room_file, existing_lab_timetable, existing_theory_timetable]:
        if not os.path.exists(file_path):
            logger.error(f"Required file not found: {file_path}")
            return False
    
    logger.info("🚀 Starting Selective Biotechnology S5 Regeneration...")
    logger.info(f"📁 Course file: {course_file}")
    logger.info(f"🏢 Room file: {room_file}")
    logger.info(f"🧪 Existing lab timetable: {existing_lab_timetable}")
    logger.info(f"📚 Existing theory timetable: {existing_theory_timetable}")
    
    # Create regenerator and run
    regenerator = SelectiveBiotechS5Regenerator(
        course_file=course_file,
        room_file=room_file,
        existing_lab_timetable=existing_lab_timetable,
        existing_theory_timetable=existing_theory_timetable
    )
    
    success = regenerator.regenerate()
    
    if success:
        logger.info("🎉 Selective regeneration completed successfully!")
        logger.info("💡 The updated timetables now include regenerated Biotechnology 5th semester schedules")
        logger.info("💡 Original timetables have been backed up with timestamp suffix")
        return True
    else:
        logger.error("💥 Selective regeneration failed!")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1) 