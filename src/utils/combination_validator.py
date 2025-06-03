import os
import pandas as pd
import logging
import json
import numpy as np
from collections import defaultdict

class CourseSelectionValidator:
    """
    Validates whether the generated timetable allows all students to select
    a valid combination of required courses without time conflicts.
    
    This validator checks if 700 students can each find a combination of all 5
    required courses (one teacher per course) without scheduling conflicts.
    """
    
    def __init__(self, schedule_path, semester=5, student_count=700):
        """
        Initialize the validator with schedule data.
        
        Args:
            schedule_path: Path to the CSV schedule file
            semester: The semester to validate (default: 5)
            student_count: Number of students to accommodate (default: 700)
        """
        self.logger = logging.getLogger(__name__)
        self.schedule_path = schedule_path
        self.semester = semester
        self.student_count = student_count
        self.schedule_df = None
        self.course_teachers = {}
        self.teacher_schedules = {}
        self.valid_combinations = []
        self.total_capacity = 0
        self.max_combinations_to_check = 10000  # Limit the maximum combinations to check
        
        # Load data
        self._load_schedule_data()
    
    def _load_schedule_data(self):
        """Load and process the schedule data from CSV."""
        try:
            self.schedule_df = pd.read_csv(self.schedule_path)
            self.logger.info(f"Loaded schedule data with {len(self.schedule_df)} entries")
            
            # Filter for the specific semester
            if 'semester' in self.schedule_df.columns:
                self.schedule_df = self.schedule_df[self.schedule_df['semester'] == self.semester]
                self.logger.info(f"Filtered to {len(self.schedule_df)} entries for semester {self.semester}")
            
            # Extract course and teacher information
            self._extract_course_teacher_info()
            
            # Build teacher schedules
            self._build_teacher_schedules()
        except Exception as e:
            self.logger.error(f"Error loading schedule data: {str(e)}")
            raise
    
    def _extract_course_teacher_info(self):
        """Extract course and teacher information from the schedule data."""
        # Group teachers by course
        course_teachers = defaultdict(set)
        
        for _, row in self.schedule_df.iterrows():
            course_id = row.get('course_id')
            teacher_id = row.get('teacher_id')
            
            if course_id and teacher_id:
                course_teachers[course_id].add(teacher_id)
        
        # Convert to regular dict with counts
        self.course_teachers = {course: list(teachers) for course, teachers in course_teachers.items()}
        self.logger.info(f"Found {len(self.course_teachers)} courses with teachers")
        
        for course, teachers in self.course_teachers.items():
            self.logger.info(f"Course {course}: {len(teachers)} teachers")
    
    def _build_teacher_schedules(self):
        """Build schedule information for each teacher."""
        teacher_schedules = {}
        
        for _, row in self.schedule_df.iterrows():
            teacher_id = row.get('teacher_id')
            day = row.get('day')
            slot_index = row.get('slot_index')
            course_id = row.get('course_id')
            
            if teacher_id and day and slot_index is not None and course_id:
                if teacher_id not in teacher_schedules:
                    teacher_schedules[teacher_id] = {}
                
                key = f"{day}_{slot_index}"
                teacher_schedules[teacher_id][key] = course_id
        
        self.teacher_schedules = teacher_schedules
    
    def validate_course_combinations(self):
        """
        Validate if sufficient course combinations exist for all students.
        
        Returns:
            dict: Validation results
        """
        # Get all required courses
        required_courses = list(self.course_teachers.keys())
        
        if len(required_courses) < 5:
            self.logger.warning(f"Found only {len(required_courses)} courses, expected 5")
        
        # Generate teacher combinations more efficiently by sampling
        # instead of generating all possible combinations
        sample_combinations = self._generate_limited_teacher_combinations(required_courses)
        self.logger.info(f"Generated {len(sample_combinations)} sample teacher combinations (limited for performance)")
        
        # Find valid combinations (no schedule conflicts)
        valid_combinations = []
        for combo in sample_combinations:
            if self._is_combination_valid(combo):
                # For each valid combination, find the minimum capacity
                min_capacity = self._get_combination_capacity(combo)
                valid_combinations.append((combo, min_capacity))
        
        self.valid_combinations = valid_combinations
        self.total_capacity = sum(capacity for _, capacity in valid_combinations)
        
        # Estimate total capacity based on sample
        estimated_total_capacity = self.total_capacity
        if len(sample_combinations) < self._calculate_total_possible_combinations(required_courses):
            # Scale up the estimated capacity based on sampling ratio
            total_possible = self._calculate_total_possible_combinations(required_courses)
            sampling_ratio = total_possible / len(sample_combinations)
            estimated_total_capacity = int(self.total_capacity * sampling_ratio)
            self.logger.info(f"Sampled {len(sample_combinations)} of {total_possible} combinations ({sampling_ratio:.2f}x)")
            self.logger.info(f"Estimated total capacity: {estimated_total_capacity} students (based on sampling)")
        
        self.logger.info(f"Found {len(valid_combinations)} valid combinations in sample")
        self.logger.info(f"Sample capacity: {self.total_capacity} students")
        
        # Prepare validation result
        result = {
            "status": "SUCCESS" if estimated_total_capacity >= self.student_count else "FAILED",
            "valid_combinations_count": len(valid_combinations),
            "total_capacity": self._to_python_type(self.total_capacity),
            "estimated_total_capacity": self._to_python_type(estimated_total_capacity),
            "required_capacity": self._to_python_type(self.student_count),
            "is_sampled": len(sample_combinations) < self._calculate_total_possible_combinations(required_courses),
            "sample_size": len(sample_combinations),
            "total_possible_combinations": self._calculate_total_possible_combinations(required_courses),
            "course_teacher_counts": {course: len(teachers) for course, teachers in self.course_teachers.items()},
            "valid_combinations": [
                {
                    "courses": [self._get_course_code(course_id) for course_id, _ in combo],
                    "teachers": [teacher_id for _, teacher_id in combo],
                    "capacity": self._to_python_type(capacity)
                }
                for combo, capacity in valid_combinations[:10]  # Limit to first 10 for brevity
            ]
        }
        
        return result
    
    def _generate_limited_teacher_combinations(self, courses):
        """
        Generate a limited number of teacher combinations for the given courses.
        Uses sampling for large combination spaces to avoid memory issues.
        
        Args:
            courses: List of course IDs
        
        Returns:
            list: List of teacher combinations (limited)
        """
        import random
        
        # Calculate the total number of possible combinations
        total_possible = self._calculate_total_possible_combinations(courses)
        
        if total_possible <= self.max_combinations_to_check:
            # If total is manageable, generate all combinations
            return self._generate_teacher_combinations(courses)
        
        # Otherwise, use sampling for a limited subset
        self.logger.info(f"Total possible combinations ({total_possible}) exceeds limit, using sampling")
        
        # Create a list of teachers for each course
        course_teacher_lists = [self.course_teachers.get(course, []) for course in courses]
        
        # Generate limited random combinations
        combinations = []
        for _ in range(self.max_combinations_to_check):
            combo = []
            for course_idx, course in enumerate(courses):
                # Select a random teacher for each course
                teachers = course_teacher_lists[course_idx]
                if teachers:
                    teacher = random.choice(teachers)
                    combo.append((course, teacher))
            
            # Add combination if it includes all courses
            if len(combo) == len(courses):
                combinations.append(combo)
        
        return combinations
    
    def _calculate_total_possible_combinations(self, courses):
        """Calculate the total number of possible teacher combinations."""
        total = 1
        for course in courses:
            num_teachers = len(self.course_teachers.get(course, []))
            if num_teachers > 0:
                total *= num_teachers
        return total
    
    def _generate_teacher_combinations(self, courses):
        """
        Generate all possible teacher combinations for the given courses.
        
        Args:
            courses: List of course IDs
        
        Returns:
            list: List of teacher combinations
        """
        if not courses:
            return [[]]
        
        current_course = courses[0]
        remaining_courses = courses[1:]
        
        # Get all teachers for current course
        teachers = self.course_teachers.get(current_course, [])
        
        # Get combinations for remaining courses
        sub_combinations = self._generate_teacher_combinations(remaining_courses)
        
        # Combine current course teachers with sub-combinations
        result = []
        for teacher in teachers:
            for sub_combo in sub_combinations:
                result.append([(current_course, teacher)] + sub_combo)
        
        return result
    
    def _is_combination_valid(self, combination):
        """
        Check if a teacher combination has no scheduling conflicts.
        
        Args:
            combination: List of (course_id, teacher_id) tuples
        
        Returns:
            bool: True if no conflicts exist
        """
        # Extract time slots for each teacher
        time_slots = {}
        for course_id, teacher_id in combination:
            if teacher_id in self.teacher_schedules:
                for slot, slot_course in self.teacher_schedules[teacher_id].items():
                    if slot_course == course_id:
                        if slot in time_slots:
                            # Conflict found - same time slot used by different courses
                            return False
                        time_slots[slot] = (course_id, teacher_id)
        
        # Ensure all courses are scheduled
        scheduled_courses = set(course_id for course_id, _ in combination)
        covered_courses = set(course_id for course_id, _ in time_slots.values())
        
        return scheduled_courses == covered_courses
    
    def _get_combination_capacity(self, combination):
        """
        Get the capacity of a combination (minimum student count).
        
        Args:
            combination: List of (course_id, teacher_id) tuples
        
        Returns:
            int: Minimum capacity
        """
        capacities = []
        
        for course_id, teacher_id in combination:
            # Find student count for this specific course-teacher combination
            relevant_rows = self.schedule_df[
                (self.schedule_df['course_id'] == course_id) & 
                (self.schedule_df['teacher_id'] == teacher_id)
            ]
            
            if not relevant_rows.empty and 'student_count' in relevant_rows.columns:
                student_count = relevant_rows['student_count'].iloc[0]
                capacities.append(student_count)
            else:
                # Default to a low value if no student count found
                capacities.append(1)
        
        # Combination capacity is limited by the minimum capacity across all courses
        return min(capacities) if capacities else 0
    
    def _get_course_code(self, course_id):
        """Get course code for the given course ID."""
        if self.schedule_df is not None:
            course_rows = self.schedule_df[self.schedule_df['course_id'] == course_id]
            if not course_rows.empty and 'course_code' in course_rows.columns:
                return course_rows['course_code'].iloc[0]
        return str(course_id)
    
    def _to_python_type(self, value):
        """Convert NumPy types to native Python types for JSON serialization."""
        if isinstance(value, np.integer):
            return int(value)
        elif isinstance(value, np.floating):
            return float(value)
        elif isinstance(value, np.ndarray):
            return value.tolist()
        else:
            return value
    
    def generate_report(self, output_dir):
        """
        Generate a validation report.
        
        Args:
            output_dir: Directory to save the report
        
        Returns:
            str: Path to the generated report
        """
        # Validate combinations
        validation_results = self.validate_course_combinations()
        
        # Create report file
        report_path = os.path.join(output_dir, 'combination_validation_report.txt')
        
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write("Course Combination Validation Report\n")
            f.write("==================================\n\n")
            
            f.write(f"Overall Status: {validation_results['status']}\n")
            f.write(f"Valid combinations in sample: {validation_results['valid_combinations_count']}\n")
            
            if validation_results.get('is_sampled', False):
                f.write(f"Sample size: {validation_results['sample_size']} of {validation_results['total_possible_combinations']} possible combinations\n")
                f.write(f"Estimated total capacity: {validation_results.get('estimated_total_capacity', 0)} students\n")
            else:
                f.write(f"Total valid combinations: {validation_results['valid_combinations_count']}\n")
            
            f.write(f"Sample capacity: {validation_results['total_capacity']} students\n")
            f.write(f"Required capacity: {validation_results['required_capacity']} students\n\n")
            
            f.write("Course-Teacher Counts:\n")
            for course, count in validation_results['course_teacher_counts'].items():
                f.write(f"  {course}: {count} teachers\n")
            
            f.write("\nValid Course Combinations (Sample):\n")
            if validation_results['valid_combinations']:
                for combo in validation_results['valid_combinations']:
                    courses_str = ", ".join(combo['courses'])
                    f.write(f"  ({courses_str}) - Capacity: {combo['capacity']} students\n")
            else:
                f.write("  No valid combinations found\n")
            
            f.write("\nCombination Validation Details:\n")
            if validation_results['status'] == "SUCCESS":
                if validation_results.get('is_sampled', False):
                    f.write(f"  The generated timetable is estimated to provide sufficient combinations\n")
                    f.write(f"  for {validation_results['required_capacity']} students based on sampling.\n")
                    f.write(f"  Estimated total capacity: {validation_results.get('estimated_total_capacity', 0)} students.\n")
                else:
                    f.write(f"  The generated timetable provides {validation_results['valid_combinations_count']} valid combinations\n")
                    f.write(f"  for {validation_results['total_capacity']} students, which is sufficient for the required {validation_results['required_capacity']} students.\n")
            else:
                f.write(f"  The generated timetable DOES NOT provide sufficient valid combinations\n")
                f.write(f"  for {validation_results['required_capacity']} students. Only {validation_results.get('estimated_total_capacity', validation_results['total_capacity'])} can be accommodated.\n")
                f.write(f"  Consider adjusting the schedule to allow for more non-conflicting combinations.\n")
        
        # Also save as JSON for further processing
        json_path = os.path.join(output_dir, 'combination_validation.json')
        
        # Use custom JSON encoder to handle NumPy types
        class NumpyEncoder(json.JSONEncoder):
            def default(self, obj):
                if isinstance(obj, np.integer):
                    return int(obj)
                elif isinstance(obj, np.floating):
                    return float(obj)
                elif isinstance(obj, np.ndarray):
                    return obj.tolist()
                return super().default(obj)
        
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(validation_results, f, indent=2, cls=NumpyEncoder)
        
        return report_path

# Helper function to run validation
def validate_student_combinations(schedule_path, output_dir, semester=5, student_count=700):
    """
    Validate if the timetable allows sufficient course combinations for all students.
    
    Args:
        schedule_path: Path to the schedule CSV file
        output_dir: Directory to save validation results
        semester: Semester to validate (default: 5)
        student_count: Number of students to accommodate (default: 700)
    
    Returns:
        str: Path to the validation report
    """
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        filename=os.path.join(output_dir, 'combination_validation.log')
    )
    
    validator = CourseSelectionValidator(schedule_path, semester, student_count)
    report_path = validator.generate_report(output_dir)
    
    return report_path

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Validate course combinations for students')
    parser.add_argument('--schedule', required=True, help='Path to schedule CSV file')
    parser.add_argument('--output', required=True, help='Output directory for reports')
    parser.add_argument('--semester', type=int, default=5, help='Semester to validate')
    parser.add_argument('--students', type=int, default=700, help='Number of students to accommodate')
    parser.add_argument('--max-combinations', type=int, default=10000, help='Maximum combinations to check')
    
    args = parser.parse_args()
    
    validator = CourseSelectionValidator(args.schedule, args.semester, args.students)
    validator.max_combinations_to_check = args.max_combinations
    report_path = validator.generate_report(args.output)
    
    print(f"Validation report generated at: {report_path}") 