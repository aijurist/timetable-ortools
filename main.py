from src.db import execute_query
import pandas as pd

def main():
    df = execute_query("SELECT * FROM rooms_room")
    
    if df is not None:
        print(df)
        df.to_csv("rooms.csv", index=False)
        print("Data exported to rooms.csv")

if __name__ == "__main__":
    main()