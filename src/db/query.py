import sqlite3
import pandas as pd
from src.db.connect import connect_db, close_connection

def execute_query(query, params=None):
    """
    Execute a SQL query and return results as a DataFrame (for SELECT)
    or commit changes (for INSERT/UPDATE/DELETE).
    
    Args:
        query (str): SQL query to execute
        params (tuple): Optional query parameters
    
    Returns:
        pd.DataFrame or None
    """
    conn = connect_db()
    if conn is None:
        return None

    try:
        cursor = conn.cursor()
        if query.strip().lower().startswith("select"):
            print("Executing SELECT query...")
            df = pd.read_sql_query(query, conn, params=params)
            return df
        else:
            cursor.execute(query, params or ())
            conn.commit()
            print("Query executed successfully.")
            return None
    except sqlite3.Error as e:
        print(f"SQL error: {e}")
        return None
    finally:
        close_connection(conn)