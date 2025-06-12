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

def get_departments(conn):
    """Get all departments."""
    query = """
    SELECT DISTINCT id, dept_name
    FROM department_department
    ORDER BY dept_name
    """
    try:
        cursor = conn.cursor()
        cursor.execute(query)
        departments = cursor.fetchall()
        return departments
    except sqlite3.Error as e:
        print(f"Error fetching departments: {e}")
        return []

def analyze_cross_departmental_courses(conn):
    """Analyze courses where teaching_dept != student_dept"""
    query = """
    SELECT DISTINCT 
        cm.course_name,
        cm.course_id as course_code,
        dcd.dept_name as course_dept,
        dtd.dept_name as teaching_dept,
        dsd.dept_name as student_dept,
        COUNT(*) as teacher_count
    FROM 
        teacherCourse_teachercourse tc
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
    WHERE 
        dtd.dept_name != dsd.dept_name
    GROUP BY 
        cm.course_name, dcd.dept_name, dtd.dept_name, dsd.dept_name
    ORDER BY 
        cm.course_name
    """
    try:
        cursor = conn.cursor()
        cursor.execute(query)
        return cursor.fetchall()
    except sqlite3.Error as e:
        print(f"Error analyzing cross-departmental courses: {e}")
        return []

def extract_course_data_by_student_dept(conn, dept_id, dept_name):
    """Extract course data for a specific student department"""
    query = """
    SELECT 
        tc.id,
        tc.student_count,
        tc.academic_year,
        tc.semester,
        tc.requires_special_scheduling,
        CASE WHEN tc.asssist_teacher_id IS NOT NULL THEN 1 ELSE 0 END as is_assistant,
        t.id as teacher_id,
        t.staff_code,
        COALESCE(u.first_name, 'Unknown') as first_name,
        COALESCE(u.last_name, 'Teacher') as last_name,
        COALESCE(u.email, '') as teacher_email,
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

def extract_course_data_by_teaching_dept(conn, dept_id, dept_name):
    """Extract course data for a specific teaching department"""
    query = """
    SELECT 
        tc.id,
        tc.student_count,
        tc.academic_year,
        tc.semester,
        tc.requires_special_scheduling,
        CASE WHEN tc.asssist_teacher_id IS NOT NULL THEN 1 ELSE 0 END as is_assistant,
        t.id as teacher_id,
        t.staff_code,
        COALESCE(u.first_name, 'Unknown') as first_name,
        COALESCE(u.last_name, 'Teacher') as last_name,
        COALESCE(u.email, '') as teacher_email,
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
        c.teaching_dept_id_id = ?
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

def save_cross_dept_analysis(cross_dept_courses, filename):
    """Save cross-departmental course analysis to CSV"""
    with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['Course Name', 'Course Code', 'Course Dept', 'Teaching Dept', 'Student Dept', 'Teacher Count'])
        for course in cross_dept_courses:
            writer.writerow([course['course_name'], course['course_code'], course['course_dept'], 
                           course['teaching_dept'], course['student_dept'], course['teacher_count']])

def main():
    print("Enhanced Department Data Extraction Tool")
    print("="*50)
    
    # Database path
    db_path = input("Enter the path to your SQLite database file: ")
    
    if not os.path.exists(db_path):
        print(f"Database file not found: {db_path}")
        sys.exit(1)
    
    # Connect to the database
    conn = get_db_connection(db_path)
    
    try:
        # Analyze cross-departmental courses first
        print("\nAnalyzing cross-departmental courses...")
        cross_dept_courses = analyze_cross_departmental_courses(conn)
        
        if cross_dept_courses:
            print(f"\nFound {len(cross_dept_courses)} cross-departmental courses:")
            print("(Teaching Dept != Student Dept)")
            for course in cross_dept_courses[:10]:  # Show first 10
                print(f"  - {course['course_name']}: Teaching={course['teaching_dept']}, Student={course['student_dept']}")
            if len(cross_dept_courses) > 10:
                print(f"  ... and {len(cross_dept_courses) - 10} more")
            
            # Save analysis
            analysis_dir = 'data/analysis'
            ensure_directory_exists(analysis_dir)
            analysis_file = os.path.join(analysis_dir, 'cross_departmental_courses.csv')
            save_cross_dept_analysis(cross_dept_courses, analysis_file)
            print(f"\nCross-departmental analysis saved to: {analysis_file}")
        
        # Choose grouping strategy
        print("\nChoose grouping strategy:")
        print("1. Group by Student Department (recommended for timetabling)")
        print("2. Group by Teaching Department (alternative view)")
        print("3. Both (creates two sets of files)")
        
        choice = input("Enter your choice (1/2/3): ").strip()
        
        # Get all departments
        departments = get_departments(conn)
        print(f"\nFound {len(departments)} departments")
        
        if choice in ['1', '3']:
            print("\n" + "="*50)
            print("EXTRACTING DATA BY STUDENT DEPARTMENT")
            print("="*50)
            
            # Create data directory
            data_dir = 'data/department_data_by_student'
            ensure_directory_exists(data_dir)
            
            # Extract data for each department (by student dept)
            for dept in departments:
                dept_id = dept['id']
                dept_name = dept['dept_name']
                print(f"Processing department: {dept_name} (ID: {dept_id})")
                
                # Replace any characters that would be invalid in filenames
                safe_dept_name = ''.join(c if c.isalnum() else '_' for c in dept_name)
                filename = os.path.join(data_dir, f"{safe_dept_name}_courses.csv")
                
                try:
                    columns, data = extract_course_data_by_student_dept(conn, dept_id, dept_name)
                    if columns and data:
                        save_to_csv(columns, data, filename)
                        print(f"  Successfully saved {len(data)} records to {filename}")
                        
                        # Check for cross-departmental courses in this department
                        cross_dept_count = sum(1 for row in data if row[21] != dept_name)  # teaching_dept != student_dept
                        if cross_dept_count > 0:
                            print(f"  Note: {cross_dept_count} courses are taught by other departments")
                    else:
                        print(f"  No data found for department {dept_name}")
                except Exception as e:
                    print(f"  Error processing department {dept_name}: {e}")
        
        if choice in ['2', '3']:
            print("\n" + "="*50)
            print("EXTRACTING DATA BY TEACHING DEPARTMENT")
            print("="*50)
            
            # Create data directory
            data_dir = 'data/department_data_by_teaching'
            ensure_directory_exists(data_dir)
            
            # Extract data for each department (by teaching dept)
            for dept in departments:
                dept_id = dept['id']
                dept_name = dept['dept_name']
                print(f"Processing department: {dept_name} (ID: {dept_id})")
                
                # Replace any characters that would be invalid in filenames
                safe_dept_name = ''.join(c if c.isalnum() else '_' for c in dept_name)
                filename = os.path.join(data_dir, f"{safe_dept_name}_teaching.csv")
                
                try:
                    columns, data = extract_course_data_by_teaching_dept(conn, dept_id, dept_name)
                    if columns and data:
                        save_to_csv(columns, data, filename)
                        print(f"  Successfully saved {len(data)} records to {filename}")
                        
                        # Check for cross-departmental courses in this department
                        cross_dept_count = sum(1 for row in data if row[23] != dept_name)  # student_dept != teaching_dept
                        if cross_dept_count > 0:
                            print(f"  Note: {cross_dept_count} courses are for students from other departments")
                    else:
                        print(f"  No data found for department {dept_name}")
                except Exception as e:
                    print(f"  Error processing department {dept_name}: {e}")
        
        print("\n" + "="*50)
        print("EXTRACTION COMPLETE!")
        print("="*50)
        
        if choice == '1':
            print("Data grouped by Student Department - courses are organized by which students take them")
        elif choice == '2':
            print("Data grouped by Teaching Department - courses are organized by which department teaches them")
        else:
            print("Data grouped both ways - you can choose the most appropriate for your needs")
        
        if cross_dept_courses:
            print(f"\nNote: {len(cross_dept_courses)} cross-departmental courses were identified.")
            print("These courses appear in the student department files but are taught by other departments.")
            print("For example: '3D Printing and Design' is for CSD students but taught by Mechanical Engineering.")
    
    finally:
        # Close the database connection
        conn.close()

if __name__ == "__main__":
    main() 