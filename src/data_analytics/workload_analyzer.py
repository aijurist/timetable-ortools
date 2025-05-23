import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from collections import defaultdict
import os

class WorkloadAnalyzer:
    def __init__(self, course_file):
        """Initialize the workload analyzer with course data."""
        self.courses_df = pd.read_csv(course_file)
        self.process_teacher_workloads()
    
    def process_teacher_workloads(self):
        """Process teacher workloads based on course assignments."""
        self.teacher_workloads = defaultdict(lambda: {
            'total_hours': 0,
            'theory_hours': 0,
            'lab_hours': 0,
            'courses': [],
            'teacher_info': {}
        })
        
        # Process each course assignment
        for _, row in self.courses_df.iterrows():
            teacher_id = row['teacher_id']
            
            # Store teacher info
            if not self.teacher_workloads[teacher_id]['teacher_info']:
                self.teacher_workloads[teacher_id]['teacher_info'] = {
                    'name': f"{row['first_name']} {row['last_name']}".strip(),
                    'staff_code': row['staff_code']
                }
            
            # Calculate hours for this course
            lecture_hours = int(row['lecture_hours'])
            tutorial_hours = int(row['tutorial_hours'])
            practical_hours = int(row['practical_hours'])
            student_count = int(row['student_count'])
            
            # Theory hours calculation (50 min slots)
            theory_hours = lecture_hours + tutorial_hours
            
            # Lab hours calculation (100 min slots)
            # Lab slots are 2x theory slots, and large classes need batching
            lab_slots_needed = (practical_hours + 1) // 2  # Ceiling division
            if student_count > 35:
                num_batches = (student_count + 34) // 35
                lab_slots_needed *= num_batches
            
            lab_hours = lab_slots_needed * 2  # Each lab slot is 2 hours
            
            # Update teacher workload
            self.teacher_workloads[teacher_id]['theory_hours'] += theory_hours
            self.teacher_workloads[teacher_id]['lab_hours'] += lab_hours
            self.teacher_workloads[teacher_id]['total_hours'] += theory_hours + lab_hours
            
            # Store course info
            self.teacher_workloads[teacher_id]['courses'].append({
                'course_code': row['course_code'],
                'course_name': row['course_name'],
                'student_count': student_count,
                'theory_hours': theory_hours,
                'lab_hours': lab_hours,
                'instance_id': row['id']
            })
    
    def analyze_workload_distribution(self):
        """Analyze workload distribution issues."""
        print("=" * 80)
        print("WORKLOAD DISTRIBUTION ANALYSIS")
        print("=" * 80)
        
        total_teachers = len(self.teacher_workloads)
        overloaded_teachers = []
        underloaded_teachers = []
        balanced_teachers = []
        
        print(f"\nTotal Teachers: {total_teachers}")
        print(f"Weekly Hour Limit: 21 hours per teacher")
        print("\nTeacher Workload Breakdown:")
        print("-" * 100)
        print(f"{'Teacher':<25} {'Staff Code':<12} {'Theory':<8} {'Lab':<8} {'Total':<8} {'Status':<15}")
        print("-" * 100)
        
        for teacher_id, workload in self.teacher_workloads.items():
            name = workload['teacher_info']['name']
            staff_code = workload['teacher_info']['staff_code']
            theory_hours = workload['theory_hours']
            lab_hours = workload['lab_hours']
            total_hours = workload['total_hours']
            
            if total_hours > 21:
                status = f"OVERLOADED (+{total_hours-21})"
                overloaded_teachers.append((teacher_id, workload))
            elif total_hours < 15:
                status = f"UNDERLOADED (-{21-total_hours})"
                underloaded_teachers.append((teacher_id, workload))
            else:
                status = "BALANCED"
                balanced_teachers.append((teacher_id, workload))
            
            print(f"{name[:24]:<25} {staff_code:<12} {theory_hours:<8} {lab_hours:<8} {total_hours:<8} {status:<15}")
        
        print("-" * 100)
        print(f"\nSUMMARY:")
        print(f"• Overloaded Teachers: {len(overloaded_teachers)} ({len(overloaded_teachers)/total_teachers*100:.1f}%)")
        print(f"• Balanced Teachers: {len(balanced_teachers)} ({len(balanced_teachers)/total_teachers*100:.1f}%)")
        print(f"• Underloaded Teachers: {len(underloaded_teachers)} ({len(underloaded_teachers)/total_teachers*100:.1f}%)")
        
        # Detailed analysis of problematic cases
        if overloaded_teachers:
            print(f"\n🚨 OVERLOADED TEACHERS ANALYSIS:")
            print("=" * 60)
            for teacher_id, workload in overloaded_teachers:
                self._analyze_teacher_details(teacher_id, workload)
        
        if underloaded_teachers:
            print(f"\n📊 UNDERLOADED TEACHERS (Potential for more assignments):")
            print("=" * 60)
            for teacher_id, workload in underloaded_teachers[:5]:  # Show top 5
                name = workload['teacher_info']['name']
                available_hours = 21 - workload['total_hours']
                print(f"• {name}: {available_hours} hours available")
        
        return {
            'total_teachers': total_teachers,
            'overloaded': len(overloaded_teachers),
            'balanced': len(balanced_teachers),
            'underloaded': len(underloaded_teachers),
            'overloaded_details': overloaded_teachers
        }
    
    def _analyze_teacher_details(self, teacher_id, workload):
        """Analyze details for a specific teacher."""
        name = workload['teacher_info']['name']
        staff_code = workload['teacher_info']['staff_code']
        total_hours = workload['total_hours']
        excess_hours = total_hours - 21
        
        print(f"\nTeacher: {name} ({staff_code})")
        print(f"Total Hours: {total_hours} (Exceeds limit by {excess_hours} hours)")
        print("Course Breakdown:")
        
        for course in workload['courses']:
            print(f"  • {course['course_code']}: {course['course_name']}")
            print(f"    Students: {course['student_count']}, Theory: {course['theory_hours']}h, Lab: {course['lab_hours']}h")
        
        print(f"Suggestions:")
        print(f"  - Consider redistributing {excess_hours} hours to other teachers")
        print(f"  - Look for assistant teacher opportunities for lab sessions")
        print(f"  - Review if multiple instances of same course can be combined")
    
    def create_visualizations(self, output_dir):
        """Create visualizations for workload analysis."""
        print(f"\n📊 Creating visualizations in {output_dir}...")
        
        # Prepare data for visualization
        teachers_data = []
        for teacher_id, workload in self.teacher_workloads.items():
            teachers_data.append({
                'teacher_name': workload['teacher_info']['name'],
                'staff_code': workload['teacher_info']['staff_code'],
                'theory_hours': workload['theory_hours'],
                'lab_hours': workload['lab_hours'],
                'total_hours': workload['total_hours'],
                'exceeds_limit': workload['total_hours'] > 21
            })
        
        df = pd.DataFrame(teachers_data)
        
        # Set style
        plt.style.use('default')
        sns.set_palette("husl")
        
        # 1. Workload Distribution Histogram
        fig, axes = plt.subplots(2, 2, figsize=(16, 12))
        fig.suptitle('Teacher Workload Analysis', fontsize=16, fontweight='bold')
        
        # Histogram of total hours
        axes[0, 0].hist(df['total_hours'], bins=15, alpha=0.7, color='skyblue', edgecolor='black')
        axes[0, 0].axvline(x=21, color='red', linestyle='--', linewidth=2, label='21-hour limit')
        axes[0, 0].set_xlabel('Total Weekly Hours')
        axes[0, 0].set_ylabel('Number of Teachers')
        axes[0, 0].set_title('Distribution of Total Weekly Hours')
        axes[0, 0].legend()
        axes[0, 0].grid(True, alpha=0.3)
        
        # Theory vs Lab hours scatter plot
        colors = ['red' if x else 'green' for x in df['exceeds_limit']]
        scatter = axes[0, 1].scatter(df['theory_hours'], df['lab_hours'], 
                                   c=colors, alpha=0.7, s=60)
        axes[0, 1].set_xlabel('Theory Hours')
        axes[0, 1].set_ylabel('Lab Hours')
        axes[0, 1].set_title('Theory vs Lab Hours Distribution')
        axes[0, 1].grid(True, alpha=0.3)
        
        # Add legend for scatter plot
        import matplotlib.patches as mpatches
        red_patch = mpatches.Patch(color='red', label='Exceeds 21h limit')
        green_patch = mpatches.Patch(color='green', label='Within 21h limit')
        axes[0, 1].legend(handles=[red_patch, green_patch])
        
        # Workload categories pie chart
        overloaded = sum(1 for x in df['total_hours'] if x > 21)
        balanced = sum(1 for x in df['total_hours'] if 15 <= x <= 21)
        underloaded = sum(1 for x in df['total_hours'] if x < 15)
        
        categories = ['Overloaded (>21h)', 'Balanced (15-21h)', 'Underloaded (<15h)']
        values = [overloaded, balanced, underloaded]
        colors_pie = ['red', 'green', 'orange']
        
        axes[1, 0].pie(values, labels=categories, colors=colors_pie, autopct='%1.1f%%', startangle=90)
        axes[1, 0].set_title('Teacher Workload Categories')
        
        # Top 10 most loaded teachers bar chart
        top_teachers = df.nlargest(10, 'total_hours')
        bars = axes[1, 1].bar(range(len(top_teachers)), top_teachers['total_hours'], 
                             color=['red' if x > 21 else 'orange' for x in top_teachers['total_hours']])
        axes[1, 1].axhline(y=21, color='red', linestyle='--', linewidth=2, label='21-hour limit')
        axes[1, 1].set_xlabel('Teachers (by workload rank)')
        axes[1, 1].set_ylabel('Total Weekly Hours')
        axes[1, 1].set_title('Top 10 Most Loaded Teachers')
        axes[1, 1].set_xticks(range(len(top_teachers)))
        axes[1, 1].set_xticklabels([f"{code}" for code in top_teachers['staff_code']], rotation=45)
        axes[1, 1].legend()
        axes[1, 1].grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.savefig(os.path.join(output_dir, 'workload_analysis.png'), dpi=300, bbox_inches='tight')
        plt.close()
        
        # 2. Detailed teacher workload chart
        fig, ax = plt.subplots(figsize=(16, 10))
        
        # Sort teachers by total hours
        df_sorted = df.sort_values('total_hours', ascending=True)
        
        # Create stacked bar chart
        teachers_range = range(len(df_sorted))
        p1 = ax.bar(teachers_range, df_sorted['theory_hours'], label='Theory Hours', color='lightblue')
        p2 = ax.bar(teachers_range, df_sorted['lab_hours'], bottom=df_sorted['theory_hours'], 
                   label='Lab Hours', color='lightcoral')
        
        # Add 21-hour limit line
        ax.axhline(y=21, color='red', linestyle='--', linewidth=2, label='21-hour limit')
        
        # Customize chart
        ax.set_xlabel('Teachers (sorted by workload)')
        ax.set_ylabel('Weekly Hours')
        ax.set_title('Individual Teacher Workload Breakdown (Theory + Lab Hours)')
        ax.legend()
        ax.grid(True, alpha=0.3)
        
        # Add teacher names on x-axis (every 3rd to avoid overcrowding)
        step = max(1, len(df_sorted) // 20)  # Show max 20 labels
        ax.set_xticks(range(0, len(df_sorted), step))
        ax.set_xticklabels([df_sorted.iloc[i]['staff_code'] for i in range(0, len(df_sorted), step)], 
                          rotation=45, ha='right')
        
        plt.tight_layout()
        plt.savefig(os.path.join(output_dir, 'individual_teacher_workloads.png'), dpi=300, bbox_inches='tight')
        plt.close()
        
        print(f"✅ Visualizations saved:")
        print(f"  • workload_analysis.png - Overview charts")
        print(f"  • individual_teacher_workloads.png - Detailed teacher breakdown")
        
        return True

def main():
    """Main function to run workload analysis."""
    # Get the base directory
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Path to data file
    course_file = os.path.join(base_dir, '../../data/mapped_data/cs_teacher_courses.csv')
    
    if not os.path.exists(course_file):
        print(f"Error: Course file not found at {course_file}")
        return
    
    # Create output directory
    output_dir = os.path.join(base_dir, 'workload_analysis')
    os.makedirs(output_dir, exist_ok=True)
    
    # Create analyzer and run analysis
    analyzer = WorkloadAnalyzer(course_file)
    
    # Analyze workload distribution
    results = analyzer.analyze_workload_distribution()
    
    # Create visualizations
    analyzer.create_visualizations(output_dir)
    
    print(f"\n📁 Analysis complete! Results saved to: {output_dir}")

if __name__ == "__main__":
    main() 