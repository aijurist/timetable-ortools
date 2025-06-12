#!/usr/bin/env python
import os
import csv
import sqlite3
import sys
from datetime import datetime

def ensure_directory_exists(directory):
    """Create directory if it doesn't exist"""
    if not os.path.exists(directory):
        os.makedirs(directory)

def get_db_connection(db_path):
    """Connect to SQLite database"""
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row  # This enables column access by name
        return conn
    except sqlite3.Error as e:
        print(f"Error connecting to database: {e}")
        sys.exit(1)

def get_student_departments(conn):
    """Get all departments that have students assigned to courses."""
    query = """
    SELECT DISTINCT
        c.for_dept_id_id as id,
        dsd.dept_name as dept_name
    FROM
        course_course c
    JOIN
        department_department dsd ON c.for_dept_id_id = dsd.id
    ORDER BY
        dsd.dept_name
    """
    try:
        cursor = conn.cursor()
        cursor.execute(query)
        departments = cursor.fetchall()
        return departments
    except sqlite3.Error as e:
        print(f"Error fetching student departments: {e}")
        return []

def extract_course_data_by_dept(conn, dept_id, dept_name):
    """Extract course data for a specific department"""
    query = """
    SELECT 
        tc.id,
        tc.student_count,
        tc.academic_year,
        tc.semester,
        tc.requires_special_scheduling,
        CASE WHEN tc.asssist_teacher_id IS NOT NULL THEN 1 ELSE 0 END as is_assistant,
        
        -- Main teacher details
        t.id as teacher_id,
        t.staff_code,
        COALESCE(u.first_name, 'Unknown') as first_name,
        COALESCE(u.last_name, 'Teacher') as last_name,
        COALESCE(u.email, '') as teacher_email,
        
        -- Assistant teacher details
        assist_t.id as assist_teacher_id,
        assist_t.staff_code as assist_staff_code,
        COALESCE(assist_u.first_name, '') as assist_first_name,
        COALESCE(assist_u.last_name, '') as assist_last_name,
        COALESCE(assist_u.email, '') as assist_teacher_email,
        
        c.id as course_id,
        cm.course_id as course_code,
        cm.course_name,
        cm.course_type,
        cm.lecture_hours,
        cm.practical_hours,
        cm.tutorial_hours,
        cm.credits,
        dcd.dept_name as course_dept,
        dtd.dept_name as teaching_dept,
        c.teaching_dept_id_id,
        dsd.dept_name as student_dept,
        cmrp.preferred_for,
        cmrp.lab_type,
        cmrp.lab_description,
        COALESCE(r.room_type, 'standard') as required_room_type,
        COALESCE(cmrp.tech_level_preference, 'standard') as specific_room_type,
        COALESCE(r.room_number, '') as room_number,
        COALESCE(r.block, '') as block,
        COALESCE(r.description, '') as room_description,
        CASE 
            WHEN cm.practical_hours > 0 AND r.room_type = 'Core-Lab' THEN 'Core-Lab'
            WHEN cm.practical_hours > 0 AND r.room_type = 'Computer-Lab' THEN 'Computer-Lab'
            WHEN cm.practical_hours > 0 AND r.room_type IS NULL THEN 'Lab-Required-No-Assignment'
            WHEN cm.practical_hours > 0 THEN 'Lab-Required-Other'
            ELSE 'No-Lab-Required'
        END as lab_assignment_status
    FROM 
        teacherCourse_teachercourse tc
    JOIN 
        teacher_teacher t ON tc.teacher_id_id = t.id
    LEFT JOIN 
        authentication_user u ON t.teacher_id_id = u.email
    LEFT JOIN
        teacher_teacher assist_t ON tc.asssist_teacher_id = assist_t.id
    LEFT JOIN
        authentication_user assist_u ON assist_t.teacher_id_id = assist_u.email
    JOIN 
        course_course c ON tc.course_id_id = c.id
    JOIN 
        courseMaster_coursemaster cm ON c.course_id_id = cm.id
    JOIN 
        department_department dcd ON cm.course_dept_id_id = dcd.id
    JOIN 
        department_department dtd ON c.teaching_dept_id_id = dtd.id
    JOIN 
        department_department dsd ON c.for_dept_id_id = dsd.id
    LEFT JOIN 
        courseMaster_coursemasterroompreference cmrp ON cm.id = cmrp.course_master_id_id
    LEFT JOIN 
        rooms_room r ON cmrp.room_id_id = r.id
    WHERE 
        c.for_dept_id_id = ?
        AND tc.academic_year > 1
        AND tc.semester > 1
    """
    
    try:
        cursor = conn.cursor()
        cursor.execute(query, (dept_id,))
        columns = [description[0] for description in cursor.description]
        data = cursor.fetchall()
        
        # Convert Row objects to lists
        data_lists = []
        for row in data:
            data_lists.append([row[column] for column in columns])
            
        return columns, data_lists
    except sqlite3.Error as e:
        print(f"Error executing query for department {dept_name}: {e}")
        return [], []

def save_to_csv(columns, data, filename):
    """Save data to CSV file"""
    with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(columns)
        for row in data:
            # Convert any None values to empty strings
            processed_row = ['' if value is None else value for value in row]
            writer.writerow(processed_row)

def main():
    # Database path - change this to the actual path of your SQLite database
    db_path = input("Enter the path to your SQLite database file: ")
    
    if not os.path.exists(db_path):
        print(f"Database file not found: {db_path}")
        sys.exit(1)
    
    # Create data directory if it doesn't exist
    data_dir = 'data/department_data'
    ensure_directory_exists(data_dir)
    
    # Connect to the database
    conn = get_db_connection(db_path)
    
    try:
        # Get all departments that have students assigned to courses
        departments = get_student_departments(conn)
        
        print(f"Found {len(departments)} departments with assigned students")
        print("NOTE: Filtering out 1st year (academic_year = 1) and 1st semester (semester = 1) data")
        
        # Extract data for each department
        for dept in departments:
            dept_id = dept['id']
            dept_name = dept['dept_name']
            print(f"Processing department: {dept_name} (ID: {dept_id})")
            
            # Replace any characters that would be invalid in filenames
            safe_dept_name = ''.join(c if c.isalnum() else '_' for c in dept_name)
            filename = os.path.join(data_dir, f"{safe_dept_name}_courses.csv")
            
            try:
                columns, data = extract_course_data_by_dept(conn, dept_id, dept_name)
                if columns and data:
                    save_to_csv(columns, data, filename)
                    print(f"Successfully saved {len(data)} records to {filename}")
                else:
                    print(f"No data found for department {dept_name}")
            except Exception as e:
                print(f"Error processing department {dept_name}: {e}")
        
        print("Data extraction complete!")
    
    finally:
        # Close the database connection
        conn.close()

if __name__ == "__main__":
    main() 