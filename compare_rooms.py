"""
Script to compare room data between 1st_year.csv and techlongue.csv
Compares rooms by room_number, ignoring the id column
"""

import csv
from pathlib import Path

def load_csv(filepath):
    """Load CSV file and return headers and data indexed by room_number"""
    rooms = {}
    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames
        for row in reader:
            room_number = row.get('room_number', '').strip()
            if room_number:
                rooms[room_number] = row
    return headers, rooms

def compare_rooms():
    """Compare rooms between two CSV files and generate a report"""
    
    base_path = Path('d:/timetable-scheduler/data/block_wise')
    file1 = base_path / '1st_year.csv'
    file2 = base_path / 'techlongue.csv'
    
    headers1, rooms1 = load_csv(file1)
    headers2, rooms2 = load_csv(file2)
    
    report_lines = []
    report_lines.append("=" * 80)
    report_lines.append("ROOM COMPARISON REPORT: 1st_year.csv vs techlongue.csv")
    report_lines.append("=" * 80)
    report_lines.append("")
    
    # Header comparison
    report_lines.append("-" * 80)
    report_lines.append("1. HEADER DIFFERENCES")
    report_lines.append("-" * 80)
    report_lines.append("")
    report_lines.append(f"1st_year.csv headers ({len(headers1)} columns):")
    report_lines.append(f"  {headers1}")
    report_lines.append("")
    report_lines.append(f"techlongue.csv headers ({len(headers2)} columns):")
    report_lines.append(f"  {headers2}")
    report_lines.append("")
    
    # Find header differences
    set1 = set(headers1)
    set2 = set(headers2)
    only_in_1 = set1 - set2
    only_in_2 = set2 - set1
    
    if only_in_1:
        report_lines.append(f"Columns only in 1st_year.csv: {only_in_1}")
    if only_in_2:
        report_lines.append(f"Columns only in techlongue.csv: {only_in_2}")
    
    # Check column order
    if headers1 != headers2:
        report_lines.append("Column ORDER is DIFFERENT between the files")
    report_lines.append("")
    
    # Room presence comparison
    report_lines.append("-" * 80)
    report_lines.append("2. ROOM PRESENCE COMPARISON")
    report_lines.append("-" * 80)
    report_lines.append("")
    
    rooms1_set = set(rooms1.keys())
    rooms2_set = set(rooms2.keys())
    common_rooms = rooms1_set & rooms2_set
    only_in_file1 = rooms1_set - rooms2_set
    only_in_file2 = rooms2_set - rooms1_set
    
    report_lines.append(f"Total rooms in 1st_year.csv: {len(rooms1)}")
    report_lines.append(f"Total rooms in techlongue.csv: {len(rooms2)}")
    report_lines.append(f"Common rooms (by room_number): {len(common_rooms)}")
    report_lines.append("")
    
    if only_in_file1:
        report_lines.append(f"Rooms only in 1st_year.csv ({len(only_in_file1)}):")
        for room in sorted(only_in_file1):
            report_lines.append(f"  - {room}")
        report_lines.append("")
    
    if only_in_file2:
        report_lines.append(f"Rooms only in techlongue.csv ({len(only_in_file2)}):")
        for room in sorted(only_in_file2):
            report_lines.append(f"  - {room}")
        report_lines.append("")
    
    # Field-by-field comparison for common rooms
    report_lines.append("-" * 80)
    report_lines.append("3. FIELD DIFFERENCES FOR COMMON ROOMS (excluding 'id' column)")
    report_lines.append("-" * 80)
    report_lines.append("")
    
    # Get common fields (excluding id)
    common_fields = (set1 & set2) - {'id'}
    
    rooms_with_differences = []
    
    for room_number in sorted(common_rooms):
        row1 = rooms1[room_number]
        row2 = rooms2[room_number]
        
        differences = []
        for field in sorted(common_fields):
            val1 = row1.get(field, '').strip()
            val2 = row2.get(field, '').strip()
            
            if val1 != val2:
                differences.append({
                    'field': field,
                    'val1': val1,
                    'val2': val2
                })
        
        if differences:
            rooms_with_differences.append({
                'room_number': room_number,
                'differences': differences
            })
    
    if rooms_with_differences:
        report_lines.append(f"Found {len(rooms_with_differences)} rooms with field differences:\n")
        
        for room_info in rooms_with_differences:
            report_lines.append(f"Room: {room_info['room_number']}")
            report_lines.append(f"  {'Field':<25} {'1st_year.csv':<35} {'techlongue.csv':<35}")
            report_lines.append(f"  {'-'*25} {'-'*35} {'-'*35}")
            for diff in room_info['differences']:
                report_lines.append(f"  {diff['field']:<25} {diff['val1']:<35} {diff['val2']:<35}")
            report_lines.append("")
    else:
        report_lines.append("No field differences found for common rooms.")
        report_lines.append("")
    
    # Summary of systematic differences
    report_lines.append("-" * 80)
    report_lines.append("4. SUMMARY OF SYSTEMATIC DIFFERENCES")
    report_lines.append("-" * 80)
    report_lines.append("")
    
    # Analyze room_type patterns
    room_types1 = set()
    room_types2 = set()
    for room in rooms1.values():
        room_types1.add(room.get('room_type', ''))
    for room in rooms2.values():
        room_types2.add(room.get('room_type', ''))
    
    report_lines.append("room_type values in 1st_year.csv:")
    for rt in sorted(room_types1):
        report_lines.append(f"  - {rt}")
    report_lines.append("")
    report_lines.append("room_type values in techlongue.csv:")
    for rt in sorted(room_types2):
        report_lines.append(f"  - {rt}")
    report_lines.append("")
    
    # Count differences by field
    field_diff_counts = {}
    for room_info in rooms_with_differences:
        for diff in room_info['differences']:
            field = diff['field']
            field_diff_counts[field] = field_diff_counts.get(field, 0) + 1
    
    if field_diff_counts:
        report_lines.append("Count of differences by field:")
        for field, count in sorted(field_diff_counts.items(), key=lambda x: -x[1]):
            report_lines.append(f"  {field}: {count} rooms differ")
    
    report_lines.append("")
    report_lines.append("=" * 80)
    report_lines.append("END OF REPORT")
    report_lines.append("=" * 80)
    
    # Write report to file
    output_path = base_path / 'room_comparison_report.txt'
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(report_lines))
    
    print(f"Report saved to: {output_path}")
    return output_path

if __name__ == '__main__':
    compare_rooms()
