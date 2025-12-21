#!/usr/bin/env python3
"""Replace PE-specific course codes with their general PE code.

Example mapping row (from data/pe_course_map.csv):
  BT23PE02,BT23C12,BT23F13,,BT,6

This script will replace any occurrence of BT23C12 or BT23F13 in the input
CSV's `course_code` column with BT23PE02 (optionally only when elective_type == PE).

Usage:
  python scripts/replace_pe_codes_with_general.py \
    --input data/sem2026/year_wise/Year_3_course_data.csv \
    --mapping data/pe_course_map.csv \
    --output data/sem2026/year_wise/Year_3_course_data.with_general_pe.csv

  # In-place (overwrites input file):
  python scripts/replace_pe_codes_with_general.py \
    --input data/sem2026/year_wise/Year_3_course_data.csv \
    --mapping data/pe_course_map.csv \
    --in-place
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


@dataclass(frozen=True)
class MappingStats:
    total_rows: int
    changed_rows: int
    unchanged_rows: int


def load_pe_mapping(mapping_csv: Path, *, min_pe_options: int) -> Dict[str, str]:
    """Return a dict mapping each PE option code -> GENERAL CODE.

    Only includes GENERAL CODE rows that have at least `min_pe_options` non-empty
    PE option codes across PE1/PE2/PE3.
    """
    if not mapping_csv.exists():
        raise FileNotFoundError(f"Mapping file not found: {mapping_csv}")

    pe_to_general: Dict[str, str] = {}

    with mapping_csv.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        required_cols = {"GENERAL CODE", "PE1", "PE2", "PE3"}
        missing = required_cols - set(reader.fieldnames or [])
        if missing:
            raise ValueError(
                f"Mapping CSV missing columns {sorted(missing)}. "
                f"Found: {reader.fieldnames}"
            )

        for row in reader:
            general = (row.get("GENERAL CODE") or "").strip()
            if not general:
                continue

            pe_codes = [
                (row.get("PE1") or "").strip(),
                (row.get("PE2") or "").strip(),
                (row.get("PE3") or "").strip(),
            ]
            pe_codes = [c for c in pe_codes if c]

            if len(pe_codes) < min_pe_options:
                continue

            for pe_code in pe_codes:
                pe_to_general[pe_code] = general

    return pe_to_general


def rewrite_course_codes(
    rows: Iterable[Dict[str, str]],
    pe_to_general: Dict[str, str],
    *,
    only_when_elective_type_pe: bool,
) -> Tuple[List[Dict[str, str]], MappingStats]:
    out_rows: List[Dict[str, str]] = []
    total = 0
    changed = 0

    for row in rows:
        total += 1
        course_code = (row.get("course_code") or "").strip()
        elective_type = (row.get("elective_type") or "").strip()

        if not course_code:
            out_rows.append(row)
            continue

        if only_when_elective_type_pe and elective_type != "PE":
            out_rows.append(row)
            continue

        general = pe_to_general.get(course_code)
        if general and general != course_code:
            row = dict(row)
            row["course_code"] = general
            changed += 1

        out_rows.append(row)

    return out_rows, MappingStats(total_rows=total, changed_rows=changed, unchanged_rows=total - changed)


def main() -> int:
    parser = argparse.ArgumentParser(description="Replace PE option codes with their general PE code")
    parser.add_argument("--input", required=True, help="Input CSV path (e.g., Year_3_course_data.csv)")
    parser.add_argument("--mapping", required=True, help="PE mapping CSV path (e.g., data/pe_course_map.csv)")
    parser.add_argument("--output", help="Output CSV path (default: derived from input)")
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Overwrite the input CSV (ignored if --output is provided)",
    )
    parser.add_argument(
        "--all-rows",
        action="store_true",
        help="Also rewrite rows where elective_type != 'PE' (default rewrites only elective_type == 'PE')",
    )
    parser.add_argument(
        "--min-pe-options",
        type=int,
        default=2,
        help="Only apply mapping rows that have at least this many PE option codes (default: 2)",
    )

    args = parser.parse_args()

    input_csv = Path(args.input)
    mapping_csv = Path(args.mapping)

    if not input_csv.exists():
        raise FileNotFoundError(f"Input file not found: {input_csv}")

    if args.output:
        output_csv = Path(args.output)
    else:
        output_csv = input_csv.with_name(input_csv.stem + ".with_general_pe" + input_csv.suffix)

    if args.min_pe_options < 1:
        raise ValueError("--min-pe-options must be >= 1")

    pe_to_general = load_pe_mapping(mapping_csv, min_pe_options=args.min_pe_options)

    with input_csv.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("Input CSV has no header row")

        if "course_code" not in reader.fieldnames:
            raise ValueError(f"Input CSV missing 'course_code' column. Found: {reader.fieldnames}")

        rows = list(reader)

    new_rows, stats = rewrite_course_codes(
        rows,
        pe_to_general,
        only_when_elective_type_pe=not args.all_rows,
    )

    # Decide final write target
    write_target = input_csv if (args.in_place and not args.output) else output_csv

    write_target.parent.mkdir(parents=True, exist_ok=True)
    with write_target.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(new_rows[0].keys()) if new_rows else (rows[0].keys() if rows else []))
        writer.writeheader()
        writer.writerows(new_rows)

    print(f"Mapping entries loaded (PE option -> general): {len(pe_to_general)}")
    print(f"Min PE options threshold: {args.min_pe_options}")
    print(f"Rows processed: {stats.total_rows}")
    print(f"Rows changed:   {stats.changed_rows}")
    print(f"Output: {write_target}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
