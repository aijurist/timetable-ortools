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
        CASE WHEN tc.asssist_teacher_id IS NOT NULL THEN 1 ELSE 0 END as is_assistant,

        -- Main teacher details
        t.id as teacher_id,
        t.staff_code,
        t.teacher_role as teacher_role,
        COALESCE(u.first_name, 'Unknown') as first_name,
        COALESCE(u.last_name, 'Teacher') as last_name,
        COALESCE(u.email, '') as teacher_email,

        c.id as course_id,
        c.elective_type as elective_type,
        cm.course_id as course_code,
        cm.course_name,
        cm.course_type,
        cm.lecture_hours,
        cm.practical_hours,
        cm.tutorial_hours,
        cm.credits,
        dsd.dept_name as student_dept,
        dtd.dept_name as teaching_dept,
        dcd.dept_name as owner_dept,
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
        authentication_user u ON t.teacher_id_id = u.uuid
    LEFT JOIN
        teacher_teacher assist_t ON tc.asssist_teacher_id = assist_t.id
    LEFT JOIN
        authentication_user assist_u ON assist_t.teacher_id_id = assist_u.uuid
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
        AND tc.academic_year >= 2
        AND tc.semester >= 2
        AND cm.degree_type IN ('BE', 'BTECH')
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
    # Find indices of department columns that need cleaning
    dept_columns = ['student_dept', 'teaching_dept', 'owner_dept']
    dept_indices = [columns.index(col) if col in columns else -1 for col in dept_columns]
    
    with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(columns)
        for row in data:
            # Convert any None values to empty strings
            processed_row = ['' if value is None else value for value in row]
            # Remove "Department of " from department columns and replace 'and' with '&'
            for idx in dept_indices:
                if idx >= 0 and isinstance(processed_row[idx], str):
                    if processed_row[idx].startswith("Department of "):
                        processed_row[idx] = processed_row[idx][len("Department of "):]
                    elif processed_row[idx].startswith("Department Of "):
                        processed_row[idx] = processed_row[idx][len("Department Of "):]
                    # Replace ' and ' with ' & '
                    processed_row[idx] = processed_row[idx].replace(" and ", " & ")
            writer.writerow(processed_row)

def clean_dept_name(dept_name):
    """Remove 'Department of ' prefix from department name"""
    if dept_name.startswith("Department of "):
        return dept_name[len("Department of "):]
    return dept_name

def main():
    # Database path - change this to the actual path of your SQLite database
    db_path = input("Enter the path to your SQLite database file: ")

    if not os.path.exists(db_path):
        print(f"Database file not found: {db_path}")
        sys.exit(1)

    # Create data directory if it doesn't exist
    data_dir = 'data'
    ensure_directory_exists(data_dir)

    # Connect to the database
    conn = get_db_connection(db_path)

    try:
        # Get all departments that have students assigned to courses
        departments = get_student_departments(conn)

        print(f"Found {len(departments)} departments with assigned students")
        print("NOTE: Filtering out 1st year (academic_year = 1) and 1st semester (semester = 1) data")
        sum = 0
        all_data = []
        all_columns = []
        
        # Dictionary to organize data by year
        # Structure: {year: {dept_name: {'columns': [], 'data': []}}}
        year_dept_data = {}

        # Extract data for each department
        for dept in departments:
            dept_id = dept['id']
            dept_name = dept['dept_name']
            # Remove "Department of " prefix
            clean_name = clean_dept_name(dept_name)
            print(f"Processing department: {clean_name} (ID: {dept_id})")

            try:
                columns, data = extract_course_data_by_dept(conn, dept_id, dept_name)
                if columns and data:
                    # Find the index of academic_year column
                    year_idx = columns.index('academic_year') if 'academic_year' in columns else None
                    
                    if year_idx is not None:
                        # Group data by year
                        for row in data:
                            year = row[year_idx]
                            
                            if year not in year_dept_data:
                                year_dept_data[year] = {}
                            
                            if clean_name not in year_dept_data[year]:
                                year_dept_data[year][clean_name] = {'columns': columns, 'data': []}
                            
                            year_dept_data[year][clean_name]['data'].append(row)
                        
                        print(f"  Extracted {len(data)} records for department {clean_name}")
                        sum += len(data)
                        
                        # Accumulate data for combined CSV
                        if not all_data:
                            all_columns = columns
                        all_data.extend(data)
                    else:
                        print(f"Warning: 'academic_year' column not found for department {clean_name}")
                else:
                    print(f"No data found for department {clean_name}")
            except Exception as e:
                print(f"Error processing department {clean_name}: {e}")

        # Save data organized by year and department
        for year, depts in year_dept_data.items():
            # Create year directory
            year_dir = os.path.join(data_dir, str(year))
            ensure_directory_exists(year_dir)
            
            for dept_name, dept_info in depts.items():
                # Sanitize department name for filename
                safe_dept_name = "".join([c for c in dept_name if c.isalpha() or c.isdigit() or c==' ' or c=='_']).rstrip()
                output_filename = os.path.join(year_dir, f'{safe_dept_name}_course_data.csv')
                save_to_csv(dept_info['columns'], dept_info['data'], output_filename)
                print(f"Saved {len(dept_info['data'])} records -> {output_filename}")

        # Save combined data (still in root data folder)
        if all_data:
            combined_filename = os.path.join(data_dir, 'combined_course_data.csv')
            save_to_csv(all_columns, all_data, combined_filename)
            print(f"Successfully created combined CSV with {len(all_data)} records -> {combined_filename}")

    finally:
        # Close the database connection
        conn.close()
        print(f"Total records extracted: {sum}")
if __name__ == "__main__":
    main()
