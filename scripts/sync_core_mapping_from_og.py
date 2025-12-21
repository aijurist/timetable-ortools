"""Sync missing core-lab mapping rows from the OG-format CSV into the simplified CSV.

This script appends rows that exist in the OG file but are missing in the simplified file.

Matching is done on the *full row signature* in the target schema (all columns in the
simplified CSV). This is important because some (course_code, department) pairs may
legitimately appear multiple times with different lab mappings.

Example:
  python scripts/sync_core_mapping_from_og.py \
    --source "data/CoreMapping (StudentDept) - OG Final Format.csv" \
    --target data/CoreMappingSimplified_StudentDept.csv \
    --in-place
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple


def _strip(v: object) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _read_csv(path: Path) -> Tuple[Sequence[str], List[Dict[str, str]]]:
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError(f"Missing CSV header: {path}")
        rows = [{k: _strip(v) for k, v in row.items()} for row in reader]
        return list(reader.fieldnames), rows


def _row_signature(row: Dict[str, str], columns: Sequence[str]) -> Tuple[str, ...]:
    return tuple(_strip(row.get(col, "")) for col in columns)


def _map_source_row_to_target(
    source_row: Dict[str, str],
    target_columns: Sequence[str],
) -> Dict[str, str]:
    # OG file uses "Student Department" for the department column.
    department = (
        source_row.get("department")
        or source_row.get("Student Department")
        or source_row.get("StudentDepartment")
        or ""
    )

    mapped: Dict[str, str] = {}
    for col in target_columns:
        if col == "department":
            mapped[col] = _strip(department)
        else:
            mapped[col] = _strip(source_row.get(col, ""))

    # Ensure core identifiers are present if available under expected names.
    # (Most files already have these exact names.)
    if "course_code" in target_columns:
        mapped["course_code"] = _strip(source_row.get("course_code", mapped.get("course_code", "")))
    if "course_name" in target_columns:
        mapped["course_name"] = _strip(source_row.get("course_name", mapped.get("course_name", "")))

    return mapped


def _write_csv(path: Path, columns: Sequence[str], rows: Iterable[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in columns})


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Append missing rows from OG core mapping CSV into the simplified core mapping CSV. "
            "Missing is determined by full-row signature in the simplified schema."
        )
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("data/CoreMapping (StudentDept) - OG Final Format.csv"),
        help="Path to OG-format CSV (default: data/CoreMapping (StudentDept) - OG Final Format.csv)",
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=Path("data/CoreMappingSimplified_StudentDept.csv"),
        help="Path to simplified CSV (default: data/CoreMappingSimplified_StudentDept.csv)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write the merged CSV to this path (default: <target>.merged.csv)",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Overwrite --target in place (takes precedence over --output)",
    )

    args = parser.parse_args(argv)

    source_path: Path = args.source
    target_path: Path = args.target

    if not source_path.exists():
        raise FileNotFoundError(source_path)
    if not target_path.exists():
        raise FileNotFoundError(target_path)

    target_columns, target_rows = _read_csv(target_path)
    _, source_rows = _read_csv(source_path)

    target_signatures = {_row_signature(row, target_columns) for row in target_rows}

    added_rows: List[Dict[str, str]] = []
    skipped_missing_keys = 0

    for src in source_rows:
        mapped = _map_source_row_to_target(src, target_columns)

        # If core identifiers are missing, skip: we can't reliably merge it.
        if not mapped.get("course_code") or not mapped.get("department"):
            skipped_missing_keys += 1
            continue

        sig = _row_signature(mapped, target_columns)
        if sig in target_signatures:
            continue

        target_signatures.add(sig)
        added_rows.append(mapped)

    if args.in_place:
        out_path = target_path
    else:
        out_path = args.output or target_path.with_suffix(".merged.csv")

    _write_csv(out_path, target_columns, list(target_rows) + added_rows)

    print(f"Target rows: {len(target_rows)}")
    print(f"Source rows: {len(source_rows)}")
    print(f"Added rows:  {len(added_rows)}")
    if skipped_missing_keys:
        print(f"Skipped rows with missing course_code/department: {skipped_missing_keys}")
    print(f"Wrote: {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
