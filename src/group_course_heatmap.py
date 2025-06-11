import os
import json
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import glob
from collections import defaultdict
import argparse

def load_courses_data(courses_csv_path):
    """Load courses data from CSV file."""
    try:
        courses_df = pd.read_csv(courses_csv_path)
        print(f"Loaded courses data: {len(courses_df)} course instances")
        return courses_df
    except Exception as e:
        print(f"Error loading courses data: {e}")
        return None

def load_lab_schedule(schedule_path):
    """Load lab schedule from JSON file."""
    try:
        with open(schedule_path, 'r') as f:
            schedule_data = json.load(f)
        return schedule_data
    except Exception as e:
        print(f"Error loading lab schedule: {e}")
        return None

def analyze_complete_group_course_distribution(courses_df, lab_schedule_data=None):
    """Analyze the distribution of ALL courses (theory + lab) across groups."""
    print("Analyzing complete group-course distribution...")
    
    # Create instance-group mapping from lab schedule if available
    instance_group_mapping = {}
    if lab_schedule_data:
        for entry in lab_schedule_data:
            instance_id = str(entry.get('course_instance_id', ''))
            dept = entry.get('department', 'Unknown')
            semester = entry.get('semester', 0)
            group_index = entry.get('group_index', 0)
            
            instance_group_mapping[instance_id] = {
                'department': dept,
                'semester': semester,
                'group_index': group_index,
                'group_name': f"{dept}_S{semester}_G{group_index}"
            }
    
    # Group all course instances by department and semester
    dept_sem_groups = defaultdict(lambda: defaultdict(list))
    
    for _, row in courses_df.iterrows():
        instance_id = str(row['id'])
        course_code = row['course_code']
        course_name = row.get('course_name', '')
        teacher_id = row['teacher_id']
        practical_hours = int(row.get('practical_hours', 0))
        student_dept = row.get('student_dept', 'Computer Science & Engineering')
        semester = row.get('semester', 1)
        
        # Get group assignment from lab schedule or create default
        if instance_id in instance_group_mapping:
            group_info = instance_group_mapping[instance_id]
            dept = group_info['department']
            semester = group_info['semester']
            group_index = group_info['group_index']
        else:
            # For instances not in lab schedule (theory courses), assign to default groups
            dept = student_dept
            # Simple hashing-based group assignment for consistency
            group_index = (hash(f"{course_code}_{teacher_id}") % 5) + 1
        
        instance_data = {
            'id': instance_id,
            'course_code': course_code,
            'course_name': course_name,
            'teacher_id': teacher_id,
            'practical_hours': practical_hours,
            'is_lab_course': practical_hours > 0,
            'student_count': row.get('student_count', 70)
        }
        
        dept_sem_groups[(dept, semester)][group_index].append(instance_data)
    
    print(f"Found {len(dept_sem_groups)} department-semester combinations")
    
    # Analyze distribution for each department-semester
    distribution_results = {}
    
    for (dept, semester), groups in dept_sem_groups.items():
        print(f"\nAnalyzing {dept} Semester {semester}:")
        print(f"  Found {len(groups)} groups")
        
        # Build course-group matrix
        all_courses = set()
        for group_index, instances in groups.items():
            group_courses = [inst['course_code'] for inst in instances]
            all_courses.update(group_courses)
            print(f"    Group {group_index}: {len(instances)} instances, courses: {set(group_courses)}")
        
        # Create matrix for heatmap
        course_list = sorted(all_courses)
        group_indices = sorted(groups.keys())
        
        # Initialize matrix with zeros
        matrix = np.zeros((len(group_indices), len(course_list)), dtype=int)
        
        # Fill matrix with instance counts
        for i, group_index in enumerate(group_indices):
            instances = groups[group_index]
            course_counts = defaultdict(int)
            
            # Count instances per course in this group
            for inst in instances:
                course_counts[inst['course_code']] += 1
            
            for j, course_code in enumerate(course_list):
                matrix[i, j] = course_counts[course_code]
        
        # Separate theory and lab courses for analysis
        theory_courses = []
        lab_courses = []
        
        for course_code in course_list:
            # Check if this course has any lab instances
            has_lab_instances = False
            for group_instances in groups.values():
                for inst in group_instances:
                    if inst['course_code'] == course_code and inst['practical_hours'] > 0:
                        has_lab_instances = True
                        break
                if has_lab_instances:
                    break
            
            if has_lab_instances:
                lab_courses.append(course_code)
            else:
                theory_courses.append(course_code)
        
        distribution_results[(dept, semester)] = {
            'matrix': matrix,
            'course_list': course_list,
            'group_indices': group_indices,
            'groups_data': groups,
            'theory_courses': theory_courses,
            'lab_courses': lab_courses,
            'total_courses': len(course_list),
            'total_groups': len(group_indices),
            'total_instances': sum(len(instances) for instances in groups.values())
        }
        
        print(f"    Total courses: {len(course_list)} ({len(theory_courses)} theory + {len(lab_courses)} lab)")
        print(f"    Total instances: {distribution_results[(dept, semester)]['total_instances']}")
    
    return distribution_results

def generate_comprehensive_heatmaps(distribution_data, output_dir):
    """Generate comprehensive heatmaps for each department-semester combination."""
    print("Generating comprehensive heatmaps...")
    
    # Create output directory
    heatmap_dir = os.path.join(output_dir, 'group_course_heatmaps')
    os.makedirs(heatmap_dir, exist_ok=True)
    
    for (dept, semester), data in distribution_data.items():
        matrix = data['matrix']
        course_list = data['course_list']
        group_indices = data['group_indices']
        theory_courses = data['theory_courses']
        lab_courses = data['lab_courses']
        
        if matrix.size == 0:
            print(f"Skipping {dept} Semester {semester} - no data")
            continue
        
        print(f"Creating heatmap for {dept} Semester {semester}")
        
        # Create DataFrame for heatmap
        df = pd.DataFrame(
            matrix,
            index=[f"Group {i}" for i in group_indices],
            columns=course_list
        )
        
        # Ensure all values are numeric
        df = df.apply(pd.to_numeric, errors='coerce').fillna(0).astype(int)
        
        # Create figure with appropriate size
        fig_width = max(8, len(course_list) * 1.5)
        fig_height = max(6, len(group_indices) * 1.2)
        
        plt.figure(figsize=(fig_width, fig_height))
        
        # Create heatmap with instance counts in boxes
        ax = sns.heatmap(
            df, 
            annot=True, 
            cmap="YlGnBu", 
            fmt="d", 
            linewidths=0.5, 
            cbar_kws={'label': 'Number of Course Instances'},
            square=False,
            xticklabels=True,
            yticklabels=True
        )
        
        # Customize the plot
        plt.title(f'Course-Group Distribution for {dept} - Semester {semester}', 
                 fontsize=14, fontweight='bold', pad=20)
        plt.xlabel('Course Code', fontsize=12, fontweight='bold')
        plt.ylabel('Group Index', fontsize=12, fontweight='bold')
        
        # Color-code course labels by type (theory vs lab)
        x_labels = ax.get_xticklabels()
        for i, label in enumerate(x_labels):
            course_code = label.get_text()
            if course_code in theory_courses:
                label.set_color('blue')
                label.set_weight('bold')
            elif course_code in lab_courses:
                label.set_color('red')
                label.set_weight('bold')
        
        # Add legend for course types
        from matplotlib.patches import Patch
        legend_elements = []
        if theory_courses:
            legend_elements.append(Patch(facecolor='blue', label=f'Theory Courses ({len(theory_courses)})'))
        if lab_courses:
            legend_elements.append(Patch(facecolor='red', label=f'Lab Courses ({len(lab_courses)})'))
        
        if legend_elements:
            plt.legend(handles=legend_elements, loc='upper right', bbox_to_anchor=(1.15, 1))
        
        # Rotate x-axis labels for better readability
        plt.xticks(rotation=45, ha='right')
        plt.yticks(rotation=0)
        
        # Adjust layout
        plt.tight_layout()
        
        # Save the plot
        safe_dept_name = dept.replace(' ', '_').replace('&', 'and')
        filename = f"heatmap_{safe_dept_name}_S{semester}.png"
        filepath = os.path.join(heatmap_dir, filename)
        plt.savefig(filepath, dpi=300, bbox_inches='tight')
        print(f"Saved heatmap: {filename}")
        
        plt.close()

def generate_overall_statistics_comprehensive(distribution_data, output_dir):
    """Generate comprehensive overall statistics across all departments and semesters."""
    print("Generating comprehensive overall statistics...")
    
    # Collect comprehensive statistics
    all_stats = []
    
    for (dept, semester), data in distribution_data.items():
        matrix = data['matrix']
        course_list = data['course_list']
        group_indices = data['group_indices']
        theory_courses = data['theory_courses']
        lab_courses = data['lab_courses']
        total_instances = data['total_instances']
        
        # Calculate distribution metrics
        total_entries = matrix.sum()
        max_instances_per_cell = matrix.max()
        min_instances_per_cell = matrix.min()
        avg_instances_per_cell = matrix.mean()
        
        # Calculate course choice metrics
        courses_with_choice = 0
        for j, course_code in enumerate(course_list):
            groups_offering_course = (matrix[:, j] > 0).sum()
            if groups_offering_course > 1:
                courses_with_choice += 1
        
        choice_percentage = (courses_with_choice / len(course_list) * 100) if course_list else 0
        
        # Group balance metrics
        group_sizes = matrix.sum(axis=1)  # Total instances per group
        group_balance = (group_sizes.std() / group_sizes.mean() * 100) if group_sizes.mean() > 0 else 0
        
        all_stats.append({
            'Department': dept,
            'Semester': semester,
            'Total_Courses': len(course_list),
            'Theory_Courses': len(theory_courses),
            'Lab_Courses': len(lab_courses),
            'Total_Groups': len(group_indices),
            'Total_Instances': total_instances,
            'Max_Instances_Per_Cell': max_instances_per_cell,
            'Min_Instances_Per_Cell': min_instances_per_cell,
            'Avg_Instances_Per_Cell': round(avg_instances_per_cell, 2),
            'Courses_With_Choice': courses_with_choice,
            'Choice_Percentage': round(choice_percentage, 1),
            'Group_Balance_CV': round(group_balance, 1)
        })
    
    # Create DataFrame and save
    stats_df = pd.DataFrame(all_stats)
    
    if not stats_df.empty:
        # Save statistics CSV
        stats_path = os.path.join(output_dir, 'comprehensive_group_course_statistics.csv')
        stats_df.to_csv(stats_path, index=False)
        print(f"Saved comprehensive statistics: {stats_path}")
        
        # Generate visualizations
        generate_comprehensive_visualizations(stats_df, output_dir)
        
        # Print summary
        print("\nCOMPREHENSIVE STATISTICS SUMMARY:")
        print("=" * 50)
        for _, row in stats_df.iterrows():
            print(f"\n{row['Department']} Semester {row['Semester']}:")
            print(f"  Courses: {row['Total_Courses']} ({row['Theory_Courses']} theory + {row['Lab_Courses']} lab)")
            print(f"  Groups: {row['Total_Groups']}")
            print(f"  Total instances: {row['Total_Instances']}")
            print(f"  Student choice: {row['Choice_Percentage']}% ({row['Courses_With_Choice']}/{row['Total_Courses']} courses)")
            print(f"  Group balance (CV): {row['Group_Balance_CV']}%")
    
    return stats_df

def generate_comprehensive_visualizations(stats_df, output_dir):
    """Generate comprehensive visualization charts."""
    print("Creating comprehensive visualization charts...")
    
    # Create visualizations directory
    viz_dir = os.path.join(output_dir, 'comprehensive_visualizations')
    os.makedirs(viz_dir, exist_ok=True)
    
    # 1. Course Distribution Overview
    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    
    # Course types distribution
    ax1 = axes[0, 0]
    dept_sem_labels = [f"{row['Department']}\nS{row['Semester']}" for _, row in stats_df.iterrows()]
    x_pos = range(len(dept_sem_labels))
    
    theory_counts = stats_df['Theory_Courses']
    lab_counts = stats_df['Lab_Courses']
    
    ax1.bar(x_pos, theory_counts, label='Theory Courses', color='lightblue', alpha=0.8)
    ax1.bar(x_pos, lab_counts, bottom=theory_counts, label='Lab Courses', color='lightcoral', alpha=0.8)
    
    ax1.set_title('Course Distribution by Type', fontweight='bold')
    ax1.set_xlabel('Department-Semester')
    ax1.set_ylabel('Number of Courses')
    ax1.set_xticks(x_pos)
    ax1.set_xticklabels(dept_sem_labels, rotation=45, ha='right')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    
    # Instance distribution
    ax2 = axes[0, 1]
    ax2.bar(x_pos, stats_df['Total_Instances'], color='green', alpha=0.7)
    ax2.set_title('Total Course Instances', fontweight='bold')
    ax2.set_xlabel('Department-Semester')
    ax2.set_ylabel('Number of Instances')
    ax2.set_xticks(x_pos)
    ax2.set_xticklabels(dept_sem_labels, rotation=45, ha='right')
    ax2.grid(True, alpha=0.3)
    
    # Add value labels on bars
    for i, v in enumerate(stats_df['Total_Instances']):
        ax2.text(i, v + 0.5, str(v), ha='center', va='bottom', fontweight='bold')
    
    # Student choice percentage
    ax3 = axes[1, 0]
    bars = ax3.bar(x_pos, stats_df['Choice_Percentage'], color='purple', alpha=0.7)
    ax3.set_title('Student Choice Percentage', fontweight='bold')
    ax3.set_xlabel('Department-Semester')
    ax3.set_ylabel('Choice Percentage (%)')
    ax3.set_xticks(x_pos)
    ax3.set_xticklabels(dept_sem_labels, rotation=45, ha='right')
    ax3.set_ylim(0, 100)
    ax3.grid(True, alpha=0.3)
    
    # Color-code bars based on choice percentage
    for i, (bar, pct) in enumerate(zip(bars, stats_df['Choice_Percentage'])):
        if pct >= 75:
            bar.set_color('green')
        elif pct >= 50:
            bar.set_color('orange')
        else:
            bar.set_color('red')
        
        # Add percentage labels
        ax3.text(i, pct + 1, f"{pct}%", ha='center', va='bottom', fontweight='bold')
    
    # Group balance
    ax4 = axes[1, 1]
    bars4 = ax4.bar(x_pos, stats_df['Group_Balance_CV'], color='teal', alpha=0.7)
    ax4.set_title('Group Balance (Coefficient of Variation)', fontweight='bold')
    ax4.set_xlabel('Department-Semester')
    ax4.set_ylabel('CV (%)')
    ax4.set_xticks(x_pos)
    ax4.set_xticklabels(dept_sem_labels, rotation=45, ha='right')
    ax4.grid(True, alpha=0.3)
    
    # Add value labels
    for i, v in enumerate(stats_df['Group_Balance_CV']):
        ax4.text(i, v + 0.5, f"{v}%", ha='center', va='bottom', fontweight='bold')
    
    plt.suptitle('Comprehensive Group-Course Distribution Analysis', fontsize=16, fontweight='bold')
    plt.tight_layout()
    
    # Save the plot
    viz_path = os.path.join(viz_dir, 'comprehensive_distribution_analysis.png')
    plt.savefig(viz_path, dpi=300, bbox_inches='tight')
    print(f"Saved comprehensive analysis: {viz_path}")
    plt.close()
    
    # 2. Detailed comparison table visualization
    create_detailed_table_visualization(stats_df, viz_dir)

def create_detailed_table_visualization(stats_df, viz_dir):
    """Create a detailed table visualization."""
    fig, ax = plt.subplots(figsize=(16, 8))
    ax.axis('tight')
    ax.axis('off')
    
    # Prepare table data
    table_data = []
    headers = ['Dept-Semester', 'Total\nCourses', 'Theory\nCourses', 'Lab\nCourses', 
              'Groups', 'Total\nInstances', 'Choice\n%', 'Balance\nCV%']
    
    for _, row in stats_df.iterrows():
        table_data.append([
            f"{row['Department']}\nS{row['Semester']}",
            str(row['Total_Courses']),
            str(row['Theory_Courses']),
            str(row['Lab_Courses']),
            str(row['Total_Groups']),
            str(row['Total_Instances']),
            f"{row['Choice_Percentage']}%",
            f"{row['Group_Balance_CV']}%"
        ])
    
    # Create table
    table = ax.table(cellText=table_data, colLabels=headers, 
                    cellLoc='center', loc='center')
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1.2, 2)
    
    # Style the table
    for i in range(len(headers)):
        table[(0, i)].set_facecolor('#4CAF50')
        table[(0, i)].set_text_props(weight='bold', color='white')
    
    # Color-code choice percentage cells
    choice_col_idx = 6  # Choice % column
    for i in range(1, len(table_data) + 1):
        choice_pct = float(table_data[i-1][choice_col_idx].replace('%', ''))
        if choice_pct >= 75:
            table[(i, choice_col_idx)].set_facecolor('#C8E6C9')
        elif choice_pct >= 50:
            table[(i, choice_col_idx)].set_facecolor('#FFE0B2')
        else:
            table[(i, choice_col_idx)].set_facecolor('#FFCDD2')
    
    plt.title('Comprehensive Group-Course Distribution Summary Table', 
             fontsize=14, fontweight='bold', pad=20)
    
    # Save the table
    table_path = os.path.join(viz_dir, 'comprehensive_summary_table.png')
    plt.savefig(table_path, dpi=300, bbox_inches='tight')
    print(f"Saved summary table: {table_path}")
    plt.close()

def find_latest_lab_schedule():
    """Find the most recent lab schedule file."""
    output_dir = "output"
    if not os.path.exists(output_dir):
        print(f"Output directory '{output_dir}' not found")
        return None
    
    # Find all lab schedule directories
    schedule_dirs = glob.glob(os.path.join(output_dir, "lab_schedule_*"))
    if not schedule_dirs:
        print("No lab schedule directories found")
        return None
    
    # Get the most recent one
    latest_dir = max(schedule_dirs, key=os.path.getctime)
    
    # Look for JSON file
    json_path = os.path.join(latest_dir, "lab_schedule.json")
    if os.path.exists(json_path):
        return json_path
    
    print(f"No lab_schedule.json found in {latest_dir}")
    return None

def main():
    parser = argparse.ArgumentParser(description='Generate comprehensive course-group distribution heatmaps')
    parser.add_argument('--courses', type=str, help='Path to courses CSV file', 
                       default='data/department_data/Artificial_Intelligence___Machine_Learning_courses.csv')
    parser.add_argument('--schedule', type=str, help='Path to lab schedule JSON file')
    parser.add_argument('--output', type=str, help='Output directory', 
                       default='output/group_course_analysis')
    
    args = parser.parse_args()
    
    # Check if courses file exists
    if not os.path.exists(args.courses):
        print(f"Courses file not found: {args.courses}")
        return
    
    # Load courses data
    print(f"Loading courses data from {args.courses}")
    courses_df = load_courses_data(args.courses)
    if courses_df is None:
        return
    
    # Load lab schedule if provided, otherwise find latest
    lab_schedule_data = None
    if args.schedule:
        if os.path.exists(args.schedule):
            print(f"Loading lab schedule from {args.schedule}")
            lab_schedule_data = load_lab_schedule(args.schedule)
        else:
            print(f"Lab schedule file not found: {args.schedule}")
    else:
        print("No lab schedule specified, looking for latest...")
        latest_schedule = find_latest_lab_schedule()
        if latest_schedule:
            print(f"Found latest lab schedule: {latest_schedule}")
            lab_schedule_data = load_lab_schedule(latest_schedule)
        else:
            print("No lab schedule found, proceeding with courses data only")
    
    # Create output directory
    output_dir = args.output
    os.makedirs(output_dir, exist_ok=True)
    print(f"Output directory: {output_dir}")
    
    # Analyze distribution
    distribution_data = analyze_complete_group_course_distribution(courses_df, lab_schedule_data)
    
    if not distribution_data:
        print("No distribution data found")
        return
    
    # Generate heatmaps
    generate_comprehensive_heatmaps(distribution_data, output_dir)
    
    # Generate statistics
    generate_overall_statistics_comprehensive(distribution_data, output_dir)
    
    print(f"\nAnalysis complete! Check the output directory: {output_dir}")

if __name__ == "__main__":
    main() 