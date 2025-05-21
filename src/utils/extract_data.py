import sqlite3
import pandas as pd
from typing import  Dict, Any, Optional

DB_PATH = "../../data/data-dump-final.sqlite3"

def connect_db():
    """Establish connection to the SQLite database"""
    try:
        conn = sqlite3.connect(DB_PATH)
        return conn
    except sqlite3.Error as e:
        print(f"Database connection error: {e}")
        return None

def close_connection(conn):
    """Close the database connection"""
    if conn:
        conn.close()

def execute_query(query: str, params: tuple = (), one: bool = False):
    """Execute a query and return the results
    
    Args:
        query (str): SQL query to execute
        params (tuple, optional): Parameters for the query. Defaults to ().
        one (bool, optional): If True, return only one result. Defaults to False.
        
    Returns:
        List or Dict: Query results
    """
    conn = connect_db()
    if not conn:
        return None
    
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(query, params)
        
        if one:
            result = dict(cursor.fetchone()) if cursor.fetchone() else None
        else:
            result = [dict(row) for row in cursor.fetchall()]
        
        return result
    except sqlite3.Error as e:
        print(f"Query execution error: {e}")
        return None
    finally:
        close_connection(conn)

def get_data_as_dataframe(table_name: str) -> Optional[pd.DataFrame]:
    """Get data from a table as a pandas DataFrame
    
    Args:
        table_name (str): Name of the table
        
    Returns:
        Optional[pd.DataFrame]: DataFrame containing the table data or None if error
    """
    conn = connect_db()
    if not conn:
        return None
    
    try:
        query = f"SELECT * FROM {table_name}"
        df = pd.read_sql_query(query, conn)
        return df
    except sqlite3.Error as e:
        print(f"Error fetching data from {table_name}: {e}")
        return None
    finally:
        close_connection(conn)

# Functions for each table in the database

def get_attendance():
    """Get data from attendance table"""
    return get_data_as_dataframe('attendance')

def get_attendance_session():
    """Get data from attendance_session table"""
    return get_data_as_dataframe('attendance_session')

def get_auth_group():
    """Get data from auth_group table"""
    return get_data_as_dataframe('auth_group')

def get_auth_group_permissions():
    """Get data from auth_group_permissions table"""
    return get_data_as_dataframe('auth_group_permissions')

def get_auth_permission():
    """Get data from auth_permission table"""
    return get_data_as_dataframe('auth_permission')

def get_blocked_students():
    """Get data from authentication_blockedstudents table"""
    return get_data_as_dataframe('authentication_blockedstudents')

def get_forget_password():
    """Get data from authentication_forgetpassword table"""
    return get_data_as_dataframe('authentication_forgetpassword')

def get_users():
    """Get data from authentication_user table"""
    return get_data_as_dataframe('authentication_user')

def get_user_groups():
    """Get data from authentication_user_groups table"""
    return get_data_as_dataframe('authentication_user_groups')

def get_user_permissions():
    """Get data from authentication_user_user_permissions table"""
    return get_data_as_dataframe('authentication_user_user_permissions')

def get_course_master():
    """Get data from courseMaster_coursemaster table"""
    return get_data_as_dataframe('courseMaster_coursemaster')

def get_course_master_room_preference():
    """Get data from courseMaster_coursemasterroompreference table"""
    return get_data_as_dataframe('courseMaster_coursemasterroompreference')

def get_courses():
    """Get data from course_course table with related information"""
    conn = connect_db()
    if not conn:
        return None
    
    try:
        query = """
        SELECT cc.*,
               cm.course_id, cm.course_name, cm.is_zero_credit_course, cm.lecture_hours,
               cm.practical_hours, cm.tutorial_hours, cm.credits, cm.regulation, 
               cm.course_type, cm.degree_type,
               fd.dept_name as for_dept_name,
               td.dept_name as teaching_dept_name
        FROM course_course cc
        JOIN courseMaster_coursemaster cm ON cc.course_id_id = cm.id
        LEFT JOIN department_department fd ON cc.for_dept_id_id = fd.id
        LEFT JOIN department_department td ON cc.teaching_dept_id_id = td.id
        """
        df = pd.read_sql_query(query, conn)
        return df
    except sqlite3.Error as e:
        print(f"Error fetching courses: {e}")
        return None
    finally:
        close_connection(conn)

def get_course_resource_allocation():
    """Get data from course_courseresourceallocation table"""
    return get_data_as_dataframe('course_courseresourceallocation')

def get_course_slot_preference():
    """Get data from course_courseslotpreference table"""
    return get_data_as_dataframe('course_courseslotpreference')

def get_departments():
    """Get data from department_department table"""
    return get_data_as_dataframe('department_department')

def get_rooms():
    """Get data from rooms_room table"""
    return get_data_as_dataframe('rooms_room')

def get_slots():
    """Get data from slot_slot table"""
    return get_data_as_dataframe('slot_slot')

def get_teacher_slot_assignment():
    """Get data from slot_teacherslotassignment table"""
    return get_data_as_dataframe('slot_teacherslotassignment')

def get_student_courses():
    """Get data from studentCourse_studentcourse table"""
    return get_data_as_dataframe('studentCourse_studentcourse')

def get_students():
    """Get data from student_student table"""
    return get_data_as_dataframe('student_student')

def get_teacher_courses():
    """Get data from teacherCourse_teachercourse table with related information"""
    conn = connect_db()
    if not conn:
        return None
    
    try:
        query = """
        SELECT tc.*, 
               cc.course_year, cc.course_semester, cc.elective_type, cc.lab_type, cc.teaching_status,
               cm.course_id, cm.course_name, cm.is_zero_credit_course, cm.credits, 
               cm.regulation, cm.course_type, cm.degree_type,
               t.staff_code, t.teacher_role, t.teacher_specialisation,
               au.first_name, au.last_name, au.email
        FROM teacherCourse_teachercourse tc
        JOIN course_course cc ON tc.course_id_id = cc.id
        JOIN courseMaster_coursemaster cm ON cc.course_id_id = cm.id
        JOIN teacher_teacher t ON tc.teacher_id_id = t.id
        JOIN authentication_user au ON t.teacher_id_id = au.email
        """
        df = pd.read_sql_query(query, conn)
        return df
    except sqlite3.Error as e:
        print(f"Error fetching teacher courses: {e}")
        return None
    finally:
        close_connection(conn)

def get_teacher_course_availability():
    """Get data from teacherCourse_teachercourse_preferred_availability_slots table"""
    return get_data_as_dataframe('teacherCourse_teachercourse_preferred_availability_slots')

def get_teachers():
    """Get data from teacher_teacher table"""
    return get_data_as_dataframe('teacher_teacher')

def get_teacher_availability():
    """Get data from teacher_teacheravailability table"""
    return get_data_as_dataframe('teacher_teacheravailability')

def get_timetable():
    """Get data from timetable table"""
    return get_data_as_dataframe('timetable')

def get_timetable_changes():
    """Get data from timetable_change table"""
    return get_data_as_dataframe('timetable_change')

# Example of a more complex query for related data
def get_teacher_with_courses() -> Dict[str, Any]:
    """Get all teachers details along with their assigned courses
    
    Returns:
        Dict: Dictionary with teachers and their courses
    """
    conn = connect_db()
    if not conn:
        return None
    
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get all teachers
        teacher_query = """
        SELECT * FROM teacher_teacher 
        JOIN authentication_user ON authentication_user.email = teacher_teacher.teacher_id_id
        """
        cursor.execute(teacher_query)
        teachers = [dict(row) for row in cursor.fetchall()]
        
        if not teachers:
            return None
        
        # Get all teacher courses
        courses_query = """
        SELECT tc.*, cc.*, cm.* 
        FROM teacherCourse_teachercourse tc
        JOIN course_course cc ON cc.id = tc.course_id_id
        JOIN courseMaster_coursemaster cm ON cm.id = cc.course_id_id
        """
        cursor.execute(courses_query)
        all_courses = [dict(row) for row in cursor.fetchall()]
        
        # Map courses to respective teachers
        result = {}
        for teacher in teachers:
            teacher_id = teacher.get('teacher_id_id')
            teacher_courses = [
                course for course in all_courses 
                if course.get('teacher_id_id') == teacher_id
            ]
            teacher_info = dict(teacher)
            teacher_info['courses'] = teacher_courses
            result[teacher_id] = teacher_info
        
        return result
    except sqlite3.Error as e:
        print(f"Error fetching teacher data: {e}")
        return None
    finally:
        close_connection(conn)

# Example of a function to get timetable for a specific teacher
def get_teacher_timetable(teacher_id: str) -> pd.DataFrame:
    """Get timetable entries for a specific teacher
    
    Args:
        teacher_id (str): Teacher's ID
        
    Returns:
        pd.DataFrame: Teacher's timetable
    """
    conn = connect_db()
    if not conn:
        return None
    
    try:
        query = """
        SELECT t.*, s.slot_name, s.slot_start_time, s.slot_end_time, 
               r.room_number, r.block, tc.course_id_id, cm.course_name
        FROM timetable t
        JOIN slot_slot s ON t.slot_id = s.id
        JOIN rooms_room r ON t.room_id = r.id
        JOIN teacherCourse_teachercourse tc ON t.course_assignment_id = tc.id
        JOIN course_course cc ON tc.course_id_id = cc.id
        JOIN courseMaster_coursemaster cm ON cc.course_id_id = cm.id
        WHERE tc.teacher_id_id = ?
        """
        df = pd.read_sql_query(query, conn, params=(teacher_id,))
        return df
    except sqlite3.Error as e:
        print(f"Error fetching teacher timetable: {e}")
        return None
    finally:
        close_connection(conn)

# Example usage
if __name__ == "__main__":
    # Example 1: Get teachers with courses (dictionary return)
    print("\n=== TEACHERS WITH COURSES (Dictionary) ===")
    teachers_with_courses = get_teacher_with_courses()
    if teachers_with_courses is not None:
        # Get the first 2 teacher entries
        sample_teachers = list(teachers_with_courses.items())[:2]
        for teacher_id, teacher_data in sample_teachers:
            print(f"Teacher ID: {teacher_id}")
            print(f"Name: {teacher_data.get('first_name')} {teacher_data.get('last_name')}")
            print(f"Number of courses: {len(teacher_data.get('courses', []))}")
            if teacher_data.get('courses'):
                print("Course names:")
                for course in teacher_data.get('courses', [])[:2]:  # Show max 2 courses
                    print(f"  - {course.get('course_name', 'Unknown')}")
            print("---")
    
    # Example 2: Get enhanced teacher courses (dataframe return)
    print("\n=== TEACHER COURSES (DataFrame) ===")
    teacher_courses_df = get_teacher_courses()
    if teacher_courses_df is not None:
        print(f"Total records: {len(teacher_courses_df)}")
        if not teacher_courses_df.empty:
            # Display specific columns to see the joined data
            print(teacher_courses_df[['first_name', 'last_name', 'course_name', 'course_semester', 'student_count']].head(3))
            # Show all columns
            print("\nAll columns available:")
            print(teacher_courses_df.columns.tolist())
    
    # Example 3: Get enhanced courses data
    print("\n=== COURSES (Enhanced) ===")
    courses_df = get_courses()
    if courses_df is not None:
        print(f"Total courses: {len(courses_df)}")
        if not courses_df.empty:
            # Display specific columns
            print(courses_df[['course_id', 'course_name', 'course_year', 'course_semester', 'for_dept_name', 'teaching_dept_name']].head(3))
            # Show all columns
            print("\nAll columns available:")
            print(courses_df.columns.tolist())
    
    # Example 4: Get departments (original simple function)
    print("\n=== DEPARTMENTS (Simple) ===")
    departments_df = get_departments()
    if departments_df is not None:
        print(departments_df.head(3))
    
    # Example 5: Get timetable entries
    print("\n=== TIMETABLE ===")
    timetable_df = get_timetable()
    if timetable_df is not None:
        print(timetable_df.head(3)) 