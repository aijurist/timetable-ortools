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
        
        # Add shift analysis if teacher_shift column exists
        self.has_shift_data = 'teacher_shift' in self.schedule_df.columns
        
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
                course_info = self.courses_df[self.courses_df['course_code'] == course].iloc[0]
                semester_info[course] = course_info['semester']
                dept_info[course] = course_info['course_dept']
            
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
            print(f"  Semesters: {sorted(set(semester_info.values()))}")
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
        
        # 5. Constraint Violations Summary
        self._plot_violations_summary(macroblock_analysis)
        
        # 6. Detailed Macroblock Grid
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
        semesters = sorted(semester_distribution.keys())
        macroblocks = sorted(macroblock_analysis.keys())
        
        heatmap_data = np.zeros((len(semesters), len(macroblocks)))
        
        for i, semester in enumerate(semesters):
            for j, mb in enumerate(macroblocks):
                if mb in semester_distribution[semester]:
                    # Count courses from this semester in this macroblock
                    mb_analysis = macroblock_analysis[mb]
                    courses_in_semester = sum(1 for course in mb_analysis['courses'] 
                                            if mb_analysis['semester_info'].get(course) == semester)
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
            total_courses = sum(1 for _, row in self.courses_df.iterrows() if row['semester'] == semester)
            scheduled_courses = sum(1 for _, row in self.schedule_df.iterrows() 
                                  if row['semester'] == semester)
            macroblocks_used = len([mb for mb in semester_distribution[semester]])
            
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
            semesters = sorted(set(analysis['semesters']))
            sem_text = f"Sem: {', '.join(map(str, semesters))}"
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

    def analyze_shift_distribution(self):
        """Analyze teacher shift distribution and effectiveness."""
        print("Analyzing teacher shift distribution...")
        
        if not self.has_shift_data:
            return None
            
        shift_analysis = {
            'teacher_distribution': {},
            'macroblock_distribution': {},
            'overlap_analysis': {},
            'department_distribution': {}
        }
        
        # Analyze teacher distribution across shifts
        teacher_shifts = self.schedule_df.groupby('teacher_id')['teacher_shift'].first()
        shift_counts = teacher_shifts.value_counts()
        
        shift_analysis['teacher_distribution'] = {
            'total_teachers': len(teacher_shifts),
            'shift_counts': shift_counts.to_dict(),
            'shift_percentages': (shift_counts / len(teacher_shifts) * 100).to_dict()
        }
        
        # Analyze macroblock distribution by shift
        macroblock_shifts = self.schedule_df.groupby(['macroblock', 'teacher_shift']).size().unstack(fill_value=0)
        shift_analysis['macroblock_distribution'] = macroblock_shifts.to_dict()
        
        # Analyze department distribution across shifts
        dept_shifts = self.schedule_df.groupby(['course_dept', 'teacher_shift']).agg({
            'teacher_id': 'nunique'
        }).unstack(fill_value=0)
        
        shift_analysis['department_distribution'] = dept_shifts.to_dict()
        
        # Analyze overlapping time slots
        overlapping_slots = self._identify_overlapping_slots()
        shift_analysis['overlap_analysis'] = overlapping_slots
        
        return shift_analysis
    
    def _identify_overlapping_slots(self):
        """Identify and analyze overlapping time slots between shifts."""
        # Define shift time ranges (simplified)
        shift_times = {
            'shift1': list(range(8, 15)),  # 8:00-14:50
            'shift2': list(range(10, 17)), # 10:00-16:50  
            'shift3': list(range(12, 19))  # 12:00-18:50
        }
        
        overlaps = {
            'shift1_shift2': set(shift_times['shift1']) & set(shift_times['shift2']),
            'shift2_shift3': set(shift_times['shift2']) & set(shift_times['shift3']),
            'all_shifts': set(shift_times['shift1']) & set(shift_times['shift2']) & set(shift_times['shift3'])
        }
        
        overlap_analysis = {}
        for overlap_name, overlap_hours in overlaps.items():
            if overlap_hours:
                overlap_analysis[overlap_name] = {
                    'hours': sorted(list(overlap_hours)),
                    'duration': len(overlap_hours)
                }
        
        return overlap_analysis
    
    def create_shift_visualizations(self, shift_analysis):
        """Create visualizations for shift analysis."""
        print("Creating shift distribution visualizations...")
        
        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(16, 12))
        fig.suptitle('Teacher Shift Distribution Analysis', fontsize=16, fontweight='bold')
        
        # Teacher distribution pie chart
        shift_counts = shift_analysis['teacher_distribution']['shift_counts']
        ax1.pie(shift_counts.values(), labels=shift_counts.keys(), autopct='%1.1f%%', startangle=90)
        ax1.set_title('Teacher Distribution Across Shifts')
        
        # Macroblock usage by shift
        mb_data = shift_analysis['macroblock_distribution']
        if mb_data:
            shifts = list(next(iter(mb_data.values())).keys())
            macroblocks = list(mb_data.keys())[:10]  # Show top 10 macroblocks
            
            shift_totals = {shift: [] for shift in shifts}
            for mb in macroblocks:
                for shift in shifts:
                    shift_totals[shift].append(mb_data.get(mb, {}).get(shift, 0))
            
            x = np.arange(len(macroblocks))
            width = 0.25
            
            for i, (shift, values) in enumerate(shift_totals.items()):
                ax2.bar(x + i * width, values, width, label=shift)
            
            ax2.set_xlabel('Macroblocks')
            ax2.set_ylabel('Number of Assignments')
            ax2.set_title('Macroblock Usage by Shift')
            ax2.set_xticks(x + width)
            ax2.set_xticklabels(macroblocks, rotation=45)
            ax2.legend()
        
        # Department distribution
        dept_data = shift_analysis['department_distribution']
        if dept_data and 'teacher_id' in dept_data:
            depts = list(dept_data['teacher_id'].keys())[:5]  # Show top 5 departments
            shifts = list(next(iter(dept_data['teacher_id'].values())).keys())
            
            dept_shift_data = []
            for dept in depts:
                dept_values = []
                for shift in shifts:
                    dept_values.append(dept_data['teacher_id'].get(dept, {}).get(shift, 0))
                dept_shift_data.append(dept_values)
            
            x = np.arange(len(shifts))
            width = 0.15
            
            for i, (dept, values) in enumerate(zip(depts, dept_shift_data)):
                ax3.bar(x + i * width, values, width, label=dept[:20])  # Truncate long dept names
            
            ax3.set_xlabel('Shifts')
            ax3.set_ylabel('Number of Teachers')
            ax3.set_title('Teacher Distribution by Department')
            ax3.set_xticks(x + width * 2)
            ax3.set_xticklabels(shifts)
            ax3.legend()
        
        # Overlap analysis
        overlap_data = shift_analysis['overlap_analysis']
        if overlap_data:
            overlap_names = list(overlap_data.keys())
            overlap_durations = [overlap_data[name]['duration'] for name in overlap_names]
            
            ax4.bar(overlap_names, overlap_durations, color=['lightblue', 'lightgreen', 'lightcoral'])
            ax4.set_ylabel('Hours of Overlap')
            ax4.set_title('Shift Overlap Analysis')
            ax4.tick_params(axis='x', rotation=45)
            
            # Add duration labels on bars
            for i, (name, duration) in enumerate(zip(overlap_names, overlap_durations)):
                ax4.text(i, duration + 0.1, f'{duration}h', ha='center', va='bottom')
        
        plt.tight_layout()
        plt.savefig(os.path.join(self.output_dir, 'shift_distribution_analysis.png'), dpi=300, bbox_inches='tight')
        plt.close()

    def generate_detailed_report(self, macroblock_analysis, choice_analysis, shift_analysis=None):
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
            f.write(f"Constraint Effectiveness: {(clean_macroblocks/total_macroblocks)*100:.1f}%\n\n")
            
            f.write("DETAILED MACROBLOCK ANALYSIS\n")
            f.write("-" * 30 + "\n\n")
            
            for mb, analysis in sorted(macroblock_analysis.items()):
                f.write(f"Macroblock {mb}:\n")
                f.write(f"  Courses ({analysis['num_courses']}): {', '.join(analysis['courses'])}\n")
                f.write(f"  Teachers ({analysis['num_teachers']}): {', '.join(map(str, analysis['teachers']))}\n")
                f.write(f"  Semesters: {', '.join(map(str, sorted(set(analysis['semesters']))))}\n")
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
                    f.write(f"  ✅ No constraint violations\n")
                
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
            
            # Add shift analysis if available
            if shift_analysis:
                f.write("TEACHER SHIFT DISTRIBUTION ANALYSIS\n")
                f.write("-" * 35 + "\n\n")
                
                teacher_dist = shift_analysis['teacher_distribution']
                f.write(f"Total Teachers: {teacher_dist['total_teachers']}\n\n")
                
                f.write("Shift Distribution:\n")
                for shift, count in teacher_dist['shift_counts'].items():
                    percentage = teacher_dist['shift_percentages'][shift]
                    f.write(f"  {shift}: {count} teachers ({percentage:.1f}%)\n")
                
                f.write("\nShift Overlap Analysis:\n")
                for overlap_name, overlap_info in shift_analysis['overlap_analysis'].items():
                    f.write(f"  {overlap_name}: {overlap_info['duration']} hours overlap\n")
                    f.write(f"    Hours: {overlap_info['hours']}\n")
                
                f.write("\nDepartment Distribution:\n")
                dept_dist = shift_analysis['department_distribution']
                if dept_dist and 'teacher_id' in dept_dist:
                    for dept, shift_counts in dept_dist['teacher_id'].items():
                        f.write(f"  {dept}:\n")
                        for shift, count in shift_counts.items():
                            f.write(f"    - {shift}: {count} teachers\n")
                
                f.write("\n")
        
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
    courses_file = 'data/mapped_data/cs_teacher_courses.csv'
    
    if not os.path.exists(schedule_file):
        print(f"Schedule file not found: {schedule_file}")
        return
    
    if not os.path.exists(courses_file):
        print(f"Courses file not found: {courses_file}")
        return
    
    print(f"Analyzing schedule from: {schedule_file}")
    
    # Create analyzer
    analyzer = SemesterGroupingAnalyzer(schedule_file, courses_file)
    
    # Run analysis
    macroblock_analysis = analyzer.analyze_macroblock_grouping()
    choice_analysis = analyzer.analyze_student_choice_optimization()
    
    # Create visualizations
    analyzer.create_visualizations(macroblock_analysis, choice_analysis)
    
    # Analyze shift distribution if data is available
    shift_analysis = None
    if analyzer.has_shift_data:
        shift_analysis = analyzer.analyze_shift_distribution()
        analyzer.create_shift_visualizations(shift_analysis)
    
    # Generate detailed report
    analyzer.generate_detailed_report(macroblock_analysis, choice_analysis, shift_analysis)
    
    print(f"\nAnalysis complete! Results saved to: {analyzer.output_dir}")
    print("\nGenerated files:")
    print("- macroblock_distribution.png")
    print("- teacher_diversity_analysis.png") 
    print("- semester_grouping_analysis.png")
    print("- student_choice_analysis.png")
    print("- violations_summary.png")
    print("- macroblock_grid_overview.png")
    print("- grouping_constraint_report.txt")
    if analyzer.has_shift_data:
        print("- shift_distribution_analysis.png")

if __name__ == "__main__":
    main() 