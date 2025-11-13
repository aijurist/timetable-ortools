#!/usr/bin/env python3
"""
Quick Fifth Semester Grouping Summary

This script provides a quick summary of the 5th semester course-teacher grouping
results including Hall's theorem satisfaction and student capacity analysis.
"""

import json
import pandas as pd
import os

def quick_fifth_semester_summary():
    """Display a quick summary of the 5th semester grouping results."""
    print("🎯 QUICK FIFTH SEMESTER GROUPING SUMMARY")
    print("=" * 60)
    
    # Load results
    json_file = 'output/fifth_semester_grouping/fifth_semester_optimal_groups.json'
    csv_file = 'output/fifth_semester_grouping/fifth_semester_groups_summary.csv'
    
    if not os.path.exists(json_file):
        print(f"❌ Results file not found: {json_file}")
        print("Please run the 5th semester grouping analysis first.")
        return
    
    # Load JSON results
    with open(json_file, 'r', encoding='utf-8') as f:
        results = json.load(f)
    
    # Load CSV summary
    if os.path.exists(csv_file):
        summary_df = pd.read_csv(csv_file)
    else:
        summary_df = None
    
    print(f"📊 Analysis Results Overview:")
    print(f"   🗓️  Analysis Date: {results['timestamp'][:19]}")
    print(f"   🎓 Semester: {results['semester']}")
    print(f"   📚 Total Courses: {results['total_courses']}")
    print(f"   👥 Total Teachers: {results['total_teachers']}")
    print(f"   👨‍🎓 Students per Teacher: {results['students_per_teacher']}")
    
    print(f"\n🎯 Grouping Results:")
    summary = results['summary']
    print(f"   📦 Total Groups Created: {summary['total_groups']}")
    print(f"   ✅ Hall's Theorem Satisfied: {summary['halls_satisfied_groups']}/{summary['total_groups']}")
    print(f"   👨‍🎓 Sufficient Capacity: {summary['capacity_sufficient_groups']}/{summary['total_groups']}")
    print(f"   📈 Average Efficiency: {summary['average_efficiency']:.1f}%")
    print(f"   🎓 Total Student Capacity: {summary['total_student_capacity']}")
    print(f"   📊 Total Requirements: {summary['total_student_requirements']}")
    print(f"   💯 Capacity Utilization: {(summary['total_student_requirements']/summary['total_student_capacity'])*100:.1f}%")
    
    print(f"\n📋 Detailed Group Breakdown:")
    print("-" * 60)
    
    for group in results['groups']:
        print(f"\n🎯 GROUP {group['group_id']}:")
        print(f"   📚 Courses ({group['course_count']}): {', '.join(group['courses'])}")
        print(f"   👥 Teachers: {group['teacher_count']}")
        print(f"   🧮 Hall's Theorem: {'✅ SATISFIED' if group['halls_satisfied'] else '❌ VIOLATED'}")
        print(f"   ⏰ Total Hours: {group['total_hours']}")
        print(f"   👨‍🎓 Student Capacity: {group['student_capacity']}")
        print(f"   📊 Required Capacity: {group['student_requirements']}")
        print(f"   ✅ Capacity OK: {'YES' if group['capacity_sufficient'] else 'NO'}")
        print(f"   🎯 Efficiency: {group['group_efficiency']:.1f}%")
        
        # Show course details with teacher assignments
        print(f"   📖 Course Details:")
        for course_code in group['courses']:
            assigned_teachers = group['course_teacher_matrix'].get(course_code, [])
            print(f"      • {course_code}: {len(assigned_teachers)} teachers assigned")
    
    # Student capacity analysis
    print(f"\n👨‍🎓 Student Capacity Analysis:")
    print("-" * 40)
    
    for group in results['groups']:
        capacity_ratio = group['student_requirements'] / group['student_capacity'] if group['student_capacity'] > 0 else 0
        print(f"   Group {group['group_id']}: {capacity_ratio:.1%} capacity used")
        
        # Calculate potential for additional students
        surplus = group['student_capacity'] - group['student_requirements']
        additional_sections = surplus // 70 if surplus > 0 else 0
        print(f"      Surplus capacity: {surplus} students ({additional_sections} additional sections possible)")
    
    # Hall's Theorem Analysis
    print(f"\n🧮 Hall's Theorem Analysis:")
    print("-" * 30)
    
    all_satisfied = all(group['halls_satisfied'] for group in results['groups'])
    print(f"   Overall Status: {'✅ ALL GROUPS SATISFY HALL\'S THEOREM' if all_satisfied else '❌ SOME VIOLATIONS EXIST'}")
    
    if all_satisfied:
        print(f"   🎉 Perfect matching is possible for all groups!")
        print(f"   ✅ Course assignments are mathematically feasible")
        print(f"   📊 Teacher distribution is optimal")
    
    # Teacher workload distribution
    print(f"\n👨‍🏫 Teacher Distribution Analysis:")
    print("-" * 35)
    
    all_teachers = set()
    teacher_groups = {}
    
    for group in results['groups']:
        for teacher in group['teachers']:
            all_teachers.add(teacher)
            if teacher not in teacher_groups:
                teacher_groups[teacher] = []
            teacher_groups[teacher].append(group['group_id'])
    
    # Count teachers by number of groups
    single_group_teachers = sum(1 for groups in teacher_groups.values() if len(groups) == 1)
    multi_group_teachers = sum(1 for groups in teacher_groups.values() if len(groups) > 1)
    
    print(f"   👥 Total teachers: {len(all_teachers)}")
    print(f"   🎯 Single group teachers: {single_group_teachers}")
    print(f"   🔄 Multi-group teachers: {multi_group_teachers}")
    
    if multi_group_teachers > 0:
        print(f"   📋 Teachers in multiple groups:")
        for teacher, groups in teacher_groups.items():
            if len(groups) > 1:
                print(f"      • Teacher {teacher}: Groups {', '.join(map(str, groups))}")
    
    # Optimization recommendations
    print(f"\n💡 Key Insights & Recommendations:")
    print("-" * 40)
    
    if all_satisfied and summary['capacity_sufficient_groups'] == summary['total_groups']:
        print(f"   ✅ Grouping is OPTIMAL!")
        print(f"   ✅ All Hall's theorem conditions satisfied")
        print(f"   ✅ Sufficient student capacity in all groups")
        print(f"   📊 Efficient teacher utilization: {summary['average_efficiency']:.1f}%")
        print(f"   🎯 Ready for timetable scheduling!")
    else:
        print(f"   ⚠️  Some optimization needed")
        if summary['halls_satisfied_groups'] < summary['total_groups']:
            print(f"   ❌ Hall's theorem violations in some groups")
        if summary['capacity_sufficient_groups'] < summary['total_groups']:
            print(f"   ❌ Insufficient capacity in some groups")
    
    # Show generated files
    print(f"\n📁 Generated Files:")
    output_dir = 'output/fifth_semester_grouping'
    if os.path.exists(output_dir):
        files = os.listdir(output_dir)
        for file in sorted(files):
            if file.endswith(('.json', '.csv', '.txt', '.png')):
                file_type = "📊" if file.endswith('.json') else "📋" if file.endswith('.csv') else "📝" if file.endswith('.txt') else "📈"
                print(f"   {file_type} {file}")
    
    print(f"\n🎉 Fifth Semester Grouping Analysis Complete!")
    print(f"📈 {summary['total_groups']} optimal groups created with {summary['average_efficiency']:.1f}% efficiency")

if __name__ == "__main__":
    quick_fifth_semester_summary() 