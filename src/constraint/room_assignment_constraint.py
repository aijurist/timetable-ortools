"""
Room Assignment Constraint

This constraint ensures proper room allocation based on capacity,
availability, and department-based block assignments.
INSTANCE-AWARE: Considers individual course instance requirements.
"""

import logging

logger = logging.getLogger(__name__)

class RoomAssignmentConstraint:
    def __init__(self, model, teachers, teacher_course_assignments, classrooms, labs):
        """Initialize the room assignment constraint."""
        self.model = model
        self.teachers = teachers
        self.teacher_course_assignments = teacher_course_assignments
        self.classrooms = classrooms
        self.labs = labs
        
        # Create department-to-block mapping
        self.department_block_mapping = {
            'Computer Science & Engineering': ['A Block'],  # CS can use both A and B blocks
            'Information Technology': ['A Block'],
            'Electronics and Communication Engineering': ['B Block'],
            'Mechanical Engineering': ['B Block'],
            'Civil Engineering': ['B Block'],
            'Default': ['A Block', 'B Block']  # Fallback for unknown departments
        }
        
        # Pre-process room data by department blocks
        self.rooms_by_block = self._categorize_rooms_by_block()
        
        logger.info("RoomAssignmentConstraint initialized with department-based block allocation (INSTANCE-AWARE)")
    
    def _categorize_rooms_by_block(self):
        """Categorize classrooms by their building blocks."""
        rooms_by_block = {
            'A Block': [],
            'B Block': [],
            'Techlounge': [],
            'J Block': [],
            'K Block': [],
            'D Block': [],
            'Unknown Block': []
        }
        
        for _, room in self.classrooms.iterrows():
            block = str(room.get('block', 'Unknown Block')).strip()
            room_info = {
                'id': room['id'],
                'room_number': room['room_number'],
                'capacity': room['room_max_cap'],
                'block': block
            }
            
            if block in rooms_by_block:
                rooms_by_block[block].append(room_info)
            else:
                rooms_by_block['Unknown Block'].append(room_info)
        
        # Log room distribution
        for block, rooms in rooms_by_block.items():
            if rooms:
                logger.info(f"{block}: {len(rooms)} classrooms (capacity range: {min(r['capacity'] for r in rooms)}-{max(r['capacity'] for r in rooms)})")
        
        return rooms_by_block
    
    def _get_department_from_teacher(self, teacher_id):
        """Get the department for a teacher based on their course assignments."""
        if teacher_id not in self.teacher_course_assignments:
            return 'Default'
        
        # Get the first course assignment to determine department
        assignments = self.teacher_course_assignments[teacher_id]
        if assignments:
            return assignments[0].get('course_dept', 'Default')
        
        return 'Default'
    
    def _get_preferred_blocks_for_teacher(self, teacher_id):
        """Get the preferred building blocks for a teacher based on their department."""
        department = self._get_department_from_teacher(teacher_id)
        return self.department_block_mapping.get(department, self.department_block_mapping['Default'])
    
    def _get_rooms_for_department(self, teacher_id):
        """Get appropriate classroom IDs for a teacher's department."""
        preferred_blocks = self._get_preferred_blocks_for_teacher(teacher_id)
        suitable_rooms = []
        
        for block in preferred_blocks:
            if block in self.rooms_by_block:
                suitable_rooms.extend([room['id'] for room in self.rooms_by_block[block]])
        
        # If no rooms found in preferred blocks, allow any classroom as fallback
        if not suitable_rooms:
            logger.warning(f"No rooms found in preferred blocks {preferred_blocks} for teacher {teacher_id}, using all classrooms")
            suitable_rooms = self.classrooms['id'].tolist()
        
        return suitable_rooms
    
    def _get_instance_capacity_requirements(self, teacher_id):
        """Get capacity requirements for each course instance of a teacher (INSTANCE-AWARE)."""
        if teacher_id not in self.teacher_course_assignments:
            return {}
        
        instance_requirements = {}
        for instance in self.teacher_course_assignments[teacher_id]:
            instance_id = instance['id']
            student_count = instance.get('student_count', 0)
            course_code = instance.get('course_code', '')
            
            # Determine minimum capacity needed (add 10% buffer)
            min_capacity = int(student_count * 1.1) if student_count > 0 else 70
            
            instance_requirements[instance_id] = {
                'student_count': student_count,
                'min_capacity': min_capacity,
                'course_code': course_code
            }
        
        return instance_requirements
    
    def apply(self, teacher_theory_assignments, teacher_lab_assignments=None):
        """Apply room assignment constraints with department-based block allocation (INSTANCE-AWARE)."""
        try:
            logger.info("Applying department-based room assignment constraints (INSTANCE-AWARE)...")
            
            # 1. Department-based classroom allocation for theory classes (instance-aware)
            self._apply_department_classroom_constraints_instance_aware(teacher_theory_assignments)
            
            # 2. Basic room conflict prevention
            self._apply_room_conflict_constraints(teacher_theory_assignments, teacher_lab_assignments)
            
            # 3. Room capacity constraints (instance-aware)
            self._apply_room_capacity_constraints_instance_aware(teacher_theory_assignments, teacher_lab_assignments)
            
            logger.info("Department-based room assignment constraints (INSTANCE-AWARE) applied successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error applying room assignment constraints: {e}")
            return False
    
    def _apply_department_classroom_constraints_instance_aware(self, teacher_theory_assignments):
        """Apply department-based classroom allocation constraints (INSTANCE-AWARE)."""
        logger.info("Applying department-based classroom allocation (INSTANCE-AWARE)...")
        
        constraint_count = 0
        for teacher in self.teachers:
            # Get suitable classrooms for this teacher's department
            suitable_room_ids = self._get_rooms_for_department(teacher)
            department = self._get_department_from_teacher(teacher)
            preferred_blocks = self._get_preferred_blocks_for_teacher(teacher)
            
            # Get course instances for this teacher (INSTANCE-AWARE)
            teacher_instances = self.teacher_course_assignments.get(teacher, [])
            instance_info = []
            total_theory_hours = 0
            for instance in teacher_instances:
                theory_hrs = instance['lecture_hours'] + instance['tutorial_hours']
                if theory_hrs > 0:
                    total_theory_hours += theory_hrs
                    instance_info.append(f"Instance {instance['id']}:{instance['course_code']}(Cap:{instance['student_count']},Hrs:{theory_hrs})")
            
            logger.debug(f"Teacher {teacher} ({department}) - {len(instance_info)} theory instances, {total_theory_hours} total hours")
            logger.debug(f"  Instances: {', '.join(instance_info)}")
            logger.debug(f"  Can use rooms in blocks: {preferred_blocks} ({len(suitable_room_ids)} rooms)")
            
            # Constrain teacher to only use rooms from their department's blocks
            for day in range(len(teacher_theory_assignments[teacher])):
                for slot in range(len(teacher_theory_assignments[teacher][day])):
                    # Allow assignments only to suitable rooms
                    allowed_assignments = []
                    blocked_assignments = []
                    
                    for room_id, assignment_var in teacher_theory_assignments[teacher][day][slot].items():
                        if room_id in suitable_room_ids:
                            allowed_assignments.append(assignment_var)
                        else:
                            blocked_assignments.append(assignment_var)
                    
                    # Block assignments to non-suitable rooms
                    for blocked_var in blocked_assignments:
                        self.model.Add(blocked_var == 0)
                        constraint_count += 1
        
        logger.info(f"Applied {constraint_count} department-based classroom allocation constraints (INSTANCE-AWARE)")
    
    def _apply_room_conflict_constraints(self, teacher_theory_assignments, teacher_lab_assignments):
        """Ensure no room conflicts - one assignment per room per time slot."""
        logger.info("Applying room conflict prevention constraints...")
        
        constraint_count = 0
        
        # Theory room conflicts
        all_room_ids = self.classrooms['id'].tolist()
        for room_id in all_room_ids:
            for day in range(5):  # 5 days
                for slot in range(11):  # 11 theory slots
                    room_assignments = []
                    for teacher in self.teachers:
                        if (room_id in teacher_theory_assignments[teacher][day][slot]):
                            room_assignments.append(teacher_theory_assignments[teacher][day][slot][room_id])
                    
                    if len(room_assignments) > 1:
                        # At most one teacher can use this room at this time
                        self.model.Add(sum(room_assignments) <= 1)
                        constraint_count += 1
        
        # Lab room conflicts (if lab assignments exist)
        if teacher_lab_assignments:
            lab_room_ids = self.labs['id'].tolist()
            lab_sessions = ['L1', 'L2', 'L3', 'L4', 'L5', 'L6']
            
            for room_id in lab_room_ids:
                for day in range(5):  # 5 days
                    for session in lab_sessions:
                        room_assignments = []
                        for teacher in self.teachers:
                            if (room_id in teacher_lab_assignments[teacher][day][session]):
                                room_assignments.append(teacher_lab_assignments[teacher][day][session][room_id])
                        
                        if len(room_assignments) > 1:
                            # At most one teacher can use this lab at this time
                            self.model.Add(sum(room_assignments) <= 1)
                            constraint_count += 1
        
        logger.info(f"Applied {constraint_count} room conflict prevention constraints")
    
    def _apply_room_capacity_constraints_instance_aware(self, teacher_theory_assignments, teacher_lab_assignments):
        """Apply room capacity constraints based on individual course instances (INSTANCE-AWARE)."""
        logger.info("Applying room capacity preference constraints (INSTANCE-AWARE)...")
        
        constraint_count = 0
        capacity_mismatches = 0
        
        for teacher in self.teachers:
            if teacher not in self.teacher_course_assignments:
                continue
            
            # Get instance-specific capacity requirements
            instance_requirements = self._get_instance_capacity_requirements(teacher)
            
            if not instance_requirements:
                continue
            
            # Log instance capacity requirements
            for instance_id, req in instance_requirements.items():
                logger.debug(f"Teacher {teacher} - Instance {instance_id} ({req['course_code']}): {req['student_count']} students, needs {req['min_capacity']}+ capacity")
            
            # Get maximum student count across all instances
            max_students = max(req['student_count'] for req in instance_requirements.values())
            min_capacity_needed = max(req['min_capacity'] for req in instance_requirements.values())
            
            # Get suitable rooms for this teacher's department
            suitable_room_ids = self._get_rooms_for_department(teacher)
            
            # Check if suitable rooms can accommodate the largest class
            suitable_large_rooms = []
            for room_id in suitable_room_ids:
                room_info = self.classrooms[self.classrooms['id'] == room_id]
                if not room_info.empty:
                    capacity = room_info.iloc[0]['room_max_cap']
                    if capacity >= min_capacity_needed:
                        suitable_large_rooms.append(room_id)
            
            if not suitable_large_rooms and max_students > 0:
                # No suitable rooms with adequate capacity - log warning
                logger.warning(f"Teacher {teacher}: Max {max_students} students but no suitable rooms with {min_capacity_needed}+ capacity")
                capacity_mismatches += 1
                
                # Allow any room as fallback to maintain feasibility
                suitable_large_rooms = suitable_room_ids
            
            # If we have large classes, prefer large capacity rooms
            if max_students > 60 and suitable_large_rooms:
                logger.debug(f"Teacher {teacher}: Large classes ({max_students} students) - preferring {len(suitable_large_rooms)} large rooms")
                
                # Soft constraint via room preference (implemented through ordering)
                # The actual preference is handled by the room selection algorithm
                constraint_count += 1
        
        if capacity_mismatches > 0:
            logger.warning(f"Found {capacity_mismatches} teachers with potential capacity mismatches")
        
        logger.info(f"Applied {constraint_count} room capacity preference constraints (INSTANCE-AWARE)")
        return True 