import pandas as pd
import sys

def remove_duplicates_from_csv(input_file, output_file):
    """
    Remove duplicate entries from CSV based on course_code and course_name
    Keep the first occurrence of each unique combination
    """
    try:
        # Read the CSV file
        df = pd.read_csv(input_file)
        
        # Print initial statistics
        print(f"Original file has {len(df)} rows")
        
        # Remove rows where both course_code and course_name are empty/null
        df_cleaned = df.dropna(subset=['course_code', 'course_name'], how='all')
        print(f"After removing completely empty rows: {len(df_cleaned)} rows")
        
        # Remove duplicates based on course_code and course_name
        # Keep the first occurrence
        df_no_duplicates = df_cleaned.drop_duplicates(subset=['course_code', 'course_name'], keep='first')
        
        print(f"After removing duplicates: {len(df_no_duplicates)} rows")
        print(f"Removed {len(df_cleaned) - len(df_no_duplicates)} duplicate entries")
        
        # Save the cleaned data
        df_no_duplicates.to_csv(output_file, index=False)
        print(f"Cleaned data saved to: {output_file}")
        
        # Show some statistics about what was removed
        duplicates = df_cleaned[df_cleaned.duplicated(subset=['course_code', 'course_name'], keep=False)]
        if len(duplicates) > 0:
            print("\nDuplicate entries found for these course codes:")
            duplicate_summary = duplicates.groupby(['course_code', 'course_name']).size().reset_index(name='count')
            for _, row in duplicate_summary.iterrows():
                print(f"  {row['course_code']} - {row['course_name']}: {row['count']} occurrences")
        
        return True
        
    except Exception as e:
        print(f"Error processing file: {str(e)}")
        return False

if __name__ == "__main__":
    input_file = "timetable_scheduler/data/core_mapping.csv"
    output_file = "timetable_scheduler/data/core_mapping_cleaned.csv"
    
    success = remove_duplicates_from_csv(input_file, output_file)
    if success:
        print("✅ Successfully removed duplicates!")
    else:
        print("❌ Failed to remove duplicates!") 