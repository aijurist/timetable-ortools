# add basic utility functions such as preprocessing data

from src.utils import get_teacher_with_courses
import pandas as pd
import numpy as np

output = get_teacher_with_courses()
print(output)