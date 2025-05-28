#!/usr/bin/env python3
"""
Quick Runner for Lab Distribution Analysis
==========================================

This is a simplified runner that provides a clean summary of lab distribution.
"""

import pandas as pd
import os
from datetime import datetime

def analyze_lab_distribution_summary():
    """Provide a quick summary of lab distribution by capacity."""
    
    # Load data
    data_file = os.path.join('data', 'block_wise', 'techlongue.csv')
    
    if not os.path.exists(data_file):
        print(f"❌ Data file not found: {data_file}")
        return
    
    print("🧪 LAB CAPACITY DISTRIBUTION ANALYSIS")
    print("=" * 60)
    print(f"Analysis Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Load and filter lab data
    df = pd.read_csv(data_file)
    labs_df = df[df['is_lab'] == 1].copy()
    
    print(f"📊 OVERVIEW:")
    print(f"Total rooms in database: {len(df)}")
    print(f"Total laboratory facilities: {len(labs_df)}")
    print(f"Total classrooms: {len(df[df['is_lab'] == 0])}")
    print()
    
    # Capacity analysis
    print("🎯 LAB CAPACITY BREAKDOWN:")
    print("-" * 50)
    
    # Count by exact capacity
    capacity_counts = labs_df['room_max_cap'].value_counts().sort_index()
    
    total_capacity = labs_df['room_max_cap'].sum()
    
    print(f"{'Capacity':>8} | {'Count':>5} | {'Percentage':>10} | {'Total Cap':>10}")
    print("-" * 50)
    
    for capacity in sorted(capacity_counts.index):
        count = capacity_counts[capacity]
        percentage = (count / len(labs_df)) * 100
        cap_total = capacity * count
        print(f"{capacity:>8} | {count:>5} | {percentage:>9.1f}% | {cap_total:>10}")
    
    print("-" * 50)
    print(f"{'TOTAL':>8} | {len(labs_df):>5} | {'100.0%':>10} | {total_capacity:>10}")
    print()
    
    # Standard scheduling categories
    print("📋 SCHEDULING CATEGORIES:")
    print("-" * 40)
    
    labs_35 = len(labs_df[labs_df['room_max_cap'] <= 35])
    labs_70 = len(labs_df[(labs_df['room_max_cap'] > 35) & (labs_df['room_max_cap'] <= 70)])
    labs_140 = len(labs_df[labs_df['room_max_cap'] > 70])
    
    print(f"35-capacity labs:  {labs_35:2d} labs ({(labs_35/len(labs_df)*100):5.1f}%)")
    print(f"70-capacity labs:  {labs_70:2d} labs ({(labs_70/len(labs_df)*100):5.1f}%)")
    print(f"140-capacity labs: {labs_140:2d} labs ({(labs_140/len(labs_df)*100):5.1f}%)")
    print()
    
    # Block distribution
    print("🏢 DISTRIBUTION BY BUILDING BLOCK:")
    print("-" * 45)
    
    block_analysis = labs_df.groupby('block').agg({
        'room_max_cap': ['count', 'sum', 'mean']
    }).round(1)
    
    block_analysis.columns = ['Labs', 'Total_Cap', 'Avg_Cap']
    
    print(f"{'Block':12} | {'Labs':>4} | {'Total Cap':>9} | {'Avg Cap':>7}")
    print("-" * 45)
    
    for block in sorted(block_analysis.index):
        data = block_analysis.loc[block]
        print(f"{block:12} | {data['Labs']:>4.0f} | {data['Total_Cap']:>9.0f} | {data['Avg_Cap']:>7.1f}")
    
    print()
    
    # Hard constraint analysis
    print("🚨 SCHEDULING CONSTRAINT IMPACT:")
    print("-" * 50)
    print("Hard Constraint: Courses with practical_hours < 3 MUST use 35-capacity labs only")
    print()
    
    sessions_per_week_per_lab = 30  # 6 sessions/day × 5 days
    
    unrestricted_sessions = labs_35 * sessions_per_week_per_lab
    restricted_sessions = (labs_70 + labs_140) * sessions_per_week_per_lab
    total_sessions = unrestricted_sessions + restricted_sessions
    
    print(f"Labs available to ALL courses:           {labs_35:2d} labs = {unrestricted_sessions:3d} weekly sessions")
    print(f"Labs RESTRICTED to >=3 practical hours: {labs_70 + labs_140:2d} labs = {restricted_sessions:3d} weekly sessions")
    print(f"Total lab capacity:                      {len(labs_df):2d} labs = {total_sessions:3d} weekly sessions")
    print()
    print(f"Constraint impact: {((labs_70 + labs_140)/len(labs_df)*100):4.1f}% of labs have usage restrictions")
    print()
    
    # Utilization potential
    print("⚡ WEEKLY UTILIZATION POTENTIAL:")
    print("-" * 40)
    print("(Assuming 30 lab sessions per lab per week)")
    print()
    
    cap_35_total = labs_df[labs_df['room_max_cap'] <= 35]['room_max_cap'].sum()
    cap_70_total = labs_df[(labs_df['room_max_cap'] > 35) & (labs_df['room_max_cap'] <= 70)]['room_max_cap'].sum()
    cap_140_total = labs_df[labs_df['room_max_cap'] > 70]['room_max_cap'].sum()
    
    weekly_35 = labs_35 * sessions_per_week_per_lab * (cap_35_total / labs_35 if labs_35 > 0 else 0)
    weekly_70 = labs_70 * sessions_per_week_per_lab * (cap_70_total / labs_70 if labs_70 > 0 else 0)
    weekly_140 = labs_140 * sessions_per_week_per_lab * (cap_140_total / labs_140 if labs_140 > 0 else 0)
    total_weekly = weekly_35 + weekly_70 + weekly_140
    
    print(f"35-capacity labs:  {weekly_35:>8.0f} student-sessions/week")
    print(f"70-capacity labs:  {weekly_70:>8.0f} student-sessions/week")
    print(f"140-capacity labs: {weekly_140:>8.0f} student-sessions/week")
    print("-" * 40)
    print(f"TOTAL CAPACITY:    {total_weekly:>8.0f} student-sessions/week")
    print()
    
    # Technology levels
    print("💻 TECHNOLOGY LEVEL DISTRIBUTION:")
    print("-" * 35)
    
    tech_analysis = labs_df['tech_level'].fillna('Not Specified').value_counts()
    
    for tech_level in sorted(tech_analysis.index):
        count = tech_analysis[tech_level]
        percentage = (count / len(labs_df)) * 100
        print(f"{tech_level:15}: {count:2d} labs ({percentage:5.1f}%)")
    
    print()
    print("✅ Analysis completed successfully!")
    print(f"📁 For detailed analysis with visualizations, run: python analyze_lab_distribution.py")

if __name__ == "__main__":
    analyze_lab_distribution_summary() 