import pandas as pd

# Load the schedule
df = pd.read_csv('output/macroblock_schedule_20250601_000548/macroblock_schedule.csv')

# Filter for 5th semester Computer Science Engineering
cse_5 = df[(df['semester'] == 5) & (df['course_dept'] == 'Computer Science & Engineering')]

print("5th Semester Computer Science Engineering Courses:")
print("=" * 60)

if not cse_5.empty:
    for course in cse_5['course_code'].unique():
        course_name = cse_5[cse_5['course_code'] == course]['course_name'].iloc[0]
        teacher_count = cse_5[cse_5['course_code'] == course]['teacher_id'].nunique()
        macroblock_count = cse_5[cse_5['course_code'] == course]['macroblock'].nunique()
        print(f"{course}: {course_name}")
        print(f"  Teachers: {teacher_count}, Macroblocks: {macroblock_count}")
        print()
else:
    print("No 5th semester Computer Science Engineering courses found.")

print("\nAll 5th semester courses (any department):")
print("=" * 60)
sem_5 = df[df['semester'] == 5]
for course in sem_5['course_code'].unique():
    course_info = sem_5[sem_5['course_code'] == course].iloc[0]
    print(f"{course}: {course_info['course_name']} ({course_info['course_dept']})") 