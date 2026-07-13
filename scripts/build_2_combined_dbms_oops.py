"""Build complementary second-year DBMS/OOPS and non-DBMS/OOPS inputs.

The pseudo CSE A/B input replaces the original CSE input so the same source
rows are never included twice.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = PROJECT_ROOT / "data" / "2" / "2"
OUTPUT_DIR = PROJECT_ROOT / "data" / "2_combined"
OUTPUT_CSV = OUTPUT_DIR / "DBMS_OOPS_Combined_course_data.csv"
OTHER_OUTPUT_CSV = OUTPUT_DIR / "Other_Departments_Combined_course_data.csv"
ALL_OUTPUT_CSV = OUTPUT_DIR / "All_Departments_Combined_course_data.csv"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"
COMBINED_CODES = {"CS23332", "CS23333"}
ORIGINAL_CSE = "Computer Science and Engineering_course_data.csv"
PSEUDO_CSE = "Computer Science and Engineering A and B_course_data.csv"


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
	with path.open(newline="", encoding="utf-8-sig") as handle:
		reader = csv.DictReader(handle)
		return list(reader.fieldnames or ()), list(reader)


def validate_unique_ids(label: str, rows: list[dict[str, str]]) -> None:
	ids = [(row.get("id") or "").strip() for row in rows]
	duplicate_ids = sorted({row_id for row_id in ids if row_id and ids.count(row_id) > 1})
	if duplicate_ids:
		raise ValueError(f"Duplicate instance ids in {label} input: {duplicate_ids[:10]}")


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
	with path.open("w", newline="", encoding="utf-8") as handle:
		writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="raise")
		writer.writeheader()
		writer.writerows(rows)


def main() -> None:
	selected: list[tuple[Path, list[dict[str, str]]]] = []
	other: list[tuple[Path, list[dict[str, str]]]] = []
	all_inputs: list[tuple[Path, list[dict[str, str]]]] = []
	fieldnames: list[str] | None = None
	pseudo_cse_exists = (SOURCE_DIR / PSEUDO_CSE).exists()

	for path in sorted(SOURCE_DIR.glob("*_course_data.csv"), key=lambda item: item.name.casefold()):
		if pseudo_cse_exists and path.name == ORIGINAL_CSE:
			continue
		header, rows = read_csv(path)
		if fieldnames is None:
			fieldnames = header
		elif header != fieldnames:
			raise ValueError(f"Header mismatch in {path}")
		all_inputs.append((path, rows))
		if any((row.get("course_code") or "").strip() in COMBINED_CODES for row in rows):
			selected.append((path, rows))
		else:
			other.append((path, rows))

	if not selected or not other or fieldnames is None:
		raise ValueError(f"Could not build complementary second-year inputs from {SOURCE_DIR}")

	all_rows = [row for _path, rows in selected for row in rows]
	other_rows = [row for _path, rows in other for row in rows]
	all_department_rows = [row for _path, rows in all_inputs for row in rows]
	validate_unique_ids("DBMS/OOPS combined", all_rows)
	validate_unique_ids("other-departments combined", other_rows)
	validate_unique_ids("all-departments combined", all_department_rows)

	OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
	write_csv(OUTPUT_CSV, fieldnames, all_rows)
	write_csv(OTHER_OUTPUT_CSV, fieldnames, other_rows)
	write_csv(ALL_OUTPUT_CSV, fieldnames, all_department_rows)

	manifest = {
		"course_codes": sorted(COMBINED_CODES),
		"combined_csv": str(OUTPUT_CSV.relative_to(PROJECT_ROOT)),
		"row_count": len(all_rows),
		"department_count": len({(row.get("student_dept") or "").strip() for row in all_rows}),
		"sources": [
			{
				"file": str(path.relative_to(PROJECT_ROOT)),
				"rows": len(rows),
				"departments": sorted({(row.get("student_dept") or "").strip() for row in rows}),
				"dbms_instances": sum((row.get("course_code") or "").strip() == "CS23332" for row in rows),
				"oops_instances": sum((row.get("course_code") or "").strip() == "CS23333" for row in rows),
			}
			for path, rows in selected
		],
		"other_combined_csv": str(OTHER_OUTPUT_CSV.relative_to(PROJECT_ROOT)),
		"other_row_count": len(other_rows),
		"other_department_count": len(
			{(row.get("student_dept") or "").strip() for row in other_rows}
		),
		"other_sources": [
			{
				"file": str(path.relative_to(PROJECT_ROOT)),
				"rows": len(rows),
				"departments": sorted({(row.get("student_dept") or "").strip() for row in rows}),
			}
			for path, rows in other
		],
		"all_combined_csv": str(ALL_OUTPUT_CSV.relative_to(PROJECT_ROOT)),
		"all_row_count": len(all_department_rows),
		"all_source_file_count": len(all_inputs),
		"all_department_count": len(
			{(row.get("student_dept") or "").strip() for row in all_department_rows}
		),
	}
	MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
	print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
	main()
