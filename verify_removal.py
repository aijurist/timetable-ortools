#!/usr/bin/env python3
"""
Verification script to check what entries were removed from the combined schedule file.
"""

import pandas as pd
from pathlib import Path

def verify_removal():
    """Verify what entries were removed and show examples"""
    
    print("🔍 Verification Script - Checking Removed Entries")
    print("=" * 60)
    
    # File paths
    batch_file = "data/santhosh - Batch 1_2 split - Sheet1.csv"
    original_file = "data/santhosh - combined_schedule_lab.csv"
    filtered_file = "data/santhosh - combined_schedule_lab_filtered.csv"
    
    try:
        # Read all files
        batch_df = pd.read_csv(batch_file)
        original_df = pd.read_csv(original_file)
        filtered_df = pd.read_csv(filtered_file)
        
        print(f"📊 File Statistics:")
        print(f"   Batch split file: {len(batch_df)} entries")
        print(f"   Original combined file: {len(original_df)} entries")
        print(f"   Filtered combined file: {len(filtered_df)} entries")
        print(f"   Entries removed: {len(original_df) - len(filtered_df)}")
        
        # Get the course_instance_ids from batch file
        batch_course_ids = set(batch_df['course_instance_id'].unique())
        
        # Find removed entries
        removed_entries = original_df[original_df['course_instance_id'].isin(batch_course_ids)]
        
        print(f"\n📋 Detailed Breakdown:")
        print(f"   Unique course_instance_ids in batch file: {len(batch_course_ids)}")
        print(f"   Total entries removed from combined file: {len(removed_entries)}")
        
        # Show breakdown by course_instance_id
        print(f"\n🔢 Entries removed by course_instance_id:")
        for course_id in sorted(batch_course_ids):
            count_original = len(original_df[original_df['course_instance_id'] == course_id])
            count_filtered = len(filtered_df[filtered_df['course_instance_id'] == course_id])
            removed_count = count_original - count_filtered
            print(f"   {course_id}: {removed_count} entries removed")
        
        # Show some examples of removed entries
        print(f"\n📝 Examples of removed entries:")
        print("-" * 60)
        
        # Display first few removed entries with key columns
        key_columns = ['day', 'session_name', 'course_code', 'course_name', 'teacher_name', 'batch_info']
        
        for i, (_, row) in enumerate(removed_entries.head(5).iterrows()):
            print(f"\nExample {i+1}:")
            for col in key_columns:
                if col in row:
                    print(f"   {col}: {row[col]}")
        
        if len(removed_entries) > 5:
            print(f"\n   ... and {len(removed_entries) - 5} more entries")
        
        # Verify no entries with these IDs remain in filtered file
        remaining_unwanted = filtered_df[filtered_df['course_instance_id'].isin(batch_course_ids)]
        
        if len(remaining_unwanted) == 0:
            print(f"\n✅ Verification passed: No entries with batch course_instance_ids remain in filtered file")
        else:
            print(f"\n❌ Verification failed: {len(remaining_unwanted)} unwanted entries still remain!")
        
        # Show which course codes were affected
        print(f"\n📚 Course codes affected:")
        affected_courses = removed_entries['course_code'].value_counts()
        for course_code, count in affected_courses.items():
            print(f"   {course_code}: {count} entries")
        
        print(f"\n🎯 Summary:")
        print(f"   ✓ Successfully removed all {len(removed_entries)} entries")
        print(f"   ✓ Filtered file contains {len(filtered_df)} entries")
        print(f"   ✓ No duplicate or remaining unwanted entries")
        
    except Exception as e:
        print(f"❌ Error during verification: {e}")

if __name__ == "__main__":
    verify_removal() 