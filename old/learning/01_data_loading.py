"""01 — Data loading and sanitization

Simple demo of loading course and room data with pandas. If CSVs are not present,
this script creates small sample dataframes and demonstrates normalization steps
used in the scheduler.
"""
import pandas as pd
import os


def main():
    print('01_data_loading: demo')
    base = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    sample_course = os.path.join(base, 'data', 'courses_sample.csv')
    if os.path.exists(sample_course):
        df = pd.read_csv(sample_course)
    else:
        df = pd.DataFrame([
            {'course_id': 'CS101', 'department': 'CSE', 'semester': 3, 'instances': 2},
            {'course_id': 'CS102', 'department': 'CSE', 'semester': 4, 'instances': 1},
        ])
    print('\nCourses (head):')
    print(df.head())

    # Basic sanitization example
    required_cols = ['course_id', 'department', 'semester']
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        print('Warning: missing columns:', missing)
    else:
        df['semester'] = df['semester'].astype(int)
        print('\nSanitized: semesters ->', df['semester'].tolist())

if __name__ == '__main__':
    main()

