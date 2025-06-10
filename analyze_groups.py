import json
import os
import glob

# Find the most recent output directory
output_dirs = glob.glob('output/lab_schedule_*')
latest_output = max(output_dirs, key=os.path.getctime)

print(f"Analyzing schedule in: {latest_output}")

# Load the schedule data
with open(f'{latest_output}/lab_schedule.json', 'r') as f:
    data = json.load(f)

# Group analysis
groups = {}
for item in data:
    group = item.get('group_name', 'Unknown')
    day = item.get('day', 'Unknown')
    session = item.get('session_name', 'Unknown')
    
    if group not in groups:
        groups[group] = {}
    
    if day not in groups[group]:
        groups[group][day] = {}
    
    if session not in groups[group][day]:
        groups[group][day][session] = []
    
    course_code = item.get('course_code', 'Unknown')
    groups[group][day][session].append(course_code)

# Print group stats
print("\n===== GROUP STATS =====")
for group, days in groups.items():
    if group != 'Unknown':
        slot_count = sum(len(sessions) for sessions in days.values())
        day_count = len(days)
        
        # Calculate sessions per day
        sessions_per_day = {day: len(sessions) for day, sessions in days.items()}
        
        # Count how many courses run in parallel
        parallel_sessions = []
        for day, sessions in days.items():
            for session, courses in sessions.items():
                if len(courses) > 1:
                    parallel_sessions.append((day, session, len(courses)))
        
        print(f"\nGroup: {group}")
        print(f"  Total time slots used: {slot_count}")
        print(f"  Days scheduled: {day_count}")
        print(f"  Sessions per day: {sessions_per_day}")
        print(f"  Parallel sessions: {len(parallel_sessions)}")
        
        # Print details of parallel sessions
        if parallel_sessions:
            print("  Parallel course details:")
            for day, session, count in parallel_sessions:
                courses = groups[group][day][session]
                print(f"    {day} {session}: {count} courses - {', '.join(courses)}")

print("\n===== OVERALL STATS =====")
total_labs = len(data)
unique_groups = sum(1 for group in groups.keys() if group != 'Unknown')
max_slots_per_group = max([sum(len(sessions) for sessions in days.values()) 
                         for group, days in groups.items() if group != 'Unknown'], default=0)
parallel_total = sum(len(courses) - 1 for group, days in groups.items() if group != 'Unknown'
                  for day, sessions in days.items() for session, courses in sessions.items() if len(courses) > 1)

print(f"Total lab assignments: {total_labs}")
print(f"Unique groups: {unique_groups}")
print(f"Maximum slots used by any group: {max_slots_per_group}")
print(f"Total parallel course instances: {parallel_total}")

# Optimization stats
print("\n===== OPTIMIZATION EFFICIENCY =====")
# Count instances that are scheduled in parallel within the same group
parallel_instances = sum(len(courses) for group, days in groups.items() if group != 'Unknown'
                      for day, sessions in days.items() for session, courses in sessions.items() if len(courses) > 1)
parallel_pct = (parallel_instances / total_labs) * 100 if total_labs > 0 else 0

# Count groups that stay within the 4-slot limit
groups_within_limit = sum(1 for group, days in groups.items() if group != 'Unknown' 
                        and sum(len(sessions) for sessions in days.values()) <= 4)
groups_pct = (groups_within_limit / unique_groups) * 100 if unique_groups > 0 else 0

print(f"Courses scheduled in parallel: {parallel_instances}/{total_labs} ({parallel_pct:.1f}%)")
print(f"Groups within 4-slot limit: {groups_within_limit}/{unique_groups} ({groups_pct:.1f}%)")

if max_slots_per_group <= 4:
    print("\n✅ SUCCESS: All groups are within the 4-slot limit!")
else:
    print(f"\n❌ ISSUE: Some groups exceed the 4-slot limit (max: {max_slots_per_group})") 