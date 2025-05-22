import sqlite3
import pandas as pd
import os

# Connect to the database
db_path = os.path.join('data', 'data-dump-final.sqlite3')
conn = sqlite3.connect(db_path)

# List all tables
print("Database Tables:")
tables = pd.read_sql_query("SELECT name FROM sqlite_master WHERE type='table'", conn)
for table in tables['name']:
    print(f"- {table}")
    
    # Get table schema
    schema = pd.read_sql_query(f"PRAGMA table_info({table})", conn)
    print(f"  Columns: {', '.join(schema['name'])}")
    
    # Get row count
    count = pd.read_sql_query(f"SELECT COUNT(*) as count FROM {table}", conn)
    print(f"  Row count: {count['count'][0]}")
    
    # Print first few rows if there are any
    if count['count'][0] > 0:
        print("  Sample data:")
        data = pd.read_sql_query(f"SELECT * FROM {table} LIMIT 3", conn)
        print(data)
    
    print()

conn.close() 