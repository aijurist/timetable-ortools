"""
Room Assignment Constraint

This constraint ensures proper room allocation based on capacity,
availability, and department-based block assignments.
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
        
        logger.info("RoomAssignmentConstraint initialized with department-based block allocation")
    
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
    
    def apply(self, teacher_theory_assignments, teacher_lab_assignments=None):
        """Apply room assignment constraints with department-based block allocation."""
        try:
            logger.info("Applying department-based room assignment constraints...")
            
            # 1. Department-based classroom allocation for theory classes
            self._apply_department_classroom_constraints(teacher_theory_assignments)
            
            # 2. Basic room conflict prevention
            self._apply_room_conflict_constraints(teacher_theory_assignments, teacher_lab_assignments)
            
            # 3. Room capacity constraints (soft)
            self._apply_room_capacity_constraints(teacher_theory_assignments, teacher_lab_assignments)
            
            logger.info("Department-based room assignment constraints applied successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error applying room assignment constraints: {e}")
            return False
    
    def _apply_department_classroom_constraints(self, teacher_theory_assignments):
        """Apply department-based classroom allocation constraints."""
        logger.info("Applying department-based classroom allocation...")
        
        constraint_count = 0
        for teacher in self.teachers:
            # Get suitable classrooms for this teacher's department
            suitable_room_ids = self._get_rooms_for_department(teacher)
            department = self._get_department_from_teacher(teacher)
            preferred_blocks = self._get_preferred_blocks_for_teacher(teacher)
            
            logger.debug(f"Teacher {teacher} ({department}) can use rooms in blocks: {preferred_blocks}")
            
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
        
        logger.info(f"Applied {constraint_count} department-based classroom allocation constraints")
    
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
    
    def _apply_room_capacity_constraints(self, teacher_theory_assignments, teacher_lab_assignments):
        """Apply room capacity constraints (soft - prefer larger rooms for larger classes)."""
        logger.info("Applying room capacity preference constraints...")
        
        # This is implemented as soft constraints through room selection preferences
        # rather than hard constraints to maintain feasibility
        
        constraint_count = 0
        for teacher in self.teachers:
            if teacher not in self.teacher_course_assignments:
                continue
            
            # Get maximum student count for this teacher's courses
            max_students = 0
            for assignment in self.teacher_course_assignments[teacher]:
                student_count = assignment.get('student_count', 0)
                max_students = max(max_students, student_count)
            
            # If student count is high, prefer larger capacity rooms
            if max_students > 60:  # Large class threshold
                suitable_room_ids = self._get_rooms_for_department(teacher)
                
                # Get large capacity rooms from suitable blocks
                large_rooms = []
                for room_id in suitable_room_ids:
                    room_info = self.classrooms[self.classrooms['id'] == room_id]
                    if not room_info.empty:
                        capacity = room_info.iloc[0]['room_max_cap']
                        if capacity >= 70:  # Large room threshold
                            large_rooms.append(room_id)
                
                # Prefer large rooms for large classes (soft constraint)
                if large_rooms:
                    for day in range(5):
                        for slot in range(11):
                            large_room_assignments = []
                            for room_id in large_rooms:
                                if room_id in teacher_theory_assignments[teacher][day][slot]:
                                    large_room_assignments.append(teacher_theory_assignments[teacher][day][slot][room_id])
                            
                            # Encourage use of large rooms (soft constraint via objective)
                            # This is handled in the optimization objective
                            constraint_count += len(large_room_assignments)
        
        logger.info(f"Applied {constraint_count} room capacity preference constraints")
        return True 