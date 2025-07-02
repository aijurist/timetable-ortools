# Lab Data Entry Removal Process

## Overview
This document describes the process of removing specific lab data entries from the combined schedule file based on entries present in a batch split file.

## Files Involved

### Input Files:
1. **`data/santhosh - Batch 1_2 split - Sheet1.csv`** (36 entries)
   - Contains lab data entries that need to be removed from the combined schedule
   - Used as the reference for which entries to remove

2. **`data/santhosh - combined_schedule_lab.csv`** (1,000 entries)
   - Main combined schedule file containing all lab entries
   - Target file from which entries will be removed

### Output Files:
1. **`data/santhosh - combined_schedule_lab_filtered.csv`** (964 entries)
   - Filtered version of the combined schedule with specified entries removed
   - Contains 36 fewer entries than the original

## Process Details

### Method
- Entries are matched and removed based on the `course_instance_id` column
- All entries in the combined schedule that have the same `course_instance_id` as any entry in the batch split file are removed

### Entries Removed
- **Total removed:** 36 entries
- **Unique course_instance_ids:** 12
- **Affected course codes:** 9 different courses

### Breakdown by course_instance_id:
```
91:   3 entries (CS23531 - Web Programming)
416:  3 entries (CS23422 - Python Programming for Machine Learning)  
425:  3 entries (CS23336 - Introduction to Python Programming)
476:  3 entries (MT19713 - Mechatronics Problem Solving using AI, ML & DL)
844:  3 entries (CS23532 - Computer Networks)
962:  3 entries (FT19714 - Problem solving using AI and ML for Food Technologist)
1291: 3 entries (BT19712 - Bioinformatics Laboratory)
1309: 3 entries (BT23522 - Bioinformatics Laboratory)
1546: 3 entries (CS23422 - Python Programming for Machine Learning)
1933: 3 entries (CS23531 - Web Programming)
2022: 3 entries (CS23332 - Database Management Systems)
2023: 3 entries (CS23332 - Database Management Systems)
```

### Affected Course Codes:
- CS23422: 6 entries
- CS23531: 6 entries  
- CS23332: 6 entries
- BT19712: 3 entries
- BT23522: 3 entries
- FT19714: 3 entries
- CS23532: 3 entries
- CS23336: 3 entries
- MT19713: 3 entries

## Scripts Used

### 1. `remove_batch_entries.py`
Main script that performs the removal operation:
- Reads both input CSV files
- Identifies matching entries based on `course_instance_id`
- Removes matching entries from the combined schedule
- Saves the filtered result to a new file
- Provides detailed logging and progress information

**Usage:**
```bash
python remove_batch_entries.py
```

### 2. `verify_removal.py`
Verification script that confirms the removal was successful:
- Compares original and filtered files
- Shows detailed statistics about removed entries
- Provides examples of removed entries
- Verifies no unwanted entries remain

**Usage:**
```bash
python verify_removal.py
```

## Verification Results

✅ **Process completed successfully!**
- All 36 specified entries were removed
- No duplicate or remaining unwanted entries
- Filtered file contains exactly 964 entries (1000 - 36)
- File integrity maintained (all columns and structure preserved)

## Usage Notes

1. **File Paths:** Scripts are configured to work with the specific file names in the `data/` directory
2. **Backup:** Original files are preserved; new filtered file is created with `_filtered` suffix
3. **Column Dependency:** Process depends on the `course_instance_id` column being present in both files
4. **Error Handling:** Scripts include comprehensive error handling for missing files, empty data, and missing columns

## Result Summary

- **Original combined file:** 1,000 entries
- **Filtered combined file:** 964 entries  
- **Entries removed:** 36 entries
- **Verification status:** ✅ Passed all checks 