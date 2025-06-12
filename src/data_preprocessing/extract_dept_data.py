#!/usr/bin/env python
import os
import csv
import django
import sys
from datetime import datetime

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'your_project.settings')

try:
    django.setup()
except Exception as e:
    print(f"Error setting up Django: {e}")
    print("This script needs to be run in a Django environment.")
    print("Proceeding with direct database connection...")

# Import necessary models or use direct SQL if Django setup fails
try:
    from django.db import connection
except ImportError:
    print("Django not installed or configured correctly.")
    print("Please install Django or update the script to use another database library.")
    sys.exit(1)

def ensure_directory_exists(directory):
    """Create directory if it doesn't exist"""
    if not os.path.exists(directory):
        os.makedirs(directory)

def get_departments():
    """Get all departments from the database"""
    with connection.cursor() as cursor:
        cursor.execute("SELECT id, dept_name FROM department_department")
        departments = cursor.fetchall()
    return departments

def extract_course_data_by_dept(dept_id, dept_name):
    """Extract course data for a specific department"""
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
        u.first_name,
        u.last_name,
        u.email as teacher_email,
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
        COALESCE(r.description, '') as room_description
    FROM 
        teacherCourse_teachercourse tc
    JOIN 
        teacher_teacher t ON tc.teacher_id_id = t.id
    JOIN 
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
        c.for_dept_id_id = %s
    """
    
    with connection.cursor() as cursor:
        cursor.execute(query, [dept_id])
        columns = [col[0] for col in cursor.description]
        data = cursor.fetchall()
    
    return columns, data

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
    # Create data directory if it doesn't exist
    data_dir = 'data/department_data'
    ensure_directory_exists(data_dir)
    
    # Get all departments
    departments = get_departments()
    
    print(f"Found {len(departments)} departments")
    
    # Extract data for each department
    for dept_id, dept_name in departments:
        print(f"Processing department: {dept_name} (ID: {dept_id})")
        
        # Replace any characters that would be invalid in filenames
        safe_dept_name = ''.join(c if c.isalnum() else '_' for c in dept_name)
        filename = os.path.join(data_dir, f"{safe_dept_name}_courses.csv")
        
        try:
            columns, data = extract_course_data_by_dept(dept_id, dept_name)
            save_to_csv(columns, data, filename)
            print(f"Successfully saved {len(data)} records to {filename}")
        except Exception as e:
            print(f"Error processing department {dept_name}: {e}")
    
    print("Data extraction complete!")

if __name__ == "__main__":
    main() 