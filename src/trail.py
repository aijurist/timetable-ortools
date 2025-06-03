#!/usr/bin/env python
import os
import sys
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from collections import Counter

# Add parent directory to path
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(parent_dir)

from src.scheduler import MacroblockTimetableScheduler

def main():
    """
    Trail script to test and analyze the distribution of courses with lecture + tutorial hours ≥ 4
    across all macroblocks a1-g1, demonstrating the removal of the a1-d1 block restriction.
    """
    print("=" * 80)
    print("TRAIL SCRIPT: Testing 4+ Hour Course Distribution Across All Blocks")
    print("=" * 80)
    
    # Define paths
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    course_file = os.path.join(base_dir, 'data/mapped_data/cs_5sem.csv')
    room_file = os.path.join(base_dir, 'data/block_wise/techlongue.csv')
    
    # Verify input files
    verify_input_files(course_file)
    
    # Create scheduler
    print("\nCreating scheduler...")
    scheduler = MacroblockTimetableScheduler(course_file, room_file)
    
    # Generate timetable
    print("\nGenerating timetable with modified constraints...")
    print("- Courses with lecture + tutorial ≥ 4 hours can now use all a1-g1 blocks")
    print("- Previous restriction to only a1-d1 blocks has been removed")
    print("- New 5-hour course CS23507 (3L+2T) added to test this modification")
    solution = scheduler.generate_timetable()
    
    if solution:
        print("\n✅ Timetable generation successful!")
        print(f"Output directory: {scheduler.output_dir}")
        
        # Analyze the distribution of 4+ hour courses
        analyze_course_distribution(scheduler.output_dir)
    else:
        print("\n❌ Timetable generation failed.")

def verify_input_files(course_file):
    """Verify and display information about the input course file."""
    courses_df = pd.read_csv(course_file)
    
    print("\nInput Course File Analysis:")
    print(f"Total courses: {len(courses_df['course_code'].unique())}")
    print(f"Total course instances: {len(courses_df)}")
    
    # Group by course and analyze hours
    course_info = {}
    for _, row in courses_df.iterrows():
        course_code = row['course_code']
        if course_code not in course_info:
            course_info[course_code] = {
                'name': row['course_name'],
                'lecture_hours': row['lecture_hours'],
                'tutorial_hours': row['tutorial_hours'],
                'total_hours': row['lecture_hours'] + row['tutorial_hours'],
                'instance_count': 0
            }
        course_info[course_code]['instance_count'] += 1
    
    # Display course information
    print("\nCourse Information:")
    print(f"{'Code':<10} {'Name':<35} {'Hours':<10} {'Teachers':<10}")
    print("-" * 65)
    
    four_plus_hour_courses = []
    
    for code, info in course_info.items():
        hours_str = f"{info['lecture_hours']}L+{info['tutorial_hours']}T"
        print(f"{code:<10} {info['name']:<35} {hours_str:<10} {info['instance_count']:<10}")
        
        if info['total_hours'] >= 4:
            four_plus_hour_courses.append(code)
    
    print("\n4+ Hour Courses (target for analysis):")
    for code in four_plus_hour_courses:
        info = course_info[code]
        hours_str = f"{info['lecture_hours']}L+{info['tutorial_hours']}T={info['total_hours']}"
        print(f"- {code}: {info['name']} ({hours_str} hours)")

def analyze_course_distribution(output_dir):
    """Analyze the distribution of 4+ hour courses across macroblocks."""
    print("\nAnalyzing 4+ Hour Course Distribution:")
    
    # Load schedule
    schedule_file = os.path.join(output_dir, 'macroblock_schedule.csv')
    if not os.path.exists(schedule_file):
        print(f"Schedule file not found: {schedule_file}")
        return
    
    schedule_df = pd.read_csv(schedule_file)
    
    # Define blocks
    a_to_d_blocks = ['a1', 'b1', 'c1', 'd1']
    e_to_g_blocks = ['e1', 'f1', 'g1']
    all_blocks = a_to_d_blocks + e_to_g_blocks
    
    # Load course data to identify 4+ hour courses
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    course_file = os.path.join(base_dir, 'data/mapped_data/cs_5sem.csv')
    courses_df = pd.read_csv(course_file)
    
    # Identify 4+ hour courses
    four_plus_hour_courses = set()
    course_hours = {}
    
    for _, row in courses_df.iterrows():
        course_code = row['course_code']
        total_hours = row['lecture_hours'] + row['tutorial_hours']
        course_hours[course_code] = total_hours
        
        if total_hours >= 4:
            four_plus_hour_courses.add(course_code)
    
    print(f"\nCourses with 4+ hours: {', '.join(sorted(four_plus_hour_courses))}")
    
    # Group schedule by course and analyze
    course_block_distribution = {course: {'a1-d1': 0, 'e1-g1': 0} for course in four_plus_hour_courses}
    course_block_details = {course: [] for course in four_plus_hour_courses}
    
    for _, row in schedule_df.iterrows():
        course_code = row['course_code']
        if course_code in four_plus_hour_courses:
            macroblock = row['macroblock']
            if macroblock in all_blocks:  # Only count a1-g1 blocks
                if macroblock in a_to_d_blocks:
                    course_block_distribution[course_code]['a1-d1'] += 1
                elif macroblock in e_to_g_blocks:
                    course_block_distribution[course_code]['e1-g1'] += 1
                
                # Record instance details
                course_block_details[course_code].append({
                    'teacher': f"{row['first_name']} {row['last_name']}",
                    'macroblock': macroblock,
                    'slot_type': row['slot_type']
                })
    
    # Display results
    print("\nBlock Distribution of 4+ Hour Courses:")
    print(f"{'Course':<10} {'Total Hours':<12} {'a1-d1 Slots':<12} {'e1-g1 Slots':<12} {'Distribution':<15}")
    print("-" * 60)
    
    for course, dist in course_block_distribution.items():
        a_to_d_count = dist['a1-d1']
        e_to_g_count = dist['e1-g1']
        total_count = a_to_d_count + e_to_g_count
        
        if total_count > 0:
            a_to_d_percent = (a_to_d_count / total_count) * 100
            e_to_g_percent = (e_to_g_count / total_count) * 100
            distribution = f"{a_to_d_percent:.1f}% / {e_to_g_percent:.1f}%"
        else:
            distribution = "N/A"
        
        print(f"{course:<10} {course_hours.get(course, 'N/A'):<12} {a_to_d_count:<12} {e_to_g_count:<12} {distribution:<15}")
    
    # Analyze specifically the new 5-hour course (CS23507)
    if 'CS23507' in four_plus_hour_courses:
        print("\nDetailed Analysis of New 5-hour Course (CS23507):")
        cs23507_details = course_block_details.get('CS23507', [])
        
        if cs23507_details:
            # Group by macroblock
            macroblock_counts = Counter([d['macroblock'] for d in cs23507_details])
            
            print(f"\nMacroblock distribution for CS23507 (Machine Learning Algorithms):")
            for block in all_blocks:
                count = macroblock_counts.get(block, 0)
                print(f"  {block}: {count} assignments")
            
            # Check if e1-g1 blocks are being used
            e_to_g_usage = sum(macroblock_counts.get(block, 0) for block in e_to_g_blocks)
            if e_to_g_usage > 0:
                print(f"\n✅ CONFIRMATION: 5-hour course CS23507 is using e1-g1 blocks ({e_to_g_usage} assignments)")
                print("   This confirms our modification allowing 4+ hour courses to use all a1-g1 blocks works correctly.")
            else:
                print("\n⚠️ CS23507 is not using any e1-g1 blocks. Modification may not be working as expected.")
        else:
            print("  No schedule data found for CS23507")
    
    # Visualize the distribution
    visualize_distribution(course_block_distribution, course_hours)

def visualize_distribution(course_block_distribution, course_hours):
    """Visualize the distribution of 4+ hour courses across macroblocks."""
    # Create a figure with two subplots
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))
    
    # Prepare data for the first plot - distribution by course
    courses = []
    a_to_d_values = []
    e_to_g_values = []
    total_hours = []
    
    for course, dist in course_block_distribution.items():
        if dist['a1-d1'] + dist['e1-g1'] > 0:  # Only include courses with data
            courses.append(course)
            a_to_d_values.append(dist['a1-d1'])
            e_to_g_values.append(dist['e1-g1'])
            total_hours.append(course_hours.get(course, 0))
    
    # Sort by total hours
    sorted_indices = np.argsort(total_hours)[::-1]  # Descending order
    courses = [courses[i] for i in sorted_indices]
    a_to_d_values = [a_to_d_values[i] for i in sorted_indices]
    e_to_g_values = [e_to_g_values[i] for i in sorted_indices]
    total_hours = [total_hours[i] for i in sorted_indices]
    
    # Plot stacked bar chart
    x = np.arange(len(courses))
    width = 0.7
    
    ax1.bar(x, a_to_d_values, width, label='a1-d1 blocks', color='skyblue')
    ax1.bar(x, e_to_g_values, width, bottom=a_to_d_values, label='e1-g1 blocks', color='orange')
    
    ax1.set_title('Distribution of 4+ Hour Courses Across Macroblocks')
    ax1.set_xlabel('Course Code (with total hours)')
    ax1.set_ylabel('Number of Assignments')
    ax1.set_xticks(x)
    ax1.set_xticklabels([f"{c}\n({h}h)" for c, h in zip(courses, total_hours)])
    ax1.legend()
    
    # Prepare data for the second plot - percentage distribution
    percentages_a_to_d = []
    percentages_e_to_g = []
    
    for i in range(len(courses)):
        total = a_to_d_values[i] + e_to_g_values[i]
        if total > 0:
            percentages_a_to_d.append((a_to_d_values[i] / total) * 100)
            percentages_e_to_g.append((e_to_g_values[i] / total) * 100)
        else:
            percentages_a_to_d.append(0)
            percentages_e_to_g.append(0)
    
    # Plot percentage distribution
    ax2.bar(x, percentages_a_to_d, width, label='a1-d1 blocks (%)', color='skyblue')
    ax2.bar(x, percentages_e_to_g, width, bottom=percentages_a_to_d, label='e1-g1 blocks (%)', color='orange')
    
    ax2.set_title('Percentage Distribution of 4+ Hour Courses')
    ax2.set_xlabel('Course Code (with total hours)')
    ax2.set_ylabel('Percentage of Assignments (%)')
    ax2.set_xticks(x)
    ax2.set_xticklabels([f"{c}\n({h}h)" for c, h in zip(courses, total_hours)])
    ax2.set_ylim(0, 100)
    ax2.legend()
    
    # Add a horizontal line at 70% for reference (our target distribution)
    ax2.axhline(y=70, color='r', linestyle='--', alpha=0.5)
    ax2.text(len(courses)-1, 71, '70% Target', color='r', ha='right')
    
    plt.tight_layout()
    
    # Save figure
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    output_dir = os.path.join(base_dir, 'output')
    os.makedirs(output_dir, exist_ok=True)
    
    output_file = os.path.join(output_dir, 'four_plus_hour_distribution.png')
    plt.savefig(output_file)
    print(f"\nDistribution visualization saved to {output_file}")
    
    # Try to display the plot (will work in environments that support it)
    try:
        plt.show()
    except:
        pass

if __name__ == "__main__":
    main()
