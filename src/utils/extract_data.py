import sqlite3
import pandas as pd
import os
import sys

# Database path
DB_PATH = r"C:\Users\ShanthoshS\OneDrive\Desktop\timetable_scheduler\data\data-dump-final.sqlite3"

def get_db_path():
    """Determine database path, checking if file exists"""
    abs_path = os.path.abspath(DB_PATH)
    
    if not os.path.exists(abs_path):
        print(f"ERROR: Database file not found at: {abs_path}")
        print(f"Current working directory: {os.getcwd()}")
        return None
    
    print(f"Using database at: {abs_path}")
    return abs_path

def connect_db():
    """Establish connection to the SQLite database"""
    db_path = get_db_path()
    if not db_path:
        return None
        
    try:
        conn = sqlite3.connect(db_path)
        return conn
    except sqlite3.Error as e:
        print(f"Database connection error: {e}")
        return None

def close_connection(conn):
    """Close the database connection"""
    if conn:
        conn.close()

def get_semester5_teacher_course_data():
    """Get teacher course data for semester 5 only"""
    conn = connect_db()
    if not conn:
        return None
    
    try:
        # Query specifically for semester 5 courses
        query = """
        SELECT 
            tc.id, 
            tc.student_count, 
            tc.academic_year, 
            tc.semester,
            tc.requires_special_scheduling,
            tc.is_assistant,
            
            -- Course information
            cm.course_id AS course_code, 
            cm.course_name,
            cm.credits,
            cm.regulation,
            cm.course_type,
            cm.degree_type,
            cm.is_zero_credit_course,
            
            cc.course_year,
            cc.course_semester,
            cc.elective_type,
            cc.lab_type,
            cc.teaching_status,
            
            -- Teacher information
            au.first_name, 
            au.last_name,
            au.email,
            t.staff_code,
            t.teacher_role,
            t.teacher_specialisation
            
        FROM teacherCourse_teachercourse tc
        JOIN course_course cc ON tc.course_id_id = cc.id
        JOIN courseMaster_coursemaster cm ON cc.course_id_id = cm.id
        JOIN teacher_teacher t ON tc.teacher_id_id = t.id
        JOIN authentication_user au ON t.teacher_id_id = au.email
        WHERE cc.course_semester = 5
        """
        df = pd.read_sql_query(query, conn)
        return df
    except sqlite3.Error as e:
        print(f"Error fetching semester 5 teacher course data: {e}")
        return None
    finally:
        close_connection(conn)

if __name__ == "__main__":
    # Get semester 5 data
    print("\n=== SEMESTER 5 TEACHER COURSE DATA ===")
    semester5_df = get_semester5_teacher_course_data()
    
    if semester5_df is not None:
        print(f"Total semester 5 records: {len(semester5_df)}")
        
        # Quick summary of the data
        print("\nDepartment distribution (based on course code):")
        dept_counts = semester5_df['course_code'].str[:2].value_counts()
        for dept, count in dept_counts.items():
            print(f"  - {dept}: {count} courses")
        
        # Course distribution by type
        print("\nCourse type distribution:")
        type_counts = semester5_df['course_type'].value_counts()
        for course_type, count in type_counts.items():
            print(f"  - {course_type}: {count} courses")
        
        # Teacher distribution
        print("\nTop 5 teachers by number of semester 5 courses:")
        teacher_counts = semester5_df.groupby(['first_name', 'last_name']).size().sort_values(ascending=False)
        for (first, last), count in teacher_counts.head(5).items():
            print(f"  - {first} {last}: {count} courses")
        
        # Save to CSV
        output_file = "semester5_teacher_course_data.csv"
        semester5_df.to_csv(output_file, index=False)
        print(f"\nSemester 5 data saved to {output_file}")
        
        print("\nColumn names in the CSV file:")
        for col in semester5_df.columns:
            print(f"  - {col}")
        
        # Print first few rows to verify data
        print("\nSample data (first 5 rows):")
        sample_cols = ['first_name', 'last_name', 'course_code', 'course_name', 'student_count']
        print(semester5_df[sample_cols].head(5))
    else:
        print("Could not retrieve semester 5 teacher course data")