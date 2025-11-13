#!/usr/bin/env python3
"""
Script to remove lab data entries that are present in the batch split file 
from the combined schedule lab file.

The script identifies matching entries based on course_instance_id and removes them
from the combined schedule file.
"""

import pandas as pd
import sys
from pathlib import Path

def remove_batch_entries(batch_file_path, combined_file_path, output_file_path=None):
    """
    Remove entries from combined_file that are present in batch_file
    
    Args:
        batch_file_path (str): Path to the batch split CSV file
        combined_file_path (str): Path to the combined schedule CSV file  
        output_file_path (str, optional): Path for output file. If None, creates a new file
    
    Returns:
        tuple: (number_of_entries_removed, output_file_path)
    """
    
    try:
        # Read the CSV files
        print(f"Reading batch split file: {batch_file_path}")
        batch_df = pd.read_csv(batch_file_path)
        
        print(f"Reading combined schedule file: {combined_file_path}")
        combined_df = pd.read_csv(combined_file_path)
        
        # Get initial counts
        initial_combined_count = len(combined_df)
        initial_batch_count = len(batch_df)
        
        print(f"\nInitial counts:")
        print(f"  Batch split file: {initial_batch_count} entries")
        print(f"  Combined schedule file: {initial_combined_count} entries")
        
        # Get course_instance_ids to remove from batch file
        batch_course_ids = set(batch_df['course_instance_id'].unique())
        print(f"\nUnique course_instance_ids in batch file: {len(batch_course_ids)}")
        
        # Check how many entries in combined file match these IDs
        matching_entries = combined_df[combined_df['course_instance_id'].isin(batch_course_ids)]
        num_matching = len(matching_entries)
        
        print(f"Matching entries found in combined file: {num_matching}")
        
        if num_matching > 0:
            print("\nMatching course_instance_ids:")
            for course_id in sorted(batch_course_ids):
                count = len(combined_df[combined_df['course_instance_id'] == course_id])
                if count > 0:
                    print(f"  {course_id}: {count} entries")
        
        # Remove matching entries
        filtered_df = combined_df[~combined_df['course_instance_id'].isin(batch_course_ids)]
        final_count = len(filtered_df)
        entries_removed = initial_combined_count - final_count
        
        print(f"\nEntries removed: {entries_removed}")
        print(f"Remaining entries: {final_count}")
        
        # Generate output filename if not provided
        if output_file_path is None:
            combined_path = Path(combined_file_path)
            output_file_path = combined_path.parent / f"{combined_path.stem}_filtered{combined_path.suffix}"
        
        # Save the filtered data
        print(f"\nSaving filtered data to: {output_file_path}")
        filtered_df.to_csv(output_file_path, index=False)
        
        print(f"✅ Successfully created filtered file with {final_count} entries")
        
        return entries_removed, str(output_file_path)
        
    except FileNotFoundError as e:
        print(f"❌ Error: File not found - {e}")
        return None, None
    except pd.errors.EmptyDataError:
        print("❌ Error: One of the CSV files is empty")
        return None, None
    except KeyError as e:
        print(f"❌ Error: Required column not found - {e}")
        print("Make sure both files have 'course_instance_id' column")
        return None, None
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return None, None

def main():
    """Main function to execute the script"""
    
    # File paths
    batch_file = "data/santhosh - Batch 1_2 split - Sheet1.csv"
    combined_file = "data/santhosh - combined_schedule_lab.csv"
    
    print("🔄 Lab Data Entry Removal Script")
    print("=" * 50)
    
    # Check if files exist
    if not Path(batch_file).exists():
        print(f"❌ Error: Batch file not found: {batch_file}")
        return
    
    if not Path(combined_file).exists():
        print(f"❌ Error: Combined file not found: {combined_file}")
        return
    
    # Remove batch entries
    entries_removed, output_file = remove_batch_entries(batch_file, combined_file)
    
    if entries_removed is not None:
        print("\n" + "=" * 50)
        print(f"✅ Process completed successfully!")
        print(f"📊 Summary:")
        print(f"   • Entries removed: {entries_removed}")
        print(f"   • Output file: {output_file}")
    else:
        print("\n❌ Process failed. Please check the error messages above.")

if __name__ == "__main__":
    main() 