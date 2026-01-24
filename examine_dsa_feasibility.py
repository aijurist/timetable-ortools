import pandas as pd
import os

def check_dsa():
    file_path = 'd:/timetable-scheduler/data/sem2026/1st year/cse-split.csv'
    if not os.path.exists(file_path):
        print(f"Error: File not found at {file_path}")
        return

    df = pd.read_csv(file_path)
    
    # Filter for DSA (Data Structures)
    # Using course code from previous finding: CS23231
    dsa_rows = df[df['course_code'].str.contains('CS23231', case=False, na=False) | 
                  df['course_name'].str.contains('Data Structures', case=False, na=False)]
    
    print("=== DSA Course Analysis ===")
    print(f"Total Rows Found: {len(dsa_rows)}")
    
    if len(dsa_rows) == 0:
        print("No DSA rows found.")
        return

    # Join names
    dsa_rows['teacher_name'] = dsa_rows['first_name'] + ' ' + dsa_rows['last_name']
    cols = ['id', 'student_count', 'course_code', 'course_type', 'practical_hours', 
            'required_room_type', 'teacher_id', 'teacher_name']
    
    print("\n--- Rows ---")
    print(dsa_rows[cols].to_string())

    print("\n--- Summary ---")
    total_students = dsa_rows['student_count'].sum() # This might be double counting if same group listed multiple times? 
    # Usually each row is a course-teacher mapping. If multiple teachers for same course section, it might duplicate.
    
    # Check for duplicate course_id / group entries if possible.
    # Assuming 'id' is unique record ID.
    
    print(f"Total entries: {len(dsa_rows)}")
    
    # Analyze 'LoT' course type
    print(f"\nCourse Types: {dsa_rows['course_type'].unique()}")
    
    # Analyze Teachers
    teachers = dsa_rows['teacher_name'].unique()
    print(f"\nTeachers involved ({len(teachers)}): {teachers}")
    print(f"\nStudent Counts (Group Sizes): {dsa_rows['student_count'].value_counts().to_dict()}")
    print(f"\nRequired Room Types: {dsa_rows['required_room_type'].value_counts().to_dict()}")
    teacher_counts = dsa_rows['teacher_id'].value_counts()
    print("\nTeacher Assignment Counts (Rows per teacher):")
    print(teacher_counts)

if __name__ == "__main__":
    check_dsa()
