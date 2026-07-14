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

Override proof budgets or worker count when required:

```powershell
.venv\Scripts\python.exe -u scripts\run_full_second_year.py --phase1-time 1200 --phase2-time 1200 --workers 24
```
