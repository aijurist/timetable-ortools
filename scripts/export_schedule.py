"""Merge the latest generated schedule into a single CSV.

Outputs columns:
  day, session_name, time_range, course_instance_id, course_code, course_code_display,
  course_name, practical_hours, teacher_id, teacher_name, staff_code, room_id,
  room_number, block, capacity, student_count, total_students, is_batched,
  batch_info, num_batches, schedule_type, group_name, group_index, department,
  semester, day_pattern, is_co_scheduled, co_schedule_id, co_schedule_group_size,
  co_schedule_partner_teachers, co_schedule_info

Usage:
  python scripts/export_schedule.py --root output --run-dir output/2025-12-18_00-11-55 --out merged.csv

If --run-dir is omitted, the newest timestamped folder under --root is used.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Dict, Iterable, List, Mapping

COLUMNS = [
    "day",
    "session_name",
    "time_range",
    "course_instance_id",
    "course_code",
    "course_code_display",
    "course_name",
    "practical_hours",
    "teacher_id",
    "teacher_name",
    "staff_code",
    "room_id",
    "room_number",
    "block",
    "capacity",
    "student_count",
    "total_students",
    "is_batched",
    "batch_info",
    "num_batches",
    "schedule_type",
    "group_name",
    "group_index",
    "department",
    "semester",
    "day_pattern",
    "is_co_scheduled",
    "co_schedule_id",
    "co_schedule_group_size",
    "co_schedule_partner_teachers",
    "co_schedule_info",
]


def find_latest_run(root: Path) -> Path:
    run_dirs = [d for d in root.iterdir() if d.is_dir()]
    if not run_dirs:
        raise FileNotFoundError(f"No run folders found under {root}")
    return sorted(run_dirs)[-1]


def read_json_or_csv(path: Path) -> List[Mapping[str, object]]:
    if not path.exists():
        return []
    if path.suffix.lower() == ".json":
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            raise ValueError(f"Unexpected JSON structure in {path}")
    rows: List[Mapping[str, object]] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows.extend(reader)
    return rows


def parse_capacity(value: object) -> str:
    if value is None:
        return ""
    text = str(value)
    digits = re.findall(r"\d+", text)
    return digits[0] if digits else text


def to_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = str(value).strip().lower()
    return text in {"true", "1", "yes", "y"}


def normalize_entry(entry: Mapping[str, object], schedule_type: str) -> Dict[str, object]:
    row: Dict[str, object] = {col: "" for col in COLUMNS}
    row["schedule_type"] = schedule_type
    row["day"] = entry.get("day", "")
    row["session_name"] = entry.get("session_name") or entry.get("time_slot") or ""
    row["time_range"] = entry.get("time_range") or entry.get("time_slot") or ""
    row["course_instance_id"] = entry.get("course_instance_id", "")
    row["course_code"] = entry.get("course_code", "")
    row["course_code_display"] = entry.get("course_code_display") or entry.get("course_code", "")
    row["course_name"] = entry.get("course_name", "")
    practical = entry.get("practical_hours")
    if practical in (None, ""):
        practical = 0
    row["practical_hours"] = practical
    row["teacher_id"] = entry.get("teacher_id", "")
    row["teacher_name"] = entry.get("teacher_name", "")
    row["staff_code"] = entry.get("staff_code", "")
    row["room_id"] = entry.get("room_id", "")
    row["room_number"] = entry.get("room_number", "")
    row["block"] = entry.get("block", "")
    capacity = entry.get("capacity")
    if not capacity:
        capacity = parse_capacity(entry.get("capacity_info"))
    row["capacity"] = capacity
    row["student_count"] = entry.get("student_count", "")
    row["total_students"] = entry.get("total_students", "")
    row["is_batched"] = to_bool(entry.get("is_batched"))
    row["batch_info"] = entry.get("batch_info", "")
    row["num_batches"] = entry.get("num_batches", 1)
    row["group_name"] = entry.get("group_name", "")
    row["group_index"] = entry.get("group_index", "")
    row["department"] = entry.get("department", "")
    row["semester"] = entry.get("semester", "")
    row["day_pattern"] = entry.get("day_pattern", "")
    row["is_co_scheduled"] = to_bool(entry.get("is_co_scheduled"))
    row["co_schedule_id"] = entry.get("co_schedule_id", "")
    row["co_schedule_group_size"] = entry.get("co_schedule_group_size", "")
    row["co_schedule_partner_teachers"] = entry.get("co_schedule_partner_teachers", "")
    row["co_schedule_info"] = entry.get("co_schedule_info", "")
    return row


def load_run_entries(run_dir: Path) -> tuple[List[Dict[str, object]], List[Mapping[str, object]], List[Mapping[str, object]]]:
    """Load and process schedule entries from a run directory.
    
    Returns:
        A tuple of (normalized_entries, raw_lab_entries, raw_theory_entries).
        normalized_entries are for CSV export, raw entries preserve original keys for JSON export.
    """
    entries: List[Dict[str, object]] = []
    
    schedule_json = run_dir / "schedule.json"
    if not schedule_json.exists():
        raise FileNotFoundError(f"schedule.json not found in {run_dir}")
    
    with schedule_json.open("r", encoding="utf-8") as f:
        data = json.load(f)
    
    # Get raw entries (preserve original keys)
    raw_lab_entries = data.get("lab_entries", [])
    raw_theory_entries = data.get("theory_entries", [])
    
    # Read lab_entries (normalized for CSV)
    for raw in raw_lab_entries:
        entries.append(normalize_entry(raw, "lab"))
    
    # Read theory_entries (normalized for CSV)
    for raw in raw_theory_entries:
        entries.append(normalize_entry(raw, "theory"))
    
    if not entries:
        raise FileNotFoundError(f"No entries found in {schedule_json}")
    return entries, raw_lab_entries, raw_theory_entries


def write_csv(rows: Iterable[Mapping[str, object]], dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_json(rows: Iterable[Mapping[str, object]], dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8") as f:
        json.dump(list(rows), f, ensure_ascii=False, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export merged schedule CSV from latest run output")
    parser.add_argument("--root", type=Path, default=Path("output"), help="Root output folder containing run folders")
    parser.add_argument("--run-dir", type=Path, default=None, help="Specific run folder; defaults to newest under --root")
    parser.add_argument("--out", type=Path, default=None, help="Destination CSV; default is <run-dir>/merged_schedule.csv")
    parser.add_argument("--json-out", action="store_true", help="Output separate lab_schedule.json and theory_schedule.json files")
    args = parser.parse_args()

    run_dir = args.run_dir or find_latest_run(args.root)
    if not run_dir.exists():
        raise FileNotFoundError(f"Run directory not found: {run_dir}")

    rows, raw_lab_entries, raw_theory_entries = load_run_entries(run_dir)
    out_path = args.out or (run_dir / "merged_schedule.csv")
    write_csv(rows, out_path)
    print(f"Wrote {len(rows)} rows to {out_path}")

    if args.json_out:
        lab_json_path = run_dir / "lab_schedule.json"
        theory_json_path = run_dir / "theory_schedule.json"
        
        # Use raw entries to preserve original keys (no normalization)
        write_json(raw_lab_entries, lab_json_path)
        write_json(raw_theory_entries, theory_json_path)
        print(f"Wrote {len(raw_lab_entries)} lab rows to {lab_json_path}")
        print(f"Wrote {len(raw_theory_entries)} theory rows to {theory_json_path}")


if __name__ == "__main__":
    main()
