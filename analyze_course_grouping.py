#!/usr/bin/env python3

"""
Course Grouping Analysis Tool
============================

This script analyzes the timetable scheduler's course grouping decisions and explains
why courses were placed in specific blocks, including conflict resolution scenarios.

Features:
- Course-to-block mapping analysis
- Teacher conflict detection and resolution tracking
- Priority course placement verification
- Grouping effectiveness metrics
- Detailed reasoning for each scheduling decision
"""

import pandas as pd
import numpy as np
import os
import logging
from collections import defaultdict, Counter
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime

class CourseGroupingAnalyzer:
    def __init__(self, schedule_file=None, course_file=None):
        """Initialize the analyzer with schedule and course data."""
        self.logger = logging.getLogger(__name__)
        
        # Find latest schedule if not provided
        if schedule_file is None:
            schedule_file = self._find_latest_schedule()
        
        if course_file is None:
            course_file = "data/mapped_data/cs_teacher_courses.csv"
        
        print(f"📊 COURSE GROUPING ANALYSIS TOOL")
        print(f"=" * 80)
        print(f"Schedule file: {schedule_file}")
        print(f"Course file: {course_file}")
        print(f"=" * 80)
        
        # Load data
        self.schedule_df = pd.read_csv(schedule_file)
        self.course_df = pd.read_csv(course_file)
        
        # Initialize analysis data structures
        self.course_block_mapping = {}
        self.teacher_conflicts = {}
        self.priority_courses = {}
        self.grouping_decisions = {}
        
        # Block definitions
        self.theory_blocks = ['a1', 'b1', 'c1', 'd1', 'e1', 'f1', 'g1']
        self.priority_blocks = ['a1', 'b1', 'c1']  # Priority blocks for 4-hour courses
        
        # Expected course-to-block mapping (ideal scenario)
        self.expected_mapping = {
            'priority_courses': self.priority_blocks,  # Courses with L+T=4
            'regular_courses': ['d1', 'e1', 'f1', 'g1']  # Other courses
        }
        
    def _find_latest_schedule(self):
        """Find the latest generated schedule file."""
        output_dir = "output"
        if not os.path.exists(output_dir):
            raise FileNotFoundError("No output directory found!")
        
        # Find theory schedule folders
        theory_folders = [f for f in os.listdir(output_dir) if f.startswith("macroblock_schedule_")]
        if not theory_folders:
            raise FileNotFoundError("No macroblock schedule found!")
            
        latest_folder = max(theory_folders)
        schedule_file = os.path.join(output_dir, latest_folder, "macroblock_schedule.csv")
        
        if not os.path.exists(schedule_file):
            raise FileNotFoundError(f"Schedule file not found: {schedule_file}")
            
        return schedule_file
    
    def analyze_complete_grouping(self):
        """Perform complete course grouping analysis."""
        print(f"\n🔍 STARTING COMPREHENSIVE COURSE GROUPING ANALYSIS")
        print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"=" * 80)
        
        # Step 1: Analyze course-to-block mapping
        self._analyze_course_block_mapping()
        
        # Step 2: Detect and analyze teacher conflicts
        self._analyze_teacher_conflicts()
        
        # Step 3: Analyze priority course placement
        self._analyze_priority_course_placement()
        
        # Step 4: Analyze course grouping effectiveness
        self._analyze_grouping_effectiveness()
        
        # Step 5: Explain scheduling decisions
        self._explain_scheduling_decisions()
        
        # Step 6: Generate visualizations
        self._generate_analysis_visualizations()
        
        # Step 7: Generate summary report
        self._generate_summary_report()
        
        print(f"\n✅ ANALYSIS COMPLETE!")
        print(f"=" * 80)
    
    def _analyze_course_block_mapping(self):
        """Analyze how courses are mapped to blocks."""
        print(f"\n📋 STEP 1: COURSE-TO-BLOCK MAPPING ANALYSIS")
        print(f"-" * 60)
        
        # Group schedule by course and block
        course_block_counts = defaultdict(lambda: defaultdict(int))
        course_info = {}
        
        for _, row in self.schedule_df.iterrows():
            if row['slot_type'] in ['Lecture', 'Tutorial']:
                course_code = row['course_code']
                block = row['macroblock']
                course_instance_id = row['course_instance_id']
                
                # Count instances per block
                if block in self.theory_blocks:
                    course_block_counts[course_code][block] += 1
                
                # Store course info
                if course_code not in course_info:
                    course_info[course_code] = {
                        'instances': set(),
                        'teachers': set(),
                        'total_scheduled': 0
                    }
                
                course_info[course_code]['instances'].add(str(course_instance_id))
                course_info[course_code]['teachers'].add(row['teacher_id'])
                course_info[course_code]['total_scheduled'] += 1
        
        self.course_block_mapping = dict(course_block_counts)
        self.course_info = course_info
        
        # Display mapping
        print(f"{'Course Code':<15} {'Instances':<10} {'Teachers':<9} {'Block Distribution':<50} {'Primary Block':<12}")
        print(f"-" * 120)
        
        for course_code, block_counts in sorted(self.course_block_mapping.items()):
            instances = len(self.course_info[course_code]['instances'])
            teachers = len(self.course_info[course_code]['teachers'])
            
            # Find primary block (most assignments)
            primary_block = max(block_counts.items(), key=lambda x: x[1])[0] if block_counts else 'None'
            
            # Create distribution string
            distribution = []
            for block in self.theory_blocks:
                count = block_counts.get(block, 0)
                if count > 0:
                    distribution.append(f"{block}:{count}")
            
            distribution_str = ', '.join(distribution) if distribution else 'None'
            
            print(f"{course_code:<15} {instances:<10} {teachers:<9} {distribution_str:<50} {primary_block:<12}")
        
        print(f"\n📊 MAPPING SUMMARY:")
        total_courses = len(self.course_block_mapping)
        single_block_courses = sum(1 for blocks in self.course_block_mapping.values() if len(blocks) == 1)
        multi_block_courses = total_courses - single_block_courses
        
        print(f"  • Total courses: {total_courses}")
        print(f"  • Single-block courses: {single_block_courses} ({(single_block_courses/total_courses)*100:.1f}%)")
        print(f"  • Multi-block courses: {multi_block_courses} ({(multi_block_courses/total_courses)*100:.1f}%)")
        
        if multi_block_courses > 0:
            print(f"  ⚠️  Multi-block courses indicate teacher conflicts or constraint violations")
    
    def _analyze_teacher_conflicts(self):
        """Analyze teacher conflicts and their resolution."""
        print(f"\n⚠️  STEP 2: TEACHER CONFLICT ANALYSIS")
        print(f"-" * 60)
        
        # Group by teacher and course
        teacher_course_blocks = defaultdict(lambda: defaultdict(set))
        teacher_course_instances = defaultdict(lambda: defaultdict(list))
        
        for _, row in self.schedule_df.iterrows():
            if row['slot_type'] in ['Lecture', 'Tutorial']:
                teacher_id = row['teacher_id']
                course_code = row['course_code']
                block = row['macroblock']
                instance_id = row['course_instance_id']
                
                if block in self.theory_blocks:
                    teacher_course_blocks[teacher_id][course_code].add(block)
                    teacher_course_instances[teacher_id][course_code].append({
                        'instance_id': instance_id,
                        'block': block,
                        'day': row['day'],
                        'slot': row['slot_index'],
                        'teacher_name': f"{row['first_name']} {row['last_name']}".strip()
                    })
        
        # Detect conflicts
        conflict_count = 0
        same_course_conflicts = 0
        different_course_conflicts = 0
        
        print(f"{'Teacher ID':<10} {'Teacher Name':<25} {'Course':<12} {'Conflict Type':<20} {'Resolution':<30}")
        print(f"-" * 110)
        
        for teacher_id, courses in teacher_course_blocks.items():
            teacher_has_conflicts = False
            
            for course_code, blocks in courses.items():
                instances = teacher_course_instances[teacher_id][course_code]
                teacher_name = instances[0]['teacher_name'] if instances else f"Teacher {teacher_id}"
                
                if len(instances) > 1:
                    # Multiple instances of same course
                    if len(blocks) > 1:
                        # Conflict: Multiple instances in different blocks
                        conflict_count += 1
                        same_course_conflicts += 1
                        teacher_has_conflicts = True
                        
                        block_list = ', '.join(sorted(blocks))
                        print(f"{teacher_id:<10} {teacher_name[:24]:<25} {course_code:<12} {'Same Course Multi':<20} {'Split: ' + block_list:<30}")
                        
                        # Store conflict details
                        if teacher_id not in self.teacher_conflicts:
                            self.teacher_conflicts[teacher_id] = []
                        
                        self.teacher_conflicts[teacher_id].append({
                            'type': 'same_course_multiple_blocks',
                            'course': course_code,
                            'instances': len(instances),
                            'blocks': list(blocks),
                            'resolution': f"Split across {len(blocks)} blocks"
                        })
                    
                    elif len(blocks) == 1:
                        # Multiple instances in same block - check if this violates global constraint
                        block = list(blocks)[0]
                        
                        # Check if teacher has other courses in same block
                        other_courses_same_block = []
                        for other_course, other_blocks in courses.items():
                            if other_course != course_code and block in other_blocks:
                                other_courses_same_block.append(other_course)
                        
                        if other_courses_same_block:
                            conflict_count += 1
                            different_course_conflicts += 1
                            teacher_has_conflicts = True
                            
                            print(f"{teacher_id:<10} {teacher_name[:24]:<25} {course_code:<12} {'Block Overlap':<20} {f'With: {other_courses_same_block[0]}':<30}")
            
            # Check for different course conflicts
            all_teacher_blocks = set()
            overlapping_blocks = set()
            
            for course_code, blocks in courses.items():
                for block in blocks:
                    if block in all_teacher_blocks:
                        overlapping_blocks.add(block)
                    all_teacher_blocks.add(block)
            
            if overlapping_blocks and not teacher_has_conflicts:
                # Additional cross-course conflicts
                for block in overlapping_blocks:
                    overlapping_courses = [course for course, blocks in courses.items() if block in blocks]
                    if len(overlapping_courses) > 1:
                        conflict_count += 1
                        different_course_conflicts += 1
                        
                        course_list = ', '.join(overlapping_courses[:2])  # Show first 2
                        teacher_name = teacher_course_instances[teacher_id][overlapping_courses[0]][0]['teacher_name']
                        print(f"{teacher_id:<10} {teacher_name[:24]:<25} {'Multiple':<12} {'Cross-Course':<20} {f'Block {block}: {course_list}':<30}")
        
        print(f"\n📊 CONFLICT SUMMARY:")
        print(f"  • Total conflicts detected: {conflict_count}")
        print(f"  • Same course conflicts: {same_course_conflicts}")
        print(f"  • Different course conflicts: {different_course_conflicts}")
        print(f"  • Teachers with conflicts: {len(self.teacher_conflicts)}")
        
        if conflict_count == 0:
            print(f"  ✅ No conflicts detected - excellent constraint satisfaction!")
        else:
            print(f"  ⚠️  Conflicts present - indicates constraint violations or complex scenarios")
    
    def _analyze_priority_course_placement(self):
        """Analyze priority course placement in preferred blocks."""
        print(f"\n🎯 STEP 3: PRIORITY COURSE PLACEMENT ANALYSIS")
        print(f"-" * 60)
        
        # Get course hour information
        course_hours = {}
        for _, row in self.course_df.iterrows():
            course_code = row['course_code']
            if course_code not in course_hours:
                course_hours[course_code] = {
                    'lecture_hours': row['lecture_hours'],
                    'tutorial_hours': row['tutorial_hours'],
                    'total_lt': row['lecture_hours'] + row['tutorial_hours']
                }
        
        # Classify courses
        priority_courses = {}
        regular_courses = {}
        
        for course_code, hours in course_hours.items():
            if hours['total_lt'] == 4:
                priority_courses[course_code] = hours
            else:
                regular_courses[course_code] = hours
        
        self.priority_courses = priority_courses
        
        print(f"📋 COURSE CLASSIFICATION:")
        print(f"  • Priority courses (L+T=4): {len(priority_courses)}")
        print(f"  • Regular courses (L+T≠4): {len(regular_courses)}")
        
        # Analyze priority course placement
        print(f"\n🎯 PRIORITY COURSE PLACEMENT:")
        print(f"{'Course Code':<12} {'L+T Hours':<10} {'Primary Block':<12} {'Expected':<12} {'Status':<15} {'Reason':<30}")
        print(f"-" * 100)
        
        priority_correctly_placed = 0
        
        for course_code in priority_courses:
            if course_code in self.course_block_mapping:
                blocks = self.course_block_mapping[course_code]
                primary_block = max(blocks.items(), key=lambda x: x[1])[0] if blocks else 'None'
                
                lt_hours = priority_courses[course_code]['total_lt']
                expected = "a1/b1/c1"
                
                if primary_block in self.priority_blocks:
                    status = "✅ Correct"
                    reason = "Placed in priority block"
                    priority_correctly_placed += 1
                else:
                    status = "⚠️ Misplaced"
                    if len(blocks) > 1:
                        reason = "Teacher conflicts forced split"
                    else:
                        reason = "Priority blocks unavailable"
                
                print(f"{course_code:<12} {lt_hours:<10} {primary_block:<12} {expected:<12} {status:<15} {reason:<30}")
            else:
                print(f"{course_code:<12} {priority_courses[course_code]['total_lt']:<10} {'Not Found':<12} {'a1/b1/c1':<12} {'❌ Missing':<15} {'Course not scheduled':<30}")
        
        # Analyze regular course placement
        print(f"\n📚 REGULAR COURSE PLACEMENT:")
        print(f"{'Course Code':<12} {'L+T Hours':<10} {'Primary Block':<12} {'Expected':<12} {'Status':<15} {'Reason':<30}")
        print(f"-" * 100)
        
        regular_correctly_placed = 0
        
        for course_code in regular_courses:
            if course_code in self.course_block_mapping:
                blocks = self.course_block_mapping[course_code]
                primary_block = max(blocks.items(), key=lambda x: x[1])[0] if blocks else 'None'
                
                lt_hours = regular_courses[course_code]['total_lt']
                expected = "d1/e1/f1/g1"
                
                if primary_block in self.expected_mapping['regular_courses']:
                    status = "✅ Correct"
                    reason = "Placed in regular block"
                    regular_correctly_placed += 1
                elif primary_block in self.priority_blocks:
                    status = "⚠️ In Priority"
                    reason = "Placed in priority area"
                else:
                    status = "❓ Other"
                    reason = "Unexpected placement"
                
                print(f"{course_code:<12} {lt_hours:<10} {primary_block:<12} {expected:<12} {status:<15} {reason:<30}")
        
        print(f"\n📊 PLACEMENT SUMMARY:")
        total_priority = len(priority_courses)
        total_regular = len(regular_courses)
        
        if total_priority > 0:
            priority_success_rate = (priority_correctly_placed / total_priority) * 100
            print(f"  • Priority course success rate: {priority_correctly_placed}/{total_priority} ({priority_success_rate:.1f}%)")
        
        if total_regular > 0:
            regular_success_rate = (regular_correctly_placed / total_regular) * 100
            print(f"  • Regular course success rate: {regular_correctly_placed}/{total_regular} ({regular_success_rate:.1f}%)")
    
    def _analyze_grouping_effectiveness(self):
        """Analyze overall course grouping effectiveness."""
        print(f"\n📈 STEP 4: GROUPING EFFECTIVENESS ANALYSIS")
        print(f"-" * 60)
        
        # Analyze same-course grouping
        same_course_grouped = 0
        same_course_split = 0
        
        for course_code, blocks in self.course_block_mapping.items():
            if len(self.course_info[course_code]['instances']) > 1:
                if len(blocks) == 1:
                    same_course_grouped += 1
                else:
                    same_course_split += 1
        
        # Analyze different-course separation
        block_course_counts = defaultdict(set)
        for course_code, blocks in self.course_block_mapping.items():
            for block in blocks:
                block_course_counts[block].add(course_code)
        
        single_course_blocks = sum(1 for courses in block_course_counts.values() if len(courses) == 1)
        multi_course_blocks = len(block_course_counts) - single_course_blocks
        
        # Calculate effectiveness metrics
        total_multi_instance_courses = same_course_grouped + same_course_split
        grouping_effectiveness = (same_course_grouped / total_multi_instance_courses * 100) if total_multi_instance_courses > 0 else 0
        
        separation_effectiveness = (single_course_blocks / len(block_course_counts) * 100) if block_course_counts else 0
        
        print(f"🎯 SAME-COURSE GROUPING:")
        print(f"  • Courses with multiple instances: {total_multi_instance_courses}")
        print(f"  • Successfully grouped: {same_course_grouped}")
        print(f"  • Split across blocks: {same_course_split}")
        print(f"  • Grouping effectiveness: {grouping_effectiveness:.1f}%")
        
        print(f"\n🎯 DIFFERENT-COURSE SEPARATION:")
        print(f"  • Total blocks used: {len(block_course_counts)}")
        print(f"  • Single-course blocks: {single_course_blocks}")
        print(f"  • Multi-course blocks: {multi_course_blocks}")
        print(f"  • Separation effectiveness: {separation_effectiveness:.1f}%")
        
        print(f"\n📊 BLOCK UTILIZATION:")
        for block in sorted(block_course_counts.keys()):
            courses = block_course_counts[block]
            course_list = ', '.join(sorted(courses))
            if len(courses) == 1:
                status = "✅ Perfect"
            elif len(courses) <= 2:
                status = "⚠️ Acceptable"
            else:
                status = "❌ Crowded"
            
            print(f"  {block}: {len(courses)} courses ({status}) - {course_list}")
        
        # Store effectiveness metrics
        self.effectiveness_metrics = {
            'same_course_grouping': grouping_effectiveness,
            'different_course_separation': separation_effectiveness,
            'priority_placement': 0,  # Will be calculated in priority analysis
            'overall_effectiveness': (grouping_effectiveness + separation_effectiveness) / 2
        }
    
    def _explain_scheduling_decisions(self):
        """Explain the reasoning behind scheduling decisions."""
        print(f"\n🧠 STEP 5: SCHEDULING DECISION EXPLANATION")
        print(f"-" * 60)
        
        decisions = []
        
        # Explain each course placement
        for course_code, blocks in self.course_block_mapping.items():
            instances = len(self.course_info[course_code]['instances'])
            teachers = len(self.course_info[course_code]['teachers'])
            
            # Determine course type
            if course_code in self.priority_courses:
                course_type = "Priority (L+T=4)"
                expected_blocks = "a1, b1, c1"
            else:
                course_type = "Regular"
                expected_blocks = "d1, e1, f1, g1"
            
            # Analyze placement decision
            primary_block = max(blocks.items(), key=lambda x: x[1])[0] if blocks else 'None'
            
            if len(blocks) == 1:
                # Single block placement
                if course_code in self.priority_courses and primary_block in self.priority_blocks:
                    reason = f"✅ IDEAL: {course_type} course correctly placed in priority block {primary_block}"
                elif course_code not in self.priority_courses and primary_block in self.expected_mapping['regular_courses']:
                    reason = f"✅ IDEAL: {course_type} course correctly placed in regular block {primary_block}"
                elif instances == 1:
                    reason = f"✅ SIMPLE: Single instance course placed in available block {primary_block}"
                elif teachers == 1:
                    reason = f"✅ GROUPED: Multiple instances with same teacher grouped in block {primary_block}"
                else:
                    reason = f"✅ GROUPED: Multiple instances with different teachers grouped in block {primary_block}"
            else:
                # Multi-block placement - conflict resolution
                block_list = ', '.join(sorted(blocks.keys()))
                if teachers > 1:
                    reason = f"⚠️ CONFLICT RESOLUTION: Teacher conflicts forced split across blocks: {block_list}"
                else:
                    reason = f"⚠️ OVERFLOW: Limited capacity forced split across blocks: {block_list}"
            
            decisions.append({
                'course': course_code,
                'type': course_type,
                'instances': instances,
                'teachers': teachers,
                'blocks': list(blocks.keys()),
                'primary_block': primary_block,
                'expected': expected_blocks,
                'reason': reason
            })
        
        # Display decisions
        print(f"{'Course':<12} {'Type':<15} {'Inst':<4} {'Tchr':<4} {'Primary':<8} {'Decision Reasoning':<60}")
        print(f"-" * 115)
        
        for decision in sorted(decisions, key=lambda x: (x['type'], x['course'])):
            print(f"{decision['course']:<12} {decision['type']:<15} {decision['instances']:<4} {decision['teachers']:<4} {decision['primary_block']:<8} {decision['reason']:<60}")
        
        self.grouping_decisions = decisions
        
        # Summary of decision types
        ideal_decisions = sum(1 for d in decisions if d['reason'].startswith('✅ IDEAL'))
        good_decisions = sum(1 for d in decisions if d['reason'].startswith('✅'))
        conflict_decisions = sum(1 for d in decisions if 'CONFLICT' in d['reason'])
        
        print(f"\n📊 DECISION SUMMARY:")
        print(f"  • Ideal placements: {ideal_decisions}")
        print(f"  • Good placements: {good_decisions - ideal_decisions}")
        print(f"  • Conflict resolutions: {conflict_decisions}")
        print(f"  • Overall satisfaction: {(good_decisions/len(decisions)*100):.1f}%")
    
    def _generate_analysis_visualizations(self):
        """Generate visualization charts for the analysis."""
        print(f"\n📊 STEP 6: GENERATING ANALYSIS VISUALIZATIONS")
        print(f"-" * 60)
        
        try:
            # Create heatmap of course-block distribution
            self._create_course_block_heatmap()
            
            # Create teacher conflict visualization
            self._create_teacher_conflict_chart()
            
            # Create effectiveness metrics chart
            self._create_effectiveness_chart()
            
            print(f"✅ Visualizations generated successfully")
            
        except Exception as e:
            print(f"⚠️ Could not generate visualizations: {e}")
    
    def _create_course_block_heatmap(self):
        """Create heatmap showing course distribution across blocks."""
        # Prepare data for heatmap
        courses = sorted(self.course_block_mapping.keys())
        blocks = self.theory_blocks
        
        heatmap_data = []
        for course in courses:
            row = []
            for block in blocks:
                count = self.course_block_mapping[course].get(block, 0)
                row.append(count)
            heatmap_data.append(row)
        
        # Create heatmap
        plt.figure(figsize=(12, 8))
        sns.heatmap(heatmap_data, 
                    xticklabels=blocks, 
                    yticklabels=courses,
                    annot=True, 
                    fmt='d',
                    cmap='YlOrRd',
                    cbar_kws={'label': 'Number of Instances'})
        
        plt.title('Course Distribution Across Macroblocks\n(Higher values indicate grouping in that block)', fontsize=14)
        plt.xlabel('Macroblock', fontsize=12)
        plt.ylabel('Course Code', fontsize=12)
        plt.tight_layout()
        
        # Save the plot
        output_dir = os.path.dirname(self._find_latest_schedule())
        heatmap_path = os.path.join(output_dir, 'course_grouping_heatmap.png')
        plt.savefig(heatmap_path, dpi=300, bbox_inches='tight')
        plt.close()
        
        print(f"  • Course-block heatmap saved to: {heatmap_path}")
    
    def _create_teacher_conflict_chart(self):
        """Create chart showing teacher conflicts and resolutions."""
        if not self.teacher_conflicts:
            print(f"  • No teacher conflicts to visualize")
            return
        
        # Prepare conflict data
        conflict_types = defaultdict(int)
        for teacher_id, conflicts in self.teacher_conflicts.items():
            for conflict in conflicts:
                conflict_types[conflict['type']] += 1
        
        # Create bar chart
        plt.figure(figsize=(10, 6))
        types = list(conflict_types.keys())
        counts = list(conflict_types.values())
        
        bars = plt.bar(types, counts, color=['#ff7f7f', '#7f7fff', '#7fff7f'])
        plt.title('Teacher Conflict Types and Resolutions', fontsize=14)
        plt.xlabel('Conflict Type', fontsize=12)
        plt.ylabel('Number of Conflicts', fontsize=12)
        
        # Add value labels on bars
        for bar in bars:
            height = bar.get_height()
            plt.text(bar.get_x() + bar.get_width()/2., height + 0.1,
                    f'{int(height)}', ha='center', va='bottom')
        
        plt.xticks(rotation=45, ha='right')
        plt.tight_layout()
        
        # Save the plot
        output_dir = os.path.dirname(self._find_latest_schedule())
        conflict_path = os.path.join(output_dir, 'teacher_conflicts_analysis.png')
        plt.savefig(conflict_path, dpi=300, bbox_inches='tight')
        plt.close()
        
        print(f"  • Teacher conflicts chart saved to: {conflict_path}")
    
    def _create_effectiveness_chart(self):
        """Create chart showing grouping effectiveness metrics."""
        if not hasattr(self, 'effectiveness_metrics'):
            return
        
        metrics = self.effectiveness_metrics
        labels = ['Same-Course\nGrouping', 'Different-Course\nSeparation', 'Overall\nEffectiveness']
        values = [metrics['same_course_grouping'], 
                 metrics['different_course_separation'], 
                 metrics['overall_effectiveness']]
        colors = ['#4CAF50', '#2196F3', '#FF9800']
        
        # Create bar chart
        plt.figure(figsize=(10, 6))
        bars = plt.bar(labels, values, color=colors, alpha=0.8)
        
        plt.title('Course Grouping Effectiveness Metrics', fontsize=14)
        plt.ylabel('Effectiveness (%)', fontsize=12)
        plt.ylim(0, 100)
        
        # Add value labels on bars
        for bar, value in zip(bars, values):
            height = bar.get_height()
            plt.text(bar.get_x() + bar.get_width()/2., height + 1,
                    f'{value:.1f}%', ha='center', va='bottom', fontweight='bold')
        
        # Add horizontal reference lines
        plt.axhline(y=80, color='green', linestyle='--', alpha=0.7, label='Excellent (80%+)')
        plt.axhline(y=60, color='orange', linestyle='--', alpha=0.7, label='Good (60%+)')
        plt.axhline(y=40, color='red', linestyle='--', alpha=0.7, label='Poor (40%+)')
        
        plt.legend()
        plt.tight_layout()
        
        # Save the plot
        output_dir = os.path.dirname(self._find_latest_schedule())
        effectiveness_path = os.path.join(output_dir, 'grouping_effectiveness.png')
        plt.savefig(effectiveness_path, dpi=300, bbox_inches='tight')
        plt.close()
        
        print(f"  • Effectiveness metrics chart saved to: {effectiveness_path}")
    
    def _generate_summary_report(self):
        """Generate comprehensive summary report."""
        print(f"\n📄 STEP 7: GENERATING SUMMARY REPORT")
        print(f"-" * 60)
        
        output_dir = os.path.dirname(self._find_latest_schedule())
        report_path = os.path.join(output_dir, 'course_grouping_analysis_report.txt')
        
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write("COURSE GROUPING ANALYSIS REPORT\n")
            f.write("=" * 80 + "\n\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            
            # Executive Summary
            f.write("EXECUTIVE SUMMARY\n")
            f.write("-" * 40 + "\n")
            
            total_courses = len(self.course_block_mapping)
            multi_instance_courses = sum(1 for course_code in self.course_block_mapping 
                                       if len(self.course_info[course_code]['instances']) > 1)
            
            grouped_courses = sum(1 for course_code, blocks in self.course_block_mapping.items() 
                                if len(self.course_info[course_code]['instances']) > 1 and len(blocks) == 1)
            
            f.write(f"Total courses analyzed: {total_courses}\n")
            f.write(f"Courses with multiple instances: {multi_instance_courses}\n")
            f.write(f"Successfully grouped courses: {grouped_courses}\n")
            
            if multi_instance_courses > 0:
                grouping_rate = (grouped_courses / multi_instance_courses) * 100
                f.write(f"Grouping success rate: {grouping_rate:.1f}%\n")
            
            f.write(f"Teacher conflicts detected: {len(self.teacher_conflicts)}\n")
            f.write(f"Priority courses: {len(self.priority_courses)}\n\n")
            
            # Detailed Analysis
            f.write("DETAILED COURSE ANALYSIS\n")
            f.write("-" * 40 + "\n")
            
            for decision in sorted(self.grouping_decisions, key=lambda x: x['course']):
                f.write(f"\nCourse: {decision['course']}\n")
                f.write(f"  Type: {decision['type']}\n")
                f.write(f"  Instances: {decision['instances']}, Teachers: {decision['teachers']}\n")
                f.write(f"  Blocks used: {', '.join(decision['blocks'])}\n")
                f.write(f"  Decision: {decision['reason']}\n")
            
            # Recommendations
            f.write("\n\nRECOMMENDATIONS FOR IMPROVEMENT\n")
            f.write("-" * 40 + "\n")
            
            if len(self.teacher_conflicts) > 0:
                f.write("1. TEACHER CONFLICT RESOLUTION:\n")
                f.write("   - Consider adjusting teacher assignments to reduce conflicts\n")
                f.write("   - Implement teacher preference constraints\n")
                f.write("   - Allow more flexible block assignments for conflicting teachers\n\n")
            
            # Check if priority courses are misplaced
            misplaced_priority = sum(1 for course_code in self.priority_courses 
                                   if course_code in self.course_block_mapping and
                                   max(self.course_block_mapping[course_code].items(), key=lambda x: x[1])[0] not in self.priority_blocks)
            
            if misplaced_priority > 0:
                f.write("2. PRIORITY COURSE PLACEMENT:\n")
                f.write(f"   - {misplaced_priority} priority courses not in preferred blocks\n")
                f.write("   - Consider increasing priority block capacity\n")
                f.write("   - Implement stronger priority constraints\n\n")
            
            # Block utilization recommendations
            block_usage = defaultdict(int)
            for blocks in self.course_block_mapping.values():
                for block in blocks:
                    block_usage[block] += 1
            
            underused_blocks = [block for block in self.theory_blocks if block_usage[block] < 2]
            overused_blocks = [block for block in self.theory_blocks if block_usage[block] > 3]
            
            if underused_blocks or overused_blocks:
                f.write("3. BLOCK UTILIZATION OPTIMIZATION:\n")
                if underused_blocks:
                    f.write(f"   - Underused blocks: {', '.join(underused_blocks)}\n")
                if overused_blocks:
                    f.write(f"   - Overused blocks: {', '.join(overused_blocks)}\n")
                f.write("   - Consider rebalancing course assignments\n\n")
            
            f.write("4. GENERAL RECOMMENDATIONS:\n")
            f.write("   - Monitor teacher satisfaction with current assignments\n")
            f.write("   - Consider student preferences for teacher selection\n")
            f.write("   - Implement feedback mechanisms for continuous improvement\n")
            f.write("   - Regular analysis of grouping effectiveness\n")
        
        print(f"✅ Comprehensive report saved to: {report_path}")
        
        # Print key insights
        print(f"\n🔍 KEY INSIGHTS:")
        if hasattr(self, 'effectiveness_metrics'):
            print(f"  • Overall grouping effectiveness: {self.effectiveness_metrics['overall_effectiveness']:.1f}%")
        
        if len(self.teacher_conflicts) == 0:
            print(f"  • ✅ No teacher conflicts - excellent constraint satisfaction")
        else:
            print(f"  • ⚠️ {len(self.teacher_conflicts)} teachers have conflicts requiring resolution")
        
        # Check for any completely random-looking assignments
        random_assignments = []
        for course_code, blocks in self.course_block_mapping.items():
            if len(blocks) > 2:  # More than 2 blocks indicates complex conflicts
                random_assignments.append(course_code)
        
        if random_assignments:
            print(f"  • ⚠️ Courses with complex assignments: {', '.join(random_assignments)}")
            print(f"    These may appear random but are due to teacher conflicts")
        else:
            print(f"  • ✅ No apparently random assignments detected")

def main():
    """Main function to run the course grouping analysis."""
    
    print("🚀 STARTING COURSE GROUPING ANALYSIS")
    print("=" * 80)
    
    try:
        # Create analyzer
        analyzer = CourseGroupingAnalyzer()
        
        # Run complete analysis
        analyzer.analyze_complete_grouping()
        
        print(f"\n🎉 ANALYSIS COMPLETED SUCCESSFULLY!")
        print(f"Check the output directory for detailed reports and visualizations.")
        
    except Exception as e:
        print(f"❌ Error during analysis: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main() 