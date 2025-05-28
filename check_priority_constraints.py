import pandas as pd

# Load the schedule and course data
df = pd.read_csv('output/macroblock_schedule_20250528_154519/macroblock_schedule.csv')
courses_df = pd.read_csv('data/mapped_data/computer_dept_teacher_courses.csv')

print('=== PRIORITY CONSTRAINT VERIFICATION ===')
print()

# Find priority courses (4L, 3L+1T, 2L+2T)
priority_courses = courses_df[
    (courses_df['lecture_hours'] == 4) | 
    ((courses_df['lecture_hours'] == 3) & (courses_df['tutorial_hours'] == 1)) | 
    ((courses_df['lecture_hours'] == 2) & (courses_df['tutorial_hours'] == 2))
]

print(f'Priority courses (4L, 3L+1T, 2L+2T): {len(priority_courses)} instances')
print()

extended_blocks = ['a1', 'a2', 'b1', 'b2', 'c1', 'c2']
violations = 0

for _, course in priority_courses.iterrows():
    course_schedule = df[df['course_instance_id'] == str(course['id'])]
    if not course_schedule.empty:
        assigned_blocks = course_schedule['macroblock'].unique()
        main_blocks = [b for b in assigned_blocks if b in ['a1', 'a2', 'b1', 'b2', 'c1', 'c2', 'd1', 'd2', 'e1', 'e2', 'f1', 'f2', 'g1', 'g2']]
        priority_satisfied = all(block in extended_blocks for block in main_blocks)
        
        status = "✅ PRIORITY SATISFIED" if priority_satisfied else "❌ PRIORITY VIOLATED"
        if not priority_satisfied:
            violations += 1
            
        print(f'{course["course_code"]} ({course["lecture_hours"]}L+{course["tutorial_hours"]}T): {main_blocks} -> {status}')

print()
print(f'Priority constraint violations: {violations}')
print()

print('=== V1/V2 EXCLUSION VERIFICATION ===')
v1_v2_usage = df[df['macroblock'].isin(['v1', 'v2'])]
print(f'v1/v2 block usage: {len(v1_v2_usage)} assignments (should be 0)')

if len(v1_v2_usage) == 0:
    print('✅ v1 and v2 properly excluded from assignments')
else:
    print('❌ v1/v2 exclusion violated')
    print(v1_v2_usage[['course_code', 'macroblock', 'teacher_id']])

print()
print('=== COURSE HOUR SATISFACTION CHECK ===')
all_satisfied = True

for _, course in courses_df.iterrows():
    course_schedule = df[df['course_instance_id'] == str(course['id'])]
    if not course_schedule.empty:
        lecture_count = len(course_schedule[course_schedule['slot_type'] == 'Lecture'])
        tutorial_count = len(course_schedule[course_schedule['slot_type'] == 'Tutorial'])
        
        required_lectures = course['lecture_hours']
        required_tutorials = course['tutorial_hours']
        
        hours_satisfied = (lecture_count == required_lectures) and (tutorial_count == required_tutorials)
        
        if not hours_satisfied:
            all_satisfied = False
            print(f'❌ {course["course_code"]}: Required {required_lectures}L+{required_tutorials}T, Got {lecture_count}L+{tutorial_count}T')

if all_satisfied:
    print('✅ All course hour requirements satisfied')

print()
print('=== EXTENDED TUTORIAL BLOCK USAGE ===')
extended_tutorial_blocks = ['taa1', 'taa2', 'tbb1', 'tbb2', 'tcc1', 'tcc2']
extended_usage = df[df['macroblock'].isin(extended_tutorial_blocks)]

print(f'Extended tutorial blocks used: {len(extended_usage)} assignments')
if not extended_usage.empty:
    print('Extended tutorial usage by course:')
    for course_code in extended_usage['course_code'].unique():
        course_ext_usage = extended_usage[extended_usage['course_code'] == course_code]
        blocks_used = course_ext_usage['macroblock'].unique()
        print(f'  {course_code}: {list(blocks_used)}') 