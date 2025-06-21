#!/usr/bin/env python3
"""
Biotechnology Data Test for CourseGroupOptimizer

Tests the OR-Tools optimizer with real Biotechnology course data
and generates heatmap visualizations.
"""

import os
import sys
import pandas as pd
import numpy as np
import logging
import json
from datetime import datetime
from collections import defaultdict
import matplotlib.pyplot as plt
import seaborn as sns
from course_group_optimizer import CourseGroupOptimizer


class BiotechnologyDataTester:
    """Test the CourseGroupOptimizer with Biotechnology course data."""
    
    def __init__(self, csv_file_path="data/department_data/Computing_main.csv"):
        self.csv_file_path = csv_file_path
        self.output_dir = "biotechnology_optimization_results"
        self.viz_dir = os.path.join(self.output_dir, "visualizations")
        
        # Setup directories
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.viz_dir, exist_ok=True)
        
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(os.path.join(self.output_dir, 'optimization.log')),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
        
        # Results storage
        self.results = {}
        self.data_by_dept_sem = {}
    
    def load_data(self):
        """Load and process the Biotechnology CSV data."""
        self.logger.info(f"Loading data from {self.csv_file_path}")
        
        try:
            df = pd.read_csv(self.csv_file_path)
            self.logger.info(f"Loaded {len(df)} course instances")
            
            # Group by student department and semester (students taking the courses)
            grouped = df.groupby(['student_dept', 'semester'])
            
            for (dept, semester), group_df in grouped:
                instances = self._convert_to_optimizer_format(group_df)
                if instances:
                    self.data_by_dept_sem[(dept, semester)] = instances
                    self.logger.info(f"Processed {len(instances)} instances for {dept} Semester {semester}")
            
            self.logger.info(f"Total department-semester combinations: {len(self.data_by_dept_sem)}")
            
        except Exception as e:
            self.logger.error(f"Error loading data: {e}")
            raise
    
    def _convert_to_optimizer_format(self, df):
        """Convert DataFrame to optimizer format."""
        instances = []
        
        for _, row in df.iterrows():
            try:
                # Determine course characteristics
                has_lab = row['course_type'] in ['L', 'LoT'] or row['practical_hours'] > 0
                has_theory = row['course_type'] in ['T', 'LoT'] or row['lecture_hours'] > 0 or row['tutorial_hours'] > 0
                

                
                instance = {
                    'id': int(row['id']),
                    'teacher_id': str(row['teacher_id']).strip(),
                    'course_id': row.get('course_id', row['id']),
                    'course_code': str(row['course_code']).strip(),
                    'course_name': str(row['course_name']).strip(),
                    'course_type': str(row.get('course_type', 'T')).strip(),
                    'lecture_hours': int(row.get('lecture_hours', 0)),
                    'tutorial_hours': int(row.get('tutorial_hours', 0)),
                    'practical_hours': int(row.get('practical_hours', 0)),
                    'student_count': int(row.get('student_count', 70)),
                    'semester': row.get('semester', 1),
                    'course_dept': row.get('course_dept', 'Computer Science & Engineering'),
                    'student_dept': row.get('student_dept', 'Computer Science & Engineering'),
                    'has_lab': has_lab,
                    'has_theory': has_theory,
                    'credits': float(row.get('credits', 3.0))
                }
                
                instances.append(instance)
                
            except Exception as e:
                self.logger.warning(f"Skipping row {row.get('id', 'unknown')}: {e}")
                continue
        
        return instances
    
    def run_all_optimizations(self):
        """Run optimization for all department-semester combinations."""
        self.logger.info("="*60)
        self.logger.info("STARTING BIOTECHNOLOGY OPTIMIZATION TESTS")
        self.logger.info("="*60)
        
        total = len(self.data_by_dept_sem)
        successful = 0
        
        for i, ((dept, semester), instances) in enumerate(self.data_by_dept_sem.items(), 1):
            self.logger.info(f"\n[{i}/{total}] Optimizing {dept} Semester {semester}")
            self.logger.info(f"Course instances: {len(instances)}")
            
            # Create optimizer
            optimizer = CourseGroupOptimizer(
                courses=instances,
                dept=dept,
                semester=semester,
                logger=self.logger
            )
            
            # Run optimization
            if optimizer.optimize_distribution() and optimizer.validate_solution():
                successful += 1
                self.results[(dept, semester)] = {
                    'optimizer': optimizer,
                    'groups': optimizer.get_groups(),
                    'objective_value': optimizer.objective_value,
                    'success': True
                }
                
                # Save individual result
                filename = f"optimization_{dept.replace(' ', '_')}_S{semester}.json"
                optimizer.save_results(os.path.join(self.output_dir, filename))
                
                self.logger.info(f"SUCCESS - Objective: {optimizer.objective_value}")
            else:
                self.results[(dept, semester)] = {'success': False}
                self.logger.error(f"FAILED")
        
        success_rate = (successful / total * 100) if total > 0 else 0
        self.logger.info(f"\nRESULTS: {successful}/{total} successful ({success_rate:.1f}%)")
        
        return successful > 0
    
    def generate_heatmaps(self):
        """Generate heatmap visualizations for all successful optimizations."""
        self.logger.info("Generating heatmap visualizations...")
        
        successful_results = [(key, result) for key, result in self.results.items() if result.get('success', False)]
        
        if not successful_results:
            self.logger.warning("No successful results to visualize")
            return
        
        for (dept, semester), result in successful_results:
            self._create_heatmap(dept, semester, result['groups'])
        
        # Create overview
        self._create_overview_heatmap(successful_results)
        
        self.logger.info(f"Generated {len(successful_results)} individual heatmaps plus overview")
    
    def _create_heatmap(self, dept, semester, groups):
        """Create heatmap for a specific department-semester combination."""
        try:
            if not groups:
                return
            
            # Prepare data
            course_group_matrix = {}
            all_courses = set()
            group_names = []
            lab_courses = set()
            theory_courses = set()
            
            for group_idx, group in enumerate(groups):
                if not group:
                    continue
                
                group_name = f"G{group_idx + 1}"
                group_names.append(group_name)
                
                course_teacher_counts = {}
                for instance in group:
                    course_code = instance['course_code']
                    teacher_id = instance['teacher_id']
                    all_courses.add(course_code)
                    
                    if instance.get('has_lab', False):
                        lab_courses.add(course_code)
                    if instance.get('has_theory', False):
                        theory_courses.add(course_code)
                    
                    if course_code not in course_teacher_counts:
                        course_teacher_counts[course_code] = set()
                    course_teacher_counts[course_code].add(teacher_id)
                
                for course_code, teachers in course_teacher_counts.items():
                    if course_code not in course_group_matrix:
                        course_group_matrix[course_code] = {}
                    course_group_matrix[course_code][group_name] = len(teachers)
            
            if not all_courses or not group_names:
                return
            
            # Create matrix
            courses_list = sorted(list(all_courses))
            matrix_data = []
            
            for course in courses_list:
                row = []
                for group_name in group_names:
                    count = course_group_matrix.get(course, {}).get(group_name, 0)
                    row.append(count)
                matrix_data.append(row)
            
            # Create figure
            plt.figure(figsize=(max(10, len(group_names) * 1.5), max(8, len(courses_list) * 0.5)))
            
            matrix_array = np.array(matrix_data)
            
            # Create heatmap
            ax = sns.heatmap(matrix_array,
                           xticklabels=group_names,
                           yticklabels=courses_list,
                           annot=True,
                           fmt='d',
                           cmap='viridis',
                           cbar_kws={'label': 'Teacher Assignments'},
                           linewidths=0.5)
            
            # Styling
            plt.title(f'OR-Tools Optimized Course-Group Distribution\n{dept} - Semester {semester}',
                     fontsize=14, fontweight='bold', pad=20)
            plt.xlabel('Groups', fontsize=12, fontweight='bold')
            plt.ylabel('Courses', fontsize=12, fontweight='bold')
            
            # Add course type annotations
            for i, course in enumerate(courses_list):
                course_types = []
                if course in lab_courses:
                    course_types.append('L')
                if course in theory_courses:
                    course_types.append('T')
                
                if course_types:
                    type_str = '+'.join(course_types)
                    plt.text(-0.8, i + 0.5, f'[{type_str}]',
                           ha='right', va='center', fontsize=8,
                           bbox=dict(boxstyle="round,pad=0.2", facecolor="lightblue", alpha=0.7))
            
            # Statistics
            total_assignments = np.sum(matrix_array)
            courses_with_choice = sum(1 for course in courses_list
                                    if sum(course_group_matrix.get(course, {}).values()) > 1)
            choice_percentage = (courses_with_choice / len(courses_list) * 100) if courses_list else 0
            
            stats_text = f'Courses: {len(courses_list)} ({len(lab_courses)} lab, {len(theory_courses)} theory)\n'
            stats_text += f'Groups: {len(group_names)}, Total assignments: {total_assignments}\n'
            stats_text += f'Courses with choice: {courses_with_choice} ({choice_percentage:.1f}%)'
            
            plt.figtext(0.02, 0.02, stats_text, fontsize=9,
                       bbox=dict(boxstyle="round,pad=0.3", facecolor="lightgray", alpha=0.8))
            
            plt.tight_layout()
            
            # Save
            safe_dept_name = dept.replace(" ", "_").replace("&", "and")
            filename = f'heatmap_{safe_dept_name}_S{semester}.png'
            filepath = os.path.join(self.viz_dir, filename)
            plt.savefig(filepath, dpi=300, bbox_inches='tight')
            plt.close()
            
            self.logger.info(f"Heatmap saved: {filename}")
            
        except Exception as e:
            self.logger.error(f"Error creating heatmap for {dept} S{semester}: {e}")
    
    def _create_overview_heatmap(self, successful_results):
        """Create overview heatmap showing all results."""
        try:
            if not successful_results:
                return
            
            # Create subplots
            n_results = len(successful_results)
            cols = min(2, n_results)
            rows = (n_results + cols - 1) // cols
            
            fig, axes = plt.subplots(rows, cols, figsize=(cols * 8, rows * 6))
            if n_results == 1:
                axes = [axes]
            elif rows == 1:
                axes = [axes] if cols == 1 else axes
            else:
                axes = axes.flatten()
            
            fig.suptitle('OR-Tools Optimization Overview - All Department-Semester Combinations', 
                        fontsize=16, fontweight='bold')
            
            for idx, ((dept, semester), result) in enumerate(successful_results):
                if idx >= len(axes):
                    break
                
                ax = axes[idx]
                groups = result['groups']
                
                # Create mini heatmap data
                course_group_matrix = {}
                all_courses = set()
                group_names = []
                
                for group_idx, group in enumerate(groups):
                    if not group:
                        continue
                    
                    group_name = f"G{group_idx + 1}"
                    group_names.append(group_name)
                    
                    for instance in group:
                        course_code = instance['course_code']
                        all_courses.add(course_code)
                        
                        if course_code not in course_group_matrix:
                            course_group_matrix[course_code] = {}
                        course_group_matrix[course_code][group_name] = \
                            course_group_matrix[course_code].get(group_name, 0) + 1
                
                if all_courses and group_names:
                    courses_list = sorted(list(all_courses))
                    matrix_data = []
                    
                    for course in courses_list:
                        row = []
                        for group_name in group_names:
                            count = course_group_matrix.get(course, {}).get(group_name, 0)
                            row.append(count)
                        matrix_data.append(row)
                    
                    matrix_array = np.array(matrix_data)
                    
                    sns.heatmap(matrix_array,
                              xticklabels=group_names,
                              yticklabels=courses_list,
                              annot=True,
                              fmt='d',
                              cmap='viridis',
                              ax=ax,
                              cbar=False)
                    
                    ax.set_title(f'{dept} - S{semester}', fontweight='bold')
                    ax.set_xlabel('Groups')
                    ax.set_ylabel('Courses')
                else:
                    ax.text(0.5, 0.5, 'No Data', ha='center', va='center', transform=ax.transAxes)
                    ax.set_title(f'{dept} - S{semester} (No Data)')
            
            # Hide unused subplots
            for idx in range(n_results, len(axes)):
                axes[idx].set_visible(False)
            
            plt.tight_layout()
            
            overview_filepath = os.path.join(self.viz_dir, 'overview_all_departments.png')
            plt.savefig(overview_filepath, dpi=300, bbox_inches='tight')
            plt.close()
            
            self.logger.info(f"Overview heatmap saved: overview_all_departments.png")
            
        except Exception as e:
            self.logger.error(f"Error creating overview heatmap: {e}")
    
    def generate_summary_report(self):
        """Generate a comprehensive summary report."""
        try:
            report_path = os.path.join(self.output_dir, 'biotechnology_optimization_report.txt')
            
            with open(report_path, 'w', encoding='utf-8') as f:
                f.write("BIOTECHNOLOGY COURSE GROUP OPTIMIZATION REPORT\n")
                f.write("="*60 + "\n")
                f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Method: OR-Tools CP-SAT Optimization\n")
                f.write(f"Data Source: {self.csv_file_path}\n\n")
                
                # Overall statistics
                total_combinations = len(self.results)
                successful = sum(1 for r in self.results.values() if r.get('success', False))
                
                f.write(f"OVERALL RESULTS:\n")
                f.write(f"- Total Department-Semester Combinations: {total_combinations}\n")
                f.write(f"- Successful Optimizations: {successful}\n")
                f.write(f"- Failed Optimizations: {total_combinations - successful}\n")
                f.write(f"- Success Rate: {successful/total_combinations*100:.1f}%\n\n")
                
                # Detailed results
                f.write(f"DETAILED RESULTS:\n")
                for (dept, semester), result in sorted(self.results.items()):
                    f.write(f"\n{dept} - Semester {semester}:\n")
                    if result.get('success', False):
                        groups = result['groups']
                        total_instances = sum(len(group) for group in groups)
                        total_courses = len(set(inst['course_code'] for group in groups for inst in group))
                        
                        f.write(f"  ✅ Status: SUCCESS\n")
                        f.write(f"  📊 Objective Value: {result['objective_value']}\n")
                        f.write(f"  👥 Groups: {len(groups)}\n")
                        f.write(f"  📝 Instances: {total_instances}\n")
                        f.write(f"  📚 Courses: {total_courses}\n")
                    else:
                        f.write(f"  ❌ Status: FAILED\n")
                
                # OR-Tools advantages
                f.write(f"\nOR-TOOLS ADVANTAGES:\n")
                f.write(f"+ Optimal Solutions: Mathematical optimization guarantees best result\n")
                f.write(f"+ Constraint Satisfaction: All constraints mathematically enforced\n")
                f.write(f"+ Student Choice: Maximizes course availability across groups\n")
                f.write(f"+ Scalability: Handles complex problems efficiently\n")
                f.write(f"+ Reproducibility: Consistent results for same input\n")
            
            self.logger.info(f"Summary report saved: biotechnology_optimization_report.txt")
            
        except Exception as e:
            self.logger.error(f"Error generating summary report: {e}")


def main():
    """Main function to run the Biotechnology data test."""
    print("🧬 Biotechnology Course Group Optimization Test")
    print("="*60)
    
    try:
        # Create tester
        tester = BiotechnologyDataTester()
        
        # Load data
        tester.load_data()
        
        # Run optimizations
        if tester.run_all_optimizations():
            # Generate visualizations
            tester.generate_heatmaps()
            
            # Generate report
            tester.generate_summary_report()
            
            print("\nTest completed successfully!")
            print(f"Results saved in: {tester.output_dir}")
            print(f"Visualizations in: {tester.viz_dir}")
            return 0
        else:
            print("\nAll optimizations failed!")
            return 1
            
    except Exception as e:
        print(f"\nTest failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main()) 