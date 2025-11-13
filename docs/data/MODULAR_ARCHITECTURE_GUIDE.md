# Modular Architecture Implementation Guide

## Overview

This guide provides a complete modular architecture for integrating:
1. **Configuration Management** (YAML-based, type-safe)
2. **Data Loading** (with validation and normalization)
3. **Data Preprocessing** (transforms and enrichment)
4. **Group Optimization** (intelligent grouping algorithm)

All components follow these principles:
- ✅ Strong typing (Pydantic, TypedDict)
- ✅ Configuration-driven (YAML files)
- ✅ Modular & composable
- ✅ Easy pipeline integration
- ✅ Comprehensive logging
- ✅ Graceful error handling

---

## Architecture Diagram

```
Pipeline Flow:
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│  1. CONFIGURATION MANAGER                                  │
│     ├─ Load YAML configs                                   │
│     ├─ Validate schema                                     │
│     └─ Return ConfigState                                  │
│                                                             │
│  2. DATA LOADER                                            │
│     ├─ Load CSV files (courses, rooms, time)               │
│     ├─ Normalize & validate                                │
│     └─ Return LoadedData                                   │
│                                                             │
│  3. DATA PREPROCESSOR                                      │
│     ├─ Transform data (parse dept, semester, etc.)         │
│     ├─ Enrich data (add virtual instances, mappings)       │
│     ├─ Validate integrity                                  │
│     └─ Return PreprocessedData                             │
│                                                             │
│  4. GROUP OPTIMIZER                                        │
│     ├─ Create groups by dept/semester                      │
│     ├─ Optimize group distribution                         │
│     ├─ Handle virtual instances                            │
│     └─ Return GroupedData                                  │
│                                                             │
│  5. SCHEDULER (MODEL + SOLVER)                             │
│     └─ Use GroupedData + Constraints + Solver              │
│                                                             │
└─────────────────────────────────────────────────────────────┘

Each component:
- Takes input from previous stage
- Validates & transforms data
- Returns typed output
- Logs detailed progress
- Handles errors gracefully
```

---

## File Structure

```
src/
├── config/
│   ├── __init__.py
│   ├── schemas.py              # Pydantic models for all data structures
│   ├── manager.py              # Configuration loading & validation
│   └── defaults.py             # Default configurations
│
├── data/
│   ├── __init__.py
│   ├── loader.py               # Step 1: Load raw data
│   ├── preprocessor.py         # Step 2: Transform & enrich
│   ├── optimizer.py            # Step 3: Group optimization
│   ├── schemas.py              # Data structure definitions (Pydantic)
│   └── types.py                # TypedDict definitions
│
├── utils/
│   ├── validators.py           # Validation functions
│   ├── normalizers.py          # Normalization functions
│   ├── transformers.py         # Data transformation utilities
│   └── logging_utils.py        # Logging setup
│
├── pipeline.py                 # Main orchestrator (ties everything together)
└── cli.py                      # CLI entry point
```

---

## Key Principles

### 1. **Type Safety**
```python
# Use Pydantic models for validation + IDE support
from pydantic import BaseModel, Field

class CourseModel(BaseModel):
    code: str
    teacher_id: str
    department: str
    semester: int
    hours_lab: int = 0
    hours_theory: int = 0
    student_count: int

# Or TypedDict for simpler cases
from typing import TypedDict

class RoomDict(TypedDict):
    id: str
    capacity: int
    block: str
    floor: int
```

### 2. **Configuration-Driven**
```yaml
# config/scheduler.yaml
data:
  courses_csv: "data/courses.csv"
  rooms_csv: "data/techlongue.csv"
  time_slots_csv: "data/time_slots.csv"
  
preprocessing:
  virtual_instance_threshold: 140
  max_group_size: 80
  
optimization:
  algorithm: "constraint_satisfaction"
  max_groups_per_semester: 4
  
solver:
  timeout_seconds: 60
  log_level: "INFO"
```

### 3. **Composable Pipeline**
```python
# Easy to integrate:
config = ConfigManager.load('config/scheduler.yaml')
loaded_data = DataLoader(config).load()
preprocessed_data = DataPreprocessor(config).preprocess(loaded_data)
grouped_data = GroupOptimizer(config).optimize(preprocessed_data)
```

### 4. **Comprehensive Logging**
```python
# Track progress at each stage
logger.info(f"Loaded {len(courses)} courses from {path}")
logger.debug(f"Course normalization: {course_code} -> {normalized_code}")
logger.warning(f"Course {code} missing teacher, skipping")
logger.error(f"Failed to parse room capacity for {room_id}")
```

---

## Implementation Steps

### Step 1: Create Schemas (src/config/schemas.py)
Define all data structures with Pydantic for validation and type hints.

### Step 2: Create Configuration Manager (src/config/manager.py)
Load YAML files, validate against schemas, provide easy access.

### Step 3: Create Data Loader (src/data/loader.py)
Read CSVs, normalize formats, return typed data structures.

### Step 4: Create Preprocessor (src/data/preprocessor.py)
Transform data (parse departments, extract semesters, create virtual instances).

### Step 5: Create Group Optimizer (src/data/optimizer.py)
Intelligent grouping algorithm with proper handling of edge cases.

### Step 6: Create Pipeline (src/pipeline.py)
Tie all components together for easy CLI usage.

---

## Each Component in Detail

See the separate documents for complete implementation:

1. **MODULAR_CONFIG_MANAGEMENT.md** - Configuration system with YAML
2. **MODULAR_DATA_SCHEMAS.md** - Pydantic models and type definitions
3. **MODULAR_DATA_LOADER.md** - Robust CSV loading and normalization
4. **MODULAR_DATA_PREPROCESSOR.md** - Data transformation and enrichment
5. **MODULAR_GROUP_OPTIMIZER.md** - Intelligent grouping algorithm
6. **MODULAR_PIPELINE_INTEGRATION.md** - Tying everything together

---

## Integration Checklist

- [ ] Create schema files with Pydantic models
- [ ] Create configuration manager for YAML loading
- [ ] Create type definitions (TypedDict) for all data structures
- [ ] Implement data loader with CSV handling
- [ ] Implement preprocessor with transformations
- [ ] Implement group optimizer with algorithm
- [ ] Create pipeline orchestrator
- [ ] Add comprehensive logging at each stage
- [ ] Add error handling and validation
- [ ] Write unit tests for each component
- [ ] Create CLI entry point
- [ ] Document all functions and classes
- [ ] Add example configuration YAML files
- [ ] Create integration tests for full pipeline

---

## Benefits of This Architecture

✅ **Testability**: Each component can be tested independently
✅ **Maintainability**: Clear separation of concerns
✅ **Extensibility**: Easy to add new transformations or validators
✅ **Reusability**: Components can be used in different pipelines
✅ **Type Safety**: IDE support, catch errors early
✅ **Configuration**: Easy to experiment with different settings
✅ **Logging**: Complete audit trail of data transformations
✅ **Error Handling**: Graceful degradation with clear error messages
✅ **Performance**: Lazy loading, caching where appropriate
✅ **Documentation**: Self-documenting code with type hints

---

## Quick Start Example

```python
# src/pipeline.py
from config.manager import ConfigManager
from data.loader import DataLoader
from data.preprocessor import DataPreprocessor
from data.optimizer import GroupOptimizer

class SchedulerPipeline:
    def __init__(self, config_path: str):
        self.config = ConfigManager.load(config_path)
        
    def run(self) -> dict:
        """Run the complete pipeline."""
        
        # Stage 1: Load
        logger.info("Stage 1: Loading data...")
        loader = DataLoader(self.config)
        loaded = loader.load()
        logger.info(f"  ✓ Loaded {len(loaded.courses)} courses, {len(loaded.rooms)} rooms")
        
        # Stage 2: Preprocess
        logger.info("Stage 2: Preprocessing...")
        preprocessor = DataPreprocessor(self.config)
        preprocessed = preprocessor.preprocess(loaded)
        logger.info(f"  ✓ Created {len(preprocessed.virtual_instances)} virtual instances")
        
        # Stage 3: Optimize Groups
        logger.info("Stage 3: Optimizing groups...")
        optimizer = GroupOptimizer(self.config)
        grouped = optimizer.optimize(preprocessed)
        logger.info(f"  ✓ Created {len(grouped.groups)} groups")
        
        # Return for scheduler
        return grouped.to_dict()

# Usage:
if __name__ == '__main__':
    pipeline = SchedulerPipeline('config/scheduler.yaml')
    result = pipeline.run()
    # Pass result to scheduler...
```

---

## Next Steps

1. **Review each implementation document** (see list above)
2. **Start with schemas** - define all data structures
3. **Implement configuration manager** - YAML loading
4. **Build data loader** - CSV to data structures
5. **Build preprocessor** - transformations
6. **Build optimizer** - grouping logic
7. **Create pipeline** - orchestration
8. **Add tests** - unit + integration
9. **Add CLI** - user-facing entry point

Each component is independent and can be developed/tested separately.
