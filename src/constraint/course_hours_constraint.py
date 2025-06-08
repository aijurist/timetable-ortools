"""
Course Hours Constraint

This constraint ensures correct hour allocation per course instance with minimal variables.
HIGHLY OPTIMIZED: Uses caching, pre-computation, and efficient constraint structure.
GROUP-BASED COMPATIBLE: Works with the new group-based scheduling approach.
"""

import logging
from .constraint_base import ConstraintBase

logger = logging.getLogger(__name__)

class CourseHoursConstraint(ConstraintBase):
    """Course hours constraint with minimal variable creation and efficient constraint structure."""
    
    def __init__(self, model, teachers, teacher_course_assignments, classrooms, labs):
        """Initialize with optimization-ready caching."""
        super().__init__(model, teachers, teacher_course_assignments, classrooms, labs)
        
        # OPTIMIZATION: Pre-compute and cache instance requirements
        self._instance_requirements_cache = {}
        self._teacher_requirements_cache = {}
        
        # Pre-compute all instance requirements
        self._precompute_all_requirements()
    
    def _precompute_all_requirements(self):
        """
        PERFORMANCE OPTIMIZATION: Pre-compute all instance and teacher requirements.
        This reduces redundant calculations during constraint application.
        """
        logger.info("Pre-computing instance and teacher requirements for performance optimization...")
        
        # Process all instances
        for teacher, instances in self.teacher_course_assignments.items():
            teacher_total_theory = 0
            teacher_total_practical = 0
            
            for instance in instances:
                instance_id = instance['id']
                
                # Cache instance requirements
                theory_hours = instance['lecture_hours'] + instance['tutorial_hours']
                practical_hours = instance['practical_hours']
                
                self._instance_requirements_cache[instance_id] = {
                    'total_theory_hours': theory_hours,
                    'practical_hours': practical_hours
                }
                
                # Accumulate teacher totals
                teacher_total_theory += theory_hours
                teacher_total_practical += practical_hours
            
            # Cache teacher requirements
            self._teacher_requirements_cache[teacher] = {
                'total_theory_hours': teacher_total_theory,
                'total_practical_hours': teacher_total_practical,
                'lab_sessions_required': sum(
                    max(1, (self._instance_requirements_cache[inst['id']]['practical_hours'] + 1) // 2)
                    for inst in instances
                    if self._instance_requirements_cache[inst['id']]['practical_hours'] > 0
                )
            }
        
        logger.info(f"Pre-computed requirements for {len(self._instance_requirements_cache)} instances and {len(self._teacher_requirements_cache)} teachers")
    
    def apply(self, teacher_theory_assignments, teacher_lab_assignments=None):
        """
        Apply course hours constraint ensuring proper hour allocation with high optimization.
        
        PERFORMANCE OPTIMIZATIONS:
        1. Uses cached requirements instead of recalculating
        2. Collects variables more efficiently
        3. Uses optimized constraint structure
        4. Reduces variable traversal with smarter iteration
        
        GROUP-BASED COMPATIBLE: With group-based scheduling, this constraint only ensures
        that total required hours per teacher are available across all groups.
        Post-processing will handle the actual hour distribution.
        """
        logger.info("Applying HIGHLY OPTIMIZED course hours constraint...")
        
        total_constraints_added = 0
        lab_assignments_enabled = teacher_lab_assignments is not None
        
        if not lab_assignments_enabled:
            logger.info("Lab assignments disabled - theory hours only")
        
        # PERFORMANCE OPTIMIZATION: Only process teachers with assignments
        teachers_with_theory = [t for t, req in self._teacher_requirements_cache.items() 
                              if req['total_theory_hours'] > 0]
        
        teachers_with_lab = [t for t, req in self._teacher_requirements_cache.items() 
                           if lab_assignments_enabled and req['total_practical_hours'] > 0]
        
        # Process theory assignments with optimized structure
        if teachers_with_theory:
            logger.info(f"Processing theory hours for {len(teachers_with_theory)} teachers")
            
            # OPTIMIZATION: Batch variable collection by structure
            for teacher in teachers_with_theory:
                # Use cached requirements
                total_theory_hours_required = self._teacher_requirements_cache[teacher]['total_theory_hours']
                
                # OPTIMIZATION: Collect variables more efficiently
                teacher_theory_vars = []
                
                # Loop optimization: Process by day and slot for cache locality
                for day_idx in range(self.num_days):
                    day_assignments = teacher_theory_assignments[teacher][day_idx]
                    for slot_idx in range(self.num_slots):
                        slot_assignments = day_assignments[slot_idx]
                        teacher_theory_vars.extend(slot_assignments.values())
                
                # Single efficient constraint
                self.model.Add(sum(teacher_theory_vars) == total_theory_hours_required)
                total_constraints_added += 1
                
                logger.info(f"Teacher {teacher}: EXACTLY {total_theory_hours_required} theory hours required")
        
        # Process lab assignments with optimized structure (if enabled)
        if lab_assignments_enabled and teachers_with_lab:
            logger.info(f"Processing lab hours for {len(teachers_with_lab)} teachers")
            
            for teacher in teachers_with_lab:
                # Use cached requirements
                total_lab_sessions_required = self._teacher_requirements_cache[teacher]['lab_sessions_required']
                
                # OPTIMIZATION: Collect lab variables more efficiently
                teacher_lab_vars = []
                
                # Loop optimization: Process by day for cache locality
                for day_idx in range(self.num_days):
                    day_assignments = teacher_lab_assignments[teacher][day_idx]
                    for session, session_assignments in day_assignments.items():
                        teacher_lab_vars.extend(session_assignments.values())
                
                # Single efficient constraint
                self.model.Add(sum(teacher_lab_vars) == total_lab_sessions_required)
                total_constraints_added += 1
                
                logger.info(f"Teacher {teacher}: EXACTLY {total_lab_sessions_required} lab sessions required")
        
        self.log_constraint_info("HIGHLY OPTIMIZED Course Hours Constraint", total_constraints_added)
        logger.info(f"Added {total_constraints_added} constraints with optimized variable structure")
        return True
    
    # OPTIMIZATION: Override get_instance_requirements to use cache
    def get_instance_requirements(self, instance_id):
        """Get cached instance requirements for better performance."""
        return self._instance_requirements_cache.get(instance_id, {
            'total_theory_hours': 0,
            'practical_hours': 0
        }) 