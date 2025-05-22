# Timetable Scheduler

A comprehensive timetable scheduling solution for academic institutions using Google OR-Tools constraint programming solver.

## Overview

This timetable scheduler is designed to automatically generate feasible timetables for academic departments, optimizing the allocation of teachers, courses, and rooms across time slots while respecting various constraints.

## Features

- **LTP Hours Support**: Handles Lecture, Tutorial, and Practical hours as specified in course requirements
- **Theory and Lab Scheduling**: Allocates appropriate slots for theory classes and lab sessions
- **Conflict Avoidance**: Ensures no teacher is scheduled for overlapping slots
- **Room Appropriateness**: Assigns labs to lab rooms and theory classes to classrooms
- **Visualization**: Generates visual timetables for easy review
- **Detailed Reports**: Produces CSV files and summaries for analysis

## Requirements

- Python 3.6+
- Google OR-Tools
- Pandas
- Matplotlib
- NumPy

## Installation

```bash
# Clone the repository
git clone https://github.com/your-username/timetable_scheduler.git
cd timetable_scheduler

# Install dependencies
pip install -r requirements.txt
```

## Data Format

The scheduler requires two main data files:

1. **Teacher-Course Assignments** (`data/mapped_data/cs_teacher_courses.csv`):
   - Contains all teacher-course assignments with lecture, tutorial, and practical hours

2. **Room Information** (`data/block_wise/techlongue.csv`):
   - Contains information about classrooms and labs, including capacity and facilities

## Constraints

The scheduler enforces several key constraints:

1. **Teacher Single Assignment**: A teacher cannot be assigned to multiple rooms in the same time slot
2. **No Overlapping Slots**: A teacher cannot be assigned to both lab and theory slots that overlap in time
3. **Course Hours**: Each course must be allocated the required lecture and practical hours
4. **Room Single Assignment**: A room cannot be assigned to multiple teachers in the same time slot
5. **Lab Batch Constraint**: Classes with more students than lab capacity (35) are split into multiple batches
   - Example: A course with 70 students and 2 practical hours requires 2 separate lab slots (4 total hours)

## Time Slots

- **Theory Slots**: 11 slots per day (50 min with 10 min break) from 8:00 to 18:50
- **Lab Slots**: 5 slots per day (1hr:50min with 10 min break) from 8:00 to 17:50

## Usage

```bash
# Run the scheduler
python main.py
```

## Output

The scheduler generates the following outputs in the `output/schedule_YYYYMMDD_HHMMSS` directory:

- `schedule.csv`: Master schedule with all assignments
- `teacher_*_schedule.csv`: Individual teacher schedules
- `room_*_schedule.csv`: Individual room schedules
- `constraint_summary.txt`: Detailed impact analysis of each constraint
- `constraint_summary.json`: Machine-readable constraint analysis
- `summary.txt`: Overview of the generated schedule
- `*.png`: Visualizations of the timetable

## Architecture

- `main.py`: Entry point for the scheduler
- `src/scheduler.py`: Core scheduling logic
- `src/constraints.py`: Constraint definitions and handling
- `src/utils/visualizer.py`: Visualization utilities for timetable rendering

## License

[MIT License](LICENSE) 