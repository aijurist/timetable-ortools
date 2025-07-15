# CombinedScheduler - Unified Timetable Scheduling System

## Overview

The `CombinedScheduler` is a sophisticated, unified scheduling system that handles both laboratory and theory sessions using Google OR-Tools CP-SAT solver. It provides intelligent course grouping, constraint management, and optimization for educational institutions with complex scheduling requirements.

## Key Features

### 🎯 **Unified Scheduling Architecture**
- **Lab Sessions**: 12-slot time structure grouped into 6 sessions of 2 hours each (L1-L6)
- **Theory Sessions**: 11-slot time structure with 1-hour sessions
- **Cross-system conflict detection** and resolution
- **Unified group creation** and constraint management

### 📚 **Intelligent Course Grouping**
- **OR-Tools optimization** for optimal student choice using Hall's theorem
- **Department-semester based grouping** with constraints
- **Virtual instance handling** for large courses (140+ students)
- **Core lab mapping** support for specialized laboratory assignments

### ⏰ **Advanced Time Management**
- **Department-specific day patterns**: Monday-Friday, Tuesday-Saturday, Monday-Saturday
- **Semester-specific overrides** for flexible scheduling
- **Shift-based constraints** (Shift 1: 8AM-3:30PM, Shift 2: 10AM-5:30PM)
- **Lunch break management** with flexible and fixed configurations

### 🏫 **Smart Room Allocation**
- **Capacity-based room assignment** (35, 70, 140+ capacity labs)
- **Block-specific priorities** (A Block, B Block, C Block)
- **TIFAC room restrictions** and specialized lab mappings
- **Core lab department restrictions** for optimal resource utilization

### 🔧 **Constraint Management**
- **Teacher clash prevention** across both lab and theory
- **5PM scheduling constraints** (hard and soft)
- **Consecutive session limits** and teacher workload management
- **Cross-department teacher handling** with individual shift patterns

## Architecture

### Core Components

```python
class CombinedScheduler:
    """
    Unified scheduler handling both lab and theory sessions
    with separate time structures and cross-system validation.
    """
```

### Time Structures

#### Lab Time Slots (6 Sessions × 2 Hours)
```python
lab_sessions = {
    'L1': '8:00 - 9:40',    # Morning session
    'L2': '9:50 - 11:30',   # Late morning
    'L3': '11:40 - 1:20',   # Pre-lunch
    'L4': '1:50 - 3:20',    # Afternoon
    'L5': '3:30 - 5:10',    # Late afternoon
    'L6': '5:20 - 7:00'     # Evening session
}
```

#### Theory Time Slots (11 Slots × 1 Hour)
```python
theory_time_slots = [
    "8:00 - 8:50", "8:55 - 9:45", "9:50 - 10:40", 
    "10:45 - 11:35", "11:40 - 12:30", "12:35 - 1:20",
    "1:50 - 2:40", "3:20 - 4:10", "4:15 - 5:05", 
    "5:10 - 6:00", "6:10 - 7:00"
]
```

## Installation & Dependencies

### Required Dependencies
```python
# Core dependencies
import pandas as pd
import numpy as np
import logging
import json
from datetime import datetime
from collections import defaultdict, Counter
from itertools import combinations

# Optimization
from ortools.sat.python import cp_model

# Visualization
import matplotlib.pyplot as plt
import seaborn as sns

# Custom modules
from .course_group_optimizer import CourseGroupOptimizer
from .shift_report_generator import ShiftReportGenerator
```

### Installation
```bash
pip install ortools pandas numpy matplotlib seaborn
```

## Usage

### Basic Initialization

```python
from src.combined_scheduler import CombinedScheduler

# Initialize scheduler
scheduler = CombinedScheduler(
    course_file='data/courses.csv',
    room_file='data/rooms.csv'
)

# Generate schedule
success = scheduler.generate_combined_schedule()
```

### Advanced Configuration

#### Adding Semester-Specific Day Patterns
```python
# Add Monday-Saturday pattern for specific department-semester
scheduler.add_semester_day_override(
    dept_name='Biotechnology', 
    semester=5, 
    day_pattern='Monday-Saturday'
)
```

#### Custom Constraint Configuration
```python
# Check if department has 5PM constraints
has_constraint = scheduler._has_5pm_constraint(
    dept_name='Computer Science & Engineering',
    semester=3,
    constraint_type='hard'
)

# Get department working days
dept_days = scheduler._get_days_for_department(
    dept_name='Mechanical Engineering',
    semester=5
)
```

## Data Requirements

### Input Files

#### 1. Course Data (courses.csv)
```csv
id,teacher_id,course_code,course_name,course_type,lecture_hours,tutorial_hours,practical_hours,student_count,semester,course_dept,student_dept
1,101,CS101,Programming,Core,3,1,2,70,3,Computer Science & Engineering,Computer Science & Engineering
```

#### 2. Room Data (techlongue.csv/rooms.csv)
```csv
id,room_number,room_max_cap,is_lab,room_type,block,description
1,A301,70,0,Classroom,A Block,Theory Classroom
2,LAB1,35,1,Laboratory,K Block,Programming Lab
```

#### 3. Teacher Preferences (pop.csv) - Optional
```csv
id_faculty,name_faculty,subject_code,preffered_day_1,preffered_day_2
101,Dr. Smith,CS101,monday,wednesday
```

#### 4. Day Order Configuration (day_order.csv) - Optional
```csv
Department,ODD
Computer Science & Engineering,Monday - Friday
Biotechnology,Tuesday - Saturday
```

#### 5. Core Lab Mapping (og-final.csv) - Optional
```csv
course_code,course_name,department,total_labs,lab_1,lab_2,lab_3
CS201,Data Structures,Computer Science,2,LAB1,LAB2,
```

## Key Methods

### Core Scheduling Methods

#### `generate_combined_schedule()`
Main method that orchestrates the entire scheduling process:
1. Runs feasibility analysis
2. Creates CP-SAT variables for lab and theory
3. Applies unified constraints
4. Solves optimization model
5. Extracts and validates results

#### `process_courses()`
Processes course data and separates into lab and theory requirements:
- Creates teacher-course assignments
- Categorizes courses by practical/theory hours
- Builds requirement structures for optimization

#### `create_course_groups()`
Creates unified course groups using OR-Tools optimization:
- Loads from extracted JSON or runs live optimization
- Ensures Hall's theorem compliance for student choice
- Handles virtual instances for large courses

### Constraint Application Methods

#### `_apply_unified_constraints(model, lab_variables, theory_variables)`
Applies all scheduling constraints:
- Lab-specific constraints (capacity, room assignment, consecutive sessions)
- Theory-specific constraints (group allocation, time slots)
- Cross-system constraints (teacher conflicts, room conflicts)
- Department-specific constraints (5PM rules, lunch breaks)

#### `apply_course_lab_requirements_constraint(model, lab_variables)`
Sophisticated lab assignment with priority system:
- **Priority Departments**: Computer Science & Engineering, Information Technology
- **Capacity Intelligence**: 35-cap vs 70+ capacity lab allocation
- **Block Priorities**: AIML/AIDS/CSD get K & J block preference
- **Student-Based Batching**: Automatic batching for 35+ student courses

### Analysis and Validation Methods

#### `analyze_lab_capacity()`
Analyzes lab capacity distribution and requirements

#### `analyze_theory_feasibility()`
Performs feasibility analysis for theory scheduling

#### `_validate_combined_schedules(lab_schedule, theory_schedule)`
Comprehensive validation of generated schedules

## Configuration Systems

### 1. Lunch Break Management

#### Fixed Lunch Breaks
```python
department_semester_lunch_breaks = {
    ('Computer Science & Engineering', 3): 4,  # Slot 4: 11:40-12:30
    ('Biotechnology', 5): 3,                   # Slot 3: 10:45-11:35
}
```

#### Flexible Lunch Breaks
```python
flexible_lunch_department_semesters = [
    ('Biomedical Engineering', 3),  # Model decides optimal lunch slot
    ('Mechanical Engineering', 5),
]
```

### 2. Shift-Based Constraints

#### Department Shift Patterns
```python
shift_definitions = {
    'shift_1': {
        'name': 'Shift 1 (8AM-3:30PM)',
        'theory_slots': [0, 1, 2, 3, 4, 5, 6],
        'lab_sessions': ['L1', 'L2', 'L3', 'L4']
    },
    'shift_2': {
        'name': 'Shift 2 (10AM-5:30PM)', 
        'theory_slots': [2, 3, 4, 5, 6, 7, 8],
        'lab_sessions': ['L2', 'L3', 'L4', 'L5']
    }
}
```

### 3. 5PM Constraints

#### Hard Constraints (Cannot schedule after 5:30PM)
```python
hard_5pm_constraint_departments = [
    "Artificial Intelligence & Data Science",      # All semesters
    "Computer Science & Engineering_S5",           # Specific semester
    "Mechanical Engineering_S3",
]
```

#### Soft Constraints (Discouraged after 5:00PM)
```python
soft_5pm_constraint_departments = [
    "Electronics & Communication Engineering_S3",
    "Computer Science & Engineering_S3",
]
```

## Output Files

### Generated Schedules
- `combined_lab_schedule.csv/json` - Complete lab schedule
- `combined_theory_schedule.csv/json` - Complete theory schedule
- `combined_schedule_summary.txt` - Summary statistics

### Analysis Reports
- `shift_reports/` - Department shift pattern analysis
- `visualizations/` - Schedule visualization charts
- `grouping_visualizations/` - Course group analysis

### Validation Reports
- Room conflict analysis
- Teacher workload distribution
- Constraint violation reports

## Advanced Features

### 1. Department-Specific Day Patterns
Supports different working day patterns per department:
- **Monday-Friday**: Standard 5-day schedule
- **Tuesday-Saturday**: Alternative 5-day schedule  
- **Monday-Saturday**: Extended 6-day schedule for intensive programs

### 2. Cross-Department Teacher Management
Handles teachers who teach multiple departments:
- Individual shift patterns for cross-department teachers
- Coordinated scheduling across student departments
- Workload balancing and conflict prevention

### 3. Intelligent Room Allocation
Smart room assignment based on:
- **Course requirements** (practical hours, student count)
- **Department priorities** (CS/IT priority for 70-cap labs)
- **Block preferences** (AIML/AIDS/CSD prefer K & J blocks)
- **Capacity optimization** (prevent small courses in large labs)

### 4. Batch Scheduling for Large Courses
Automatic handling of courses with 35+ students:
- **Batching Logic**: Splits large courses into manageable batches
- **Consecutive Preference**: Encourages consecutive sessions for learning continuity
- **Capacity Intelligence**: Chooses optimal lab capacity based on student count

## Troubleshooting

### Common Issues

#### 1. No Solution Found
```python
# Check feasibility
if not scheduler.analyze_theory_feasibility():
    print("Theory scheduling not feasible with current constraints")
```

#### 2. Room Conflicts
- Ensure `techlongue.csv` has correct room capacity data
- Check for duplicate room assignments in input data
- Verify block assignments are consistent

#### 3. Teacher Conflicts
- Review teacher workload distribution
- Check cross-department teacher assignments
- Validate day pattern consistency

#### 4. Missing Core Labs
- Verify `og-final.csv` format and room mappings
- Check laboratory room type assignments
- Ensure core lab IDs match room data

### Performance Optimization

#### Solver Parameters
```python
solver.parameters.max_time_in_seconds = 4000
solver.parameters.num_search_workers = 16
solver.parameters.max_memory_in_mb = 30000
```

#### Memory Management
- Large datasets may require increased memory limits
- Consider reducing constraint complexity for initial testing
- Use progressive constraint application for debugging

## Best Practices

### 1. Data Preparation
- Ensure consistent department naming across all files
- Validate teacher IDs and course codes
- Check room capacity and type assignments

### 2. Constraint Configuration
- Start with basic constraints and add complexity gradually
- Use soft constraints for preferences, hard constraints for requirements
- Test department-specific patterns before full deployment

### 3. Validation and Testing
- Always run validation after schedule generation
- Review conflict reports and constraint violations
- Test with smaller datasets before full-scale deployment

### 4. Performance Monitoring
- Monitor solver time and memory usage
- Use logging to track constraint application
- Validate solution quality with generated reports

## Contributing

When modifying the CombinedScheduler:

1. **Maintain constraint hierarchy** - Core constraints should have priority
2. **Test cross-system interactions** - Changes to lab constraints may affect theory scheduling
3. **Validate department patterns** - Ensure new features respect day pattern configurations
4. **Update documentation** - Keep method documentation current with changes
5. **Add comprehensive logging** - Use structured logging for debugging complex constraints

## License

This project is part of the Timetable Scheduler system and follows the same licensing terms as the parent project. 