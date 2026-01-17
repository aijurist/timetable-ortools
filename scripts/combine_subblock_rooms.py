"""
Script to combine subblock rooms (e.g., ANEW101-A, ANEW101-B) back into their parent room (ANEW101).
Reads the CSV files from final/{name}/csv and updates room_number, room_id, and capacity columns.
"""

import csv
from pathlib import Path

# Mapping from subblock room_number to parent room data
# Format: subblock_room_number -> (parent_room_number, parent_room_id, parent_capacity)
# Data sourced from data/block_wise/1st_year.csv
SUBBLOCK_TO_PARENT = {
    # A208/209 subblocks (id=13, capacity=130)
    "A208/209-A": ("A208/209", "13", "130"),  # subblock id=14
    "A208/209-B": ("A208/209", "13", "130"),  # subblock id=229
    # A210/211 subblocks (id=15, capacity=150)
    "A210/211-A": ("A210/211", "15", "150"),  # subblock id=16
    "A210/211-B": ("A210/211", "15", "150"),  # subblock id=230
    # ANEW101 subblocks (id=231, capacity=165)
    "ANEW101-A": ("ANEW101", "231", "165"),   # subblock id=235
    "ANEW101-B": ("ANEW101", "231", "165"),   # subblock id=236
    # ANEW102 subblocks (id=232, capacity=165)
    "ANEW102-A": ("ANEW102", "232", "165"),   # subblock id=233
    "ANEW102-B": ("ANEW102", "232", "165"),   # subblock id=234
    # ANEW103 subblocks (id=3, capacity=140)
    "ANEW103-A": ("ANEW103", "3", "140"),     # subblock id=4
    "ANEW103-B": ("ANEW103", "3", "140"),     # subblock id=5
    # KSL03 subblocks (id=190, capacity=140)
    "KSL03-A": ("KSL03", "190", "140"),       # subblock id=191
    "KSL03-B": ("KSL03", "190", "140"),       # subblock id=192
}


def combine_subblock_rooms(csv_path: Path) -> int:
    """
    Process a CSV file and combine subblock rooms back to their parent room.
    Updates room_number, room_id, and capacity columns.
    Returns the number of rows updated.
    """
    if not csv_path.exists():
        print(f"  File not found: {csv_path}")
        return 0

    # Read all rows
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    if not fieldnames or "room_number" not in fieldnames:
        print(f"  No 'room_number' column found in {csv_path.name}")
        return 0

    # Update room fields for subblock rooms
    updated_count = 0
    for row in rows:
        room = row.get("room_number", "")
        if room in SUBBLOCK_TO_PARENT:
            parent_room, parent_id, parent_capacity = SUBBLOCK_TO_PARENT[room]
            row["room_number"] = parent_room
            if "room_id" in row:
                row["room_id"] = parent_id
            if "capacity" in row:
                row["capacity"] = parent_capacity
            updated_count += 1

    # Write back
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return updated_count


def main():
    base_dir = Path(__file__).parent.parent
    final_dir = base_dir / "output" / "final"

    if not final_dir.exists():
        print(f"Final output directory not found: {final_dir}")
        return

    # Find all subdirectories in final/
    for subdir in final_dir.iterdir():
        if not subdir.is_dir():
            continue

        csv_dir = subdir / "csv"
        if not csv_dir.exists():
            continue

        print(f"\nProcessing: {subdir.name}")

        for csv_file in ["lab_schedule.csv", "theory_schedule.csv"]:
            csv_path = csv_dir / csv_file
            updated = combine_subblock_rooms(csv_path)
            print(f"  {csv_file}: {updated} rows updated")


if __name__ == "__main__":
    main()
    print("\nDone!")
