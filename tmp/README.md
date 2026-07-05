# Exovance Timetable Export and Conversion Utilities

This directory contains one complete workflow for taking the current Exovance
production database, converting it into the older `jan9.sqlite`-style schema,
and exporting timetable input files used by the existing scheduler tooling.

The usual order is:

1. `pull_exovance_latest_sqlite.py` - pull the live Exovance database from the
   VPS and save it locally as SQLite.
2. `convert_exovance_to_jan9.py` - convert that new Exovance SQLite dump into
   the older Jan 9/Django schema.
3. `main.py` - export department-wise course allocation CSV files from the
   converted database.
4. `extract_timetable_artifacts.py` - optionally export additional scheduler
   support files such as rooms, POP availability, lab mappings, and day-order
   reports.

## Directory Contents

### `pull_exovance_latest_sqlite.py`

Pulls the latest live Exovance database from the remote server and builds a
local SQLite copy.

What it does:

- Connects to the VPS over SSH.
- Runs a remote export script against the Postgres database inside Docker.
- Exports all non-system tables, views, and materialized views to CSV.
- Downloads the export archive with `scp`.
- Verifies the archive SHA256 hash.
- Rebuilds the export as a local SQLite database.
- Adds export metadata tables:
  - `_export_metadata`
  - `_table_counts`
- Runs SQLite integrity and row-count checks.
- Removes the temporary export files from the server when possible.

Default connection settings:

```text
Host:        89.116.121.23
User:        root
SSH key:     ~/.ssh/timetable
Container:   exo_postgres
DB user:     exovance
DB name:     exovance_prod
Output dir:  D:\data_works_timetable
```

Default output naming:

```text
D:\data_works_timetable\exovance-YYYY-MM-DD-vN.sqlite
```

For example, if you run it multiple times on the same day, it will create
`v1`, `v2`, `v3`, and so on.

### `convert_exovance_to_jan9.py`

Converts the new Exovance SQLite export into the older `jan9.sqlite` schema
used by older scheduler scripts.

Current hard-coded paths inside the script:

```python
BASE = 'D:/data_works_timetable/'
NEW = BASE + 'exovance-2026-06-16-v1.sqlite'
OLD = BASE + 'jan9.sqlite'
OUT = BASE + 'exovance_converted_jan9_20260612.sqlite'
```

Before running this script, make sure those files exist, or edit the constants
at the top of the file to match the new dump you pulled.

What it reads:

- `NEW`: the Exovance live SQLite export produced by
  `pull_exovance_latest_sqlite.py`.
- `OLD`: the existing `jan9.sqlite` reference database. This is used for:
  - cloning the old table structure;
  - reusing known department, course, room, teacher, student, and offering IDs
    where natural keys match;
  - preserving old scheduler-compatible values where the new schema does not
    contain an exact equivalent.

What it writes:

- `OUT`: a new SQLite database with the old Jan 9/Django table structure.
- `D:\data_works_timetable\conversion_log.txt`: a readable conversion log.
- `_conversion_id_map` inside the converted database. This is important for
  later scripts because it maps new Exovance UUIDs to converted Jan 9 integer
  IDs.

Major mappings:

| Exovance source | Converted Jan 9 table |
| --- | --- |
| `departments` | `department_department` |
| `users` | `authentication_user` |
| `faculty` | `teacher_teacher` |
| `rooms` | `rooms_room` |
| `courses` | `courseMaster_coursemaster` |
| course room preferences | `courseMaster_coursemasterroompreference` |
| `teaching_assignments` | `course_course` and `teacherCourse_teachercourse` |
| `student_profiles` | `student_student` |
| `time_grids.slots` JSON | `timetableMaster_session` |

Important behavior:

- Existing Jan 9 IDs are reused when possible.
- New IDs are allocated above the old maximum ID range.
- Department-declared vacancy faculty are converted as placeholder teachers.
- Unassigned teaching assignments get one placeholder teacher per teaching
  department.
- Course structure JSON such as `{"L": 3, "T": 0, "P": 2}` is converted into
  lecture, tutorial, and practical hour columns.
- `teaching_assignments.section_count` is expanded into one
  `teacherCourse_teachercourse` row per section.
- Student count is estimated from department-year cohort size divided by
  section count, with department class size as fallback.
- The output database is deleted and recreated if the `OUT` path already
  exists.

### `main.py`

Exports department-wise course allocation data from the converted Jan 9-style
database.

This script is interactive. It asks for the SQLite database path at runtime.
Use the converted database produced by `convert_exovance_to_jan9.py`.

What it extracts:

- student department;
- teaching department;
- owning department;
- course code, name, type, credits, and L/T/P hours;
- academic year and semester;
- assigned teacher details;
- student count;
- room preference and room assignment details;
- lab assignment status.

Filtering applied:

- Includes only `academic_year >= 2`.
- Includes only `semester >= 2`.
- Includes only `BE` and `BTECH` courses.

Outputs:

```text
data\combined_course_data.csv
data\<academic_year>\<Department>_course_data.csv
```

The `data` directory is created relative to the directory where you run the
script. If you run the script from this `tmp` directory, the output will be
created under:

```text
D:\timetable-scheduler\tmp\data
```

The script also cleans department names in the CSV output by removing
`Department of ` and replacing ` and ` with ` & `.

### `extract_timetable_artifacts.py`

Optionally extracts additional scheduler support files from both:

- the original Exovance SQLite dump; and
- the converted Jan 9-style SQLite database.

Run this after `convert_exovance_to_jan9.py`. It depends on the
`_conversion_id_map` table created by the converter.

Outputs:

| File | Purpose |
| --- | --- |
| `rooms_new.csv` | All converted rooms in Jan 9-compatible columns. |
| `pop.csv` | POP, adjunct, and constrained faculty availability windows. |
| `core_lab_mapping.csv` | Course-to-core-lab mapping, including Exovance data, optional Jan 9 backfill, and manual overrides. |
| `computer_lab_mapping.csv` | Course-to-computer-lab room/block preferences. |
| `consecutive_labs.csv` | Offered courses with `P >= 4`, meaning they need multiple lab blocks per week. |
| `day_order_report.txt` | Observed department-wise working-day usage from published scheduled sessions. |

Notes:

- POP availability is built from `faculty.availability_blacklist` and
  `faculty.preferences`.
- Availability blacklist codes such as `MON-A` through `SAT-F` are interpreted
  as six daily lab/session blocks.
- Core lab mappings come from Exovance room preferences first, then optional
  old Jan 9 backfill, then manual overrides.
- The current manual core-lab override maps `EE23B21` to `TANCAM`.
- If no old `jan9.sqlite` path is available, core-lab backfill is skipped.

## Prerequisites

- Python 3.
- SSH access to the Exovance VPS.
- The SSH key expected by the pull script, by default:

```text
~/.ssh/timetable
```

- `ssh` and `scp` available in PowerShell.
- The remote server must have the expected Docker container and Postgres
  database:

```text
Docker container: exo_postgres
Database user:    exovance
Database name:    exovance_prod
```

- A reference old-schema database at:

```text
D:\data_works_timetable\jan9.sqlite
```

## Recommended Runbook

Run these commands from PowerShell.

First, move into this directory:

```powershell
cd D:\timetable-scheduler\tmp
```

### 1. Pull the Exovance live database

If you want the output file to match the current hard-coded converter input,
run:

```powershell
python .\pull_exovance_latest_sqlite.py --output "D:\data_works_timetable\exovance-2026-06-16-v1.sqlite"
```

If you want a date-versioned latest dump instead, run:

```powershell
python .\pull_exovance_latest_sqlite.py
```

When using the date-versioned output, update the `NEW` constant in
`convert_exovance_to_jan9.py` before running the conversion.

### 2. Convert the Exovance dump to Jan 9 format

Check these constants at the top of `convert_exovance_to_jan9.py`:

```python
BASE = 'D:/data_works_timetable/'
NEW = BASE + 'exovance-2026-06-16-v1.sqlite'
OLD = BASE + 'jan9.sqlite'
OUT = BASE + 'exovance_converted_jan9_20260612.sqlite'
```

Then run:

```powershell
python .\convert_exovance_to_jan9.py
```

Expected main output:

```text
D:\data_works_timetable\exovance_converted_jan9_20260612.sqlite
```

Expected log:

```text
D:\data_works_timetable\conversion_log.txt
```

### 3. Export department-wise allocation CSVs

Run:

```powershell
python .\main.py
```

When prompted, enter:

```text
D:\data_works_timetable\exovance_converted_jan9_20260612.sqlite
```

Expected outputs:

```text
D:\timetable-scheduler\tmp\data\combined_course_data.csv
D:\timetable-scheduler\tmp\data\<academic_year>\<Department>_course_data.csv
```

### 4. Optionally extract additional timetable artifacts

Run:

```powershell
python .\extract_timetable_artifacts.py `
  --source "D:\data_works_timetable\exovance-2026-06-16-v1.sqlite" `
  --converted "D:\data_works_timetable\exovance_converted_jan9_20260612.sqlite" `
  --jan9 "D:\data_works_timetable\jan9.sqlite" `
  --outdir ".\artifacts"
```

Expected outputs:

```text
D:\timetable-scheduler\tmp\artifacts\rooms_new.csv
D:\timetable-scheduler\tmp\artifacts\pop.csv
D:\timetable-scheduler\tmp\artifacts\core_lab_mapping.csv
D:\timetable-scheduler\tmp\artifacts\computer_lab_mapping.csv
D:\timetable-scheduler\tmp\artifacts\consecutive_labs.csv
D:\timetable-scheduler\tmp\artifacts\day_order_report.txt
```

To skip old Jan 9 core-lab backfill:

```powershell
python .\extract_timetable_artifacts.py `
  --source "D:\data_works_timetable\exovance-2026-06-16-v1.sqlite" `
  --converted "D:\data_works_timetable\exovance_converted_jan9_20260612.sqlite" `
  --jan9 "" `
  --outdir ".\artifacts"
```

## Quick Output Checklist

After a successful run, confirm these files exist:

```text
D:\data_works_timetable\exovance-2026-06-16-v1.sqlite
D:\data_works_timetable\exovance_converted_jan9_20260612.sqlite
D:\data_works_timetable\conversion_log.txt
D:\timetable-scheduler\tmp\data\combined_course_data.csv
```

If you ran the optional artifact extraction, also confirm:

```text
D:\timetable-scheduler\tmp\artifacts\rooms_new.csv
D:\timetable-scheduler\tmp\artifacts\pop.csv
D:\timetable-scheduler\tmp\artifacts\core_lab_mapping.csv
D:\timetable-scheduler\tmp\artifacts\computer_lab_mapping.csv
D:\timetable-scheduler\tmp\artifacts\consecutive_labs.csv
D:\timetable-scheduler\tmp\artifacts\day_order_report.txt
```

## Common Problems

### Converter cannot find the Exovance dump

`convert_exovance_to_jan9.py` does not accept command-line arguments. It reads
the `NEW`, `OLD`, and `OUT` constants from the top of the file.

Fix one of these:

- run the pull script with `--output` set to the exact `NEW` path; or
- edit `NEW` in `convert_exovance_to_jan9.py` to match the pulled dump.

### Converter cannot find `jan9.sqlite`

Place the old reference database at:

```text
D:\data_works_timetable\jan9.sqlite
```

Or edit the `OLD` constant in `convert_exovance_to_jan9.py`.

### `extract_timetable_artifacts.py` fails because `_conversion_id_map` is missing

Run `convert_exovance_to_jan9.py` first and pass its output database as the
`--converted` value.

### `main.py` writes output somewhere unexpected

`main.py` writes to a relative `data` directory. The actual output location
depends on the directory from which you run the script.

Run it from `D:\timetable-scheduler\tmp` if you want:

```text
D:\timetable-scheduler\tmp\data
```

### SSH or SCP fails

Check:

- the VPS is reachable;
- the SSH key exists at `~/.ssh/timetable`;
- the key has access to `root@89.116.121.23`;
- the remote Docker container name is still `exo_postgres`;
- the database name is still `exovance_prod`.

## Suggested Future Cleanup

These scripts work as a pipeline, but two improvements would make them easier
to reuse:

- Add command-line arguments to `convert_exovance_to_jan9.py` for `--source`,
  `--jan9`, and `--output` instead of editing constants.
- Add a non-interactive `--db` argument to `main.py` so the whole workflow can
  be scripted end to end.
