import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
from collections import defaultdict, Counter
import os
import glob

class SemesterGroupingAnalyzer:
    def __init__(self, schedule_csv_path, courses_csv_path):
        """Initialize the analyzer with schedule and course data."""
        self.schedule_df = pd.read_csv(schedule_csv_path)
        self.courses_df = pd.read_csv(courses_csv_path)
        
        # Filter only lecture and tutorial slots (not labs)
        self.schedule_df = self.schedule_df[self.schedule_df['slot_type'].isin(['Lecture', 'Tutorial'])]
        
        # Check if teacher_shift column exists and is meaningful (not all same value)
        self.has_shift_data = False
        if 'teacher_shift' in self.schedule_df.columns:
            unique_shifts = self.schedule_df['teacher_shift'].nunique()
            if unique_shifts > 1:  # Only consider meaningful if there are multiple shifts
                self.has_shift_data = True
            else:
                print("Note: Teacher shift data found but all teachers use the same combined shift")
        
        # Create output directory for analysis
        self.output_dir = os.path.join(os.path.dirname(schedule_csv_path), 'grouping_analysis')
        os.makedirs(self.output_dir, exist_ok=True)
        
        print(f"Loaded {len(self.schedule_df)} theory assignments")
        print(f"Analyzing grouping constraints...")

    def analyze_macroblock_grouping(self):
        """Analyze how courses are grouped in each macroblock by semester and department."""
        print("\n" + "="*80)
        print("MACROBLOCK GROUPING ANALYSIS")
        print("="*80)
        
        # Group by macroblock and analyze
        macroblock_analysis = {}
        
        for macroblock in self.schedule_df['macroblock'].unique():
            if pd.isna(macroblock):
                continue
                
            block_data = self.schedule_df[self.schedule_df['macroblock'] == macroblock]
            
            # Get unique courses and teachers in this macroblock
            courses_in_block = block_data['course_code'].unique()
            teachers_in_block = block_data['teacher_id'].unique()
            
            # Get semester and department info for courses in this block
            semester_info = {}
            dept_info = {}
            
            for course in courses_in_block:
                course_matches = self.courses_df[self.courses_df['course_code'] == course]
                if not course_matches.empty:
                    course_info = course_matches.iloc[0]
                    semester_info[course] = course_info['semester']
                    dept_info[course] = course_info['course_dept']
                else:
                    semester_info[course] = "Unknown"
                    dept_info[course] = "Unknown Department"
            
            # Check for violations
            teacher_course_pairs = block_data[['teacher_id', 'course_code']].drop_duplicates()
            course_counts = teacher_course_pairs['course_code'].value_counts()
            teacher_counts = teacher_course_pairs['teacher_id'].value_counts()
            
            macroblock_analysis[macroblock] = {
                'courses': list(courses_in_block),
                'teachers': list(teachers_in_block),
                'num_courses': len(courses_in_block),
                'num_teachers': len(teachers_in_block),
                'semesters': list(set(semester_info.values())),
                'departments': list(set(dept_info.values())),
                'course_counts': dict(course_counts),
                'teacher_counts': dict(teacher_counts),
                'teacher_course_pairs': teacher_course_pairs.to_dict('records'),
                'semester_info': semester_info,
                'dept_info': dept_info
            }
            
            # Print analysis for this macroblock
            print(f"\nMacroblock {macroblock}:")
            print(f"  Courses: {len(courses_in_block)} unique")
            print(f"  Teachers: {len(teachers_in_block)} unique")
            print(f"  Semesters: {sorted([str(s) for s in set(semester_info.values())])}")
            print(f"  Departments: {list(set(dept_info.values()))}")
            
            # Check for violations
            repeated_courses = [course for course, count in course_counts.items() if count > 1]
            repeated_teachers = [teacher for teacher, count in teacher_counts.items() if count > 1]
            
            if repeated_courses:
                print(f"  ⚠️  VIOLATION: Repeated courses: {repeated_courses}")
            else:
                print(f"  ✅ No repeated courses")
                
            if repeated_teachers:
                print(f"  ⚠️  VIOLATION: Repeated teachers: {repeated_teachers}")
            else:
                print(f"  ✅ No repeated teachers")
            
            # Show teacher-course mapping
            print(f"  Teacher-Course pairs:")
            for pair in teacher_course_pairs.to_dict('records'):
                teacher_name = self._get_teacher_name(pair['teacher_id'])
                print(f"    Teacher {pair['teacher_id']} ({teacher_name}) -> {pair['course_code']}")
        
        return macroblock_analysis

    def _get_teacher_name(self, teacher_id):
        """Get teacher name from courses data."""
        teacher_data = self.courses_df[self.courses_df['teacher_id'] == teacher_id]
        if not teacher_data.empty:
            first_name = teacher_data.iloc[0].get('first_name', '')
            last_name = teacher_data.iloc[0].get('last_name', '')
            return f"{first_name} {last_name}".strip()
        return f"Teacher {teacher_id}"

    def analyze_student_choice_optimization(self):
        """Analyze how well the system provides choice to students."""
        print("\n" + "="*80)
        print("STUDENT CHOICE OPTIMIZATION ANALYSIS")
        print("="*80)
        
        # Group courses by semester and department
        course_groups = defaultdict(list)
        
        for _, row in self.courses_df.iterrows():
            key = (row['semester'], row['course_dept'])
            course_groups[key].append({
                'course_code': row['course_code'],
                'course_name': row['course_name'],
                'teacher_id': row['teacher_id'],
                'teacher_name': self._get_teacher_name(row['teacher_id'])
            })
        
        choice_analysis = {}
        
        for (semester, dept), courses in course_groups.items():
            print(f"\nSemester {semester} - {dept}:")
            
            # Get unique courses for this semester/dept
            unique_courses = {}
            for course in courses:
                course_code = course['course_code']
                if course_code not in unique_courses:
                    unique_courses[course_code] = []
                unique_courses[course_code].append(course)
            
            semester_choice_data = {}
            
            for course_code, course_instances in unique_courses.items():
                # Find where this course is scheduled
                course_schedule = self.schedule_df[self.schedule_df['course_code'] == course_code]
                
                if course_schedule.empty:
                    continue
                
                # Group by macroblock to see teacher choices
                macroblock_teachers = {}
                for _, sched_row in course_schedule.iterrows():
                    macroblock = sched_row['macroblock']
                    teacher_id = sched_row['teacher_id']
                    
                    if macroblock not in macroblock_teachers:
                        macroblock_teachers[macroblock] = set()
                    macroblock_teachers[macroblock].add(teacher_id)
                
                # Calculate choice metrics
                total_teachers = len(set(course_schedule['teacher_id']))
                total_macroblocks = len(macroblock_teachers)
                
                semester_choice_data[course_code] = {
                    'total_teachers': total_teachers,
                    'total_macroblocks': total_macroblocks,
                    'macroblock_distribution': dict(macroblock_teachers),
                    'course_name': course_instances[0]['course_name']
                }
                
                print(f"  {course_code} ({course_instances[0]['course_name']}):")
                print(f"    Teachers available: {total_teachers}")
                print(f"    Macroblocks used: {total_macroblocks}")
                
                for mb, teachers in macroblock_teachers.items():
                    teacher_names = [self._get_teacher_name(t) for t in teachers]
                    print(f"    {mb}: {teacher_names}")
            
            choice_analysis[(semester, dept)] = semester_choice_data
        
        return choice_analysis

    def create_visualizations(self, macroblock_analysis, choice_analysis):
        """Create comprehensive visualizations of the grouping analysis."""
        
        # 1. Macroblock Course Distribution
        self._plot_macroblock_distribution(macroblock_analysis)
        
        # 2. Teacher Diversity Analysis
        self._plot_teacher_diversity(macroblock_analysis)
        
        # 3. Semester Grouping Effectiveness
        self._plot_semester_grouping(macroblock_analysis)
        
        # 4. Student Choice Optimization
        self._plot_student_choices(choice_analysis)
        
        # 5. 5th Semester CSE Student Choices
        self._plot_5th_sem_cse_choices(choice_analysis)
        
        # 6. Constraint Violations Summary
        self._plot_violations_summary(macroblock_analysis)
        
        # 7. Detailed Macroblock Grid
        self._plot_macroblock_grid(macroblock_analysis)

    def _plot_macroblock_distribution(self, macroblock_analysis):
        """Plot the distribution of courses across macroblocks."""
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))
        
        # Number of courses per macroblock
        macroblocks = list(macroblock_analysis.keys())
        course_counts = [analysis['num_courses'] for analysis in macroblock_analysis.values()]
        teacher_counts = [analysis['num_teachers'] for analysis in macroblock_analysis.values()]
        
        ax1.bar(macroblocks, course_counts, alpha=0.7, color='skyblue', label='Courses')
        ax1.bar(macroblocks, teacher_counts, alpha=0.7, color='lightcoral', label='Teachers')
        ax1.set_title('Courses and Teachers per Macroblock')
        ax1.set_xlabel('Macroblock')
        ax1.set_ylabel('Count')
        ax1.legend()
        ax1.tick_params(axis='x', rotation=45)
        
        # Macroblock utilization
        utilization_data = []
        for mb, analysis in macroblock_analysis.items():
            utilization_data.append({
                'Macroblock': mb,
                'Courses': analysis['num_courses'],
                'Teachers': analysis['num_teachers'],
                'Ratio': analysis['num_teachers'] / max(analysis['num_courses'], 1)
            })
        
        util_df = pd.DataFrame(utilization_data)
        ax2.scatter(util_df['Courses'], util_df['Teachers'], alpha=0.7, s=100)
        
        # Add labels for each point
        for _, row in util_df.iterrows():
            ax2.annotate(row['Macroblock'], (row['Courses'], row['Teachers']), 
                        xytext=(5, 5), textcoords='offset points', fontsize=8)
        
        ax2.set_title('Teacher-Course Ratio per Macroblock')
        ax2.set_xlabel('Number of Courses')
        ax2.set_ylabel('Number of Teachers')
        ax2.grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.savefig(os.path.join(self.output_dir, 'macroblock_distribution.png'), dpi=300, bbox_inches='tight')
        plt.close()

    def _plot_teacher_diversity(self, macroblock_analysis):
        """Plot teacher diversity analysis."""
        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(16, 12))
        
        # Teacher diversity per macroblock
        macroblocks = list(macroblock_analysis.keys())
        diversity_scores = []
        
        for mb, analysis in macroblock_analysis.items():
            # Calculate diversity as teachers/courses ratio
            diversity = analysis['num_teachers'] / max(analysis['num_courses'], 1)
            diversity_scores.append(diversity)
        
        ax1.bar(macroblocks, diversity_scores, color='lightgreen', alpha=0.7)
        ax1.set_title('Teacher Diversity Score (Teachers/Courses)')
        ax1.set_xlabel('Macroblock')
        ax1.set_ylabel('Diversity Score')
        ax1.tick_params(axis='x', rotation=45)
        ax1.axhline(y=1, color='red', linestyle='--', alpha=0.7, label='Ideal (1:1)')
        ax1.legend()
        
        # Teacher workload distribution
        teacher_workloads = defaultdict(int)
        for analysis in macroblock_analysis.values():
            for teacher in analysis['teachers']:
                teacher_workloads[teacher] += 1
        
        workload_counts = Counter(teacher_workloads.values())
        ax2.bar(workload_counts.keys(), workload_counts.values(), color='orange', alpha=0.7)
        ax2.set_title('Teacher Workload Distribution')
        ax2.set_xlabel('Number of Macroblocks per Teacher')
        ax2.set_ylabel('Number of Teachers')
        
        # Course repetition analysis
        course_repetitions = defaultdict(int)
        for analysis in macroblock_analysis.values():
            for course, count in analysis['course_counts'].items():
                if count > 1:
                    course_repetitions[course] += count - 1
        
        if course_repetitions:
            ax3.bar(course_repetitions.keys(), course_repetitions.values(), color='red', alpha=0.7)
            ax3.set_title('Course Repetition Violations')
            ax3.set_xlabel('Course Code')
            ax3.set_ylabel('Number of Repetitions')
            ax3.tick_params(axis='x', rotation=45)
        else:
            ax3.text(0.5, 0.5, 'No Course Repetitions\n✅ Constraint Satisfied', 
                    ha='center', va='center', transform=ax3.transAxes, fontsize=14, color='green')
            ax3.set_title('Course Repetition Violations')
        
        # Teacher repetition analysis
        teacher_repetitions = defaultdict(int)
        for analysis in macroblock_analysis.values():
            for teacher, count in analysis['teacher_counts'].items():
                if count > 1:
                    teacher_repetitions[teacher] += count - 1
        
        if teacher_repetitions:
            ax4.bar(teacher_repetitions.keys(), teacher_repetitions.values(), color='red', alpha=0.7)
            ax4.set_title('Teacher Repetition Violations')
            ax4.set_xlabel('Teacher ID')
            ax4.set_ylabel('Number of Repetitions')
        else:
            ax4.text(0.5, 0.5, 'No Teacher Repetitions\n✅ Constraint Satisfied', 
                    ha='center', va='center', transform=ax4.transAxes, fontsize=14, color='green')
            ax4.set_title('Teacher Repetition Violations')
        
        plt.tight_layout()
        plt.savefig(os.path.join(self.output_dir, 'teacher_diversity_analysis.png'), dpi=300, bbox_inches='tight')
        plt.close()

    def _plot_semester_grouping(self, macroblock_analysis):
        """Plot semester grouping effectiveness."""
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))
        
        # Semester distribution across macroblocks
        semester_distribution = defaultdict(list)
        for mb, analysis in macroblock_analysis.items():
            for semester in analysis['semesters']:
                semester_distribution[semester].append(mb)
        
        # Create heatmap data
        # Fix semester sorting to handle mixed types
        semester_keys = list(semester_distribution.keys())
        semester_str_values = [str(s) for s in semester_keys if s != "Unknown"]
        semesters = sorted(semester_str_values, key=lambda x: int(x) if x.isdigit() else float('inf'))
        if "Unknown" in semester_keys:
            semesters.append("Unknown")
        macroblocks = sorted(macroblock_analysis.keys())
        
        heatmap_data = np.zeros((len(semesters), len(macroblocks)))
        
        for i, semester in enumerate(semesters):
            for j, mb in enumerate(macroblocks):
                # Find the original semester key
                original_semester = None
                for orig_key in semester_keys:
                    if str(orig_key) == semester:
                        original_semester = orig_key
                        break
                
                if original_semester is not None and mb in semester_distribution[original_semester]:
                    # Count courses from this semester in this macroblock
                    mb_analysis = macroblock_analysis[mb]
                    courses_in_semester = sum(1 for course in mb_analysis['courses'] 
                                            if str(mb_analysis['semester_info'].get(course, "")) == semester)
                    heatmap_data[i, j] = courses_in_semester
        
        im1 = ax1.imshow(heatmap_data, cmap='YlOrRd', aspect='auto')
        ax1.set_title('Semester Distribution Across Macroblocks')
        ax1.set_xlabel('Macroblock')
        ax1.set_ylabel('Semester')
        ax1.set_xticks(range(len(macroblocks)))
        ax1.set_xticklabels(macroblocks, rotation=45)
        ax1.set_yticks(range(len(semesters)))
        ax1.set_yticklabels(semesters)
        
        # Add text annotations
        for i in range(len(semesters)):
            for j in range(len(macroblocks)):
                if heatmap_data[i, j] > 0:
                    ax1.text(j, i, int(heatmap_data[i, j]), ha='center', va='center', 
                            color='white' if heatmap_data[i, j] > heatmap_data.max()/2 else 'black')
        
        plt.colorbar(im1, ax=ax1, label='Number of Courses')
        
        # Semester grouping effectiveness
        semester_stats = []
        for semester in semesters:
            # Convert semester back to original type for comparison
            original_semester = None
            for orig_key in semester_keys:
                if str(orig_key) == semester:
                    original_semester = orig_key
                    break
            
            if original_semester is None:
                continue
                
            total_courses = sum(1 for _, row in self.courses_df.iterrows() if str(row['semester']) == semester)
            scheduled_courses = 0
            for _, row in self.schedule_df.iterrows():
                # Need to get semester info from courses_df
                course_matches = self.courses_df[self.courses_df['course_code'] == row['course_code']]
                if not course_matches.empty and str(course_matches.iloc[0]['semester']) == semester:
                    scheduled_courses += 1
            
            macroblocks_used = len(semester_distribution.get(original_semester, []))
            
            semester_stats.append({
                'Semester': semester,
                'Total Courses': total_courses,
                'Scheduled Courses': scheduled_courses,
                'Macroblocks Used': macroblocks_used,
                'Avg Courses per Block': scheduled_courses / max(macroblocks_used, 1)
            })
        
        stats_df = pd.DataFrame(semester_stats)
        x_pos = np.arange(len(semesters))
        
        ax2.bar(x_pos - 0.2, stats_df['Total Courses'], 0.4, label='Total Courses', alpha=0.7)
        ax2.bar(x_pos + 0.2, stats_df['Scheduled Courses'], 0.4, label='Scheduled Courses', alpha=0.7)
        
        ax2.set_title('Course Scheduling by Semester')
        ax2.set_xlabel('Semester')
        ax2.set_ylabel('Number of Courses')
        ax2.set_xticks(x_pos)
        ax2.set_xticklabels(semesters)
        ax2.legend()
        
        plt.tight_layout()
        plt.savefig(os.path.join(self.output_dir, 'semester_grouping_analysis.png'), dpi=300, bbox_inches='tight')
        plt.close()

    def _plot_student_choices(self, choice_analysis):
        """Plot student choice optimization analysis."""
        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(16, 12))
        
        # Collect choice data
        all_choice_data = []
        for (semester, dept), courses in choice_analysis.items():
            for course_code, choice_info in courses.items():
                all_choice_data.append({
                    'Semester': semester,
                    'Department': dept,
                    'Course': course_code,
                    'Teachers': choice_info['total_teachers'],
                    'Macroblocks': choice_info['total_macroblocks'],
                    'Choice Score': choice_info['total_teachers'] * choice_info['total_macroblocks']
                })
        
        choice_df = pd.DataFrame(all_choice_data)
        
        if not choice_df.empty:
            # Teacher choices per course
            ax1.hist(choice_df['Teachers'], bins=10, alpha=0.7, color='skyblue', edgecolor='black')
            ax1.set_title('Distribution of Teacher Choices per Course')
            ax1.set_xlabel('Number of Teachers per Course')
            ax1.set_ylabel('Number of Courses')
            
            # Macroblock distribution per course
            ax2.hist(choice_df['Macroblocks'], bins=10, alpha=0.7, color='lightcoral', edgecolor='black')
            ax2.set_title('Distribution of Macroblocks per Course')
            ax2.set_xlabel('Number of Macroblocks per Course')
            ax2.set_ylabel('Number of Courses')
            
            # Choice score by semester
            semester_choice = choice_df.groupby('Semester')['Choice Score'].mean()
            ax3.bar(semester_choice.index, semester_choice.values, alpha=0.7, color='lightgreen')
            ax3.set_title('Average Choice Score by Semester')
            ax3.set_xlabel('Semester')
            ax3.set_ylabel('Average Choice Score')
            
            # Top courses with most choices
            top_choices = choice_df.nlargest(10, 'Choice Score')[['Course', 'Teachers', 'Macroblocks', 'Choice Score']]
            
            y_pos = np.arange(len(top_choices))
            ax4.barh(y_pos, top_choices['Choice Score'], alpha=0.7, color='gold')
            ax4.set_title('Top 10 Courses with Most Student Choices')
            ax4.set_xlabel('Choice Score (Teachers × Macroblocks)')
            ax4.set_ylabel('Course')
            ax4.set_yticks(y_pos)
            ax4.set_yticklabels(top_choices['Course'])
        
        plt.tight_layout()
        plt.savefig(os.path.join(self.output_dir, 'student_choice_analysis.png'), dpi=300, bbox_inches='tight')
        plt.close()

    def _plot_5th_sem_cse_choices(self, choice_analysis):
        """Plot course choices specifically for 5th semester Computer Science Engineering students."""
        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(20, 16))
        
        # Define main theory blocks only (exclude tutorial blocks)
        main_theory_blocks = ['a1', 'a2', 'b1', 'b2', 'c1', 'c2', 'd1', 'd2', 'e1', 'e2', 'f1', 'f2', 'g1', 'g2']
        
        # Filter for 5th semester Computer Science Engineering courses
        cse_5th_sem_data = []
        cse_key = None
        
        # Find the key for 5th semester CSE - use exact department name
        for (semester, dept), courses in choice_analysis.items():
            if (str(semester) == '5' and 
                dept == 'Computer Science & Engineering'):  # Use exact match
                cse_key = (semester, dept)
                break
        
        if cse_key and cse_key in choice_analysis:
            for course_code, choice_info in choice_analysis[cse_key].items():
                # Get additional course information from schedule_df
                course_schedule = self.schedule_df[self.schedule_df['course_code'] == course_code]
                course_name = choice_info.get('course_name', course_code)
                
                # Filter macroblock distribution to only include main theory blocks
                filtered_macroblock_dist = {}
                all_teachers = set()
                
                for macroblock, teachers in choice_info['macroblock_distribution'].items():
                    if macroblock in main_theory_blocks:
                        filtered_macroblock_dist[macroblock] = teachers
                        all_teachers.update(teachers)
                
                macroblocks = list(filtered_macroblock_dist.keys())
                
                cse_5th_sem_data.append({
                    'Course Code': course_code,
                    'Course Name': course_name,
                    'Teachers Available': len(all_teachers),
                    'Macroblocks Available': len(macroblocks),
                    'Choice Score': len(all_teachers) * len(macroblocks),
                    'Teacher Options': ', '.join([self._get_teacher_name(t) for t in all_teachers]),
                    'Macroblock Options': ', '.join(sorted(macroblocks)),
                    'Macroblock Distribution': filtered_macroblock_dist
                })
        
        # If no data found in choice_analysis, try to get directly from schedule_df
        if not cse_5th_sem_data and hasattr(self, 'schedule_df') and not self.schedule_df.empty:
            # Get 5th semester CSE courses directly from schedule
            cse_5th_schedule = self.schedule_df[
                (self.schedule_df['semester'] == 5) & 
                (self.schedule_df['course_dept'] == 'Computer Science & Engineering')
            ]
            
            if not cse_5th_schedule.empty:
                for course_code in cse_5th_schedule['course_code'].unique():
                    course_data = cse_5th_schedule[cse_5th_schedule['course_code'] == course_code]
                    course_name = course_data['course_name'].iloc[0]
                    
                    # Filter to only main theory blocks
                    course_data_filtered = course_data[course_data['macroblock'].isin(main_theory_blocks)]
                    
                    teachers = course_data_filtered['teacher_id'].unique()
                    macroblocks = course_data_filtered['macroblock'].unique()
                    
                    # Create macroblock distribution (only main blocks)
                    macroblock_dist = {}
                    for macroblock in macroblocks:
                        mb_data = course_data_filtered[course_data_filtered['macroblock'] == macroblock]
                        macroblock_dist[macroblock] = mb_data['teacher_id'].unique().tolist()
                    
                    cse_5th_sem_data.append({
                        'Course Code': course_code,
                        'Course Name': course_name,
                        'Teachers Available': len(teachers),
                        'Macroblocks Available': len(macroblocks),
                        'Choice Score': len(teachers) * len(macroblocks),
                        'Teacher Options': ', '.join([self._get_teacher_name(t) for t in teachers]),
                        'Macroblock Options': ', '.join(sorted(macroblocks)),
                        'Macroblock Distribution': macroblock_dist
                    })
        
        if cse_5th_sem_data:
            cse_df = pd.DataFrame(cse_5th_sem_data)
            
            # 1. Course-wise teacher availability
            bars1 = ax1.bar(range(len(cse_df)), cse_df['Teachers Available'], 
                           color='lightblue', alpha=0.8, edgecolor='navy')
            ax1.set_title('Teacher Availability for 5th Sem CSE Courses', fontsize=14, fontweight='bold')
            ax1.set_xlabel('Courses')
            ax1.set_ylabel('Number of Teachers Available')
            ax1.set_xticks(range(len(cse_df)))
            ax1.set_xticklabels(cse_df['Course Code'], rotation=45, ha='right')
            
            # Add value labels on bars
            for i, bar in enumerate(bars1):
                height = bar.get_height()
                ax1.text(bar.get_x() + bar.get_width()/2., height + 0.05,
                        f'{int(height)}', ha='center', va='bottom', fontweight='bold')
            
            # 2. Course-wise macroblock availability
            bars2 = ax2.bar(range(len(cse_df)), cse_df['Macroblocks Available'], 
                           color='lightgreen', alpha=0.8, edgecolor='darkgreen')
            ax2.set_title('Main Macroblock Availability for 5th Sem CSE Courses', fontsize=14, fontweight='bold')
            ax2.set_xlabel('Courses')
            ax2.set_ylabel('Number of Main Macroblocks Available')
            ax2.set_xticks(range(len(cse_df)))
            ax2.set_xticklabels(cse_df['Course Code'], rotation=45, ha='right')
            
            # Add value labels on bars
            for i, bar in enumerate(bars2):
                height = bar.get_height()
                ax2.text(bar.get_x() + bar.get_width()/2., height + 0.05,
                        f'{int(height)}', ha='center', va='bottom', fontweight='bold')
            
            # 3. Detailed Macroblock Distribution Heatmap (only main blocks)
            ax3.set_title('Main Macroblock Distribution for Each Course\n(Theory Blocks: a1-g2 only)', fontsize=14, fontweight='bold')
            
            # Create a matrix showing which main blocks each course uses
            all_blocks = set()
            for _, row in cse_df.iterrows():
                all_blocks.update(row['Macroblock Distribution'].keys())
            
            # Filter to only main theory blocks and sort them properly
            all_blocks = [block for block in main_theory_blocks if block in all_blocks]
            
            # Create matrix
            matrix = []
            course_labels = []
            
            for _, row in cse_df.iterrows():
                course_labels.append(f"{row['Course Code']}\n{row['Course Name'][:20]}...")
                block_row = []
                for block in all_blocks:
                    if block in row['Macroblock Distribution']:
                        # Count how many teachers for this course in this block
                        teacher_count = len(row['Macroblock Distribution'][block])
                        block_row.append(teacher_count)
                    else:
                        block_row.append(0)
                matrix.append(block_row)
            
            # Plot heatmap
            if matrix and all_blocks:
                matrix = np.array(matrix)
                im = ax3.imshow(matrix, cmap='YlOrRd', aspect='auto')
                
                # Set ticks and labels
                ax3.set_xticks(range(len(all_blocks)))
                ax3.set_xticklabels(all_blocks, rotation=45, ha='right')
                ax3.set_yticks(range(len(course_labels)))
                ax3.set_yticklabels(course_labels)
                
                # Add text annotations
                for i in range(len(course_labels)):
                    for j in range(len(all_blocks)):
                        if matrix[i, j] > 0:
                            ax3.text(j, i, f'{int(matrix[i, j])}', 
                                   ha='center', va='center', fontweight='bold', color='black')
                
                # Add colorbar
                plt.colorbar(im, ax=ax3, label='Number of Teachers')
            else:
                ax3.text(0.5, 0.5, 'No main macroblock distribution data', 
                        ha='center', va='center', transform=ax3.transAxes)
            
            # 4. Detailed course information table with main block distribution
            ax4.axis('tight')
            ax4.axis('off')
            
            # Create a detailed summary table
            table_data = []
            for _, row in cse_df.iterrows():
                # Format main macroblock distribution only
                block_dist = row['Macroblock Distribution']
                block_summary = []
                for block, teachers in sorted(block_dist.items()):
                    if block in main_theory_blocks:  # Only include main blocks
                        block_summary.append(f"{block}({len(teachers)}T)")
                
                blocks_text = ', '.join(block_summary[:8])  # Limit to first 8 blocks
                if len(block_summary) > 8:
                    blocks_text += f"... +{len(block_summary)-8} more"
                
                table_data.append([
                    row['Course Code'],
                    row['Course Name'][:30] + '...' if len(row['Course Name']) > 30 else row['Course Name'],
                    f"{row['Teachers Available']}",
                    f"{row['Macroblocks Available']}",
                    blocks_text
                ])
            
            table = ax4.table(cellText=table_data,
                             colLabels=['Code', 'Course Name', 'Teachers', 'Main Blocks', 'Main Block Distribution (Block(Teachers))'],
                             cellLoc='left',
                             loc='center',
                             bbox=[0, 0, 1, 1])
            
            table.auto_set_font_size(False)
            table.set_fontsize(8)
            table.scale(1, 2.5)
            
            # Style the table
            for i in range(len(table_data) + 1):
                for j in range(5):
                    cell = table[(i, j)]
                    if i == 0:  # Header row
                        cell.set_facecolor('#4CAF50')
                        cell.set_text_props(weight='bold', color='white')
                    else:
                        if i % 2 == 0:
                            cell.set_facecolor('#F5F5F5')
                        else:
                            cell.set_facecolor('#FFFFFF')
            
            ax4.set_title('5th Semester CSE Course - Main Block Distribution Details', fontsize=14, fontweight='bold', pad=20)
            
            # Add summary statistics with main block distribution info
            avg_teachers = cse_df['Teachers Available'].mean()
            avg_blocks = cse_df['Macroblocks Available'].mean()
            avg_flexibility = cse_df['Choice Score'].mean()
            
            # Create detailed main block distribution summary
            block_usage_summary = {}
            for _, row in cse_df.iterrows():
                for block in row['Macroblock Distribution'].keys():
                    if block in main_theory_blocks:  # Only count main blocks
                        if block not in block_usage_summary:
                            block_usage_summary[block] = 0
                        block_usage_summary[block] += 1
            
            most_used_blocks = sorted(block_usage_summary.items(), key=lambda x: x[1], reverse=True)[:5]
            
            summary_text = f"""
Summary for 5th Semester Computer Science Engineering Students:

📚 Total Courses Available: {len(cse_df)}
👨‍🏫 Average Teachers per Course: {avg_teachers:.1f}
🏗️ Average Main Macroblocks per Course: {avg_blocks:.1f}
⭐ Average Flexibility Score: {avg_flexibility:.1f}

Most Used Main Macroblocks:
            """
            
            for block, count in most_used_blocks:
                summary_text += f"\n  • {block}: Used by {count} course(s)"
            
            summary_text += f"\n\nCourse Details (Main Blocks Only):"
            # Add course details with their main blocks only
            for _, row in cse_df.iterrows():
                main_blocks_only = [block for block in row['Macroblock Distribution'].keys() if block in main_theory_blocks][:3]
                summary_text += f"\n• {row['Course Code']}: {', '.join(main_blocks_only)}"
                if len([block for block in row['Macroblock Distribution'].keys() if block in main_theory_blocks]) > 3:
                    summary_text += f" (+{len([block for block in row['Macroblock Distribution'].keys() if block in main_theory_blocks])-3} more)"
            
            summary_text += f"\n\nNote: Only showing main theory blocks (a1-g2)."
            summary_text += f"\nTutorial blocks (ta1, taa1, etc.) are derived from main blocks."
            
            # Add this as a text box
            fig.text(0.02, 0.02, summary_text, fontsize=9, 
                    bbox=dict(boxstyle="round,pad=0.5", facecolor='lightblue', alpha=0.7),
                    verticalalignment='bottom')
            
        else:
            # No 5th semester CSE data found
            for ax in [ax1, ax2, ax3, ax4]:
                ax.text(0.5, 0.5, 'No 5th Semester CSE Data Found', 
                       ha='center', va='center', transform=ax.transAxes, 
                       fontsize=16, color='red')
                ax.set_title('5th Semester CSE Course Analysis')
        
        plt.suptitle('5th Semester Computer Science Engineering - Main Block Distribution Analysis\n(Theory Blocks: a1, a2, b1, b2, c1, c2, d1, d2, e1, e2, f1, f2, g1, g2)', 
                     fontsize=16, fontweight='bold', y=0.95)
        plt.tight_layout()
        plt.subplots_adjust(bottom=0.35)  # Make room for summary text
        plt.savefig(os.path.join(self.output_dir, '5th_sem_cse_student_choices.png'), 
                   dpi=300, bbox_inches='tight')
        plt.close()

    def _plot_violations_summary(self, macroblock_analysis):
        """Plot summary of constraint violations."""
        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(16, 12))
        
        # Count violations
        violation_summary = {
            'No Violations': 0,
            'Course Repetitions': 0,
            'Teacher Repetitions': 0,
            'Both Violations': 0
        }
        
        macroblock_violations = {}
        
        for mb, analysis in macroblock_analysis.items():
            course_violations = any(count > 1 for count in analysis['course_counts'].values())
            teacher_violations = any(count > 1 for count in analysis['teacher_counts'].values())
            
            macroblock_violations[mb] = {
                'course_violations': course_violations,
                'teacher_violations': teacher_violations
            }
            
            if not course_violations and not teacher_violations:
                violation_summary['No Violations'] += 1
            elif course_violations and teacher_violations:
                violation_summary['Both Violations'] += 1
            elif course_violations:
                violation_summary['Course Repetitions'] += 1
            elif teacher_violations:
                violation_summary['Teacher Repetitions'] += 1
        
        # Violation summary pie chart
        labels = list(violation_summary.keys())
        sizes = list(violation_summary.values())
        colors = ['lightgreen', 'orange', 'red', 'darkred']
        
        ax1.pie(sizes, labels=labels, colors=colors, autopct='%1.1f%%', startangle=90)
        ax1.set_title('Constraint Violation Summary')
        
        # Macroblock violation status
        violation_status = []
        for mb, violations in macroblock_violations.items():
            if violations['course_violations'] or violations['teacher_violations']:
                violation_status.append(f"{mb} ❌")
            else:
                violation_status.append(f"{mb} ✅")
        
        # Show violation status as text
        violation_text = "\n".join(violation_status)
        ax2.text(0.1, 0.9, "Macroblock Status:", transform=ax2.transAxes, fontsize=12, fontweight='bold')
        ax2.text(0.1, 0.1, violation_text, transform=ax2.transAxes, fontsize=10, verticalalignment='bottom')
        ax2.set_xlim(0, 1)
        ax2.set_ylim(0, 1)
        ax2.axis('off')
        ax2.set_title('Individual Macroblock Status')
        
        # Calculate constraint effectiveness
        total_macroblocks = len(macroblock_analysis)
        clean_macroblocks = violation_summary['No Violations']
        effectiveness = (clean_macroblocks / total_macroblocks) * 100 if total_macroblocks > 0 else 0
        
        ax3.bar(['Constraint Effectiveness'], [effectiveness], color='lightblue', alpha=0.7)
        ax3.set_ylim(0, 100)
        ax3.set_ylabel('Percentage')
        ax3.set_title(f'Overall Constraint Effectiveness: {effectiveness:.1f}%')
        
        # Add percentage text
        ax3.text(0, effectiveness + 2, f'{effectiveness:.1f}%', ha='center', fontsize=14, fontweight='bold')
        
        # Summary statistics
        stats_text = f"""
Total Macroblocks: {total_macroblocks}
Clean Macroblocks: {clean_macroblocks}
With Violations: {total_macroblocks - clean_macroblocks}

Course Diversity: ✅
Teacher Diversity: ✅
Semester Grouping: ✅
Combined Shift System: ✅
        """
        
        ax4.text(0.1, 0.5, stats_text, transform=ax4.transAxes, fontsize=12, verticalalignment='center')
        ax4.set_xlim(0, 1)
        ax4.set_ylim(0, 1)
        ax4.axis('off')
        ax4.set_title('Summary Statistics')
        
        plt.tight_layout()
        plt.savefig(os.path.join(self.output_dir, 'violations_summary.png'), dpi=300, bbox_inches='tight')
        plt.close()

    def _plot_macroblock_grid(self, macroblock_analysis):
        """Create a detailed grid view of all macroblocks."""
        fig, ax = plt.subplots(figsize=(20, 12))
        
        # Create grid layout
        macroblocks = sorted(macroblock_analysis.keys())
        num_blocks = len(macroblocks)
        
        # Calculate grid dimensions
        cols = min(7, num_blocks)  # Max 7 columns
        rows = (num_blocks + cols - 1) // cols
        
        for i, mb in enumerate(macroblocks):
            row = i // cols
            col = i % cols
            
            analysis = macroblock_analysis[mb]
            
            # Create a subplot for each macroblock
            rect_x = col / cols
            rect_y = 1 - (row + 1) / rows
            rect_width = 1 / cols
            rect_height = 1 / rows
            
            # Draw rectangle for macroblock
            rect = plt.Rectangle((rect_x, rect_y), rect_width, rect_height, 
                               linewidth=2, edgecolor='black', facecolor='lightblue', alpha=0.3)
            ax.add_patch(rect)
            
            # Add macroblock label
            ax.text(rect_x + rect_width/2, rect_y + rect_height - 0.02, mb, 
                   ha='center', va='top', fontsize=14, fontweight='bold')
            
            # Add course and teacher info
            info_text = f"Courses: {analysis['num_courses']}\nTeachers: {analysis['num_teachers']}"
            ax.text(rect_x + rect_width/2, rect_y + rect_height/2, info_text, 
                   ha='center', va='center', fontsize=10)
            
            # Add semester info
            semester_values = [str(s) for s in set(analysis['semesters']) if s != "Unknown"]
            sorted_semesters = sorted(semester_values, key=lambda x: int(x) if x.isdigit() else float('inf'))
            if "Unknown" in analysis['semesters']:
                sorted_semesters.append("Unknown")
            sem_text = f"Sem: {', '.join(sorted_semesters)}"
            ax.text(rect_x + rect_width/2, rect_y + 0.02, sem_text, 
                   ha='center', va='bottom', fontsize=8, style='italic')
            
            # Color code by violation status
            has_violations = (any(count > 1 for count in analysis['course_counts'].values()) or 
                            any(count > 1 for count in analysis['teacher_counts'].values()))
            
            if has_violations:
                rect.set_facecolor('lightcoral')
                rect.set_alpha(0.5)
        
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.set_aspect('equal')
        ax.axis('off')
        ax.set_title('Macroblock Grid Overview\n(Red = Constraint Violations, Blue = Clean)', 
                    fontsize=16, fontweight='bold', pad=20)
        
        plt.tight_layout()
        plt.savefig(os.path.join(self.output_dir, 'macroblock_grid_overview.png'), dpi=300, bbox_inches='tight')
        plt.close()

    def generate_detailed_report(self, macroblock_analysis, choice_analysis):
        """Generate a detailed text report of the analysis."""
        report_path = os.path.join(self.output_dir, 'grouping_constraint_report.txt')
        
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write("SEMESTER AND DEPARTMENT GROUPING CONSTRAINT ANALYSIS REPORT\n")
            f.write("=" * 70 + "\n\n")
            
            f.write("EXECUTIVE SUMMARY\n")
            f.write("-" * 20 + "\n")
            
            total_macroblocks = len(macroblock_analysis)
            clean_macroblocks = sum(1 for analysis in macroblock_analysis.values() 
                                  if not any(count > 1 for count in analysis['course_counts'].values()) and
                                     not any(count > 1 for count in analysis['teacher_counts'].values()))
            
            f.write(f"Total Macroblocks Analyzed: {total_macroblocks}\n")
            f.write(f"Macroblocks without violations: {clean_macroblocks}\n")
            f.write(f"Constraint Effectiveness: {(clean_macroblocks/total_macroblocks)*100:.1f}%\n")
            f.write(f"System Type: Combined Shift System (Simplified)\n\n")
            
            f.write("DETAILED MACROBLOCK ANALYSIS\n")
            f.write("-" * 30 + "\n\n")
            
            for mb, analysis in sorted(macroblock_analysis.items()):
                f.write(f"Macroblock {mb}:\n")
                f.write(f"  Courses ({analysis['num_courses']}): {', '.join(analysis['courses'])}\n")
                f.write(f"  Teachers ({analysis['num_teachers']}): {', '.join(map(str, analysis['teachers']))}\n")
                
                # Fix the sorting issue by converting all semester values to strings first
                semester_values = [str(s) for s in set(analysis['semesters']) if s != "Unknown"]
                # Sort as strings, then convert back to display format
                sorted_semesters = sorted(semester_values, key=lambda x: int(x) if x.isdigit() else float('inf'))
                if "Unknown" in analysis['semesters']:
                    sorted_semesters.append("Unknown")
                
                f.write(f"  Semesters: {', '.join(sorted_semesters)}\n")
                f.write(f"  Departments: {', '.join(analysis['departments'])}\n")
                
                # Check violations
                course_violations = [course for course, count in analysis['course_counts'].items() if count > 1]
                teacher_violations = [teacher for teacher, count in analysis['teacher_counts'].items() if count > 1]
                
                if course_violations or teacher_violations:
                    f.write(f"  VIOLATIONS DETECTED:\n")
                    if course_violations:
                        f.write(f"    - Repeated courses: {course_violations}\n")
                    if teacher_violations:
                        f.write(f"    - Repeated teachers: {teacher_violations}\n")
                else:
                    f.write(f"  No constraint violations\n")
                
                f.write(f"  Teacher-Course pairs:\n")
                for pair in analysis['teacher_course_pairs']:
                    teacher_name = self._get_teacher_name(pair['teacher_id'])
                    f.write(f"    - Teacher {pair['teacher_id']} ({teacher_name}) -> {pair['course_code']}\n")
                
                f.write("\n")
            
            f.write("STUDENT CHOICE ANALYSIS\n")
            f.write("-" * 25 + "\n\n")
            
            for (semester, dept), courses in choice_analysis.items():
                f.write(f"Semester {semester} - {dept}:\n")
                for course_code, choice_info in courses.items():
                    f.write(f"  {course_code} ({choice_info['course_name']}):\n")
                    f.write(f"    - Teachers available: {choice_info['total_teachers']}\n")
                    f.write(f"    - Macroblocks used: {choice_info['total_macroblocks']}\n")
                    f.write(f"    - Choice score: {choice_info['total_teachers'] * choice_info['total_macroblocks']}\n")
                    
                    for mb, teachers in choice_info['macroblock_distribution'].items():
                        teacher_names = [self._get_teacher_name(t) for t in teachers]
                        f.write(f"    - {mb}: {', '.join(teacher_names)}\n")
                f.write("\n")
            
            f.write("SYSTEM NOTES\n")
            f.write("-" * 12 + "\n")
            f.write("• Combined shift system: All teachers use unified shift\n")
            f.write("• 3-lecture courses: 2 lectures + 1 tutorial (3rd hour)\n")
            f.write("• Tutorial blocks (ta1/tb1/tc1 etc.) used as 3rd lecture hour\n")
            f.write("• Lab allocation skipped in current implementation\n")
            f.write("• Theory-only scheduling with classroom assignments\n\n")
        
        print(f"\nDetailed report saved to: {report_path}")

def main():
    """Main function to run the grouping analysis."""
    
    # Find the most recent schedule file
    output_dirs = glob.glob('output/macroblock_schedule_*')
    if not output_dirs:
        print("No schedule output directories found!")
        return
    
    latest_dir = max(output_dirs, key=os.path.getmtime)
    schedule_file = os.path.join(latest_dir, 'macroblock_schedule.csv')
    
    # Use the correct course file name
    courses_file = 'data/mapped_data/computer_dept_teacher_courses.csv'
    
    if not os.path.exists(schedule_file):
        print(f"Schedule file not found: {schedule_file}")
        return
    
    if not os.path.exists(courses_file):
        print(f"Courses file not found: {courses_file}")
        # Try alternative file name as fallback
        courses_file = 'data/mapped_data/cs_teacher_courses.csv'
        if not os.path.exists(courses_file):
            print(f"Alternative courses file also not found: {courses_file}")
            return
    
    print(f"Analyzing schedule from: {schedule_file}")
    print(f"Using course data from: {courses_file}")
    
    # Create analyzer
    analyzer = SemesterGroupingAnalyzer(schedule_file, courses_file)
    
    # Run analysis
    macroblock_analysis = analyzer.analyze_macroblock_grouping()
    choice_analysis = analyzer.analyze_student_choice_optimization()
    
    # Create visualizations
    analyzer.create_visualizations(macroblock_analysis, choice_analysis)
    
    # Generate detailed report
    analyzer.generate_detailed_report(macroblock_analysis, choice_analysis)
    
    print(f"\nAnalysis complete! Results saved to: {analyzer.output_dir}")
    print("\nGenerated files:")
    print("- macroblock_distribution.png")
    print("- teacher_diversity_analysis.png") 
    print("- semester_grouping_analysis.png")
    print("- student_choice_analysis.png")
    print("- violations_summary.png")
    print("- macroblock_grid_overview.png")
    print("- grouping_constraint_report.txt")

if __name__ == "__main__":
    main() 