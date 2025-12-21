# 🎓 University Timetable Scheduler

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue)](https://www.python.org/)
[![OR-Tools](https://img.shields.io/badge/OR--Tools-9.4%2B-green)](https://developers.google.com/optimization)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Status](https://img.shields.io/badge/Status-Active-brightgreen)](https://github.com)

A sophisticated, constraint-based timetable scheduling system for educational institutions, powered by Google OR-Tools CP-SAT solver. The system intelligently schedules both laboratory and theory sessions while respecting complex academic constraints and optimizing resource utilization.

## 🌟 Key Features

### 🎯 **Unified Scheduling Architecture**
- **Dual-Mode Scheduling**: Handles both lab (2-hour sessions) and theory (1-hour sessions) with separate time structures
- **Integrated Optimization**: Unified constraint-based model prevents conflicts across lab and theory schedules
- **Cross-System Validation**: Real-time conflict detection between different scheduling components

### 🧠 **Intelligent Course Grouping**
- **OR-Tools Optimization**: Uses constraint programming for optimal student choice maximization
- **Hall's Theorem Compliance**: Ensures maximum flexibility for student course selection
- **Virtual Instance Handling**: Automatically manages large courses (140+ students) through intelligent batching
- **Department-Semester Grouping**: Sophisticated grouping based on academic requirements

### ⏰ **Advanced Time Management**
- **Flexible Day Patterns**: Monday-Friday, Tuesday-Saturday, Monday-Saturday scheduling
- **Shift-Based Constraints**: Configurable shift patterns (8AM-3:30PM, 10AM-5:30PM)
- **Lunch Break Management**: Fixed and flexible lunch break configurations per department
- **5PM Constraints**: Hard and soft constraints for departments requiring early completion

### 🏫 **Smart Resource Allocation**
- **Capacity-Aware Assignment**: Automatic room assignment based on course requirements and room capacity
- **Block-Priority System**: Intelligent room allocation across campus blocks (A, B, C blocks)
- **Department Preferences**: Priority-based lab allocation for Computer Science and IT departments
- **TIFAC Room Management**: Specialized handling of TIFAC and core engineering lab restrictions

### 🔧 **Advanced Constraint Management**
- **Teacher Conflict Prevention**: Comprehensive teacher clash detection across all scheduling modes
- **Room Double-Booking Prevention**: Real-time room availability tracking and conflict resolution
- **Workload Balancing**: Automatic teacher workload distribution and consecutive session limits
- **Cross-Department Teachers**: Individual shift patterns for teachers serving multiple departments

## 📊 System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    TIMETABLE SCHEDULER                      │
├─────────────────────────────────────────────────────────────┤
│  🎯 Combined Scheduler (Main Engine)                       │
│  ├── Lab Scheduler      (6 × 2-hour sessions)              │
│  ├── Theory Scheduler   (11 × 1-hour sessions)             │
│  └── Course Group Optimizer                                │
├─────────────────────────────────────────────────────────────┤
│  🔧 Constraint Management                                  │
│  ├── Teacher Clash Prevention                              │
│  ├── Room Conflict Resolution                              │
│  ├── Capacity Management                                   │
│  ├── Time Pattern Constraints                              │
│  └── Department-Specific Rules                             │
├─────────────────────────────────────────────────────────────┤
│  📊 Analytics & Validation                                 │
│  ├── Schedule Conflict Analysis                            │
│  ├── Constraint Verification                               │
│  ├── Teacher Workload Reports                              │
│  └── Room Utilization Analysis                             │
├─────────────────────────────────────────────────────────────┤
│  🎨 Visualization & Export                                 │
│  ├── Schedule Heatmaps                                     │
│  ├── Teacher Timetables                                    │
│  ├── Room Occupancy Charts                                 │
│  └── CSV/JSON Export                                       │
└─────────────────────────────────────────────────────────────┘
```

## 🚀 Quick Start

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/your-username/timetable_scheduler.git
   cd timetable_scheduler
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Prepare your data files** (see [Data Format](#-data-format) section)

4. **Run the scheduler**
   ```bash
   # Combined scheduling (recommended)
   python main.py --mode combined --course-file data/courses.csv --room-file data/techlongue.csv
   
   # Lab only
   python main.py --mode lab --course-file data/courses.csv --room-file data/techlongue.csv
   
   # Theory only  
   python main.py --mode theory --course-file data/courses.csv --room-file data/techlongue.csv
   
   # Sequential (lab then theory)
   python main.py --mode all --course-file data/courses.csv --room-file data/techlongue.csv
   ```

### Command Line Options

```bash
python main.py [OPTIONS]

Options:
  --mode {lab,theory,all,combined}  Scheduling mode (default: combined)
  --course-file PATH               Path to courses CSV file
  --room-file PATH                Path to rooms CSV file  
  --output-dir PATH               Output directory (default: output)
  --visualize                     Generate visualizations (default: True)
  -h, --help                      Show help message
```

## �️ Interactive Dashboard & API Server

A lightweight FastAPI server lives in `src/app` so you can explore the latest generated schedule with a modern dashboard UI.

### Launch the dashboard

```powershell
python -m src.app.server --host 0.0.0.0 --port 8000
```

Then open [http://localhost:8000](http://localhost:8000). The app automatically finds the most recent folder inside `output/` (supports both `schedule.json` and `combined_*` exports) and serves:

- **Snapshot-aware metrics** – key totals, busiest day/time-slot, top rooms, and department loads.
- **Schedule explorer** – filter by department, semester, group, day, session type, or perform fuzzy text search for courses/teachers/rooms.
- **Room utilization view** – block/type filters, utilization percentages, and inline mini-timetables for every room, plus an alert list for unassigned sessions.

### Diagnostics mode

To verify data without starting the HTTP server:

```powershell
python -m src.app.server --print-metrics
```

This prints the latest snapshot metadata plus the aggregate counters returned by `/api/metrics`.


## �📋 Data Format

### Required Input Files

#### 1. Course Data (`courses.csv`)
```csv
id,teacher_id,course_code,course_name,course_type,lecture_hours,tutorial_hours,practical_hours,student_count,semester,course_dept,student_dept
1,101,CS101,Programming Fundamentals,Core,3,1,2,70,3,Computer Science & Engineering,Computer Science & Engineering
2,102,MA201,Mathematics II,Core,4,0,0,140,3,Mathematics,Computer Science & Engineering
```

**Required Columns:**
- `id`: Unique course instance identifier
- `teacher_id`: Teacher identifier  
- `course_code`: Course code (e.g., CS101)
- `course_name`: Full course name
- `lecture_hours`: Weekly lecture hours
- `tutorial_hours`: Weekly tutorial hours  
- `practical_hours`: Weekly practical/lab hours
- `student_count`: Number of enrolled students
- `semester`: Semester number (3, 5, 7, etc.)
- `student_dept`: Department of students taking the course

#### 2. Room Data (`techlongue.csv` or `rooms.csv`)
```csv
id,room_number,room_max_cap,is_lab,room_type,block,description
1,A301,70,0,Classroom,A Block,Theory Classroom
2,LAB1,35,1,Laboratory,K Block,Programming Lab
3,TIFAC-A401,140,0,Classroom,A Block,Large Classroom
```

**Required Columns:**
- `id`: Unique room identifier
- `room_number`: Room number/name
- `room_max_cap`: Maximum capacity
- `is_lab`: 1 for labs, 0 for classrooms
- `room_type`: Laboratory, Classroom, etc.
- `block`: Campus block (A Block, B Block, etc.)

### Optional Configuration Files

#### 3. Teacher Preferences (`pop.csv`)
```csv
id_faculty,name_faculty,subject_code,preffered_day_1,preffered_day_2
101,Dr. Smith,CS101,monday,wednesday
102,Prof. Johnson,MA201,tuesday,friday
```

#### 4. Day Pattern Configuration (`day_order.csv`)
```csv
Department,ODD
Computer Science & Engineering,Monday - Friday
Biotechnology,Tuesday - Saturday
Electronics & Communication Engineering,Monday - Saturday
```

#### 5. Core Lab Mapping (`og-final.csv`)
```csv
course_code,course_name,department,total_labs,lab_1,lab_2,lab_3
CS201,Data Structures,Computer Science,2,LAB1,LAB2,
EE301,Circuit Analysis,Electrical Engineering,3,EE_LAB1,EE_LAB2,EE_LAB3
```

## 🎛️ Configuration

### Scheduling Modes

| Mode | Description | Use Case |
|------|-------------|----------|
| `combined` | **Unified optimization** of lab and theory sessions | **Recommended** - Optimal resource utilization |
| `lab` | Laboratory sessions only | Lab-only scheduling or debugging |
| `theory` | Theory sessions only | Theory-only scheduling or debugging |
| `all` | Sequential lab then theory | Legacy mode - less optimal |

### Time Structures

#### Lab Sessions (6 × 2-hour blocks)
```
L1: 08:00 - 09:40   L4: 13:50 - 15:20
L2: 09:50 - 11:30   L5: 15:30 - 17:10  
L3: 11:40 - 13:20   L6: 17:20 - 19:00
```

#### Theory Sessions (11 × 1-hour slots)
```
T1: 08:00-08:50   T7:  13:50-14:40
T2: 08:55-09:45   T8:  15:20-16:10
T3: 09:50-10:40   T9:  16:15-17:05
T4: 10:45-11:35   T10: 17:10-18:00
T5: 11:40-12:30   T11: 18:10-19:00
T6: 12:35-13:20
```

### Grouping Controls

You can control where the "maximize each course into one group (if feasible)" behaviour applies.

- If `grouping.consolidation_dept_sem_allowlist` is empty (default), consolidation is enabled for **all departments** in **S5 & S6**.
- If it is non-empty, consolidation is enabled **only** for the cohorts you list.

Example (in `config/scheduler.yaml`):

```yaml
grouping:
    consolidation_dept_sem_allowlist:
        - "Information Technology|6"
        - "Mechanical Engineering|6"
        - "Computer Science & Engineering_S5"
```

### Constraint Configuration

#### Department-Specific 5PM Constraints
```python
# Hard constraints (cannot schedule after 5:30PM)
hard_5pm_departments = [
    "Artificial Intelligence & Data Science",
    "Computer Science & Engineering_S5",  # Semester-specific
]

# Soft constraints (discouraged after 5:00PM)
soft_5pm_departments = [
    "Electronics & Communication Engineering_S3",
]
```

#### Shift-Based Patterns
```python
shift_definitions = {
    'shift_1': '8AM-3:30PM',  # Early shift
    'shift_2': '10AM-5:30PM'  # Late shift
}
```

#### Lunch Break Management
```python
# Fixed lunch breaks
lunch_breaks = {
    ('Computer Science & Engineering', 3): 'Slot 4 (11:40-12:30)',
    ('Biotechnology', 5): 'Slot 3 (10:45-11:35)',
}

# Flexible lunch breaks (model decides)
flexible_lunch_departments = [
    ('Biomedical Engineering', 3),
    ('Mechanical Engineering', 5),
]
```

## 📊 Output Files

### Generated Schedules
```
output/combined_schedule_YYYYMMDD_HHMMSS/
├── combined_lab_schedule.csv           # Complete lab schedule
├── combined_lab_schedule.json          # Lab schedule (JSON format)
├── combined_theory_schedule.csv        # Complete theory schedule  
├── combined_theory_schedule.json       # Theory schedule (JSON format)
├── combined_schedule_summary.txt       # Summary statistics
├── visualizations/                     # Schedule visualizations
│   ├── combined_schedule_overview.png
│   ├── teacher_workload_analysis.png
│   └── room_utilization_heatmap.png
├── shift_reports/                      # Shift pattern analysis
│   ├── daily_campus_presence.json
│   ├── department_patterns.json
│   └── staff_violations.json
└── grouping_visualizations/            # Course group analysis
    ├── group_heatmap_CS_S3.png
    └── group_distribution_report.txt
```

### Schedule Data Format

#### Lab Schedule Output
```csv
day,session,room_id,room_number,teacher_id,teacher_name,course_code,course_name,student_count,department,semester,is_batched
tuesday,L1,45,LAB1,101,Dr. Smith,CS201,Data Structures Lab,35,Computer Science & Engineering,3,false
```

#### Theory Schedule Output  
```csv
day,time_slot,room_id,room_number,teacher_id,teacher_name,course_code,course_name,student_count,department,semester,group_name
tuesday,8:00 - 8:50,12,A301,102,Prof. Johnson,MA201,Mathematics II,70,Computer Science & Engineering,3,CS_S3_G1
```

## 🔧 Advanced Features

### 1. **Intelligent Room Assignment**
- **Capacity Matching**: Automatically assigns appropriate room sizes based on student count
- **Department Priorities**: CS/IT departments get priority for 70+ capacity labs
- **Block Optimization**: AIML/AIDS/CSD departments prioritized for K & J blocks
- **TIFAC Restrictions**: Core engineering departments get exclusive access to specialized TIFAC labs

### 2. **Cross-Department Teacher Management**
- **Individual Shift Patterns**: Teachers serving multiple departments get personalized schedules
- **Workload Balancing**: Automatic distribution of teaching load across departments
- **Conflict Prevention**: Real-time teacher availability tracking across all departments

### 3. **Batch Scheduling for Large Courses**
- **Automatic Batching**: Courses with 35+ students automatically split into manageable batches
- **Consecutive Preference**: Batched sessions scheduled consecutively for learning continuity
- **Capacity Intelligence**: Smart room selection based on actual batch sizes

### 4. **Department Day Patterns**
- **Flexible Patterns**: Support for Monday-Friday, Tuesday-Saturday, Monday-Saturday schedules
- **Semester Overrides**: Specific semesters can have different day patterns than department default
- **Holiday Management**: Built-in support for academic calendar variations

## 📈 Analytics & Validation

### Constraint Verification
The system provides comprehensive validation:

```bash
# Run constraint verification
python src/data_analytics/combined_analytics/combined_constraint_verifier.py

# Generate evaluation reports  
python src/data_analytics/combined_analytics/combined_schedule_evaluator.py
```

### Key Metrics Tracked
- **Teacher Conflicts**: Zero-tolerance for teacher double-booking
- **Room Conflicts**: Real-time room availability validation
- **Constraint Violations**: Comprehensive constraint compliance checking
- **Resource Utilization**: Room and teacher workload optimization metrics
- **Student Choice**: Hall's theorem compliance for maximum course selection flexibility

### Visualization Features
- **Schedule Heatmaps**: Visual representation of time slot utilization
- **Teacher Workload**: Individual teacher schedule visualization
- **Room Occupancy**: Campus-wide room utilization analysis
- **Group Distributions**: Course group allocation visualization
- **Conflict Analysis**: Detailed conflict identification and resolution tracking

## 🛠️ Development

### Project Structure
```
timetable_scheduler/
├── main.py                            # Main entry point
├── src/                               # Core scheduling modules
│   ├── combined_scheduler.py          # Unified scheduler (main engine)
│   ├── lab_scheduler.py              # Lab-specific scheduling
│   ├── theory_scheduler.py           # Theory-specific scheduling
│   ├── course_group_optimizer.py     # Course grouping optimization
│   ├── visualizer.py                 # Schedule visualization
│   ├── data_analytics/               # Analysis and validation tools
│   └── utils/                        # Utility functions
├── data/                             # Input data files
│   ├── block_wise/                   # Room data by campus blocks
│   ├── department_data/              # Course data by departments
│   └── mapped_data/                  # Processed/mapped data
├── output/                           # Generated schedules and reports
├── old/                             # Legacy implementations
└── biotechnology_optimization_results/ # Department-specific results
```

### Key Classes

#### `CombinedScheduler`
The main scheduling engine that coordinates all scheduling activities:
- Unified constraint management
- Cross-system conflict resolution  
- Optimization objective management
- Solution extraction and validation

#### `CourseGroupOptimizer`
Handles intelligent course grouping:
- OR-Tools based optimization
- Hall's theorem compliance
- Virtual instance management
- Student choice maximization

#### `LabScheduler` & `TheoryScheduler`
Specialized schedulers for specific session types:
- Time structure management
- Resource allocation
- Constraint application
- Schedule generation

### Adding New Constraints

1. **Create constraint method in CombinedScheduler**:
```python
def apply_new_constraint(self, model, variables):
    """Apply new scheduling constraint."""
    constraints_applied = 0
    
    # Implement constraint logic
    for teacher_id in variables:
        # Add constraint using OR-Tools CP-SAT
        model.Add(constraint_expression)
        constraints_applied += 1
    
    return constraints_applied
```

2. **Add to unified constraints**:
```python
def _apply_unified_constraints(self, model, lab_variables, theory_variables):
    # ... existing constraints ...
    constraints_applied += self.apply_new_constraint(model, lab_variables)
    return constraints_applied
```

3. **Test thoroughly**:
```bash
python main.py --mode combined --course-file test_data.csv --room-file test_rooms.csv
```

## 🧪 Testing

### Unit Tests
```bash
# Run constraint validation
python src/data_analytics/combined_analytics/combined_constraint_verifier.py

# Test course grouping
python src/course_group_optimizer.py --test-mode

# Validate room assignments
python check_double_bookings.py
```

### Integration Tests
```bash
# Test complete scheduling pipeline
python main.py --mode combined --course-file data/test_courses.csv --room-file data/test_rooms.csv

# Validate cross-system integration
python src/data_analytics/combined_analytics/combined_schedule_evaluator.py
```

### Performance Benchmarks
- **Small Dataset** (5 departments, 50 courses): < 30 seconds
- **Medium Dataset** (10 departments, 200 courses): < 2 minutes  
- **Large Dataset** (15+ departments, 500+ courses): < 10 minutes

## 🤝 Contributing

We welcome contributions! Please follow these guidelines:

### Development Setup
1. Fork the repository
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Install development dependencies: `pip install -r requirements.txt`
4. Make your changes with comprehensive testing
5. Commit with clear messages: `git commit -m 'Add amazing feature'`
6. Push to your branch: `git push origin feature/amazing-feature`
7. Create a Pull Request

### Contribution Guidelines
- **Maintain constraint hierarchy**: Core constraints should have priority
- **Test cross-system interactions**: Changes to lab constraints may affect theory scheduling
- **Validate department patterns**: Ensure new features respect day pattern configurations
- **Add comprehensive logging**: Use structured logging for debugging complex constraints
- **Update documentation**: Keep method documentation current with changes

### Code Style
- Follow PEP 8 style guidelines
- Use meaningful variable names
- Add docstrings to all public methods
- Include type hints where appropriate
- Write comprehensive test cases

## 🐛 Troubleshooting

### Common Issues

#### 1. **No Solution Found**
```python
# Check feasibility first
if not scheduler.analyze_theory_feasibility():
    print("Theory scheduling not feasible with current constraints")
```

**Solutions:**
- Reduce constraint complexity
- Increase available time slots
- Check for conflicting requirements
- Verify teacher-course assignments

#### 2. **Room Conflicts**
**Symptoms:** Multiple sessions assigned to same room at same time

**Solutions:**
- Ensure `techlongue.csv` has correct room data
- Check for duplicate room IDs
- Verify block assignments are consistent
- Review room capacity requirements

#### 3. **Teacher Conflicts** 
**Symptoms:** Teachers assigned to multiple sessions simultaneously

**Solutions:**
- Review teacher workload distribution
- Check cross-department teacher assignments  
- Validate day pattern consistency
- Ensure teacher ID consistency across files

#### 4. **Performance Issues**
**Symptoms:** Solver takes too long or runs out of memory

**Solutions:**
```python
# Adjust solver parameters
solver.parameters.max_time_in_seconds = 4000
solver.parameters.num_search_workers = 16  
solver.parameters.max_memory_in_mb = 30000
```

- Reduce dataset size for testing
- Simplify constraints temporarily
- Use progressive constraint application
- Monitor memory usage

### Debug Mode
```bash
# Enable detailed logging
export PYTHONPATH=.
python main.py --mode combined --course-file data/debug_courses.csv --room-file data/debug_rooms.csv --log-level DEBUG
```

### Support
- **GitHub Issues**: Report bugs and feature requests
- **Documentation**: Check the comprehensive README and inline documentation
- **Code Examples**: See the `/examples` directory for usage patterns

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- **Google OR-Tools**: For providing the powerful constraint programming solver
- **Academic Community**: For feedback and real-world testing scenarios
- **Contributors**: All developers who have contributed to improving the system

## 📞 Contact

- **Project Repository**: [GitHub Repository URL]
- **Issue Tracker**: [GitHub Issues URL]
- **Documentation**: [Documentation URL]

---

**Built with ❤️ for the academic community using modern constraint programming techniques.** 