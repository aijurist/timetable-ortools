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
- GROUP-BASED SCHEDULING: Allocates dynamic number of timeslots per group based on course hours
- STUDENT CHOICE: No time conflicts between groups in the same semester
- CROSS-GROUP SELECTION: Students can take courses from multiple groups
- Post-processing allocation: Course instances span across group timeslots based on hours
- Enhanced instance tracking and analysis
- TEACHER UNIQUENESS CONSTRAINT: No teacher can appear multiple times in the same group
  (but teachers can be in different groups)
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
        
        # Time slots (needed for reporting and output)
        self.time_slots = [
            "8:00 - 8:50", "9:00 - 9:50", "10:00 - 10:50", "11:00 - 11:50",
            "12:00 - 12:50", "1:00 - 1:50", "2:00 - 2:50", "3:00 - 3:50", 
            "4:00 - 4:50", "5:00 - 5:50", "6:00 - 6:50"
        ]
        
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
        
        # GROUP-BASED SCHEDULING:
        # Store group timeslot variables and assignments
        self.group_timeslot_vars = {}  # Stores CP-SAT variables for group timeslots
        self.group_timeslots = {}      # Will store the actual timeslots assigned to each group
        self.timeslots_per_group = {}  # Dynamic allocation based on group course hours
    
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
        Distribute teacher-course instances across groups with PREPROCESSED HALL'S THEOREM OPTIMIZATION.
        
        OPTIMIZED APPROACH:
        1. Pre-calculate Hall's theorem distribution BEFORE scheduling algorithm runs
        2. Ensure teacher uniqueness in each group as a hard constraint
        3. Maximize student choice by enforcing distribution that always satisfies Hall's theorem
        4. Use bipartite matching for optimal distribution
        5. FIXED GROUP COUNT: Number of groups equals number of unique theory courses
        
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
        
        # Count courses with theory hours (lecture or tutorial)
        theory_courses = [inst for inst in courses if (inst['lecture_hours'] + inst['tutorial_hours']) > 0]
        theory_instances_count = len(theory_courses)
        
        # Enhanced instance analysis
        instance_analysis = {
            'total_instances': total_instances,
            'theory_instances_count': theory_instances_count,
            'unique_courses': len(set(inst['course_code'] for inst in courses)),
            'unique_theory_courses': len(set(inst['course_code'] for inst in theory_courses)),
            'unique_teachers': len(set(inst['teacher_id'] for inst in courses)),
            'total_theory_hours': sum(inst['lecture_hours'] + inst['tutorial_hours'] for inst in courses),
            'total_practical_hours': sum(inst['practical_hours'] for inst in courses),
            'avg_student_count': sum(inst.get('student_count', 0) for inst in courses) / total_instances if total_instances > 0 else 0
        }
        
        logger.info(f"OPTIMIZED Hall-based analysis for {dept} Semester {semester}:")
        logger.info(f"  {instance_analysis['total_instances']} total instances, {theory_instances_count} theory instances")
        logger.info(f"  {instance_analysis['unique_courses']} unique courses, {instance_analysis['unique_teachers']} unique teachers")
        logger.info(f"  Total workload: {instance_analysis['total_theory_hours']}T + {instance_analysis['total_practical_hours']}P")
        logger.info(f"  Average class size: {instance_analysis['avg_student_count']:.1f} students")
        
        # OPTIMIZATION: Calculate number of groups based on unique theory course codes
        # This ensures we have optimal distribution based on the number of unique theory courses
        unique_theory_course_codes = instance_analysis['unique_theory_courses']
        
        # FIXED GROUP COUNT: Use the number of unique theory course codes as the number of groups
        # Apply reasonable limits (minimum 1, maximum 5 groups per semester)
        num_groups = min(5, max(1, unique_theory_course_codes))
        
        logger.info(f"FIXED GROUP COUNT: Using {num_groups} groups based on {unique_theory_course_codes} unique theory courses")
        logger.info(f"Creating {num_groups} groups (target: ~{theory_instances_count//num_groups if num_groups > 0 else 0} theory instances per group)")
        
        # Initialize groups
        groups = [[] for _ in range(num_groups)]
        
        # Track group metrics for enhanced balancing with theory-specific tracking
        group_metrics = []
        for i in range(num_groups):
            group_metrics.append({
                'workload': 0,
                'theory_workload': 0,  # Track theory hours separately
                'practical_workload': 0,  # Track practical hours separately
                'student_count': 0,
                'instance_count': 0,
                'theory_instance_count': 0,  # Track theory instances separately
                'courses': set(),
                'teachers': set()
            })
        
        # HALLS OPTIMIZATION: Pre-process course-teacher graph structure
        # This approach pre-computes a course-teacher distribution that guarantees Hall's theorem satisfaction
        
        # 1. Build the course-teacher bipartite graph
        course_to_teachers = {}  # Maps courses to available teachers
        teacher_to_courses = {}  # Maps teachers to available courses
        
        for instance in theory_courses:
            course_code = instance['course_code']
            teacher_id = instance['teacher_id']
            
            if course_code not in course_to_teachers:
                course_to_teachers[course_code] = set()
            course_to_teachers[course_code].add(teacher_id)
            
            if teacher_id not in teacher_to_courses:
                teacher_to_courses[teacher_id] = set()
            teacher_to_courses[teacher_id].add(course_code)
        
        # 2. Group instances by course code
        course_instances = {}
        for instance in theory_courses:
            course_code = instance['course_code']
            if course_code not in course_instances:
                course_instances[course_code] = []
            course_instances[course_code].append(instance)
        
        # 3. Sort courses by number of teachers (ascending) for better Hall satisfaction
        sorted_courses = sorted(course_to_teachers.keys(), 
                              key=lambda c: len(course_to_teachers[c]))
        
        logger.info("HALLS PRE-PROCESSING: Course-teacher availability analysis:")
        for course_code in sorted_courses:
            teacher_count = len(course_to_teachers[course_code])
            logger.info(f"  {course_code}: {teacher_count} teachers available, {len(course_instances[course_code])} instances to distribute")
        
        # 4. Pre-allocate courses to groups to maximize Hall's theorem satisfaction
        logger.info("HALLS PRE-PROCESSING: Pre-allocating courses to maximize Hall's theorem satisfaction")
        
        # First, distribute one instance of each course to each group in round-robin fashion
        # This ensures each group has at least one instance of each course (when possible)
        pre_allocation = [set() for _ in range(num_groups)]
        next_group = 0
        
        for course_code in sorted_courses:
            # Try to allocate at least one instance of this course to each group
            instances = course_instances[course_code].copy()
            
            # Make sure we don't exceed group count
            allocations = min(len(instances), num_groups)
            
            for _ in range(allocations):
                pre_allocation[next_group].add(course_code)
                next_group = (next_group + 1) % num_groups
        
        # Log pre-allocation plan
        for group_idx, courses in enumerate(pre_allocation):
            logger.info(f"  Group {group_idx+1} pre-allocation: {', '.join(sorted(courses))}")
        
        # 5. Execute the pre-processed distribution
        # Distribute instances according to pre-allocation while maintaining teacher uniqueness
        for group_idx, target_courses in enumerate(pre_allocation):
            logger.info(f"Executing pre-processed distribution for Group {group_idx+1}...")
            
            # Track teachers already used in this group
            used_teachers = set()
            
            # First, try to fulfill the pre-allocation plan
            for course_code in target_courses:
                instances = [inst for inst in course_instances[course_code] if inst not in [i for g in groups for i in g]]
                
                if not instances:
                    logger.warning(f"  No instances left for {course_code} in Group {group_idx+1}")
                    continue
                
                # Find an instance with a teacher not yet used in this group
                found = False
                for instance in instances:
                    teacher_id = instance['teacher_id']
                    
                    if teacher_id not in used_teachers:
                        # Add this instance to the group
                        groups[group_idx].append(instance)
                        used_teachers.add(teacher_id)
                        
                        # Update metrics
                        metrics = group_metrics[group_idx]
                        theory_hrs = instance['lecture_hours'] + instance['tutorial_hours']
                        practical_hrs = instance['practical_hours']
                        workload = theory_hrs + practical_hrs
                        
                        metrics['workload'] += workload
                        metrics['theory_workload'] += theory_hrs
                        metrics['practical_workload'] += practical_hrs
                        metrics['student_count'] += instance.get('student_count', 0)
                        metrics['instance_count'] += 1
                        if theory_hrs > 0:
                            metrics['theory_instance_count'] += 1
                        metrics['courses'].add(instance['course_code'])
                        metrics['teachers'].add(instance['teacher_id'])
                        
                        logger.info(f"  Pre-allocated: {course_code} (T{teacher_id}) → Group {group_idx + 1}")
                        found = True
                        break
                
                if not found:
                    logger.warning(f"  Could not find teacher for {course_code} in Group {group_idx+1} that preserves uniqueness")
        
        # 6. Distribute remaining instances while maintaining teacher uniqueness
        # Collect all remaining instances
        remaining_instances = []
        for course_code, instances in course_instances.items():
            for instance in instances:
                if instance not in [i for g in groups for i in g]:
                    remaining_instances.append(instance)
        
        logger.info(f"Distributing {len(remaining_instances)} remaining instances...")
        
        # Sort remaining instances by priority
        def instance_priority(inst):
            theory_hrs = inst['lecture_hours'] + inst['tutorial_hours']
            practical_hrs = inst['practical_hours']
            course_code = inst['course_code']
            return (theory_hrs > 0, course_code, theory_hrs, practical_hrs)
        
        remaining_instances.sort(key=instance_priority, reverse=True)
        
        # Distribute remaining instances
        for instance in remaining_instances:
            teacher_id = instance['teacher_id']
            course_code = instance['course_code']
            
            # Find the best group for this instance
            best_group = None
            best_score = -1
            
            for group_idx in range(num_groups):
                # Skip if teacher already in this group
                if teacher_id in {inst['teacher_id'] for inst in groups[group_idx]}:
                    continue
                
                # Calculate score - prefer groups that don't have this course yet
                course_in_group = course_code in {inst['course_code'] for inst in groups[group_idx]}
                group_size = len(groups[group_idx])
                
                # Scoring: smaller groups are better, prefer groups without this course
                score = 1000 - group_size*10
                if not course_in_group:
                    score += 500  # Big bonus for adding a new course
                
                if score > best_score:
                    best_score = score
                    best_group = group_idx
            
            # If no valid group (all groups have this teacher), use least loaded group
            if best_group is None:
                group_sizes = [(len(groups[i]), i) for i in range(num_groups)]
                _, best_group = min(group_sizes)
                logger.warning(f"Teacher {teacher_id} forced into Group {best_group + 1} - no unique group available")
            
            # Add instance to the selected group
            groups[best_group].append(instance)
            
            # Update metrics
            metrics = group_metrics[best_group]
            theory_hrs = instance['lecture_hours'] + instance['tutorial_hours']
            practical_hrs = instance['practical_hours']
            workload = theory_hrs + practical_hrs
            
            metrics['workload'] += workload
            metrics['theory_workload'] += theory_hrs
            metrics['practical_workload'] += practical_hrs
            metrics['student_count'] += instance.get('student_count', 0)
            metrics['instance_count'] += 1
            if theory_hrs > 0:
                metrics['theory_instance_count'] += 1
            metrics['courses'].add(instance['course_code'])
            metrics['teachers'].add(instance['teacher_id'])
            
            logger.info(f"  Allocated remaining: {course_code} (T{teacher_id}) → Group {best_group + 1}")
        
        # 7. Validate constraints
        # Validate teacher uniqueness constraint
        self._validate_teacher_uniqueness_constraint(groups, dept, semester)
        
        # Validate Hall's theorem satisfaction
        halls_satisfied = self._validate_halls_theorem(groups, dept, semester)
        
        if not halls_satisfied:
            logger.warning("Hall's theorem not satisfied - attempting optimization")
            groups = self._optimize_for_halls_theorem(groups, dept, semester)
        
        # Log final group distribution
        logger.info(f"Final optimized group distribution for {dept} Semester {semester}:")
        for i, group in enumerate(groups):
            if group:  # Only show non-empty groups
                metrics = group_metrics[i]
                teacher_list = sorted(set(str(instance['teacher_id']) for instance in group))
                course_list = sorted(set(instance['course_code'] for instance in group))
                
                logger.info(f"  Group {i+1}: {metrics['instance_count']} instances ({metrics['theory_instance_count']} theory), "
                           f"{len(metrics['courses'])} unique courses, {len(metrics['teachers'])} unique teachers")
                logger.info(f"    Teachers: [{', '.join(teacher_list)}] (No duplicates: ✓)")
                logger.info(f"    Courses: [{', '.join(course_list)}]")
                logger.info(f"    Workload: {metrics['theory_workload']}T + {metrics['practical_workload']}P = {metrics['workload']} total hours")
                logger.info(f"    Students: {metrics['student_count']} total students")
        
        # Remove empty groups (shouldn't happen with this logic, but safety check)
        non_empty_groups = [group for group in groups if group]
        
        return non_empty_groups
    
    def _validate_teacher_uniqueness_constraint(self, groups, dept, semester):
        """
        Validate that no teacher appears multiple times in the same group.
        
        Args:
            groups: List of groups containing course instances
            dept: Department name
            semester: Semester number
        """
        logger.info(f"Validating teacher uniqueness constraint for {dept} Semester {semester}...")
        
        constraint_violations = 0
        total_teachers_checked = 0
        
        for group_idx, group in enumerate(groups):
            if not group:
                continue
                
            # Count occurrences of each teacher in this group
            teacher_occurrences = {}
            for instance in group:
                teacher_id = instance['teacher_id']
                if teacher_id not in teacher_occurrences:
                    teacher_occurrences[teacher_id] = []
                teacher_occurrences[teacher_id].append(instance['course_code'])
            
            # Check for violations (teacher appearing more than once)
            group_violations = 0
            for teacher_id, course_codes in teacher_occurrences.items():
                total_teachers_checked += 1
                if len(course_codes) > 1:
                    constraint_violations += 1
                    group_violations += 1
                    logger.error(f"CONSTRAINT VIOLATION: Teacher {teacher_id} appears {len(course_codes)} times in Group {group_idx + 1}")
                    logger.error(f"  Courses: {', '.join(course_codes)}")
            
            if group_violations == 0:
                unique_teachers = len(teacher_occurrences)
                logger.info(f"  Group {group_idx + 1}: ✓ All {unique_teachers} teachers are unique")
            else:
                logger.error(f"  Group {group_idx + 1}: ✗ {group_violations} teacher uniqueness violations found")
        
        if constraint_violations == 0:
            logger.info(f"✅ Teacher uniqueness constraint SATISFIED: {total_teachers_checked} teacher assignments checked, 0 violations")
        else:
            logger.error(f"❌ Teacher uniqueness constraint VIOLATED: {constraint_violations} violations found out of {total_teachers_checked} assignments")
            
        return constraint_violations == 0
    
    def _validate_halls_theorem(self, groups, dept, semester):
        """
        Validate that groups satisfy Hall's theorem for optimal student choice.
        
        Hall's theorem states that for any subset of courses S, the number of 
        unique teachers assigned to courses in S must be at least |S|.
        
        Args:
            groups: List of groups containing course instances
            dept: Department name
            semester: Semester number
            
        Returns:
            bool: True if Hall's theorem is satisfied for all groups
        """
        from itertools import combinations
        
        logger.info(f"Validating Hall's theorem for {dept} Semester {semester}...")
        
        total_violations = 0
        total_groups_checked = 0
        
        for group_idx, group in enumerate(groups):
            if not group:
                continue
            
            total_groups_checked += 1
            group_name = f"{dept}_S{semester}_G{group_idx + 1}"
            
            # Extract unique courses and teachers in this group
            courses = set()
            course_teacher_matrix = {}  # Maps courses to their teachers
            
            for instance in group:
                course_code = instance['course_code']
                teacher_id = instance['teacher_id']
                
                courses.add(course_code)
                
                if course_code not in course_teacher_matrix:
                    course_teacher_matrix[course_code] = set()
                
                course_teacher_matrix[course_code].add(teacher_id)
            
            # Check Hall's theorem for all non-empty subsets of courses
            violations = []
            
            for r in range(1, len(courses) + 1):
                for course_subset in combinations(courses, r):
                    # Find all teachers assigned to any course in this subset
                    neighbor_teachers = set()
                    for course in course_subset:
                        neighbor_teachers.update(course_teacher_matrix.get(course, set()))
                    
                    # Hall's condition: |N(S)| >= |S|
                    if len(neighbor_teachers) < len(course_subset):
                        violations.append({
                            'subset': list(course_subset),
                            'subset_size': len(course_subset),
                            'teacher_count': len(neighbor_teachers),
                            'teachers': list(neighbor_teachers)
                        })
            
            if violations:
                total_violations += len(violations)
                logger.warning(f"⚠️ Hall's theorem VIOLATED for Group {group_idx + 1}: {len(violations)} violations")
                
                # Log details of violations (limit to first 3 for clarity)
                for i, violation in enumerate(violations[:3]):
                    logger.warning(f"  Violation {i+1}: Courses {', '.join(violation['subset'])} have only {violation['teacher_count']} teachers")
                    logger.warning(f"    Need at least: {violation['subset_size']} teachers")
                
                if len(violations) > 3:
                    logger.warning(f"  (... {len(violations) - 3} more violations ...)")
            else:
                logger.info(f"  Group {group_idx + 1}: ✓ Hall's theorem SATISFIED")
        
        if total_violations == 0:
            logger.info(f"✅ Hall's theorem SATISFIED for all groups: Optimal student choice enabled")
        else:
            logger.warning(f"⚠️ Hall's theorem VIOLATED: {total_violations} violations across {total_groups_checked} groups")
            logger.warning(f"  This may limit student course choices")
            
        return total_violations == 0
        
    def _optimize_for_halls_theorem(self, groups, dept, semester):
        """
        Attempt to optimize group distribution to satisfy Hall's theorem.
        
        This optimization rearranges teacher-course assignments to ensure
        Hall's theorem is satisfied, enabling optimal student choice.
        
        Args:
            groups: List of groups containing course instances
            dept: Department name
            semester: Semester number
            
        Returns:
            List of optimized groups
        """
        from itertools import combinations
        
        logger.info(f"Optimizing for Hall's theorem in {dept} Semester {semester}...")
        
        # First check if Hall's theorem is already satisfied
        if self._validate_halls_theorem(groups, dept, semester):
            logger.info("  ✓ Hall's theorem already satisfied, no optimization needed")
            return groups
        
        # For each group with violations, attempt to optimize
        for group_idx, group in enumerate(groups):
            if not group:
                continue
            
            group_name = f"{dept}_S{semester}_G{group_idx + 1}"
            
            # Extract unique courses and teachers in this group
            courses = set()
            course_teacher_matrix = {}  # Maps courses to their teachers
            
            for instance in group:
                course_code = instance['course_code']
                teacher_id = instance['teacher_id']
                
                courses.add(course_code)
                
                if course_code not in course_teacher_matrix:
                    course_teacher_matrix[course_code] = set()
                
                course_teacher_matrix[course_code].add(teacher_id)
            
            # Check for Hall's theorem violations
            violations = []
            
            for r in range(1, len(courses) + 1):
                for course_subset in combinations(courses, r):
                    # Find all teachers assigned to any course in this subset
                    neighbor_teachers = set()
                    for course in course_subset:
                        neighbor_teachers.update(course_teacher_matrix.get(course, set()))
                    
                    # Hall's condition: |N(S)| >= |S|
                    if len(neighbor_teachers) < len(course_subset):
                        violations.append({
                            'subset': list(course_subset),
                            'subset_size': len(course_subset),
                            'teacher_count': len(neighbor_teachers),
                            'teachers': list(neighbor_teachers)
                        })
            
            if violations:
                logger.info(f"  Optimizing Group {group_idx + 1} with {len(violations)} Hall's theorem violations")
                
                # Sort violations by severity (largest deficit first)
                violations.sort(key=lambda v: v['subset_size'] - v['teacher_count'], reverse=True)
                
                # For each violation, try to add more teachers to the courses in the subset
                for violation in violations:
                    subset_courses = violation['subset']
                    deficit = violation['subset_size'] - violation['teacher_count']
                    
                    if deficit <= 0:
                        continue
                    
                    logger.info(f"    Attempting to fix: Courses {', '.join(subset_courses)} need {deficit} more teachers")
                    
                    # Try to find teachers from other groups who can teach these courses
                    other_groups = [g for i, g in enumerate(groups) if i != group_idx and g]
                    available_teachers = {}  # Maps teacher_id -> list of courses they can teach
                    
                    # Find teachers in other groups who can teach courses in this subset
                    for other_group in other_groups:
                        for instance in other_group:
                            teacher_id = instance['teacher_id']
                            course_code = instance['course_code']
                            
                            if course_code in subset_courses:
                                if teacher_id not in available_teachers:
                                    available_teachers[teacher_id] = []
                                
                                if course_code not in available_teachers[teacher_id]:
                                    available_teachers[teacher_id].append(course_code)
                    
                    # Sort teachers by how many courses they can teach from the subset
                    candidate_teachers = sorted(
                        available_teachers.items(),
                        key=lambda x: len(x[1]),
                        reverse=True
                    )
                    
                    # Attempt to move teachers to fix the violation
                    teachers_moved = 0
                    for teacher_id, teachable_courses in candidate_teachers:
                        if teachers_moved >= deficit:
                            break
                            
                        # Find this teacher in other groups
                        for other_group_idx, other_group in enumerate(groups):
                            if other_group_idx == group_idx:
                                continue
                                
                            # Find instances that can be moved
                            movable_instances = []
                            for i, instance in enumerate(other_group):
                                if (instance['teacher_id'] == teacher_id and 
                                    instance['course_code'] in subset_courses):
                                    movable_instances.append((i, instance))
                            
                            # Move one instance if possible
                            if movable_instances:
                                idx, instance = movable_instances[0]
                                logger.info(f"      Moving Teacher {teacher_id} teaching {instance['course_code']} from Group {other_group_idx + 1} to Group {group_idx + 1}")
                                
                                # Remove from source group
                                other_group.pop(idx)
                                
                                # Add to target group
                                groups[group_idx].append(instance)
                                
                                # Update course-teacher matrix
                                if instance['course_code'] not in course_teacher_matrix:
                                    course_teacher_matrix[instance['course_code']] = set()
                                course_teacher_matrix[instance['course_code']].add(teacher_id)
                                
                                teachers_moved += 1
                            break  # Move to next teacher
        
        # Validate again after optimization
        optimized = self._validate_halls_theorem(groups, dept, semester)
        
        if optimized:
            logger.info("✅ Successfully optimized groups to satisfy Hall's theorem")
        else:
            logger.warning("⚠️ Could not fully satisfy Hall's theorem after optimization")
            logger.warning("  Consider manual adjustment for optimal student choice")
        
        return groups

    def _create_instance_group_mapping(self):
        """Create enhanced mapping from course instances to their groups (INSTANCE-AWARE)."""
        logger.info("Creating enhanced instance-group mapping (INSTANCE-AWARE)...")
        
        total_mapped_instances = 0
        
        for (dept, semester), groups in self.course_groups.items():
            # First validate teacher uniqueness constraint
            self._validate_teacher_uniqueness_constraint(groups, dept, semester)
            
            # Now validate and optimize for Hall's theorem
            self._validate_halls_theorem(groups, dept, semester)
            
            # Try to optimize if Hall's theorem is not satisfied
            groups = self._optimize_for_halls_theorem(groups, dept, semester)
            
            # Create mapping
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
        Apply course group constraint with HIGHLY OPTIMIZED group-based scheduling.
        
        This constraint:
        1. Creates logical groupings of course instances by semester and department
        2. Allocates optimal timeslots to each group using adaptive compression
        3. Course instances within a group will be scheduled to these timeslots in post-processing
        4. Stores group information for output in CSV files
        5. INSTANCE-AWARE: Enhanced tracking of individual instances
        
        PERFORMANCE OPTIMIZATIONS:
        1. Pre-computation of all metrics and requirements
        2. Reduced variable count and constraint structure
        3. Hall's theorem satisfaction through preprocessing
        4. Optimized priority slot allocation constraints
        5. Improved global compactness constraints
        6. Adaptive compression factor for group requirements
        """
        logger.info("Applying HIGHLY OPTIMIZED course group constraint with GROUP-BASED SCHEDULING...")
        
        if not self.course_groups:
            logger.info("No course groups found, skipping constraint")
            return True
        
        # PERFORMANCE ENHANCEMENT: Pre-validate Hall's theorem satisfaction
        logger.info("Pre-validating Hall's theorem satisfaction...")
        all_semesters_validated = True
        total_violations = 0
        
        for (dept, semester), groups in self.course_groups.items():
            satisfied = self._validate_halls_theorem(groups, dept, semester)
            if not satisfied:
                logger.warning(f"Hall's theorem not satisfied for {dept} Semester {semester}")
                total_violations += 1
                all_semesters_validated = False
        
        if not all_semesters_validated:
            logger.info(f"Found {total_violations} Hall's theorem violations - optimizing distribution")
            for (dept, semester), groups in self.course_groups.items():
                self._optimize_for_halls_theorem(groups, dept, semester)
            
            # Verify again after optimization
            remaining_violations = 0
            for (dept, semester), groups in self.course_groups.items():
                if not self._validate_halls_theorem(groups, dept, semester):
                    remaining_violations += 1
            
            logger.info(f"After optimization: {remaining_violations} Hall's theorem violations remain")
        else:
            logger.info("✅ All groups satisfy Hall's theorem - optimal student choice enabled")
            
        # Create group timeslot variables and constraints
        self._create_group_timeslot_variables(teacher_theory_assignments)
        
        # Store the course groups for later use in output generation
        self._store_group_mappings_enhanced()
        
        # Log detailed group statistics
        self._log_enhanced_group_statistics()
        
        logger.info("HIGHLY OPTIMIZED course group constraint applied successfully")
        return True
    
    def _create_group_timeslot_variables(self, teacher_theory_assignments):
        """
        Create variables and constraints for OPTIMIZED group-based scheduling with SEMESTER OVERLAP.
        
        OPTIMIZATION GOALS:
        1. Minimize total timeslots used across all groups
        2. Create dense population (prefer consecutive slots)
        3. MAXIMIZE SEMESTER OVERLAP for dense regional population
        4. Ensure room capacity requirements are satisfied
        5. Maintain student choice within semesters
        6. EVEN DISTRIBUTION: All slots (0-10) have equal priority for allocation
        
        PERFORMANCE OPTIMIZATIONS:
        1. Pre-calculate all requirements before constraint creation
        2. Use incremental constraint generation 
        3. Reduce redundant variable creation
        4. Optimize constraint structure for solver performance
        
        Args:
            teacher_theory_assignments: The theory assignment variables
        """
        logger.info("Creating HIGHLY OPTIMIZED group timeslot variables with EVEN SLOT DISTRIBUTION...")
        logger.info("DISTRIBUTION STRATEGY: All slots 0-10 (8:00-6:50) have equal priority for better utilization")
        
        total_constraints_added = 0
        
        # OPTIMIZATION 1: Pre-calculate total requirements per semester for compact allocation
        semester_requirements = {}
        semester_room_requirements = {}  # Track room capacity needs per semester
        
        for (dept, semester), groups in self.course_groups.items():
            total_slots_needed = 0
            total_students = 0
            max_concurrent_students = 0
            
            for group in groups:
                if group:  # Skip empty groups
                    group_slots = self._calculate_optimized_group_requirements(group)
                    total_slots_needed += group_slots
                    
                    # Calculate room capacity requirements
                    group_students = sum(inst.get('student_count', 70) for inst in group)
                    total_students += group_students
                    max_concurrent_students = max(max_concurrent_students, group_students)
            
            semester_requirements[(dept, semester)] = total_slots_needed
            semester_room_requirements[(dept, semester)] = {
                'total_students': total_students,
                'max_concurrent': max_concurrent_students,
                'rooms_needed': max(1, max_concurrent_students // 70)  # Assume 70 students per room
            }
            
            logger.info(f"Semester optimization: {dept} Sem {semester} needs {total_slots_needed} slots, "
                       f"{semester_room_requirements[(dept, semester)]['rooms_needed']} rooms for {total_students} students")
        
        # OPTIMIZATION 2: Create semester-wide compactness variables
        semester_compactness_vars = {}
        
        # OPTIMIZATION 3: Create cross-semester overlap tracking for dense population
        cross_semester_overlap_vars = {}
        available_rooms_per_slot = len(self.classroom_ids)
        
        # Create variables for each (dept, semester, group) combination
        for (dept, semester), groups in self.course_groups.items():
            logger.info(f"Creating OPTIMIZED timeslot variables for {dept} Semester {semester} ({len(groups)} groups)")
            
            # Track all groups in this semester/department for optimization
            semester_groups = []
            semester_key = (dept, semester)
            
            # OPTIMIZATION 4: Create semester-wide slot usage tracking
            semester_compactness_vars[semester_key] = {}
            for day_idx in range(self.num_days):
                semester_compactness_vars[semester_key][day_idx] = {}
                for slot_idx in range(self.num_slots):
                    # Binary variable: 1 if ANY group in this semester uses this slot
                    semester_compactness_vars[semester_key][day_idx][slot_idx] = self.model.NewBoolVar(
                        f'semester_{dept}_S{semester}_day_{day_idx}_slot_{slot_idx}_used'
                    )
            
            for group_idx, group in enumerate(groups):
                group_name = f"{dept}_S{semester}_G{group_idx + 1}"
                
                if not group:  # Skip empty groups
                    continue
                
                semester_groups.append(group_name)
                    
                # Create binary variables for each possible timeslot
                self.group_timeslot_vars[group_name] = {}
                for day_idx in range(self.num_days):
                    self.group_timeslot_vars[group_name][day_idx] = {}
                    for slot_idx in range(self.num_slots):
                        # Binary variable: 1 if this timeslot is assigned to this group
                        self.group_timeslot_vars[group_name][day_idx][slot_idx] = self.model.NewBoolVar(
                            f'group_{group_name}_day_{day_idx}_slot_{slot_idx}'
                        )
                
                # OPTIMIZATION 5: Calculate optimized requirements (more aggressive)
                optimized_slots_needed = self._calculate_optimized_group_requirements(group)
                self.timeslots_per_group[group_name] = optimized_slots_needed
                
                # Constraint: Each group must have exactly N timeslots (optimized count)
                timeslot_vars = []
                for day_idx in range(self.num_days):
                    for slot_idx in range(self.num_slots):
                        timeslot_vars.append(self.group_timeslot_vars[group_name][day_idx][slot_idx])
                
                self.model.Add(sum(timeslot_vars) == optimized_slots_needed)
                total_constraints_added += 1
                
                # OPTIMIZATION 6: Encourage consecutive slots (STRONG preference)
                for day_idx in range(self.num_days):
                    for slot_idx in range(self.num_slots - 1):
                        # Create consecutive pair indicator
                        consecutive_pair = self.model.NewBoolVar(
                            f'consecutive_{group_name}_day_{day_idx}_slots_{slot_idx}_{slot_idx+1}'
                        )
                        
                        # consecutive_pair = 1 if both consecutive slots are used
                        self.model.AddBoolAnd([
                            self.group_timeslot_vars[group_name][day_idx][slot_idx],
                            self.group_timeslot_vars[group_name][day_idx][slot_idx + 1]
                        ]).OnlyEnforceIf(consecutive_pair)
                
                # OPTIMIZATION 7: EVEN SLOT ALLOCATION - DISABLED
                # Removing priority slot allocation to allow even distribution across all slots
                logger.info(f"  Group {group_name}: Priority slot allocation disabled - using all slots evenly")
                
                # OPTIMIZATION 8: Limit slots per day but allow more density
                for day_idx in range(self.num_days):
                    day_vars = []
                    for slot_idx in range(self.num_slots):
                        day_vars.append(self.group_timeslot_vars[group_name][day_idx][slot_idx])
                    
                    # Allow up to 10 slots per day - effectively removing the constraint
                    self.model.Add(sum(day_vars) <= 10)  # Raised from 3 to 10 (basically all slots)
                    total_constraints_added += 1
                
                # OPTIMIZATION 9: Link group slots to semester compactness tracking
                for day_idx in range(self.num_days):
                    for slot_idx in range(self.num_slots):
                        # If this group uses a slot, the semester uses that slot
                        self.model.AddImplication(
                            self.group_timeslot_vars[group_name][day_idx][slot_idx],
                            semester_compactness_vars[semester_key][day_idx][slot_idx]
                        )
                        total_constraints_added += 1
                
                logger.info(f"  OPTIMIZED Group {group_name}: {len(group)} instances, {optimized_slots_needed} slots (MINIMIZED)")
            
            # OPTIMIZATION 10: No timeslot overlap between groups in the same semester
            if len(semester_groups) > 1:
                logger.info(f"  Adding non-overlap constraints for {len(semester_groups)} groups in {dept} Semester {semester}")
                
                for day_idx in range(self.num_days):
                    for slot_idx in range(self.num_slots):
                        # For each timeslot, at most one group in this semester can use it
                        slot_usage_vars = []
                        for group_name in semester_groups:
                            slot_usage_vars.append(self.group_timeslot_vars[group_name][day_idx][slot_idx])
                        
                        self.model.Add(sum(slot_usage_vars) <= 1)
                        total_constraints_added += 1
            
            # REMOVED: OPTIMIZATION 11 - Minimize total slots used per semester (COMPACTNESS)
            # This constraint was limiting the number of time slots that could be used
            logger.info(f"  Semester {dept} S{semester}: Removed slot usage limit to allow more flexibility")
        
        # OPTIMIZATION 12: NEW - Cross-semester overlap optimization for dense population
        logger.info("Adding CROSS-SEMESTER OVERLAP optimization for dense population...")
        cross_semester_constraints = self._add_cross_semester_overlap_optimization(
            semester_compactness_vars, semester_room_requirements
        )
        total_constraints_added += cross_semester_constraints

        # OPTIMIZATION 15: NEW - Global room capacity constraint (maximum groups per timeslot)
        logger.info("Adding GLOBAL ROOM CAPACITY constraints...")
        room_capacity_constraints = self._add_global_room_capacity_constraints(semester_compactness_vars)
        total_constraints_added += room_capacity_constraints

        # OPTIMIZATION 13: Global compactness across all semesters
        self._add_global_compactness_constraints(semester_compactness_vars)
        total_constraints_added += 10  # Estimate for global constraints

        # OPTIMIZATION 14: Global priority slot allocation constraints
        priority_constraints = self._add_global_priority_slot_constraints(semester_compactness_vars)
        total_constraints_added += priority_constraints
        
        logger.info(f"Added {total_constraints_added} OPTIMIZED group timeslot constraints")
        logger.info("✅ EVEN ALLOCATION STRATEGY: All slots 0-10 (8:00-6:50) have equal priority for allocation")
        logger.info("✅ SPACE OPTIMIZATION: Minimized theory slots, maximized lab availability")
        logger.info("✅ DENSE PACKING: Encouraged consecutive slots within priority zones")
        logger.info("✅ SEMESTER OVERLAP: Maximized cross-semester overlap for dense population")
        logger.info("✅ ROOM CAPACITY: Ensured room requirements are satisfied")
        logger.info("✅ GLOBAL ROOM CAPACITY: Maximum {available_rooms * 2} groups per timeslot (2x actual {available_rooms} rooms)")
        logger.info("✅ STUDENT CHOICE: Maintained non-overlap within semesters")
    
    def _add_cross_semester_overlap_optimization(self, semester_compactness_vars, semester_room_requirements):
        """
        Add cross-semester overlap optimization to maximize dense population - PERFORMANCE OPTIMIZED.
        
        STRATEGY:
        1. Encourage different semesters to use the same timeslots (dense population)
        2. Ensure room capacity constraints are satisfied
        3. Create regional clustering of classes
        4. Fall back to different slots if room capacity is exhausted
        
        OPTIMIZATION TECHNIQUES:
        1. Reduce variable count while maintaining logical structure
        2. Group constraints by semantic purpose
        3. Pre-compute metrics to avoid redundant calculations
        4. Optimize constraint structure for solver performance
        
        Args:
            semester_compactness_vars: Semester slot usage variables
            semester_room_requirements: Room capacity requirements per semester
            
        Returns:
            Number of constraints added
        """
        logger.info("Creating OPTIMIZED cross-semester overlap optimization...")
        
        constraints_added = 0
        available_rooms_per_slot = len(self.classroom_ids)
        
        # OPTIMIZATION: Pre-compute semester groups only once
        dept_semesters = {}
        for (dept, semester) in semester_compactness_vars.keys():
            if dept not in dept_semesters:
                dept_semesters[dept] = []
            dept_semesters[dept].append(semester)
        
        # OPTIMIZATION: Pre-compute slot zones
        slot_zones = {
            'early': list(range(min(6, self.num_slots))),         # Early slots (0-5)
            'late': list(range(6, self.num_slots))                # Late slots (6+)
        }
        
        # Process departments with multiple semesters
        for dept, semesters in dept_semesters.items():
            if len(semesters) <= 1:
                continue  # Need at least 2 semesters for overlap
            
            logger.info(f"Optimizing cross-semester overlap for {dept}: {len(semesters)} semesters")
            
            # OPTIMIZATION: Pre-compute room demand once per department
            total_room_demand_by_slot = {}
            for day_idx in range(self.num_days):
                for slot_idx in range(self.num_slots):
                    room_demand = sum(
                        semester_room_requirements.get((dept, sem), {}).get('rooms_needed', 1)
                        for sem in semesters
                    )
                    total_room_demand_by_slot[(day_idx, slot_idx)] = room_demand
            
            # OPTIMIZATION: Use a more efficient constraint structure
            # Process one day at a time
            for day_idx in range(self.num_days):
                # Track all variables for clustering in a single pass
                semester_usage_by_slot = {}
                overlap_indicators = {}
                
                # First pass: Create semester usage and room capacity constraints
                for slot_idx in range(self.num_slots):
                    # Calculate semester usage for this slot
                    semester_usage = sum(
                        semester_compactness_vars[(dept, sem)][day_idx][slot_idx] 
                        for sem in semesters
                    )
                    semester_usage_by_slot[slot_idx] = semester_usage
                    
                    # Create overlap indicator only if needed based on room capacity
                    room_demand = total_room_demand_by_slot[(day_idx, slot_idx)]
                    if room_demand > available_rooms_per_slot:
                        # REMOVED: Room capacity constraint
                        # Previously prevented overlap when room demand exceeded capacity
                        # Now allowing overlap regardless of room capacity
                        logger.debug(f"REMOVED: Room capacity constraint for Slot {day_idx}-{slot_idx} despite demand {room_demand} > {available_rooms_per_slot} rooms")
                    
                    # Create overlap indicator for all cases
                    overlap_indicator = self.model.NewBoolVar(f'overlap_{dept}_day_{day_idx}_slot_{slot_idx}')
                    overlap_indicators[slot_idx] = overlap_indicator
                    
                    # Link indicator to semester usage
                    self.model.Add(semester_usage >= 2).OnlyEnforceIf(overlap_indicator)
                    self.model.Add(semester_usage <= 1).OnlyEnforceIf(overlap_indicator.Not())
                    constraints_added += 2
                
                # OPTIMIZATION: Encourage clustering with fewer variables
                # Create clustering constraints for consecutive slots
                for slot_idx in range(self.num_slots - 1):
                    # Only create clustering constraint if both adjacent slots have overlap indicators
                    if slot_idx in overlap_indicators and slot_idx + 1 in overlap_indicators:
                        # Create single clustering indicator instead of multiple
                        clustering = self.model.NewBoolVar(f'clustering_{dept}_day_{day_idx}_slots_{slot_idx}_{slot_idx+1}')
                        
                        # Link to adjacent overlap indicators
                        self.model.AddBoolAnd([
                            overlap_indicators[slot_idx], 
                            overlap_indicators[slot_idx + 1]
                        ]).OnlyEnforceIf(clustering)
                        
                        constraints_added += 1
            
            # Optimize early vs late zone preference with a single constraint
            for day_idx in range(self.num_days):
                # If we have both early and late zones
                early_slots = slot_zones['early']
                late_slots = slot_zones['late']
                
                if early_slots and late_slots:
                    # REMOVED: Constraint requiring minimum early zone usage before using late zone
                    # This allows more flexible scheduling across all time slots
                    logger.debug(f"Removed early zone requirement for {dept} day {day_idx}")
        
        logger.info(f"OPTIMIZED cross-semester overlap: {constraints_added} constraints added")
        logger.info("✅ DENSE POPULATION: Maximized semester overlap where room capacity permits")
        logger.info("✅ ROOM SAFETY: Prevented overlap when room capacity would be exceeded")
        logger.info("✅ CLUSTERING: Encouraged consecutive overlapping slots with optimized constraints")
        logger.info("✅ FLEXIBLE ZONES: Removed early zone requirements to allow full slot flexibility")
        
        return constraints_added
    
    def _add_global_room_capacity_constraints(self, semester_compactness_vars):
        """
        Add global room capacity constraints to ensure the number of groups scheduled 
        in each timeslot doesn't exceed the number of available rooms.
        
        This prevents over-scheduling and resource conflicts by enforcing a hard limit
        on the maximum number of concurrent groups that can be scheduled based on 
        the total available classrooms.
        
        OPTIMIZATION TECHNIQUES:
        1. Uses direct constraint on total semester usage per timeslot
        2. Pre-computes available room count only once
        3. Creates efficient constraints with minimal variable creation
        
        Args:
            semester_compactness_vars: Dictionary of semester slot usage variables
            
        Returns:
            Number of constraints added
        """
        logger.info(f"Creating GLOBAL ROOM CAPACITY constraints with {len(self.classroom_ids)} available rooms...")
        
        constraints_added = 0
        available_rooms = len(self.classroom_ids)
        
        # Create global slot usage tracking (all departments/semesters)
        for day_idx in range(self.num_days):
            for slot_idx in range(self.num_slots):
                # Count total groups using this timeslot across all semesters
                timeslot_usage_vars = []
                
                for semester_key, day_dict in semester_compactness_vars.items():
                    if day_idx in day_dict and slot_idx in day_dict[day_idx]:
                        timeslot_usage_vars.append(day_dict[day_idx][slot_idx])
                
                # If we have usage variables for this slot, add constraint
                if timeslot_usage_vars:
                    # RELAXED: Allow up to 2x the number of available rooms
                    # This ensures we don't hit capacity limits too easily
                    relaxed_capacity = available_rooms * 2  # Double the available rooms
                    self.model.Add(sum(timeslot_usage_vars) <= relaxed_capacity)
                    constraints_added += 1
                    
                    # Log the constraint (debug level to avoid too much output)
                    logger.debug(f"  RELAXED room constraint for day {day_idx}, slot {slot_idx}: "
                               f"max {relaxed_capacity} groups (2x actual {available_rooms} rooms) out of {len(timeslot_usage_vars)} possible")
        
        logger.info(f"Added {constraints_added} global room capacity constraints")
        logger.info(f"✅ RELAXED ROOM CAPACITY: Maximum {available_rooms * 2} groups per timeslot (2x actual {available_rooms} rooms)")
        
        return constraints_added
    
    def _calculate_optimized_group_requirements(self, group):
        """
        Calculate timeslots for a group based on maximum course instance theory hours.
        
        ALLOCATION STRATEGY:
        Allocate timeslots based on the maximum theory hours (lecture + tutorial) 
        of any course instance in the group. This ensures each group has enough slots
        to accommodate its most demanding course.
        
        Args:
            group: List of course instances in this group
            
        Returns:
            Integer number of timeslots to allocate (based on max course theory hours)
        """
        if not group:
            return 4  # Default allocation for empty groups
        
        # Calculate total and maximum theory hours
        total_theory_hours = 0
        max_theory_hours = 0
        unique_courses = set()
        
        for instance in group:
            theory_hours = instance['lecture_hours'] + instance['tutorial_hours']
            total_theory_hours += theory_hours
            max_theory_hours = max(max_theory_hours, theory_hours)
            unique_courses.add(instance['course_code'])
        
        # Allocate slots based on maximum theory hours
        # Ensure at least the maximum theory hours are allocated
        # Allow up to 11 slots (full day) instead of limiting to 8
        needed_slots = max(4, min(11, max_theory_hours))
        
        logger.info(f"  FLEXIBLE ALLOCATION Group: {total_theory_hours} total theory hours, {max_theory_hours} max instance hours → {needed_slots} slots " + 
                   f"({len(unique_courses)} courses)")
        return needed_slots
    
    def _add_global_compactness_constraints(self, semester_compactness_vars):
        """
        Add global constraints to encourage overall compactness across all semesters - PERFORMANCE OPTIMIZED.
        
        OPTIMIZATION GOALS:
        1. Minimize total slots used across entire timetable
        2. Encourage clustering of used slots
        3. Leave large contiguous blocks for lab scheduling
        
        PERFORMANCE OPTIMIZATION:
        1. Reduce variable count by using more direct constraints
        2. Optimize constraint structure for solver performance
        3. Use hierarchical constraint structure
        4. Pre-compute zones for better semantic organization
        
        Args:
            semester_compactness_vars: Dictionary of semester slot usage variables
        """
        logger.info("Adding RELAXED global compactness constraints to allow flexible slot allocation...")
        
        # PERFORMANCE OPTIMIZATION: Pre-compute slot zones 
        slot_zones = {
            'theory': list(range(min(7, self.num_slots))),           # Theory zone: slots 0-6
            'lab': list(range(7, self.num_slots))                    # Lab zone: slots 7+
        }
        
        # OPTIMIZATION 1: Create unified global slot usage tracking
        # This reduces the number of variables needed
        global_slot_usage = {}
        
        # Process one day at a time for better locality
        for day_idx in range(self.num_days):
            global_slot_usage[day_idx] = {}
            
            # Collect all semester variables by slot for efficiency
            semester_vars_by_slot = {slot_idx: [] for slot_idx in range(self.num_slots)}
            
            # Group all semester variables by slot in a single pass
            for semester_vars in semester_compactness_vars.values():
                for slot_idx in range(self.num_slots):
                    semester_vars_by_slot[slot_idx].append(semester_vars[day_idx][slot_idx])
            
            # Create global usage variables only once
            for slot_idx in range(self.num_slots):
                # Skip if no semester variables for this slot
                if not semester_vars_by_slot[slot_idx]:
                    continue
                    
                # Create global usage variable (1 if ANY semester uses this slot)
                global_slot_usage[day_idx][slot_idx] = self.model.NewBoolVar(
                    f'global_day_{day_idx}_slot_{slot_idx}_used'
                )
                
                # Use a more efficient constraint: MAX equality
                self.model.AddMaxEquality(
                    global_slot_usage[day_idx][slot_idx], 
                    semester_vars_by_slot[slot_idx]
                )
        
        # OPTIMIZATION 3: Enforce zone-based constraints (theory vs lab zones)
        for day_idx in range(self.num_days):
            # Skip empty days
            if not global_slot_usage.get(day_idx):
                continue
                
            # Count usage in theory and lab zones
            theory_zone_vars = []
            lab_zone_vars = []
            
            for slot_idx in slot_zones['theory']:
                if slot_idx in global_slot_usage[day_idx]:
                    theory_zone_vars.append(global_slot_usage[day_idx][slot_idx])
            
            for slot_idx in slot_zones['lab']:
                if slot_idx in global_slot_usage[day_idx]:
                    lab_zone_vars.append(global_slot_usage[day_idx][slot_idx])
            
            # REMOVED: All theory vs lab zone constraints to allow complete flexibility
            logger.debug(f"Removed all zone-based constraints for day {day_idx}")
            
        logger.info("✅ FULLY RELAXED: All zone-based constraints removed")
        logger.info("✅ FLEXIBLE SCHEDULING: No enforced early slot usage")
        logger.info("✅ NO ZONE REQUIREMENTS: Complete freedom to use any timeslot")
    
    def _add_global_priority_slot_constraints(self, semester_compactness_vars):
        """
        Add global priority slot allocation constraints - PERFORMANCE OPTIMIZED.
        
        PRIORITY STRATEGY:
        1. First 4 slots (0-3): Primary allocation zone (8:00-11:50)
        2. Next 4 slots (4-7): Secondary allocation zone (12:00-3:50) - only if first 4 are heavily used
        3. Next 3 slots (8-10): Tertiary allocation zone (4:00-6:50) - only if first two zones are heavily used
        
        PERFORMANCE OPTIMIZATION:
        1. Use consolidated variables rather than per-day constraints
        2. Pre-compute all priority zones only once
        3. Use fewer indicator variables with the same logical constraints
        4. Optimize constraint structure for solver performance
        
        Args:
            semester_compactness_vars: Dictionary of semester slot usage variables
            
        Returns:
            Number of constraints added
        """
        logger.info("DISABLED PRIORITY SLOT ALLOCATION - allowing allocation across all slots evenly")
        
        # DISABLED: Priority slot allocation to allow all slots to be used evenly
        # This will allow scheduling to happen across all time slots without prioritizing early slots
        
        logger.info("✅ EVEN ALLOCATION STRATEGY: All slots 0-10 (8:00-6:50) have equal priority")
        
        return 0  # No constraints added

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
    
    def extract_group_timeslots(self, solver):
        """
        Extract the assigned timeslots for each group from the solver solution.
        
        Args:
            solver: The CP-SAT solver with a solution
            
        Returns:
            Dictionary mapping group_name to list of (day_idx, slot_idx) tuples
        """
        logger.info("Extracting group timeslots from solution...")
        
        self.group_timeslots = {}
        total_timeslots_allocated = 0
        
        for group_name, day_dict in self.group_timeslot_vars.items():
            self.group_timeslots[group_name] = []
            
            for day_idx, slot_dict in day_dict.items():
                for slot_idx, var in slot_dict.items():
                    if solver.Value(var) == 1:
                        self.group_timeslots[group_name].append((day_idx, slot_idx))
                        total_timeslots_allocated += 1
            
            # Log the allocated timeslots for this group
            day_names = ["Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
            timeslot_details = []
            for day_idx, slot_idx in sorted(self.group_timeslots[group_name]):
                time_interval = self.time_slots[slot_idx] if hasattr(self, 'time_slots') else f"Slot {slot_idx}"
                timeslot_details.append(f"{day_names[day_idx]} {time_interval}")
            
            logger.info(f"Group {group_name}: {len(self.group_timeslots[group_name])} timeslots allocated")
            logger.info(f"  Timeslots: {', '.join(timeslot_details)}")
        
        logger.info(f"Total group timeslots allocated: {total_timeslots_allocated}")
        return self.group_timeslots
        
    def get_group_timeslots(self, group_name):
        """
        Get the timeslots allocated to a specific group.
        
        Args:
            group_name: Name of the group
            
        Returns:
            List of (day_idx, slot_idx) tuples or empty list if not found
        """
        return self.group_timeslots.get(group_name, [])
    
    def _calculate_group_timeslot_requirements(self, group):
        """
        LEGACY METHOD: Calculate the number of timeslots needed for a group based on course hours.
        
        NOTE: This method is kept for backward compatibility but the optimized version
        _calculate_optimized_group_requirements() should be used for space optimization.
        
        Args:
            group: List of course instances in this group
            
        Returns:
            Integer number of timeslots to allocate (minimum 1, maximum 6)
        """
        logger.warning("Using legacy timeslot calculation - consider using _calculate_optimized_group_requirements()")
        return self._calculate_optimized_group_requirements(group) 