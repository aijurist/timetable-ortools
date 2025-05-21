# add basic utility functions such as preprocessing data

import pandas as pd
import numpy as np

df = pd.read_csv(r'C:\Users\ShanthoshS\OneDrive\Desktop\timetable_scheduler\data\rooms.csv', encoding="utf-8", on_bad_lines='skip')

count = df[df['block'] == 'Lab Block'].shape[0]
print(count)
