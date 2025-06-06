#!/usr/bin/env python3

"""
Test script for the FIXED fifth semester grouping with proper unique teacher constraint.

This script demonstrates the corrected algorithm that ensures:
1. Each teacher is assigned to exactly ONE group (no teacher in multiple groups)
2. Teachers with multiple instances keep ALL their instances in the same group
3. Hall's theorem satisfaction for all groups
4. Proper student capacity allocation
"""

import os
import sys

# Add the project root to Python path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from src.utils.fifth_semester_grouping import FifthSemesterGroupingAnalyzer

def test_fixed_unique_constraint():
    """Test the FIXED unique teacher constraint algorithm."""
    
    print("🔧 TESTING FIXED UNIQUE TEACHER CONSTRAINT ALGORITHM")
    print("="*80)
    print("FIXED Features:")
    print("✅ Each teacher assigned to exactly ONE group")
    print("✅ Teachers with multiple instances: all instances in same group")
    print("✅ No teacher appears in multiple groups")
    print("✅ Hall's theorem satisfaction for all groups")
    print("✅ Proper heatmap showing actual instance distribution")
    print("="*80)
    
    # Initialize analyzer
    csv_file = 'data/cse.csv'
    if not os.path.exists(csv_file):
        print(f"❌ Error: CSV file not found at {csv_file}")
        return
    
    output_dir = 'output/fixed_unique_constraint'
    analyzer = FifthSemesterGroupingAnalyzer(csv_file, output_dir)
    
    # Step 1: Analyze current distribution
    print("\n📊 STEP 1: ANALYZING CURRENT FIFTH SEMESTER DATA")
    print("-" * 60)
    distribution_analysis = analyzer.analyze_fifth_semester_distribution()
    
    # Step 2: Create FIXED unique constraint groups
    print("\n🔧 STEP 2: CREATING FIXED UNIQUE CONSTRAINT GROUPS")
    print("-" * 60)
    fixed_groups = analyzer.create_optimal_groups()
    
    # Step 3: Analyze the FIXED results
    print("\n📈 STEP 3: ANALYZING FIXED CONSTRAINT RESULTS")
    print("-" * 60)
    
    # Overall statistics
    total_groups = len(fixed_groups)
    total_instances_distributed = sum(len(g['course_instances']) for g in fixed_groups)
    total_courses_represented = len(set().union(*(g['courses_represented'] for g in fixed_groups)))
    total_teachers_assigned = len(set().union(*(g['teachers_assigned'] for g in fixed_groups)))
    total_capacity = sum(g['student_capacity'] for g in fixed_groups)
    
    print(f"📊 FIXED CONSTRAINT SUMMARY:")
    print(f"   📦 Total groups created: {total_groups}")
    print(f"   🔢 Teacher instances distributed: {total_instances_distributed}/{len(analyzer.teacher_instances)}")
    print(f"   📚 Courses represented: {total_courses_represented}/{len(analyzer.courses)}")
    print(f"   👥 Teachers assigned: {total_teachers_assigned}/{len(analyzer.teachers)}")
    print(f"   👨‍🎓 Total student capacity: {total_capacity}")
    
    # Constraint satisfaction analysis
    halls_satisfied = sum(1 for g in fixed_groups if g.get('halls_satisfied', False))
    unique_constraint_satisfied = sum(1 for g in fixed_groups if g.get('instance_constraint_satisfied', True))
    enhanced_constraint_satisfied = sum(1 for g in fixed_groups if g.get('enhanced_constraint_satisfied', True))
    
    print(f"\n🔒 CONSTRAINT SATISFACTION:")
    print(f"   🧮 Hall's Theorem: {halls_satisfied}/{total_groups} groups satisfied")
    print(f"   🔒 Unique Teacher Constraint: {unique_constraint_satisfied}/{total_groups} groups satisfied")
    print(f"   📦 Enhanced Distribution Constraint: {enhanced_constraint_satisfied}/{total_groups} groups satisfied")
    
    # Detailed group analysis
    print(f"\n📋 DETAILED GROUP ANALYSIS:")
    print("-" * 50)
    
    # Track global teacher assignments for verification
    teacher_group_mapping = {}
    
    for group in fixed_groups:
        group_id = group['group_id']
        courses = list(group['courses_represented'])
        teachers = list(group['teachers_assigned'])
        instances = group['course_instances']
        capacity = group['student_capacity']
        
        print(f"\n🎯 Group {group_id}:")
        print(f"   📚 Courses ({len(courses)}): {courses}")
        print(f"   👥 Teachers ({len(teachers)}): {teachers}")
        print(f"   🔢 Teacher instances: {len(instances)}")
        print(f"   👨‍🎓 Student capacity: {capacity}")
        print(f"   🧮 Hall's Theorem: {'✅ SATISFIED' if group.get('halls_satisfied', False) else '❌ VIOLATED'}")
        print(f"   🔒 Enhanced Constraint: {'✅ SATISFIED' if group.get('enhanced_constraint_satisfied', True) else '❌ VIOLATED'}")
        
        # Track teacher assignments for verification
        for teacher_id in teachers:
            if teacher_id in teacher_group_mapping:
                teacher_group_mapping[teacher_id].append(group_id)
            else:
                teacher_group_mapping[teacher_id] = [group_id]
        
        # Show instance distribution details
        teacher_course_map = {}
        for course_code, instance in instances:
            teacher_id = instance['teacher_id']
            if teacher_id not in teacher_course_map:
                teacher_course_map[teacher_id] = []
            teacher_course_map[teacher_id].append(course_code)
        
        print(f"   📊 Teacher-Course instance distribution:")
        for teacher_id, teacher_courses in teacher_course_map.items():
            course_counts = {}
            for course in teacher_courses:
                course_counts[course] = course_counts.get(course, 0) + 1
            
            course_summary = []
            for course, count in course_counts.items():
                if count > 1:
                    course_summary.append(f"{course}×{count}")
                else:
                    course_summary.append(course)
            
            print(f"      👨‍🏫 Teacher {teacher_id}: {', '.join(course_summary)}")
    
    # VERIFICATION: Check for unique teacher constraint violations
    print(f"\n🔍 UNIQUE TEACHER CONSTRAINT VERIFICATION:")
    print("-" * 50)
    
    total_violations = 0
    for teacher_id, group_ids in teacher_group_mapping.items():
        if len(group_ids) > 1:
            print(f"   ❌ Teacher {teacher_id} appears in multiple groups: {group_ids}")
            total_violations += 1
        else:
            print(f"   ✅ Teacher {teacher_id}: Group {group_ids[0]} only")
    
    if total_violations == 0:
        print(f"\n🎉 SUCCESS: UNIQUE TEACHER CONSTRAINT SATISFIED!")
        print(f"✅ All {len(teacher_group_mapping)} teachers assigned to exactly one group")
    else:
        print(f"\n❌ FAILURE: {total_violations} teachers violate unique constraint")
    
    # Step 4: Generate FIXED visualizations
    print("\n📈 STEP 4: GENERATING FIXED VISUALIZATIONS")
    print("-" * 50)
    analyzer.generate_group_visualizations(fixed_groups)
    
    # Step 5: Generate FIXED course-group heatmap
    print("\n🔥 STEP 5: GENERATING FIXED COURSE-GROUP HEATMAP")
    print("-" * 50)
    analyzer.generate_course_group_heatmap(fixed_groups)
    
    # Step 6: Save FIXED results
    print("\n💾 STEP 6: SAVING FIXED RESULTS")
    print("-" * 40)
    results = analyzer.save_grouping_results(fixed_groups)
    
    # Final summary
    print(f"\n🎊 FIXED UNIQUE CONSTRAINT TEST COMPLETED!")
    print("="*60)
    print(f"📁 Results saved to: {output_dir}")
    print(f"📊 Created {total_groups} groups with fixed constraints")
    print(f"🔢 Distributed {total_instances_distributed} teacher instances")
    print(f"👥 Assigned {total_teachers_assigned} teachers")
    print(f"🔒 Unique constraint violations: {total_violations}")
    print(f"🧮 Hall's theorem: {halls_satisfied}/{total_groups} satisfied")
    print(f"📈 Average efficiency: {results['summary']['avg_group_efficiency']:.1f}%")
    
    if total_violations == 0 and halls_satisfied == total_groups:
        print(f"\n🏆 PERFECT SOLUTION ACHIEVED!")
        print(f"✅ All constraints satisfied")
        print(f"✅ Unique teacher constraint enforced")
        print(f"✅ Hall's theorem satisfied")
    elif total_violations == 0:
        print(f"\n🎯 GOOD SOLUTION ACHIEVED!")
        print(f"✅ Unique teacher constraint satisfied")
        print(f"⚠️  Some Hall's theorem violations remain")
    else:
        print(f"\n🔧 SOLUTION NEEDS ATTENTION!")
        print(f"❌ Unique teacher constraint still violated")
    
    return results, total_violations

if __name__ == "__main__":
    test_fixed_unique_constraint() 