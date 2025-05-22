import sqlite3
import pandas as pd
import os
import csv

def extract_cs_teacher_course_data():
    """
    Extract teacher-course allocation data for Computer Science department
    from the data-dump-final SQLite database.
    """
    # Connect to the database
    db_path = os.path.join('data', 'data-dump-final.sqlite3')
    conn = sqlite3.connect(db_path)
    
    # Get CS department ID
    cs_dept_query = """
    SELECT id FROM department_department 
    WHERE dept_name LIKE '%Computer Science%' OR dept_name LIKE '%CSE%'
    """
    cs_dept = pd.read_sql_query(cs_dept_query, conn)
    
    if cs_dept.empty:
        print("Computer Science department not found!")
        conn.close()
        return
    
    cs_dept_ids = cs_dept['id'].tolist()
    print(f"Found CS department IDs: {cs_dept_ids}")
    
    # Query to get CS teachers
    cs_teachers_query = f"""
    SELECT t.id, t.staff_code, t.teacher_role, t.teacher_specialisation, 
           u.first_name, u.last_name, u.email, d.dept_name
    FROM teacher_teacher t
    JOIN authentication_user u ON t.teacher_id_id = u.email
    JOIN department_department d ON t.dept_id_id = d.id
    WHERE t.dept_id_id IN ({','.join(map(str, cs_dept_ids))})
    AND t.resignation_status = 'active'
    """
    
    cs_teachers = pd.read_sql_query(cs_teachers_query, conn)
    print(f"Found {len(cs_teachers)} active CS teachers")
    
    # Query to get course assignments for CS teachers
    teacher_course_query = f"""
    SELECT 
        tc.id,
        tc.student_count,
        tc.academic_year,
        tc.semester,
        tc.requires_special_scheduling,
        tc.is_assistant,
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
        d.dept_name as course_dept
    FROM teacherCourse_teachercourse tc
    JOIN teacher_teacher t ON tc.teacher_id_id = t.id
    JOIN authentication_user u ON t.teacher_id_id = u.email
    JOIN course_course c ON tc.course_id_id = c.id
    JOIN courseMaster_coursemaster cm ON c.course_id_id = cm.id
    JOIN department_department d ON c.teaching_dept_id_id = d.id
    WHERE t.dept_id_id IN ({','.join(map(str, cs_dept_ids))})
    AND t.resignation_status = 'active'
    """
    
    teacher_courses = pd.read_sql_query(teacher_course_query, conn)
    print(f"Found {len(teacher_courses)} course assignments for CS teachers")
    
    # Close the database connection
    conn.close()
    
    # Save the data to CSV files
    output_dir = os.path.join('data', 'mapped_data')
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    cs_teachers_file = os.path.join(output_dir, 'cs_teachers.csv')
    teacher_courses_file = os.path.join(output_dir, 'cs_teacher_courses.csv')
    
    cs_teachers.to_csv(cs_teachers_file, index=False)
    teacher_courses.to_csv(teacher_courses_file, index=False)
    
    print(f"CS teachers data saved to {cs_teachers_file}")
    print(f"CS teacher-course assignments saved to {teacher_courses_file}")
    
    # Format data for timetable scheduler
    formatted_data = teacher_courses[['id', 'teacher_id', 'staff_code', 'first_name', 'last_name', 
                                     'course_id', 'course_code', 'course_name', 'course_type',
                                     'student_count', 'credits']]
    
    formatted_file = os.path.join(output_dir, 'cs_teacher_course_formatted.csv')
    formatted_data.to_csv(formatted_file, index=False)
    print(f"Formatted data for scheduler saved to {formatted_file}")
    
    return cs_teachers, teacher_courses

if __name__ == "__main__":
    extract_cs_teacher_course_data() 