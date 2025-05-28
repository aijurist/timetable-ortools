
import pandas as pd
import os
import sys
from collections import defaultdict, Counter
from datetime import datetime

# Optional imports for visualization
try:
    import matplotlib.pyplot as plt
    import seaborn as sns
    import numpy as np
    VISUALIZATION_AVAILABLE = True
    plt.style.use('default')
    sns.set_palette("husl")
except ImportError:
    VISUALIZATION_AVAILABLE = False
    print("📊 Visualization libraries not available - will generate text-only analysis")
    print("   Install matplotlib and seaborn for visual charts: pip install matplotlib seaborn")

class LabDistributionAnalyzer:
    def __init__(self, data_file_path):
        """Initialize the lab distribution analyzer."""
        self.data_file_path = data_file_path
        self.df = None
        self.labs_df = None
        self.output_dir = None
        self.analysis_results = {}
        
        # Load and process data
        self.load_data()
        self.setup_output_directory()
    
    def load_data(self):
        """Load and preprocess the room/lab data."""
        try:
            print(f"📂 Loading lab data from: {self.data_file_path}")
            self.df = pd.read_csv(self.data_file_path)
            
            # Filter for labs only (is_lab = 1)
            self.labs_df = self.df[self.df['is_lab'] == 1].copy()
            
            print(f"✅ Data loaded successfully:")
            print(f"   Total rooms: {len(self.df)}")
            print(f"   Total labs: {len(self.labs_df)}")
            print(f"   Classrooms: {len(self.df[self.df['is_lab'] == 0])}")
            
            if len(self.labs_df) == 0:
                print("❌ No labs found in the data!")
                sys.exit(1)
                
        except FileNotFoundError:
            print(f"❌ Error: Data file not found at {self.data_file_path}")
            sys.exit(1)
        except Exception as e:
            print(f"❌ Error loading data: {str(e)}")
            sys.exit(1)
    
    def setup_output_directory(self):
        """Setup output directory for analysis results."""
        base_dir = os.path.dirname(os.path.abspath(__file__))
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_dir = os.path.join(base_dir, 'output', f'lab_analysis_{timestamp}')
        os.makedirs(self.output_dir, exist_ok=True)
        print(f"📁 Output directory: {self.output_dir}")
    
    def categorize_labs_by_capacity(self):
        """Categorize labs by their maximum capacity."""
        print("\n🔍 ANALYZING LAB CAPACITY DISTRIBUTION")
        print("=" * 60)
        
        # Define capacity categories
        capacity_categories = {
            'Small (≤35)': lambda x: x <= 35,
            'Medium (36-70)': lambda x: 36 <= x <= 70,
            'Large (71-140)': lambda x: 71 <= x <= 140,
            'Extra Large (>140)': lambda x: x > 140
        }
        
        # Standard categories used in scheduling
        standard_categories = {
            '35-capacity': lambda x: x <= 35,
            '70-capacity': lambda x: 36 <= x <= 70,
            '140-capacity': lambda x: x > 70
        }
        
        capacity_analysis = {}
        
        # Analyze by general categories
        for category, condition in capacity_categories.items():
            matching_labs = self.labs_df[self.labs_df['room_max_cap'].apply(condition)]
            capacity_analysis[category] = {
                'count': len(matching_labs),
                'labs': matching_labs,
                'total_capacity': matching_labs['room_max_cap'].sum(),
                'avg_capacity': matching_labs['room_max_cap'].mean() if len(matching_labs) > 0 else 0,
                'capacity_range': f"{matching_labs['room_max_cap'].min()}-{matching_labs['room_max_cap'].max()}" if len(matching_labs) > 0 else "N/A"
            }
        
        # Analyze by standard scheduling categories
        standard_analysis = {}
        for category, condition in standard_categories.items():
            matching_labs = self.labs_df[self.labs_df['room_max_cap'].apply(condition)]
            standard_analysis[category] = {
                'count': len(matching_labs),
                'labs': matching_labs,
                'total_capacity': matching_labs['room_max_cap'].sum(),
                'avg_capacity': matching_labs['room_max_cap'].mean() if len(matching_labs) > 0 else 0
            }
        
        self.analysis_results['capacity_categories'] = capacity_analysis
        self.analysis_results['standard_categories'] = standard_analysis
        
        # Print capacity distribution
        print("📊 GENERAL CAPACITY DISTRIBUTION:")
        print("-" * 50)
        total_labs = len(self.labs_df)
        total_capacity = self.labs_df['room_max_cap'].sum()
        
        for category, data in capacity_analysis.items():
            percentage = (data['count'] / total_labs) * 100 if total_labs > 0 else 0
            capacity_percentage = (data['total_capacity'] / total_capacity) * 100 if total_capacity > 0 else 0
            print(f"{category:20} | {data['count']:3d} labs ({percentage:5.1f}%) | "
                  f"Cap: {data['total_capacity']:4d} ({capacity_percentage:5.1f}%) | "
                  f"Avg: {data['avg_capacity']:5.1f} | Range: {data['capacity_range']}")
        
        print(f"\n📊 SCHEDULING STANDARD CATEGORIES:")
        print("-" * 50)
        for category, data in standard_analysis.items():
            percentage = (data['count'] / total_labs) * 100 if total_labs > 0 else 0
            capacity_percentage = (data['total_capacity'] / total_capacity) * 100 if total_capacity > 0 else 0
            print(f"{category:15} | {data['count']:3d} labs ({percentage:5.1f}%) | "
                  f"Total capacity: {data['total_capacity']:4d} ({capacity_percentage:5.1f}%)")
        
        print(f"\n📈 OVERALL STATISTICS:")
        print(f"Total labs: {total_labs}")
        print(f"Total lab capacity: {total_capacity} students")
        print(f"Average lab capacity: {self.labs_df['room_max_cap'].mean():.1f} students")
        print(f"Median lab capacity: {self.labs_df['room_max_cap'].median():.1f} students")
        print(f"Capacity range: {self.labs_df['room_max_cap'].min()} - {self.labs_df['room_max_cap'].max()} students")
        
        return capacity_analysis, standard_analysis
    
    def analyze_by_block(self):
        """Analyze lab distribution by building block."""
        print("\n🏢 ANALYZING LAB DISTRIBUTION BY BUILDING BLOCK")
        print("=" * 60)
        
        block_analysis = {}
        blocks = self.labs_df['block'].unique()
        
        for block in sorted(blocks):
            if pd.notna(block):
                block_labs = self.labs_df[self.labs_df['block'] == block]
                
                # Capacity distribution within the block
                capacity_dist = {
                    '35-capacity': len(block_labs[block_labs['room_max_cap'] <= 35]),
                    '70-capacity': len(block_labs[(block_labs['room_max_cap'] > 35) & (block_labs['room_max_cap'] <= 70)]),
                    '140-capacity': len(block_labs[block_labs['room_max_cap'] > 70])
                }
                
                block_analysis[block] = {
                    'total_labs': len(block_labs),
                    'labs': block_labs,
                    'total_capacity': block_labs['room_max_cap'].sum(),
                    'avg_capacity': block_labs['room_max_cap'].mean(),
                    'capacity_distribution': capacity_dist,
                    'capacity_range': f"{block_labs['room_max_cap'].min()}-{block_labs['room_max_cap'].max()}"
                }
        
        self.analysis_results['block_analysis'] = block_analysis
        
        # Print block analysis
        print("📍 BLOCK-WISE LAB DISTRIBUTION:")
        print("-" * 80)
        print(f"{'Block':12} | {'Labs':4} | {'Total Cap':9} | {'Avg Cap':7} | {'35-cap':6} | {'70-cap':6} | {'140-cap':7} | {'Range':10}")
        print("-" * 80)
        
        for block, data in sorted(block_analysis.items()):
            cap_dist = data['capacity_distribution']
            print(f"{block:12} | {data['total_labs']:4d} | {data['total_capacity']:9d} | "
                  f"{data['avg_capacity']:7.1f} | {cap_dist['35-capacity']:6d} | "
                  f"{cap_dist['70-capacity']:6d} | {cap_dist['140-capacity']:7d} | {data['capacity_range']:10}")
        
        return block_analysis
    
    def analyze_technology_levels(self):
        """Analyze labs by technology level."""
        print("\n💻 ANALYZING LAB TECHNOLOGY LEVELS")
        print("=" * 60)
        
        # Clean and categorize technology levels
        self.labs_df['tech_level_clean'] = self.labs_df['tech_level'].fillna('Not Specified')
        tech_analysis = {}
        
        tech_levels = self.labs_df['tech_level_clean'].unique()
        
        for tech_level in sorted(tech_levels):
            tech_labs = self.labs_df[self.labs_df['tech_level_clean'] == tech_level]
            
            # Capacity distribution for this tech level
            capacity_dist = {
                '35-capacity': len(tech_labs[tech_labs['room_max_cap'] <= 35]),
                '70-capacity': len(tech_labs[(tech_labs['room_max_cap'] > 35) & (tech_labs['room_max_cap'] <= 70)]),
                '140-capacity': len(tech_labs[tech_labs['room_max_cap'] > 70])
            }
            
            tech_analysis[tech_level] = {
                'count': len(tech_labs),
                'labs': tech_labs,
                'total_capacity': tech_labs['room_max_cap'].sum(),
                'avg_capacity': tech_labs['room_max_cap'].mean(),
                'capacity_distribution': capacity_dist,
                'blocks': list(tech_labs['block'].unique())
            }
        
        self.analysis_results['tech_analysis'] = tech_analysis
        
        # Print technology analysis
        print("🔧 TECHNOLOGY LEVEL DISTRIBUTION:")
        print("-" * 75)
        print(f"{'Tech Level':15} | {'Labs':4} | {'Total Cap':9} | {'Avg Cap':7} | {'35-cap':6} | {'70-cap':6} | {'140-cap':7}")
        print("-" * 75)
        
        for tech_level, data in sorted(tech_analysis.items()):
            cap_dist = data['capacity_distribution']
            print(f"{tech_level:15} | {data['count']:4d} | {data['total_capacity']:9d} | "
                  f"{data['avg_capacity']:7.1f} | {cap_dist['35-capacity']:6d} | "
                  f"{cap_dist['70-capacity']:6d} | {cap_dist['140-capacity']:7d}")
        
        return tech_analysis
    
    def analyze_detailed_capacity_distribution(self):
        """Analyze detailed capacity distribution showing exact capacity values."""
        print("\n📊 DETAILED CAPACITY DISTRIBUTION")
        print("=" * 60)
        
        # Count labs by exact capacity
        capacity_counts = self.labs_df['room_max_cap'].value_counts().sort_index()
        
        detailed_analysis = {}
        for capacity, count in capacity_counts.items():
            capacity_labs = self.labs_df[self.labs_df['room_max_cap'] == capacity]
            detailed_analysis[capacity] = {
                'count': count,
                'labs': capacity_labs,
                'blocks': list(capacity_labs['block'].unique()),
                'room_numbers': list(capacity_labs['room_number'].values)
            }
        
        self.analysis_results['detailed_capacity'] = detailed_analysis
        
        print("🎯 EXACT CAPACITY BREAKDOWN:")
        print("-" * 50)
        print(f"{'Capacity':8} | {'Count':5} | {'Blocks':30} | {'Rooms':20}")
        print("-" * 80)
        
        for capacity in sorted(capacity_counts.index):
            data = detailed_analysis[capacity]
            blocks_str = ', '.join(data['blocks'][:3])  # Show first 3 blocks
            if len(data['blocks']) > 3:
                blocks_str += f" (+ {len(data['blocks']) - 3} more)"
            
            rooms_str = ', '.join(data['room_numbers'][:3])  # Show first 3 rooms
            if len(data['room_numbers']) > 3:
                rooms_str += f" (+ {len(data['room_numbers']) - 3} more)"
            
            print(f"{capacity:8d} | {data['count']:5d} | {blocks_str:30} | {rooms_str:20}")
        
        return detailed_analysis
    
    def calculate_utilization_potential(self):
        """Calculate potential lab utilization scenarios."""
        print("\n⚡ CALCULATING LAB UTILIZATION POTENTIAL")
        print("=" * 60)
        
        # Assume 6 lab sessions per day × 5 days = 30 lab sessions per week per lab
        sessions_per_lab_per_week = 30
        
        utilization_analysis = {}
        
        # Calculate by capacity categories
        for category, data in self.analysis_results['standard_categories'].items():
            lab_count = data['count']
            total_capacity = data['total_capacity']
            
            # Weekly capacity potential
            weekly_lab_sessions = lab_count * sessions_per_lab_per_week
            weekly_student_capacity = weekly_lab_sessions * data['avg_capacity']
            
            utilization_analysis[category] = {
                'lab_count': lab_count,
                'weekly_sessions': weekly_lab_sessions,
                'total_capacity': total_capacity,
                'avg_capacity': data['avg_capacity'],
                'weekly_student_capacity': weekly_student_capacity
            }
        
        # Calculate by blocks
        block_utilization = {}
        for block, data in self.analysis_results['block_analysis'].items():
            lab_count = data['total_labs']
            total_capacity = data['total_capacity']
            avg_capacity = data['avg_capacity']
            
            weekly_lab_sessions = lab_count * sessions_per_lab_per_week
            weekly_student_capacity = weekly_lab_sessions * avg_capacity
            
            block_utilization[block] = {
                'lab_count': lab_count,
                'weekly_sessions': weekly_lab_sessions,
                'total_capacity': total_capacity,
                'avg_capacity': avg_capacity,
                'weekly_student_capacity': weekly_student_capacity
            }
        
        self.analysis_results['utilization_potential'] = utilization_analysis
        self.analysis_results['block_utilization'] = block_utilization
        
        # Print utilization potential
        print("🎯 WEEKLY UTILIZATION POTENTIAL BY CAPACITY:")
        print("-" * 70)
        print(f"{'Category':15} | {'Labs':4} | {'Sessions/Week':12} | {'Student Capacity/Week':18}")
        print("-" * 70)
        
        total_weekly_sessions = 0
        total_weekly_capacity = 0
        
        for category, data in utilization_analysis.items():
            print(f"{category:15} | {data['lab_count']:4d} | {data['weekly_sessions']:12d} | {data['weekly_student_capacity']:18.0f}")
            total_weekly_sessions += data['weekly_sessions']
            total_weekly_capacity += data['weekly_student_capacity']
        
        print("-" * 70)
        print(f"{'TOTAL':15} | {sum(d['lab_count'] for d in utilization_analysis.values()):4d} | "
              f"{total_weekly_sessions:12d} | {total_weekly_capacity:18.0f}")
        
        print(f"\n🎯 WEEKLY UTILIZATION POTENTIAL BY BLOCK:")
        print("-" * 70)
        print(f"{'Block':12} | {'Labs':4} | {'Sessions/Week':12} | {'Student Capacity/Week':18}")
        print("-" * 70)
        
        for block in sorted(block_utilization.keys()):
            data = block_utilization[block]
            print(f"{block:12} | {data['lab_count']:4d} | {data['weekly_sessions']:12d} | {data['weekly_student_capacity']:18.0f}")
        
        return utilization_analysis, block_utilization
    
    def analyze_hard_constraints_impact(self):
        """Analyze the impact of hard constraints on lab allocation."""
        print("\n🚨 ANALYZING HARD CONSTRAINT IMPACT FOR SCHEDULING")
        print("=" * 60)
        print("Hard Constraint: Courses with practical_hours < 3 MUST use 35-capacity labs only")
        print("Courses with practical_hours >= 3 CAN use 70-capacity labs")
        print("-" * 60)
        
        # Get lab counts by capacity
        labs_35 = self.analysis_results['standard_categories']['35-capacity']['count']
        labs_70 = self.analysis_results['standard_categories']['70-capacity']['count']
        labs_140 = self.analysis_results['standard_categories']['140-capacity']['count']
        
        # Calculate constraint impact
        constraint_analysis = {
            '35_capacity_labs': {
                'count': labs_35,
                'weekly_sessions': labs_35 * 30,  # 30 sessions per week per lab
                'suitable_for': 'All courses (forced for <3 practical hours)',
                'constraint_type': 'Required for courses with <3 practical hours'
            },
            '70_capacity_labs': {
                'count': labs_70 + labs_140,  # Treat 140 as 70 for scheduling
                'weekly_sessions': (labs_70 + labs_140) * 30,
                'suitable_for': 'Only courses with >=3 practical hours',
                'constraint_type': 'Available only for courses with >=3 practical hours'
            }
        }
        
        self.analysis_results['constraint_analysis'] = constraint_analysis
        
        print("📊 CONSTRAINT-BASED LAB AVAILABILITY:")
        print("-" * 60)
        print(f"35-capacity labs (unrestricted): {labs_35} labs = {labs_35 * 30} weekly sessions")
        print(f"70+ capacity labs (restricted):  {labs_70 + labs_140} labs = {(labs_70 + labs_140) * 30} weekly sessions")
        print(f"")
        print(f"Total weekly lab capacity:")
        print(f"  - For courses with <3 practical hours: {labs_35 * 30} sessions (35-cap only)")
        print(f"  - For courses with >=3 practical hours: {(labs_35 + labs_70 + labs_140) * 30} sessions (all labs)")
        print(f"")
        print(f"Constraint impact:")
        print(f"  - {((labs_70 + labs_140) / (labs_35 + labs_70 + labs_140) * 100):.1f}% of labs restricted by practical hours constraint")
        print(f"  - {(labs_35 / (labs_35 + labs_70 + labs_140) * 100):.1f}% of labs available to all courses")
        
        return constraint_analysis
    
    def generate_visualizations(self):
        """Generate visualization charts if matplotlib is available."""
        if not VISUALIZATION_AVAILABLE:
            print("\n📊 Skipping visualizations (matplotlib not available)")
            return
        
        print("\n📊 GENERATING VISUALIZATION CHARTS")
        print("=" * 60)
        
        # Create visualization directory
        viz_dir = os.path.join(self.output_dir, 'visualizations')
        os.makedirs(viz_dir, exist_ok=True)
        
        # 1. Capacity distribution pie chart
        plt.figure(figsize=(12, 8))
        
        # Subplot 1: Capacity Categories
        plt.subplot(2, 2, 1)
        categories = list(self.analysis_results['capacity_categories'].keys())
        counts = [self.analysis_results['capacity_categories'][cat]['count'] for cat in categories]
        colors = ['#FF9999', '#66B2FF', '#99FF99', '#FFD700']
        
        plt.pie(counts, labels=categories, autopct='%1.1f%%', colors=colors, startangle=90)
        plt.title('Lab Distribution by Capacity Categories')
        
        # Subplot 2: Standard Categories  
        plt.subplot(2, 2, 2)
        std_categories = list(self.analysis_results['standard_categories'].keys())
        std_counts = [self.analysis_results['standard_categories'][cat]['count'] for cat in std_categories]
        colors_std = ['#FF6B6B', '#4ECDC4', '#45B7D1']
        
        plt.pie(std_counts, labels=std_categories, autopct='%1.1f%%', colors=colors_std, startangle=90)
        plt.title('Scheduling Standard Categories')
        
        # Subplot 3: Block distribution
        plt.subplot(2, 2, 3)
        blocks = list(self.analysis_results['block_analysis'].keys())
        block_counts = [self.analysis_results['block_analysis'][block]['total_labs'] for block in blocks]
        
        plt.bar(blocks, block_counts, color=['#FF9999', '#66B2FF', '#99FF99', '#FFD700', '#FF6B6B'][:len(blocks)])
        plt.title('Labs per Building Block')
        plt.xlabel('Building Block')
        plt.ylabel('Number of Labs')
        plt.xticks(rotation=45)
        
        # Subplot 4: Capacity range histogram
        plt.subplot(2, 2, 4)
        capacities = self.labs_df['room_max_cap'].values
        plt.hist(capacities, bins=10, color='skyblue', alpha=0.7, edgecolor='black')
        plt.title('Lab Capacity Distribution')
        plt.xlabel('Capacity (Students)')
        plt.ylabel('Number of Labs')
        
        plt.tight_layout()
        plt.savefig(os.path.join(viz_dir, 'lab_distribution_overview.png'), dpi=300, bbox_inches='tight')
        plt.close()
        
        # 2. Detailed capacity breakdown
        plt.figure(figsize=(14, 8))
        
        detailed_caps = list(self.analysis_results['detailed_capacity'].keys())
        detailed_counts = [self.analysis_results['detailed_capacity'][cap]['count'] for cap in detailed_caps]
        
        plt.bar(detailed_caps, detailed_counts, color='lightcoral', alpha=0.8, edgecolor='black')
        plt.title('Detailed Lab Capacity Breakdown')
        plt.xlabel('Exact Capacity (Students)')
        plt.ylabel('Number of Labs')
        plt.xticks(detailed_caps, rotation=45)
        
        # Add value labels on bars
        for i, v in enumerate(detailed_counts):
            plt.text(detailed_caps[i], v + 0.1, str(v), ha='center', va='bottom', fontweight='bold')
        
        plt.tight_layout()
        plt.savefig(os.path.join(viz_dir, 'detailed_capacity_breakdown.png'), dpi=300, bbox_inches='tight')
        plt.close()
        
        # 3. Block-wise capacity distribution
        plt.figure(figsize=(14, 10))
        
        blocks = list(self.analysis_results['block_analysis'].keys())
        capacities_35 = [self.analysis_results['block_analysis'][block]['capacity_distribution']['35-capacity'] for block in blocks]
        capacities_70 = [self.analysis_results['block_analysis'][block]['capacity_distribution']['70-capacity'] for block in blocks]
        capacities_140 = [self.analysis_results['block_analysis'][block]['capacity_distribution']['140-capacity'] for block in blocks]
        
        x = np.arange(len(blocks))
        width = 0.25
        
        plt.bar(x - width, capacities_35, width, label='35-capacity', color='#FF6B6B', alpha=0.8)
        plt.bar(x, capacities_70, width, label='70-capacity', color='#4ECDC4', alpha=0.8)
        plt.bar(x + width, capacities_140, width, label='140-capacity', color='#45B7D1', alpha=0.8)
        
        plt.title('Lab Capacity Distribution by Building Block')
        plt.xlabel('Building Block')
        plt.ylabel('Number of Labs')
        plt.xticks(x, blocks, rotation=45)
        plt.legend()
        plt.grid(axis='y', alpha=0.3)
        
        plt.tight_layout()
        plt.savefig(os.path.join(viz_dir, 'block_capacity_distribution.png'), dpi=300, bbox_inches='tight')
        plt.close()
        
        print(f"✅ Visualizations saved to: {viz_dir}")
        print("   - lab_distribution_overview.png")
        print("   - detailed_capacity_breakdown.png") 
        print("   - block_capacity_distribution.png")
    
    def export_detailed_analysis(self):
        """Export detailed analysis to CSV files."""
        print(f"\n💾 EXPORTING DETAILED ANALYSIS")
        print("=" * 60)
        
        export_dir = os.path.join(self.output_dir, 'detailed_data')
        os.makedirs(export_dir, exist_ok=True)
        
        # Export all labs with analysis
        labs_analysis = self.labs_df.copy()
        
        # Add capacity category
        def categorize_capacity(capacity):
            if capacity <= 35:
                return '35-capacity'
            elif capacity <= 70:
                return '70-capacity'
            else:
                return '140-capacity'
        
        labs_analysis['capacity_category'] = labs_analysis['room_max_cap'].apply(categorize_capacity)
        labs_analysis['general_category'] = labs_analysis['room_max_cap'].apply(
            lambda x: 'Small (≤35)' if x <= 35 else 
                     'Medium (36-70)' if x <= 70 else
                     'Large (71-140)' if x <= 140 else 
                     'Extra Large (>140)'
        )
        
        # Export main analysis
        labs_analysis.to_csv(os.path.join(export_dir, 'all_labs_analysis.csv'), index=False)
        
        # Export capacity summary
        capacity_summary = []
        for category, data in self.analysis_results['capacity_categories'].items():
            capacity_summary.append({
                'Category': category,
                'Lab_Count': data['count'],
                'Total_Capacity': data['total_capacity'],
                'Average_Capacity': data['avg_capacity'],
                'Capacity_Range': data['capacity_range']
            })
        
        pd.DataFrame(capacity_summary).to_csv(os.path.join(export_dir, 'capacity_summary.csv'), index=False)
        
        # Export block analysis
        block_summary = []
        for block, data in self.analysis_results['block_analysis'].items():
            block_summary.append({
                'Block': block,
                'Total_Labs': data['total_labs'],
                'Total_Capacity': data['total_capacity'],
                'Average_Capacity': data['avg_capacity'],
                'Labs_35_Capacity': data['capacity_distribution']['35-capacity'],
                'Labs_70_Capacity': data['capacity_distribution']['70-capacity'],
                'Labs_140_Capacity': data['capacity_distribution']['140-capacity'],
                'Capacity_Range': data['capacity_range']
            })
        
        pd.DataFrame(block_summary).to_csv(os.path.join(export_dir, 'block_analysis.csv'), index=False)
        
        # Export utilization potential
        utilization_summary = []
        for category, data in self.analysis_results['utilization_potential'].items():
            utilization_summary.append({
                'Capacity_Category': category,
                'Lab_Count': data['lab_count'],
                'Weekly_Sessions': data['weekly_sessions'],
                'Weekly_Student_Capacity': data['weekly_student_capacity'],
                'Average_Lab_Capacity': data['avg_capacity']
            })
        
        pd.DataFrame(utilization_summary).to_csv(os.path.join(export_dir, 'utilization_potential.csv'), index=False)
        
        print(f"✅ Detailed analysis exported to: {export_dir}")
        print("   - all_labs_analysis.csv: Complete lab data with categorization")
        print("   - capacity_summary.csv: Summary by capacity categories")
        print("   - block_analysis.csv: Block-wise analysis")
        print("   - utilization_potential.csv: Weekly utilization potential")
    
    def generate_summary_report(self):
        """Generate a comprehensive summary report."""
        print(f"\n📋 GENERATING SUMMARY REPORT")
        print("=" * 60)
        
        report_path = os.path.join(self.output_dir, 'lab_distribution_report.txt')
        
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write("LAB DISTRIBUTION ANALYSIS REPORT\n")
            f.write("=" * 50 + "\n")
            f.write(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Data source: {self.data_file_path}\n\n")
            
            # Executive Summary
            f.write("EXECUTIVE SUMMARY\n")
            f.write("-" * 20 + "\n")
            total_labs = len(self.labs_df)
            total_capacity = self.labs_df['room_max_cap'].sum()
            f.write(f"Total laboratory facilities: {total_labs}\n")
            f.write(f"Total student capacity: {total_capacity}\n")
            f.write(f"Average lab capacity: {self.labs_df['room_max_cap'].mean():.1f} students\n")
            f.write(f"Capacity range: {self.labs_df['room_max_cap'].min()} - {self.labs_df['room_max_cap'].max()} students\n\n")
            
            # Capacity Distribution
            f.write("CAPACITY DISTRIBUTION\n")
            f.write("-" * 20 + "\n")
            for category, data in self.analysis_results['standard_categories'].items():
                percentage = (data['count'] / total_labs) * 100
                f.write(f"{category}: {data['count']} labs ({percentage:.1f}%)\n")
            f.write("\n")
            
            # Block Distribution
            f.write("BLOCK DISTRIBUTION\n")
            f.write("-" * 20 + "\n")
            for block, data in sorted(self.analysis_results['block_analysis'].items()):
                f.write(f"{block}: {data['total_labs']} labs (Total capacity: {data['total_capacity']})\n")
            f.write("\n")
            
            # Utilization Potential
            f.write("WEEKLY UTILIZATION POTENTIAL\n")
            f.write("-" * 30 + "\n")
            f.write("Assuming 30 lab sessions per lab per week (6 sessions/day × 5 days):\n")
            total_weekly_sessions = sum(data['weekly_sessions'] for data in self.analysis_results['utilization_potential'].values())
            total_weekly_capacity = sum(data['weekly_student_capacity'] for data in self.analysis_results['utilization_potential'].values())
            f.write(f"Total weekly lab sessions: {total_weekly_sessions}\n")
            f.write(f"Total weekly student capacity: {total_weekly_capacity:.0f}\n\n")
            
            # Hard Constraints Impact
            f.write("SCHEDULING CONSTRAINTS IMPACT\n")
            f.write("-" * 30 + "\n")
            f.write("Hard Constraint: Courses with <3 practical hours must use 35-capacity labs only\n")
            labs_35 = self.analysis_results['standard_categories']['35-capacity']['count']
            labs_70_plus = sum(self.analysis_results['standard_categories'][cat]['count'] 
                              for cat in ['70-capacity', '140-capacity'] if cat in self.analysis_results['standard_categories'])
            
            f.write(f"35-capacity labs (unrestricted): {labs_35} labs\n")
            f.write(f"70+ capacity labs (restricted): {labs_70_plus} labs\n")
            f.write(f"Restriction impact: {(labs_70_plus / total_labs * 100):.1f}% of labs have usage restrictions\n\n")
            
            # Recommendations
            f.write("RECOMMENDATIONS\n")
            f.write("-" * 15 + "\n")
            
            if labs_35 < labs_70_plus:
                f.write("• Consider increasing 35-capacity lab availability for courses with <3 practical hours\n")
            
            if total_weekly_capacity / total_weekly_sessions < 50:
                f.write("• Average lab capacity is relatively low - consider optimizing lab assignments\n")
            
            blocks_with_few_labs = [block for block, data in self.analysis_results['block_analysis'].items() 
                                   if data['total_labs'] < 3]
            if blocks_with_few_labs:
                f.write(f"• Blocks with limited lab facilities: {', '.join(blocks_with_few_labs)}\n")
            
            f.write("• Implement dynamic batching for optimal lab utilization\n")
            f.write("• Consider scheduling preferences based on practical hours requirements\n")
        
        print(f"✅ Summary report saved to: {report_path}")
    
    def run_complete_analysis(self):
        """Run the complete lab distribution analysis."""
        print("🚀 STARTING COMPREHENSIVE LAB DISTRIBUTION ANALYSIS")
        print("=" * 80)
        
        try:
            # Run all analysis components
            self.categorize_labs_by_capacity()
            self.analyze_by_block()
            self.analyze_technology_levels()
            self.analyze_detailed_capacity_distribution()
            self.calculate_utilization_potential()
            self.analyze_hard_constraints_impact()
            
            # Generate outputs
            self.generate_visualizations()
            self.export_detailed_analysis()
            self.generate_summary_report()
            
            print(f"\n🎉 ANALYSIS COMPLETE!")
            print("=" * 80)
            print(f"📁 All results saved to: {self.output_dir}")
            print("📊 Analysis includes:")
            print("   ✅ Capacity distribution analysis")
            print("   ✅ Block-wise lab distribution")
            print("   ✅ Technology level analysis")
            print("   ✅ Detailed capacity breakdown")
            print("   ✅ Utilization potential calculation")
            print("   ✅ Hard constraints impact analysis")
            if VISUALIZATION_AVAILABLE:
                print("   ✅ Visual charts and graphs")
            print("   ✅ Detailed CSV exports")
            print("   ✅ Comprehensive summary report")
            
        except Exception as e:
            print(f"❌ Error during analysis: {str(e)}")
            import traceback
            traceback.print_exc()

def main():
    """Main function to run the lab distribution analysis."""
    print("🧪 LAB DISTRIBUTION ANALYZER")
    print("=" * 50)
    print("This tool analyzes laboratory capacity distribution for optimal timetable scheduling.")
    print()
    
    # Default data file path
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_file = os.path.join(base_dir, 'data', 'block_wise', 'techlongue.csv')
    
    # Check if data file exists
    if not os.path.exists(data_file):
        print(f"❌ Data file not found: {data_file}")
        print("Please ensure the techlongue.csv file exists in the correct location.")
        return
    
    # Create analyzer and run analysis
    analyzer = LabDistributionAnalyzer(data_file)
    analyzer.run_complete_analysis()

if __name__ == "__main__":
    main() 