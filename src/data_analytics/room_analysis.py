import pandas as pd 
import numpy as np

import os
import sys

df = pd.read_csv(r"C:\Users\ShanthoshS\OneDrive\Desktop\timetable_scheduler\rooms.csv")
df = df[df['description'] == 'Classroom']
print(df['room_max_cap'].sum())