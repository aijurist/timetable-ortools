# Remote Server Import Scripts

Retrieved from:

`root@187.127.150.104:/root/Exovance-Timetable-Scheduler-Core/backend`

Retrieved on: 2026-06-19

## What matters

- `scripts/reimport_all.py` is the main full reimport script. It rebuilds rooms, faculty, courses, PE/OE teaching assignments, scheduled sessions, cohorts, course offerings, and buckets from legacy CSV/telemetry seed files.
- `scripts/import_legacy_schedule.py` imports generated legacy scheduler CSV output into the app DB `scheduled_sessions` structure.
- `src/app/services/bulk/course_import.py` is the FastAPI service for course bulk upload/import.
- `src/app/services/bulk/base.py` contains the shared CSV/XLSX parser and fuzzy column mapping used by bulk imports.
- `scripts/export_for_legacy_scheduler.py` does the reverse direction: app DB to old scheduler CSV/config inputs.

## Included dependencies

- `data/legacy_seeds/` contains the seed CSV files used by `reimport_all.py`.
- `scripts/data/` contains the course/faculty/student/room source files used by the server import/seed scripts.

Secrets such as server `.env` files were not copied.
