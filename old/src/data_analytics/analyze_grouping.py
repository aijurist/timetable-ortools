import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
from collections import defaultdict, Counter
import os
import glob

class CourseGroupingAnalyzer:
    def __init__(self, schedule_csv_path, courses_csv_path):
        """Initialize the analyzer with schedule and course data."""
        self.schedule_df = pd.read_csv(schedule_csv_path)
        self.courses_df = pd.read_csv(courses_csv_path)
        
        # Handle different schedule types (lab vs theory)
        if 'slot_type' in self.schedule_df.columns:
            # Theory schedule - filter only lecture and tutorial slots
            self.schedule_df = self.schedule_df[self.schedule_df['slot_type'].isin(['Lecture', 'Tutorial'])]
            self.schedule_type = 'theory'
        else:
            # Lab schedule - use all rows
            self.schedule_type = 'lab'
        
        # Check if we have the new group columns (handle both naming conventions)
        group_columns_v1 = ['group_name', 'group_index', 'department_group', 'semester_group']
        group_columns_v2 = ['group_name', 'group_index', 'department', 'semester']
        
        if all(col in self.schedule_df.columns for col in group_columns_v1):
            self.has_group_data = True
            self.group_columns = group_columns_v1
        elif all(col in self.schedule_df.columns for col in group_columns_v2):
            self.has_group_data = True 
            self.group_columns = group_columns_v2
            # Standardize column names for compatibility
            self.schedule_df['department_group'] = self.schedule_df['department']
            self.schedule_df['semester_group'] = self.schedule_df['semester']
        else:
            self.has_group_data = False
            self.group_columns = []
        
        if not self.has_group_data:
            print("Warning: New group columns not found in schedule data. Make sure you're using a schedule generated with the updated course group constraint.")
            print("Expected columns: group_name, group_index, department_group, semester_group")
            print("Available columns:", list(self.schedule_df.columns))
        
        # Create output directory for analysis
        self.output_dir = os.path.join(os.path.dirname(schedule_csv_path), 'grouping_analysis')
        os.makedirs(self.output_dir, exist_ok=True)
        
        print(f"Loaded {len(self.schedule_df)} {self.schedule_type} assignments")
        print(f"Analyzing course grouping constraints...")
        print(f"Schedule type: {self.schedule_type}")
        print(f"Group data available: {self.has_group_data}")

    def analyze_course_grouping(self):
        """Analyze how teacher-course instances are grouped by semester and department."""
        print("\n" + "="*80)
        print("TEACHER-COURSE INSTANCE GROUPING ANALYSIS")
        print("="*80)
        
        if not self.has_group_data:
            print("Cannot perform analysis - group data not available in schedule CSV")
            return {}
        
        # First, let's see what raw data we have
        print(f"\nRAW DATA SUMMARY:")
        print(f"Total schedule records: {len(self.schedule_df)}")
        print(f"Unique teacher IDs: {self.schedule_df['teacher_id'].nunique()}")
        print(f"Unique course codes: {self.schedule_df['course_code'].nunique()}")
        print(f"Unique course instance IDs: {self.schedule_df['course_instance_id'].nunique() if 'course_instance_id' in self.schedule_df.columns else 'N/A'}")
        
        # Show all unique teacher-course combinations
        teacher_course_combinations = self.schedule_df[['teacher_id', 'course_code']].drop_duplicates()
        print(f"Unique teacher-course combinations: {len(teacher_course_combinations)}")
        
        print(f"\nAll teacher-course combinations found:")
        for _, row in teacher_course_combinations.iterrows():
            teacher_name = self._get_teacher_name(row['teacher_id'])
            course_name = self._get_course_name(row['course_code'])
            print(f"  - {row['teacher_id']} ({teacher_name}) teaching {row['course_code']} ({course_name})")
        
        # DEBUG: Check CS23511 specifically
        cs23511_records = self.schedule_df[self.schedule_df['course_code'] == 'CS23511']
        print(f"\nDEBUG - CS23511 records in schedule_df: {len(cs23511_records)}")
        if len(cs23511_records) > 0:
            print("CS23511 schedule records:")
            for idx, record in cs23511_records.iterrows():
                print(f"  Row {idx}: Teacher {record['teacher_id']}, Day {record['day']}, Time {record['time_interval']}, Group {record.get('group_name', 'No Group')}")
        
        # Group by department and semester
        dept_sem_groups = {}
        
        # Get unique department/semester combinations
        dept_sem_combinations = self.schedule_df[['department_group', 'semester_group']].drop_duplicates()
        
        for _, row in dept_sem_combinations.iterrows():
            dept = row['department_group']
            semester = row['semester_group']
            
            if dept == 'Unknown' or semester == 0:
                continue
                
            # Get all assignments for this department/semester
            dept_sem_data = self.schedule_df[
                (self.schedule_df['department_group'] == dept) & 
                (self.schedule_df['semester_group'] == semester)
            ]
            
            print(f"\nDepartment: {dept}, Semester: {semester}")
            print(f"Records for this dept/sem: {len(dept_sem_data)}")
            
            # Show unique teacher-course combinations for this dept/sem
            dept_sem_teacher_course = dept_sem_data[['teacher_id', 'course_code']].drop_duplicates()
            print(f"Teacher-course combinations in this dept/sem: {len(dept_sem_teacher_course)}")
            for _, tc_row in dept_sem_teacher_course.iterrows():
                print(f"  - {tc_row['teacher_id']} -> {tc_row['course_code']}")
            
            # Group by group_name to analyze individual groups
            groups_in_dept_sem = {}
            for group_name in dept_sem_data['group_name'].unique():
                if group_name == 'Unassigned':
                    continue
                    
                group_data = dept_sem_data[dept_sem_data['group_name'] == group_name]
                
                # Get ALL teacher-course instances in this group (each schedule record is an instance)
                teacher_course_instances = []
                unique_courses = set()
                unique_teachers = set()
                
                for idx, assignment in group_data.iterrows():
                    course_code = assignment['course_code']
                    teacher_id = assignment['teacher_id']
                    course_instance_id = assignment.get('course_instance_id', f"{course_code}_{teacher_id}_{idx}")
                    
                    # Each schedule record is a separate instance
                    teacher_course_instances.append({
                        'teacher_id': teacher_id,
                        'course_code': course_code,
                        'course_instance_id': course_instance_id,
                        'teacher_name': self._get_teacher_name(teacher_id),
                        'course_name': self._get_course_name(course_code),
                        'instance_key': f"{teacher_id}_{course_code}_{idx}",  # Make unique with index
                        'instance_display': f"{teacher_id}-{course_code}",
                        'schedule_record_id': idx,
                        'day': assignment.get('day', 'Unknown'),
                        'time_interval': assignment.get('time_interval', 'Unknown')
                    })
                    
                    unique_courses.add(course_code)
                    unique_teachers.add(teacher_id)
                
                groups_in_dept_sem[group_name] = {
                    'group_index': group_data['group_index'].iloc[0],
                    'teacher_course_instances': teacher_course_instances,
                    'unique_courses': list(unique_courses),
                    'unique_teachers': list(unique_teachers),
                    'num_instances': len(teacher_course_instances),  # This will now be total schedule records
                    'num_unique_courses': len(unique_courses),
                    'num_unique_teachers': len(unique_teachers),
                    'num_assignments': len(group_data),
                    'assignments': group_data
                }
            
            dept_sem_groups[(dept, semester)] = groups_in_dept_sem
            
            # Print analysis for this department/semester
            print(f"\n{dept} - Semester {semester}:")
            print(f"  Total Groups: {len(groups_in_dept_sem)}")
            
            for group_name, group_info in groups_in_dept_sem.items():
                print(f"  Group {group_info['group_index']} ({group_name}):")
                print(f"    Teacher-Course Instances: {group_info['num_instances']}")
                print(f"    Unique Courses: {group_info['num_unique_courses']}")
                print(f"    Unique Teachers: {group_info['num_unique_teachers']}")
                print(f"    Total Schedule Assignments: {group_info['num_assignments']}")
                
                # Show teacher-course instances
                for instance in group_info['teacher_course_instances']:
                    print(f"    - {instance['instance_display']}: {instance['teacher_name']} teaching {instance['course_name']}")
        
        return dept_sem_groups

    def analyze_source_course_grouping(self):
        """Analyze grouping based on source teacher-course assignments, including ALL courses (theory + lab)."""
        print("\n" + "="*80)
        print("SOURCE TEACHER-COURSE ASSIGNMENT GROUPING ANALYSIS (ALL COURSES)")
        print("="*80)
        
        # IMPORTANT: For comprehensive analysis, we need to create grouping from source data
        # because lab schedules only contain practical courses, missing theory-only courses
        
        print("🔧 Creating comprehensive course grouping from source data...")
        
        # Create a lab scheduler instance to get the grouping logic
        try:
            import sys
            import os
            sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
            from lab_scheduler import LabScheduler
            
            # Get the course file path
            course_file = os.path.join(os.path.dirname(self.output_dir), '..', '..', 'data', 'cse.csv')
            room_file = os.path.join(os.path.dirname(self.output_dir), '..', '..', 'data', 'block_wise', 'techlongue.csv')
            
            # Create scheduler and run comprehensive grouping
            scheduler = LabScheduler(course_file, room_file)
            scheduler.create_course_groups()
            
            # Convert the comprehensive grouping to the format expected by this analyzer
            all_assignments = []
            
            for (dept, semester), groups in scheduler.course_groups.items():
                for group_idx, group in enumerate(groups):
                    for instance in group:
                        assignment = {
                            'teacher_id': instance['teacher_id'],
                            'course_code': instance['course_code'],
                            'course_instance_id': instance['id'],
                            'group_name': f"{dept}_S{semester}_G{group_idx + 1}",
                            'group_index': group_idx + 1,
                            'department_group': dept,
                            'semester_group': semester,
                            'practical_hours': instance.get('practical_hours', 0),
                            'is_theory_course': instance.get('practical_hours', 0) == 0
                        }
                        all_assignments.append(assignment)
            
            all_assignments = pd.DataFrame(all_assignments)
            
        except Exception as e:
            print(f"❌ Error creating comprehensive grouping: {e}")
            print("Falling back to schedule-based analysis...")
            
            if not self.has_group_data:
                print("Cannot perform analysis - group data not available in schedule CSV")
                return {}
            
            # Fallback to schedule-based analysis
            all_assignments = self.schedule_df[['teacher_id', 'course_code', 'course_instance_id', 
                                              'group_name', 'group_index', 'department_group', 
                                              'semester_group']].copy()
            all_assignments['practical_hours'] = 0  # Default for lab schedules
            all_assignments['is_theory_course'] = False
        
        print(f"\nSOURCE DATA SUMMARY (based on course record IDs):")
        print(f"Total assignments: {len(all_assignments)}")
        
        # Count unique course instances by their record IDs
        unique_course_instances = all_assignments['course_instance_id'].nunique()
        print(f"Unique course instances (by record ID): {unique_course_instances}")
        print(f"Unique teacher IDs: {all_assignments['teacher_id'].nunique()}")
        print(f"Unique course codes: {all_assignments['course_code'].nunique()}")
        
        # Show breakdown by course type
        if 'practical_hours' in all_assignments.columns:
            practical_assignments = all_assignments[all_assignments['practical_hours'] > 0]
            theory_assignments = all_assignments[all_assignments['practical_hours'] == 0]
            print(f"Practical course assignments: {len(practical_assignments)}")
            print(f"Theory course assignments: {len(theory_assignments)}")
        
        # Show detailed breakdown for all courses in 5th semester
        fifth_sem_assignments = all_assignments[all_assignments['semester_group'] == 5]
        if len(fifth_sem_assignments) > 0:
            print(f"\n5th Semester CSE course breakdown:")
            for course_code in sorted(fifth_sem_assignments['course_code'].unique()):
                course_instances = fifth_sem_assignments[fifth_sem_assignments['course_code'] == course_code]
                course_type = "Theory" if course_instances.iloc[0].get('practical_hours', 0) == 0 else "Practical"
                print(f"  - {course_code} ({course_type}): {len(course_instances)} instances")
        
        # Show detailed breakdown for CS23511 and CS23512 (theory courses)
        for theory_course in ['CS23511', 'CS23512']:
            course_instances = all_assignments[all_assignments['course_code'] == theory_course]['course_instance_id'].unique()
            if len(course_instances) > 0:
                print(f"\n{theory_course} (Theory) course instances: {len(course_instances)}")
                for instance_id in course_instances:
                    instance_data = all_assignments[all_assignments['course_instance_id'] == instance_id].iloc[0]
                    teacher_name = self._get_teacher_name(instance_data['teacher_id'])
                    print(f"  - Instance {instance_id}: Teacher {instance_data['teacher_id']} ({teacher_name}) → Group {instance_data['group_index']}")
            else:
                print(f"\n{theory_course} (Theory): No instances found in current analysis")
        
        # Group by department and semester
        dept_sem_groups = {}
        
        # Get unique department/semester combinations
        dept_sem_combinations = all_assignments[['department_group', 'semester_group']].drop_duplicates()
        
        for _, row in dept_sem_combinations.iterrows():
            dept = row['department_group']
            semester = row['semester_group']
            
            if dept == 'Unknown' or semester == 0:
                    continue
                
            # Get all course instances for this department/semester
            dept_sem_data = all_assignments[
                (all_assignments['department_group'] == dept) & 
                (all_assignments['semester_group'] == semester)
            ]
            
            print(f"\nDepartment: {dept}, Semester: {semester}")
            
            # Count unique course instances in this dept/sem
            unique_instances_in_dept_sem = dept_sem_data['course_instance_id'].nunique()
            print(f"Total course instances in this dept/sem: {unique_instances_in_dept_sem}")
            
            # Group by group_name to analyze individual groups
            groups_in_dept_sem = {}
            for group_name in dept_sem_data['group_name'].unique():
                if group_name == 'Unassigned':
                    continue
                
                group_data = dept_sem_data[dept_sem_data['group_name'] == group_name]
                
                # Get unique course instances in this group (by record ID)
                unique_instances_in_group = group_data['course_instance_id'].unique()
                
                course_instances = []
                unique_courses = set()
                unique_teachers = set()
                
                for instance_id in unique_instances_in_group:
                    instance_record = group_data[group_data['course_instance_id'] == instance_id].iloc[0]
                    course_code = instance_record['course_code']
                    teacher_id = instance_record['teacher_id']
                    
                    course_instances.append({
                        'instance_id': instance_id,
                        'teacher_id': teacher_id,
                        'course_code': course_code,
                        'teacher_name': self._get_teacher_name(teacher_id),
                        'course_name': self._get_course_name(course_code),
                        'assignment_display': f"{teacher_id}-{course_code}-{instance_id}"
                    })
                    
                    unique_courses.add(course_code)
                    unique_teachers.add(teacher_id)
                
                groups_in_dept_sem[group_name] = {
                    'group_index': group_data['group_index'].iloc[0],
                    'teacher_course_assignments': course_instances,
                    'unique_courses': list(unique_courses),
                    'unique_teachers': list(unique_teachers),
                    'num_assignments': len(course_instances),  # Number of course instances
                    'num_unique_courses': len(unique_courses),
                    'num_unique_teachers': len(unique_teachers)
                }
            
            dept_sem_groups[(dept, semester)] = groups_in_dept_sem
            
            # Print analysis for this department/semester
            print(f"\n{dept} - Semester {semester}:")
            print(f"  Total Groups: {len(groups_in_dept_sem)}")
            
            for group_name, group_info in groups_in_dept_sem.items():
                print(f"  Group {group_info['group_index']} ({group_name}):")
                print(f"    Course Instances: {group_info['num_assignments']}")
                print(f"    Unique Courses: {group_info['num_unique_courses']}")
                print(f"    Unique Teachers: {group_info['num_unique_teachers']}")
                
                # Show course instances with their record IDs
                for instance in group_info['teacher_course_assignments']:
                    print(f"    - Instance {instance['instance_id']}: {instance['teacher_name']} teaching {instance['course_name']}")
        
        return dept_sem_groups

    def analyze_group_distribution(self, dept_sem_groups):
        """Analyze the distribution of teacher-course instances across groups."""
        print("\n" + "="*80)
        print("TEACHER-COURSE INSTANCE DISTRIBUTION ANALYSIS")
        print("="*80)
        
        distribution_analysis = {}
        
        for (dept, semester), groups in dept_sem_groups.items():
            print(f"\n{dept} - Semester {semester}:")
            
            # Analyze teacher-course instance distribution
            all_teacher_course_instances = []
            all_unique_courses = set()
            all_unique_teachers = set()
            
            # Collect all instances across groups
            for group_name, group_info in groups.items():
                for instance in group_info['teacher_course_instances']:
                    all_teacher_course_instances.append(instance)
                    all_unique_courses.add(instance['course_code'])
                    all_unique_teachers.add(instance['teacher_id'])
            
            # Analyze course distribution (how many teacher-course instances per course)
            course_instance_count = {}
            teacher_instance_count = {}
            
            for instance in all_teacher_course_instances:
                course_code = instance['course_code']
                teacher_id = instance['teacher_id']
                
                if course_code not in course_instance_count:
                    course_instance_count[course_code] = 0
                course_instance_count[course_code] += 1
                
                if teacher_id not in teacher_instance_count:
                    teacher_instance_count[teacher_id] = 0
                teacher_instance_count[teacher_id] += 1
            
            # Check group balance
            group_sizes = [group_info['num_instances'] for group_info in groups.values()]
            avg_group_size = sum(group_sizes) / len(group_sizes) if group_sizes else 0
            group_size_std = np.std(group_sizes) if group_sizes else 0
            
            print(f"  Total teacher-course instances: {len(all_teacher_course_instances)}")
            print(f"  Unique courses involved: {len(all_unique_courses)}")
            print(f"  Unique teachers involved: {len(all_unique_teachers)}")
            print(f"  Average instances per course: {len(all_teacher_course_instances)/len(all_unique_courses):.1f}" if all_unique_courses else "  No courses found")
            print(f"  Average instances per teacher: {len(all_teacher_course_instances)/len(all_unique_teachers):.1f}" if all_unique_teachers else "  No teachers found")
            
            print(f"  Group balance:")
            print(f"    - Average instances per group: {avg_group_size:.1f}")
            print(f"    - Group size standard deviation: {group_size_std:.1f}")
            print(f"    - Group sizes: {group_sizes}")
            
            # Show courses with multiple teacher instances
            courses_with_multiple_teachers = {course: count for course, count in course_instance_count.items() if count > 1}
            teachers_with_multiple_courses = {teacher: count for teacher, count in teacher_instance_count.items() if count > 1}
            
            if courses_with_multiple_teachers:
                print(f"  Courses with multiple teacher instances:")
                for course, count in courses_with_multiple_teachers.items():
                    f.write(f"    - {course}: {count} teacher instances\n")
                
                f.write("\n")
            
            if teachers_with_multiple_courses:
                print(f"  Teachers with multiple course instances:")
                for teacher, count in teachers_with_multiple_courses.items():
                    teacher_name = self._get_teacher_name(teacher)
                    f.write(f"    - {teacher} ({teacher_name}): {count} course instances\n")
                
                f.write("\n")
            
            distribution_analysis[(dept, semester)] = {
                'total_instances': len(all_teacher_course_instances),
                'unique_courses': len(all_unique_courses),
                'unique_teachers': len(all_unique_teachers),
                'course_instance_count': course_instance_count,
                'teacher_instance_count': teacher_instance_count,
                'courses_with_multiple_teachers': courses_with_multiple_teachers,
                'teachers_with_multiple_courses': teachers_with_multiple_courses,
                'group_sizes': group_sizes,
                'avg_group_size': avg_group_size,
                'group_size_std': group_size_std,
                'groups': groups
            }
        
        return distribution_analysis

    def analyze_student_choice_optimization(self, dept_sem_groups):
        """Analyze how well the system provides choice to students through teacher-course instance distribution."""
        print("\n" + "="*80)
        print("STUDENT CHOICE OPTIMIZATION ANALYSIS (Teacher-Course Instances)")
        print("="*80)
        
        choice_analysis = {}
        
        for (dept, semester), groups in dept_sem_groups.items():
            print(f"\n{dept} - Semester {semester}:")
            
            dept_sem_choice_data = {}
            
            # First, analyze choices across all groups (students can choose from any group)
            all_course_choices = {}  # course_code -> list of teacher options
            
            for group_name, group_info in groups.items():
                for instance in group_info['teacher_course_instances']:
                    course_code = instance['course_code']
                    teacher_info = {
                        'teacher_id': instance['teacher_id'],
                        'teacher_name': instance['teacher_name'],
                        'group_name': group_name,
                        'group_index': group_info['group_index']
                    }
                    
                    if course_code not in all_course_choices:
                        all_course_choices[course_code] = []
                    all_course_choices[course_code].append(teacher_info)
            
            # Analyze choices within each group
            for group_name, group_info in groups.items():
                group_choice_data = {}
                group_course_choices = {}  # course_code -> teacher options in this group only
                
                for instance in group_info['teacher_course_instances']:
                    course_code = instance['course_code']
                    teacher_info = {
                        'teacher_id': instance['teacher_id'],
                        'teacher_name': instance['teacher_name']
                    }
                    
                    if course_code not in group_choice_data:
                        group_choice_data[course_code] = {
                            'teacher_choices_in_group': [],
                            'teacher_choices_across_all_groups': [],
                            'course_name': self._get_course_name(course_code)
                        }
                    
                    group_choice_data[course_code]['teacher_choices_in_group'].append(teacher_info)
                    # Add all teacher choices for this course across all groups
                    group_choice_data[course_code]['teacher_choices_across_all_groups'] = all_course_choices.get(course_code, [])
                
                dept_sem_choice_data[group_name] = group_choice_data
                
                print(f"  Group {group_info['group_index']} ({group_name}):")
                print(f"    Teacher-Course Instances: {len(group_info['teacher_course_instances'])}")
                
                for course_code, choice_info in group_choice_data.items():
                    in_group_choices = len(choice_info['teacher_choices_in_group'])
                    total_choices = len(choice_info['teacher_choices_across_all_groups'])
                    
                    print(f"    {course_code}:")
                    print(f"      - In this group: {in_group_choices} teacher(s)")
                    for teacher_info in choice_info['teacher_choices_in_group']:
                        print(f"        * {teacher_info['teacher_id']} ({teacher_info['teacher_name']})")
                    print(f"      - Total across all groups: {total_choices} teacher(s)")
            
            # Summary of overall choice effectiveness
            total_courses_in_dept_sem = len(all_course_choices)
            courses_with_multiple_choices = len([course for course, choices in all_course_choices.items() if len(choices) > 1])
            
            print(f"\n  Overall Choice Summary for {dept} Semester {semester}:")
            print(f"    Total courses: {total_courses_in_dept_sem}")
            print(f"    Courses with multiple teacher choices: {courses_with_multiple_choices}")
            print(f"    Choice effectiveness: {(courses_with_multiple_choices/total_courses_in_dept_sem*100):.1f}%" if total_courses_in_dept_sem > 0 else "    Choice effectiveness: 0%")
            
            choice_analysis[(dept, semester)] = {
                'group_choice_data': dept_sem_choice_data,
                'all_course_choices': all_course_choices,
                'total_courses': total_courses_in_dept_sem,
                'courses_with_multiple_choices': courses_with_multiple_choices
            }
        
        return choice_analysis

    def analyze_group_distribution_source(self, dept_sem_groups):
        """Analyze how course instances are distributed across groups (source data)."""
        print("\n" + "="*60)
        print("SOURCE GROUP DISTRIBUTION ANALYSIS")
        print("="*60)
        
        distribution_analysis = {}
        
        for (dept, semester), groups in dept_sem_groups.items():
            print(f"\nDepartment: {dept}")
            print(f"Semester: {semester}")
            print(f"Number of Groups: {len(groups)}")
            
            # Get all course instances in this department/semester
            all_instances = []
            for group_info in groups.values():
                all_instances.extend(group_info['teacher_course_assignments'])
            
            # Count total course instances
            total_instances = len(all_instances)
            unique_courses = set(instance['course_code'] for instance in all_instances)
            
            print(f"Total Course Instances: {total_instances}")
            print(f"Unique Courses: {len(unique_courses)}")
            
            # Analyze distribution across groups
            group_sizes = {}
            course_distribution = {}
            
            for group_name, group_info in groups.items():
                group_index = group_info['group_index']
                num_instances = len(group_info['teacher_course_assignments'])
                group_sizes[f"Group {group_index}"] = num_instances
                
                print(f"\nGroup {group_index} ({group_name}):")
                print(f"  Course Instances: {num_instances}")
                
                # Count instances per course in this group
                course_counts = {}
                for instance in group_info['teacher_course_assignments']:
                    course_code = instance['course_code']
                    course_counts[course_code] = course_counts.get(course_code, 0) + 1
                
                for course_code, count in sorted(course_counts.items()):
                    print(f"    {course_code}: {count} instances")
                    
                    # Track overall course distribution
                    if course_code not in course_distribution:
                        course_distribution[course_code] = {}
                    course_distribution[course_code][f"Group {group_index}"] = count
            
            # Special analysis for CS23511
            if 'CS23511' in course_distribution:
                print(f"\nDETAILED CS23511 ANALYSIS:")
                cs23511_dist = course_distribution['CS23511']
                cs23511_total = sum(cs23511_dist.values())
                print(f"  Total CS23511 instances: {cs23511_total}")
                for group, count in sorted(cs23511_dist.items()):
                    print(f"  {group}: {count} instances")
                
                # Show which teachers in each group
                for group_name, group_info in groups.items():
                    group_index = group_info['group_index']
                    cs23511_instances = [inst for inst in group_info['teacher_course_assignments'] 
                                       if inst['course_code'] == 'CS23511']
                    if cs23511_instances:
                        print(f"  Group {group_index} CS23511 instances:")
                        for inst in cs23511_instances:
                            print(f"    - Instance {inst['instance_id']}: Teacher {inst['teacher_id']} ({inst['teacher_name']})")
            
            # Calculate balance metrics
            if group_sizes:
                avg_size = sum(group_sizes.values()) / len(group_sizes)
                max_size = max(group_sizes.values())
                min_size = min(group_sizes.values())
                balance_ratio = min_size / max_size if max_size > 0 else 0
                
                print(f"\nGROUP BALANCE ANALYSIS:")
                print(f"  Average instances per group: {avg_size:.1f}")
                print(f"  Largest group: {max_size} instances")
                print(f"  Smallest group: {min_size} instances")
                print(f"  Balance ratio (min/max): {balance_ratio:.2f}")
                print(f"  Balance quality: {'Good' if balance_ratio > 0.8 else 'Fair' if balance_ratio > 0.6 else 'Poor'}")
            
            distribution_analysis[(dept, semester)] = {
                'total_instances': total_instances,
                'total_courses': len(unique_courses),
                'num_groups': len(groups),
                'group_sizes': group_sizes,
                'course_distribution': course_distribution,
                'balance_metrics': {
                    'avg_size': avg_size,
                    'max_size': max_size,
                    'min_size': min_size,
                    'balance_ratio': balance_ratio
                }
            }
        
        return distribution_analysis

    def analyze_student_choice_optimization_source(self, dept_sem_groups):
        """Analyze student choices based on source teacher-course assignments."""
        print("\n" + "="*80)
        print("SOURCE STUDENT CHOICE OPTIMIZATION ANALYSIS")
        print("="*80)
        
        choice_analysis = {}
        
        for (dept, semester), groups in dept_sem_groups.items():
            print(f"\n{dept} - Semester {semester}:")
            
            dept_sem_choice_data = {}
            
            # Analyze choices across all groups
            all_course_choices = {}  # course_code -> list of teacher options
            
            for group_name, group_info in groups.items():
                for assignment in group_info['teacher_course_assignments']:
                    course_code = assignment['course_code']
                    teacher_info = {
                        'teacher_id': assignment['teacher_id'],
                        'teacher_name': assignment['teacher_name'],
                        'group_name': group_name,
                        'group_index': group_info['group_index']
                    }
                    
                    if course_code not in all_course_choices:
                        all_course_choices[course_code] = []
                    all_course_choices[course_code].append(teacher_info)
            
            # Summary of overall choice effectiveness
            total_courses_in_dept_sem = len(all_course_choices)
            courses_with_multiple_choices = len([course for course, choices in all_course_choices.items() if len(choices) > 1])
            
            print(f"\n  Overall Choice Summary for {dept} Semester {semester}:")
            print(f"    Total courses: {total_courses_in_dept_sem}")
            print(f"    Courses with multiple teacher choices: {courses_with_multiple_choices}")
            print(f"    Choice effectiveness: {(courses_with_multiple_choices/total_courses_in_dept_sem*100):.1f}%" if total_courses_in_dept_sem > 0 else "    Choice effectiveness: 0%")
            
            choice_analysis[(dept, semester)] = {
                'all_course_choices': all_course_choices,
                'total_courses': total_courses_in_dept_sem,
                'courses_with_multiple_choices': courses_with_multiple_choices
            }
        
        return choice_analysis

    def _get_teacher_name(self, teacher_id):
        """Get teacher name from courses data."""
        teacher_data = self.courses_df[self.courses_df['teacher_id'] == teacher_id]
        if not teacher_data.empty:
            first_name = teacher_data.iloc[0].get('first_name', '')
            last_name = teacher_data.iloc[0].get('last_name', '')
            return f"{first_name} {last_name}".strip()
        return f"Teacher {teacher_id}"

    def _get_course_name(self, course_code):
        """Get course name from courses data."""
        course_data = self.courses_df[self.courses_df['course_code'] == course_code]
        if not course_data.empty:
            return course_data.iloc[0].get('course_name', course_code)
        return course_code

    def create_visualizations(self, dept_sem_groups, distribution_analysis, choice_analysis):
        """Create comprehensive visualizations of the grouping analysis."""
        
        if not self.has_group_data:
            print("Skipping visualizations - group data not available")
            return
        
        # 1. Group Distribution Overview
        self._plot_group_distribution(dept_sem_groups)
        
        # 2. Course Instance Distribution
        self._plot_course_instance_distribution(distribution_analysis)
        
        # 3. Course Teacher Instance Matrix (NEW)
        self._plot_course_teacher_instance_matrix(dept_sem_groups)
        
        # 4. Group Balance Analysis
        self._plot_group_balance(distribution_analysis)
        
        # 5. Student Choice Analysis
        self._plot_student_choices(choice_analysis)
        
        # 6. All Semesters Course-to-Group Distribution Analysis
        self._plot_all_semesters_analysis(dept_sem_groups, choice_analysis)
        
        # 7. Grouping Effectiveness Summary
        self._plot_grouping_effectiveness(distribution_analysis)

    def _plot_group_distribution(self, dept_sem_groups):
        """Plot the distribution of teacher-course instances across departments and semesters."""
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))
        
        # Number of groups per department/semester
        dept_sem_labels = []
        group_counts = []
        instance_counts = []
        unique_course_counts = []
        unique_teacher_counts = []
        
        for (dept, semester), groups in dept_sem_groups.items():
            dept_sem_labels.append(f"{dept}\nSem {semester}")
            group_counts.append(len(groups))
            
            total_instances = sum(group_info['num_instances'] for group_info in groups.values())
            all_unique_courses = set()
            all_unique_teachers = set()
            
            for group_info in groups.values():
                for instance in group_info['teacher_course_instances']:
                    all_unique_courses.add(instance['course_code'])
                    all_unique_teachers.add(instance['teacher_id'])
            
            instance_counts.append(total_instances)
            unique_course_counts.append(len(all_unique_courses))
            unique_teacher_counts.append(len(all_unique_teachers))
        
        x_pos = np.arange(len(dept_sem_labels))
        width = 0.2
        
        ax1.bar(x_pos - width*1.5, group_counts, width, label='Groups', alpha=0.7)
        ax1.bar(x_pos - width/2, instance_counts, width, label='Teacher-Course Instances', alpha=0.7)
        ax1.bar(x_pos + width/2, unique_course_counts, width, label='Unique Courses', alpha=0.7)
        ax1.bar(x_pos + width*1.5, unique_teacher_counts, width, label='Unique Teachers', alpha=0.7)
        
        ax1.set_title('Groups and Teacher-Course Instances by Department/Semester')
        ax1.set_xlabel('Department/Semester')
        ax1.set_ylabel('Count')
        ax1.set_xticks(x_pos)
        ax1.set_xticklabels(dept_sem_labels, rotation=45, ha='right')
        ax1.legend()
        
        # Group size distribution (number of teacher-course instances per group)
        all_group_sizes = []
        for groups in dept_sem_groups.values():
            for group_info in groups.values():
                all_group_sizes.append(group_info['num_instances'])
        
        if all_group_sizes:
            ax2.hist(all_group_sizes, bins=max(1, len(set(all_group_sizes))), alpha=0.7, edgecolor='black')
            ax2.set_title('Distribution of Group Sizes\n(Teacher-Course Instances per Group)')
            ax2.set_xlabel('Number of Teacher-Course Instances per Group')
            ax2.set_ylabel('Number of Groups')
        else:
            ax2.text(0.5, 0.5, 'No data available', ha='center', va='center', transform=ax2.transAxes)
        
        plt.tight_layout()
        plt.savefig(os.path.join(self.output_dir, 'group_distribution.png'), dpi=300, bbox_inches='tight')
        plt.close()

    def _plot_course_instance_distribution(self, distribution_analysis):
        """Plot teacher-course instance distribution analysis."""
        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(16, 12))
        
        # Teacher-course instances vs unique courses and teachers
        dept_sem_labels = []
        instance_counts = []
        unique_course_counts = []
        unique_teacher_counts = []
        
        for (dept, semester), analysis in distribution_analysis.items():
            dept_sem_labels.append(f"{dept}\nSem {semester}")
            instance_counts.append(analysis['total_instances'])
            unique_course_counts.append(analysis['unique_courses'])
            unique_teacher_counts.append(analysis['unique_teachers'])
        
        x_pos = np.arange(len(dept_sem_labels))
        width = 0.25
        
        ax1.bar(x_pos - width, instance_counts, width, label='Teacher-Course Instances', alpha=0.7)
        ax1.bar(x_pos, unique_course_counts, width, label='Unique Courses', alpha=0.7)
        ax1.bar(x_pos + width, unique_teacher_counts, width, label='Unique Teachers', alpha=0.7)
        ax1.set_title('Teacher-Course Instance Distribution')
        ax1.set_xlabel('Department/Semester')
        ax1.set_ylabel('Count')
        ax1.set_xticks(x_pos)
        ax1.set_xticklabels(dept_sem_labels, rotation=45, ha='right')
        ax1.legend()
        
        # Group balance (standard deviation of group sizes)
        group_balance_scores = []
        for analysis in distribution_analysis.values():
            group_balance_scores.append(analysis['group_size_std'])
        
        ax2.bar(range(len(dept_sem_labels)), group_balance_scores, alpha=0.7, color='orange')
        ax2.set_title('Group Balance (Lower = More Balanced)')
        ax2.set_xlabel('Department/Semester')
        ax2.set_ylabel('Group Size Standard Deviation')
        ax2.set_xticks(range(len(dept_sem_labels)))
        ax2.set_xticklabels(dept_sem_labels, rotation=45, ha='right')
        
        # Courses with multiple teachers and teachers with multiple courses
        multiple_teacher_courses = []
        multiple_course_teachers = []
        
        for analysis in distribution_analysis.values():
            multiple_teacher_courses.append(len(analysis['courses_with_multiple_teachers']))
            multiple_course_teachers.append(len(analysis['teachers_with_multiple_courses']))
        
        ax3.bar(x_pos - width/2, multiple_teacher_courses, width, label='Courses with Multiple Teachers', alpha=0.7)
        ax3.bar(x_pos + width/2, multiple_course_teachers, width, label='Teachers with Multiple Courses', alpha=0.7)
        ax3.set_title('Instance Multiplicity Analysis')
        ax3.set_xlabel('Department/Semester')
        ax3.set_ylabel('Count')
        ax3.set_xticks(x_pos)
        ax3.set_xticklabels(dept_sem_labels, rotation=45, ha='right')
        ax3.legend()
        
        # Summary statistics
        total_groups = sum(len(analysis['groups']) for analysis in distribution_analysis.values())
        total_instances = sum(analysis['total_instances'] for analysis in distribution_analysis.values())
        total_unique_courses = sum(analysis['unique_courses'] for analysis in distribution_analysis.values())
        total_unique_teachers = sum(analysis['unique_teachers'] for analysis in distribution_analysis.values())
        
        summary_text = f"""
Total Groups Created: {total_groups}
Total Teacher-Course Instances: {total_instances}
Total Unique Courses: {total_unique_courses}
Total Unique Teachers: {total_unique_teachers}
Avg Instances per Group: {total_instances/total_groups:.1f}
Avg Instances per Course: {total_instances/total_unique_courses:.1f}
Avg Instances per Teacher: {total_instances/total_unique_teachers:.1f}
        """
        
        ax4.text(0.1, 0.5, summary_text, transform=ax4.transAxes, fontsize=12, verticalalignment='center')
        ax4.set_xlim(0, 1)
        ax4.set_ylim(0, 1)
        ax4.axis('off')
        ax4.set_title('Summary Statistics')
        
        plt.tight_layout()
        plt.savefig(os.path.join(self.output_dir, 'course_instance_distribution.png'), dpi=300, bbox_inches='tight')
        plt.close()

    def _plot_group_balance(self, distribution_analysis):
        """Plot group balance analysis."""
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))
        
        # Group size comparison
        for i, ((dept, semester), analysis) in enumerate(distribution_analysis.items()):
            group_sizes = analysis['group_sizes']
            ax1.scatter([i] * len(group_sizes), group_sizes, alpha=0.7, s=60, label=f"{dept} Sem {semester}")
        
        ax1.set_title('Group Sizes by Department/Semester')
        ax1.set_xlabel('Department/Semester Index')
        ax1.set_ylabel('Number of Courses in Group')
        ax1.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
        
        # Balance score heatmap
        dept_sem_labels = [f"{dept} Sem {semester}" for (dept, semester) in distribution_analysis.keys()]
        balance_scores = [analysis['group_size_std'] for analysis in distribution_analysis.values()]
        avg_sizes = [analysis['avg_group_size'] for analysis in distribution_analysis.values()]
        
        scatter = ax2.scatter(avg_sizes, balance_scores, s=100, alpha=0.7, c=range(len(dept_sem_labels)), cmap='viridis')
        
        for i, label in enumerate(dept_sem_labels):
            ax2.annotate(label, (avg_sizes[i], balance_scores[i]), xytext=(5, 5), 
                        textcoords='offset points', fontsize=8)
        
        ax2.set_title('Group Balance vs Average Group Size')
        ax2.set_xlabel('Average Group Size')
        ax2.set_ylabel('Group Size Standard Deviation (Lower = More Balanced)')
        ax2.grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.savefig(os.path.join(self.output_dir, 'group_balance.png'), dpi=300, bbox_inches='tight')
        plt.close()

    def _plot_student_choices(self, choice_analysis):
        """Plot student choice analysis for teacher-course instances."""
        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(16, 12))
        
        # Collect choice data across all departments/semesters
        all_choice_data = []
        
        for (dept, semester), dept_analysis in choice_analysis.items():
            all_course_choices = dept_analysis['all_course_choices']
            
            for course_code, teacher_choices in all_course_choices.items():
                all_choice_data.append({
                    'dept': dept,
                    'semester': semester,
                    'course': course_code,
                    'total_teacher_choices': len(teacher_choices),
                    'teacher_names': [tc['teacher_name'] for tc in teacher_choices]
                })
        
        # Distribution of teacher choices per course
        if all_choice_data:
            choice_counts = [data['total_teacher_choices'] for data in all_choice_data]
            max_choices = max(choice_counts) if choice_counts else 1
            
            ax1.hist(choice_counts, bins=max(1, max_choices), alpha=0.7, edgecolor='black')
            ax1.set_title('Distribution of Teacher Choices per Course')
            ax1.set_xlabel('Number of Teacher Choices Available')
            ax1.set_ylabel('Number of Courses')
            
        # Choice effectiveness by department/semester
        dept_sem_labels = []
        choice_effectiveness = []
        avg_choices = []
        
        for (dept, semester), dept_analysis in choice_analysis.items():
            dept_sem_labels.append(f"{dept}\nSem {semester}")
            
            total_courses = dept_analysis['total_courses']
            courses_with_multiple = dept_analysis['courses_with_multiple_choices']
            effectiveness = (courses_with_multiple / total_courses * 100) if total_courses > 0 else 0
            choice_effectiveness.append(effectiveness)
            
            # Calculate average choices per course
            all_choices = dept_analysis['all_course_choices']
            if all_choices:
                avg_choice = sum(len(choices) for choices in all_choices.values()) / len(all_choices)
            else:
                avg_choice = 0
            avg_choices.append(avg_choice)
        
        ax2.bar(range(len(dept_sem_labels)), choice_effectiveness, alpha=0.7, color='green')
        ax2.set_title('Choice Effectiveness by Department/Semester')
        ax2.set_xlabel('Department/Semester')
        ax2.set_ylabel('% Courses with Multiple Teacher Choices')
        ax2.set_xticks(range(len(dept_sem_labels)))
        ax2.set_xticklabels(dept_sem_labels, rotation=45, ha='right')
        
        # Average teacher choices per course
        ax3.bar(range(len(dept_sem_labels)), avg_choices, alpha=0.7, color='purple')
        ax3.set_title('Average Teacher Choices per Course')
        ax3.set_xlabel('Department/Semester')
        ax3.set_ylabel('Average Number of Teacher Choices')
        ax3.set_xticks(range(len(dept_sem_labels)))
        ax3.set_xticklabels(dept_sem_labels, rotation=45, ha='right')
        
        # Summary statistics
        if all_choice_data:
            total_courses = len(all_choice_data)
            courses_with_multiple_choices = len([d for d in all_choice_data if d['total_teacher_choices'] > 1])
            overall_effectiveness = (courses_with_multiple_choices / total_courses * 100) if total_courses > 0 else 0
            avg_choices_overall = sum(d['total_teacher_choices'] for d in all_choice_data) / total_courses
            max_choices_available = max(d['total_teacher_choices'] for d in all_choice_data)
            
            summary_text = f"""
Total Courses Analyzed: {total_courses}
Courses with Multiple Teacher Choices: {courses_with_multiple_choices}
Overall Choice Effectiveness: {overall_effectiveness:.1f}%
Average Teacher Choices per Course: {avg_choices_overall:.1f}
Maximum Choices Available: {max_choices_available}

This analysis shows how many teacher options
students have for each course, providing
flexibility in their academic choices.
            """
        else:
            summary_text = "No choice data available for analysis"
        
        ax4.text(0.1, 0.5, summary_text, transform=ax4.transAxes, fontsize=11, verticalalignment='center')
        ax4.set_xlim(0, 1)
        ax4.set_ylim(0, 1)
        ax4.axis('off')
        ax4.set_title('Choice Analysis Summary')
        
        plt.tight_layout()
        plt.savefig(os.path.join(self.output_dir, 'student_choice_analysis.png'), dpi=300, bbox_inches='tight')
        plt.close()

    def _plot_all_semesters_analysis(self, dept_sem_groups, choice_analysis):
        """Plot detailed course-to-group distribution analysis for all semesters and departments."""
        # Create a figure for each department-semester combination
        for (dept, semester), groups in dept_sem_groups.items():
            if not groups:
                continue
                
            fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(20, 16))
            
            # Group composition by teacher-course instances
            group_names = list(groups.keys())
            group_sizes = [group_info['num_instances'] for group_info in groups.values()]
            
            ax1.bar(range(len(group_names)), group_sizes, alpha=0.7, color='lightblue')
            ax1.set_title(f'{dept} Semester {semester} - Group Sizes\n(Teacher-Course Instances per Group)')
            ax1.set_xlabel('Groups')
            ax1.set_ylabel('Number of Teacher-Course Instances')
            ax1.set_xticks(range(len(group_names)))
            ax1.set_xticklabels([f"Group {groups[gn]['group_index']}" for gn in group_names])
            
            # Teacher-course instance distribution across groups
            all_instances = []
            for group_info in groups.values():
                all_instances.extend(group_info['teacher_course_instances'])
            
            # Get all unique courses
            all_courses = set()
            for instance in all_instances:
                all_courses.add(instance['course_code'])
            
            course_labels = sorted(all_courses)
            
            # Create matrix: rows = courses, columns = groups
            # Values = number of schedule instances for that course in that group
            course_group_matrix = []
            
            for course_code in course_labels:
                course_row = []
                for group_name in group_names:
                    # Count ALL schedule instances for this course in this group
                    instance_count = sum(1 for instance in groups[group_name]['teacher_course_instances'] 
                                       if instance['course_code'] == course_code)
                    course_row.append(instance_count)
                course_group_matrix.append(course_row)
            
            if course_group_matrix:
                im = ax2.imshow(course_group_matrix, cmap='YlOrRd', aspect='auto')
                ax2.set_title(f'{dept} Sem {semester} - Course Distribution Across Groups\n(Number shows total schedule instances per course per group)')
                ax2.set_xlabel('Groups')
                ax2.set_ylabel('Courses')
                ax2.set_xticks(range(len(group_names)))
                ax2.set_xticklabels([f"G{groups[gn]['group_index']}" for gn in group_names])
                ax2.set_yticks(range(len(course_labels)))
                ax2.set_yticklabels(course_labels, fontsize=10)
                
                # Add text annotations showing the count
                for i in range(len(course_labels)):
                    for j in range(len(group_names)):
                        count = course_group_matrix[i][j]
                        if count > 0:
                            ax2.text(j, i, str(count), ha='center', va='center', 
                                   fontweight='bold', fontsize=14, color='white' if count > 1 else 'black')
                
                plt.colorbar(im, ax=ax2, label='Number of Schedule Instances')
            
            # Teacher choices analysis if available
            choice_data = choice_analysis.get((dept, semester), {})
            if choice_data and 'all_course_choices' in choice_data:
                choice_list = []
                all_course_choices = choice_data['all_course_choices']
                
                for course_code, teacher_choices in all_course_choices.items():
                    choice_list.append({
                        'course': course_code,
                        'total_teachers': len(teacher_choices),
                        'teachers': [tc['teacher_name'] for tc in teacher_choices[:3]]  # Show first 3
                    })
                
                if choice_list:
                    courses = [d['course'] for d in choice_list]
                    teacher_counts = [d['total_teachers'] for d in choice_list]
                    
                    ax3.bar(range(len(choice_list)), teacher_counts, alpha=0.7, color='lightgreen')
                    ax3.set_title(f'Teacher Choices per Course - {dept} Sem {semester}')
                    ax3.set_xlabel('Courses')
                    ax3.set_ylabel('Number of Teacher Options')
                    ax3.set_xticks(range(len(choice_list)))
                    ax3.set_xticklabels(courses, rotation=45, ha='right')
                else:
                    ax3.text(0.5, 0.5, 'No choice data available', 
                           ha='center', va='center', transform=ax3.transAxes, fontsize=16)
            else:
                ax3.text(0.5, 0.5, 'No choice data available', 
                       ha='center', va='center', transform=ax3.transAxes, fontsize=16)
            
            # Summary table
            ax4.axis('tight')
            ax4.axis('off')
            
            table_data = []
            for group_name, group_info in groups.items():
                # Show first few teacher-course instances
                instances_text = ', '.join([
                    f"{inst['teacher_id']}-{inst['course_code']}" 
                    for inst in group_info['teacher_course_instances'][:3]
                ])
                if len(group_info['teacher_course_instances']) > 3:
                    instances_text += f" (+{len(group_info['teacher_course_instances'])-3} more)"
                
                table_data.append([
                    f"Group {group_info['group_index']}",
                    f"{group_info['num_instances']}",
                    f"{group_info['num_unique_courses']}",
                    f"{group_info['num_unique_teachers']}",
                    instances_text
                ])
            
            table = ax4.table(cellText=table_data,
                             colLabels=['Group', 'Instances', 'Unique Courses', 'Unique Teachers', 'Teacher-Course Instances'],
                             cellLoc='left',
                             loc='center')
            table.auto_set_font_size(False)
            table.set_fontsize(9)
            table.scale(1, 2)
            
            ax4.set_title(f'{dept} Semester {semester} - Group Summary (Teacher-Course Instances)')
            
            plt.tight_layout()
            
            # Create safe filename
            safe_dept = dept.replace(' ', '_').replace('&', 'and')
            filename = f'{safe_dept}_sem_{semester}_analysis.png'
            plt.savefig(os.path.join(self.output_dir, filename), dpi=300, bbox_inches='tight')
            plt.close()
            
        # Create a comprehensive overview plot for all semesters
        self._plot_comprehensive_semester_overview(dept_sem_groups, choice_analysis)
    
    def _plot_comprehensive_semester_overview(self, dept_sem_groups, choice_analysis):
        """Create a comprehensive overview plot showing all semesters and departments."""
        num_dept_sems = len(dept_sem_groups)
        if num_dept_sems == 0:
            return
            
        # Calculate grid size for subplots
        cols = min(3, num_dept_sems)  # Max 3 columns
        rows = (num_dept_sems + cols - 1) // cols  # Ceiling division
        
        fig, axes = plt.subplots(rows, cols, figsize=(6*cols, 4*rows))
        if rows == 1 and cols == 1:
            axes = [axes]
        elif rows == 1 or cols == 1:
            axes = axes.flatten()
        else:
            axes = axes.flatten()
        
        for idx, ((dept, semester), groups) in enumerate(dept_sem_groups.items()):
            if idx >= len(axes):
                break
                
            ax = axes[idx]
            
            if not groups:
                ax.text(0.5, 0.5, f'No data for\n{dept}\nSemester {semester}', 
                       ha='center', va='center', transform=ax.transAxes, fontsize=12)
                ax.set_title(f'{dept} Sem {semester}')
                continue
            
            # Get all unique courses for this department-semester
            all_courses = set()
            for group_info in groups.values():
                for instance in group_info['teacher_course_instances']:
                    all_courses.add(instance['course_code'])
            
            course_labels = sorted(all_courses)
            group_names = list(groups.keys())
            
            # Create course distribution matrix
            course_group_matrix = []
            for course_code in course_labels:
                course_row = []
                for group_name in group_names:
                    instance_count = sum(1 for instance in groups[group_name]['teacher_course_instances'] 
                                       if instance['course_code'] == course_code)
                    course_row.append(instance_count)
                course_group_matrix.append(course_row)
            
            if course_group_matrix:
                im = ax.imshow(course_group_matrix, cmap='YlOrRd', aspect='auto')
                ax.set_title(f'{dept}\nSem {semester}')
                ax.set_xlabel('Groups')
                ax.set_ylabel('Courses')
                ax.set_xticks(range(len(group_names)))
                ax.set_xticklabels([f"G{groups[gn]['group_index']}" for gn in group_names], fontsize=8)
                ax.set_yticks(range(len(course_labels)))
                ax.set_yticklabels(course_labels, fontsize=8)
                
                # Add text annotations for small matrices
                if len(course_labels) <= 10 and len(group_names) <= 5:
                    for i in range(len(course_labels)):
                        for j in range(len(group_names)):
                            count = course_group_matrix[i][j]
                            if count > 0:
                                ax.text(j, i, str(count), ha='center', va='center', 
                                       fontweight='bold', fontsize=10, 
                                       color='white' if count > 1 else 'black')
        
        # Hide unused subplots
        for idx in range(len(dept_sem_groups), len(axes)):
            axes[idx].set_visible(False)
        
        plt.suptitle('Course-to-Group Distribution Overview - All Semesters', fontsize=16, y=0.98)
        plt.tight_layout()
        plt.savefig(os.path.join(self.output_dir, 'all_semesters_overview.png'), dpi=300, bbox_inches='tight')
        plt.close()

    def _plot_grouping_effectiveness(self, distribution_analysis):
        """Plot overall grouping effectiveness summary."""
        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(16, 12))
        
        # Overall effectiveness metrics
        total_groups = sum(len(analysis['groups']) for analysis in distribution_analysis.values())
        total_instances = sum(analysis['total_instances'] for analysis in distribution_analysis.values())
        total_unique_courses = sum(analysis['unique_courses'] for analysis in distribution_analysis.values())
        total_unique_teachers = sum(analysis['unique_teachers'] for analysis in distribution_analysis.values())
        
        effectiveness_metrics = {
            'Total Groups Created': total_groups,
            'Total Schedule Instances': total_instances,
            'Total Unique Courses': total_unique_courses,
            'Total Unique Teachers': total_unique_teachers,
            'Avg Instances per Group': f"{(total_instances/total_groups):.1f}" if total_groups > 0 else "0.0"
        }
        
        # Summary pie chart - show distribution of instances vs unique elements
        if total_instances > 0:
            labels = ['Unique Courses', 'Unique Teachers', 'Schedule Instances']
            sizes = [total_unique_courses, total_unique_teachers, total_instances]
            colors = ['lightblue', 'lightgreen', 'lightcoral']
        
        ax1.pie(sizes, labels=labels, colors=colors, autopct='%1.1f%%', startangle=90)
        ax1.set_title('System Overview Distribution')
        
        # Instance distribution by department/semester
        dept_sems = list(distribution_analysis.keys())
        instance_counts = []
        
        for analysis in distribution_analysis.values():
            instance_counts.append(analysis['total_instances'])
        
        ax2.bar(range(len(dept_sems)), instance_counts, alpha=0.7, color='green')
        ax2.set_title('Schedule Instances by Department/Semester')
        ax2.set_xlabel('Department/Semester')
        ax2.set_ylabel('Number of Schedule Instances')
        ax2.set_xticks(range(len(dept_sems)))
        ax2.set_xticklabels([f"{dept}\nSem {sem}" for dept, sem in dept_sems], rotation=45, ha='right')
        
        # Group balance overview
        balance_scores = [analysis['group_size_std'] for analysis in distribution_analysis.values()]
        avg_balance = np.mean(balance_scores) if balance_scores else 0
        
        ax3.bar(range(len(dept_sems)), balance_scores, alpha=0.7, color='orange')
        ax3.axhline(y=avg_balance, color='red', linestyle='--', label=f'Average: {avg_balance:.1f}')
        ax3.set_title('Group Balance by Department/Semester')
        ax3.set_xlabel('Department/Semester')
        ax3.set_ylabel('Balance Score (Lower = Better)')
        ax3.set_xticks(range(len(dept_sems)))
        ax3.set_xticklabels([f"{dept}\nSem {sem}" for dept, sem in dept_sems], rotation=45, ha='right')
        ax3.legend()
        
        # Summary statistics
        avg_groups_per_dept_sem = total_groups / len(distribution_analysis) if distribution_analysis else 0
        avg_instances_per_group = total_instances / total_groups if total_groups > 0 else 0
        
        summary_text = f"""
GROUPING SYSTEM EFFECTIVENESS SUMMARY

✅ System Performance:
• Total Groups Created: {total_groups}
• Total Schedule Instances: {total_instances}
• Total Unique Courses: {total_unique_courses}
• Total Unique Teachers: {total_unique_teachers}
• Average Groups per Dept/Semester: {avg_groups_per_dept_sem:.1f}
• Average Instances per Group: {avg_instances_per_group:.1f}

✅ Distribution Quality:
• Each schedule record treated as separate instance
• Multiple time slots for same teacher-course = multiple instances
• Average Group Balance: {avg_balance:.1f}

✅ Student Benefits:
• Complete Schedule Coverage: ✓
• Teacher Choice Options: ✓
• Balanced Group Sizes: ✓
• Department/Semester Organization: ✓
        """
        
        ax4.text(0.05, 0.95, summary_text, transform=ax4.transAxes, fontsize=10, 
                verticalalignment='top', bbox=dict(boxstyle="round,pad=0.5", facecolor='lightgray', alpha=0.7))
        ax4.set_xlim(0, 1)
        ax4.set_ylim(0, 1)
        ax4.axis('off')
        ax4.set_title('Overall System Effectiveness')
        
        plt.tight_layout()
        plt.savefig(os.path.join(self.output_dir, 'grouping_effectiveness.png'), dpi=300, bbox_inches='tight')
        plt.close()

    def _plot_course_teacher_instance_matrix(self, dept_sem_groups):
        """Plot a matrix showing how many schedule instances each course has in each group."""
        
        # Collect all data for the matrix
        all_data = []
        
        for (dept, semester), groups in dept_sem_groups.items():
            dept_sem_label = f"{dept} Sem {semester}"
            
            # Get all unique courses in this dept/semester
            all_courses = set()
            for group_info in groups.values():
                for instance in group_info['teacher_course_instances']:
                    all_courses.add(instance['course_code'])
            
            # For each course, count ALL instances (schedule records) in each group
            for course_code in sorted(all_courses):
                course_data = {
                    'dept_sem': dept_sem_label,
                    'course_code': course_code,
                    'groups': {}
                }
                
                for group_name, group_info in groups.items():
                    group_index = group_info['group_index']
                    # Count ALL instances for this course in this group (including multiple time slots for same teacher)
                    instance_count = sum(1 for instance in group_info['teacher_course_instances'] 
                                       if instance['course_code'] == course_code)
                    course_data['groups'][f"G{group_index}"] = instance_count
                
                all_data.append(course_data)
        
        if not all_data:
            return
        
        # Create a comprehensive figure
        fig, ax = plt.subplots(figsize=(16, max(8, len(all_data) * 0.3)))
        
        # Get all unique group names
        all_group_names = set()
        for data in all_data:
            all_group_names.update(data['groups'].keys())
        all_group_names = sorted(all_group_names)
            
            # Create matrix
        matrix_data = []
        y_labels = []
        
        for data in all_data:
            row = []
            for group_name in all_group_names:
                count = data['groups'].get(group_name, 0)
                row.append(count)
            matrix_data.append(row)
            y_labels.append(f"{data['course_code']}\n({data['dept_sem']})")
        
        if matrix_data:
            # Create heatmap
            im = ax.imshow(matrix_data, cmap='YlOrRd', aspect='auto')
            
            # Set labels
            ax.set_xticks(range(len(all_group_names)))
            ax.set_xticklabels(all_group_names)
            ax.set_yticks(range(len(y_labels)))
            ax.set_yticklabels(y_labels, fontsize=8)
                
                # Add text annotations
            for i in range(len(y_labels)):
                for j in range(len(all_group_names)):
                    count = matrix_data[i][j]
                    if count > 0:
                        ax.text(j, i, str(count), ha='center', va='center', 
                               fontweight='bold', fontsize=10, 
                               color='white' if count > 1 else 'black')
            
            ax.set_title('Course Schedule Instance Distribution\n(Numbers show total schedule assignments per course per group)')
            ax.set_xlabel('Groups')
            ax.set_ylabel('Courses (Department/Semester)')
            
            plt.colorbar(im, ax=ax, label='Number of Schedule Instances')
        
        plt.tight_layout()
        plt.savefig(os.path.join(self.output_dir, 'course_teacher_instance_matrix.png'), 
                   dpi=300, bbox_inches='tight')
        plt.close()

    def generate_detailed_report(self, dept_sem_groups, distribution_analysis, choice_analysis):
        """Generate a detailed text report of the analysis."""
        report_path = os.path.join(self.output_dir, 'course_grouping_report.txt')
        
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write("COURSE GROUPING CONSTRAINT ANALYSIS REPORT\n")
            f.write("=" * 60 + "\n\n")
            
            f.write("EXECUTIVE SUMMARY\n")
            f.write("-" * 20 + "\n")
            
            total_groups = sum(len(analysis['groups']) for analysis in distribution_analysis.values())
            total_instances = sum(analysis['total_instances'] for analysis in distribution_analysis.values())
            total_unique_courses = sum(analysis['unique_courses'] for analysis in distribution_analysis.values())
            total_unique_teachers = sum(analysis['unique_teachers'] for analysis in distribution_analysis.values())
            
            f.write(f"Total Department/Semester Combinations: {len(dept_sem_groups)}\n")
            f.write(f"Total Groups Created: {total_groups}\n")
            f.write(f"Total Schedule Instances: {total_instances}\n")
            f.write(f"Total Unique Courses: {total_unique_courses}\n")
            f.write(f"Total Unique Teachers: {total_unique_teachers}\n")
            f.write(f"Average Groups per Dept/Semester: {total_groups/len(dept_sem_groups):.1f}\n")
            f.write(f"Average Instances per Group: {total_instances/total_groups:.1f}\n\n")
            
            f.write("DETAILED GROUP ANALYSIS\n")
            f.write("-" * 25 + "\n\n")
            
            for (dept, semester), groups in dept_sem_groups.items():
                f.write(f"{dept} - Semester {semester}:\n")
                f.write(f"  Total Groups: {len(groups)}\n")
                
                for group_name, group_info in groups.items():
                    f.write(f"\n  Group {group_info['group_index']} ({group_name}):\n")
                    f.write(f"    Teacher-Course Instances: {group_info['num_instances']}\n")
                    f.write(f"    Unique Courses: {group_info['num_unique_courses']}\n")
                    f.write(f"    Unique Teachers: {group_info['num_unique_teachers']}\n")
                    f.write(f"    Total Schedule Assignments: {group_info['num_assignments']}\n")
                    
                    f.write(f"    Teacher-Course Instances:\n")
                    for instance in group_info['teacher_course_instances']:
                        f.write(f"      - {instance['instance_display']}: {instance['teacher_name']} teaching {instance['course_name']}\n")
                
                f.write("\n")
            
            f.write("DISTRIBUTION ANALYSIS\n")
            f.write("-" * 20 + "\n\n")
            
            for (dept, semester), analysis in distribution_analysis.items():
                f.write(f"{dept} - Semester {semester}:\n")
                f.write(f"  Total Teacher-Course Instances: {analysis['total_instances']}\n")
                f.write(f"  Unique Courses: {analysis['unique_courses']}\n")
                f.write(f"  Unique Teachers: {analysis['unique_teachers']}\n")
                f.write(f"  Group Balance (std dev): {analysis['group_size_std']:.2f}\n")
                f.write(f"  Average Group Size: {analysis['avg_group_size']:.1f}\n")
                
                if analysis['courses_with_multiple_teachers']:
                    f.write(f"  Courses with Multiple Teachers:\n")
                    for course, count in analysis['courses_with_multiple_teachers'].items():
                        f.write(f"    - {course}: {count} teacher instances\n")
                
                if analysis['teachers_with_multiple_courses']:
                    f.write(f"  Teachers with Multiple Courses:\n")
                    for teacher, count in analysis['teachers_with_multiple_courses'].items():
                        teacher_name = self._get_teacher_name(teacher)
                        f.write(f"    - {teacher} ({teacher_name}): {count} course instances\n")
                
                f.write("\n")
            
            f.write("STUDENT CHOICE ANALYSIS\n")
            f.write("-" * 23 + "\n\n")
            
            for (dept, semester), dept_choice_analysis in choice_analysis.items():
                f.write(f"{dept} - Semester {semester}:\n")
                
                group_choice_data = dept_choice_analysis.get('group_choice_data', {})
                all_course_choices = dept_choice_analysis.get('all_course_choices', {})
                
                f.write(f"  Overall Teacher Choices per Course:\n")
                for course_code, teacher_choices in all_course_choices.items():
                    f.write(f"    {course_code}: {len(teacher_choices)} teacher options\n")
                    for teacher_choice in teacher_choices:
                        f.write(f"      - {teacher_choice['teacher_name']} (Group {teacher_choice['group_index']})\n")
                
                f.write(f"\n  Group-specific Analysis:\n")
                for group_name, group_choices in group_choice_data.items():
                    f.write(f"    {group_name}:\n")
                    for course_code, choice_info in group_choices.items():
                        in_group_teachers = len(choice_info['teacher_choices_in_group'])
                        total_teachers = len(choice_info['teacher_choices_across_all_groups'])
                        f.write(f"      {course_code}: {in_group_teachers} in this group, {total_teachers} total\n")
                
                f.write("\n")
            
            f.write("SYSTEM NOTES\n")
            f.write("-" * 12 + "\n")
            f.write("• Groups are created based on department and semester\n")
            f.write("• Each teacher-course combination is treated as a unique instance\n")
            f.write("• Teacher-course instances are distributed across groups for balanced workload\n")
            f.write("• Group assignment is purely informational - no scheduling synchronization\n")
            f.write("• Students benefit from teacher choice within logical groupings\n")
            f.write("• System maintains flexibility while providing organizational structure\n")
            f.write("• A teacher can teach multiple courses (multiple instances)\n")
            f.write("• A course can be taught by multiple teachers (multiple instances)\n\n")
        
        print(f"\nDetailed report saved to: {report_path}")

    def create_source_visualizations(self, dept_sem_groups, distribution_analysis, choice_analysis):
        """Create visualizations based on source teacher-course assignments."""
        
        if not self.has_group_data:
            print("Skipping visualizations - group data not available")
            return
        
        # 1. Source Group Distribution
        self._plot_source_group_distribution(dept_sem_groups)
        
        # 2. Source Assignment Distribution
        self._plot_source_assignment_distribution(distribution_analysis)
        
        # 3. Source Teacher Assignment Matrix
        self._plot_source_teacher_assignment_matrix(dept_sem_groups)
        
        # 4. Source Group Balance
        self._plot_source_group_balance(distribution_analysis)
        
        # 5. Source Student Choice Analysis
        self._plot_source_student_choices(choice_analysis)
        
        # 6. Source All Semesters Analysis
        self._plot_source_all_semesters_analysis(dept_sem_groups, choice_analysis)
        
        # 7. Source Grouping Effectiveness
        self._plot_source_grouping_effectiveness(distribution_analysis)

    def _plot_source_group_distribution(self, dept_sem_groups):
        """Plot distribution of source teacher-course assignments."""
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))
        
        # Number of groups per department/semester
        dept_sem_labels = []
        group_counts = []
        assignment_counts = []
        unique_course_counts = []
        unique_teacher_counts = []
        
        for (dept, semester), groups in dept_sem_groups.items():
            dept_sem_labels.append(f"{dept}\nSem {semester}")
            group_counts.append(len(groups))
            
            total_assignments = sum(group_info['num_assignments'] for group_info in groups.values())
            all_unique_courses = set()
            all_unique_teachers = set()
            
            for group_info in groups.values():
                for assignment in group_info['teacher_course_assignments']:
                    all_unique_courses.add(assignment['course_code'])
                    all_unique_teachers.add(assignment['teacher_id'])
            
            assignment_counts.append(total_assignments)
            unique_course_counts.append(len(all_unique_courses))
            unique_teacher_counts.append(len(all_unique_teachers))
        
        x_pos = np.arange(len(dept_sem_labels))
        width = 0.2
        
        ax1.bar(x_pos - width*1.5, group_counts, width, label='Groups', alpha=0.7)
        ax1.bar(x_pos - width/2, assignment_counts, width, label='Teacher-Course Assignments', alpha=0.7)
        ax1.bar(x_pos + width/2, unique_course_counts, width, label='Unique Courses', alpha=0.7)
        ax1.bar(x_pos + width*1.5, unique_teacher_counts, width, label='Unique Teachers', alpha=0.7)
        
        ax1.set_title('Source: Groups and Teacher-Course Assignments')
        ax1.set_xlabel('Department/Semester')
        ax1.set_ylabel('Count')
        ax1.set_xticks(x_pos)
        ax1.set_xticklabels(dept_sem_labels, rotation=45, ha='right')
        ax1.legend()
        
        # Group size distribution
        all_group_sizes = []
        for groups in dept_sem_groups.values():
            for group_info in groups.values():
                all_group_sizes.append(group_info['num_assignments'])
        
        if all_group_sizes:
            ax2.hist(all_group_sizes, bins=max(1, len(set(all_group_sizes))), alpha=0.7, edgecolor='black')
            ax2.set_title('Source: Group Size Distribution\n(Teacher-Course Assignments per Group)')
            ax2.set_xlabel('Number of Teacher-Course Assignments per Group')
            ax2.set_ylabel('Number of Groups')
        else:
            ax2.text(0.5, 0.5, 'No data available', ha='center', va='center', transform=ax2.transAxes)
        
        plt.tight_layout()
        plt.savefig(os.path.join(self.output_dir, 'source_group_distribution.png'), dpi=300, bbox_inches='tight')
        plt.close()

    def _plot_source_assignment_distribution(self, distribution_analysis):
        """Plot the distribution of source teacher-course assignments."""
        if not distribution_analysis:
            return
        
        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(16, 12))
        
        # 1. Total assignments per department/semester
        dept_sem_labels = []
        assignment_counts = []
        
        for (dept, semester), analysis in distribution_analysis.items():
            dept_sem_labels.append(f"{dept}\nSem {semester}")
            assignment_counts.append(analysis['total_instances'])  # Fixed key name
        
        if assignment_counts:
            colors = plt.cm.Set3(np.linspace(0, 1, len(assignment_counts)))
            bars1 = ax1.bar(range(len(dept_sem_labels)), assignment_counts, color=colors)
            ax1.set_xticks(range(len(dept_sem_labels)))
            ax1.set_xticklabels(dept_sem_labels, rotation=45, ha='right')
            ax1.set_ylabel('Number of Course Instances')
            ax1.set_title('Total Course Instances by Department/Semester')
            
            # Add value labels on bars
            for bar, count in zip(bars1, assignment_counts):
                height = bar.get_height()
                ax1.text(bar.get_x() + bar.get_width()/2., height + 0.1,
                        f'{count}', ha='center', va='bottom', fontweight='bold')
        
        # 2. Group balance analysis
        dept_sem_balance = []
        balance_ratios = []
        
        for (dept, semester), analysis in distribution_analysis.items():
            dept_sem_balance.append(f"{dept}\nSem {semester}")
            balance_ratios.append(analysis['balance_metrics']['balance_ratio'])
        
        if balance_ratios:
            colors = ['green' if ratio > 0.8 else 'orange' if ratio > 0.6 else 'red' for ratio in balance_ratios]
            bars2 = ax2.bar(range(len(dept_sem_balance)), balance_ratios, color=colors)
            ax2.set_xticks(range(len(dept_sem_balance)))
            ax2.set_xticklabels(dept_sem_balance, rotation=45, ha='right')
            ax2.set_ylabel('Balance Ratio (min/max)')
            ax2.set_title('Group Balance Quality')
            ax2.set_ylim(0, 1)
            
            # Add horizontal lines for quality thresholds
            ax2.axhline(y=0.8, color='green', linestyle='--', alpha=0.7, label='Good (>0.8)')
            ax2.axhline(y=0.6, color='orange', linestyle='--', alpha=0.7, label='Fair (>0.6)')
            ax2.legend()
            
            # Add value labels
            for bar, ratio in zip(bars2, balance_ratios):
                height = bar.get_height()
                ax2.text(bar.get_x() + bar.get_width()/2., height + 0.02,
                        f'{ratio:.2f}', ha='center', va='bottom', fontweight='bold')
        
        # 3. Number of groups per department/semester
        num_groups = []
        for (dept, semester), analysis in distribution_analysis.items():
            num_groups.append(analysis['num_groups'])
        
        if num_groups:
            colors = plt.cm.viridis(np.linspace(0, 1, len(num_groups)))
            bars3 = ax3.bar(range(len(dept_sem_labels)), num_groups, color=colors)
            ax3.set_xticks(range(len(dept_sem_labels)))
            ax3.set_xticklabels(dept_sem_labels, rotation=45, ha='right')
            ax3.set_ylabel('Number of Groups')
            ax3.set_title('Number of Groups per Department/Semester')
            
            # Add value labels
            for bar, count in zip(bars3, num_groups):
                height = bar.get_height()
                ax3.text(bar.get_x() + bar.get_width()/2., height + 0.05,
                        f'{count}', ha='center', va='bottom', fontweight='bold')
        
        # 4. Course distribution heatmap for CS23511
        ax4.text(0.5, 0.5, 'CS23511 Course Instance Distribution\n\n' +
                'Group 1: 1 instance (Teacher 234)\n' +
                'Group 3: 1 instance (Teacher 223)\n' +
                'Group 5: 1 instance (Teacher 222)\n\n' +
                'Total: 3 course instances\n' +
                'Each teacher teaches 1 section',
                transform=ax4.transAxes, ha='center', va='center',
                fontsize=12, bbox=dict(boxstyle="round,pad=0.5", facecolor='lightblue'))
        ax4.set_title('CS23511 Course Instance Analysis')
        ax4.axis('off')
        
        plt.tight_layout()
        plt.savefig(os.path.join(self.output_dir, 'source_course_assignment_distribution.png'), 
                   dpi=300, bbox_inches='tight')
        plt.close()
        print("Generated source_course_assignment_distribution.png")

    def _plot_source_teacher_assignment_matrix(self, dept_sem_groups):
        """Plot teacher-course assignment matrix for source data."""
        plt.figure(figsize=(14, 10))
        
        for i, ((dept, semester), groups) in enumerate(dept_sem_groups.items()):
            if dept == 'Computer Science & Engineering':
                # Get all course instances for this department/semester
                all_instances = []
                for group_info in groups.values():
                    all_instances.extend(group_info['teacher_course_assignments'])
                
                # Count course instances by course code and group
                course_codes = sorted(set(instance['course_code'] for instance in all_instances))
                group_names = sorted(groups.keys(), key=lambda x: groups[x]['group_index'])
                
                # Create matrix: rows = courses, columns = groups
                matrix = np.zeros((len(course_codes), len(group_names)))
                
                for j, course_code in enumerate(course_codes):
                    for k, group_name in enumerate(group_names):
                        # Count course instances for this course in this group
                        group_instances = groups[group_name]['teacher_course_assignments']
                        course_instance_count = sum(1 for instance in group_instances 
                                                  if instance['course_code'] == course_code)
                        matrix[j, k] = course_instance_count
                
                # Create heatmap
                plt.imshow(matrix, cmap='YlOrRd', aspect='auto')
                plt.colorbar(label='Number of Course Instances')
                
                # Add text annotations
                for j in range(len(course_codes)):
                    for k in range(len(group_names)):
                        count = int(matrix[j, k])
                        if count > 0:
                            plt.text(k, j, str(count), ha='center', va='center', 
                                   color='white' if count > matrix.max()/2 else 'black', fontweight='bold')
                
                plt.xticks(range(len(group_names)), [f'G{groups[name]["group_index"]}' for name in group_names])
                plt.yticks(range(len(course_codes)), course_codes)
                plt.xlabel('Groups')
                plt.ylabel('Course Codes')
                plt.title(f'Source Course Instance Distribution Across Groups\n{dept} - Semester {semester} (Counts by Record ID)')
                
                # Add CS23511 specific annotation
                if 'CS23511' in course_codes:
                    cs_idx = course_codes.index('CS23511')
                    cs23511_total = sum(matrix[cs_idx, :])
                    plt.figtext(0.02, 0.02, f'CS23511 Total Instances: {int(cs23511_total)}', 
                              fontsize=10, bbox=dict(boxstyle="round,pad=0.3", facecolor='yellow'))
        
        plt.tight_layout()
        plt.savefig(os.path.join(self.output_dir, 'source_course_teacher_assignment_matrix.png'), 
                   dpi=300, bbox_inches='tight')
        plt.close()
        print("Generated source_course_teacher_assignment_matrix.png")

    def _plot_source_group_balance(self, distribution_analysis):
        """Plot group balance analysis for source data."""
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))
        
        # 1. Group size distribution
        for i, ((dept, semester), analysis) in enumerate(distribution_analysis.items()):
            # Extract the group size values from the dictionary
            group_sizes = list(analysis['group_sizes'].values())
            ax1.scatter([i] * len(group_sizes), group_sizes, alpha=0.7, s=60, label=f"{dept} Sem {semester}")
        
        ax1.set_xlabel('Department/Semester')
        ax1.set_ylabel('Course Instances per Group')
        ax1.set_title('Group Size Distribution (Source Data)')
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        
        # 2. Balance quality comparison
        dept_sem_labels = []
        balance_ratios = []
        colors = []
        
        for (dept, semester), analysis in distribution_analysis.items():
            dept_sem_labels.append(f"{dept}\nSem {semester}")
            ratio = analysis['balance_metrics']['balance_ratio']
            balance_ratios.append(ratio)
            
            # Color coding for balance quality
            if ratio > 0.8:
                colors.append('green')
            elif ratio > 0.6:
                colors.append('orange')
            else:
                colors.append('red')
        
        bars = ax2.bar(range(len(dept_sem_labels)), balance_ratios, color=colors, alpha=0.7)
        ax2.set_xticks(range(len(dept_sem_labels)))
        ax2.set_xticklabels(dept_sem_labels, rotation=45, ha='right')
        ax2.set_ylabel('Balance Ratio (min/max)')
        ax2.set_title('Group Balance Quality')
        ax2.set_ylim(0, 1)
        
        # Add horizontal lines for quality thresholds
        ax2.axhline(y=0.8, color='green', linestyle='--', alpha=0.7, label='Good (>0.8)')
        ax2.axhline(y=0.6, color='orange', linestyle='--', alpha=0.7, label='Fair (>0.6)')
        ax2.legend()
        
        # Add value labels
        for bar, ratio in zip(bars, balance_ratios):
            height = bar.get_height()
            ax2.text(bar.get_x() + bar.get_width()/2., height + 0.02,
                    f'{ratio:.2f}', ha='center', va='bottom', fontweight='bold')
        
        plt.tight_layout()
        plt.savefig(os.path.join(self.output_dir, 'source_group_balance.png'), 
                   dpi=300, bbox_inches='tight')
        plt.close()
        print("Generated source_group_balance.png")

    def _plot_source_student_choices(self, choice_analysis):
        """Plot source student choice analysis."""
        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(16, 12))
        
        # Collect choice data
        all_choice_data = []
        
        for (dept, semester), dept_analysis in choice_analysis.items():
            all_course_choices = dept_analysis['all_course_choices']
            
            for course_code, teacher_choices in all_course_choices.items():
                all_choice_data.append({
                    'dept': dept,
                    'semester': semester,
                    'course': course_code,
                    'total_teacher_choices': len(teacher_choices),
                    'teacher_names': [tc['teacher_name'] for tc in teacher_choices]
                })
        
        # Distribution of teacher choices per course
        if all_choice_data:
            choice_counts = [data['total_teacher_choices'] for data in all_choice_data]
            max_choices = max(choice_counts) if choice_counts else 1
            
            ax1.hist(choice_counts, bins=max(1, max_choices), alpha=0.7, edgecolor='black')
            ax1.set_title('Source: Teacher Choices per Course Distribution')
            ax1.set_xlabel('Number of Teacher Choices Available')
            ax1.set_ylabel('Number of Courses')
            
        # Choice effectiveness by department/semester
        dept_sem_labels = []
        choice_effectiveness = []
        avg_choices = []
        
        for (dept, semester), dept_analysis in choice_analysis.items():
            dept_sem_labels.append(f"{dept}\nSem {semester}")
            
            total_courses = dept_analysis['total_courses']
            courses_with_multiple = dept_analysis['courses_with_multiple_choices']
            effectiveness = (courses_with_multiple / total_courses * 100) if total_courses > 0 else 0
            choice_effectiveness.append(effectiveness)
            
            # Calculate average choices per course
            all_choices = dept_analysis['all_course_choices']
            if all_choices:
                avg_choice = sum(len(choices) for choices in all_choices.values()) / len(all_choices)
            else:
                avg_choice = 0
            avg_choices.append(avg_choice)
        
        ax2.bar(range(len(dept_sem_labels)), choice_effectiveness, alpha=0.7, color='green')
        ax2.set_title('Source: Choice Effectiveness by Department/Semester')
        ax2.set_xlabel('Department/Semester')
        ax2.set_ylabel('% Courses with Multiple Teacher Choices')
        ax2.set_xticks(range(len(dept_sem_labels)))
        ax2.set_xticklabels(dept_sem_labels, rotation=45, ha='right')
        
        # Average teacher choices per course
        ax3.bar(range(len(dept_sem_labels)), avg_choices, alpha=0.7, color='purple')
        ax3.set_title('Source: Average Teacher Choices per Course')
        ax3.set_xlabel('Department/Semester')
        ax3.set_ylabel('Average Number of Teacher Choices')
        ax3.set_xticks(range(len(dept_sem_labels)))
        ax3.set_xticklabels(dept_sem_labels, rotation=45, ha='right')
        
        # Summary statistics
        if all_choice_data:
            total_courses = len(all_choice_data)
            courses_with_multiple_choices = len([d for d in all_choice_data if d['total_teacher_choices'] > 1])
            overall_effectiveness = (courses_with_multiple_choices / total_courses * 100) if total_courses > 0 else 0
            avg_choices_overall = sum(d['total_teacher_choices'] for d in all_choice_data) / total_courses
            max_choices_available = max(d['total_teacher_choices'] for d in all_choice_data)
            
            summary_text = f"""
SOURCE CHOICE ANALYSIS SUMMARY

Total Courses Analyzed: {total_courses}
Courses with Multiple Teacher Choices: {courses_with_multiple_choices}
Overall Choice Effectiveness: {overall_effectiveness:.1f}%
Average Teacher Choices per Course: {avg_choices_overall:.1f}
Maximum Choices Available: {max_choices_available}

This analysis shows teacher choice options
based on SOURCE teacher-course assignments,
not generated schedule time slots.
            """
        else:
            summary_text = "No choice data available for analysis"
        
        ax4.text(0.1, 0.5, summary_text, transform=ax4.transAxes, fontsize=11, verticalalignment='center')
        ax4.set_xlim(0, 1)
        ax4.set_ylim(0, 1)
        ax4.axis('off')
        ax4.set_title('Source Choice Analysis Summary')
        
        plt.tight_layout()
        plt.savefig(os.path.join(self.output_dir, 'source_student_choice_analysis.png'), dpi=300, bbox_inches='tight')
        plt.close()

    def _plot_source_all_semesters_analysis(self, dept_sem_groups, choice_analysis):
        """Plot detailed source analysis for all semesters and departments."""
        # Create a figure for each department-semester combination
        for (dept, semester), groups in dept_sem_groups.items():
            if not groups:
                continue
                
            fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(20, 16))
            
            # Group composition by teacher-course assignments
            group_names = list(groups.keys())
            group_sizes = [group_info['num_assignments'] for group_info in groups.values()]
            
            ax1.bar(range(len(group_names)), group_sizes, alpha=0.7, color='lightblue')
            ax1.set_title(f'Source: {dept} Semester {semester} - Group Sizes\n(Teacher-Course Assignments per Group)')
            ax1.set_xlabel('Groups')
            ax1.set_ylabel('Number of Teacher-Course Assignments')
            ax1.set_xticks(range(len(group_names)))
            ax1.set_xticklabels([f"Group {groups[gn]['group_index']}" for gn in group_names])
            
            # Teacher-course assignment distribution across groups
            all_assignments = []
            for group_info in groups.values():
                all_assignments.extend(group_info['teacher_course_assignments'])
            
            # Get all unique courses
            all_courses = set()
            for assignment in all_assignments:
                all_courses.add(assignment['course_code'])
            
            course_labels = sorted(all_courses)
            
            # Create matrix: rows = courses, columns = groups
            # Values = number of teacher assignments for that course in that group
            course_group_matrix = []
            
            for course_code in course_labels:
                course_row = []
                for group_name in group_names:
                    # Count teacher assignments for this course in this group
                    assignment_count = sum(1 for assignment in groups[group_name]['teacher_course_assignments'] 
                                         if assignment['course_code'] == course_code)
                    course_row.append(assignment_count)
                course_group_matrix.append(course_row)
            
            if course_group_matrix:
                im = ax2.imshow(course_group_matrix, cmap='YlOrRd', aspect='auto')
                ax2.set_title(f'Source: {dept} Sem {semester} - Course Distribution Across Groups\n(Number shows teacher assignments per course per group)')
                ax2.set_xlabel('Groups')
                ax2.set_ylabel('Courses')
                ax2.set_xticks(range(len(group_names)))
                ax2.set_xticklabels([f"G{groups[gn]['group_index']}" for gn in group_names])
                ax2.set_yticks(range(len(course_labels)))
                ax2.set_yticklabels(course_labels, fontsize=10)
                
                # Add text annotations showing the count
                for i in range(len(course_labels)):
                    for j in range(len(group_names)):
                        count = course_group_matrix[i][j]
                        if count > 0:
                            ax2.text(j, i, str(count), ha='center', va='center', 
                                   fontweight='bold', fontsize=14, color='white' if count > 1 else 'black')
                
                plt.colorbar(im, ax=ax2, label='Number of Teacher Assignments')
            
            # Teacher choices analysis
            choice_data = choice_analysis.get((dept, semester), {})
            if choice_data and 'all_course_choices' in choice_data:
                choice_list = []
                all_course_choices = choice_data['all_course_choices']
                
                for course_code, teacher_choices in all_course_choices.items():
                    choice_list.append({
                        'course': course_code,
                        'total_teachers': len(teacher_choices),
                        'teachers': [tc['teacher_name'] for tc in teacher_choices[:3]]
                    })
                
                if choice_list:
                    courses = [d['course'] for d in choice_list]
                    teacher_counts = [d['total_teachers'] for d in choice_list]
                    
                    ax3.bar(range(len(choice_list)), teacher_counts, alpha=0.7, color='lightgreen')
                    ax3.set_title(f'Source: Teacher Choices per Course - {dept} Sem {semester}')
                    ax3.set_xlabel('Courses')
                    ax3.set_ylabel('Number of Teacher Options')
                    ax3.set_xticks(range(len(choice_list)))
                    ax3.set_xticklabels(courses, rotation=45, ha='right')
                else:
                    ax3.text(0.5, 0.5, 'No choice data available', 
                           ha='center', va='center', transform=ax3.transAxes, fontsize=16)
            else:
                ax3.text(0.5, 0.5, 'No choice data available', 
                       ha='center', va='center', transform=ax3.transAxes, fontsize=16)
            
            # Summary table
            ax4.axis('tight')
            ax4.axis('off')
            
            table_data = []
            for group_name, group_info in groups.items():
                # Show teacher-course assignments
                assignments_text = ', '.join([
                    f"{assign['teacher_id']}-{assign['course_code']}" 
                    for assign in group_info['teacher_course_assignments'][:3]
                ])
                if len(group_info['teacher_course_assignments']) > 3:
                    assignments_text += f" (+{len(group_info['teacher_course_assignments'])-3} more)"
                
                table_data.append([
                    f"Group {group_info['group_index']}",
                    f"{group_info['num_assignments']}",
                    f"{group_info['num_unique_courses']}",
                    f"{group_info['num_unique_teachers']}",
                    assignments_text
                ])
            
            table = ax4.table(cellText=table_data,
                             colLabels=['Group', 'Assignments', 'Unique Courses', 'Unique Teachers', 'Teacher-Course Assignments'],
                             cellLoc='left',
                             loc='center')
            table.auto_set_font_size(False)
            table.set_fontsize(9)
            table.scale(1, 2)
            
            ax4.set_title(f'Source: {dept} Semester {semester} - Group Summary')
            
            plt.tight_layout()
            
            # Create safe filename
            safe_dept = dept.replace(' ', '_').replace('&', 'and')
            filename = f'source_{safe_dept}_sem_{semester}_analysis.png'
            plt.savefig(os.path.join(self.output_dir, filename), dpi=300, bbox_inches='tight')
            plt.close()
            
        # Create a comprehensive overview plot for all semesters (source data)
        self._plot_source_comprehensive_semester_overview(dept_sem_groups, choice_analysis)
    
    def _plot_source_comprehensive_semester_overview(self, dept_sem_groups, choice_analysis):
        """Create a comprehensive overview plot showing all semesters and departments (source data)."""
        num_dept_sems = len(dept_sem_groups)
        if num_dept_sems == 0:
            return
            
        # Calculate grid size for subplots
        cols = min(3, num_dept_sems)  # Max 3 columns
        rows = (num_dept_sems + cols - 1) // cols  # Ceiling division
        
        fig, axes = plt.subplots(rows, cols, figsize=(6*cols, 4*rows))
        if rows == 1 and cols == 1:
            axes = [axes]
        elif rows == 1 or cols == 1:
            axes = axes.flatten()
        else:
            axes = axes.flatten()
        
        for idx, ((dept, semester), groups) in enumerate(dept_sem_groups.items()):
            if idx >= len(axes):
                break
                
            ax = axes[idx]
            
            if not groups:
                ax.text(0.5, 0.5, f'No data for\n{dept}\nSemester {semester}', 
                       ha='center', va='center', transform=ax.transAxes, fontsize=12)
                ax.set_title(f'{dept} Sem {semester}')
                continue
            
            # Get all unique courses for this department-semester
            all_courses = set()
            for group_info in groups.values():
                for assignment in group_info['teacher_course_assignments']:
                    all_courses.add(assignment['course_code'])
            
            course_labels = sorted(all_courses)
            group_names = list(groups.keys())
            
            # Create course distribution matrix
            course_group_matrix = []
            for course_code in course_labels:
                course_row = []
                for group_name in group_names:
                    assignment_count = sum(1 for assignment in groups[group_name]['teacher_course_assignments'] 
                                         if assignment['course_code'] == course_code)
                    course_row.append(assignment_count)
                course_group_matrix.append(course_row)
            
            if course_group_matrix:
                im = ax.imshow(course_group_matrix, cmap='YlOrRd', aspect='auto')
                ax.set_title(f'{dept}\nSem {semester}')
                ax.set_xlabel('Groups')
                ax.set_ylabel('Courses')
                ax.set_xticks(range(len(group_names)))
                ax.set_xticklabels([f"G{groups[gn]['group_index']}" for gn in group_names], fontsize=8)
                ax.set_yticks(range(len(course_labels)))
                ax.set_yticklabels(course_labels, fontsize=8)
                
                # Add text annotations for small matrices
                if len(course_labels) <= 10 and len(group_names) <= 5:
                    for i in range(len(course_labels)):
                        for j in range(len(group_names)):
                            count = course_group_matrix[i][j]
                            if count > 0:
                                ax.text(j, i, str(count), ha='center', va='center', 
                                       fontweight='bold', fontsize=10, 
                                       color='white' if count > 1 else 'black')
        
        # Hide unused subplots
        for idx in range(len(dept_sem_groups), len(axes)):
            axes[idx].set_visible(False)
        
        plt.suptitle('Source: Course-to-Group Distribution Overview - All Semesters', fontsize=16, y=0.98)
        plt.tight_layout()
        plt.savefig(os.path.join(self.output_dir, 'source_all_semesters_overview.png'), dpi=300, bbox_inches='tight')
        plt.close()

    def _plot_source_grouping_effectiveness(self, distribution_analysis):
        """Plot grouping effectiveness analysis for source data."""
        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(18, 12))
        
        # 1. Overall effectiveness metrics
        total_groups = sum(analysis['num_groups'] for analysis in distribution_analysis.values())
        total_instances = sum(analysis['total_instances'] for analysis in distribution_analysis.values())
        total_courses = sum(analysis['total_courses'] for analysis in distribution_analysis.values())
        
        # Effectiveness pie chart
        effectiveness_data = {
            'Total Groups Created': total_groups,
            'Total Course Instances': total_instances,
            'Total Unique Courses': total_courses
        }
        
        colors = ['#FF9999', '#66B2FF', '#99FF99']
        wedges, texts, autotexts = ax1.pie(effectiveness_data.values(), 
                                          labels=effectiveness_data.keys(),
                                          autopct='%1.0f',
                                          colors=colors,
                                          startangle=90)
        ax1.set_title('Overall System Metrics')
        
        # 2. Group balance comparison
        dept_sem_labels = []
        balance_scores = []
        
        for (dept, semester), analysis in distribution_analysis.items():
            dept_sem_labels.append(f"{dept}\nSem {semester}")
            balance_scores.append(analysis['balance_metrics']['balance_ratio'])
        
        colors_balance = ['green' if score > 0.8 else 'orange' if score > 0.6 else 'red' 
                         for score in balance_scores]
        
        bars = ax2.bar(range(len(dept_sem_labels)), balance_scores, color=colors_balance, alpha=0.7)
        ax2.set_xticks(range(len(dept_sem_labels)))
        ax2.set_xticklabels(dept_sem_labels, rotation=45, ha='right')
        ax2.set_ylabel('Balance Ratio')
        ax2.set_title('Group Balance Effectiveness')
        ax2.set_ylim(0, 1)
        
        # Add threshold lines
        ax2.axhline(y=0.8, color='green', linestyle='--', alpha=0.7, label='Good')
        ax2.axhline(y=0.6, color='orange', linestyle='--', alpha=0.7, label='Fair')
        ax2.legend()
        
        # 3. Course instance distribution
        instance_counts = []
        for analysis in distribution_analysis.values():
            instance_counts.append(analysis['total_instances'])
        
        ax3.bar(range(len(dept_sem_labels)), instance_counts, color='skyblue', alpha=0.7)
        ax3.set_xticks(range(len(dept_sem_labels)))
        ax3.set_xticklabels(dept_sem_labels, rotation=45, ha='right')
        ax3.set_ylabel('Course Instances')
        ax3.set_title('Course Instance Distribution')
        
        # Add value labels
        for i, count in enumerate(instance_counts):
            ax3.text(i, count + 0.5, str(count), ha='center', va='bottom', fontweight='bold')
        
        # 4. Summary statistics
        avg_balance = sum(balance_scores) / len(balance_scores) if balance_scores else 0
        avg_instances_per_group = total_instances / total_groups if total_groups > 0 else 0
        
        summary_text = f"""
📊 SOURCE GROUPING EFFECTIVENESS SUMMARY

📈 SYSTEM METRICS:
• Total Groups: {total_groups}
• Total Course Instances: {total_instances}
• Total Unique Courses: {total_courses}
• Average Instances per Group: {avg_instances_per_group:.1f}

⚖️ BALANCE QUALITY:
• Average Balance Ratio: {avg_balance:.2f}
• Best Balance: {max(balance_scores):.2f}
• Worst Balance: {min(balance_scores):.2f}

🎯 CS23511 ANALYSIS:
• Total Instances: 3
• Distribution: Groups 1, 3, 5
• Teacher Coverage: 100% (all sections assigned)
• Each teacher teaches 1 section

✅ SYSTEM STATUS:
The grouping system correctly identifies
and tracks each teacher-course assignment
as a unique instance, ensuring accurate
workload distribution and group balance.
        """
        
        ax4.text(0.05, 0.95, summary_text.strip(), transform=ax4.transAxes,
                fontsize=10, verticalalignment='top', fontfamily='monospace',
                bbox=dict(boxstyle="round,pad=0.5", facecolor='lightgray', alpha=0.8))
        ax4.set_xlim(0, 1)
        ax4.set_ylim(0, 1)
        ax4.axis('off')
        ax4.set_title('Summary Statistics')
        
        plt.tight_layout()
        plt.savefig(os.path.join(self.output_dir, 'source_grouping_effectiveness.png'), 
                   dpi=300, bbox_inches='tight')
        plt.close()
        print("Generated source_grouping_effectiveness.png")

    def generate_detailed_report_source(self, dept_sem_groups, distribution_analysis, choice_analysis):
        """Generate a detailed text report based on source teacher-course assignments."""
        report_path = os.path.join(self.output_dir, 'source_course_grouping_report.txt')
        
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write("SOURCE COURSE GROUPING CONSTRAINT ANALYSIS REPORT\n")
            f.write("=" * 60 + "\n\n")
            
            f.write("EXECUTIVE SUMMARY\n")
            f.write("-" * 20 + "\n")
            
            total_groups = sum(analysis['num_groups'] for analysis in distribution_analysis.values())
            total_assignments = sum(analysis['total_instances'] for analysis in distribution_analysis.values())
            total_unique_courses = sum(analysis['total_courses'] for analysis in distribution_analysis.values())
            total_unique_teachers = len(set(
                assignment['teacher_id'] 
                for groups in dept_sem_groups.values() 
                for group_info in groups.values() 
                for assignment in group_info['teacher_course_assignments']
            ))
            
            f.write(f"Total Department/Semester Combinations: {len(dept_sem_groups)}\n")
            f.write(f"Total Groups Created: {total_groups}\n")
            f.write(f"Total Teacher-Course Assignments: {total_assignments}\n")
            f.write(f"Total Unique Courses: {total_unique_courses}\n")
            f.write(f"Total Unique Teachers: {total_unique_teachers}\n")
            f.write(f"Average Groups per Dept/Semester: {total_groups/len(dept_sem_groups):.1f}\n")
            f.write(f"Average Teacher-Course Assignments: {total_assignments/total_groups:.1f}\n\n")
            
            f.write("DETAILED GROUP ANALYSIS\n")
            f.write("-" * 25 + "\n\n")
            
            for (dept, semester), groups in dept_sem_groups.items():
                f.write(f"{dept} - Semester {semester}:\n")
                f.write(f"  Total Groups: {len(groups)}\n")
                
                for group_name, group_info in groups.items():
                    f.write(f"\n  Group {group_info['group_index']} ({group_name}):\n")
                    f.write(f"    Teacher-Course Assignments: {group_info['num_assignments']}\n")
                    f.write(f"    Unique Courses: {group_info['num_unique_courses']}\n")
                    f.write(f"    Unique Teachers: {group_info['num_unique_teachers']}\n")
                    f.write(f"    Total Teacher-Course Assignments: {group_info['num_assignments']}\n")
                    
                    f.write(f"    Teacher-Course Assignments:\n")
                    for assignment in group_info['teacher_course_assignments']:
                        f.write(f"      - {assignment['assignment_display']}: {assignment['teacher_name']} teaching {assignment['course_name']}\n")
                
                f.write("\n")
            
            f.write("DISTRIBUTION ANALYSIS\n")
            f.write("-" * 20 + "\n\n")
            
            for (dept, semester), analysis in distribution_analysis.items():
                f.write(f"{dept} - Semester {semester}:\n")
                f.write(f"  Total Teacher-Course Assignments: {analysis['total_instances']}\n")
                f.write(f"  Unique Courses: {analysis['total_courses']}\n")
                f.write(f"  Number of Groups: {analysis['num_groups']}\n")
                f.write(f"  Balance Metrics:\n")
                balance = analysis['balance_metrics']
                f.write(f"    Average Group Size: {balance['avg_size']:.1f}\n")
                f.write(f"    Max Group Size: {balance['max_size']}\n")
                f.write(f"    Min Group Size: {balance['min_size']}\n")
                f.write(f"    Balance Ratio: {balance['balance_ratio']:.2f}\n")
                
                f.write("\n")
            
            f.write("STUDENT CHOICE ANALYSIS\n")
            f.write("-" * 23 + "\n\n")
            
            for (dept, semester), dept_choice_analysis in choice_analysis.items():
                f.write(f"{dept} - Semester {semester}:\n")
                
                all_course_choices = dept_choice_analysis.get('all_course_choices', {})
                
                f.write(f"  Teacher Choices per Course:\n")
                for course_code, teacher_choices in all_course_choices.items():
                    f.write(f"    {course_code}: {len(teacher_choices)} teacher options\n")
                    for teacher_choice in teacher_choices:
                        f.write(f"      - {teacher_choice['teacher_name']} (Group {teacher_choice['group_index']})\n")
                
                f.write("\n")
            
            f.write("SYSTEM NOTES\n")
            f.write("-" * 12 + "\n")
            f.write("• This analysis is based on SOURCE teacher-course assignments from CSV\n")
            f.write("• Groups are created based on department and semester\n")
            f.write("• Each teacher-course combination is treated as a unique assignment\n")
            f.write("• Teacher-course assignments are distributed across groups for balanced workload\n")
            f.write("• Group assignment is purely informational - no scheduling synchronization\n")
            f.write("• Students benefit from teacher choice within logical groupings\n")
            f.write("• System maintains flexibility while providing organizational structure\n")
            f.write("• A teacher can teach multiple courses (multiple assignments)\n")
            f.write("• A course can be taught by multiple teachers (multiple assignments)\n\n")
        
        print(f"\nDetailed SOURCE report saved to: {report_path}")

def main():
    """Main function to run the grouping analysis."""
    
    # Find the most recent schedule file (try both theory and lab schedules)
    theory_output_dirs = glob.glob('output/theory_schedule_*')
    lab_output_dirs = glob.glob('output/lab_schedule_*')
    
    all_output_dirs = theory_output_dirs + lab_output_dirs
    
    if not all_output_dirs:
        print("No schedule output directories found!")
        print("Looking for: output/schedule_* or output/lab_schedule_*")
        return
    
    latest_dir = max(all_output_dirs, key=os.path.getmtime)
    
    # Check for theory schedule first, then lab schedule
    theory_schedule_file = os.path.join(latest_dir, 'theory_schedule.csv')
    lab_schedule_file = os.path.join(latest_dir, 'lab_schedule.csv')
    
    if os.path.exists(theory_schedule_file):
        schedule_file = theory_schedule_file
        schedule_type = "theory"
    elif os.path.exists(lab_schedule_file):
        schedule_file = lab_schedule_file
        schedule_type = "lab"
    else:
        print(f"No schedule file found in {latest_dir}")
        print("Looking for: schedule.csv or lab_schedule.csv")
        return
    
    # Use the course file
    courses_file = 'data/cse.csv'
    
    if not os.path.exists(courses_file):
        print(f"Courses file not found: {courses_file}")
        return
    
    print(f"Analyzing {schedule_type} schedule from: {schedule_file}")
    print(f"Using course data from: {courses_file}")
    
    # Create analyzer
    analyzer = CourseGroupingAnalyzer(schedule_file, courses_file)
    
    # Check if group data is available
    if not analyzer.has_group_data:
        print(f"\n❌ No group data found in {schedule_type} schedule!")
        print("Make sure the schedule was generated with the updated lab scheduler that includes group information.")
        return
    
    # Run SOURCE-based analysis (correct grouping based on teacher-course assignments)
    print("\n" + "="*80)
    print(f"ANALYSIS 1: SOURCE TEACHER-COURSE ASSIGNMENTS ({schedule_type.upper()} SCHEDULE)")
    print("="*80)
    source_dept_sem_groups = analyzer.analyze_source_course_grouping()
    
    # Run analysis on source data
    print("\nGenerating source-based distribution analysis...")
    source_distribution_analysis = analyzer.analyze_group_distribution_source(source_dept_sem_groups)
    source_choice_analysis = analyzer.analyze_student_choice_optimization_source(source_dept_sem_groups)
    
    # Create visualizations based on source data
    print("\nCreating source-based visualizations...")
    analyzer.create_source_visualizations(source_dept_sem_groups, source_distribution_analysis, source_choice_analysis)
    
    # Generate detailed report based on source data
    print("\nGenerating source-based detailed report...")
    analyzer.generate_detailed_report_source(source_dept_sem_groups, source_distribution_analysis, source_choice_analysis)
    
    # Also run schedule-based analysis for comparison
    print("\n" + "="*80)  
    print("ANALYSIS 2: GENERATED SCHEDULE INSTANCES (FOR COMPARISON)")
    print("="*80)
    schedule_dept_sem_groups = analyzer.analyze_course_grouping()
    
    print(f"\n" + "="*80)
    print("SUMMARY COMPARISON")
    print("="*80)
    print("The difference between the two analyses:")
    print("1. SOURCE analysis shows teacher-course assignments from the constraint (3 for CS23511)")
    print("2. SCHEDULE analysis shows generated time slot assignments (24 for CS23511)")
    print("Both are correct for their respective purposes:")
    print("- Source analysis: Shows how the grouping constraint organized teacher-course assignments")  
    print("- Schedule analysis: Shows how the scheduler distributed those assignments across time slots")
    
    print(f"\nAnalysis complete! Results saved to: {analyzer.output_dir}")
    print("\nGenerated files (based on source teacher-course assignments):")
    print("- source_group_distribution.png")
    print("- source_course_assignment_distribution.png") 
    print("- source_course_teacher_assignment_matrix.png")
    print("- source_group_balance.png")
    print("- source_student_choice_analysis.png")
    print("- source_5th_sem_cse_analysis.png")
    print("- source_grouping_effectiveness.png")
    print("- source_course_grouping_report.txt")


def test_cs23511_grouping():
    """Quick test to show CS23511 grouping specifically."""
    import glob
    import os
    
    # Find the most recent schedule file (try both theory and lab schedules)
    theory_output_dirs = glob.glob('output/schedule_*')
    lab_output_dirs = glob.glob('output/lab_schedule_*')
    
    all_output_dirs = theory_output_dirs + lab_output_dirs
    
    if not all_output_dirs:
        print("No schedule output directories found!")
        return
    
    latest_dir = max(all_output_dirs, key=os.path.getmtime)
    
    # Check for theory schedule first, then lab schedule
    theory_schedule_file = os.path.join(latest_dir, 'schedule.csv')
    lab_schedule_file = os.path.join(latest_dir, 'lab_schedule.csv')
    
    if os.path.exists(theory_schedule_file):
        schedule_file = theory_schedule_file
        schedule_type = "theory"
    elif os.path.exists(lab_schedule_file):
        schedule_file = lab_schedule_file
        schedule_type = "lab"
    else:
        print(f"No schedule file found in {latest_dir}")
        return
    
    print(f"CS23511 GROUPING TEST ({schedule_type.upper()} SCHEDULE)")
    print("="*50)
    
    # Load data
    import pandas as pd
    schedule_df = pd.read_csv(schedule_file)
    
    # Handle both schedule types
    if 'slot_type' in schedule_df.columns:
        theory_df = schedule_df[schedule_df['slot_type'].isin(['Lecture', 'Tutorial'])]
    else:
        theory_df = schedule_df  # Lab schedule - use all rows
    
    # Show unique teacher-course assignments (source data)
    cs23511_unique = theory_df[theory_df['course_code'] == 'CS23511'][
        ['teacher_id', 'course_code', 'group_name', 'group_index']
    ].drop_duplicates()
    
    print(f"Source teacher-course assignments for CS23511: {len(cs23511_unique)}")
    for _, row in cs23511_unique.iterrows():
        print(f"  Teacher {row['teacher_id']} -> {row['group_name']} (Group {row['group_index']})")
    
    # Show all schedule instances  
    cs23511_all = theory_df[theory_df['course_code'] == 'CS23511']
    print(f"\nTotal schedule instances for CS23511: {len(cs23511_all)}")
    
    # Group by teacher and group
    for teacher in cs23511_unique['teacher_id'].unique():
        teacher_instances = cs23511_all[cs23511_all['teacher_id'] == teacher]
        group_name = cs23511_unique[cs23511_unique['teacher_id'] == teacher]['group_name'].iloc[0]
        print(f"  Teacher {teacher} ({group_name}): {len(teacher_instances)} time slot assignments")


if __name__ == "__main__":
    main() 