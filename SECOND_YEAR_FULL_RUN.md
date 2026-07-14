# Full second-year timetable run

From the repository root on the solver PC:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -u scripts\run_full_second_year.py
```

The command verifies that both `prod/` schedule locks match the approved
`copy/kutty_concepts` files, solves all 19 departments with hard lunch and the
same optimization policy, validates clashes/coverage, and writes the complete
result to:

```text
output/timetables/second_year_full/
```

The run is certified only when `full_run_report.json` says `PASS`: all 19
departments must be present, both phases must be `OPTIMAL` for every department,
and the validator must report zero violations.

Before the combined run, certify every department independently with the same
hard-lunch rule and the production locks:

```powershell
.venv\Scripts\python.exe -u scripts\run_departments_individually.py --phase1-time 900 --phase2-time 900 --workers 16 --run-tag dept_by_dept_hard_deterministic
```

The independent report is written to:

```text
output/timetables/dept_by_dept_hard_deterministic/report.csv
```

To certify the 12 departments without DBMS/OOPS/DB-Tech independently (each
department sees only the production locks):

```powershell
.venv\Scripts\python.exe -u scripts\run_departments_individually.py --core-only --phase1-time 300 --phase2-time 300 --workers 16 --run-tag core_departments_hard_lunch
```

To produce one composed, cross-department conflict-free timetable for those 12
departments, use the full runner. It solves them sequentially on one shared
occupancy calendar, so every department reserves rooms and staff before the next
department is placed:

```powershell
.venv\Scripts\python.exe -u scripts\run_full_second_year.py --core-only --phase1-time 900 --phase2-time 900 --workers 16 --phase1-gap 25 --run-tag core_departments_composed
```

Override the direct solve proof budgets when required:

```powershell
.venv\Scripts\python.exe -u scripts\run_full_second_year.py --phase1-time 1200 --phase2-time 1200 --workers 16
```

Both commands use one fixed CP-SAT tie-breaker and one direct pass. Parallel
workers accelerate that pass, but the scheduler never retries random seeds or
relaxes lunch to a soft constraint.

The independent certification accepts an absolute Phase-1 gap of 25 points:
at most one additional ordinary lab cell above the solver's proven bound. This
prevents A.I.D.S. from spending minutes proving `1500` after a valid `1525`
hard-lunch timetable has already been found. Phase 2 is still solved without
that tolerance.
