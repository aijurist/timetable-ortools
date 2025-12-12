import argparse
import csv
import re
from collections import defaultdict
from pathlib import Path


def slugify(name: str) -> str:
    # Produce a safe, lowercase filename token from department name.
    token = name.strip().lower()
    token = re.sub(r"&", "and", token)
    token = re.sub(r"[^a-z0-9]+", "_", token)
    token = re.sub(r"_+", "_", token).strip("_")
    return token or "unknown"


def group_by_department(input_csv: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    with input_csv.open("r", encoding="utf-8", newline="") as infile:
        reader = csv.DictReader(infile)
        rows_by_dept = defaultdict(list)
        for row in reader:
            dept = row.get("student_dept") or "UNKNOWN"
            rows_by_dept[dept].append(row)
        fieldnames = reader.fieldnames or []

    for dept, rows in rows_by_dept.items():
        slug = slugify(dept)
        outfile = output_dir / f"{slug}.csv"
        with outfile.open("w", encoding="utf-8", newline="") as out:
            writer = csv.DictWriter(out, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)



def main() -> None:
    parser = argparse.ArgumentParser(description="Split Year 3 course data by student_dept.")
    parser.add_argument(
        "input_csv",
        type=Path,
        default=Path("data/sem2026/year_wise/Year_3_course_data.csv"),
        nargs="?",
        help="Path to Year_3_course_data.csv",
    )
    parser.add_argument(
        "output_dir",
        type=Path,
        default=Path("data/sem2026/year_wise/3rd_year"),
        nargs="?",
        help="Directory to write per-department CSVs",
    )
    args = parser.parse_args()

    if not args.input_csv.exists():
        parser.error(f"Input CSV not found: {args.input_csv}")

    group_by_department(args.input_csv, args.output_dir)


if __name__ == "__main__":
    main()
