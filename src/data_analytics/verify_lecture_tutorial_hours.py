#!/usr/bin/env python3
"""
Verify lecture and tutorial hours from theory scheduling output.

This script verifies that all courses have been assigned the correct number of lecture
and tutorial hours according to their requirements. It analyzes the theory scheduler
output files and compares them against the original course requirements.
"""

import pandas as pd
import os
import json
from collections import defaultdict
import matplotlib.pyplot as plt
from datetime import datetime

def verify_lecture_tutorial_hours(theory_schedule_file=None, course_file=None):
    """
    Verify that lecture and tutorial hours requirements are satisfied for all courses.
    
    Parameters:
    -----------
    theory_schedule_file : str, optional
        Path to theory schedule CSV or JSON file. If None, will try to find the latest.
    course_file : str, optional
        Path to course requirements CSV file. Defaults to 'data/cse.csv'.
    
    Returns:
    --------
    bool
        True if verification process completed, False if critical errors occurred.
    """
    # Setup default file paths
    if course_file is None:
        course_file = "data/department_data/Computing_main.csv"
    
    if not os.path.exists(course_file):
        print(f"Course file not found: {course_file}")
        return False
    
    print(f"Using course file: {course_file}")
    courses_df = pd.read_csv(course_file)
    
    # Find or use provided theory schedule file
    if theory_schedule_file is None:
        # Find the latest theory schedule
        output_dir = "output"
        if not os.path.exists(output_dir):
            print("No output directory found!")
            return False
        
        # Find theory schedule folders
        theory_schedule_folders = [f for f in os.listdir(output_dir) if f.startswith("theory_schedule_")]
        combined_schedule_folders = [f for f in os.listdir(output_dir) if f.startswith("combined_schedule_")]
        
        if not theory_schedule_folders and not combined_schedule_folders:
            print("No theory or combined schedule folders found!")
            return False
        
        # Get latest schedules
        latest_theory_folder = max(theory_schedule_folders) if theory_schedule_folders else None
        latest_combined_folder = max(combined_schedule_folders) if combined_schedule_folders else None
        
        print(f"Latest theory schedule folder: {latest_theory_folder}")
        print(f"Latest combined schedule folder: {latest_combined_folder}")
        
        # Try to load theory schedule
        theory_schedule_df = None
        
        # First try individual theory folder
        if latest_theory_folder:
            theory_schedule_file = os.path.join(output_dir, latest_theory_folder, "theory_schedule.csv")
            if os.path.exists(theory_schedule_file):
                theory_schedule_df = pd.read_csv(theory_schedule_file)
                print(f"Loaded theory schedule with {len(theory_schedule_df)} assignments")
            else:
                # Try JSON version
                theory_schedule_file = os.path.join(output_dir, latest_theory_folder, "theory_schedule.json")
                if os.path.exists(theory_schedule_file):
                    with open(theory_schedule_file, 'r') as f:
                        theory_schedule_data = json.load(f)
                    theory_schedule_df = pd.DataFrame(theory_schedule_data)
                    print(f"Loaded theory schedule from JSON with {len(theory_schedule_df)} assignments")
        
        # If not found, try combined folder
        if theory_schedule_df is None and latest_combined_folder:
            combined_theory_file = os.path.join(output_dir, latest_combined_folder,"combined_theory_schedule.csv")
            if os.path.exists(combined_theory_file):
                theory_schedule_df = pd.read_csv(combined_theory_file)
                print(f"Loaded combined theory schedule with {len(theory_schedule_df)} assignments")
            else:
                # Try JSON version
                combined_theory_file = os.path.join(output_dir, latest_combined_folder,"combined_theory_schedule.json")
                if os.path.exists(combined_theory_file):
                    with open(combined_theory_file, 'r') as f:
                        theory_schedule_data = json.load(f)
                    theory_schedule_df = pd.DataFrame(theory_schedule_data)
                    print(f"Loaded combined theory schedule from JSON with {len(theory_schedule_df)} assignments")
    else:
        # Use provided file path
        if os.path.exists(theory_schedule_file):
            if theory_schedule_file.endswith('.csv'):
                theory_schedule_df = pd.read_csv(theory_schedule_file)
            elif theory_schedule_file.endswith('.json'):
                with open(theory_schedule_file, 'r') as f:
                    theory_schedule_data = json.load(f)
                theory_schedule_df = pd.DataFrame(theory_schedule_data)
            print(f"Loaded theory schedule from provided path with {len(theory_schedule_df)} assignments")
        else:
            print(f"Theory schedule file not found: {theory_schedule_file}")
            return False
    
    # Verify we have theory schedule data
    if theory_schedule_df is None or theory_schedule_df.empty:
        print("No valid theory schedule data found!")
        return False
    
    print("=" * 85)
    print("LECTURE AND TUTORIAL HOURS VERIFICATION")
    print("=" * 85)
    
    # Create mapping of course requirements
    course_requirements = {}
    for _, row in courses_df.iterrows():
        instance_id = str(row['id'])
        course_dept = row.get('course_dept', 'Unknown')
        
        course_requirements[instance_id] = {
            'lecture_hours': row['lecture_hours'],
            'tutorial_hours': row['tutorial_hours'],
            'course_code': row['course_code'],
            'course_name': row['course_name'],
            'teacher_id': row['teacher_id'],
            'student_count': row['student_count'],
            'first_name': row.get('first_name', ''),
            'last_name': row.get('last_name', ''),
            'semester': row.get('semester', 'Unknown'),
            'course_dept': course_dept,
            'academic_year': row.get('academic_year', 'Unknown')
        }
    
    # Count scheduled hours per course instance
    scheduled_hours = defaultdict(lambda: {'lecture': 0, 'tutorial': 0})
    
    # Count theory assignments
    for _, row in theory_schedule_df.iterrows():
        try:
            instance_id = str(int(float(row['course_instance_id'])))
        except:
            instance_id = str(row['course_instance_id'])
        
        session_type = row.get('session_type', 'lecture').lower()
        
        if session_type in ['lecture', 'theory']:
            scheduled_hours[instance_id]['lecture'] += 1
        elif session_type in ['tutorial', 'tut']:
            scheduled_hours[instance_id]['tutorial'] += 1
    
    # Prepare to track verification results
    verification_results = []
    
    # Display header for verification results
    print(f"{'ID':<6} {'Course':<12} {'Teacher':<20} {'Sem':<4} {'L Req':<6} {'L Sch':<6} {'T Req':<6} {'T Sch':<6} {'Status':<25}")
    print("-" * 105)
    
    # Track statistics
    total_instances = 0
    violations = 0
    not_scheduled = 0
    lecture_hour_violations = 0
    tutorial_hour_violations = 0
    lecture_hour_excess = 0
    tutorial_hour_excess = 0
    
    # Process ALL instances with theory requirements from the course file
    for instance_id, requirements in sorted(course_requirements.items(), key=lambda x: int(x[0])):
        lecture_required = requirements['lecture_hours']
        tutorial_required = requirements['tutorial_hours']
        
        # Skip if no theory requirements
        if lecture_required == 0 and tutorial_required == 0:
            continue
        
        total_instances += 1
        
        course_code = requirements['course_code']
        course_name = requirements['course_name']
        teacher_id = requirements['teacher_id']
        teacher_name = f"{requirements['first_name']} {requirements['last_name']}".strip() or f"T{teacher_id}"
        semester = requirements['semester']
        
        lecture_scheduled = scheduled_hours[instance_id]['lecture']
        tutorial_scheduled = scheduled_hours[instance_id]['tutorial']
        
        # Determine status
        status = "✅ COMPLIANT"
        status_details = []
        is_compliant = True
        
        # Check if scheduled at all
        if lecture_scheduled == 0 and tutorial_scheduled == 0:
            status = "❌ NOT SCHEDULED"
            status_details.append("Not scheduled")
            is_compliant = False
            not_scheduled += 1
        else:
            # Check lecture hours
            if lecture_scheduled < lecture_required:
                status = "❌ VIOLATION"
                status_details.append(f"Missing {lecture_required - lecture_scheduled} lecture hours")
                is_compliant = False
                lecture_hour_violations += 1
            elif lecture_scheduled > lecture_required:
                status = "⚠️ EXCESS HOURS"
                status_details.append(f"Excess {lecture_scheduled - lecture_required} lecture hours")
                lecture_hour_excess += 1
            
            # Check tutorial hours
            if tutorial_scheduled < tutorial_required:
                status = "❌ VIOLATION"
                status_details.append(f"Missing {tutorial_required - tutorial_scheduled} tutorial hours")
                is_compliant = False
                tutorial_hour_violations += 1
            elif tutorial_scheduled > tutorial_required:
                status = "⚠️ EXCESS HOURS"
                status_details.append(f"Excess {tutorial_scheduled - tutorial_required} tutorial hours")
                tutorial_hour_excess += 1
        
        if not is_compliant:
            violations += 1
        
        # Combine status details
        status_text = status
        if status_details:
            status_text = f"{status} ({', '.join(status_details)})"
        
        # Print verification result
        print(f"{instance_id:<6} {course_code:<12} {teacher_name[:19]:<20} {semester:<4} "
              f"{lecture_required:<6} {lecture_scheduled:<6} {tutorial_required:<6} {tutorial_scheduled:<6} "
              f"{status_text:<25}")
        
        # Store result for reporting
        verification_results.append({
            'instance_id': instance_id,
            'course_code': course_code,
            'course_name': course_name,
            'teacher_id': teacher_id,
            'teacher_name': teacher_name,
            'semester': semester,
            'lecture_required': lecture_required,
            'lecture_scheduled': lecture_scheduled,
            'tutorial_required': tutorial_required,
            'tutorial_scheduled': tutorial_scheduled,
            'status': status,
            'status_details': status_details,
            'is_compliant': is_compliant
        })
    
    # Print summary
    print("=" * 105)
    print(f"VERIFICATION SUMMARY:")
    print(f"- Total courses with theory requirements: {total_instances}")
    print(f"- Compliant courses: {total_instances - violations} ({(total_instances - violations) / total_instances * 100:.1f}%)")
    print(f"- Violations: {violations} ({violations / total_instances * 100:.1f}%)")
    print(f"- Not scheduled: {not_scheduled} ({not_scheduled / total_instances * 100:.1f}%)")
    print(f"- Lecture hour violations: {lecture_hour_violations} ({lecture_hour_violations / total_instances * 100:.1f}%)")
    print(f"- Tutorial hour violations: {tutorial_hour_violations} ({tutorial_hour_violations / total_instances * 100:.1f}%)")
    
    # Generate visualization report
    if verification_results:
        generate_verification_report(verification_results)
    
    return True

def generate_verification_report(verification_results):
    """Generate visual report of lecture and tutorial hour verification."""
    output_dir = "output/verification_reports"
    os.makedirs(output_dir, exist_ok=True)
    
    # Convert results to DataFrame for easier analysis
    df = pd.DataFrame(verification_results)
    
    # Create report file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_file = os.path.join(output_dir, f"theory_hours_verification_{timestamp}.html")
    
    # Calculate compliance metrics
    total = len(df)
    compliant = df['is_compliant'].sum()
    violations = total - compliant
    
    # Create plot figures
    plt.figure(figsize=(12, 10))
    
    # Plot 1: Compliance pie chart
    plt.subplot(2, 2, 1)
    labels = ['Compliant', 'Non-compliant']
    sizes = [compliant, violations]
    colors = ['#4CAF50', '#F44336']
    plt.pie(sizes, labels=labels, colors=colors, autopct='%1.1f%%', startangle=90)
    plt.axis('equal')
    plt.title('Theory Hours Compliance')
    
    # Plot 2: Lecture hours compliance
    plt.subplot(2, 2, 2)
    lecture_status = ['Exact Match', 'Missing Hours', 'Excess Hours']
    lecture_counts = [
        len(df[(df['lecture_scheduled'] == df['lecture_required']) & (df['lecture_required'] > 0)]),
        len(df[df['lecture_scheduled'] < df['lecture_required']]),
        len(df[df['lecture_scheduled'] > df['lecture_required']])
    ]
    plt.bar(lecture_status, lecture_counts, color=['#4CAF50', '#F44336', '#FFC107'])
    plt.title('Lecture Hours Compliance')
    plt.ylabel('Number of Courses')
    plt.xticks(rotation=45)
    
    # Plot 3: Tutorial hours compliance
    plt.subplot(2, 2, 3)
    tutorial_status = ['Exact Match', 'Missing Hours', 'Excess Hours']
    tutorial_counts = [
        len(df[(df['tutorial_scheduled'] == df['tutorial_required']) & (df['tutorial_required'] > 0)]),
        len(df[df['tutorial_scheduled'] < df['tutorial_required']]),
        len(df[df['tutorial_scheduled'] > df['tutorial_required']])
    ]
    plt.bar(tutorial_status, tutorial_counts, color=['#4CAF50', '#F44336', '#FFC107'])
    plt.title('Tutorial Hours Compliance')
    plt.ylabel('Number of Courses')
    plt.xticks(rotation=45)
    
    # Plot 4: Compliance by semester
    plt.subplot(2, 2, 4)
    if 'semester' in df.columns:
        semester_compliance = df.groupby('semester')['is_compliant'].mean() * 100
        semester_compliance.plot(kind='bar', color='#2196F3')
        plt.title('Compliance Rate by Semester')
        plt.ylabel('Compliance Percentage')
        plt.xticks(rotation=45)
        plt.ylim(0, 100)
    
    plt.tight_layout()
    
    # Save the figure
    plt.savefig(os.path.join(output_dir, f"theory_hours_charts_{timestamp}.png"))
    
    # Generate HTML report
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write("""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Theory Hours Verification Report</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 20px; }
                h1, h2 { color: #333; }
                .summary { background-color: #f5f5f5; padding: 15px; border-radius: 5px; margin-bottom: 20px; }
                .charts { text-align: center; margin: 20px 0; }
                table { border-collapse: collapse; width: 100%; margin-top: 20px; }
                th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
                th { background-color: #f2f2f2; }
                tr:nth-child(even) { background-color: #f9f9f9; }
                .compliant { color: green; }
                .violation { color: red; }
                .warning { color: orange; }
            </style>
        </head>
        <body>
        """)
        
        # Add report header
        f.write(f"<h1>Theory Hours Verification Report</h1>")
        f.write(f"<p>Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>")
        
        # Add summary section
        f.write("<div class='summary'>")
        f.write("<h2>Summary</h2>")
        f.write(f"<p>Total courses with theory requirements: {total}</p>")
        f.write(f"<p>Compliant courses: {compliant} ({compliant/total*100:.1f}%)</p>")
        f.write(f"<p>Violations: {violations} ({violations/total*100:.1f}%)</p>")
        
        lecture_missing = len(df[df['lecture_scheduled'] < df['lecture_required']])
        tutorial_missing = len(df[df['tutorial_scheduled'] < df['tutorial_required']])
        not_scheduled = len(df[(df['lecture_scheduled'] == 0) & (df['tutorial_scheduled'] == 0)])
        
        f.write(f"<p>Not scheduled at all: {not_scheduled} ({not_scheduled/total*100:.1f}%)</p>")
        f.write(f"<p>Missing lecture hours: {lecture_missing} ({lecture_missing/total*100:.1f}%)</p>")
        f.write(f"<p>Missing tutorial hours: {tutorial_missing} ({tutorial_missing/total*100:.1f}%)</p>")
        f.write("</div>")
        
        # Add charts
        f.write("<div class='charts'>")
        f.write("<h2>Visualization</h2>")
        f.write(f"<img src='theory_hours_charts_{timestamp}.png' alt='Theory Hours Compliance Charts' style='max-width:100%;'>")
        f.write("</div>")
        
        # Add detailed results table
        f.write("<h2>Detailed Results</h2>")
        f.write("<table>")
        f.write("<tr><th>ID</th><th>Course</th><th>Teacher</th><th>Sem</th><th>Lecture Req</th><th>Lecture Sch</th>"
                "<th>Tutorial Req</th><th>Tutorial Sch</th><th>Status</th></tr>")
        
        for _, row in df.iterrows():
            status_class = "compliant" if row['is_compliant'] else "violation"
            if not row['is_compliant'] and "EXCESS" in row['status']:
                status_class = "warning"
                
            status_text = row['status']
            if row['status_details']:
                status_text += f" ({', '.join(row['status_details'])})"
                
            f.write(f"<tr>")
            f.write(f"<td>{row['instance_id']}</td>")
            f.write(f"<td>{row['course_code']}</td>")
            f.write(f"<td>{row['teacher_name']}</td>")
            f.write(f"<td>{row['semester']}</td>")
            f.write(f"<td>{row['lecture_required']}</td>")
            f.write(f"<td>{row['lecture_scheduled']}</td>")
            f.write(f"<td>{row['tutorial_required']}</td>")
            f.write(f"<td>{row['tutorial_scheduled']}</td>")
            f.write(f"<td class='{status_class}'>{status_text}</td>")
            f.write(f"</tr>")
        
        f.write("</table>")
        f.write("</body></html>")
    
    print(f"\nVerification report generated: {report_file}")
    return report_file

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Verify lecture and tutorial hours from theory scheduling output.')
    parser.add_argument('--theory-schedule', type=str, help='Path to theory schedule CSV or JSON file')
    parser.add_argument('--course-file', type=str, help='Path to course requirements CSV file')
    
    args = parser.parse_args()
    
    verify_lecture_tutorial_hours(args.theory_schedule, args.course_file)