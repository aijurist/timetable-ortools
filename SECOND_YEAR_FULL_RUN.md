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
.venv\Scripts\python.exe -u scripts\run_departments_individually.py --phase1-time 900 --phase2-time 900 --run-tag dept_by_dept_hard_deterministic
```

The independent report is written to:

```text
output/timetables/dept_by_dept_hard_deterministic/report.csv
```

Override the direct solve proof budgets when required:

```powershell
.venv\Scripts\python.exe -u scripts\run_full_second_year.py --phase1-time 1200 --phase2-time 1200
```

Both commands use one worker and one fixed CP-SAT tie-breaker. They do not retry
random seeds or relax lunch to a soft constraint.
