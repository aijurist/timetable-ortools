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
    """Get data from course_course table"""
    return get_data_as_dataframe('course_course')

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
    """Get data from teacherCourse_teachercourse table"""
    return get_data_as_dataframe('teacherCourse_teachercourse')

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
def get_teacher_with_courses(teacher_id: str) -> Dict[str, Any]:
    """Get teacher details along with assigned courses
    
    Args:
        teacher_id (str): Teacher's ID
        
    Returns:
        Dict: Teacher details with courses
    """
    conn = connect_db()
    if not conn:
        return None
    
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get teacher details
        teacher_query = """
        SELECT * FROM teacher_teacher 
        JOIN authentication_user ON authentication_user.email = teacher_teacher.teacher_id_id 
        WHERE teacher_id_id = ?
        """
        cursor.execute(teacher_query, (teacher_id,))
        teacher = dict(cursor.fetchone()) if cursor.fetchone() else None
        
        if not teacher:
            return None
        
        # Get teacher's courses
        courses_query = """
        SELECT * FROM teacherCourse_teachercourse
        JOIN course_course ON course_course.id = teacherCourse_teachercourse.course_id_id
        JOIN courseMaster_coursemaster ON courseMaster_coursemaster.id = course_course.course_id_id
        WHERE teacherCourse_teachercourse.teacher_id_id = ?
        """
        cursor.execute(courses_query, (teacher_id,))
        courses = [dict(row) for row in cursor.fetchall()]
        
        # Combine results
        teacher['courses'] = courses
        return teacher
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
    # Example 1: Get all departments
    departments_df = get_departments()
    if departments_df is not None:
        print("Departments:")
        print(departments_df.head())
        print()
    
    # Example 2: Get all courses
    courses_df = get_courses()
    if courses_df is not None:
        print("Courses:")
        print(courses_df.head())
        print()
    
    # Example 3: Get all teachers
    teachers_df = get_teachers()
    if teachers_df is not None:
        print("Teachers:")
        print(teachers_df.head())
        print()
    
    # Example 4: Get all timetable entries
    timetable_df = get_timetable()
    if timetable_df is not None:
        print("Timetable:")
        print(timetable_df.head()) 