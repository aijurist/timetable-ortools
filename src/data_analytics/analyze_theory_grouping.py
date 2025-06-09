#!/usr/bin/env python3
"""
Analyze theory schedule grouping patterns and visualize them as heat maps.

This script analyzes how theory courses are distributed across different groups
and visualizes the patterns using heat maps to identify scheduling patterns
and potential optimization opportunities.
"""

import os
import json
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from collections import defaultdict
import argparse
from datetime import datetime

def find_latest_theory_schedule():
    """Find the latest theory schedule file in the output directory."""
    output_dir = "output"
    
    # Find theory schedule folders
    theory_schedule_folders = [f for f in os.listdir(output_dir) if f.startswith("theory_schedule_")]
    combined_schedule_folders = [f for f in os.listdir(output_dir) if f.startswith("combined_schedule_")]
    
    if not theory_schedule_folders and not combined_schedule_folders:
        print("No theory or combined schedule folders found!")
        return None
    
    # Get latest schedules
    latest_theory_folder = max(theory_schedule_folders) if theory_schedule_folders else None
    latest_combined_folder = max(combined_schedule_folders) if combined_schedule_folders else None
    
    # Try to find theory schedule file
    if latest_theory_folder:
        theory_json_file = os.path.join(output_dir, latest_theory_folder, "theory_schedule.json")
        if os.path.exists(theory_json_file):
            return theory_json_file
    
    if latest_combined_folder:
        combined_theory_file = os.path.join(output_dir, latest_combined_folder, "theory_schedule", "theory_schedule.json")
        if os.path.exists(combined_theory_file):
            return combined_theory_file
    
    return None

def load_theory_schedule(file_path=None):
    """Load theory schedule data from a JSON file."""
    if not file_path:
        file_path = find_latest_theory_schedule()
        
    if not file_path or not os.path.exists(file_path):
        print(f"Theory schedule file not found: {file_path}")
        return None
    
    print(f"Loading theory schedule from: {file_path}")
    with open(file_path, 'r') as f:
        schedule_data = json.load(f)
    
    return pd.DataFrame(schedule_data)

def analyze_theory_grouping(theory_df):
    """Analyze how theory courses are distributed across groups."""
    if theory_df is None or theory_df.empty:
        print("No theory schedule data to analyze!")
        return None
    
    # Extract group and course information
    required_columns = ['course_code', 'group_name', 'group_index', 'group_semester']
    missing_columns = [col for col in required_columns if col not in theory_df.columns]
    
    if missing_columns:
        print(f"Missing required columns: {missing_columns}")
        # Try to find alternative columns
        if 'course_code' in missing_columns and 'course_id' in theory_df.columns:
            theory_df['course_code'] = theory_df['course_id']
        if 'group_name' in missing_columns:
            # Try to create group name from department and semester if available
            if 'department' in theory_df.columns and 'semester' in theory_df.columns:
                theory_df['group_name'] = theory_df['department'] + '_S' + theory_df['semester'].astype(str)
            else:
                theory_df['group_name'] = 'Unknown_Group'
        if 'group_index' in missing_columns:
            theory_df['group_index'] = 1
        if 'group_semester' in missing_columns and 'semester' in theory_df.columns:
            theory_df['group_semester'] = theory_df['semester']
    
    # Create a summary DataFrame of course-group distribution
    course_group_count = theory_df.groupby(['course_code', 'group_name']).size().unstack(fill_value=0)
    
    # Identify which department and semester each group belongs to
    group_info = {}
    for _, row in theory_df.drop_duplicates(['group_name']).iterrows():
        group_info[row['group_name']] = {
            'semester': row.get('group_semester', row.get('semester', 'Unknown')),
            'department': row.get('department', 'Unknown')
        }
    
    # Count session types if available
    session_type_distribution = None
    if 'session_type' in theory_df.columns:
        session_type_distribution = theory_df.groupby(['course_code', 'session_type']).size().unstack(fill_value=0)
    
    # Analyze course distribution by semester
    semester_distribution = theory_df.groupby(['group_semester', 'course_code']).size().unstack(fill_value=0)
    
    return {
        'course_group_count': course_group_count,
        'group_info': group_info,
        'session_type_distribution': session_type_distribution,
        'semester_distribution': semester_distribution,
        'theory_df': theory_df
    }

def create_course_group_heatmap(analysis_results, output_dir=None):
    """Create a heat map visualization of course-group distribution."""
    if not analysis_results or 'course_group_count' not in analysis_results:
        print("No analysis results to visualize!")
        return
    
    # Setup output directory
    if not output_dir:
        output_dir = os.path.join("output", "analysis_results")
    os.makedirs(output_dir, exist_ok=True)
    
    course_group_count = analysis_results['course_group_count']
    
    # Create course-group heatmap
    plt.figure(figsize=(14, 10))
    
    # Use a custom colormap for better visualization
    cmap = sns.color_palette("YlOrRd", as_cmap=True)
    
    # Plot heatmap
    ax = sns.heatmap(course_group_count, cmap=cmap, linewidths=0.5, linecolor='gray',
                     cbar_kws={'label': 'Number of Sessions'})
    
    # Set title and labels
    plt.title('Theory Course Distribution Across Groups', fontsize=16, pad=20)
    plt.xlabel('Groups', fontsize=12)
    plt.ylabel('Courses', fontsize=12)
    
    # Rotate x-axis labels for better readability
    plt.xticks(rotation=45, ha='right')
    plt.yticks(rotation=0)
    
    # Adjust layout
    plt.tight_layout()
    
    # Save the figure
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(output_dir, f"theory_group_heatmap_{timestamp}.png")
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"Saved heat map to: {output_file}")
    
    return output_file

def create_session_type_heatmap(analysis_results, output_dir=None):
    """Create a heat map of lecture vs tutorial distribution by course."""
    if (not analysis_results or 
        'session_type_distribution' not in analysis_results or 
        analysis_results['session_type_distribution'] is None):
        print("No session type data available for visualization!")
        return
    
    # Setup output directory
    if not output_dir:
        output_dir = os.path.join("output", "analysis_results")
    os.makedirs(output_dir, exist_ok=True)
    
    session_type_dist = analysis_results['session_type_distribution']
    
    # Create lecture vs tutorial heatmap
    plt.figure(figsize=(12, 10))
    
    # Use a custom colormap 
    cmap = sns.color_palette("viridis", as_cmap=True)
    
    # Plot heatmap
    ax = sns.heatmap(session_type_dist, cmap=cmap, linewidths=0.5, linecolor='gray',
                   cbar_kws={'label': 'Number of Sessions'})
    
    # Set title and labels
    plt.title('Lecture vs Tutorial Distribution by Course', fontsize=16, pad=20)
    plt.xlabel('Session Type', fontsize=12)
    plt.ylabel('Courses', fontsize=12)
    
    # Adjust layout
    plt.tight_layout()
    
    # Save the figure
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(output_dir, f"session_type_heatmap_{timestamp}.png")
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"Saved session type heat map to: {output_file}")
    
    return output_file

def create_semester_course_heatmap(analysis_results, output_dir=None):
    """Create a heat map of course distribution by semester."""
    if not analysis_results or 'semester_distribution' not in analysis_results:
        print("No semester distribution data available!")
        return
    
    # Setup output directory
    if not output_dir:
        output_dir = os.path.join("output", "analysis_results")
    os.makedirs(output_dir, exist_ok=True)
    
    semester_dist = analysis_results['semester_distribution']
    
    # Create semester-course heatmap
    plt.figure(figsize=(14, 8))
    
    # Use a sequential colormap
    cmap = sns.color_palette("Blues", as_cmap=True)
    
    # Plot heatmap
    ax = sns.heatmap(semester_dist, cmap=cmap, linewidths=0.5, linecolor='gray',
                   cbar_kws={'label': 'Number of Sessions'})
    
    # Set title and labels
    plt.title('Course Distribution by Semester', fontsize=16, pad=20)
    plt.xlabel('Courses', fontsize=12)
    plt.ylabel('Semester', fontsize=12)
    
    # Rotate x-axis labels for better readability
    plt.xticks(rotation=45, ha='right')
    
    # Adjust layout
    plt.tight_layout()
    
    # Save the figure
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(output_dir, f"semester_course_heatmap_{timestamp}.png")
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"Saved semester course heat map to: {output_file}")
    
    return output_file

def analyze_group_uniqueness(analysis_results, output_dir=None):
    """Analyze how unique each group's course composition is."""
    if not analysis_results or 'course_group_count' not in analysis_results:
        print("No analysis results for group uniqueness!")
        return
    
    # Setup output directory
    if not output_dir:
        output_dir = os.path.join("output", "analysis_results")
    os.makedirs(output_dir, exist_ok=True)
    
    course_group_count = analysis_results['course_group_count']
    
    # Convert to binary presence/absence matrix
    presence_matrix = (course_group_count > 0).astype(int)
    
    # Calculate similarity between groups (Jaccard similarity)
    num_groups = presence_matrix.shape[1]
    similarity_matrix = np.zeros((num_groups, num_groups))
    
    for i in range(num_groups):
        for j in range(num_groups):
            group1 = presence_matrix.iloc[:, i]
            group2 = presence_matrix.iloc[:, j]
            
            # Jaccard similarity: intersection / union
            intersection = (group1 & group2).sum()
            union = (group1 | group2).sum()
            
            # Avoid division by zero
            if union > 0:
                similarity_matrix[i, j] = intersection / union
            else:
                similarity_matrix[i, j] = 0
    
    # Convert to DataFrame with group names
    similarity_df = pd.DataFrame(
        similarity_matrix,
        index=presence_matrix.columns,
        columns=presence_matrix.columns
    )
    
    # Create similarity heatmap
    plt.figure(figsize=(12, 10))
    
    # Use a custom colormap
    cmap = sns.color_palette("coolwarm", as_cmap=True)
    
    # Plot heatmap
    ax = sns.heatmap(similarity_df, cmap=cmap, vmin=0, vmax=1, 
                   linewidths=0.5, linecolor='gray',
                   cbar_kws={'label': 'Jaccard Similarity'})
    
    # Set title and labels
    plt.title('Group Similarity Matrix (Jaccard Index)', fontsize=16, pad=20)
    plt.xlabel('Groups', fontsize=12)
    plt.ylabel('Groups', fontsize=12)
    
    # Rotate labels for better readability
    plt.xticks(rotation=45, ha='right')
    plt.yticks(rotation=0)
    
    # Adjust layout
    plt.tight_layout()
    
    # Save the figure
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(output_dir, f"group_similarity_heatmap_{timestamp}.png")
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"Saved group similarity heat map to: {output_file}")
    
    return output_file

def create_sem_dept_heatmaps(analysis_results, output_dir=None):
    """Create heatmaps showing course distribution across groups for each semester and department."""
    if not analysis_results or 'theory_df' not in analysis_results:
        print("No analysis results to visualize semester/department heatmaps!")
        return []
    
    # Setup output directory
    if not output_dir:
        output_dir = os.path.join("output", "analysis_results")
    os.makedirs(output_dir, exist_ok=True)
    
    theory_df = analysis_results['theory_df']
    group_info = analysis_results.get('group_info', {})
    
    # Get unique semester-department combinations
    sem_dept_combinations = set()
    for group_name, info in group_info.items():
        sem_dept_combinations.add((info.get('semester', 'Unknown'), info.get('department', 'Unknown')))
    
    output_files = []
    
    # Process each semester-department combination
    for semester, department in sem_dept_combinations:
        # Filter data for this semester and department
        groups_in_sem_dept = [group for group, info in group_info.items() 
                             if info.get('semester') == semester and info.get('department') == department]
        
        if not groups_in_sem_dept:
            continue
            
        # Filter dataframe for these groups
        sem_dept_df = theory_df[theory_df['group_name'].isin(groups_in_sem_dept)]
        
        if sem_dept_df.empty:
            continue
        
        # Count UNIQUE course instances per course-group combination
        # First, get unique course instances (not sessions)
        unique_instances = sem_dept_df.drop_duplicates(['course_instance_id', 'course_code', 'group_name'])
        
        # Now count course instances per course-group combination
        course_group_matrix = pd.crosstab(
            unique_instances['course_code'], 
            unique_instances['group_name'],
            dropna=False
        )
        
        # Create a more descriptive title
        sem_text = f"Semester {semester}" if semester != "Unknown" else "Unknown Semester"
        dept_text = department if department != "Unknown" else "Unknown Department"
        title = f"Course Instance Distribution - {dept_text} - {sem_text}"
        
        # Create the heatmap
        plt.figure(figsize=(12, max(8, len(course_group_matrix) * 0.4)))
        
        # Use a custom colormap
        cmap = sns.color_palette("YlOrRd", as_cmap=True)
        
        # Create heatmap with annotations (course instance counts)
        ax = sns.heatmap(
            course_group_matrix, 
            cmap=cmap,
            annot=True,  # Show values in cells
            fmt="d",     # Format as integers
            linewidths=0.5,
            linecolor='gray',
            cbar_kws={'label': 'Number of Course Instances'}
        )
        
        # Set title and labels
        plt.title(title, fontsize=16, pad=20)
        plt.xlabel('Groups', fontsize=12)
        plt.ylabel('Courses', fontsize=12)
        
        # Rotate x-axis labels for better readability
        plt.xticks(rotation=45, ha='right')
        plt.yticks(rotation=0)
        
        # Adjust layout
        plt.tight_layout()
        
        # Save the figure
        file_prefix = f"sem{semester}_{department.replace(' ', '_')}"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = os.path.join(output_dir, f"{file_prefix}_instance_heatmap_{timestamp}.png")
        plt.savefig(output_file, dpi=300, bbox_inches='tight')
        print(f"Saved {sem_text} - {dept_text} course instance heat map to: {output_file}")
        plt.close()
        
        output_files.append(output_file)
        
        # Print summary for verification
        print(f"\n{sem_text} - {dept_text} Summary:")
        total_instances = len(unique_instances)
        total_courses = len(course_group_matrix.index)
        print(f"  Total unique course instances: {total_instances}")
        print(f"  Total unique courses: {total_courses}")
        print(f"  Course instance distribution:")
        for course in course_group_matrix.index:
            course_total = course_group_matrix.loc[course].sum()
            print(f"    {course}: {course_total} instances")
    
    return output_files

def generate_html_report(analysis_results, output_files, output_dir=None):
    """Generate an HTML report with all analysis results and visualizations."""
    if not output_dir:
        output_dir = os.path.join("output", "analysis_results")
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_file = os.path.join(output_dir, f"theory_grouping_analysis_{timestamp}.html")
    
    theory_df = analysis_results.get('theory_df')
    course_group_count = analysis_results.get('course_group_count')
    group_info = analysis_results.get('group_info', {})
    
    # Create summary statistics
    total_courses = len(course_group_count.index) if course_group_count is not None else 0
    total_groups = len(course_group_count.columns) if course_group_count is not None else 0
    total_sessions = theory_df.shape[0] if theory_df is not None else 0
    
    # Calculate courses per group
    courses_per_group = {}
    if course_group_count is not None:
        for group in course_group_count.columns:
            courses_per_group[group] = course_group_count[group][course_group_count[group] > 0].count()
    
    # Get session type distribution
    session_types = {}
    if theory_df is not None and 'session_type' in theory_df.columns:
        session_types = theory_df['session_type'].value_counts().to_dict()
    
    # Get unique semester-department combinations
    sem_dept_combinations = set()
    for group_name, info in group_info.items():
        sem_dept_combinations.add((info.get('semester', 'Unknown'), info.get('department', 'Unknown')))
    
    # Create HTML report
    with open(report_file, 'w') as f:
        f.write("""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Theory Grouping Analysis Report</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 20px; }
                h1, h2, h3 { color: #333; }
                .summary { background-color: #f5f5f5; padding: 15px; border-radius: 5px; margin-bottom: 20px; }
                .visualization { text-align: center; margin: 30px 0; }
                .visualization img { max-width: 100%; border: 1px solid #ddd; border-radius: 5px; }
                table { border-collapse: collapse; width: 100%; margin: 20px 0; }
                th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
                th { background-color: #f2f2f2; }
                tr:nth-child(even) { background-color: #f9f9f9; }
                .metric { font-weight: bold; color: #2196F3; }
                .sem-dept-section { margin-top: 30px; padding: 15px; background-color: #f9f9f9; border-radius: 5px; }
            </style>
        </head>
        <body>
        """)
        
        # Add report header
        f.write(f"<h1>Theory Grouping Analysis Report</h1>")
        f.write(f"<p>Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>")
        
        # Add summary section
        f.write("<div class='summary'>")
        f.write("<h2>Summary</h2>")
        f.write(f"<p>Total theory sessions: <span class='metric'>{total_sessions}</span></p>")
        f.write(f"<p>Unique courses: <span class='metric'>{total_courses}</span></p>")
        f.write(f"<p>Total groups: <span class='metric'>{total_groups}</span></p>")
        f.write(f"<p>Semester-Department combinations: <span class='metric'>{len(sem_dept_combinations)}</span></p>")
        
        if session_types:
            f.write("<h3>Session Type Distribution</h3>")
            f.write("<ul>")
            for session_type, count in session_types.items():
                f.write(f"<li>{session_type}: <span class='metric'>{count}</span> sessions</li>")
            f.write("</ul>")
        
        f.write("</div>")
        
        # Add group summary
        if courses_per_group:
            f.write("<h2>Group Summary</h2>")
            f.write("<table>")
            f.write("<tr><th>Group</th><th>Semester</th><th>Department</th><th>Courses</th></tr>")
            
            for group, count in sorted(courses_per_group.items(), key=lambda x: x[1], reverse=True):
                semester = group_info.get(group, {}).get('semester', 'Unknown')
                department = group_info.get(group, {}).get('department', 'Unknown')
                f.write(f"<tr><td>{group}</td><td>{semester}</td><td>{department}</td><td>{count}</td></tr>")
            
            f.write("</table>")
        
        # Organize visualizations by type
        f.write("<h2>Visualizations</h2>")
        
        # First add global visualizations
        global_visualizations = [file for file in output_files if file and not any(f"sem{s}_{d.replace(' ', '_')}_instance_heatmap" in file for s, d in sem_dept_combinations)]
        
        if global_visualizations:
            f.write("<h3>Global Analysis</h3>")
            for file_path in global_visualizations:
                if file_path:
                    file_name = os.path.basename(file_path)
                    title = file_name.replace('_', ' ').replace('.png', '').title()
                    
                    f.write("<div class='visualization'>")
                    f.write(f"<h4>{title}</h4>")
                    f.write(f"<img src='{os.path.relpath(file_path, output_dir)}' alt='{title}'>")
                    f.write("</div>")
        
        # Then add semester-department specific visualizations in their own sections
        sem_dept_visualizations = [file for file in output_files if file and any(f"sem{s}_{d.replace(' ', '_')}_instance_heatmap" in file for s, d in sem_dept_combinations)]
        
        if sem_dept_visualizations:
            f.write("<h3>Semester and Department Specific Analysis</h3>")
            
            # Group by semester-department
            for semester, department in sorted(sem_dept_combinations):
                sem_text = f"Semester {semester}" if semester != "Unknown" else "Unknown Semester"
                dept_text = department if department != "Unknown" else "Unknown Department"
                
                section_files = [file for file in sem_dept_visualizations 
                               if f"sem{semester}_{department.replace(' ', '_')}_instance_heatmap" in file]
                
                if section_files:
                    f.write(f"<div class='sem-dept-section'>")
                    f.write(f"<h4>{dept_text} - {sem_text}</h4>")
                    
                    for file_path in section_files:
                        if file_path:
                            file_name = os.path.basename(file_path)
                            title = "Course-Group Distribution"
                            
                            f.write("<div class='visualization'>")
                            f.write(f"<p>This heatmap shows the distribution of courses across groups with course instance counts displayed in each cell.</p>")
                            f.write(f"<img src='{os.path.relpath(file_path, output_dir)}' alt='{title}'>")
                            f.write("</div>")
                    
                    f.write("</div>")
        
        # Add course distribution table
        if course_group_count is not None:
            f.write("<h2>Course-Group Distribution</h2>")
            f.write("<p>Number of sessions for each course in each group:</p>")
            
            # Convert DataFrame to HTML table
            course_table_html = course_group_count.to_html(classes='dataframe')
            f.write(course_table_html)
        
        f.write("</body></html>")
    
    print(f"\nHTML report generated: {report_file}")
    return report_file

def main():
    parser = argparse.ArgumentParser(description='Analyze theory schedule grouping patterns.')
    parser.add_argument('--theory-schedule', type=str, help='Path to theory schedule JSON file')
    parser.add_argument('--output-dir', type=str, default=None, help='Directory to save output visualizations')
    
    args = parser.parse_args()
    
    # Load theory schedule data
    theory_df = load_theory_schedule(args.theory_schedule)
    
    if theory_df is not None:
        # Perform analysis
        analysis_results = analyze_theory_grouping(theory_df)
        
        if analysis_results:
            output_dir = args.output_dir or os.path.join("output", "analysis_results")
            os.makedirs(output_dir, exist_ok=True)
            
            # Generate visualizations
            output_files = []
            output_files.append(create_course_group_heatmap(analysis_results, output_dir))
            output_files.append(create_session_type_heatmap(analysis_results, output_dir))
            output_files.append(create_semester_course_heatmap(analysis_results, output_dir))
            output_files.append(analyze_group_uniqueness(analysis_results, output_dir))
            
            # Generate semester/department specific heatmaps
            sem_dept_files = create_sem_dept_heatmaps(analysis_results, output_dir)
            output_files.extend(sem_dept_files)
            
            # Generate HTML report
            generate_html_report(analysis_results, output_files, output_dir)
            
            print("\nAnalysis completed successfully!")
            return True
    
    print("Analysis failed. Please check the input data.")
    return False

if __name__ == "__main__":
    main()