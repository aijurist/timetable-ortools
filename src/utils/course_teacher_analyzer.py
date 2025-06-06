"""
Course-Teacher Assignment Analyzer

This module analyzes course-teacher assignments from the CSE dataset,
identifies teachers with multiple course assignments, and generates
Hall's theorem distribution analysis for every semester.

Hall's Theorem Application:
- Analyzes the bipartite graph between courses and teachers
- Determines if perfect matching is possible
- Provides feasibility analysis for course assignments
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import os
import json
from collections import defaultdict, Counter
from itertools import combinations
import networkx as nx
from datetime import datetime

class NumpyEncoder(json.JSONEncoder):
    """Custom JSON encoder to handle numpy types."""
    def default(self, obj):
        if isinstance(obj, (np.integer, np.int64)):
            return int(obj)
        elif isinstance(obj, (np.floating, np.float64)):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, (pd.Timestamp, pd.Timedelta)):
            return str(obj)
        return super(NumpyEncoder, self).default(obj)

class CourseTeacherAnalyzer:
    def __init__(self, csv_file_path, output_dir=None):
        """Initialize the analyzer with CSV data."""
        self.csv_file_path = csv_file_path
        self.output_dir = output_dir or 'output/course_teacher_analysis'
        
        # Create output directory
        os.makedirs(self.output_dir, exist_ok=True)
        
        # Load and process data
        self.df = pd.read_csv(csv_file_path)
        self.process_data()
        
        print(f"📊 Course-Teacher Analyzer initialized")
        print(f"📁 Output directory: {self.output_dir}")
        print(f"📋 Total records: {len(self.df)}")
    
    def process_data(self):
        """Process and clean the data."""
        # Filter out Unknown teachers
        self.df_valid = self.df[self.df['teacher_id'] != 'Unknown'].copy()
        
        # Create teacher full names
        self.df_valid['teacher_full_name'] = (
            self.df_valid['first_name'].fillna('') + ' ' + 
            self.df_valid['last_name'].fillna('')
        ).str.strip()
        
        # Create course full identifier
        self.df_valid['course_full_name'] = (
            self.df_valid['course_code'] + ' - ' + 
            self.df_valid['course_name']
        )
        
        print(f"✅ Processed data: {len(self.df_valid)} valid records (excluded Unknown teachers)")
    
    def analyze_courses_with_teachers(self):
        """Analyze all courses with their assigned teachers."""
        print("\n" + "="*80)
        print("📚 COURSE-TEACHER ASSIGNMENT ANALYSIS")
        print("="*80)
        
        course_teacher_mapping = {}
        course_stats = {}
        
        # Group by course
        for course_code in self.df_valid['course_code'].unique():
            course_data = self.df_valid[self.df_valid['course_code'] == course_code]
            
            # Get unique teachers for this course
            teachers = course_data['teacher_full_name'].unique().tolist()
            teacher_ids = course_data['teacher_id'].unique().tolist()
            
            # Get course details
            course_info = course_data.iloc[0]
            
            course_teacher_mapping[course_code] = {
                'course_name': course_info['course_name'],
                'course_type': course_info['course_type'],
                'lecture_hours': course_info['lecture_hours'],
                'practical_hours': course_info['practical_hours'],
                'tutorial_hours': course_info['tutorial_hours'],
                'credits': course_info['credits'],
                'teachers': teachers,
                'teacher_ids': teacher_ids,
                'teacher_count': len(teachers),
                'total_assignments': len(course_data)
            }
            
            course_stats[course_code] = {
                'teacher_count': len(teachers),
                'total_hours': course_info['lecture_hours'] + course_info['practical_hours'] + course_info['tutorial_hours'],
                'assignments': len(course_data)
            }
        
        # Display results
        print(f"\n📋 TOTAL COURSES ANALYZED: {len(course_teacher_mapping)}")
        print("\n🔍 COURSE DETAILS:")
        print("-" * 80)
        
        for course_code, info in course_teacher_mapping.items():
            print(f"\n📖 {course_code} ({info['course_name']})")
            print(f"   📊 Type: {info['course_type']} | Credits: {info['credits']}")
            print(f"   ⏰ Hours: L={info['lecture_hours']}, P={info['practical_hours']}, T={info['tutorial_hours']}")
            print(f"   👥 Teachers ({info['teacher_count']}): {', '.join(info['teachers'])}")
            print(f"   📈 Total Assignments: {info['total_assignments']}")
        
        # Save to JSON
        json_file = os.path.join(self.output_dir, 'course_teacher_mapping.json')
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(course_teacher_mapping, f, indent=2, ensure_ascii=False, cls=NumpyEncoder)
        
        print(f"\n💾 Course-teacher mapping saved to: {json_file}")
        return course_teacher_mapping, course_stats
    
    def analyze_teachers_with_multiple_courses(self):
        """Analyze teachers assigned to multiple courses."""
        print("\n" + "="*80)
        print("👥 TEACHERS WITH MULTIPLE COURSE ASSIGNMENTS")
        print("="*80)
        
        teacher_course_mapping = defaultdict(list)
        teacher_stats = {}
        
        # Group by teacher
        for teacher_id in self.df_valid['teacher_id'].unique():
            teacher_data = self.df_valid[self.df_valid['teacher_id'] == teacher_id]
            
            # Get teacher details
            teacher_info = teacher_data.iloc[0]
            teacher_name = teacher_info['teacher_full_name']
            
            # Get unique courses for this teacher
            courses = []
            total_hours = 0
            
            for _, row in teacher_data.iterrows():
                course_info = {
                    'course_code': row['course_code'],
                    'course_name': row['course_name'],
                    'course_type': row['course_type'],
                    'lecture_hours': row['lecture_hours'],
                    'practical_hours': row['practical_hours'],
                    'tutorial_hours': row['tutorial_hours'],
                    'credits': row['credits'],
                    'semester': row['semester'],
                    'academic_year': row['academic_year']
                }
                courses.append(course_info)
                total_hours += (row['lecture_hours'] + row['practical_hours'] + row['tutorial_hours'])
            
            # Remove duplicates based on course_code
            unique_courses = []
            seen_courses = set()
            for course in courses:
                if course['course_code'] not in seen_courses:
                    unique_courses.append(course)
                    seen_courses.add(course['course_code'])
            
            teacher_course_mapping[teacher_id] = {
                'teacher_name': teacher_name,
                'staff_code': teacher_info.get('staff_code', ''),
                'courses': unique_courses,
                'course_count': len(unique_courses),
                'total_hours': total_hours,
                'total_assignments': len(teacher_data)
            }
            
            teacher_stats[teacher_id] = {
                'course_count': len(unique_courses),
                'total_hours': total_hours,
                'assignments': len(teacher_data)
            }
        
        # Filter teachers with multiple courses
        multiple_course_teachers = {
            tid: info for tid, info in teacher_course_mapping.items() 
            if info['course_count'] > 1
        }
        
        print(f"\n📊 TEACHERS WITH MULTIPLE COURSES: {len(multiple_course_teachers)} out of {len(teacher_course_mapping)}")
        print("\n🔍 DETAILED BREAKDOWN:")
        print("-" * 80)
        
        for teacher_id, info in multiple_course_teachers.items():
            print(f"\n👨‍🏫 {info['teacher_name']} ({teacher_id})")
            print(f"   📚 Courses ({info['course_count']}): {', '.join([c['course_code'] for c in info['courses']])}")
            print(f"   ⏰ Total Hours: {info['total_hours']}")
            print(f"   📈 Total Assignments: {info['total_assignments']}")
            
            # Show course details
            for course in info['courses']:
                hours = course['lecture_hours'] + course['practical_hours'] + course['tutorial_hours']
                print(f"      • {course['course_code']} ({course['course_type']}) - {hours}h - Sem {course['semester']}")
        
        # Save to JSON
        json_file = os.path.join(self.output_dir, 'teachers_multiple_courses.json')
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(multiple_course_teachers, f, indent=2, ensure_ascii=False, cls=NumpyEncoder)
        
        print(f"\n💾 Multiple course teachers data saved to: {json_file}")
        return teacher_course_mapping, multiple_course_teachers
    
    def analyze_semester_wise_distribution(self):
        """Analyze course-teacher distribution by semester."""
        print("\n" + "="*80)
        print("📅 SEMESTER-WISE DISTRIBUTION ANALYSIS")
        print("="*80)
        
        semester_analysis = {}
        
        for semester in sorted(self.df_valid['semester'].unique()):
            sem_data = self.df_valid[self.df_valid['semester'] == semester]
            
            # Get unique courses and teachers for this semester
            courses = sem_data['course_code'].unique()
            teachers = sem_data['teacher_id'].unique()
            
            # Course-teacher matrix for this semester
            course_teacher_matrix = defaultdict(set)
            teacher_course_matrix = defaultdict(set)
            
            for _, row in sem_data.iterrows():
                course_teacher_matrix[row['course_code']].add(row['teacher_id'])
                teacher_course_matrix[row['teacher_id']].add(row['course_code'])
            
            # Calculate statistics
            avg_teachers_per_course = np.mean([len(teachers) for teachers in course_teacher_matrix.values()])
            avg_courses_per_teacher = np.mean([len(courses) for courses in teacher_course_matrix.values()])
            
            semester_analysis[semester] = {
                'total_courses': len(courses),
                'total_teachers': len(teachers),
                'total_assignments': len(sem_data),
                'course_teacher_matrix': {k: list(v) for k, v in course_teacher_matrix.items()},
                'teacher_course_matrix': {k: list(v) for k, v in teacher_course_matrix.items()},
                'avg_teachers_per_course': avg_teachers_per_course,
                'avg_courses_per_teacher': avg_courses_per_teacher,
                'courses_list': courses.tolist(),
                'teachers_list': teachers.tolist()
            }
        
        # Display results
        for semester, analysis in semester_analysis.items():
            print(f"\n📊 SEMESTER {semester}:")
            print(f"   📚 Courses: {analysis['total_courses']}")
            print(f"   👥 Teachers: {analysis['total_teachers']}")
            print(f"   📈 Assignments: {analysis['total_assignments']}")
            print(f"   📊 Avg Teachers/Course: {analysis['avg_teachers_per_course']:.2f}")
            print(f"   📊 Avg Courses/Teacher: {analysis['avg_courses_per_teacher']:.2f}")
        
        return semester_analysis
    
    def apply_halls_theorem_analysis(self):
        """Apply Hall's theorem to analyze assignment feasibility."""
        print("\n" + "="*80)
        print("🧮 HALL'S THEOREM DISTRIBUTION ANALYSIS")
        print("="*80)
        
        semester_analysis = self.analyze_semester_wise_distribution()
        halls_analysis = {}
        
        for semester, data in semester_analysis.items():
            print(f"\n🔬 Analyzing Semester {semester} with Hall's Theorem...")
            
            courses = data['courses_list']
            teachers = data['teachers_list']
            course_teacher_matrix = data['course_teacher_matrix']
            
            # Create bipartite graph
            G = nx.Graph()
            
            # Add nodes
            for course in courses:
                G.add_node(f"course_{course}", bipartite=0, type='course')
            for teacher in teachers:
                G.add_node(f"teacher_{teacher}", bipartite=1, type='teacher')
            
            # Add edges based on assignments
            for course, assigned_teachers in course_teacher_matrix.items():
                for teacher in assigned_teachers:
                    G.add_edge(f"course_{course}", f"teacher_{teacher}")
            
            # Hall's theorem analysis
            halls_results = self._check_halls_condition(courses, teachers, course_teacher_matrix)
            
            # Maximum matching
            try:
                matching = nx.bipartite.maximum_matching(G)
                max_matching_size = len(matching) // 2  # Each edge is counted twice
            except:
                max_matching_size = 0
            
            # Perfect matching feasibility
            perfect_matching_possible = (max_matching_size == len(courses) == len(teachers))
            
            halls_analysis[semester] = {
                'courses_count': len(courses),
                'teachers_count': len(teachers),
                'total_edges': sum(len(teachers) for teachers in course_teacher_matrix.values()),
                'max_matching_size': max_matching_size,
                'perfect_matching_possible': perfect_matching_possible,
                'halls_condition_satisfied': halls_results['condition_satisfied'],
                'halls_violations': halls_results['violations'],
                'matching_efficiency': (max_matching_size / max(len(courses), len(teachers))) * 100 if max(len(courses), len(teachers)) > 0 else 0,
                'assignment_density': (sum(len(teachers) for teachers in course_teacher_matrix.values()) / (len(courses) * len(teachers))) * 100 if len(courses) * len(teachers) > 0 else 0
            }
            
            # Display results
            print(f"   📊 Courses: {len(courses)}, Teachers: {len(teachers)}")
            print(f"   🔗 Total Assignments: {halls_analysis[semester]['total_edges']}")
            print(f"   🎯 Maximum Matching: {max_matching_size}")
            print(f"   ✅ Perfect Matching Possible: {perfect_matching_possible}")
            print(f"   🧮 Hall's Condition Satisfied: {halls_results['condition_satisfied']}")
            print(f"   📈 Matching Efficiency: {halls_analysis[semester]['matching_efficiency']:.2f}%")
            print(f"   📊 Assignment Density: {halls_analysis[semester]['assignment_density']:.2f}%")
            
            if halls_results['violations']:
                print(f"   ⚠️  Hall's Violations: {len(halls_results['violations'])}")
                for violation in halls_results['violations'][:3]:  # Show first 3 violations
                    print(f"      • Subset {violation['subset']} has only {violation['neighbor_count']} teachers")
        
        return halls_analysis
    
    def _check_halls_condition(self, courses, teachers, course_teacher_matrix):
        """Check Hall's marriage condition for course-teacher assignment."""
        violations = []
        
        # Check all non-empty subsets of courses
        for r in range(1, len(courses) + 1):
            for course_subset in combinations(courses, r):
                # Find all teachers assigned to any course in this subset
                neighbors = set()
                for course in course_subset:
                    neighbors.update(course_teacher_matrix.get(course, []))
                
                # Hall's condition: |N(S)| >= |S|
                if len(neighbors) < len(course_subset):
                    violations.append({
                        'subset': list(course_subset),
                        'subset_size': len(course_subset),
                        'neighbor_count': len(neighbors),
                        'neighbors': list(neighbors)
                    })
        
        return {
            'condition_satisfied': len(violations) == 0,
            'violations': violations
        }
    
    def generate_visualizations(self):
        """Generate comprehensive visualizations."""
        print("\n" + "="*80)
        print("📈 GENERATING VISUALIZATIONS")
        print("="*80)
        
        # Set style
        plt.style.use('default')
        sns.set_palette("husl")
        
        # 1. Course-Teacher Distribution
        self._plot_course_teacher_distribution()
        
        # 2. Semester-wise Analysis
        self._plot_semester_analysis()
        
        # 3. Hall's Theorem Analysis
        self._plot_halls_theorem_analysis()
        
        # 4. Teacher Workload Distribution
        self._plot_teacher_workload()
        
        print("✅ All visualizations generated successfully!")
    
    def _plot_course_teacher_distribution(self):
        """Plot course-teacher distribution."""
        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(16, 12))
        
        # Teachers per course
        course_teacher_counts = self.df_valid.groupby('course_code')['teacher_id'].nunique()
        ax1.hist(course_teacher_counts, bins=10, alpha=0.7, color='skyblue', edgecolor='black')
        ax1.set_title('Distribution of Teachers per Course')
        ax1.set_xlabel('Number of Teachers')
        ax1.set_ylabel('Number of Courses')
        ax1.grid(True, alpha=0.3)
        
        # Courses per teacher
        teacher_course_counts = self.df_valid.groupby('teacher_id')['course_code'].nunique()
        ax2.hist(teacher_course_counts, bins=10, alpha=0.7, color='lightcoral', edgecolor='black')
        ax2.set_title('Distribution of Courses per Teacher')
        ax2.set_xlabel('Number of Courses')
        ax2.set_ylabel('Number of Teachers')
        ax2.grid(True, alpha=0.3)
        
        # Course types distribution
        course_types = self.df_valid['course_type'].value_counts()
        ax3.pie(course_types.values, labels=course_types.index, autopct='%1.1f%%', startangle=90)
        ax3.set_title('Distribution of Course Types')
        
        # Semester distribution
        semester_counts = self.df_valid['semester'].value_counts().sort_index()
        ax4.bar(semester_counts.index, semester_counts.values, color='lightgreen', edgecolor='black')
        ax4.set_title('Assignments per Semester')
        ax4.set_xlabel('Semester')
        ax4.set_ylabel('Number of Assignments')
        ax4.grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.savefig(os.path.join(self.output_dir, 'course_teacher_distribution.png'), dpi=300, bbox_inches='tight')
        plt.close()
        print("📊 Course-teacher distribution plot saved")
    
    def _plot_semester_analysis(self):
        """Plot semester-wise analysis."""
        semester_data = self.df_valid.groupby('semester').agg({
            'course_code': 'nunique',
            'teacher_id': 'nunique',
            'id': 'count'
        }).rename(columns={'course_code': 'courses', 'teacher_id': 'teachers', 'id': 'assignments'})
        
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))
        
        # Semester statistics
        x = semester_data.index
        width = 0.25
        
        ax1.bar(x - width, semester_data['courses'], width, label='Courses', alpha=0.8)
        ax1.bar(x, semester_data['teachers'], width, label='Teachers', alpha=0.8)
        ax1.bar(x + width, semester_data['assignments']/10, width, label='Assignments/10', alpha=0.8)
        
        ax1.set_title('Semester-wise Statistics')
        ax1.set_xlabel('Semester')
        ax1.set_ylabel('Count')
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        
        # Course-Teacher ratio per semester
        ratios = semester_data['courses'] / semester_data['teachers']
        ax2.plot(x, ratios, 'o-', linewidth=2, markersize=8, color='purple')
        ax2.set_title('Course-to-Teacher Ratio by Semester')
        ax2.set_xlabel('Semester')
        ax2.set_ylabel('Courses / Teachers')
        ax2.grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.savefig(os.path.join(self.output_dir, 'semester_analysis.png'), dpi=300, bbox_inches='tight')
        plt.close()
        print("📊 Semester analysis plot saved")
    
    def _plot_halls_theorem_analysis(self):
        """Plot Hall's theorem analysis results."""
        halls_data = self.apply_halls_theorem_analysis()
        
        # Prepare data for plotting
        semesters = list(halls_data.keys())
        matching_efficiency = [halls_data[sem]['matching_efficiency'] for sem in semesters]
        assignment_density = [halls_data[sem]['assignment_density'] for sem in semesters]
        halls_satisfied = [halls_data[sem]['halls_condition_satisfied'] for sem in semesters]
        
        fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(18, 6))
        
        # Matching efficiency
        bars1 = ax1.bar(semesters, matching_efficiency, color='lightblue', edgecolor='black')
        ax1.set_title("Hall's Theorem: Matching Efficiency")
        ax1.set_xlabel('Semester')
        ax1.set_ylabel('Matching Efficiency (%)')
        ax1.set_ylim(0, 100)
        ax1.grid(True, alpha=0.3)
        
        # Add value labels on bars
        for bar, value in zip(bars1, matching_efficiency):
            ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1, 
                    f'{value:.1f}%', ha='center', va='bottom')
        
        # Assignment density
        bars2 = ax2.bar(semesters, assignment_density, color='lightcoral', edgecolor='black')
        ax2.set_title('Assignment Density by Semester')
        ax2.set_xlabel('Semester')
        ax2.set_ylabel('Assignment Density (%)')
        ax2.grid(True, alpha=0.3)
        
        # Add value labels on bars
        for bar, value in zip(bars2, assignment_density):
            ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1, 
                    f'{value:.1f}%', ha='center', va='bottom')
        
        # Hall's condition satisfaction
        colors = ['green' if satisfied else 'red' for satisfied in halls_satisfied]
        bars3 = ax3.bar(semesters, [100 if satisfied else 0 for satisfied in halls_satisfied], 
                       color=colors, alpha=0.7, edgecolor='black')
        ax3.set_title("Hall's Condition Satisfaction")
        ax3.set_xlabel('Semester')
        ax3.set_ylabel('Condition Satisfied')
        ax3.set_ylim(0, 120)
        ax3.set_yticks([0, 100])
        ax3.set_yticklabels(['Not Satisfied', 'Satisfied'])
        
        plt.tight_layout()
        plt.savefig(os.path.join(self.output_dir, 'halls_theorem_analysis.png'), dpi=300, bbox_inches='tight')
        plt.close()
        print("📊 Hall's theorem analysis plot saved")
    
    def _plot_teacher_workload(self):
        """Plot teacher workload distribution."""
        # Calculate teacher workloads
        teacher_workload = self.df_valid.groupby('teacher_id').agg({
            'lecture_hours': 'sum',
            'practical_hours': 'sum',
            'tutorial_hours': 'sum',
            'course_code': 'nunique'
        })
        
        teacher_workload['total_hours'] = (teacher_workload['lecture_hours'] + 
                                         teacher_workload['practical_hours'] + 
                                         teacher_workload['tutorial_hours'])
        
        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(16, 12))
        
        # Total hours distribution
        ax1.hist(teacher_workload['total_hours'], bins=15, alpha=0.7, color='gold', edgecolor='black')
        ax1.set_title('Distribution of Total Teaching Hours per Teacher')
        ax1.set_xlabel('Total Hours')
        ax1.set_ylabel('Number of Teachers')
        ax1.axvline(teacher_workload['total_hours'].mean(), color='red', linestyle='--', 
                   label=f'Mean: {teacher_workload["total_hours"].mean():.1f}h')
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        
        # Hours vs courses scatter
        ax2.scatter(teacher_workload['course_code'], teacher_workload['total_hours'], 
                   alpha=0.6, color='purple')
        ax2.set_title('Teaching Hours vs Number of Courses')
        ax2.set_xlabel('Number of Courses')
        ax2.set_ylabel('Total Teaching Hours')
        ax2.grid(True, alpha=0.3)
        
        # Hour type breakdown
        hour_types = ['lecture_hours', 'practical_hours', 'tutorial_hours']
        hour_totals = [teacher_workload[ht].sum() for ht in hour_types]
        colors = ['lightblue', 'lightgreen', 'lightyellow']
        
        wedges, texts, autotexts = ax3.pie(hour_totals, labels=['Lecture', 'Practical', 'Tutorial'], 
                                          colors=colors, autopct='%1.1f%%', startangle=90)
        ax3.set_title('Distribution of Teaching Hour Types')
        
        # Top teachers by workload
        top_teachers = teacher_workload.nlargest(10, 'total_hours')
        teacher_names = [f"T{tid}" for tid in top_teachers.index]  # Simplified names
        
        bars = ax4.barh(range(len(top_teachers)), top_teachers['total_hours'], color='lightcoral')
        ax4.set_yticks(range(len(top_teachers)))
        ax4.set_yticklabels(teacher_names)
        ax4.set_title('Top 10 Teachers by Total Teaching Hours')
        ax4.set_xlabel('Total Hours')
        ax4.grid(True, alpha=0.3)
        
        # Add value labels on bars
        for i, (bar, value) in enumerate(zip(bars, top_teachers['total_hours'])):
            ax4.text(bar.get_width() + 0.5, bar.get_y() + bar.get_height()/2, 
                    f'{value:.0f}h', ha='left', va='center')
        
        plt.tight_layout()
        plt.savefig(os.path.join(self.output_dir, 'teacher_workload_analysis.png'), dpi=300, bbox_inches='tight')
        plt.close()
        print("📊 Teacher workload analysis plot saved")
    
    def generate_comprehensive_report(self):
        """Generate a comprehensive analysis report."""
        print("\n" + "="*80)
        print("📝 GENERATING COMPREHENSIVE REPORT")
        print("="*80)
        
        # Run all analyses
        course_teacher_mapping, course_stats = self.analyze_courses_with_teachers()
        teacher_course_mapping, multiple_course_teachers = self.analyze_teachers_with_multiple_courses()
        semester_analysis = self.analyze_semester_wise_distribution()
        halls_analysis = self.apply_halls_theorem_analysis()
        
        # Generate visualizations
        self.generate_visualizations()
        
        # Create comprehensive report
        report = {
            'timestamp': datetime.now().isoformat(),
            'summary': {
                'total_records': len(self.df),
                'valid_records': len(self.df_valid),
                'total_courses': len(course_teacher_mapping),
                'total_teachers': len(teacher_course_mapping),
                'teachers_with_multiple_courses': len(multiple_course_teachers),
                'semesters_analyzed': list(semester_analysis.keys())
            },
            'course_teacher_mapping': course_teacher_mapping,
            'teacher_course_mapping': {str(k): v for k, v in teacher_course_mapping.items()},
            'multiple_course_teachers': {str(k): v for k, v in multiple_course_teachers.items()},
            'semester_analysis': semester_analysis,
            'halls_theorem_analysis': halls_analysis
        }
        
        # Save comprehensive report
        report_file = os.path.join(self.output_dir, 'comprehensive_analysis_report.json')
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False, cls=NumpyEncoder)
        
        # Generate summary text report
        self._generate_text_summary(report)
        
        print(f"\n✅ Comprehensive analysis completed!")
        print(f"📁 All files saved to: {self.output_dir}")
        print(f"📊 JSON Report: comprehensive_analysis_report.json")
        print(f"📝 Text Summary: analysis_summary.txt")
        print(f"📈 Visualizations: *.png files")
        
        return report
    
    def _generate_text_summary(self, report):
        """Generate a text summary of the analysis."""
        summary_file = os.path.join(self.output_dir, 'analysis_summary.txt')
        
        with open(summary_file, 'w', encoding='utf-8') as f:
            f.write("COURSE-TEACHER ASSIGNMENT ANALYSIS SUMMARY\n")
            f.write("=" * 50 + "\n\n")
            f.write(f"Analysis Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            
            # Overall Statistics
            f.write("OVERALL STATISTICS:\n")
            f.write("-" * 20 + "\n")
            f.write(f"Total Records: {report['summary']['total_records']}\n")
            f.write(f"Valid Records: {report['summary']['valid_records']}\n")
            f.write(f"Total Courses: {report['summary']['total_courses']}\n")
            f.write(f"Total Teachers: {report['summary']['total_teachers']}\n")
            f.write(f"Teachers with Multiple Courses: {report['summary']['teachers_with_multiple_courses']}\n")
            f.write(f"Semesters Analyzed: {', '.join(map(str, report['summary']['semesters_analyzed']))}\n\n")
            
            # Hall's Theorem Results
            f.write("HALL'S THEOREM ANALYSIS:\n")
            f.write("-" * 25 + "\n")
            for semester, analysis in report['halls_theorem_analysis'].items():
                f.write(f"Semester {semester}:\n")
                f.write(f"  - Courses: {analysis['courses_count']}\n")
                f.write(f"  - Teachers: {analysis['teachers_count']}\n")
                f.write(f"  - Max Matching: {analysis['max_matching_size']}\n")
                f.write(f"  - Perfect Matching Possible: {analysis['perfect_matching_possible']}\n")
                f.write(f"  - Hall's Condition Satisfied: {analysis['halls_condition_satisfied']}\n")
                f.write(f"  - Matching Efficiency: {analysis['matching_efficiency']:.2f}%\n")
                f.write(f"  - Assignment Density: {analysis['assignment_density']:.2f}%\n\n")
        
        print(f"📝 Text summary saved to: {summary_file}")


def main():
    """Main function to run the analysis."""
    import sys
    import os
    
    # Default CSV file path
    csv_file = 'data/cse.csv'
    
    # Check if CSV file exists
    if not os.path.exists(csv_file):
        print(f"❌ Error: CSV file not found at {csv_file}")
        print("Please ensure the cse.csv file exists in the data directory.")
        return
    
    # Create analyzer
    analyzer = CourseTeacherAnalyzer(csv_file)
    
    # Run comprehensive analysis
    report = analyzer.generate_comprehensive_report()
    
    print("\n🎉 Analysis completed successfully!")
    print("Check the output directory for detailed results and visualizations.")

if __name__ == "__main__":
    main() 