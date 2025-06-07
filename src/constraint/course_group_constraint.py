"""
Course Group Constraint

This constraint creates logical groupings of teacher-course instances by semester and department.
Each teacher-course combination is treated as a unique instance that gets placed into a group.
This provides students with organized course selection options while maintaining teacher choice flexibility.

INSTANCE-AWARE: Fully works at the individual teacher-course-instance level.

Key features:
- Groups teacher-course instances (not just courses or teachers)
- Balances workload across groups at instance level
- Provides group information for CSV output
- No scheduling synchronization constraints
- Enhanced instance tracking and analysis
"""

import logging
from collections import defaultdict

logger = logging.getLogger(__name__)

class CourseGroupConstraint:
    def __init__(self, model, teachers, teacher_course_assignments, classrooms, labs):
        """Initialize the course group constraint."""
        self.model = model
        self.teachers = teachers
        self.teacher_course_assignments = teacher_course_assignments
        self.classrooms = classrooms
        self.labs = labs
        
        # Pre-compute room IDs for efficiency
        self.classroom_ids = self.classrooms['id'].tolist()
        self.lab_ids = self.labs['id'].tolist()
        
        # Time structure
        self.days = ["tuesday", "wed", "thur", "fri", "sat"]
        self.num_days = len(self.days)
        self.num_slots = 11  # Theory slots per day
        
        # Lab sessions
        self.lab_sessions = {
            'L1': {'slots': [0, 1], 'time_range': '8:00 - 9:40'},
            'L2': {'slots': [2, 3], 'time_range': '9:50 - 11:30'},
            'L3': {'slots': [4, 5], 'time_range': '11:50 - 1:30'},
            'L4': {'slots': [6, 7], 'time_range': '1:50 - 3:30'},
            'L5': {'slots': [8, 9], 'time_range': '3:50 - 5:30'},
            'L6': {'slots': [10, 11], 'time_range': '5:30 - 7:10'}
        }
        
        # Create course instance groups (INSTANCE-AWARE)
        self.course_groups = self._create_course_groups_instance_aware()
        
        # Enhanced instance tracking
        self.instance_group_mapping = {}
        self._create_instance_group_mapping()
    
    def _create_course_groups_instance_aware(self):
        """
        Group teacher-course instances by semester and department (INSTANCE-AWARE).
        
        Each teacher-course combination is treated as a unique instance that needs to be
        placed into a group. For example:
        - Teacher A teaching Course X = Instance 1
        - Teacher A teaching Course Y = Instance 2  
        - Teacher B teaching Course X = Instance 3
        
        Returns a dictionary with keys as (dept, semester) tuples and 
        values as lists of groups of teacher-course instances.
        """
        logger.info("Creating course groups (INSTANCE-AWARE)...")
        
        # First, collect all course instances by department and semester
        dept_sem_courses = defaultdict(list)
        total_instances = 0
        
        # Gather all course instances with enhanced tracking
        all_instances = []
        for teacher, assignments in self.teacher_course_assignments.items():
            for instance in assignments:
                # Add teacher ID to instance for tracking
                instance_with_teacher = instance.copy()
                instance_with_teacher['teacher_id'] = teacher
                all_instances.append(instance_with_teacher)
                total_instances += 1
        
        logger.info(f"Processing {total_instances} total course instances across {len(self.teachers)} teachers")
        
        # Group by department and semester (INSTANCE-AWARE)
        for instance in all_instances:
            dept = instance.get('course_dept', 'Unknown')
            semester = instance.get('semester', 0)
            dept_sem_courses[(dept, semester)].append(instance)
        
        # Log department-semester distribution
        for (dept, semester), instances in dept_sem_courses.items():
            instance_details = []
            for inst in instances:
                theory_hrs = inst['lecture_hours'] + inst['tutorial_hours']
                practical_hrs = inst['practical_hours']
                instance_details.append(f"T{inst['teacher_id']}-{inst['course_code']}({theory_hrs}T+{practical_hrs}P)")
            
            logger.info(f"Dept: {dept}, Semester: {semester}: {len(instances)} instances")
            logger.debug(f"  Instances: {', '.join(instance_details[:10])}" + 
                        (f" (+{len(instance_details)-10} more)" if len(instance_details) > 10 else ""))
        
        # Now create groups for each department and semester
        course_groups = {}
        
        for (dept, semester), courses in dept_sem_courses.items():
            # Skip if there are no courses for this department/semester
            if not courses:
                continue
            
            # Analyze course instances and group them properly (INSTANCE-AWARE)
            course_groups[(dept, semester)] = self._distribute_course_instances_enhanced(courses, dept, semester)
        
        return course_groups
    
    def _distribute_course_instances_enhanced(self, courses, dept, semester):
        """
        Distribute teacher-course instances across groups (ENHANCED INSTANCE-AWARE).
        
        Each teacher-course combination is treated as a unique instance that should be
        placed in a group. The goal is to create balanced groups where students have
        choice options within their department and semester.
        
        Args:
            courses: List of course instances for a specific department and semester
            dept: Department name
            semester: Semester number
            
        Returns:
            List of groups, where each group contains teacher-course instances
        """
        total_instances = len(courses)
        
        if total_instances == 0:
            return []
        
        # Enhanced instance analysis
        instance_analysis = {
            'total_instances': total_instances,
            'unique_courses': len(set(inst['course_code'] for inst in courses)),
            'unique_teachers': len(set(inst['teacher_id'] for inst in courses)),
            'total_theory_hours': sum(inst['lecture_hours'] + inst['tutorial_hours'] for inst in courses),
            'total_practical_hours': sum(inst['practical_hours'] for inst in courses),
            'avg_student_count': sum(inst.get('student_count', 0) for inst in courses) / total_instances if total_instances > 0 else 0
        }
        
        logger.info(f"Enhanced analysis for {dept} Semester {semester}:")
        logger.info(f"  {instance_analysis['total_instances']} instances, {instance_analysis['unique_courses']} unique courses, {instance_analysis['unique_teachers']} unique teachers")
        logger.info(f"  Total workload: {instance_analysis['total_theory_hours']}T + {instance_analysis['total_practical_hours']}P")
        logger.info(f"  Average class size: {instance_analysis['avg_student_count']:.1f} students")
        
        # Calculate optimal number of groups based on total instances
        # Aim for 3-5 teacher-course instances per group for good choice balance
        optimal_instances_per_group = 4
        num_groups = max(1, min(8, (total_instances + optimal_instances_per_group - 1) // optimal_instances_per_group))
        
        # Ensure we have reasonable group distribution
        if total_instances <= 3:
            num_groups = 1
        elif total_instances <= 8:
            num_groups = 2
        elif total_instances <= 15:
            num_groups = 3
        else:
            num_groups = min(6, (total_instances + 3) // 4)  # Cap at 6 groups, aim for ~4 per group
        
        logger.info(f"Creating {num_groups} groups (target: ~{total_instances//num_groups} instances per group)")
        
        # Initialize groups
        groups = [[] for _ in range(num_groups)]
        
        # Track group metrics for enhanced balancing
        group_metrics = []
        for i in range(num_groups):
            group_metrics.append({
                'workload': 0,
                'student_count': 0,
                'instance_count': 0,
                'courses': set(),
                'teachers': set()
            })
        
        # Enhanced sorting: Consider workload, student count, and course diversity
        def instance_priority(inst):
            theory_hrs = inst['lecture_hours'] + inst['tutorial_hours']
            practical_hrs = inst['practical_hours']
            student_count = inst.get('student_count', 0)
            # Priority based on total workload and student count
            return (theory_hrs + practical_hrs, student_count)
        
        courses_sorted = sorted(courses, key=instance_priority, reverse=True)
        
        # Distribute teacher-course instances using enhanced balancing
        for i, course_instance in enumerate(courses_sorted):
            # Find the group with the best balance (lowest combined metric)
            best_group_idx = 0
            best_score = float('inf')
            
            for group_idx in range(num_groups):
                metrics = group_metrics[group_idx]
                # Combined score considering workload, capacity, and diversity
                workload_score = metrics['workload']
                capacity_score = metrics['student_count'] / 100  # Normalize student count
                diversity_penalty = 0
                
                # Penalty for teacher/course duplication within group
                if course_instance['teacher_id'] in metrics['teachers']:
                    diversity_penalty += 5  # Prefer different teachers
                if course_instance['course_code'] in metrics['courses']:
                    diversity_penalty += 3  # Some penalty for same course
                
                combined_score = workload_score + capacity_score + diversity_penalty
                
                if combined_score < best_score:
                    best_score = combined_score
                    best_group_idx = group_idx
            
            # Add this teacher-course instance to the best group
            groups[best_group_idx].append(course_instance)
            
            # Update metrics
            metrics = group_metrics[best_group_idx]
            workload = course_instance['lecture_hours'] + course_instance['tutorial_hours'] + course_instance['practical_hours']
            student_count = course_instance.get('student_count', 0)
            
            metrics['workload'] += workload
            metrics['student_count'] += student_count
            metrics['instance_count'] += 1
            metrics['courses'].add(course_instance['course_code'])
            metrics['teachers'].add(course_instance['teacher_id'])
            
            logger.debug(f"  Instance: T{course_instance['teacher_id']}-{course_instance['course_code']} "
                       f"({workload}h, {student_count}s) -> Group {best_group_idx + 1}")
        
        # Log final group distribution (ENHANCED)
        logger.info(f"Final enhanced group distribution for {dept} Semester {semester}:")
        for i, group in enumerate(groups):
            if group:  # Only show non-empty groups
                metrics = group_metrics[i]
                instances_info = []
                
                for instance in group:
                    teacher_id = instance['teacher_id']
                    course_code = instance['course_code']
                    workload = instance['lecture_hours'] + instance['tutorial_hours'] + instance['practical_hours']
                    instances_info.append(f"T{teacher_id}-{course_code}({workload}h)")
                
                logger.info(f"  Group {i+1}: {metrics['instance_count']} instances, "
                           f"{len(metrics['courses'])} unique courses, {len(metrics['teachers'])} unique teachers")
                logger.info(f"    Total: {metrics['workload']}h workload, {metrics['student_count']} total students")
                logger.info(f"    Instances: {', '.join(instances_info)}")
        
        # Remove empty groups (shouldn't happen with this logic, but safety check)
        non_empty_groups = [group for group in groups if group]
        
        return non_empty_groups
    
    def _create_instance_group_mapping(self):
        """Create enhanced mapping from course instances to their groups (INSTANCE-AWARE)."""
        logger.info("Creating enhanced instance-group mapping (INSTANCE-AWARE)...")
        
        total_mapped_instances = 0
        
        for (dept, semester), groups in self.course_groups.items():
            for group_idx, group in enumerate(groups):
                for instance in group:
                    instance_id = instance['id']
                    teacher_id = instance['teacher_id']
                    course_code = instance['course_code']
                    
                    self.instance_group_mapping[instance_id] = {
                        'group_name': f"{dept}_S{semester}_G{group_idx + 1}",
                        'group_index': group_idx,
                        'department': dept,
                        'semester': semester,
                        'teacher_id': teacher_id,
                        'course_code': course_code
                    }
                    total_mapped_instances += 1
        
        logger.info(f"Enhanced instance-group mapping created: {total_mapped_instances} instances mapped to groups")
    
    def apply(self, teacher_theory_assignments, teacher_lab_assignments=None):
        """
        Apply course group constraint to create course groupings for output (INSTANCE-AWARE).
        
        This constraint now only:
        1. Creates logical groupings of course instances by semester and department
        2. Stores group information for output in CSV files
        3. Does not enforce any scheduling synchronization (removed as requested)
        4. INSTANCE-AWARE: Enhanced tracking of individual instances
        """
        logger.info("Applying course group constraint (INSTANCE-AWARE grouping only, no synchronization)...")
        
        if not self.course_groups:
            logger.info("No course groups found, skipping constraint")
            return True
        
        # Store the course groups for later use in output generation
        # This will be accessed by the scheduler to add group information to CSV output
        self._store_group_mappings_enhanced()
        
        # Log detailed group statistics (INSTANCE-AWARE)
        self._log_enhanced_group_statistics()
        
        logger.info("Course group constraint (INSTANCE-AWARE) applied successfully")
        return True
    
    def _store_group_mappings_enhanced(self):
        """Store enhanced group mappings for use in output generation (INSTANCE-AWARE)."""
        logger.info("Storing enhanced group mappings for output generation...")
        
        # The instance_group_mapping will be used by the scheduler
        # to add group information to the CSV output
        
        group_summary = {}
        total_groups = 0
        
        for (dept, semester), groups in self.course_groups.items():
            group_summary[(dept, semester)] = len(groups)
            total_groups += len(groups)
        
        logger.info(f"Enhanced group mappings stored: {total_groups} total groups across departments/semesters")
        for (dept, semester), count in group_summary.items():
            logger.debug(f"  {dept} Semester {semester}: {count} groups")
    
    def _log_enhanced_group_statistics(self):
        """Log enhanced statistics about the created groups (INSTANCE-AWARE)."""
        total_groups = 0
        total_instances = 0
        
        for (dept, semester), groups in self.course_groups.items():
            total_groups += len(groups)
            for group in groups:
                total_instances += len(group)
        
        logger.info(f"Enhanced Group Statistics (INSTANCE-AWARE):")
        logger.info(f"  Total groups created: {total_groups}")
        logger.info(f"  Total instances distributed: {total_instances}")
        logger.info(f"  Average instances per group: {total_instances / total_groups:.1f}" if total_groups > 0 else "  No groups created")
    
    def get_group_info_for_course_instance(self, teacher_id, course_instance_id):
        """
        Get group information for a specific course instance (INSTANCE-AWARE).
        
        Args:
            teacher_id: ID of the teacher
            course_instance_id: ID of the course instance
            
        Returns:
            Dictionary with group information or default values
        """
        if course_instance_id in self.instance_group_mapping:
            return self.instance_group_mapping[course_instance_id]
        else:
            # Fallback for instances not found in mapping
            logger.warning(f"Instance {course_instance_id} for teacher {teacher_id} not found in group mapping")
            return {
                'group_name': 'Unassigned',
                'group_index': 0,
                'department': 'Unknown',
                'semester': 0,
                'teacher_id': teacher_id,
                'course_code': 'Unknown'
            } 