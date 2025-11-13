# Complete Implementation Integration Guide

## Overview

This guide shows how to integrate all modular components into your existing `src/` folder structure.

---

## File Organization

```
src/
├── config/
│   ├── __init__.py
│   ├── schemas.py                    # Pydantic config models (EXISTING)
│   ├── manager.py                    # ConfigManager class (EXISTING)
│   └── defaults.yaml                 # Default config (EXISTING)
│
├── data/
│   ├── __init__.py
│   ├── schemas.py                    # UPDATE: Add Pydantic models
│   ├── loader.py                     # UPDATE: Add DataLoader implementation
│   ├── preprocessor.py               # NEW: Add DataPreprocessor
│   └── data_loader.py                # KEEP: Existing (to be phased out)
│
├── grouping/
│   ├── __init__.py
│   ├── schemas.py                    # NEW: Add GroupModel, SessionModel
│   └── group_optimizer.py            # NEW: Add GroupOptimizer
│
├── pipeline/
│   ├── __init__.py
│   └── orchestrator.py               # NEW: Add PipelineOrchestrator
│
├── utils/
│   ├── __init__.py
│   ├── normalizers.py                # NEW: Add normalization utilities
│   └── validators.py                 # UPDATE: Add validation utilities
│
├── constraints/
│   ├── __init__.py
│   ├── builder.py                    # EXISTING: Constraint building
│   └── models.py                     # EXISTING: Constraint models
│
├── solver/
│   ├── __init__.py
│   └── solver.py                     # EXISTING: OR-Tools solver
│
├── models/
│   └── ...                           # EXISTING: Model builders
│
└── main.py                           # UPDATE: Use orchestrator
```

---

## Step 1: Create Data Schemas

**File: `src/data/schemas.py`**

```python
"""
Data Schema Models

Defines all typed models for data loading and processing.
"""

from pydantic import BaseModel, Field, validator
from typing import List, Dict, Optional, Set
from enum import Enum
from datetime import datetime

# ═════════════════════════════════════════════════════════════════════════════════
# ENUMS
# ═════════════════════════════════════════════════════════════════════════════════

class RoomType(str, Enum):
    """Room type classification."""
    THEORY = "theory"
    LAB = "lab"
    CORE_LAB = "core_lab"
    TUTORIAL = "tutorial"

# ═════════════════════════════════════════════════════════════════════════════════
# MODELS
# ═════════════════════════════════════════════════════════════════════════════════

class CourseModel(BaseModel):
    """
    Represents a course (subject).
    
    A course can have theory, lab, and tutorial components,
    potentially split into multiple batches for large classes.
    """
    code: str = Field(description="Unique course code")
    name: str = Field(description="Course name")
    department: str = Field(description="Department offering course")
    semester: int = Field(ge=1, le=8, description="Semester level")
    teacher_id: str = Field(description="Faculty ID")
    teacher_name: str = Field(description="Faculty name")
    hours_lab: int = Field(ge=0, description="Lab hours/week")
    hours_theory: int = Field(ge=0, description="Theory hours/week")
    hours_tutorial: int = Field(ge=0, description="Tutorial hours/week")
    student_count: int = Field(gt=0, description="Number of students")
    course_type: str = Field(default="core", description="Course category")
    teaching_dept: Optional[str] = Field(default=None, description="Teaching department")
    
    @property
    def total_hours(self) -> int:
        """Total hours per week."""
        return self.hours_theory + self.hours_lab + self.hours_tutorial
    
    @validator('total_hours')
    def validate_total_hours(cls, v):
        if v == 0:
            raise ValueError("Course must have at least 1 hour")
        return v
    
    class Config:
        frozen = True

class RoomModel(BaseModel):
    """Represents a room/classroom."""
    id: str = Field(description="Room ID")
    capacity: int = Field(gt=0, description="Room capacity")
    floor: int = Field(ge=0, description="Floor number")
    block: str = Field(description="Block/Building")
    type: RoomType = Field(description="Room type")
    equipment: Optional[str] = Field(default=None, description="Equipment available")
    building: Optional[str] = Field(default=None, description="Building name")
    is_lab: bool = Field(description="Whether room is a lab")
    
    class Config:
        frozen = True

class TimeSlotDict(BaseModel):
    """Represents a time slot."""
    index: int
    start_time: str
    end_time: str
    duration_minutes: int

class LoadedDataModel(BaseModel):
    """Complete output from data loading stage."""
    courses: List[CourseModel]
    rooms: List[RoomModel]
    teachers: Set[str]
    departments: Set[str]
    time_slots: Dict[str, List[TimeSlotDict]]
    days: List[str]
    load_timestamp: datetime
    
    class Config:
        arbitrary_types_allowed = True
```

---

## Step 2: Create Configuration Manager

**File: `src/config/manager.py`**

```python
"""
Configuration Manager

Loads and validates scheduler configuration from YAML files.
"""

import yaml
import logging
from pathlib import Path
from typing import Optional

from .schemas import SchedulerConfig

logger = logging.getLogger(__name__)

class ConfigManager:
    """Manages scheduler configuration."""
    
    @staticmethod
    def load(config_path: str) -> SchedulerConfig:
        """
        Load configuration from YAML file.
        
        Args:
            config_path: Path to YAML configuration file
        
        Returns:
            SchedulerConfig with validated settings
        
        Raises:
            FileNotFoundError: If config file not found
            ValueError: If configuration is invalid
        """
        config_file = Path(config_path)
        
        if not config_file.exists():
            raise FileNotFoundError(f"Configuration not found: {config_path}")
        
        logger.info(f"Loading configuration from {config_path}")
        
        with open(config_file, 'r') as f:
            config_dict = yaml.safe_load(f)
        
        # Convert to Pydantic model (this validates)
        config = SchedulerConfig(**config_dict)
        
        logger.info("Configuration loaded and validated")
        return config
```

---

## Step 3: Create Normalizers

**File: `src/utils/normalizers.py`**

See `MODULAR_DATA_LOADER.md` for complete normalizers implementation.

---

## Step 4: Create DataLoader

**File: `src/data/loader.py`**

See `MODULAR_DATA_LOADER.md` for complete DataLoader implementation.

---

## Step 5: Create Preprocessor

**File: `src/data/preprocessor.py`**

See `MODULAR_DATA_PREPROCESSOR.md` for complete Preprocessor implementation.

---

## Step 6: Create Group Schemas

**File: `src/grouping/schemas.py`**

See `MODULAR_GROUP_OPTIMIZER.md` for complete Group schemas.

---

## Step 7: Create GroupOptimizer

**File: `src/grouping/group_optimizer.py`**

See `MODULAR_GROUP_OPTIMIZER.md` for complete GroupOptimizer implementation.

---

## Step 8: Create Pipeline Orchestrator

**File: `src/pipeline/orchestrator.py`**

See `MODULAR_PIPELINE_ORCHESTRATOR.md` for complete Orchestrator implementation.

---

## Step 9: Update main.py

**File: `main.py`**

```python
"""
Main entry point for scheduler.

Usage:
    python main.py
"""

import logging
import sys
import json
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)

logger = logging.getLogger(__name__)

def main():
    """Main entry point."""
    try:
        # Import pipeline (this ensures all modules are available)
        from src.pipeline.orchestrator import PipelineOrchestrator, PipelineError
        
        # Run pipeline
        logger.info("Starting scheduler pipeline...")
        orchestrator = PipelineOrchestrator('config/scheduler.yaml')
        result = orchestrator.run()
        
        # Print summary
        print(f"\n{'='*80}")
        print(f"✓ PIPELINE SUCCESSFUL")
        print(f"{'='*80}")
        print(f"Loaded {result.total_groups} groups")
        print(f"Created {result.total_sessions} sessions")
        print(f"  - Theory: {result.total_theory_sessions}")
        print(f"  - Lab: {result.total_lab_sessions}")
        print(f"Ready for constraint building")
        print(f"{'='*80}\n")
        
        # Optional: Save to JSON
        output_dir = Path('output')
        output_dir.mkdir(exist_ok=True)
        
        with open(output_dir / 'groups.json', 'w') as f:
            json.dump(
                [g.dict() for g in result.groups],
                f,
                indent=2,
                default=str
            )
        
        print(f"Saved groups to output/groups.json")
        
        return result
    
    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        sys.exit(1)

if __name__ == '__main__':
    main()
```

---

## Step 10: Create Configuration YAML

**File: `config/scheduler.yaml`**

```yaml
# Scheduler Configuration

# Data file paths
data_paths:
  courses_csv: "data/courses.csv"
  techlongue_csv: "data/block_wise/techlongue.csv"
  rooms_csv: "data/room.csv"
  day_order_csv: "data/day_order.csv"

# Time slot configuration
time_config:
  days:
    - "Monday"
    - "Tuesday"
    - "Wednesday"
    - "Thursday"
    - "Friday"
  
  theory_system:
    slots:
      - { index: 0, start_time: "8:00", end_time: "8:50", duration_minutes: 50 }
      - { index: 1, start_time: "8:50", end_time: "9:40", duration_minutes: 50 }
      - { index: 2, start_time: "9:40", end_time: "10:30", duration_minutes: 50 }
      - { index: 3, start_time: "10:30", end_time: "11:20", duration_minutes: 50 }
      - { index: 4, start_time: "11:30", end_time: "12:20", duration_minutes: 50 }
      - { index: 5, start_time: "12:20", end_time: "1:10", duration_minutes: 50 }
      - { index: 6, start_time: "1:10", end_time: "2:00", duration_minutes: 50 }
      - { index: 7, start_time: "2:00", end_time: "2:50", duration_minutes: 50 }
      - { index: 8, start_time: "2:50", end_time: "3:40", duration_minutes: 50 }
  
  lab_system:
    slots:
      - { index: 0, start_time: "8:00", end_time: "9:40", duration_minutes: 100 }
      - { index: 1, start_time: "9:40", end_time: "11:20", duration_minutes: 100 }
      - { index: 2, start_time: "11:30", end_time: "1:10", duration_minutes: 100 }
      - { index: 3, start_time: "1:10", end_time: "2:50", duration_minutes: 100 }
      - { index: 4, start_time: "2:50", end_time: "4:30", duration_minutes: 100 }

# Group optimization
lab_batch_size: 60  # Students per lab batch

# Constraint parameters
constraints:
  min_gap_between_classes: 0  # No gap required
  max_consecutive_classes: 4
  prefer_consecutive_hours: true

# Solver parameters
solver:
  time_limit_seconds: 300
  log_search_progress: true
  num_workers: 4
```

---

## Step 11: Update Package Imports

**File: `src/__init__.py`**

```python
"""
Scheduler package
"""

from .pipeline.orchestrator import PipelineOrchestrator
from .data.loader import DataLoader
from .data.preprocessor import DataPreprocessor
from .grouping.group_optimizer import GroupOptimizer

__all__ = [
    'PipelineOrchestrator',
    'DataLoader',
    'DataPreprocessor',
    'GroupOptimizer',
]
```

**File: `src/data/__init__.py`**

```python
"""Data module"""

from .loader import DataLoader
from .preprocessor import DataPreprocessor
from .schemas import CourseModel, RoomModel, LoadedDataModel

__all__ = [
    'DataLoader',
    'DataPreprocessor',
    'CourseModel',
    'RoomModel',
    'LoadedDataModel',
]
```

**File: `src/grouping/__init__.py`**

```python
"""Grouping module"""

from .group_optimizer import GroupOptimizer
from .schemas import GroupModel, SessionModel, SessionType

__all__ = [
    'GroupOptimizer',
    'GroupModel',
    'SessionModel',
    'SessionType',
]
```

**File: `src/pipeline/__init__.py`**

```python
"""Pipeline module"""

from .orchestrator import PipelineOrchestrator, PipelineError

__all__ = [
    'PipelineOrchestrator',
    'PipelineError',
]
```

---

## Step 12: Testing the Integration

### Test 1: Configuration Loading

```python
# test_integration_config.py
from src.config.manager import ConfigManager

config = ConfigManager.load('config/scheduler.yaml')
print(f"Config loaded: {len(config.time_config.days)} days")
assert len(config.time_config.days) == 5
print("✓ Configuration test passed")
```

### Test 2: Data Loading

```python
# test_integration_loader.py
from src.config.manager import ConfigManager
from src.data.loader import DataLoader

config = ConfigManager.load('config/scheduler.yaml')
loader = DataLoader(config)
data = loader.load()

print(f"Loaded {len(data.courses)} courses, {len(data.rooms)} rooms")
assert len(data.courses) > 0
assert len(data.rooms) > 0
print("✓ Data loading test passed")
```

### Test 3: Full Pipeline

```python
# test_integration_pipeline.py
from src.pipeline.orchestrator import PipelineOrchestrator

orchestrator = PipelineOrchestrator('config/scheduler.yaml')
result = orchestrator.run()

print(f"Pipeline complete:")
print(f"  Groups: {result.total_groups}")
print(f"  Sessions: {result.total_sessions}")
assert result.total_groups > 0
assert result.total_sessions > 0
print("✓ Pipeline test passed")
```

---

## Step 13: Running the System

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run pipeline
python main.py

# 3. Check output
ls output/groups.json

# 4. Run tests
python -m pytest test_integration_*.py -v
```

---

## File Summary

| File | Purpose | Status |
|------|---------|--------|
| `src/data/schemas.py` | Pydantic models | CREATE |
| `src/data/loader.py` | Data loading | CREATE |
| `src/data/preprocessor.py` | Data cleaning | CREATE |
| `src/grouping/schemas.py` | Group models | CREATE |
| `src/grouping/group_optimizer.py` | Group creation | CREATE |
| `src/utils/normalizers.py` | Name normalization | CREATE |
| `src/pipeline/orchestrator.py` | Pipeline orchestration | CREATE |
| `config/scheduler.yaml` | Configuration | CREATE |
| `main.py` | Entry point | UPDATE |

---

## Integration Checklist

- [ ] Create `src/data/schemas.py` with Pydantic models
- [ ] Create `src/config/manager.py` with ConfigManager
- [ ] Create `src/utils/normalizers.py` with normalizers
- [ ] Create `src/data/loader.py` with DataLoader
- [ ] Create `src/data/preprocessor.py` with Preprocessor
- [ ] Create `src/grouping/schemas.py` with Group models
- [ ] Create `src/grouping/group_optimizer.py` with GroupOptimizer
- [ ] Create `src/pipeline/orchestrator.py` with Orchestrator
- [ ] Create `config/scheduler.yaml` configuration
- [ ] Update `main.py` to use orchestrator
- [ ] Update package `__init__.py` files
- [ ] Run integration tests
- [ ] Test full pipeline end-to-end

---

## Next Steps

Once integration is complete:

1. **Constraint Building**: Pass groups to ConstraintBuilder
2. **Solving**: Use OR-Tools with constraints
3. **Validation**: Verify solution meets all constraints
4. **Extraction**: Extract timetable from solution
5. **Output**: Generate UI/export timetable

See existing `src/constraints/` and `src/solver/` modules for next stages.

---

## Tips & Troubleshooting

### Issue: "ModuleNotFoundError"
**Solution**: Ensure all `__init__.py` files are in place and packages are imported correctly.

### Issue: "Configuration not found"
**Solution**: Check `config/scheduler.yaml` exists and paths are correct.

### Issue: "No courses loaded"
**Solution**: Verify `data/courses.csv` exists and has correct format.

### Issue: "Validation error in Pydantic models"
**Solution**: Check data types match model definitions (e.g., student_count should be int).

---

## Additional Resources

- `MODULAR_ARCHITECTURE_GUIDE.md` - Architecture patterns
- `MODULAR_DATA_SCHEMAS.md` - Complete schema definitions
- `MODULAR_DATA_LOADER.md` - Loader implementation details
- `MODULAR_DATA_PREPROCESSOR.md` - Preprocessor details
- `MODULAR_GROUP_OPTIMIZER.md` - Group optimizer details
- `MODULAR_PIPELINE_ORCHESTRATOR.md` - Orchestrator details
