import pandas as pd
import sys

def check_consistency(file_path):
    try:
        df = pd.read_csv(file_path)
    except Exception as e:
        print(f"Error reading file: {e}")
        return

    # Group by group_name
    groups = df.groupby('group_name')
    
    inconsistencies = []

    for group_name, group_df in groups:
        # Get unique sessions for this group
        # A session is defined by day and session_name (e.g., tuesday, L1)
        sessions = group_df[['day', 'session_name']].drop_duplicates()
        
        # Dictionary to store teacher sets for each session
        session_teachers = {}
        
        for index, row in sessions.iterrows():
            day = row['day']
            session_name = row['session_name']
            
            # Get teachers for this specific session
            teachers = group_df[
                (group_df['day'] == day) & 
                (group_df['session_name'] == session_name)
            ]['teacher_name'].unique()
            
            # Sort to ensure tuple comparison works irrespective of order
            teacher_set = tuple(sorted(teachers))
            session_key = f"{day} {session_name}"
            session_teachers[session_key] = teacher_set

        # Check if all sessions have the same set of teachers
        if not session_teachers:
            continue
            
        first_session = list(session_teachers.keys())[0]
        reference_teachers = session_teachers[first_session]
        
        group_issues = []
        for session, teachers in session_teachers.items():
            if teachers != reference_teachers:
                group_issues.append((session, teachers))
        
        if group_issues:
            inconsistencies.append({
                'group': group_name,
                'reference_session': first_session,
                'reference_teachers': reference_teachers,
                'issues': group_issues
            })

    if inconsistencies:
        print(f"Found {len(inconsistencies)} groups with inconsistent teacher pairs:")
        print("-" * 50)
        for issue in inconsistencies:
            print(f"Group: {issue['group']}")
            print(f"  Reference ({issue['reference_session']}): {', '.join(issue['reference_teachers'])}")
            for session, teachers in issue['issues']:
                print(f"  Mismatch  ({session}): {', '.join(teachers)}")
            print("-" * 50)
    else:
        print("Consistency Check Passed: All lab groups have consistent teacher pairs across sessions.")

if __name__ == "__main__":
    file_path = r"d:\timetable-scheduler\data\sem2026\1st year\lab.csv"
    check_consistency(file_path)
