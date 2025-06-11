import os
import json
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import glob
from collections import defaultdict
import argparse

def load_lab_schedule(schedule_path):
    """Load lab schedule from JSON file."""
    with open(schedule_path, 'r') as f:
        schedule_data = json.load(f)
    return schedule_data

def analyze_group_course_distribution(schedule_data):
    """Analyze the distribution of courses across groups and create a matrix for the heatmap."""
    # Extract department-semester-group mapping
    dept_sem_groups = {}
    all_courses = {}  # Track all courses by dept, semester
    
    # First pass: collect all courses and groups by dept/semester
    for entry in schedule_data:
        dept = entry.get('department', 'Unknown')
        semester = entry.get('semester', 0)
        group_index = entry.get('group_index', 0)
        course_code = entry.get('course_code', '')
        
        if (dept, semester) not in dept_sem_groups:
            dept_sem_groups[(dept, semester)] = set()
            all_courses[(dept, semester)] = set()
            
        dept_sem_groups[(dept, semester)].add(group_index)
        all_courses[(dept, semester)].add(course_code)
    
    # Process each department-semester combination separately
    results = {}
    for (dept, semester), groups in dept_sem_groups.items():
        # Skip if there are no groups or only one group
        if len(groups) <= 1:
            continue
            
        # Get all courses for this dept/semester
        course_set = all_courses[(dept, semester)]
        group_list = sorted(list(groups))
        course_list = sorted(list(course_set))
        
        # Create empty DataFrame with all groups and all courses
        # This ensures all courses appear even if they don't have instances in some groups
        df = pd.DataFrame(0, index=group_list, columns=course_list)
        
        # Count course instances in each group
        for entry in schedule_data:
            if entry.get('department') == dept and entry.get('semester') == semester:
                course_code = entry.get('course_code')
                group_idx = entry.get('group_index')
                
                if course_code in course_list and group_idx in group_list:
                    # Increment instance count for this course in this group
                    df.loc[group_idx, course_code] = df.loc[group_idx, course_code] + 1
        
        # Convert DataFrame to numeric values (important for heatmap)
        df = df.astype(int)
        
        # Store the result
        results[(dept, semester)] = df
    
    return results

def generate_heatmaps(distribution_data, output_dir):
    """Generate heatmaps for each department-semester combination."""
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    # Generate a heatmap for each department-semester combination
    for (dept, semester), df in distribution_data.items():
        # Ensure data is numeric
        df = df.fillna(0)  # Replace any NaN with 0
        
        # Double-check that all values are numeric
        if not np.issubdtype(df.values.dtype, np.number):
            print(f"Warning: Non-numeric values detected for {dept} Semester {semester}")
            # Convert all values to integers, forcing conversion
            df = df.astype(float).fillna(0).astype(int)
        
        # Create figure
        plt.figure(figsize=(max(10, len(df.columns) * 1.5), max(8, len(df.index) * 0.8)))
        
        try:
            # Generate heatmap
            ax = sns.heatmap(df, annot=True, cmap="YlGnBu", fmt="d", linewidths=.5, cbar_kws={'label': 'Number of Course Instances'})
            
            # Configure plot
            plt.title(f"Course-Group Distribution for {dept} - Semester {semester}")
            plt.xlabel("Course Code")
            plt.ylabel("Group Index")
            plt.tight_layout()
            
            # Save the figure
            filename = f"{dept.replace(' ', '_')}_{semester}_group_course_heatmap.png"
            filepath = os.path.join(output_dir, filename)
            plt.savefig(filepath, dpi=300, bbox_inches='tight')
            plt.close()
            
            print(f"Generated heatmap for {dept} Semester {semester}: {filepath}")
        except Exception as e:
            print(f"Error generating heatmap for {dept} Semester {semester}: {e}")
            print(f"DataFrame shape: {df.shape}")
            print(f"DataFrame columns: {df.columns.tolist()}")
            print(f"DataFrame index: {df.index.tolist()}")
            print(f"DataFrame values:\n{df}")
            plt.close()
        
        # Also create a CSV file for the data
        csv_filename = f"{dept.replace(' ', '_')}_{semester}_group_course_distribution.csv"
        csv_filepath = os.path.join(output_dir, csv_filename)
        df.to_csv(csv_filepath)
        print(f"Saved distribution data to CSV: {csv_filepath}")

def analyze_overall_statistics(distribution_data, output_dir):
    """Generate overall statistics about the course-group distribution."""
    stats = {
        'dept_semester': [],
        'groups': [],
        'courses': [],
        'total_instances': [],
        'avg_instances_per_course': [],
        'courses_with_1_group': [],
        'courses_with_2_groups': [],
        'courses_with_3plus_groups': [],
        'distribution_coverage': []
    }
    
    for (dept, semester), df in distribution_data.items():
        stats['dept_semester'].append(f"{dept} - Sem {semester}")
        stats['groups'].append(len(df.index))
        stats['courses'].append(len(df.columns))
        
        # Calculate total instances
        total_instances = df.sum().sum()
        stats['total_instances'].append(total_instances)
        
        # Calculate average instances per course
        avg_instances = total_instances / len(df.columns) if len(df.columns) > 0 else 0
        stats['avg_instances_per_course'].append(round(avg_instances, 2))
        
        # Count how many courses appear in 1, 2, or 3+ groups
        course_group_counts = (df > 0).sum(axis=0)
        courses_with_1_group = (course_group_counts == 1).sum()
        courses_with_2_groups = (course_group_counts == 2).sum()
        courses_with_3plus_groups = (course_group_counts >= 3).sum()
        
        stats['courses_with_1_group'].append(courses_with_1_group)
        stats['courses_with_2_groups'].append(courses_with_2_groups)
        stats['courses_with_3plus_groups'].append(courses_with_3plus_groups)
        
        # Calculate distribution coverage (percentage of cells with instances)
        total_cells = len(df.index) * len(df.columns)
        filled_cells = (df > 0).sum().sum()
        coverage = (filled_cells / total_cells * 100) if total_cells > 0 else 0
        stats['distribution_coverage'].append(round(coverage, 2))
    
    # Create and save statistics DataFrame
    stats_df = pd.DataFrame(stats)
    stats_path = os.path.join(output_dir, 'group_course_distribution_statistics.csv')
    stats_df.to_csv(stats_path, index=False)
    print(f"Generated overall statistics: {stats_path}")
    
    # Create summary text file
    summary_path = os.path.join(output_dir, 'group_course_distribution_summary.txt')
    with open(summary_path, 'w') as f:
        f.write("Group-Course Distribution Analysis Summary\n")
        f.write("=========================================\n\n")
        
        f.write("Analyzed Department-Semester Combinations:\n")
        for i, dept_sem in enumerate(stats['dept_semester']):
            f.write(f"\n{dept_sem}:\n")
            f.write(f"  - Groups: {stats['groups'][i]}\n")
            f.write(f"  - Courses: {stats['courses'][i]}\n")
            f.write(f"  - Total course instances: {stats['total_instances'][i]}\n")
            f.write(f"  - Average instances per course: {stats['avg_instances_per_course'][i]}\n")
            f.write(f"  - Courses in 1 group: {stats['courses_with_1_group'][i]} ({stats['courses_with_1_group'][i]/stats['courses'][i]*100:.1f}%)\n")
            f.write(f"  - Courses in 2 groups: {stats['courses_with_2_groups'][i]} ({stats['courses_with_2_groups'][i]/stats['courses'][i]*100:.1f}%)\n")
            f.write(f"  - Courses in 3+ groups: {stats['courses_with_3plus_groups'][i]} ({stats['courses_with_3plus_groups'][i]/stats['courses'][i]*100:.1f}%)\n")
            f.write(f"  - Distribution coverage: {stats['distribution_coverage'][i]}%\n")
        
        # Overall summary
        f.write("\nOverall Summary:\n")
        f.write(f"  - Total department-semester combinations: {len(stats['dept_semester'])}\n")
        f.write(f"  - Average groups per combination: {sum(stats['groups'])/len(stats['groups']):.2f}\n")
        f.write(f"  - Average courses per combination: {sum(stats['courses'])/len(stats['courses']):.2f}\n")
        f.write(f"  - Average distribution coverage: {sum(stats['distribution_coverage'])/len(stats['distribution_coverage']):.2f}%\n")
        
        # Constraint analysis
        f.write("\nConstraint Analysis:\n")
        equal_count = sum(1 for i in range(len(stats['groups'])) if stats['groups'][i] == stats['courses'][i])
        f.write(f"  - Department-semesters with groups = courses: {equal_count} ({equal_count/len(stats['groups'])*100:.1f}%)\n")
        f.write(f"  - Department-semesters with courses in exactly 2 groups: {sum(1 for i in range(len(stats['courses'])) if stats['courses_with_2_groups'][i] == stats['courses'][i])}\n")
        f.write(f"  - Department-semesters with courses in at most 2 groups: {sum(1 for i in range(len(stats['courses'])) if stats['courses_with_3plus_groups'][i] == 0)}\n")
    
    print(f"Generated summary: {summary_path}")
    
    return stats_df

def generate_overall_visualizations(stats_df, output_dir):
    """Generate overall visualizations of the statistics."""
    # Generate a bar chart of group and course counts
    plt.figure(figsize=(12, 6))
    x = range(len(stats_df['dept_semester']))
    plt.bar(x, stats_df['groups'], width=0.4, label='Groups', alpha=0.7)
    plt.bar([i+0.4 for i in x], stats_df['courses'], width=0.4, label='Courses', alpha=0.7)
    plt.xticks([i+0.2 for i in x], stats_df['dept_semester'], rotation=90)
    plt.xlabel('Department-Semester')
    plt.ylabel('Count')
    plt.title('Number of Groups vs Number of Courses')
    plt.legend()
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, 'groups_vs_courses.png'), dpi=300, bbox_inches='tight')
    plt.close()
    
    # Generate a stacked bar chart of course distribution
    plt.figure(figsize=(12, 6))
    width = 0.8
    course_data = np.array([stats_df['courses_with_1_group'], 
                           stats_df['courses_with_2_groups'], 
                           stats_df['courses_with_3plus_groups']])
    bottom = np.zeros(len(stats_df['dept_semester']))
    
    colors = ['#FFC107', '#4CAF50', '#F44336']
    labels = ['In 1 Group', 'In 2 Groups', 'In 3+ Groups']
    
    for i, data in enumerate(course_data):
        plt.bar(x, data, width, bottom=bottom, label=labels[i], color=colors[i], alpha=0.7)
        bottom += data
    
    plt.xticks(x, stats_df['dept_semester'], rotation=90)
    plt.xlabel('Department-Semester')
    plt.ylabel('Number of Courses')
    plt.title('Course Distribution Across Groups')
    plt.legend()
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, 'course_distribution.png'), dpi=300, bbox_inches='tight')
    plt.close()
    
    # Generate a scatter plot of groups vs courses with ideal line
    plt.figure(figsize=(10, 8))
    plt.scatter(stats_df['courses'], stats_df['groups'], alpha=0.7, s=80)
    
    # Add ideal line (groups = courses)
    max_val = max(stats_df['courses'].max(), stats_df['groups'].max()) + 1
    plt.plot([0, max_val], [0, max_val], 'r--', label='Groups = Courses')
    
    plt.xlabel('Number of Courses')
    plt.ylabel('Number of Groups')
    plt.title('Groups vs Courses Relationship')
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, 'groups_courses_relationship.png'), dpi=300, bbox_inches='tight')
    plt.close()

def find_latest_lab_schedule():
    """Find the most recent lab schedule directory and JSON file."""
    output_dirs = glob.glob(os.path.join('output', 'lab_schedule_*'))
    if not output_dirs:
        return None
    
    # Sort by name (which includes timestamp) and get the latest
    latest_dir = sorted(output_dirs)[-1]
    json_path = os.path.join(latest_dir, 'lab_schedule.json')
    
    if os.path.exists(json_path):
        return json_path
    return None

def main():
    parser = argparse.ArgumentParser(description='Generate group-course distribution heatmaps from lab schedule.')
    parser.add_argument('--schedule', help='Path to lab schedule JSON file')
    parser.add_argument('--output-dir', help='Directory to save output files')
    args = parser.parse_args()
    
    # If no schedule provided, try to find the latest one
    schedule_path = args.schedule
    if not schedule_path:
        schedule_path = find_latest_lab_schedule()
        if not schedule_path:
            print("Error: No lab schedule found. Please provide a path to a lab schedule JSON file.")
            return
    
    # Determine output directory
    if args.output_dir:
        output_dir = args.output_dir
    else:
        # Create output directory in the same directory as the schedule
        schedule_dir = os.path.dirname(schedule_path)
        output_dir = os.path.join(schedule_dir, 'grouping_analysis')
    
    print(f"Loading lab schedule from {schedule_path}")
    schedule_data = load_lab_schedule(schedule_path)
    print(f"Loaded {len(schedule_data)} lab schedule entries")
    
    print("Analyzing group-course distribution...")
    distribution_data = analyze_group_course_distribution(schedule_data)
    print(f"Found {len(distribution_data)} department-semester combinations with multiple groups")
    
    print("Generating heatmaps...")
    generate_heatmaps(distribution_data, output_dir)
    
    print("Generating statistics...")
    stats_df = analyze_overall_statistics(distribution_data, output_dir)
    
    print("Generating overall visualizations...")
    generate_overall_visualizations(stats_df, output_dir)
    
    print(f"Analysis complete. Results saved to {output_dir}")

if __name__ == "__main__":
    main() 