#!/usr/bin/env python3
"""
Group Constraint Verification Script

This script verifies that the timetable output meets the group-based scheduling constraints:
1. Each course instance gets its required number of hours
2. No overlap between groups in the same semester (student can take courses from different groups)
3. Teachers don't appear more than once in a group
4. Each group gets the correct number of timeslots

Usage:
    python verify_groups.py [path_to_schedule_csv]

If no path is provided, it looks for the most recent schedule output.
"""

import os
import sys
import glob
import pandas as pd
from collections import defaultdict
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("GroupVerifier")

class GroupConstraintVerifier:
    def __init__(self, schedule_path=None):
        """Initialize the verifier with a schedule file path."""
        self.schedule_path = schedule_path
        self.schedule_df = None
        self.course_df = None
        self.issues = []
        
        # If no path provided, find the most recent output
        if not self.schedule_path:
            self._find_latest_schedule()
            
        # Load the schedule
        self._load_schedule()
        
        # Load the original course data
        self._load_course_data()
    
    def _find_latest_schedule(self):
        """Find the most recent schedule output directory."""
        base_dir = os.path.dirname(os.path.abspath(__file__))
        output_dirs = glob.glob(os.path.join(base_dir, "output", "schedule_*"))
        
        if not output_dirs:
            logger.error("No schedule output directories found")
            sys.exit(1)
        
        # Sort by modification time (most recent first)
        latest_dir = max(output_dirs, key=os.path.getmtime)
        self.schedule_path = os.path.join(latest_dir, "schedule.csv")
        logger.info(f"Using latest schedule: {self.schedule_path}")
    
    def _load_schedule(self):
        """Load the schedule CSV file."""
        try:
            self.schedule_df = pd.read_csv(self.schedule_path)
            logger.info(f"Loaded schedule with {len(self.schedule_df)} assignments")
        except Exception as e:
            logger.error(f"Error loading schedule: {str(e)}")
            sys.exit(1)
    
    def _load_course_data(self):
        """Load the original course data to verify hour requirements."""
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            course_path = os.path.join(base_dir, "data", "cse.csv")
            
            if os.path.exists(course_path):
                self.course_df = pd.read_csv(course_path)
                logger.info(f"Loaded course data with {len(self.course_df)} entries")
            else:
                logger.warning(f"Course data file not found at {course_path}")
                self.course_df = None
        except Exception as e:
            logger.warning(f"Error loading course data: {str(e)}")
            self.course_df = None
    
    def run_verification(self):
        """Run all verification checks."""
        logger.info("Starting verification of group constraints...")
        
        # Run each verification check
        self.verify_teacher_uniqueness()
        self.verify_no_group_overlap()
        self.verify_course_hours()
        self.verify_group_timeslots()
        
        # Report results
        if not self.issues:
            logger.info("✅ Verification PASSED: All group constraints are satisfied!")
            return True
        else:
            logger.error(f"❌ Verification FAILED: Found {len(self.issues)} issues:")
            for i, issue in enumerate(self.issues, 1):
                logger.error(f"  {i}. {issue}")
            return False
    
    def verify_teacher_uniqueness(self):
        """Verify that no teacher appears more than once in the same group."""
        logger.info("Checking teacher uniqueness in groups...")
        
        # Group by group_name and teacher_id
        grouped = self.schedule_df.groupby('group_name')['teacher_id'].apply(set)
        teacher_counts = {}
        
        for group_name, teacher_set in grouped.items():
            # Get assignments for this group
            group_df = self.schedule_df[self.schedule_df['group_name'] == group_name]
            
            # Check for each teacher how many unique course codes they have in this group
            teacher_course_counts = {}
            for teacher_id in teacher_set:
                teacher_df = group_df[group_df['teacher_id'] == teacher_id]
                unique_courses = teacher_df['course_code'].unique()
                teacher_course_counts[teacher_id] = len(unique_courses)
                
                # If a teacher has multiple courses in the same group, flag it
                if len(unique_courses) > 1:
                    courses = ", ".join(unique_courses)
                    self.issues.append(
                        f"Teacher {teacher_id} teaches multiple courses in group {group_name}: {courses}"
                    )
        
        if not self.issues:
            logger.info("✅ Teacher uniqueness check passed - no teacher appears more than once in any group")
    
    def verify_no_group_overlap(self):
        """Verify that groups in the same semester don't have overlapping timeslots."""
        logger.info("Checking for group overlap within semesters...")
        
        # Track timeslot usage by department/semester
        dept_sem_timeslots = defaultdict(lambda: defaultdict(set))
        
        # Collect all timeslots used by each group
        for _, row in self.schedule_df.iterrows():
            dept = row['department_group']
            semester = row['semester_group']
            day = row['day']
            slot = row['slot_index']
            group_name = row['group_name']
            
            # Add this timeslot to the group's usage
            dept_sem_timeslots[(dept, semester)][(day, slot)].add(group_name)
        
        # Check for overlaps
        overlap_count = 0
        for (dept, semester), timeslot_usage in dept_sem_timeslots.items():
            for (day, slot), groups in timeslot_usage.items():
                if len(groups) > 1:
                    overlap_count += 1
                    groups_str = ", ".join(groups)
                    self.issues.append(
                        f"Overlap in {dept} Semester {semester}: {day} slot {slot} used by multiple groups: {groups_str}"
                    )
        
        if overlap_count == 0:
            logger.info("✅ No group overlap check passed - groups in the same semester don't overlap")
        else:
            logger.error(f"❌ Found {overlap_count} timeslot overlaps between groups in the same semester")
    
    def verify_course_hours(self):
        """Verify that each course instance gets its required number of hours."""
        logger.info("Checking course hour allocations...")
        
        # Get all unique course instances
        instances = self.schedule_df[['course_instance_id', 'course_code', 'teacher_id']].drop_duplicates()
        
        # For each instance, check how many hours are allocated
        hours_match = 0
        hours_mismatch = 0
        
        for _, instance in instances.iterrows():
            instance_id = instance['course_instance_id']
            course_code = instance['course_code']
            teacher_id = instance['teacher_id']
            
            # Count assignments for this instance
            instance_df = self.schedule_df[self.schedule_df['course_instance_id'] == instance_id]
            lecture_count = len(instance_df[instance_df['slot_type'] == 'Lecture'])
            tutorial_count = len(instance_df[instance_df['slot_type'] == 'Tutorial'])
            
            # If we have course data, check the required hours
            required_lecture = 0
            required_tutorial = 0
            
            if self.course_df is not None:
                # Find the matching row in the course data
                course_row = self.course_df[self.course_df['id'] == int(instance_id)]
                if not course_row.empty:
                    required_lecture = course_row.iloc[0]['lecture_hours']
                    required_tutorial = course_row.iloc[0]['tutorial_hours']
                    
                    # Check if allocated hours match required hours
                    if lecture_count == required_lecture and tutorial_count == required_tutorial:
                        hours_match += 1
                        logger.info(f"✓ Instance {instance_id} ({course_code}, Teacher {teacher_id}): "
                                    f"{lecture_count}/{required_lecture}L + {tutorial_count}/{required_tutorial}T hours")
                    else:
                        hours_mismatch += 1
                        mismatch_msg = (f"Instance {instance_id} ({course_code}, Teacher {teacher_id}): "
                                       f"Got {lecture_count}/{required_lecture}L + {tutorial_count}/{required_tutorial}T hours")
                        logger.warning(f"⚠️ {mismatch_msg}")
                        self.issues.append(mismatch_msg)
                else:
                    logger.info(f"Instance {instance_id} ({course_code}, Teacher {teacher_id}): "
                                f"{lecture_count}L + {tutorial_count}T hours (requirements unknown)")
            else:
                logger.info(f"Instance {instance_id} ({course_code}, Teacher {teacher_id}): "
                            f"{lecture_count}L + {tutorial_count}T hours (no course data available)")
        
        if self.course_df is not None:
            logger.info(f"Hour requirements: {hours_match} instances match, {hours_mismatch} instances mismatch")
    
    def verify_group_timeslots(self):
        """Verify that each group gets the correct number of timeslots."""
        logger.info("Checking group timeslot allocations...")
        
        # Count unique timeslots per group
        group_timeslots = {}
        for group_name, group_df in self.schedule_df.groupby('group_name'):
            # Count unique day+slot combinations
            unique_timeslots = set()
            for _, row in group_df.iterrows():
                unique_timeslots.add((row['day'], row['slot_index']))
            
            group_timeslots[group_name] = len(unique_timeslots)
            
            # Calculate required timeslots for this group
            if self.course_df is not None:
                # Get all course instances in this group
                course_instances = group_df['course_instance_id'].unique()
                
                # Find the max hours among these instances
                max_hours = 0
                for instance_id in course_instances:
                    course_row = self.course_df[self.course_df['id'] == int(instance_id)]
                    if not course_row.empty:
                        theory_hours = course_row.iloc[0]['lecture_hours'] + course_row.iloc[0]['tutorial_hours']
                        max_hours = max(max_hours, theory_hours)
                
                if max_hours > 0:
                    logger.info(f"Group {group_name}: {len(unique_timeslots)} unique timeslots (required: {max_hours} based on max course hours)")
                    
                    # Check if number of timeslots matches required hours
                    if len(unique_timeslots) < max_hours:
                        self.issues.append(f"Group {group_name} has {len(unique_timeslots)} timeslots but requires {max_hours} based on course hours")
                else:
                    logger.info(f"Group {group_name}: {len(unique_timeslots)} unique timeslots")
            else:
                logger.info(f"Group {group_name}: {len(unique_timeslots)} unique timeslots")

def main():
    """Main function to run verification."""
    # Get schedule path from command line if provided
    schedule_path = sys.argv[1] if len(sys.argv) > 1 else None
    
    # Create and run verifier
    verifier = GroupConstraintVerifier(schedule_path)
    result = verifier.run_verification()
    
    # Exit with appropriate code
    sys.exit(0 if result else 1)

if __name__ == "__main__":
    main() 