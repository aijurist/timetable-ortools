import sqlite3
import os
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("DB_PATH")

def connect_db():
    """Establish connection to the SQLite database"""
    db_path = os.path.abspath(DB_PATH)
    
    if not os.path.exists(db_path):
        print(f"ERROR: Database file not found at: {db_path}")
        print(f"Current working directory: {os.getcwd()}")
        return None
    
    try:
        conn = sqlite3.connect(db_path)
        print("Connected to the database successfully.")
        return conn
    except sqlite3.Error as e:
        print(f"Database connection error: {e}")
        return None
    
def close_connection(conn):
    """Close the database connection"""
    if conn:
        conn.close()