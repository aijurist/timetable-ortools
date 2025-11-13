# Modular Pipeline Orchestrator

## Overview

Complete pipeline orchestrator that:
- ✅ Chains all modules together
- ✅ Enforces type contracts at each stage
- ✅ Provides clear data flow
- ✅ Includes comprehensive logging
- ✅ Handles errors gracefully

---

## File: `src/pipeline/orchestrator.py`

Complete pipeline orchestrator implementation.

```python
"""
Pipeline Orchestrator

Coordinates the complete data processing pipeline:
1. Configuration Loading
2. Data Loading (CSV files → typed CourseModel, RoomModel)
3. Data Preprocessing (cleaning, normalization, deduplication)
4. Group Optimization (batching, session assignment)
5. Ready for Constraint Building

This is the main entry point for the system, ensuring all modules
work together with proper type contracts and error handling.
"""

import logging
from typing import Optional, Dict, Any
from datetime import datetime
from pathlib import Path

from ..config.manager import ConfigManager
from ..config.schemas import SchedulerConfig
from ..data.loader import DataLoader, DataLoadError
from ..data.preprocessor import DataPreprocessor, PreprocessingError
from ..data.schemas import LoadedDataModel
from ..grouping.group_optimizer import GroupOptimizer, GroupOptimizerError
from ..grouping.schemas import GroupModel, GroupListModel

logger = logging.getLogger(__name__)

# ═════════════════════════════════════════════════════════════════════════════════
# EXCEPTIONS
# ═════════════════════════════════════════════════════════════════════════════════

class PipelineError(Exception):
    """Raised when pipeline execution fails."""
    pass

class PipelineConfigError(Exception):
    """Raised when configuration is invalid."""
    pass

# ═════════════════════════════════════════════════════════════════════════════════
# PIPELINE ORCHESTRATOR
# ═════════════════════════════════════════════════════════════════════════════════

class PipelineOrchestrator:
    """
    Main orchestrator for the data processing pipeline.
    
    Responsibilities:
    1. Load and validate configuration
    2. Execute data loading
    3. Execute preprocessing
    4. Execute group optimization
    5. Return ready-to-schedule groups
    
    Usage:
        orchestrator = PipelineOrchestrator('config/scheduler.yaml')
        groups = orchestrator.run()
    """
    
    def __init__(self, config_path: str):
        """
        Initialize orchestrator.
        
        Args:
            config_path: Path to scheduler YAML configuration
        
        Raises:
            PipelineConfigError: If configuration is invalid
        """
        self.config_path = Path(config_path)
        self.config: Optional[SchedulerConfig] = None
        self.pipeline_start_time: Optional[datetime] = None
        self.stage_timings: Dict[str, float] = {}
        
        logger.info("="*80)
        logger.info("INITIALIZING PIPELINE ORCHESTRATOR")
        logger.info(f"Config path: {self.config_path}")
        logger.info("="*80)
        
        # Validate config path
        if not self.config_path.exists():
            raise PipelineConfigError(f"Configuration file not found: {self.config_path}")
    
    def run(self) -> GroupListModel:
        """
        Execute complete pipeline.
        
        Returns:
            GroupListModel with all optimized groups ready for scheduling
        
        Raises:
            PipelineError: If any stage fails
        """
        self.pipeline_start_time = datetime.now()
        
        try:
            # Stage 1: Load configuration
            self.config = self._stage_load_config()
            
            # Stage 2: Load data
            loaded_data = self._stage_load_data()
            
            # Stage 3: Preprocess data
            clean_data = self._stage_preprocess_data(loaded_data)
            
            # Stage 4: Optimize groups
            groups = self._stage_optimize_groups(clean_data)
            
            # Stage 5: Finalize
            result = self._stage_finalize(groups)
            
            # Log final summary
            self._log_final_summary(result)
            
            return result
        
        except (DataLoadError, PreprocessingError, GroupOptimizerError) as e:
            logger.error(f"Pipeline failed at module level: {e}")
            raise PipelineError(f"Pipeline execution failed: {e}") from e
        except Exception as e:
            logger.error(f"Pipeline failed with unexpected error: {e}", exc_info=True)
            raise PipelineError(f"Pipeline execution failed: {e}") from e
    
    # ═════════════════════════════════════════════════════════════════════════════
    # PIPELINE STAGES
    # ═════════════════════════════════════════════════════════════════════════════
    
    def _stage_load_config(self) -> SchedulerConfig:
        """
        Stage 1: Load and validate configuration.
        
        Returns:
            SchedulerConfig from YAML file
        
        Raises:
            PipelineConfigError: If config loading fails
        """
        logger.info("\n" + "="*80)
        logger.info("STAGE 1: LOAD CONFIGURATION")
        logger.info("="*80)
        
        start_time = datetime.now()
        
        try:
            config = ConfigManager.load(str(self.config_path))
            logger.info(f"✓ Configuration loaded successfully")
            logger.info(f"  Data Dir: {Path(config.data_paths.courses_csv).parent}")
            logger.info(f"  Courses CSV: {config.data_paths.courses_csv}")
            logger.info(f"  Rooms CSV: {config.data_paths.techlongue_csv}")
            
            elapsed = (datetime.now() - start_time).total_seconds()
            self.stage_timings['config'] = elapsed
            logger.info(f"  Time: {elapsed:.2f}s")
            
            return config
        
        except Exception as e:
            logger.error(f"✗ Configuration load failed: {e}")
            raise PipelineConfigError(f"Failed to load configuration: {e}") from e
    
    def _stage_load_data(self) -> LoadedDataModel:
        """
        Stage 2: Load and parse input data.
        
        Loads from CSVs using DataLoader.
        
        Returns:
            Raw LoadedDataModel (not yet cleaned)
        
        Raises:
            DataLoadError: If loading fails
        """
        logger.info("\n" + "="*80)
        logger.info("STAGE 2: LOAD DATA")
        logger.info("="*80)
        
        start_time = datetime.now()
        
        try:
            loader = DataLoader(self.config)
            loaded_data = loader.load()
            
            elapsed = (datetime.now() - start_time).total_seconds()
            self.stage_timings['load'] = elapsed
            logger.info(f"  Time: {elapsed:.2f}s")
            
            return loaded_data
        
        except DataLoadError as e:
            logger.error(f"✗ Data load failed: {e}")
            raise
    
    def _stage_preprocess_data(self, loaded_data: LoadedDataModel) -> LoadedDataModel:
        """
        Stage 3: Preprocess and clean data.
        
        Cleans, validates, and normalizes raw data.
        
        Args:
            loaded_data: Raw data from DataLoader
        
        Returns:
            Clean, normalized LoadedDataModel ready for grouping
        
        Raises:
            PreprocessingError: If preprocessing fails
        """
        logger.info("\n" + "="*80)
        logger.info("STAGE 3: PREPROCESS DATA")
        logger.info("="*80)
        
        start_time = datetime.now()
        
        try:
            preprocessor = DataPreprocessor()
            clean_data = preprocessor.preprocess(loaded_data)
            
            elapsed = (datetime.now() - start_time).total_seconds()
            self.stage_timings['preprocess'] = elapsed
            logger.info(f"  Time: {elapsed:.2f}s")
            
            return clean_data
        
        except PreprocessingError as e:
            logger.error(f"✗ Preprocessing failed: {e}")
            raise
    
    def _stage_optimize_groups(self, clean_data: LoadedDataModel) -> list[GroupModel]:
        """
        Stage 4: Optimize course groups.
        
        Creates batches and assigns sessions to groups.
        
        Args:
            clean_data: Clean data from preprocessing
        
        Returns:
            List of optimized GroupModel instances
        
        Raises:
            GroupOptimizerError: If optimization fails
        """
        logger.info("\n" + "="*80)
        logger.info("STAGE 4: OPTIMIZE GROUPS")
        logger.info("="*80)
        
        start_time = datetime.now()
        
        try:
            # Use config's lab batch size if available
            lab_batch_size = getattr(
                self.config,
                'lab_batch_size',
                GroupOptimizer.DEFAULT_LAB_BATCH_SIZE
            )
            
            optimizer = GroupOptimizer(lab_batch_size=lab_batch_size)
            groups = optimizer.optimize(clean_data)
            
            elapsed = (datetime.now() - start_time).total_seconds()
            self.stage_timings['optimize'] = elapsed
            logger.info(f"  Time: {elapsed:.2f}s")
            
            return groups
        
        except GroupOptimizerError as e:
            logger.error(f"✗ Group optimization failed: {e}")
            raise
    
    def _stage_finalize(self, groups: list[GroupModel]) -> GroupListModel:
        """
        Stage 5: Finalize and package results.
        
        Creates final GroupListModel with metadata.
        
        Args:
            groups: Optimized groups from GroupOptimizer
        
        Returns:
            Final GroupListModel ready for scheduling
        """
        logger.info("\n" + "="*80)
        logger.info("STAGE 5: FINALIZE RESULTS")
        logger.info("="*80)
        
        total_sessions = sum(len(g.sessions) for g in groups)
        
        result = GroupListModel(
            groups=groups,
            total_groups=len(groups),
            total_sessions=total_sessions,
            optimization_timestamp=datetime.now(),
        )
        
        logger.info(f"✓ Pipeline finalized")
        logger.info(f"  Total Groups: {result.total_groups}")
        logger.info(f"  Total Sessions: {result.total_sessions}")
        logger.info(f"  Theory Sessions: {result.total_theory_sessions}")
        logger.info(f"  Lab Sessions: {result.total_lab_sessions}")
        
        return result
    
    # ═════════════════════════════════════════════════════════════════════════════
    # LOGGING AND REPORTING
    # ═════════════════════════════════════════════════════════════════════════════
    
    def _log_final_summary(self, result: GroupListModel) -> None:
        """Log final pipeline summary."""
        total_elapsed = (datetime.now() - self.pipeline_start_time).total_seconds()
        
        logger.info("\n" + "="*80)
        logger.info("PIPELINE COMPLETE")
        logger.info("="*80)
        logger.info("STAGE TIMINGS:")
        
        for stage, duration in self.stage_timings.items():
            pct = (duration / total_elapsed * 100) if total_elapsed > 0 else 0
            logger.info(f"  {stage:12s}: {duration:7.2f}s ({pct:5.1f}%)")
        
        logger.info(f"\nTOTAL TIME: {total_elapsed:.2f}s")
        logger.info(f"\nRESULTS:")
        logger.info(f"  Groups: {result.total_groups}")
        logger.info(f"  Sessions: {result.total_sessions}")
        logger.info(f"  Theory: {result.total_theory_sessions}")
        logger.info(f"  Lab: {result.total_lab_sessions}")
        logger.info("="*80 + "\n")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get pipeline execution statistics."""
        return {
            'stage_timings': self.stage_timings,
            'total_time': sum(self.stage_timings.values()),
            'total_stages': len(self.stage_timings),
        }
```

---

## File: `src/pipeline/__init__.py`

Pipeline package initialization.

```python
"""Pipeline module - orchestrates complete data processing."""

from .orchestrator import PipelineOrchestrator, PipelineError, PipelineConfigError

__all__ = [
    'PipelineOrchestrator',
    'PipelineError',
    'PipelineConfigError',
]
```

---

## File: `main.py`

Simple entry point using the orchestrator.

```python
"""
Main entry point for the scheduler.

Usage:
    python main.py
"""

import logging
import sys
from pathlib import Path

from src.pipeline.orchestrator import PipelineOrchestrator, PipelineError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('scheduler.log'),
    ]
)

logger = logging.getLogger(__name__)

def main():
    """Main entry point."""
    try:
        # Run pipeline
        orchestrator = PipelineOrchestrator('config/scheduler.yaml')
        result = orchestrator.run()
        
        # Print summary
        print(f"\n{'='*80}")
        print(f"SUCCESS!")
        print(f"{'='*80}")
        print(f"Loaded {result.total_groups} groups with {result.total_sessions} sessions")
        print(f"Ready for constraint building and solving")
        print(f"{'='*80}\n")
        
        # Optional: Save groups to file
        # with open('output/groups.json', 'w') as f:
        #     json.dump(result.dict(), f, indent=2, default=str)
        
        return result
    
    except PipelineError as e:
        logger.error(f"Pipeline failed: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        sys.exit(1)

if __name__ == '__main__':
    main()
```

---

## Complete Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ PipelineOrchestrator.run()                                                  │
└─────────────────────────────────────────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│ STAGE 1: Load Configuration                                                  │
│ ┌──────────────────────────────────────────────────────────────────────────┐ │
│ │ ConfigManager.load('config/scheduler.yaml')                             │ │
│ │ ↓                                                                        │ │
│ │ SchedulerConfig (time slots, paths, constraints)                        │ │
│ └──────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│ STAGE 2: Load Data (CSV Files)                                              │
│ ┌──────────────────────────────────────────────────────────────────────────┐ │
│ │ DataLoader.load()                                                        │ │
│ │ ┌─ courses.csv  → CourseModel[]                                          │ │
│ │ ├─ techlongue.csv → RoomModel[]                                          │ │
│ │ ├─ day_order.csv → Days[]                                               │ │
│ │ └─ Extract Teachers, Departments                                         │ │
│ │ ↓                                                                        │ │
│ │ LoadedDataModel (raw, unclean)                                           │ │
│ └──────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│ STAGE 3: Preprocess Data                                                    │
│ ┌──────────────────────────────────────────────────────────────────────────┐ │
│ │ DataPreprocessor.preprocess()                                            │ │
│ │ ┌─ Merge duplicates (Batch 1/2)                                          │ │
│ │ ├─ Clean student counts (fill zeros, cap outliers)                       │ │
│ │ ├─ Normalize teacher names                                               │ │
│ │ ├─ Normalize department names                                            │ │
│ │ └─ Remove invalid rooms                                                  │ │
│ │ ↓                                                                        │ │
│ │ LoadedDataModel (clean, validated)                                       │ │
│ └──────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│ STAGE 4: Optimize Groups                                                    │
│ ┌──────────────────────────────────────────────────────────────────────────┐ │
│ │ GroupOptimizer.optimize()                                                │ │
│ │ ┌─ Create initial groups (one per course)                                │ │
│ │ ├─ Apply batch splitting (large classes → Batch 1, 2, 3...)             │ │
│ │ ├─ Assign sessions (theory, lab, tutorial)                               │ │
│ │ └─ Validate group structure                                              │ │
│ │ ↓                                                                        │ │
│ │ GroupModel[] (optimized, with sessions)                                  │ │
│ └──────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│ STAGE 5: Finalize Results                                                   │
│ ┌──────────────────────────────────────────────────────────────────────────┐ │
│ │ Create GroupListModel with metadata                                      │ │
│ │ ↓                                                                        │ │
│ │ GroupListModel (ready for scheduling)                                    │ │
│ └──────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
              ↓
       Final Output
       (Ready for Constraint Building & OR-Tools Solving)
```

---

## Usage Examples

### Basic Usage

```python
from src.pipeline.orchestrator import PipelineOrchestrator

# Create orchestrator
orchestrator = PipelineOrchestrator('config/scheduler.yaml')

# Run pipeline
result = orchestrator.run()

# Access results
print(f"Groups: {result.total_groups}")
print(f"Sessions: {result.total_sessions}")

# Iterate groups
for group in result.groups:
    print(f"{group.group_id}: {group.student_count} students")
```

### With Error Handling

```python
from src.pipeline.orchestrator import PipelineOrchestrator, PipelineError
import logging

logging.basicConfig(level=logging.INFO)

try:
    orchestrator = PipelineOrchestrator('config/scheduler.yaml')
    result = orchestrator.run()
except PipelineError as e:
    print(f"Pipeline failed: {e}")
    # Handle error (retry, use fallback, etc.)
```

### Get Performance Metrics

```python
orchestrator = PipelineOrchestrator('config/scheduler.yaml')
result = orchestrator.run()

stats = orchestrator.get_stats()
print(f"Total time: {stats['total_time']:.2f}s")
for stage, duration in stats['stage_timings'].items():
    print(f"  {stage}: {duration:.2f}s")
```

---

## Integration with Constraint Building

Once pipeline completes, groups are ready for constraints:

```python
from src.pipeline.orchestrator import PipelineOrchestrator
from src.constraints.builder import ConstraintBuilder

# Run pipeline
orchestrator = PipelineOrchestrator('config/scheduler.yaml')
groups = orchestrator.run()

# Now build constraints
constraint_builder = ConstraintBuilder(groups)
constraints = constraint_builder.build_all_constraints()

# Ready for solver
solver = Solver(constraints, groups, rooms, time_slots)
solution = solver.solve()
```

---

## Benefits

✅ **Clear Data Flow**: Each stage has clear input/output contracts
✅ **Type Safety**: Pydantic models validate data at each stage
✅ **Error Handling**: Comprehensive error handling with context
✅ **Logging**: Full visibility into pipeline execution
✅ **Performance**: Stage timing information for optimization
✅ **Modularity**: Each stage can be tested/modified independently
✅ **Extensibility**: Easy to add new stages or modify existing ones
