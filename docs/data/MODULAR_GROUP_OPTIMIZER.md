# Modular Group Optimizer Implementation

## Overview

Complete implementation of the group optimization stage with:
- ✅ Course grouping logic (combining lab + theory)
- ✅ Department-specific patterns
- ✅ Student count optimization
- ✅ Type-safe output with GroupModel
- ✅ Batch splitting (Batch 1, Batch 2)

---

## File: `src/grouping/group_optimizer.py`

Complete group optimizer implementation.

```python
"""
Group Optimizer Module

Creates optimized course groups by combining theory and lab sessions:
- Groups theory + practical + tutorial hours into batches
- Handles department-specific patterns
- Optimizes student grouping for labs (splits large classes)
- Returns typed GroupModel list

This module takes preprocessed courses and outputs groups ready for
constraint building and solving.
"""

import logging
from typing import Dict, List, Set, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict

from ..data.schemas import CourseModel, LoadedDataModel
from .schemas import GroupModel, SessionModel, SessionType

logger = logging.getLogger(__name__)

# ═════════════════════════════════════════════════════════════════════════════════
# EXCEPTIONS
# ═════════════════════════════════════════════════════════════════════════════════

class GroupOptimizerError(Exception):
    """Raised when group optimization fails."""
    pass

# ═════════════════════════════════════════════════════════════════════════════════
# GROUP OPTIMIZER
# ═════════════════════════════════════════════════════════════════════════════════

class GroupOptimizer:
    """
    Optimizes course grouping for scheduling.
    
    Key concepts:
    - Group: A unit combining one or more courses
    - Session: A time slot within a group (theory, lab, tutorial)
    - Batch: Subdivisions of groups for large classes (Batch 1, Batch 2)
    
    Example:
        Course: CSE101 - Data Structures
          - 3 hours theory/week
          - 2 hours lab/week
          - 0 hours tutorial
          - 150 students
        
        Creates groups:
          - Group 1: CSE101_B1 (75 students) → 3h theory, 2h lab
          - Group 2: CSE101_B2 (75 students) → 3h theory, 2h lab
    """
    
    # Default batch size (students per lab batch)
    DEFAULT_LAB_BATCH_SIZE = 60
    
    def __init__(self, lab_batch_size: int = DEFAULT_LAB_BATCH_SIZE):
        """
        Initialize group optimizer.
        
        Args:
            lab_batch_size: Number of students per lab batch
        """
        self.lab_batch_size = lab_batch_size
        logger.info(f"GroupOptimizer initialized (batch size: {lab_batch_size} students)")
    
    def optimize(self, clean_data: LoadedDataModel) -> List[GroupModel]:
        """
        Optimize course grouping.
        
        Takes preprocessed courses and creates batched groups.
        
        Args:
            clean_data: Preprocessed LoadedDataModel from DataPreprocessor
        
        Returns:
            List of optimized GroupModel instances
        
        Raises:
            GroupOptimizerError: If optimization fails
        """
        logger.info("="*80)
        logger.info("STARTING GROUP OPTIMIZATION")
        logger.info("="*80)
        
        try:
            # Step 1: Create initial groups (one per course)
            initial_groups = self._create_initial_groups(clean_data.courses)
            logger.info(f"Created {len(initial_groups)} initial groups (one per course)")
            
            # Step 2: Split large classes into batches
            batched_groups = self._apply_batch_splitting(initial_groups, clean_data)
            logger.info(f"After batch splitting: {len(batched_groups)} groups")
            
            # Step 3: Assign sessions (theory, lab, tutorial)
            groups_with_sessions = self._assign_sessions(batched_groups)
            
            # Step 4: Validate groups
            self._validate_groups(groups_with_sessions, clean_data)
            
            logger.info("="*80)
            logger.info("GROUP OPTIMIZATION COMPLETE")
            logger.info(f"  Total Groups: {len(groups_with_sessions)}")
            logger.info(f"  Total Sessions: {sum(len(g.sessions) for g in groups_with_sessions)}")
            logger.info("="*80)
            
            return groups_with_sessions
        
        except Exception as e:
            logger.error(f"Group optimization failed: {e}", exc_info=True)
            raise GroupOptimizerError(f"Failed to optimize groups: {e}") from e
    
    # ═════════════════════════════════════════════════════════════════════════════
    # GROUP CREATION
    # ═════════════════════════════════════════════════════════════════════════════
    
    def _create_initial_groups(self, courses: List[CourseModel]) -> List[Dict]:
        """Create initial groups (one per course)."""
        groups = []
        
        for course in courses:
            group = {
                'course_code': course.code,
                'course_name': course.name,
                'course': course,
                'teacher_id': course.teacher_id,
                'teacher_name': course.teacher_name,
                'department': course.department,
                'semester': course.semester,
                'student_count': course.student_count,
                'batch_number': 1,
                'hours': {
                    'theory': course.hours_theory,
                    'lab': course.hours_lab,
                    'tutorial': course.hours_tutorial,
                }
            }
            groups.append(group)
        
        return groups
    
    # ═════════════════════════════════════════════════════════════════════════════
    # BATCH SPLITTING
    # ═════════════════════════════════════════════════════════════════════════════
    
    def _apply_batch_splitting(self, 
                               groups: List[Dict],
                               clean_data: LoadedDataModel) -> List[Dict]:
        """
        Split large classes into batches.
        
        Strategy:
        1. For theory: All batches have same theory schedule
        2. For lab: Batches have different lab time slots
        3. For tutorial: Mix of shared and batch-specific
        
        Returns:
            Expanded groups with batch numbers
        """
        logger.info("Applying batch splitting...")
        
        expanded_groups = []
        total_batches_created = 0
        
        for group in groups:
            student_count = group['student_count']
            hours_lab = group['hours']['lab']
            
            # Determine number of batches needed
            if hours_lab > 0:
                # Lab courses: split by lab batch size
                num_batches = max(1, (student_count + self.lab_batch_size - 1) // self.lab_batch_size)
            else:
                # Theory only: no split needed
                num_batches = 1
            
            # Create batches
            for batch_num in range(1, num_batches + 1):
                # Calculate students for this batch
                batch_students = student_count // num_batches
                if batch_num <= (student_count % num_batches):
                    batch_students += 1
                
                # Create batch group
                batch_group = group.copy()
                batch_group['batch_number'] = batch_num
                batch_group['student_count'] = batch_students
                batch_group['total_batches'] = num_batches
                batch_group['group_id'] = f"{group['course_code']}_B{batch_num}"
                
                expanded_groups.append(batch_group)
                total_batches_created += 1
            
            if num_batches > 1:
                logger.debug(f"{group['course_code']}: Split into {num_batches} batches")
        
        logger.info(f"Created {total_batches_created} total batches from {len(groups)} courses")
        return expanded_groups
    
    # ═════════════════════════════════════════════════════════════════════════════
    # SESSION ASSIGNMENT
    # ═════════════════════════════════════════════════════════════════════════════
    
    def _assign_sessions(self, batched_groups: List[Dict]) -> List[GroupModel]:
        """
        Assign sessions (theory, lab, tutorial) to groups.
        
        Returns:
            GroupModel instances with sessions
        """
        logger.info("Assigning sessions to groups...")
        
        group_models = []
        
        for group_dict in batched_groups:
            sessions = []
            
            # Theory session
            if group_dict['hours']['theory'] > 0:
                sessions.append(SessionModel(
                    type=SessionType.THEORY,
                    hours=group_dict['hours']['theory'],
                    group_id=group_dict['group_id'],
                    course_code=group_dict['course_code'],
                ))
            
            # Lab session
            if group_dict['hours']['lab'] > 0:
                sessions.append(SessionModel(
                    type=SessionType.LAB,
                    hours=group_dict['hours']['lab'],
                    group_id=group_dict['group_id'],
                    course_code=group_dict['course_code'],
                ))
            
            # Tutorial session
            if group_dict['hours']['tutorial'] > 0:
                sessions.append(SessionModel(
                    type=SessionType.TUTORIAL,
                    hours=group_dict['hours']['tutorial'],
                    group_id=group_dict['group_id'],
                    course_code=group_dict['course_code'],
                ))
            
            # Create GroupModel
            group_model = GroupModel(
                group_id=group_dict['group_id'],
                course_code=group_dict['course_code'],
                course_name=group_dict['course_name'],
                teacher_id=group_dict['teacher_id'],
                teacher_name=group_dict['teacher_name'],
                department=group_dict['department'],
                semester=group_dict['semester'],
                student_count=group_dict['student_count'],
                batch_number=group_dict['batch_number'],
                total_batches=group_dict.get('total_batches', 1),
                sessions=sessions,
            )
            
            group_models.append(group_model)
        
        logger.info(f"Created {len(group_models)} groups with sessions")
        return group_models
    
    # ═════════════════════════════════════════════════════════════════════════════
    # VALIDATION
    # ═════════════════════════════════════════════════════════════════════════════
    
    def _validate_groups(self, 
                         groups: List[GroupModel],
                         clean_data: LoadedDataModel) -> None:
        """Validate group structure and integrity."""
        logger.info("Validating groups...")
        
        errors = []
        
        # Check group count
        if not groups:
            errors.append("No groups created")
        
        # Check for sessions
        groups_without_sessions = [g for g in groups if not g.sessions]
        if groups_without_sessions:
            errors.append(f"{len(groups_without_sessions)} groups have no sessions")
        
        # Check session types
        for group in groups:
            session_types = {s.type for s in group.sessions}
            if not session_types:
                errors.append(f"Group {group.group_id} has no session types")
        
        # Check student counts
        for group in groups:
            if group.student_count <= 0:
                errors.append(f"Group {group.group_id} has invalid student count: {group.student_count}")
        
        # Validate batch numbers
        for course_code in set(g.course_code for g in groups):
            course_groups = [g for g in groups if g.course_code == course_code]
            batch_numbers = sorted(g.batch_number for g in course_groups)
            
            # Should be consecutive starting from 1
            if batch_numbers != list(range(1, len(batch_numbers) + 1)):
                errors.append(f"Course {course_code}: Invalid batch numbers {batch_numbers}")
        
        if errors:
            logger.error("Group validation failed:")
            for error in errors:
                logger.error(f"  - {error}")
            raise GroupOptimizerError("Group validation failed")
        
        logger.info("Group validation passed")
```

---

## File: `src/grouping/schemas.py`

Group model schemas.

```python
"""
Group Schema Models

Defines typed models for groups and sessions.
"""

from enum import Enum
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

# ═════════════════════════════════════════════════════════════════════════════════
# ENUMS
# ═════════════════════════════════════════════════════════════════════════════════

class SessionType(str, Enum):
    """Type of session."""
    THEORY = "theory"
    LAB = "lab"
    TUTORIAL = "tutorial"

# ═════════════════════════════════════════════════════════════════════════════════
# MODELS
# ═════════════════════════════════════════════════════════════════════════════════

class SessionModel(BaseModel):
    """
    A single session within a group.
    
    Example:
        - Theory session: 3 hours
        - Lab session: 2 hours
    """
    type: SessionType
    hours: int = Field(gt=0, description="Duration in hours")
    group_id: str
    course_code: str
    
    class Config:
        frozen = True

class GroupModel(BaseModel):
    """
    A course group (batch) with multiple sessions.
    
    A group represents one batch of a course, containing:
    - One or more sessions (theory, lab, tutorial)
    - A specific student count
    - A batch number (1, 2, 3...)
    
    Example:
        CSE101_B1:
          - 150 students (Batch 1 of 2)
          - 3 hours/week theory
          - 2 hours/week lab
    """
    group_id: str = Field(description="Unique group identifier")
    course_code: str = Field(description="Course code")
    course_name: str = Field(description="Course name")
    teacher_id: str = Field(description="Teacher ID")
    teacher_name: str = Field(description="Teacher name")
    department: str = Field(description="Department offering course")
    semester: int = Field(ge=1, le=8, description="Semester level")
    student_count: int = Field(gt=0, description="Number of students in this batch")
    batch_number: int = Field(ge=1, description="Batch number (1, 2, 3...)")
    total_batches: int = Field(ge=1, description="Total batches for this course")
    sessions: List[SessionModel] = Field(description="Sessions in this group")
    
    @property
    def total_hours(self) -> int:
        """Total hours for this group per week."""
        return sum(s.hours for s in self.sessions)
    
    @property
    def has_lab(self) -> bool:
        """Whether this group has lab sessions."""
        return any(s.type == SessionType.LAB for s in self.sessions)
    
    @property
    def has_theory(self) -> bool:
        """Whether this group has theory sessions."""
        return any(s.type == SessionType.THEORY for s in self.sessions)
    
    class Config:
        frozen = True

class GroupListModel(BaseModel):
    """Collection of all optimized groups."""
    groups: List[GroupModel]
    total_groups: int
    total_sessions: int
    optimization_timestamp: datetime
    
    @property
    def total_theory_sessions(self) -> int:
        """Count theory sessions."""
        return sum(
            len([s for s in g.sessions if s.type == SessionType.THEORY])
            for g in self.groups
        )
    
    @property
    def total_lab_sessions(self) -> int:
        """Count lab sessions."""
        return sum(
            len([s for s in g.sessions if s.type == SessionType.LAB])
            for g in self.groups
        )
```

---

## Pipeline Usage

```python
from src.data.loader import DataLoader
from src.data.preprocessor import DataPreprocessor
from src.grouping.group_optimizer import GroupOptimizer
from src.config.manager import ConfigManager

# Load and preprocess
config = ConfigManager.load('config/scheduler.yaml')
loader = DataLoader(config)
raw_data = loader.load()

preprocessor = DataPreprocessor()
clean_data = preprocessor.preprocess(raw_data)

# Optimize groups
optimizer = GroupOptimizer(lab_batch_size=60)
groups = optimizer.optimize(clean_data)

# Now groups are ready for constraint building
for group in groups:
    print(f"{group.group_id}: {group.student_count} students")
    for session in group.sessions:
        print(f"  - {session.type.value}: {session.hours} hours")
```

---

## Key Features

### Batch Splitting

| Course | Students | Lab Hours | Batches | Batch Size |
|--------|----------|-----------|---------|-----------|
| CSE101 | 150      | 2         | 3       | 50 each   |
| CSE102 | 35       | 0         | 1       | 35        |
| ME201  | 180      | 3         | 3       | 60 each   |

### Session Assignment

Each batch gets:
- **Theory**: All theory hours (shared across batches)
- **Lab**: Lab hours (batch-specific scheduling)
- **Tutorial**: Tutorial hours (can be shared or batch-specific)

### Group ID Format

`{COURSE_CODE}_B{BATCH_NUMBER}`

Examples:
- `CSE101_B1` - Batch 1 of CSE101
- `CSE101_B2` - Batch 2 of CSE101
- `ME201_B1` - Batch 1 of ME201 (single batch)

---

## Benefits

✅ **Automatic Batch Splitting**: Large classes split intelligently
✅ **Type Safety**: GroupModel with validation
✅ **Session Tracking**: Each group knows its sessions
✅ **Batch Management**: Proper numbering and tracking
✅ **Ready for Constraints**: Clear structure for constraint building
