# Timetable Scheduler — Learning Chapters

This folder contains short, focused Python chapters that teach the core concepts used in `combined_scheduler.py`.

Each chapter is a small, runnable script with a short explanation and a minimal example. Run chapters with:

```powershell
python learning\run_all.py
```

Chapters:
- 01_data_loading.py — pandas: reading and sanitizing course/room CSVs
- 02_time_config.py — time slots, lab sessions, and mapping between lab/theory
- 03_rooms_groups.py — room data structures and department-preferred room selection
- 04_groups.py — course grouping logic and Hall's-theorem sanity check
- 05_cpsat_basics.py — CP-SAT basics (variables, constraints, objective)
- 06_lab_modeling.py — simple lab assignment model
- 07_theory_modeling.py — simple theory scheduling model
- 08_constraints_patterns.py — common constraint patterns (teacher clashes, capacity)
- 09_solver_tips.py — solver parameters, warm starts, callbacks, profiling
- 10_extraction_validation.py — extracting schedules and running lightweight validation checks
 - 11_modeling_patterns.py — encoding patterns (linearization, symmetry breaking, grouping)
 - 12_decomposition_warmstart.py — labs-first warm-start pattern and soft-fix example
 - 13_presolve_pruning.py — presolve strategies and Hall-style pruning checks
 - 14_performance_tuning.py — solver parameter tuning and diagnostics
 - 15_callbacks_debugging.py — solution callbacks, logging and instrumentation
 - 16_case_study_combined_mapping.py — mapping the monolith to modular patterns
 - 17_hard_soft_constraints.py — patterns for hard vs soft constraints (boolean penalties, integer overcap)

Requirements: see `requirements.txt`.
