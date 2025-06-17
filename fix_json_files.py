#!/usr/bin/env python3
"""
Fix JSON files by replacing NaN values with null

This script fixes the existing JSON files that contain invalid NaN values
by replacing them with valid JSON null values.
"""

import os
import re
import json
import pandas as pd
import numpy as np
from pathlib import Path

def fix_json_file(file_path):
    """Fix a JSON file by replacing NaN values with null."""
    print(f"Fixing {file_path}...")
    
    if not os.path.exists(file_path):
        print(f"  File not found: {file_path}")
        return False
    
    try:
        # Read the file as text first
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Replace various forms of NaN with null
        content = re.sub(r'\bNaN\b', 'null', content)
        content = re.sub(r'\bnan\b', 'null', content)
        content = re.sub(r'\bInfinity\b', 'null', content)
        content = re.sub(r'\b-Infinity\b', 'null', content)
        content = re.sub(r'\binf\b', 'null', content)
        content = re.sub(r'\b-inf\b', 'null', content)
        
        # Try to parse as JSON to validate
        try:
            data = json.loads(content)
            print(f"  Successfully parsed JSON with {len(data)} items")
        except json.JSONDecodeError as e:
            print(f"  Still invalid JSON after basic fixes: {e}")
            # Try more aggressive cleaning
            content = re.sub(r':\s*NaN\s*,', ': null,', content)
            content = re.sub(r':\s*NaN\s*}', ': null}', content)
            content = re.sub(r':\s*nan\s*,', ': null,', content)
            content = re.sub(r':\s*nan\s*}', ': null}', content)
            
            try:
                data = json.loads(content)
                print(f"  Successfully parsed JSON after aggressive cleaning with {len(data)} items")
            except json.JSONDecodeError as e2:
                print(f"  Failed to fix JSON: {e2}")
                return False
        
        # Write the fixed content back
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        print(f"  ✅ Fixed {file_path}")
        return True
        
    except Exception as e:
        print(f"  ❌ Error fixing {file_path}: {e}")
        return False

def clean_data_recursively(data):
    """Recursively clean data by replacing NaN/None values."""
    if isinstance(data, list):
        return [clean_data_recursively(item) for item in data]
    elif isinstance(data, dict):
        cleaned = {}
        for key, value in data.items():
            cleaned[key] = clean_data_recursively(value)
        return cleaned
    elif pd.isna(data):
        return None
    elif isinstance(data, float) and (np.isnan(data) or np.isinf(data)):
        return None
    elif data != data:  # NaN check (NaN != NaN is True)
        return None
    else:
        return data

def fix_json_with_pandas(file_path):
    """Alternative method using pandas to fix JSON files."""
    print(f"Trying pandas method for {file_path}...")
    
    try:
        # Read CSV version if it exists
        csv_path = file_path.replace('.json', '.csv')
        if os.path.exists(csv_path):
            print(f"  Found CSV file: {csv_path}")
            df = pd.read_csv(csv_path)
            
            # Clean the dataframe
            df = df.fillna('')  # Replace NaN with empty string
            
            # Convert back to JSON
            data = df.to_dict('records')
            
            # Clean the data recursively
            clean_data = clean_data_recursively(data)
            
            # Save the fixed JSON
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(clean_data, f, indent=2, ensure_ascii=False)
            
            print(f"  ✅ Fixed {file_path} using CSV method")
            return True
        else:
            print(f"  No CSV file found at {csv_path}")
            return False
            
    except Exception as e:
        print(f"  ❌ Error with pandas method: {e}")
        return False

def main():
    """Main function to fix JSON files."""
    print("JSON File Fixer for University Timetable Schedule")
    print("=" * 60)
    
    # Find the output directory
    output_dir = "output/combined_schedule_20250617_122057"
    
    if not os.path.exists(output_dir):
        print(f"❌ Output directory not found: {output_dir}")
        return
    
    # Files to fix
    json_files = [
        os.path.join(output_dir, 'combined_lab_schedule.json'),
        os.path.join(output_dir, 'combined_theory_schedule.json')
    ]
    
    fixed_count = 0
    
    for json_file in json_files:
        print(f"\nProcessing: {json_file}")
        
        # Try the direct text replacement method first
        if fix_json_file(json_file):
            fixed_count += 1
        else:
            # Try the pandas method as backup
            if fix_json_with_pandas(json_file):
                fixed_count += 1
            else:
                print(f"  ❌ Failed to fix {json_file}")
    
    print(f"\n" + "=" * 60)
    print(f"Summary: Fixed {fixed_count} out of {len(json_files)} JSON files")
    
    if fixed_count == len(json_files):
        print("✅ All JSON files have been fixed!")
        print("You can now open the website again.")
    else:
        print("⚠️  Some files could not be fixed automatically.")
        print("You may need to regenerate the schedule data.")

if __name__ == "__main__":
    main() 