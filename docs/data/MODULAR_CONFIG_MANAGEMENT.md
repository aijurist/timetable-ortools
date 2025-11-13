# Modular Configuration Management System

## Overview

A complete configuration system that:
- ✅ Loads YAML configuration files
- ✅ Validates using Pydantic schemas
- ✅ Provides type-safe access
- ✅ Supports environment variable overrides
- ✅ Has sensible defaults
- ✅ Generates sample configs

---

## File: `src/config/defaults.py`

Default configurations for all systems.

```python
"""
Default Configuration Values

Provides sensible defaults for all scheduler components.
"""

from enum import Enum
from typing import Dict, Any, List

# ═════════════════════════════════════════════════════════════════════════════════
# DEFAULT PATHS
# ═════════════════════════════════════════════════════════════════════════════════

DEFAULT_DATA_PATHS = {
    'courses_csv': 'data/courses.csv',
    'techlongue_csv': 'data/block_wise/techlongue.csv',
    'day_order_csv': 'data/day_order.csv',
    'time_slots_csv': 'data/time_slots.csv',
    'core_lab_mapping_csv': 'data/og-final.csv',
    'teacher_preferences_csv': 'data/pop.csv',
}

DEFAULT_OUTPUT_PATHS = {
    'output_dir': 'output',
    'schedule_file': 'schedule.csv',
    'validation_report': 'validation_report.json',
    'logs_dir': 'logs',
}

# ═════════════════════════════════════════════════════════════════════════════════
# DEFAULT TIME CONFIGURATION
# ═════════════════════════════════════════════════════════════════════════════════

DEFAULT_THEORY_TIME_SLOTS = [
    {'index': 0, 'start_time': '8:00', 'end_time': '8:50'},
    {'index': 1, 'start_time': '8:55', 'end_time': '9:45'},
    {'index': 2, 'start_time': '9:50', 'end_time': '10:40'},
    {'index': 3, 'start_time': '10:45', 'end_time': '11:35'},
    {'index': 4, 'start_time': '11:40', 'end_time': '12:30'},
    {'index': 5, 'start_time': '12:35', 'end_time': '1:20'},
    {'index': 6, 'start_time': '1:50', 'end_time': '2:40'},
    {'index': 7, 'start_time': '3:20', 'end_time': '4:10'},
    {'index': 8, 'start_time': '4:15', 'end_time': '5:05'},
    {'index': 9, 'start_time': '5:10', 'end_time': '6:00'},
    {'index': 10, 'start_time': '6:10', 'end_time': '7:00'},
]

DEFAULT_LAB_TIME_SLOTS = [
    {'index': 0, 'start_time': '8:00', 'end_time': '8:50'},
    {'index': 1, 'start_time': '8:50', 'end_time': '9:40'},
    {'index': 2, 'start_time': '9:50', 'end_time': '10:40'},
    {'index': 3, 'start_time': '10:40', 'end_time': '11:30'},
    {'index': 4, 'start_time': '11:40', 'end_time': '12:30'},
    {'index': 5, 'start_time': '12:30', 'end_time': '1:20'},
    {'index': 6, 'start_time': '1:50', 'end_time': '2:40'},
    {'index': 7, 'start_time': '2:40', 'end_time': '3:20'},
    {'index': 8, 'start_time': '3:30', 'end_time': '4:20'},
    {'index': 9, 'start_time': '4:20', 'end_time': '5:10'},
    {'index': 10, 'start_time': '5:20', 'end_time': '6:10'},
    {'index': 11, 'start_time': '5:10', 'end_time': '7:00'},
]

DEFAULT_LAB_SESSIONS = {
    'L1': {'slots': [0, 1], 'time_range': '8:00 - 9:40'},
    'L2': {'slots': [2, 3], 'time_range': '9:50 - 11:30'},
    'L3': {'slots': [4, 5], 'time_range': '11:40 - 1:20'},
    'L4': {'slots': [6, 7], 'time_range': '1:50 - 3:20'},
    'L5': {'slots': [8, 9], 'time_range': '3:30 - 5:10'},
    'L6': {'slots': [10, 11], 'time_range': '5:20 - 7:00'},
}

DEFAULT_DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']

# ═════════════════════════════════════════════════════════════════════════════════
# DEFAULT PREPROCESSING CONFIG
# ═════════════════════════════════════════════════════════════════════════════════

DEFAULT_PREPROCESSING = {
    'virtual_instance_threshold': 140,
    'virtual_instance_capacity': 70,
    'max_group_size': 80,
    'min_group_size': 30,
    'normalize_dept_names': True,
    'extract_semesters': True,
    'create_core_lab_groups': True,
}

# ═════════════════════════════════════════════════════════════════════════════════
# DEFAULT OPTIMIZATION CONFIG
# ═════════════════════════════════════════════════════════════════════════════════

DEFAULT_OPTIMIZATION = {
    'algorithm': 'constraint_satisfaction',
    'max_groups_per_semester': 4,
    'balance_group_sizes': True,
    'allow_virtual_instances': True,
    'co_schedule_enabled': True,
    'respect_course_types': True,
}

# ═════════════════════════════════════════════════════════════════════════════════
# DEFAULT SOLVER CONFIG
# ═════════════════════════════════════════════════════════════════════════════════

DEFAULT_SOLVER = {
    'timeout_seconds': 60,
    'max_threads': 4,
    'log_search_progress': False,
    'log_level': 'INFO',
    'presolve': True,
}

# ═════════════════════════════════════════════════════════════════════════════════
# COMPLETE DEFAULT CONFIG
# ═════════════════════════════════════════════════════════════════════════════════

DEFAULT_CONFIG = {
    'version': '1.0',
    'data_paths': DEFAULT_DATA_PATHS,
    'output_paths': DEFAULT_OUTPUT_PATHS,
    'time_config': {
        'theory_system': {
            'type': 'theory',
            'slots': DEFAULT_THEORY_TIME_SLOTS,
            'num_slots': len(DEFAULT_THEORY_TIME_SLOTS),
            'break_times': ['5', '6'],  # Lunch time slots
        },
        'lab_system': {
            'type': 'lab',
            'slots': DEFAULT_LAB_TIME_SLOTS,
            'num_slots': len(DEFAULT_LAB_TIME_SLOTS),
        },
        'lab_sessions': DEFAULT_LAB_SESSIONS,
        'days': DEFAULT_DAYS,
    },
    'preprocessing': DEFAULT_PREPROCESSING,
    'optimization': DEFAULT_OPTIMIZATION,
    'solver': DEFAULT_SOLVER,
}
```

---

## File: `src/config/manager.py`

Configuration manager for loading and accessing configs.

```python
"""
Configuration Manager

Handles loading configurations from YAML files, validating them,
and providing easy access throughout the application.
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, Optional, Any
import yaml
from copy import deepcopy

from .schemas import SchedulerConfig
from .defaults import DEFAULT_CONFIG

logger = logging.getLogger(__name__)

# ═════════════════════════════════════════════════════════════════════════════════
# CONFIGURATION MANAGER
# ═════════════════════════════════════════════════════════════════════════════════

class ConfigManager:
    """
    Manages configuration loading, validation, and access.
    
    Features:
    - Load from YAML files
    - Validate against Pydantic schemas
    - Merge with defaults
    - Support environment variable overrides
    - Generate sample configs
    """
    
    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize configuration manager.
        
        Args:
            config_path: Path to YAML configuration file
        """
        self.config_path = config_path
        self.config = None
        self.raw_config = None
        
    @classmethod
    def load(cls, config_path: str, strict: bool = False) -> SchedulerConfig:
        """
        Load and validate configuration from YAML file.
        
        Args:
            config_path: Path to config YAML file
            strict: If True, fail on any config issue. If False, use defaults.
        
        Returns:
            Validated SchedulerConfig
        
        Raises:
            FileNotFoundError: If config file doesn't exist (in strict mode)
            ValueError: If config validation fails (in strict mode)
        """
        logger.info(f"Loading configuration from {config_path}")
        
        if not os.path.exists(config_path):
            if strict:
                raise FileNotFoundError(f"Configuration file not found: {config_path}")
            else:
                logger.warning(f"Config file not found: {config_path}, using defaults")
                config_dict = deepcopy(DEFAULT_CONFIG)
        else:
            try:
                with open(config_path, 'r') as f:
                    config_dict = yaml.safe_load(f) or {}
                logger.info(f"Loaded YAML from {config_path}")
            except yaml.YAMLError as e:
                logger.error(f"YAML parsing error: {e}")
                if strict:
                    raise ValueError(f"Failed to parse YAML: {e}")
                config_dict = deepcopy(DEFAULT_CONFIG)
        
        # Merge with defaults (user config takes precedence)
        merged_config = cls._merge_configs(DEFAULT_CONFIG, config_dict)
        
        # Override with environment variables if present
        merged_config = cls._apply_env_overrides(merged_config)
        
        # Validate against schema
        try:
            config = SchedulerConfig(**merged_config)
            logger.info("Configuration validated successfully")
            return config
        except Exception as e:
            logger.error(f"Configuration validation error: {e}")
            if strict:
                raise ValueError(f"Invalid configuration: {e}")
            # Return default config
            logger.warning("Using default configuration")
            return SchedulerConfig(**DEFAULT_CONFIG)
    
    @staticmethod
    def _merge_configs(defaults: Dict, user_config: Dict) -> Dict:
        """
        Recursively merge user config with defaults.
        
        User config takes precedence.
        """
        merged = deepcopy(defaults)
        
        for key, value in user_config.items():
            if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
                merged[key] = ConfigManager._merge_configs(merged[key], value)
            else:
                merged[key] = value
        
        return merged
    
    @staticmethod
    def _apply_env_overrides(config: Dict) -> Dict:
        """
        Apply environment variable overrides.
        
        Supports:
        - SCHEDULER_TIMEOUT_SECONDS
        - SCHEDULER_LOG_LEVEL
        - SCHEDULER_OUTPUT_DIR
        - SCHEDULER_COURSES_CSV
        """
        config = deepcopy(config)
        
        # Solver timeouts
        if 'SCHEDULER_TIMEOUT_SECONDS' in os.environ:
            config['solver']['timeout_seconds'] = int(
                os.environ['SCHEDULER_TIMEOUT_SECONDS']
            )
        
        # Logging level
        if 'SCHEDULER_LOG_LEVEL' in os.environ:
            config['solver']['log_level'] = os.environ['SCHEDULER_LOG_LEVEL']
        
        # Output directory
        if 'SCHEDULER_OUTPUT_DIR' in os.environ:
            config['output_paths']['output_dir'] = os.environ['SCHEDULER_OUTPUT_DIR']
        
        # Courses CSV
        if 'SCHEDULER_COURSES_CSV' in os.environ:
            config['data_paths']['courses_csv'] = os.environ['SCHEDULER_COURSES_CSV']
        
        logger.debug("Applied environment variable overrides to configuration")
        return config
    
    @staticmethod
    def generate_sample_config(output_path: str = 'config/scheduler.yaml.sample'):
        """
        Generate a sample configuration file.
        
        Args:
            output_path: Where to save the sample config
        """
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        with open(output_path, 'w') as f:
            yaml.dump(DEFAULT_CONFIG, f, default_flow_style=False, sort_keys=False)
        
        logger.info(f"Generated sample configuration at {output_path}")
    
    @staticmethod
    def validate_config_file(config_path: str) -> bool:
        """
        Validate a configuration file without loading it.
        
        Args:
            config_path: Path to config file to validate
        
        Returns:
            True if valid, False otherwise
        """
        try:
            config = ConfigManager.load(config_path, strict=True)
            logger.info(f"Configuration {config_path} is valid")
            return True
        except Exception as e:
            logger.error(f"Configuration validation failed: {e}")
            return False
    
    @staticmethod
    def print_config(config: SchedulerConfig, verbose: bool = False):
        """
        Pretty print configuration.
        
        Args:
            config: Configuration to print
            verbose: If True, print full details
        """
        print("\n" + "="*80)
        print("SCHEDULER CONFIGURATION")
        print("="*80)
        
        print(f"\nVersion: {config.version}")
        print(f"\nData Paths:")
        for key, value in config.data_paths.dict().items():
            if value:
                print(f"  {key}: {value}")
        
        print(f"\nOutput Paths:")
        for key, value in config.output_paths.dict().items():
            print(f"  {key}: {value}")
        
        print(f"\nTime Configuration:")
        print(f"  Theory Slots: {config.time_config.theory_system.num_slots}")
        print(f"  Lab Sessions: {len(config.time_config.lab_sessions)}")
        print(f"  Days: {', '.join(config.time_config.days)}")
        
        print(f"\nPreprocessing:")
        print(f"  Virtual Instance Threshold: {config.preprocessing.virtual_instance_threshold}")
        print(f"  Max Group Size: {config.preprocessing.max_group_size}")
        
        print(f"\nOptimization:")
        print(f"  Algorithm: {config.optimization.algorithm}")
        print(f"  Max Groups/Semester: {config.optimization.max_groups_per_semester}")
        
        print(f"\nSolver:")
        print(f"  Timeout: {config.solver.timeout_seconds}s")
        print(f"  Log Level: {config.solver.log_level}")
        
        if verbose:
            print("\nFull Configuration:")
            print(json.dumps(config.dict(), indent=2, default=str))
        
        print("\n" + "="*80 + "\n")

# ═════════════════════════════════════════════════════════════════════════════════
# CONFIGURATION STATE (for passing through pipeline)
# ═════════════════════════════════════════════════════════════════════════════════

class ConfigState:
    """
    Immutable configuration state that can be passed through the pipeline.
    """
    
    def __init__(self, config: SchedulerConfig):
        self._config = config
    
    @property
    def config(self) -> SchedulerConfig:
        return self._config
    
    # Easy access to commonly used settings
    
    @property
    def courses_csv(self) -> str:
        return self._config.data_paths.courses_csv
    
    @property
    def rooms_csv(self) -> str:
        return self._config.data_paths.techlongue_csv
    
    @property
    def output_dir(self) -> str:
        return self._config.output_paths.output_dir
    
    @property
    def solver_timeout(self) -> int:
        return self._config.solver.timeout_seconds
    
    @property
    def log_level(self) -> str:
        return self._config.solver.log_level
    
    def dict(self) -> dict:
        """Export as dictionary."""
        return self._config.dict()
```

---

## Example Configuration File: `config/scheduler.yaml`

```yaml
version: "1.0"
description: "Timetable Scheduler Configuration"

data_paths:
  courses_csv: "data/courses.csv"
  techlongue_csv: "data/block_wise/techlongue.csv"
  day_order_csv: "data/day_order.csv"
  time_slots_csv: "data/time_slots.csv"
  core_lab_mapping_csv: "data/og-final.csv"
  teacher_preferences_csv: "data/pop.csv"

output_paths:
  output_dir: "output"
  schedule_file: "schedule.csv"
  validation_report: "validation_report.json"
  logs_dir: "logs"

time_config:
  theory_system:
    type: "theory"
    num_slots: 11
    break_times: [5, 6]  # Lunch break slots
  
  lab_system:
    type: "lab"
    num_slots: 12
  
  lab_sessions:
    L1: {slots: [0, 1], time_range: "8:00 - 9:40"}
    L2: {slots: [2, 3], time_range: "9:50 - 11:30"}
    L3: {slots: [4, 5], time_range: "11:40 - 1:20"}
    L4: {slots: [6, 7], time_range: "1:50 - 3:20"}
    L5: {slots: [8, 9], time_range: "3:30 - 5:10"}
    L6: {slots: [10, 11], time_range: "5:20 - 7:00"}
  
  days: [Monday, Tuesday, Wednesday, Thursday, Friday]

preprocessing:
  virtual_instance_threshold: 140
  virtual_instance_capacity: 70
  max_group_size: 80
  min_group_size: 30
  normalize_dept_names: true
  extract_semesters: true
  create_core_lab_groups: true

optimization:
  algorithm: "constraint_satisfaction"
  max_groups_per_semester: 4
  balance_group_sizes: true
  allow_virtual_instances: true
  co_schedule_enabled: true
  respect_course_types: true

solver:
  timeout_seconds: 60
  max_threads: 4
  log_search_progress: false
  log_level: "INFO"
  presolve: true
```

---

## Usage Examples

### Loading Configuration

```python
from src.config.manager import ConfigManager, ConfigState

# Load from file
config = ConfigManager.load('config/scheduler.yaml')

# Print configuration
ConfigManager.print_config(config, verbose=False)

# Validate configuration
is_valid = ConfigManager.validate_config_file('config/scheduler.yaml')

# Generate sample config
ConfigManager.generate_sample_config('config/scheduler.yaml.sample')

# Create state for pipeline
state = ConfigState(config)
print(state.courses_csv)
print(state.solver_timeout)
```

### Environment Variable Overrides

```bash
# Override solver timeout
export SCHEDULER_TIMEOUT_SECONDS=120

# Override output directory
export SCHEDULER_OUTPUT_DIR=/tmp/schedule_output

# Override log level
export SCHEDULER_LOG_LEVEL=DEBUG

# Run with overrides applied
python -m src.pipeline
```

---

## Benefits

✅ **Centralized Configuration**: All settings in one place
✅ **Type Safety**: Pydantic validation catches errors early
✅ **Environment Support**: Override settings via environment variables
✅ **Defaults**: Sensible defaults for all configurations
✅ **Validation**: Configuration validation before running
✅ **Documentation**: All settings documented with descriptions
✅ **Flexibility**: Easy to add new configuration options
✅ **Testability**: Easy to create test configurations
