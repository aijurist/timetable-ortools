#!/usr/bin/env python3
"""Replace PE-specific course codes with their general PE code.

Example mapping row (from data/pe_course_map.csv):
  BT23PE02,BT23C12,BT23F13,,,,BT,6

This script will replace any occurrence of BT23C12 or BT23F13 in the input
CSV's `course_code` column with BT23PE02. By default it rewrites every mapped
course code, regardless of the row's current elective_type value.

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
from typing import Dict, Iterable, List, Optional, Set, Tuple


DEPT_ABBREVIATIONS = {
    "Aeronautical Engineering": "AERO",
    "Artificial Intelligence & Data Science": "AIDS",
    "Artificial Intelligence & Machine Learning": "AIML",
    "Automobile Engineering": "AUTO",
    "Biomedical Engineering": "BME",
    "Biotechnology": "BT",
    "Chemical Engineering": "CHEM",
    "Civil Engineering": "CIVIL",
    "Computer Science & Business Systems": "CSBS",
    "Computer Science & Design": "CSD",
    "Computer Science & Engineering": "CSE",
    "Computer Science & Engineering-A": "CSEA",
    "Computer Science & Engineering-B": "CSEB",
    "Computer Science & Engineering (Cyber Security)": "CSECS",
    "Electrical & Electronics Engineering": "EEE",
    "Electronics & Communication Engineering": "ECE",
    "Food Technology": "FT",
    "Information Technology": "IT",
    "Mechanical Engineering": "MECH",
    "Mechatronics Engineering": "MCT",
    "Robotics & Automation": "RA",
}

DEPT_NAME_ALIASES = {
    "Computer Science and Business Systems": "Computer Science & Business Systems",
    "Computer Science and Design": "Computer Science & Design",
    "Computer Science and Engineering": "Computer Science & Engineering",
    "Computer Science and Engineering-A": "Computer Science & Engineering-A",
    "Computer Science and Engineering-B": "Computer Science & Engineering-B",
    "Computer Science and Engineering - Cyber Security": "Computer Science & Engineering (Cyber Security)",
    "Computer Science and Engineering Cyber Security": "Computer Science & Engineering (Cyber Security)",
}


@dataclass(frozen=True)
class MappingStats:
    total_rows: int
    changed_rows: int
    unchanged_rows: int


@dataclass(frozen=True)
class PeMapping:
    by_context: Dict[Tuple[str, str, str], str]
    fallback_by_code: Dict[str, str]
    ambiguous_fallback_codes: Set[str]


def normalize_semester(value: object) -> str:
    text = str(value or "").strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text


def department_abbreviation(value: object) -> Optional[str]:
    dept = str(value or "").strip()
    if not dept:
        return None

    upper = dept.upper()
    if upper in set(DEPT_ABBREVIATIONS.values()):
        return upper

    normalized = " ".join(dept.split())
    normalized = DEPT_NAME_ALIASES.get(normalized, normalized)
    return DEPT_ABBREVIATIONS.get(normalized)


def row_department_abbreviation(row: Dict[str, str]) -> Optional[str]:
    for column in ("student_dept", "dept", "department", "student_department", "DEPT"):
        abbrev = department_abbreviation(row.get(column))
        if abbrev:
            return abbrev
    return None


def load_pe_mapping(mapping_csv: Path, *, min_pe_options: int) -> PeMapping:
    """Return PE option -> GENERAL CODE mappings.

    Only includes GENERAL CODE rows that have at least `min_pe_options` non-empty
    PE option codes across PE1..PEn.
    """
    if not mapping_csv.exists():
        raise FileNotFoundError(f"Mapping file not found: {mapping_csv}")

    by_context: Dict[Tuple[str, str, str], str] = {}
    fallback_candidates: Dict[str, Set[str]] = {}

    with mapping_csv.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        required_cols = {"GENERAL CODE"}
        missing = required_cols - set(reader.fieldnames or [])
        if missing:
            raise ValueError(
                f"Mapping CSV missing columns {sorted(missing)}. "
                f"Found: {reader.fieldnames}"
            )
        pe_columns = _pe_option_columns(reader.fieldnames or [])
        if not pe_columns:
            raise ValueError(
                f"Mapping CSV missing PE option columns (expected PE1..PEn). "
                f"Found: {reader.fieldnames}"
            )

        for row in reader:
            general = (row.get("GENERAL CODE") or "").strip()
            if not general:
                continue

            pe_codes = [
                (row.get(column) or "").strip()
                for column in pe_columns
            ]
            pe_codes = [c for c in pe_codes if c]

            if len(pe_codes) < min_pe_options:
                continue

            dept = department_abbreviation(row.get("DEPT"))
            sem = normalize_semester(row.get("SEM"))
            for pe_code in pe_codes:
                if dept and sem:
                    by_context[(dept, sem, pe_code)] = general
                fallback_candidates.setdefault(pe_code, set()).add(general)

    fallback_by_code = {
        pe_code: next(iter(general_codes))
        for pe_code, general_codes in fallback_candidates.items()
        if len(general_codes) == 1
    }
    ambiguous_fallback_codes = {
        pe_code
        for pe_code, general_codes in fallback_candidates.items()
        if len(general_codes) > 1
    }

    return PeMapping(
        by_context=by_context,
        fallback_by_code=fallback_by_code,
        ambiguous_fallback_codes=ambiguous_fallback_codes,
    )


def _pe_option_columns(fieldnames: Iterable[str]) -> List[str]:
    columns = []
    for fieldname in fieldnames:
        name = str(fieldname or "").strip()
        if not name.upper().startswith("PE"):
            continue
        suffix = name[2:]
        if not suffix.isdigit():
            continue
        columns.append((int(suffix), name))
    return [name for _index, name in sorted(columns)]


def rewrite_course_codes(
    rows: Iterable[Dict[str, str]],
    pe_mapping: PeMapping,
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

        dept = row_department_abbreviation(row)
        sem = normalize_semester(row.get("semester") or row.get("SEM"))
        general = None
        if dept and sem:
            general = pe_mapping.by_context.get((dept, sem, course_code))

        if general is None and course_code not in pe_mapping.ambiguous_fallback_codes:
            general = pe_mapping.fallback_by_code.get(course_code)

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
    scope_group = parser.add_mutually_exclusive_group()
    scope_group.add_argument(
        "--all-rows",
        action="store_true",
        help="Rewrite all rows with mapped PE option codes. This is the default and is kept for compatibility.",
    )
    scope_group.add_argument(
        "--only-elective-type-pe",
        action="store_true",
        help="Only rewrite rows where elective_type == 'PE' (old restrictive behavior).",
    )
    parser.add_argument(
        "--min-pe-options",
        type=int,
        default=1,
        help="Only apply mapping rows that have at least this many PE option codes (default: 1)",
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

    pe_mapping = load_pe_mapping(mapping_csv, min_pe_options=args.min_pe_options)

    with input_csv.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("Input CSV has no header row")

        if "course_code" not in reader.fieldnames:
            raise ValueError(f"Input CSV missing 'course_code' column. Found: {reader.fieldnames}")

        rows = list(reader)

    new_rows, stats = rewrite_course_codes(
        rows,
        pe_mapping,
        only_when_elective_type_pe=args.only_elective_type_pe,
    )

    # Decide final write target
    write_target = input_csv if (args.in_place and not args.output) else output_csv

    write_target.parent.mkdir(parents=True, exist_ok=True)
    with write_target.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(new_rows[0].keys()) if new_rows else (rows[0].keys() if rows else []))
        writer.writeheader()
        writer.writerows(new_rows)

    print(f"Context mapping entries loaded (DEPT+SEM+PE option -> general): {len(pe_mapping.by_context)}")
    print(f"Unambiguous fallback entries loaded (PE option -> general): {len(pe_mapping.fallback_by_code)}")
    print(f"Ambiguous fallback PE option codes skipped without dept/semester context: {len(pe_mapping.ambiguous_fallback_codes)}")
    print(f"Min PE options threshold: {args.min_pe_options}")
    print(
        "Rewrite scope: "
        + ("only elective_type == PE" if args.only_elective_type_pe else "all mapped course_code rows")
    )
    print(f"Rows processed: {stats.total_rows}")
    print(f"Rows changed:   {stats.changed_rows}")
    print(f"Output: {write_target}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
