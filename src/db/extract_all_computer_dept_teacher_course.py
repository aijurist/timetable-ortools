import sqlite3
import pandas as pd
import os
import csv

def extract_all_computer_dept_teacher_course_data():
    """
    Extract teacher-course allocation data for all Computer-related departments
    (Computer Science, AI, Robotics, Data Science, Information Technology, etc.)
    from the data-dump-final SQLite database.
    """
    # Connect to the database
    db_path = os.path.join('data', 'data-dump-final.sqlite3')
    conn = sqlite3.connect(db_path)
    
    # Get all computer-related department IDs
    computer_dept_query = """
    SELECT id, dept_name FROM department_department 
    WHERE LOWER(dept_name) LIKE '%computer%' 
       OR LOWER(dept_name) LIKE '%cse%'
       OR LOWER(dept_name) LIKE '%cs%'
       OR LOWER(dept_name) LIKE '%artificial intelligence%'
       OR LOWER(dept_name) LIKE '%ai%'
       OR LOWER(dept_name) LIKE '%robotics%'
       OR LOWER(dept_name) LIKE '%data science%'
       OR LOWER(dept_name) LIKE '%information technology%'
       OR LOWER(dept_name) LIKE '%it%'
       OR LOWER(dept_name) LIKE '%software%'
       OR LOWER(dept_name) LIKE '%cybersecurity%'
       OR LOWER(dept_name) LIKE '%machine learning%'
       OR LOWER(dept_name) LIKE '%ml%'
       OR LOWER(dept_name) LIKE '%computational%'
    """
    computer_depts = pd.read_sql_query(computer_dept_query, conn)
    
    if computer_depts.empty:
        print("No computer-related departments found!")
        conn.close()
        return
    
    computer_dept_ids = computer_depts['id'].tolist()
    dept_names = computer_depts['dept_name'].tolist()
    print(f"Found {len(computer_dept_ids)} computer-related departments:")
    for dept_name in dept_names:
        print(f"  - {dept_name}")
    print(f"Department IDs: {computer_dept_ids}")
    
    # Query to get teachers from all computer departments
    computer_teachers_query = f"""
    SELECT t.id, t.staff_code, t.teacher_role, t.teacher_specialisation, 
           u.first_name, u.last_name, u.email, d.dept_name
    FROM teacher_teacher t
    JOIN authentication_user u ON t.teacher_id_id = u.email
    JOIN department_department d ON t.dept_id_id = d.id
    WHERE t.dept_id_id IN ({','.join(map(str, computer_dept_ids))})
    AND t.resignation_status = 'active'
    ORDER BY d.dept_name, u.last_name, u.first_name
    """
    
    computer_teachers = pd.read_sql_query(computer_teachers_query, conn)
    print(f"Found {len(computer_teachers)} active teachers across all computer departments")
    
    # Display teacher count by department
    teacher_count_by_dept = computer_teachers.groupby('dept_name').size()
    print("\nTeacher count by department:")
    for dept, count in teacher_count_by_dept.items():
        print(f"  {dept}: {count} teachers")
    
    # Query to get course assignments for all computer department teachers
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
        t.teacher_role,
        t.teacher_specialisation,
        u.first_name,
        u.last_name,
        u.email as teacher_email,
        teacher_dept.dept_name as teacher_dept,
        c.id as course_id,
        cm.course_id as course_code,
        cm.course_name,
        cm.course_type,
        cm.lecture_hours,
        cm.practical_hours,
        cm.tutorial_hours,
        cm.credits,
        course_dept.dept_name as course_dept
    FROM teacherCourse_teachercourse tc
    JOIN teacher_teacher t ON tc.teacher_id_id = t.id
    JOIN authentication_user u ON t.teacher_id_id = u.email
    JOIN department_department teacher_dept ON t.dept_id_id = teacher_dept.id
    JOIN course_course c ON tc.course_id_id = c.id
    JOIN courseMaster_coursemaster cm ON c.course_id_id = cm.id
    JOIN department_department course_dept ON c.teaching_dept_id_id = course_dept.id
    WHERE t.dept_id_id IN ({','.join(map(str, computer_dept_ids))})
    AND t.resignation_status = 'active'
    ORDER BY teacher_dept.dept_name, u.last_name, u.first_name, cm.course_name
    """
    
    teacher_courses = pd.read_sql_query(teacher_course_query, conn)
    print(f"Found {len(teacher_courses)} course assignments for computer department teachers")
    
    # Display course assignment statistics
    if not teacher_courses.empty:
        print(f"\nCourse assignment statistics:")
        print(f"  Total unique teachers with assignments: {teacher_courses['teacher_id'].nunique()}")
        print(f"  Total unique courses: {teacher_courses['course_id'].nunique()}")
        print(f"  Average assignments per teacher: {len(teacher_courses) / teacher_courses['teacher_id'].nunique():.1f}")
        
        # Course assignments by department
        assignments_by_dept = teacher_courses.groupby('teacher_dept').size()
        print("\nCourse assignments by teacher department:")
        for dept, count in assignments_by_dept.items():
            print(f"  {dept}: {count} assignments")
    
    # Close the database connection
    conn.close()
    
    # Save the data to CSV files
    output_dir = os.path.join('data', 'mapped_data')
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # Save department list
    computer_depts_file = os.path.join(output_dir, 'computer_departments.csv')
    computer_depts.to_csv(computer_depts_file, index=False)
    print(f"\nComputer departments data saved to {computer_depts_file}")
    
    # Save teachers data
    computer_teachers_file = os.path.join(output_dir, 'computer_dept_teachers.csv')
    computer_teachers.to_csv(computer_teachers_file, index=False)
    print(f"Computer department teachers data saved to {computer_teachers_file}")
    
    # Save teacher-course assignments
    teacher_courses_file = os.path.join(output_dir, 'computer_dept_teacher_courses.csv')
    teacher_courses.to_csv(teacher_courses_file, index=False)
    print(f"Computer department teacher-course assignments saved to {teacher_courses_file}")
    
    # Format data for timetable scheduler (comprehensive version)
    if not teacher_courses.empty:
        formatted_data = teacher_courses[[
            'id', 'teacher_id', 'staff_code', 'first_name', 'last_name', 'teacher_email',
            'teacher_dept', 'teacher_role', 'teacher_specialisation',
            'course_id', 'course_code', 'course_name', 'course_type', 'course_dept',
            'student_count', 'credits', 'lecture_hours', 'practical_hours', 'tutorial_hours',
            'academic_year', 'semester', 'requires_special_scheduling', 'is_assistant'
        ]]
        
        formatted_file = os.path.join(output_dir, 'computer_dept_teacher_course_formatted.csv')
        formatted_data.to_csv(formatted_file, index=False)
        print(f"Formatted data for scheduler saved to {formatted_file}")
    
    # Generate summary report
    summary_file = os.path.join(output_dir, 'computer_dept_extraction_summary.txt')
    with open(summary_file, 'w') as f:
        f.write("Computer Departments Teacher-Course Extraction Summary\n")
        f.write("=" * 55 + "\n\n")
        
        f.write(f"Extraction Date: {pd.Timestamp.now()}\n\n")
        
        f.write("Departments Found:\n")
        for i, dept_name in enumerate(dept_names, 1):
            f.write(f"{i:2d}. {dept_name}\n")
        f.write(f"\nTotal Departments: {len(dept_names)}\n\n")
        
        f.write(f"Teachers Found: {len(computer_teachers)}\n")
        if not computer_teachers.empty:
            f.write("Teachers by Department:\n")
            for dept, count in teacher_count_by_dept.items():
                f.write(f"  {dept}: {count}\n")
        
        f.write(f"\nCourse Assignments: {len(teacher_courses)}\n")
        if not teacher_courses.empty:
            f.write(f"Unique Teachers with Assignments: {teacher_courses['teacher_id'].nunique()}\n")
            f.write(f"Unique Courses: {teacher_courses['course_id'].nunique()}\n")
            f.write(f"Average Assignments per Teacher: {len(teacher_courses) / teacher_courses['teacher_id'].nunique():.1f}\n\n")
            
            f.write("Assignments by Department:\n")
            for dept, count in assignments_by_dept.items():
                f.write(f"  {dept}: {count}\n")
    
    print(f"Summary report saved to {summary_file}")
    
    return computer_depts, computer_teachers, teacher_courses

def get_department_statistics():
    """
    Get statistics about computer-related departments without extracting full data.
    """
    db_path = os.path.join('data', 'data-dump-final.sqlite3')
    conn = sqlite3.connect(db_path)
    
    # Query to find all departments (to help identify computer-related ones)
    all_depts_query = """
    SELECT id, dept_name, COUNT(t.id) as teacher_count
    FROM department_department d
    LEFT JOIN teacher_teacher t ON d.id = t.dept_id_id AND t.resignation_status = 'active'
    GROUP BY d.id, d.dept_name
    ORDER BY d.dept_name
    """
    
    all_depts = pd.read_sql_query(all_depts_query, conn)
    conn.close()
    
    print("All Departments (with active teacher count):")
    print("=" * 50)
    for _, dept in all_depts.iterrows():
        print(f"{dept['dept_name']:40} | {dept['teacher_count']:3d} teachers")
    
    return all_depts

if __name__ == "__main__":
    print("Computer Departments Teacher-Course Data Extraction")
    print("=" * 55)
    print("\nOption 1: Extract all computer department data")
    print("Option 2: View all departments statistics")
    
    choice = input("\nEnter your choice (1 or 2): ").strip()
    
    if choice == "2":
        get_department_statistics()
    else:
        extract_all_computer_dept_teacher_course_data() 